"""Write all tables of a document into one Markdown file.

A simple table (one header row, no merged cells) becomes a Markdown pipe
table. Any other table becomes an HTML table inside the Markdown file, so
that merged cells and multi-row headers keep their structure and no header
is invented for a table that has none.
"""

from __future__ import annotations

import html

from docling_core.types.doc import DoclingDocument, TableItem

from catalyst.dost.models import DostIssue, TableCounts
from catalyst.models import TableRecord


def tables_markdown(
    records: list[TableRecord],
    items: dict[str, list[TableItem]],
    document: DoclingDocument,
    source_name: str,
) -> tuple[str, TableCounts, list[DostIssue]]:
    """The Markdown text, the counts and the issues of all tables, in reading order."""
    counts = TableCounts(tables=len(records))
    issues: list[DostIssue] = []
    parts = [f"# Tables of {source_name}", ""]
    if not records:
        parts += ["No tables were found in this document.", ""]
        return "\n".join(parts), counts, issues

    for record in records:
        pages = sorted({region.page for region in record.regions})
        page_text = (
            ("page " if len(pages) == 1 else "pages ") + ", ".join(map(str, pages))
            if pages
            else "page unknown"
        )
        parts += [f"## Table {record.index} ({page_text})", ""]
        if record.title:
            parts += [f"**Title:** {_inline(record.title)}", ""]
        if record.caption:
            parts += [f"**Caption:** {_inline(record.caption)}", ""]
        if record.units:
            parts += [f"**Units:** {_inline(record.units)}", ""]

        parts_of_table = items[record.table_id]
        if len(parts_of_table) > 1:
            counts.joined_parts += len(parts_of_table) - 1
            parts += [
                f"*This table runs over {len(parts_of_table)} parts; "
                "the parts are joined.*",
                "",
            ]

        if not record.rows or record.num_cols == 0:
            parts += ["*No cells could be extracted from this table.*", ""]
            issues.append(
                DostIssue(
                    severity="error",
                    component="tables",
                    page=record.page,
                    message=f"Table {record.index}: no cells could be extracted.",
                )
            )
        elif _is_simple(record, parts_of_table):
            parts += [_pipe_table(record), ""]
        else:
            counts.html_tables += 1
            parts += [_html_table(record, parts_of_table), ""]

        for note in record.footnotes:
            parts += [f"> {_inline(note)}", ""]

        if record.quality.status != "ok":
            counts.with_warnings += 1
            reasons = "; ".join(record.quality.reasons)
            parts += [f"*Check this table: {reasons}.*", ""]
            issues.append(
                DostIssue(
                    severity="warn",
                    component="tables",
                    page=record.page,
                    message=f"Table {record.index}: {reasons}.",
                )
            )
    return "\n".join(parts), counts, issues


def _has_spans(table: TableItem) -> bool:
    return any(
        cell.row_span > 1 or cell.col_span > 1 for cell in table.data.table_cells
    )


def _is_simple(record: TableRecord, tables: list[TableItem]) -> bool:
    return record.header_rows == 1 and not any(_has_spans(t) for t in tables)


def _inline(text: str) -> str:
    return " ".join(text.split())


def _cell(text: str) -> str:
    """A cell of a pipe table: one line, with `|` escaped."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "<br>".join(line for line in lines if line).replace("|", "\\|")


def _pipe_table(record: TableRecord) -> str:
    header, *body = record.rows
    lines = [
        "| " + " | ".join(_cell(text) for text in header) + " |",
        "|" + "|".join(" --- " for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(_cell(text) for text in row) + " |" for row in body]
    return "\n".join(lines)


def _html_table(record: TableRecord, tables: list[TableItem]) -> str:
    """An HTML table with the merged cells of the source.

    The parts of a joined table follow each other; a later part's header rows
    are left out when they repeat the header of the first part.
    """
    first_header = record.rows[: record.header_rows]
    lines = ["<table>"]
    for number, table in enumerate(tables):
        grid = [[cell.text for cell in row] for row in table.data.grid]
        skip = 0
        if number > 0 and first_header and grid[: len(first_header)] == first_header:
            skip = len(first_header)
        for row_index, grid_row in enumerate(table.data.grid):
            if row_index < skip:
                continue
            row = []
            for col_index, cell in enumerate(grid_row):
                # A merged cell fills several grid positions; write it once, at
                # its first position. Empty positions are cells without text.
                if (cell.start_row_offset_idx != row_index and cell.row_span > 1) or (
                    cell.start_col_offset_idx != col_index and cell.col_span > 1
                ):
                    continue
                tag = "th" if cell.column_header or cell.row_header else "td"
                attrs = ""
                if cell.row_span > 1:
                    attrs += f' rowspan="{cell.row_span}"'
                if cell.col_span > 1:
                    attrs += f' colspan="{cell.col_span}"'
                text = "<br>".join(
                    html.escape(line.strip())
                    for line in cell.text.splitlines()
                    if line.strip()
                )
                row.append(f"<{tag}{attrs}>{text}</{tag}>")
            lines.append("<tr>" + "".join(row) + "</tr>")
    lines.append("</table>")
    return "\n".join(lines)
