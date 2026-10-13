"""Request settings and the standardized output envelope."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from docling_core.types.doc import ImageRefMode
from pydantic import BaseModel, Field

from docling.datamodel.base_models import InputFormat, OutputFormat
from extracta.catalog import FormatConfig

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


class ConvertRequest(BaseModel):
    """The options of one conversion, as sparse overrides of the defaults."""

    settings: dict[str, Any] = {}
    export: dict[str, Any] = {}
    validation: dict[str, Any] = {}
    envelope: dict[str, Any] = {}
    formats: dict[str, FormatConfig] = {}


# ------------------------------------------------------------------- envelope
class SourceInfo(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    detected_format: str | None = None


class ProcessingInfo(BaseModel):
    pipeline: str | None = None
    backend: str | None = None
    ocr_engine: str | None = None
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
    bundle_url: str | None = None
    original_url: str | None = None
    errors: list[ErrorInfo] = []
