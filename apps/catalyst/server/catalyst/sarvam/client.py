"""HTTP client and result parser for the Sarvam Document Intelligence API.

The client sends page images to the Digitise job endpoint, waits for the job,
downloads the result archive and turns it into text blocks with normalized
bounding boxes.

API reference: https://docs.sarvam.ai/api/api-guides-tutorials/document-intelligence/overview

The public documentation does not state the field names of the Digitise
JSON output. A real response (checked 2026-10) has this shape:

    <folder>/pages.json: {"pages": [{"page_num": 1, "image_width": 1191,
        "image_height": 1684, "blocks": [{"layout_tag": "paragraph",
        "text": "...", "confidence": 0.88, "reading_order": 1,
        "bbox_norm": [x0, y0, x1, y1],
        "coordinates": {"x1": .., "y1": .., "x2": .., "y2": ..}}]}]}

The parser reads that shape first. It also accepts other common spellings of
a box (corner lists, point polygons, x/y/width/height) in pixels or in
normalized units, in case the format changes.
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
import time
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import requests
import urllib3
from PIL.Image import Image

_log = logging.getLogger(__name__)

TERMINAL_STATES = frozenset({"completed", "partially_completed", "failed", "rejected"})
SUCCESS_STATES = frozenset({"completed", "partially_completed"})

# Sarvam limits a Digitise job to 10 pages.
MAX_PAGES_PER_JOB = 10

# Block tags that carry no text for OCR.
_NON_TEXT_TAGS = frozenset({"image", "figure", "picture", "graphic", "logo"})

_PAGE_FILE_RE = re.compile(r"page[_-]?0*(\d+)\.json$", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ROW_END_RE = re.compile(
    r"</tr\s*>|<br\s*/?>|</p\s*>|</li\s*>|</h\d\s*>", re.IGNORECASE
)
_CELL_END_RE = re.compile(r"</t[dh]\s*>", re.IGNORECASE)
_MD_TABLE_RULE_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_TABLE_HTML_RE = re.compile(r"<table[\s>]", re.IGNORECASE)
_TEXT_KEYS = ("text", "content", "markdown", "md", "html", "value")


class SarvamApiError(RuntimeError):
    """The Sarvam API returned an error or the job did not finish."""


@dataclass(frozen=True)
class SarvamBlock:
    """One text block of a digitised page.

    Attributes:
        lines: The text lines of the block, top to bottom.
        bbox: (left, top, right, bottom), normalized to 0..1 of the page
            image, with the origin at the top-left corner.
        tag: The block type that Sarvam reports (for example ``paragraph``).
        confidence: The confidence that Sarvam reports, or 1.0.
        html: For a table block, the HTML ``<table>`` that Sarvam returns,
            with its merged cells (``rowspan``, ``colspan``). ``lines`` holds
            the same text with one line per row.
    """

    lines: list[str]
    bbox: tuple[float, float, float, float]
    tag: str | None = None
    confidence: float = 1.0
    html: str | None = None


@dataclass
class SarvamPageResult:
    """The blocks of one page. ``ok`` is False when Sarvam did not process it."""

    blocks: list[SarvamBlock] = field(default_factory=list)
    ok: bool = True


@dataclass
class DigitiseResult:
    """The pages of one Digitise job and the number of pages Sarvam bills for it.

    ``billed_pages`` is ``usage.pages_processed`` of the job status, or the
    number of page images sent when the status has no usage.
    """

    pages: list[SarvamPageResult]
    billed_pages: int


@dataclass
class SarvamDocAiClient:
    """A minimal synchronous client for the Digitise job workflow."""

    api_key: str
    base_url: str = "https://api.sarvam.ai"
    request_timeout_seconds: float = 120.0
    poll_interval_seconds: float = 2.0
    job_timeout_seconds: float = 900.0
    # Retries after "busy" answers (429, 502, 503).
    max_retries: int = 3
    # Retries after network failures (DNS, refused or dropped connection). With
    # `network_wait` they bridge an outage of about two and a half minutes.
    network_retries: int = 8
    session: requests.Session = field(default_factory=requests.Session)

    def digitise_pages(
        self,
        images: Sequence[Image],
        *,
        language: str | None,
        model: str | None = None,
        content_type: str | None = None,
    ) -> DigitiseResult:
        """Digitise up to ``MAX_PAGES_PER_JOB`` page images in one job."""
        if not images:
            return DigitiseResult(pages=[], billed_pages=0)
        if len(images) > MAX_PAGES_PER_JOB:
            raise ValueError(
                f"A Sarvam job accepts at most {MAX_PAGES_PER_JOB} pages, got {len(images)}."
            )

        started = time.monotonic()
        archive = _zip_page_images(images)
        job_id = self._submit(
            archive, language=language, model=model, content_type=content_type
        )
        status, usage = self._wait(job_id)
        if status not in SUCCESS_STATES:
            raise SarvamApiError(f"Sarvam job {job_id} ended with status {status!r}.")
        if status == "partially_completed":
            _log.warning("Sarvam job %s completed only partially.", job_id)

        output = self._download(job_id)
        _log.info(
            "Sarvam job %s: %d pages in %.1f s (%.1f s per page)",
            job_id, len(images), time.monotonic() - started,
            (time.monotonic() - started) / len(images),
        )  # fmt: skip
        processed = usage.get("pages_processed")
        return DigitiseResult(
            pages=parse_digitise_archive(
                output, image_sizes=[image.size for image in images]
            ),
            billed_pages=processed if isinstance(processed, int) else len(images),
        )

    # ------------------------------------------------------------------ HTTP
    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _headers(self) -> dict[str, str]:
        return {"api-subscription-key": self.api_key}

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        delay = 1.0
        network_failures = busy = 0
        while True:
            try:
                response = self.session.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    timeout=self.request_timeout_seconds,
                    **kwargs,
                )
            except requests.RequestException as exc:
                network_failures += 1
                if network_failures <= self.network_retries and is_retryable(
                    exc, method
                ):
                    wait = network_wait(network_failures)
                    _log.warning(
                        "Sarvam not reachable (%s); retry %d of %d in %.0f s.",
                        type(exc).__name__, network_failures, self.network_retries, wait,
                    )  # fmt: skip
                    time.sleep(wait)
                    continue
                raise SarvamApiError(network_error_message(exc, self.base_url)) from exc
            if response.status_code in (429, 502, 503) and busy < self.max_retries:
                busy += 1
                retry_after = response.headers.get("Retry-After")
                wait = (
                    min(float(retry_after), _MAX_WAIT_SECONDS)
                    if retry_after and retry_after.isdigit()
                    else delay
                )
                _log.info(
                    "Sarvam returned %s; retry in %.1fs.", response.status_code, wait
                )
                time.sleep(wait)
                delay *= 2
                continue
            if response.status_code >= 400:
                raise SarvamApiError(_error_message(response))
            return response

    def _submit(
        self,
        archive: bytes,
        *,
        language: str | None,
        model: str | None,
        content_type: str | None,
    ) -> str:
        data = {"output_format": "json"}
        if language:
            data["language"] = language
        if model:
            data["model"] = model
        if content_type:
            data["content_type"] = content_type
        response = self._request(
            "POST",
            "/doc-ai/v1/job/digitise",
            files={"file": ("pages.zip", archive, "application/zip")},
            data=data,
        )
        job_id = response.json().get("job_id")
        if not job_id:
            raise SarvamApiError(f"Sarvam returned no job_id: {response.text[:300]}")
        return str(job_id)

    def _wait(self, job_id: str) -> tuple[str, Mapping[str, Any]]:
        """Poll the job until it ends. Return its status and its ``usage`` object."""
        deadline = time.monotonic() + self.job_timeout_seconds
        while True:
            body = self._request("GET", f"/doc-ai/v1/job/{job_id}/status").json()
            status = str(body.get("status", "")).lower()
            if status in TERMINAL_STATES:
                usage = body.get("usage")
                return status, usage if isinstance(usage, Mapping) else {}
            if time.monotonic() > deadline:
                raise SarvamApiError(
                    f"Sarvam job {job_id} did not finish in {self.job_timeout_seconds}s."
                )
            time.sleep(self.poll_interval_seconds)

    def _download(self, job_id: str) -> bytes:
        target = self._request("GET", f"/doc-ai/v1/job/{job_id}/download-url").json()
        method = str(target.get("method") or "GET")
        failures = 0
        while True:
            try:
                response = self.session.request(
                    method,
                    target["url"],
                    headers=target.get("headers") or {},
                    timeout=self.request_timeout_seconds,
                )
                break
            except requests.RequestException as exc:
                failures += 1
                if failures <= self.network_retries and is_retryable(exc, method):
                    time.sleep(network_wait(failures))
                    continue
                raise SarvamApiError(network_error_message(exc, target["url"])) from exc
        if response.status_code >= 400:
            raise SarvamApiError(_error_message(response))
        return response.content


_MAX_WAIT_SECONDS = 30.0


def network_wait(failures: int) -> float:
    """Seconds to wait after the n-th network failure: 2, 4, 8, 16, then 30."""
    return min(2.0**failures, _MAX_WAIT_SECONDS)


def _never_sent(exc: requests.RequestException) -> bool:
    """True when the request did not reach the server: DNS or connect failure."""
    if isinstance(exc, requests.ConnectTimeout):
        return True
    if not isinstance(exc, requests.ConnectionError):
        return False
    reason = exc.args[0] if exc.args else None
    # requests wraps urllib3's MaxRetryError; its reason is the first failure.
    if isinstance(reason, urllib3.exceptions.MaxRetryError):
        reason = reason.reason
    return isinstance(reason, urllib3.exceptions.NewConnectionError)


def is_retryable(exc: requests.RequestException, method: str) -> bool:
    """A network error that is safe to retry.

    A GET is always safe. A POST is retried only when it never reached the
    server, so a Digitise job is not created (and billed) twice.
    """
    if method.upper() == "GET":
        return isinstance(exc, requests.ConnectionError | requests.Timeout)
    return _never_sent(exc)


def network_error_message(exc: requests.RequestException, base_url: str) -> str:
    host = urlsplit(base_url).hostname or base_url
    if _never_sent(exc):
        return (
            f"Cannot reach Sarvam ({host}): the DNS lookup or the connection failed. "
            f"Check the internet connection and try again. ({type(exc).__name__})"
        )
    return f"Sarvam request to {host} failed: {type(exc).__name__}: {exc}"


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"Sarvam HTTP {response.status_code}: {response.text[:300]}"
    if isinstance(body, Mapping):
        detail = body.get("detail") or body.get("title") or body.get("message")
        if isinstance(detail, Mapping):
            detail = detail.get("message") or json.dumps(detail)
        return f"Sarvam HTTP {response.status_code}: {detail}"
    return f"Sarvam HTTP {response.status_code}: {body}"


def _zip_page_images(images: Sequence[Image]) -> bytes:
    """Pack the pages into a flat ZIP. Sarvam orders the pages by file name."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for number, image in enumerate(images, start=1):
            page_buffer = io.BytesIO()
            image.convert("RGB").save(page_buffer, format="PNG", optimize=True)
            archive.writestr(f"page_{number:03d}.png", page_buffer.getvalue())
    return buffer.getvalue()


