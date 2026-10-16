"""Settings and the report of the DOST extraction (tables, sentences, images)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "warn", "error"]

TranslationStatus = Literal[
    "translated",  # translated by the translation service
    "english",  # the sentence is English already: the translation is a copy
    "no_letters",  # numbers or symbols only: the translation is a copy
    "failed",  # the service returned an error: the translation is empty
    "unsupported",  # no translation service for this language: empty
    "disabled",  # translation is off: empty
]


class DostSettings(BaseModel):
    """Split a document into three outputs: all tables as one Markdown file,
    the written sentences with an English translation as a CSV file, and every
    image as its own file."""

    enabled: Annotated[
        bool,
        Field(
            description=(
                "Write `document_tables.md`, `document_sentences.csv` (sentence and "
                "English translation) and `images/`, with an extraction report."
            )
        ),
    ] = False
    translate: Annotated[
        bool,
        Field(
            description=(
                "Translate the sentences that are not in English with the Sarvam "
                "Translate API (needs a Sarvam key). Off: the translation column of "
                "non-English sentences stays empty."
            )
        ),
    ] = True
    source_language: Annotated[
        str | None,
        Field(
            description=(
                "Language of the document as a Sarvam code (`hi-IN`, `mr-IN`, ...). "
                "Empty takes the Sarvam OCR language, else finds the language of each "
                "sentence from its script."
            )
        ),
    ] = None
    translate_workers: Annotated[
        int,
        Field(description="Translation requests sent at the same time.", ge=1, le=16),
    ] = 4
    min_image_px: Annotated[
        int,
        Field(
            description=(
                "Skip embedded images smaller than this (width or height, in pixels), "
                "such as spacer pixels. Skipped images are listed in the report."
            ),
            ge=0,
        ),
    ] = 8
    include_page_scans: Annotated[
        bool,
        Field(
            description=(
                "Also save the scan image of a scanned page as an image. Off: the "
                "pictures that the layout model finds on a scanned page are cut out "
                "of it instead."
            )
        ),
    ] = False
    render_dpi: Annotated[
        int,
        Field(
            description=(
                "Resolution for pictures that are not stored as an image in the PDF "
                "(vector charts and diagrams), which are rendered from the page."
            ),
            ge=72,
            le=600,
        ),
    ] = 200


class DostIssue(BaseModel):
    """A limit, an error or uncertain content, so that no loss is silent."""

    severity: Severity
    component: Literal["document", "tables", "sentences", "translation", "images"]
    message: str
    page: int | None = None


class TableCounts(BaseModel):
    tables: int = 0
    html_tables: int = Field(
        default=0,
        description="Tables written as HTML in the Markdown file (merged cells or no plain header row).",
    )
    joined_parts: int = Field(
        default=0, description="Table parts on later pages joined to their table."
    )
    with_warnings: int = 0


class SentenceCounts(BaseModel):
    sentences: int = 0
    by_status: dict[str, int] = {}
    numbers_differ: int = Field(
        default=0,
        description="Translations whose numbers differ from the original sentence.",
    )
    characters_sent: int = Field(
        default=0, description="Characters sent to the translation service."
    )
    skipped_items: dict[str, int] = Field(
        default={},
        description="Text items left out of the CSV, by kind (code, formula, text inside a picture, ...).",
    )


SentenceProblemKind = Literal[
    "not_translated",  # the translation service failed: the translation is empty
    "language_not_supported",  # no service for this language: empty
    "translation_off",  # translation off or no key: empty
    "numbers_differ",  # translated, but numbers of the original are missing
    "language_assumed",  # translated, but in a language that Catalyst assumed
    "retranslated",  # the first translation was broken; this one is a second try
    "ocr_suspect",  # the sentence is in another script than the document language
]


class SentenceProblem(BaseModel):
    """One sentence that has no translation, or whose translation needs a check."""

    row: int = Field(description="Row in the sentences CSV (the header is row 1).")
    page: int | None = None
    original: str
    translation: str
    kind: SentenceProblemKind
    reason: str = Field(description="What went wrong, in plain words.")
    summary: str = Field(
        default="",
        description="The reason without the details of this sentence, to group sentences.",
    )
    action: str | None = Field(default=None, description="What the user can do.")
    detail: str | None = Field(
        default=None, description="The technical message, for example the API error."
    )


class ImageRecord(BaseModel):
    """One file in `images/`."""

    filename: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="(left, top, right, bottom) in PDF points, origin at the top-left corner.",
    )
    kind: Literal["embedded", "rendered"] = Field(
        description=(
            "embedded: the image as stored in the PDF; rendered: a picture cut from "
            "the rendered page (vector graphics, pictures on a scanned page, other formats)."
        )
    )
    format: str
    width_px: int
    height_px: int
    sha256: str
    occurrences: int = Field(
        default=1,
        description="How often the same embedded image is used in the document.",
    )
    caption: str | None = None


class ImageCounts(BaseModel):
    files: int = 0
    embedded: int = 0
    rendered: int = 0
    duplicates_skipped: int = 0
    too_small_skipped: int = 0
    page_scans_skipped: int = 0
    failed: int = 0


class DostReport(BaseModel):
    """What the extraction produced, and what it could not do."""

    schema_version: str = "1.0"
    complete: bool = Field(
        description=(
            "True only when there are no errors and no warnings. Files that exist "
            "are not proof that the extraction is complete."
        )
    )
    pages: int = 0
    scanned_pages: list[int] = Field(
        default=[], description="Pages that are a scan (one image covers the page)."
    )
    ocr_engine: str | None = None
    source_language: str | None = None
    tables: TableCounts = TableCounts()
    sentences: SentenceCounts = SentenceCounts()
    images: ImageCounts = ImageCounts()
    image_files: list[ImageRecord] = []
    sentence_problems: list[SentenceProblem] = Field(
        default=[],
        description="Every sentence without a translation or with one to check, in CSV order.",
    )
    files: dict[str, str] = {}
    issues: list[DostIssue] = []
