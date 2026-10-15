"""Content and structure checks on a converted document."""

from __future__ import annotations

from docling_core.types.doc import (
    DocItem,
    DoclingDocument,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

from catalyst.models import (
    DocumentStats,
    OutputItem,
    ValidationCheck,
    ValidationReport,
    ValidationSettings,
)
from docling.datamodel.base_models import ConversionStatus


def document_stats(document: DoclingDocument) -> DocumentStats:
    stats = DocumentStats(pages=len(document.pages))
    pages_with_content: set[int] = set()
    for item, _level in document.iterate_items(with_groups=False):
        if isinstance(item, DocItem):
            pages_with_content.update(prov.page_no for prov in item.prov)
        if isinstance(item, TableItem):
            stats.tables += 1
        elif isinstance(item, PictureItem):
            stats.pictures += 1
        elif isinstance(item, TextItem):
            stats.text_items += 1
            stats.characters += len(item.text)
            if isinstance(item, SectionHeaderItem | TitleItem):
                stats.headings += 1
    stats.empty_pages = sorted(set(document.pages) - pages_with_content)
    return stats


def validate(
    document: DoclingDocument,
    status: ConversionStatus,
    stats: DocumentStats,
    outputs: list[OutputItem],
    settings: ValidationSettings,
) -> ValidationReport:
    checks: list[ValidationCheck] = []

    if status == ConversionStatus.SUCCESS:
        checks.append(
            ValidationCheck(
                id="conversion_status", status="pass", message="Conversion succeeded."
            )
        )
    elif status == ConversionStatus.PARTIAL_SUCCESS:
        checks.append(
            ValidationCheck(
                id="conversion_status",
                status="fail" if settings.fail_on_partial_success else "warn",
                message="Conversion succeeded only partially. See the errors.",
            )
        )
    else:
        checks.append(
            ValidationCheck(
                id="conversion_status",
                status="fail",
                message=f"Conversion status is {status.value}.",
            )
        )

    has_content = (
        stats.characters >= settings.min_text_chars
        or stats.tables > 0
        or stats.pictures > 0
    )
    checks.append(
        ValidationCheck(
            id="has_content",
            status="pass" if has_content else "fail",
            message=(
                f"{stats.characters} characters, {stats.tables} tables, {stats.pictures} pictures."
                if has_content
                else "The document has no text, tables or pictures. A scanned file may need OCR."
            ),
        )
    )

    if settings.warn_empty_pages and stats.pages:
        checks.append(
            ValidationCheck(
                id="empty_pages",
                status="warn" if stats.empty_pages else "pass",
                message=(
                    f"Pages without content: {', '.join(map(str, stats.empty_pages))}."
                    if stats.empty_pages
                    else "Every page has content."
                ),
            )
        )

    empty_tables = [
        table.self_ref
        for table in document.tables
        if table.data is None or not table.data.table_cells
    ]
    if stats.tables:
        checks.append(
            ValidationCheck(
                id="table_structure",
                status="warn" if empty_tables else "pass",
                message=(
                    f"{len(empty_tables)} of {stats.tables} tables have no cells."
                    if empty_tables
                    else f"All {stats.tables} tables have cells."
                ),
            )
        )

    # A table that should have columns but came out with one: its rows were read
    # as single lines (for example by an OCR engine without word boxes).
    flat_tables = [
        table
        for table in document.tables
        if table.data is not None
        and table.data.num_cols == 1
        and table.data.num_rows >= 3
    ]
    if stats.tables:
        checks.append(
            ValidationCheck(
                id="table_columns",
                status="warn" if flat_tables else "pass",
                message=(
                    f"{len(flat_tables)} of {stats.tables} tables have only one column; "
                    "their columns may be merged."
                    if flat_tables
                    else "Every table has more than one column."
                ),
            )
        )

    limit = settings.warn_missing_headings_above_chars
    if limit is not None and stats.characters > limit:
        checks.append(
            ValidationCheck(
                id="headings",
                status="pass" if stats.headings else "warn",
                message=(
                    f"{stats.headings} headings found."
                    if stats.headings
                    else "Long document without headings. The structure may be flat."
                ),
            )
        )

    empty_outputs = [output.format for output in outputs if output.size_bytes == 0]
    if outputs:
        checks.append(
            ValidationCheck(
                id="outputs",
                status="fail" if empty_outputs else "pass",
                message=(
                    f"Empty outputs: {', '.join(empty_outputs)}."
                    if empty_outputs
                    else f"{len(outputs)} outputs written."
                ),
            )
        )

    return ValidationReport(
        passed=all(check.status != "fail" for check in checks), checks=checks
    )
