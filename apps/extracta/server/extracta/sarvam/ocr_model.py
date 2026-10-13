"""Sarvam Vision as a Docling OCR engine.

Docling still decides *where* OCR is needed (``OcrOptions.mode``): with the
default mode only the regions without a usable PDF text layer are kept. Sarvam
only does the recognition. Each page is rendered and sent as an image; up to
10 pages go into one Digitise job.

Sarvam returns block-level boxes (paragraphs, headings, tables), not word or
line boxes. A block with several text lines is split into equal-height line
cells. This is an approximation: Docling's table-structure model works best
with word or line cells, so table cell matching on scanned pages can be less
precise than with a line-level OCR engine.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell
from pydantic import ConfigDict, Field, SecretStr

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.base_models import Page
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import OcrOptions
from docling.datamodel.settings import settings
from docling.exceptions import OcrLanguageNotSupportedError
from docling.models.base_ocr_model import BaseOcrModel
from docling.utils.ocr_language import OcrLanguage, OcrLanguageSupport
from docling.utils.profiling import TimeRecorder
from docling.utils.utils import chunkify
from extracta.sarvam.client import (
    MAX_PAGES_PER_JOB,
    SarvamBlock,
    SarvamDocAiClient,
)

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

        results = self._client.digitise_pages(
            images,
            language=self._language,
            model=self.options.model,
            content_type=self.options.content_type,
        )

        for (page, rects), result in zip(chunk, results):
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
        cells: list[TextCell] = []
        for block in blocks:
            for line_text, line_box in _split_block_lines(block, width, height):
                if not any(
                    line_box.intersection_over_self(rect)
                    >= self.options.min_region_overlap
                    for rect in rects
                ):
                    continue
                cells.append(
                    TextCell(
                        index=len(cells),
                        text=line_text,
                        orig=line_text,
                        from_ocr=True,
                        confidence=block.confidence,
                        rect=BoundingRectangle.from_bounding_box(line_box),
                    )
                )
        return cells


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