# ---------------------------------------------------------------------- parsing
def parse_digitise_archive(
    archive: bytes, *, image_sizes: Sequence[tuple[int, int]]
) -> list[SarvamPageResult]:
    """Read the per-page blocks from a Digitise output archive.

    Pages that the archive does not contain are returned with ``ok=False``.
    """
    results = [SarvamPageResult(ok=False) for _ in image_sizes]
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        page_payloads = _page_payloads(zipped)

    for index, payload in page_payloads.items():
        if not 0 <= index < len(results):
            continue
        results[index] = SarvamPageResult(
            blocks=parse_page_blocks(payload, image_size=image_sizes[index]),
            ok=True,
        )
    return results


def _page_payloads(zipped: zipfile.ZipFile) -> dict[int, Any]:
    """Map a 0-based page index to the JSON payload of that page."""
    payloads: dict[int, Any] = {}
    for name in zipped.namelist():
        match = _PAGE_FILE_RE.search(name)
        if match:
            payloads[int(match.group(1)) - 1] = json.loads(zipped.read(name))
    if payloads:
        return payloads

    # No per-page files: look for a combined JSON document with a page list.
    for name in zipped.namelist():
        if not name.lower().endswith(".json") or name.lower().endswith("manifest.json"):
            continue
        document = json.loads(zipped.read(name))
        pages = document.get("pages") if isinstance(document, Mapping) else document
        if isinstance(pages, list):
            for position, page in enumerate(pages):
                number = (
                    page.get("page_num") or page.get("page_number") or page.get("page")
                    if isinstance(page, Mapping)
                    else None
                )
                index = int(number) - 1 if isinstance(number, int) else position
                payloads[index] = page
            return payloads
    return payloads


