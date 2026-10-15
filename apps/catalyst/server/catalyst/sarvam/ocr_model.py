"""Sarvam Vision as a Docling OCR engine.

Docling still decides *where* OCR is needed (``OcrOptions.mode``): with the
default mode only the regions without a usable PDF text layer are kept. Sarvam
only does the recognition. Each page is rendered and sent as an image; up to
10 pages go into one Digitise job.

Sarvam returns block-level boxes (paragraphs, headings, tables), not word or
line boxes. A block with several text lines is split into equal-height line
cells. That is good enough for running text, but not for tables: a table row
becomes one line as wide as the table, and Docling's table-structure model
cannot place its words in columns. Layout analysis runs before OCR, so the
table regions are known here. By default (`table_text="local"`) the text inside
them is read with RapidOCR, which returns word boxes; Sarvam reads the rest.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, ClassVar, Literal

import numpy
from docling_core.types.doc import BoundingBox, CoordOrigin, DocItemLabel
from docling_core.types.doc.page import BoundingRectangle, TextCell
from pydantic import ConfigDict, Field, SecretStr

from catalyst.sarvam.client import (
    MAX_PAGES_PER_JOB,
    SarvamBlock,
    SarvamDocAiClient,
)
from catalyst.sarvam.usage import record_usage
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrOptions, RapidOcrOptions
from docling.datamodel.settings import settings
from docling.exceptions import OcrLanguageNotSupportedError
from docling.models.base_ocr_model import BaseOcrModel
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
from docling.utils.ocr_language import OcrLanguage, OcrLanguageSupport
from docling.utils.profiling import TimeRecorder
from docling.utils.utils import chunkify

_log = logging.getLogger(__name__)

SARVAM_API_KEY_ENV = "SARVAM_API_KEY"

# Languages that Sarvam Vision supports, as Sarvam writes them.
SARVAM_LANGUAGES: tuple[str, ...] = (
    "en-IN", "hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN", "kn-IN",
    "ml-IN", "od-IN", "pa-IN", "as-IN", "brx-IN", "doi-IN", "ks-IN", "kok-IN",
    "mai-IN", "mni-IN", "ne-IN", "sa-IN", "sat-IN", "sd-IN", "ur-IN",
)  # fmt: skip

# ISO 639 primary subtags that differ from Sarvam's code (Odia is `or` in ISO).
_ISO_TO_SARVAM = {"or": "od-IN"}

# Layout regions whose text is laid out in columns.
_TABLE_LABELS = frozenset({DocItemLabel.TABLE, DocItemLabel.DOCUMENT_INDEX})

# RapidOCR recognizer for the tables of a document in this Sarvam language.
# None: RapidOCR has no model for the script, so tables keep Sarvam's text.
_DEVANAGARI = (
    "hi-IN",
    "mr-IN",
    "ne-IN",
    "sa-IN",
    "mai-IN",
    "kok-IN",
    "doi-IN",
    "brx-IN",
)
_TABLE_READER_LANG: dict[str | None, list[str] | None] = {
    None: None,  # no language: Sarvam treats the text as Indic
    "en-IN": [],  # RapidOCR's default (Latin) recognizer
    "ta-IN": ["ta"],
    "te-IN": ["te"],
    **{code: ["devanagari"] for code in _DEVANAGARI},
}


class SarvamOcrOptions(OcrOptions):
    """Options for the Sarvam Vision OCR engine (remote API)."""

    kind: ClassVar[Literal["sarvam"]] = "sarvam"

    lang: Annotated[
        list[str],
        Field(
            description=(
                "Document language, as a Sarvam code (`en-IN`, `hi-IN`, `ta-IN`, ...) or as "
                "a BCP-47 tag behind the `iso:` prefix (`iso:hi`). Sarvam reads one "
                "language per job; only the first entry is used. An empty list sends no "
                "language, and Sarvam then treats the document as Indic."
            ),
            examples=[["en-IN"], ["hi-IN"], ["iso:ta"]],
        ),
    ] = ["en-IN"]
    api_key: Annotated[
        SecretStr | None,
        Field(
            description=(
                f"Sarvam API subscription key. If empty, the `{SARVAM_API_KEY_ENV}` "
                "environment variable is used."
            )
        ),
    ] = None
    base_url: Annotated[str, Field(description="Base URL of the Sarvam API.")] = (
        "https://api.sarvam.ai"
    )
    model: Annotated[
        str | None,
        Field(description="Sarvam model name. Empty uses the Sarvam default."),
    ] = None
    content_type: Annotated[
        str | None,
        Field(
            description=(
                "Nature of the document content, passed to Sarvam as `content_type` "
                "(for example printed, handwritten or mixed). Empty uses the Sarvam default."
            )
        ),
    ] = None
    scale: Annotated[
        float,
        Field(
            description=(
                "Render scale for the page image sent to Sarvam (72 DPI times this "
                "factor). 2.0 gives 144 DPI, which keeps uploads small."
            ),
            gt=0.0,
        ),
    ] = 2.0
    pages_per_job: Annotated[
        int,
        Field(
            description="Pages sent in one Digitise job. Sarvam accepts at most 10.",
            ge=1,
            le=MAX_PAGES_PER_JOB,
        ),
    ] = MAX_PAGES_PER_JOB
    min_region_overlap: Annotated[
        float,
        Field(
            description=(
                "A recognized line is kept only when at least this fraction of it lies "
                "inside a region that Docling selected for OCR."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = 0.5
    table_text: Annotated[
        Literal["local", "sarvam"],
        Field(
            description=(
                "How text inside tables is read. `local` reads table regions with "
                "RapidOCR, which returns word boxes, so Docling can find the columns; "
                "it picks the Devanagari, Tamil or Telugu model from `lang`, and "
                "falls back to Sarvam's text for scripts RapidOCR cannot read. "
                "`sarvam` uses Sarvam's text, which is better for Indic scripts, but "
                "Sarvam gives one box per row, so the columns are often merged."
            )
        ),
    ] = "local"
    poll_interval_seconds: Annotated[
        float, Field(description="Delay between job status requests.", gt=0.0)
    ] = 2.0
    job_timeout_seconds: Annotated[
        float, Field(description="Maximum time to wait for one job.", gt=0.0)
    ] = 900.0
    request_timeout_seconds: Annotated[
        float, Field(description="Timeout of one HTTP request.", gt=0.0)
    ] = 120.0

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    def resolved_api_key(self) -> str | None:
        if self.api_key is not None and self.api_key.get_secret_value():
            return self.api_key.get_secret_value()
        return os.environ.get(SARVAM_API_KEY_ENV) or None


class SarvamOcrModel(BaseOcrModel):
    """OCR stage that sends page images to Sarvam Vision."""

    multiple_languages = False

    def __init__(
        self,
        enabled: bool,
        artifacts_path: Path | None,
        options: SarvamOcrOptions,
        accelerator_options: AcceleratorOptions,
    ):
        super().__init__(
            enabled=enabled,
            artifacts_path=artifacts_path,
            options=options,
            accelerator_options=accelerator_options,
        )
        self.options: SarvamOcrOptions
        self._language: str | None = None
        self._client: SarvamDocAiClient | None = None
        self._table_reader: RapidOcrModel | None = None

        if self.enabled:
            codes = self.resolve_ocr_languages()
            self._language = codes[0] if codes else None
            api_key = self.options.resolved_api_key()
            if api_key is None:
                raise ValueError(
                    "Sarvam OCR needs an API key. Set the "
                    f"{SARVAM_API_KEY_ENV} environment variable or `api_key` in the options."
                )
            self._client = SarvamDocAiClient(
                api_key=api_key,
                base_url=self.options.base_url,
                request_timeout_seconds=self.options.request_timeout_seconds,
                poll_interval_seconds=self.options.poll_interval_seconds,
                job_timeout_seconds=self.options.job_timeout_seconds,
            )
            reader_lang = _TABLE_READER_LANG.get(self._language)
            if self.options.table_text == "local" and reader_lang is not None:
                reader_options = (
                    RapidOcrOptions(lang=reader_lang)
                    if reader_lang
                    else RapidOcrOptions()
                )
                self._table_reader = RapidOcrModel(
                    enabled=True,
                    artifacts_path=artifacts_path,
                    options=reader_options,
                    accelerator_options=accelerator_options,
                )
            elif self.options.table_text == "local":
                _log.info(
                    "RapidOCR has no recognizer for %s; tables keep Sarvam's text.",
                    self._language or "Indic text",
                )

    @classmethod
    def get_options_type(cls) -> type[OcrOptions]:
        return SarvamOcrOptions

    def supported_ocr_languages(self) -> OcrLanguageSupport:
        return OcrLanguageSupport(
            bcp47=sorted(code.split("-")[0] for code in SARVAM_LANGUAGES),
            native=list(SARVAM_LANGUAGES),
        )

    def map_ocr_language(self, language: OcrLanguage) -> str:
        if language.is_passthrough():
            code = language.native
        else:
            primary = language.bcp47_language or ""
            code = _ISO_TO_SARVAM.get(primary, f"{primary}-IN")
        if code not in SARVAM_LANGUAGES:
            raise OcrLanguageNotSupportedError(
                self._engine_name,
                language.tag(),
                supported=self.supported_ocr_languages(),
            )
        return code

    def __call__(
        self, conv_res: ConversionResult, page_batch: Iterable[Page]
    ) -> Iterable[Page]:
        pages = list(page_batch)
        if not self.enabled:
            yield from pages
            return

        work: list[tuple[Page, list[BoundingBox]]] = []
        for page in pages:
            assert page._backend is not None
            if not page._backend.is_valid():
                continue
            with TimeRecorder(conv_res, "ocr"):
                rects = [rect for rect in self.get_ocr_rects(page) if rect.area() > 0]
            if rects:
                work.append((page, rects))
            else:
                # Nothing to recognize: keep the PDF cells as they are.
                self.post_process_cells([], page, conv_res)

        for chunk in chunkify(work, self.options.pages_per_job):
            with TimeRecorder(conv_res, "ocr"):
                self._recognize_chunk(conv_res, chunk)

        yield from pages

    def _recognize_chunk(
        self, conv_res: ConversionResult, chunk: list[tuple[Page, list[BoundingBox]]]
    ) -> None:
        assert self._client is not None
        images = []
        for page, _ in chunk:
            assert page._backend is not None
            images.append(page._backend.get_page_image(scale=self.options.scale))

        digitised = self._client.digitise_pages(
            images,
            language=self._language,
            model=self.options.model,
            content_type=self.options.content_type,
        )
        record_usage(conv_res, pages=digitised.billed_pages)

        for (page, rects), result in zip(chunk, digitised.pages):
            if not result.ok:
                _log.warning(
                    "Sarvam returned no result for page %s; the page keeps its PDF text only.",
                    page.page_no + 1,
                )
            cells = self._cells_for_page(page, rects, result.blocks)
            self.post_process_cells(cells, page, conv_res)
            if settings.debug.visualize_ocr:
                self.draw_ocr_rects_and_cells(conv_res, page, rects)

    def _cells_for_page(
        self, page: Page, rects: list[BoundingBox], blocks: list[SarvamBlock]
    ) -> list[TextCell]:
        assert page.size is not None
        width, height = page.size.width, page.size.height
        overlap = self.options.min_region_overlap
        # Read the tables first: a sideways table keeps Sarvam's text instead.
        tables, local = [], []
        for table in self._table_regions(page, rects):
            read = self._read_locally(page, table)
            if read is not None:
                tables.append(table)
                local.append(read)
        cells: list[TextCell] = []
        for block in blocks:
            for line_text, line_box in _split_block_lines(block, width, height):
                if not any(
                    line_box.intersection_over_self(r) >= overlap for r in rects
                ):
                    continue
                if any(line_box.intersection_over_self(t) >= overlap for t in tables):
                    continue  # read with word boxes below
                cells.append(_cell(len(cells), line_text, line_box, block.confidence))
        for read in local:
            for text, box, confidence in read:
                cells.append(_cell(len(cells), text, box, confidence))
        return cells

    def _table_regions(self, page: Page, rects: list[BoundingBox]) -> list[BoundingBox]:
        """Table regions of the page layout that need OCR, when they are read locally."""
        if self._table_reader is None or page.predictions.layout is None:
            return []
        return [
            cluster.bbox
            for cluster in page.predictions.layout.clusters
            if cluster.label in _TABLE_LABELS
            and cluster.bbox.area() > 0
            and any(cluster.bbox.intersection_over_self(r) >= 0.5 for r in rects)
        ]

    def _read_locally(
        self, page: Page, region: BoundingBox
    ) -> list[tuple[str, BoundingBox, float]] | None:
        """Read one region with RapidOCR: one entry per detected text line.

        Returns None when the text in the region runs sideways (a landscape
        table printed on a portrait page): RapidOCR reads it as garbage, while
        Sarvam reads it correctly. With `straighten_scanned_pages` (the
        default), image-only pages are already upright here; this covers pages
        with a text layer and conversions with that setting off.
        """
        assert self._table_reader is not None and page._backend is not None
        scale = self._table_reader.scale
        image = page._backend.get_page_image(scale=scale, cropbox=region)
        result = self._table_reader.reader(numpy.array(image))
        if result is None or result.boxes is None:
            return []
        boxes = result.boxes.tolist()
        if _runs_sideways(boxes, result.txts):
            _log.info(
                "Table on page %s runs sideways; it keeps Sarvam's text.",
                page.page_no + 1,
            )
            return None
        found = []
        for box, text, score in zip(boxes, result.txts, result.scores):
            if not text.strip():
                continue
            xs, ys = [point[0] for point in box], [point[1] for point in box]
            found.append(
                (
                    text,
                    BoundingBox(
                        l=min(xs) / scale + region.l,
                        t=min(ys) / scale + region.t,
                        r=max(xs) / scale + region.l,
                        b=max(ys) / scale + region.t,
                        coord_origin=CoordOrigin.TOPLEFT,
                    ),
                    float(score),
                )
            )
        return found


def _runs_sideways(boxes: list[list[list[float]]], texts: list[str]) -> bool:
    """True when most text lines of a reading are taller than wide.

    Measured on a scanned report: upright tables had no tall lines among 134
    to 244; tables printed sideways had 89 to 99 percent tall lines.
    """
    tall = wide = 0
    for box, text in zip(boxes, texts):
        if len(text.strip()) < 3:
            continue
        xs, ys = [point[0] for point in box], [point[1] for point in box]
        if max(ys) - min(ys) > 1.5 * (max(xs) - min(xs)):
            tall += 1
        else:
            wide += 1
    return tall + wide >= 5 and tall > wide


def _cell(index: int, text: str, box: BoundingBox, confidence: float) -> TextCell:
    return TextCell(
        index=index,
        text=text,
        orig=text,
        from_ocr=True,
        confidence=confidence,
        rect=BoundingRectangle.from_bounding_box(box),
    )


def _split_block_lines(
    block: SarvamBlock, page_width: float, page_height: float
) -> list[tuple[str, BoundingBox]]:
    """Split a block into equal-height line boxes in page coordinates."""
    left, top, right, bottom = block.bbox
    x0, x1 = left * page_width, right * page_width
    y0, y1 = top * page_height, bottom * page_height
    step = (y1 - y0) / len(block.lines)
    return [
        (
            text,
            BoundingBox(
                l=x0, t=y0 + i * step, r=x1, b=y0 + (i + 1) * step,
                coord_origin=CoordOrigin.TOPLEFT,
            ),
        )
        for i, text in enumerate(block.lines)
    ]  # fmt: skip
