"""Request settings and the standardized output envelope."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from docling_core.types.doc import ImageRefMode
from pydantic import BaseModel, Field

from catalyst.catalog import FormatConfig
from catalyst.dost.models import DostReport
from docling.datamodel.base_models import InputFormat, OutputFormat

ENVELOPE_SCHEMA_VERSION = "1.0"


class ChunkerType(str, Enum):
    HYBRID = "hybrid"
    HIERARCHICAL = "hierarchical"


# ------------------------------------------------------------------- settings
class ConvertSettings(BaseModel):
    """Limits and input selection for one conversion."""

    allowed_formats: Annotated[
        list[InputFormat] | None,
        Field(
            description="Accept only these input formats. Empty accepts all formats."
        ),
    ] = None
    max_file_size_mb: Annotated[
        float, Field(description="Reject files larger than this size.", gt=0)
    ] = 200.0
    max_num_pages: Annotated[
        int | None, Field(description="Reject documents with more pages.", ge=1)
    ] = None
    page_range_start: Annotated[
        int, Field(description="First page to convert (1-based).", ge=1)
    ] = 1
    page_range_end: Annotated[
        int | None,
        Field(description="Last page to convert. Empty means the last page.", ge=1),
    ] = None
    ignore_text_layer: Annotated[
        bool,
        Field(
            description=(
                "Ignore the PDF text layer and read every page with OCR, like a scan. "
                "Use it when the text in the result is garbled: legacy Indic fonts "
                "(Kruti Dev and similar) store Latin letters that only look like Hindi."
            )
        ),
    ] = False
    ignore_garbled_text_layer: Annotated[
        bool,
        Field(
            description=(
                "With Sarvam OCR in an Indic language, read a page with OCR when its PDF "
                "text layer has almost no letters in the script of that language (a "
                "legacy font such as Kruti Dev). Other pages keep their text layer. A "
                "page in another language, for example English in a Hindi document, is "
                "read with OCR as well."
            )
        ),
    ] = True
    straighten_scanned_pages: Annotated[
        bool,
        Field(
            description=(
                "Turn image-only pages (scans, image files) upright and straighten "
                "them before layout, OCR and table analysis. Fixes tables printed "
                "sideways and pages scanned at a slight angle. Pages with a text "
                "layer are not changed."
            )
        ),
    ] = True
    remove_repeated_headers: Annotated[
        bool,
        Field(
            description=(
                "Move running page headers and footers that the layout model missed "
                "(the same words at the top or bottom of three or more pages) out of "
                "the document body."
            )
        ),
    ] = True
    join_key_values: Annotated[
        bool,
        Field(
            description=(
                'In label/value blocks ("Type of Calamity : Drought"), join each label '
                "with the value on the same row. Without it, Docling can list all "
                "labels first and all values after them."
            )
        ),
    ] = True


class ExportSettings(BaseModel):
    """Which outputs to produce, and how."""

    to_formats: Annotated[
        list[OutputFormat],
        Field(
            description="Output formats to produce. JSON is the canonical DoclingDocument."
        ),
    ] = [OutputFormat.JSON, OutputFormat.HTML, OutputFormat.MARKDOWN]
    image_export_mode: Annotated[
        ImageRefMode,
        Field(
            description=(
                "How images appear in the outputs: a placeholder, embedded as base64, "
                "or referenced as separate files (download the bundle to get them)."
            )
        ),
    ] = ImageRefMode.EMBEDDED
    show_layout: Annotated[
        bool,
        Field(
            description="Draw the layout boxes on the pages of the split-page HTML output."
        ),
    ] = False
    chunker_type: Annotated[
        ChunkerType, Field(description="Chunker for the chunks output.")
    ] = ChunkerType.HYBRID
    chunk_max_tokens: Annotated[
        int | None,
        Field(
            description="Maximum tokens per chunk (hybrid chunker). Empty uses the tokenizer limit.",
            ge=1,
        ),
    ] = None
    chunk_tokenizer: Annotated[
        str, Field(description="Hugging Face tokenizer for the hybrid chunker.")
    ] = "sentence-transformers/all-MiniLM-L6-v2"
    inline_max_kb: Annotated[
        int,
        Field(
            description="Text outputs up to this size are included in the envelope; larger ones are download links only.",
            ge=0,
        ),
    ] = 5000


class ValidationSettings(BaseModel):
    """Content and structure checks on the converted document."""

    min_text_chars: Annotated[
        int,
        Field(
            description="Fail when the document has less text than this and no tables or pictures.",
            ge=0,
        ),
    ] = 1
    warn_empty_pages: Annotated[
        bool, Field(description="Warn about pages without any content.")
    ] = True
    warn_missing_headings_above_chars: Annotated[
        int | None,
        Field(
            description="Warn when a document with more text than this has no headings. Empty disables.",
            ge=0,
        ),
    ] = 3000
    fail_on_partial_success: Annotated[
        bool, Field(description="Treat a partial conversion as a failed validation.")
    ] = False


class EnvelopeSettings(BaseModel):
    include_original: Annotated[
        bool, Field(description="Keep the uploaded file and link it from the envelope.")
    ] = False


class TableFileType(str, Enum):
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"


class TableExtractionSettings(BaseModel):
    """Extract every table into files, with metadata about where it comes from."""

    enabled: Annotated[
        bool,
        Field(description="Extract all tables of the document into a table package."),
    ] = False
    file_types: Annotated[
        list[TableFileType],
        Field(
            description=(
                "Files in the package: one CSV per table, one Excel workbook with a "
                "sheet per table and an index sheet, and a JSON manifest with the "
                "metadata and cells of every table."
            )
        ),
    ] = [TableFileType.CSV, TableFileType.XLSX, TableFileType.JSON]
    include_images: Annotated[
        bool,
        Field(
            description=(
                "Save an image of each table, cut from its page, to check the "
                "result against the original."
            )
        ),
    ] = True
    join_continued: Annotated[
        bool,
        Field(
            description=(
                "Join a table that continues on the next page (same columns, same "
                "header or none) into one table. Off: the parts stay separate and "
                "are linked."
            )
        ),
    ] = False
    preview_rows: Annotated[
        int,
        Field(
            description="Rows of each table shown in the result envelope.", ge=0, le=50
        ),
    ] = 5


class PageHtmlSettings(BaseModel):
    """One HTML file per page, with links between the pages."""

    enabled: Annotated[
        bool,
        Field(
            description=(
                "Write one HTML file per page plus an index page. Pictures are linked "
                "as separate image files, not embedded."
            )
        ),
    ] = False
    html_lang: Annotated[
        str | None,
        Field(
            description=(
                "The `lang` attribute of the pages (for example `hi` for Hindi). Empty "
                "takes the OCR language when there is one, else `en`."
            )
        ),
    ] = None


class PictureExtractionSettings(BaseModel):
    """Save every picture as its own file, with metadata about its origin."""

    enabled: Annotated[
        bool,
        Field(
            description=(
                "Save every picture (photo, chart, drawing, logo) as a PNG file, with "
                "a JSON manifest of its page, position, caption and section."
            )
        ),
    ] = False
    min_size_px: Annotated[
        int,
        Field(
            description="Skip pictures smaller than this (width or height, in pixels), such as small decorations.",
            ge=0,
        ),
    ] = 32


class ConvertRequest(BaseModel):
    """The options of one conversion, as sparse overrides of the defaults."""

    settings: dict[str, Any] = {}
    export: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    envelope: dict[str, Any] = {}
    tables: dict[str, Any] = {}
    pages: dict[str, Any] = {}
    pictures: dict[str, Any] = {}
    dost: dict[str, Any] = {}
    formats: dict[str, FormatConfig] = {}


# ------------------------------------------------------------------- envelope
class SourceInfo(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    detected_format: str | None = None


class SarvamCost(BaseModel):
    """What the Sarvam OCR of one conversion costs.

    Sarvam bills Document Digitization per page, not per token. The price is
    the server's price when the job ran, so later price changes do not alter it.
    """

    jobs: int
    pages: int
    price_per_page: float
    currency: str
    cost: float


class TranslationCost(BaseModel):
    """What the Sarvam translation of one conversion costs.

    Sarvam bills translation per character sent (both models at the same
    rate). The price is the server's price when the job ran.
    """

    characters: int
    price_per_10k_characters: float
    currency: str
    cost: float


class ProcessingInfo(BaseModel):
    pipeline: str | None = None
    backend: str | None = None
    ocr_engine: str | None = None
    headers_removed: int = 0
    key_values_joined: int = 0
    sarvam_tables: int = Field(
        default=0,
        description="Tables that take their rows, columns and merged cells from Sarvam.",
    )
    sarvam: SarvamCost | None = None
    sarvam_translation: TranslationCost | None = None
    ocr_language_from_font: str | None = Field(
        default=None,
        description=(
            "Set when no OCR language was given and Catalyst took it from a legacy "
            "Indic font of the PDF (Kruti Dev, Akruti Oriya, ...)."
        ),
    )
    docling_version: str
    duration_seconds: float


class DocumentStats(BaseModel):
    pages: int = 0
    characters: int = 0
    text_items: int = 0
    headings: int = 0
    tables: int = 0
    pictures: int = 0
    empty_pages: list[int] = []


class ValidationCheck(BaseModel):
    id: str
    status: Literal["pass", "warn", "fail"]
    message: str


class ValidationReport(BaseModel):
    passed: bool
    checks: list[ValidationCheck]


class OutputItem(BaseModel):
    format: str
    filename: str
    media_type: str
    size_bytes: int
    url: str
    content: str | None = None


class TableSource(BaseModel):
    filename: str
    sha256: str
    detected_format: str | None = None
    page_count: int


class TableRegion(BaseModel):
    """Where (part of) a table lies on a page."""

    page: int
    bbox: tuple[float, float, float, float] = Field(
        description="(left, top, right, bottom) in PDF points, origin at the top-left corner."
    )
    bbox_normalized: tuple[float, float, float, float] = Field(
        description="The same box as fractions (0 to 1) of the page width and height."
    )
    page_width: float
    page_height: float
    units: Literal["pt", "cell"] = Field(
        default="pt",
        description=(
            "pt: PDF points (documents, images). cell: column and row positions, for "
            "spreadsheets, where each page is one sheet."
        ),
    )


class TableExtraction(BaseModel):
    method: Literal["text_layer", "ocr", "mixed", "structured"] = Field(
        description=(
            "text_layer: cells from the PDF text; ocr: cells from OCR (scans, images); "
            "mixed: some regions each way; structured: from a file with real tables "
            "(Word, Excel, HTML, ...)."
        )
    )
    ocr_engine: str | None = None
    table_text: str | None = None
    structure: Literal["docling", "sarvam"] = Field(
        default="docling",
        description=(
            "Where the rows, columns and merged cells come from: Docling (the table "
            "model, or the structure of the source file) or the HTML table of Sarvam OCR."
        ),
    )


class TableQuality(BaseModel):
    status: Literal["ok", "warn"]
    reasons: list[str] = []


class TableSummary(BaseModel):
    """One table and the metadata that says where it comes from."""

    table_id: str
    index: int = Field(description="Position of the table in the document, from 1.")
    source: TableSource
    page: int | None = None
    regions: list[TableRegion] = []
    caption: str | None = None
    title: str | None = None
    section: str | None = None
    units: str | None = None
    footnotes: list[str] = []
    num_rows: int
    num_cols: int
    header_rows: int
    empty_cells_share: float
    extraction: TableExtraction
    quality: TableQuality
    continues_from: str | None = None
    continues_to: str | None = None
    joined_from: list[str] = []
    files: dict[str, str] = {}
    preview: list[list[str]] = []


class TableRecord(TableSummary):
    rows: list[list[str]]


class PictureSummary(BaseModel):
    """One picture and the metadata that says where it comes from."""

    picture_id: str
    index: int = Field(description="Position of the picture in the document, from 1.")
    source: TableSource
    page: int | None = None
    regions: list[TableRegion] = []
    caption: str | None = None
    section: str | None = None
    width_px: int
    height_px: int
    files: dict[str, str] = {}


class PictureManifest(BaseModel):
    schema_version: str = "1.0"
    source: TableSource
    pictures: list[PictureSummary]


class PageLink(BaseModel):
    page: int
    url: str
    heading: str | None = None


class TableManifest(BaseModel):
    schema_version: str = "1.0"
    source: TableSource
    tables: list[TableRecord]


class ErrorInfo(BaseModel):
    component: str | None = None
    module: str | None = None
    message: str


class Envelope(BaseModel):
    """The standardized result of one conversion."""

    schema_version: str = ENVELOPE_SCHEMA_VERSION
    job_id: str
    created_at: datetime
    status: Literal["success", "partial_success", "failure", "rejected"]
    source: SourceInfo
    processing: ProcessingInfo | None = None
    stats: DocumentStats | None = None
    validation: ValidationReport | None = None
    outputs: list[OutputItem] = []
    tables: list[TableSummary] = []
    pictures: list[PictureSummary] = []
    pages: list[PageLink] = []
    dost: DostReport | None = None
    bundle_url: str | None = None
    original_url: str | None = None
    errors: list[ErrorInfo] = []


class JobSummary(BaseModel):
    """One past conversion, for the history list."""

    job_id: str
    created_at: datetime
    status: str
    filename: str
    size_bytes: int
    detected_format: str | None = None
    pages: int = 0
    tables: int = 0
    pictures: int = 0
    ocr_engine: str | None = None
    duration_seconds: float | None = None
    sarvam: SarvamCost | None = None

    @classmethod
    def from_envelope(cls, envelope: Envelope) -> JobSummary:
        return cls(
            job_id=envelope.job_id,
            created_at=envelope.created_at,
            status=envelope.status,
            filename=envelope.source.filename,
            size_bytes=envelope.source.size_bytes,
            detected_format=envelope.source.detected_format,
            pages=envelope.stats.pages if envelope.stats else 0,
            tables=envelope.stats.tables if envelope.stats else 0,
            pictures=envelope.stats.pictures if envelope.stats else 0,
            ocr_engine=envelope.processing.ocr_engine if envelope.processing else None,
            duration_seconds=envelope.processing.duration_seconds
            if envelope.processing
            else None,
            sarvam=envelope.processing.sarvam if envelope.processing else None,
        )