def parse_page_blocks(
    payload: Any, *, image_size: tuple[int, int]
) -> list[SarvamBlock]:
    """Convert one page payload into blocks with normalized boxes."""
    page_width, page_height = _page_dimensions(payload) or image_size
    blocks: list[SarvamBlock] = []
    for raw in _find_blocks(payload):
        tag = _first_str(
            raw, "layout_tag", "tag", "type", "label", "category", "block_type"
        )
        text = _first_str(raw, *_TEXT_KEYS)
        lines = _block_lines(text)
        if not lines or (tag and tag.lower() in _NON_TEXT_TAGS):
            continue
        box = _parse_box(raw)
        if box is None:
            continue
        normalized = _normalize_box(box, page_width, page_height)
        if normalized is None:
            continue
        confidence = raw.get("confidence", raw.get("score", 1.0))
        blocks.append(
            SarvamBlock(
                lines=lines,
                bbox=normalized,
                tag=tag,
                confidence=float(confidence)
                if isinstance(confidence, int | float)
                else 1.0,
                html=text if text and _TABLE_HTML_RE.search(text) else None,
            )
        )
    return blocks


_BOX_KEYS = (
    "bbox_norm",
    "bbox",
    "bounding_box",
    "boundingBox",
    "box",
    "coordinates",
    "polygon",
    "rect",
)
_BLOCK_LIST_KEYS = ("blocks", "elements", "regions", "items", "layout", "content")


