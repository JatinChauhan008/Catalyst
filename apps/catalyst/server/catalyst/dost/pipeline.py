"""Write the three DOST outputs of a converted document and the report.

<target>/document_tables.md       every table, in reading order
<target>/document_sentences.csv   original_sentence, english_translation
<target>/images/image_001.png     every image, in reading order
<target>/extraction_report.json   counts, limits, errors, uncertain content
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from docling_core.types.doc import DoclingDocument, TableItem

from catalyst.dost.images import extract_images
from catalyst.dost.models import DostIssue, DostReport, DostSettings, SentenceCounts
from catalyst.dost.sentences import CollectedText, collect_sentences
from catalyst.dost.tables_md import tables_markdown
from catalyst.dost.translate import (
    SarvamTranslator,
    Translation,
    copy_or_skip,
    numbers_differ,
)
from catalyst.models import TableRecord

TABLES_FILE = "document_tables.md"
SENTENCES_FILE = "document_sentences.csv"
IMAGES_DIR = "images"
REPORT_FILE = "extraction_report.json"

# Row numbers listed in one issue message at most.
_MAX_ROWS_LISTED = 15


@dataclass
class DostInput:
    """The converted document and what the converter knows about it."""

    document: DoclingDocument
    source_name: str
    tables: list[TableRecord]
    table_items: dict[str, list[TableItem]]
    pdf_bytes: bytes | None = None
    ocr_engine: str | None = None
    ocr_language: str | None = None
    sarvam_api_key: str | None = None
    sarvam_base_url: str = "https://api.sarvam.ai"
    conversion_errors: tuple[str, ...] = ()
    partial: bool = False
    # Why the OCR language was chosen, when Catalyst chose it from a font.
    language_note: str | None = None


def run_dost(source: DostInput, settings: DostSettings, target: Path) -> DostReport:
    target.mkdir(parents=True, exist_ok=True)
    issues: list[DostIssue] = []
    document = source.document

    if source.language_note:
        issues.append(
            DostIssue(
                severity="info",
                component="document",
                message=f"No language was given; OCR language {source.language_note}.",
            )
        )
    if source.partial:
        issues.append(
            DostIssue(
                severity="error",
                component="document",
                message="The conversion was only partly successful; some pages or items may be missing.",
            )
        )
    issues += [
        DostIssue(severity="error", component="document", message=message)
        for message in source.conversion_errors
    ]

    # 1. Tables.
    markdown, table_counts, table_issues = tables_markdown(
        source.tables, source.table_items, document, source.source_name
    )
    (target / TABLES_FILE).write_text(markdown, encoding="utf-8")
    issues += table_issues

    # 2. Images (first: it also finds the scanned pages).
    images = extract_images(document, source.pdf_bytes, settings, target / IMAGES_DIR)
    issues += images.issues
    if images.scanned_pages:
        pages = ", ".join(map(str, images.scanned_pages))
        if source.ocr_engine:
            issues.append(
                DostIssue(
                    severity="info",
                    component="document",
                    message=f"Scanned pages {pages}: the text comes from OCR ({source.ocr_engine}). Check it against the page.",
                )
            )
        else:
            issues.append(
                DostIssue(
                    severity="error",
                    component="document",
                    message=f"Scanned pages {pages}, but OCR is off: their text is missing.",
                )
            )

    # 3. Sentences and translations.
    language = settings.source_language or source.ocr_language
    collected = collect_sentences(document, source.tables)
    originals = [sentence.text for sentence in collected.sentences]
    translator = None
    if settings.translate and source.sarvam_api_key:
        translator = SarvamTranslator(
            api_key=source.sarvam_api_key,
            base_url=source.sarvam_base_url,
            workers=settings.translate_workers,
        )
        translations = translator.translate_all(originals, language)
    else:
        reason = (
            "Translation is off."
            if not settings.translate
            else "No Sarvam API key: set SARVAM_API_KEY to translate."
        )
        translations = [copy_or_skip(text, "disabled", reason) for text in originals]

    # UTF-8 with a byte order mark: without it, Excel reads the file in the
    # ANSI code page and shows Odia, Hindi, ... as "à¬..." symbols.
    with (target / SENTENCES_FILE).open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(["original_sentence", "english_translation"])
        writer.writerows(
            (original, translation.text)
            for original, translation in zip(originals, translations)
        )

    sentence_counts = SentenceCounts(
        sentences=len(originals),
        by_status=dict(Counter(t.status for t in translations)),
        characters_sent=translator.characters_sent if translator else 0,
        skipped_items=collected.skipped,
    )
    issues += _sentence_issues(originals, translations, sentence_counts, collected)

    # Standing limits, so that a reader does not take the files as complete.
    issues += [
        DostIssue(
            severity="info",
            component="images",
            message=(
                "Vector graphics are rendered only where the layout model found a "
                "picture; other drawings (lines, borders, shapes) are not saved."
            ),
        ),
        DostIssue(
            severity="info",
            component="images",
            message=(
                "Transparency masks of embedded images are not applied; such images "
                "can show a black or white background."
            ),
        ),
    ]
    if images.counts.duplicates_skipped:
        issues.append(
            DostIssue(
                severity="info",
                component="images",
                message=f"{images.counts.duplicates_skipped} repeated uses of an image were saved once (see `occurrences`).",
            )
        )
    if images.counts.too_small_skipped:
        issues.append(
            DostIssue(
                severity="info",
                component="images",
                message=f"{images.counts.too_small_skipped} embedded images smaller than {settings.min_image_px} px were skipped.",
            )
        )
    if images.counts.page_scans_skipped:
        issues.append(
            DostIssue(
                severity="info",
                component="images",
                message=(
                    f"{images.counts.page_scans_skipped} page scans were not saved as images; "
                    "the pictures found on those pages were cut out instead."
                ),
            )
        )

    report = DostReport(
        complete=not any(issue.severity != "info" for issue in issues),
        pages=len(document.pages),
        scanned_pages=images.scanned_pages,
        ocr_engine=source.ocr_engine,
        source_language=language,
        tables=table_counts,
        sentences=sentence_counts,
        images=images.counts,
        image_files=images.records,
        files={
            "tables": TABLES_FILE,
            "sentences": SENTENCES_FILE,
            "images": IMAGES_DIR,
            "report": REPORT_FILE,
        },
        issues=issues,
    )
    (target / REPORT_FILE).write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    return report


def _rows(numbers: list[int]) -> str:
    listed = ", ".join(map(str, numbers[:_MAX_ROWS_LISTED]))
    more = len(numbers) - _MAX_ROWS_LISTED
    return listed + (f" and {more} more" if more > 0 else "")


def _sentence_issues(
    originals: list[str],
    translations: list[Translation],
    counts: SentenceCounts,
    collected: CollectedText,
) -> list[DostIssue]:
    issues: list[DostIssue] = []
    if not originals:
        issues.append(
            DostIssue(
                severity="warn",
                component="sentences",
                message="No written text was found outside the tables.",
            )
        )
    # CSV row numbers: the header is row 1.
    by_status: dict[str, list[int]] = {}
    details: dict[str, str] = {}
    differ: list[int] = []
    for row, (original, translation) in enumerate(
        zip(originals, translations), start=2
    ):
        by_status.setdefault(translation.status, []).append(row)
        if translation.detail:
            details.setdefault(translation.status, translation.detail)
        if translation.status == "translated" and numbers_differ(
            original, translation.text
        ):
            differ.append(row)
    counts.numbers_differ = len(differ)

    for status, severity, what in (
        ("failed", "error", "could not be translated"),
        ("unsupported", "warn", "are in a language that Sarvam does not translate"),
        ("disabled", "warn", "have no translation"),
    ):
        rows = by_status.get(status, [])
        if rows:
            detail = details.get(status)
            issues.append(
                DostIssue(
                    severity=severity,
                    component="translation",
                    message=(
                        f"{len(rows)} sentences {what}; their translation is empty "
                        f"(CSV rows {_rows(rows)})." + (f" {detail}" if detail else "")
                    ),
                )
            )
    if differ:
        issues.append(
            DostIssue(
                severity="warn",
                component="translation",
                message=(
                    f"{len(differ)} translations do not contain all numbers of the "
                    f"original sentence; check them (CSV rows {_rows(differ)})."
                ),
            )
        )
    if collected.duplicates_removed:
        issues.append(
            DostIssue(
                severity="info",
                component="sentences",
                message=f"{collected.duplicates_removed} text blocks read twice at the same place were written once.",
            )
        )
    for kind, number in sorted(collected.skipped.items()):
        issues.append(
            DostIssue(
                severity="info",
                component="sentences",
                message=f"{number} items of kind '{kind}' are not prose and are not in the CSV.",
            )
        )
    return issues