def _find_blocks(payload: Any) -> list[Mapping[str, Any]]:
    """Find the list of block mappings in a page payload."""
    if isinstance(payload, list):
        if (
            payload
            and all(isinstance(item, Mapping) for item in payload)
            and any(_has_box(item) for item in payload)
        ):
            return list(payload)
        for item in payload:
            found = _find_blocks(item)
            if found:
                return found
        return []
    if not isinstance(payload, Mapping):
        return []
    for key in _BLOCK_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            found = _find_blocks(value)
            if found:
                return found
    for value in payload.values():
        if isinstance(value, list | Mapping):
            found = _find_blocks(value)
            if found:
                return found
    return []


def _has_box(item: Mapping[str, Any]) -> bool:
    return any(key in item for key in _BOX_KEYS) or {"x", "y"} <= item.keys()


def _page_dimensions(payload: Any) -> tuple[float, float] | None:
    if not isinstance(payload, Mapping):
        return None
    for width_key, height_key in (
        ("width", "height"),
        ("page_width", "page_height"),
        ("image_width", "image_height"),
    ):
        width, height = payload.get(width_key), payload.get(height_key)
        if (
            isinstance(width, int | float)
            and isinstance(height, int | float)
            and width > 0
            and height > 0
        ):
            return float(width), float(height)
    for key in ("dimensions", "size", "page_size"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            found = _page_dimensions(value)
            if found:
                return found
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(isinstance(v, int | float) for v in value)
        ):
            return float(value[0]), float(value[1])
    return None


def _first_str(raw: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _block_lines(text: str | None) -> list[str]:
    if text is None:
        return []
    if "<" in text and ">" in text:
        text = _CELL_END_RE.sub(" ", text)
        text = _ROW_END_RE.sub("\n", text)
        text = html.unescape(_TAG_RE.sub("", text))
    lines = []
    for line in text.splitlines():
        if _MD_TABLE_RULE_RE.match(line):
            continue
        cleaned = " ".join(line.replace("|", " ").split())
        if cleaned:
            lines.append(cleaned)
    return lines


def _parse_box(raw: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    value: Any = None
    for key in _BOX_KEYS:
        if key in raw:
            value = raw[key]
            break
    if value is None and {"x", "y"} <= raw.keys():
        value = raw
    return _box_from_value(value)


def _box_from_value(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        for keys in (
            ("x0", "y0", "x1", "y1"),
            ("left", "top", "right", "bottom"),
            ("l", "t", "r", "b"),
            ("xmin", "ymin", "xmax", "ymax"),
            ("x1", "y1", "x2", "y2"),
        ):
            if all(isinstance(value.get(k), int | float) for k in keys):
                x0, y0, x1, y1 = (float(value[k]) for k in keys)
                return _ordered(x0, y0, x1, y1)
        x, y = value.get("x", value.get("left")), value.get("y", value.get("top"))
        w, h = value.get("width", value.get("w")), value.get("height", value.get("h"))
        if all(isinstance(v, int | float) for v in (x, y, w, h)):
            return _ordered(
                float(x), float(y), float(x) + float(w), float(y) + float(h)
            )
        for key in ("points", "vertices", "polygon"):
            if key in value:
                return _box_from_value(value[key])
        return None
    if isinstance(value, list) and value:
        if len(value) == 4 and all(isinstance(v, int | float) for v in value):
            return _ordered(*(float(v) for v in value))
        points = [_point(p) for p in value]
        if all(p is not None for p in points):
            xs = [p[0] for p in points if p is not None]
            ys = [p[1] for p in points if p is not None]
            return min(xs), min(ys), max(xs), max(ys)
        flat = [v for v in value if isinstance(v, int | float)]
        if len(flat) == len(value) and len(flat) >= 4 and len(flat) % 2 == 0:
            xs, ys = flat[0::2], flat[1::2]
            return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))
    return None


def _point(value: Any) -> tuple[float, float] | None:
    if (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(v, int | float) for v in value)
    ):
        return float(value[0]), float(value[1])
    if (
        isinstance(value, Mapping)
        and isinstance(value.get("x"), int | float)
        and isinstance(value.get("y"), int | float)
    ):
        return float(value["x"]), float(value["y"])
    return None


def _ordered(
    x0: float, y0: float, x1: float, y1: float
) -> tuple[float, float, float, float]:
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _normalize_box(
    box: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float] | None:
    """Return the box in 0..1 units. Boxes with all coordinates <= 1 are taken as normalized."""
    x0, y0, x1, y1 = box
    if max(x0, y0, x1, y1) > 1.0 + 1e-6:
        x0, x1 = x0 / width, x1 / width
        y0, y1 = y0 / height, y1 / height
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1
