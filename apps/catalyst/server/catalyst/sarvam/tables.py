"""Sarvam's own table structure for the tables of a converted document.

Sarvam returns a table block as an HTML ``<table>`` with its merged cells
(``rowspan``, ``colspan``), read from the page image. Docling's table model
builds a table from text cells with word boxes instead. Sarvam gives one box
per block, so for an OCR'd table that model must rely on RapidOCR words (weak
for Indic scripts) or on the PDF text layer (garbage for legacy fonts). Where
Sarvam read a table, its structure replaces the one of the table model.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser

from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    TableCell,
    TableData,
    TableItem,
)

# A Sarvam table and a document table are the same table when the overlap
# covers this share of the smaller one.
_MIN_OVERLAP = 0.6
# Spans above this are taken as errors in the HTML and clipped.
_MAX_SPAN = 1000


@dataclass(frozen=True)
class SarvamTable:
    """A table that Sarvam read on a page.

    Attributes:
        page_no: The page number, from 1 (as in the document provenance).
        bbox: The table box in page coordinates, top-left origin.
        html: The ``<table>`` element as Sarvam returns it.
    """

    page_no: int
    bbox: BoundingBox
    html: str


@dataclass
class _HtmlCell:
    text: str
    row_span: int
    col_span: int
    header: bool


class _TableReader(HTMLParser):
    """Collects the rows of the first ``<table>``. Nested tables become cell text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[_HtmlCell]] = []
        self._depth = 0
        self._in_head = False
        self._cell: _HtmlCell | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
        if self._depth != 1:
            return
        if tag == "thead":
            self._in_head = True
        elif tag == "tr":
            self._end_cell()
            self.rows.append([])
        elif tag in ("td", "th"):
            self._end_cell()
            if not self.rows:
                self.rows.append([])
            values = dict(attrs)
            self._cell = _HtmlCell(
                text="",
                row_span=_span(values.get("rowspan")),
                col_span=_span(values.get("colspan")),
                header=tag == "th" or self._in_head,
            )
            self._parts = []
        elif tag == "br":
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 1 and tag in ("td", "th", "tr"):
            self._end_cell()
        if self._depth == 1 and tag == "thead":
            self._in_head = False
        if tag == "table":
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._end_cell()

    def _end_cell(self) -> None:
        if self._cell is None:
            return
        self._cell.text = " ".join("".join(self._parts).split())
        self.rows[-1].append(self._cell)
        self._cell = None


def _span(value: str | None) -> int:
    try:
        return min(max(1, int(value or 1)), _MAX_SPAN)
    except ValueError:
        return 1


def table_data_from_html(html: str) -> TableData | None:
    """The grid of an HTML table, with merged cells. None when it has no cells."""
    reader = _TableReader()
    reader.feed(html)
    reader.close()
    rows = [row for row in reader.rows if row]
    if not rows:
        return None

    # Place each cell in the first free slot of its row; spans block later slots.
    taken: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    for row_index, row in enumerate(rows):
        column = 0
        for html_cell in row:
            while (row_index, column) in taken:
                column += 1
            row_span = min(html_cell.row_span, len(rows) - row_index)
            for r in range(row_index, row_index + row_span):
                for c in range(column, column + html_cell.col_span):
                    taken.add((r, c))
            cells.append(
                TableCell(
                    text=html_cell.text,
                    row_span=row_span,
                    col_span=html_cell.col_span,
                    start_row_offset_idx=row_index,
                    end_row_offset_idx=row_index + row_span,
                    start_col_offset_idx=column,
                    end_col_offset_idx=column + html_cell.col_span,
                    column_header=html_cell.header,
                )
            )
            column += html_cell.col_span
    num_cols = max(c for _, c in taken) + 1
    return TableData(num_rows=len(rows), num_cols=num_cols, table_cells=cells)


def apply_sarvam_tables(
    document: DoclingDocument, tables: list[SarvamTable]
) -> set[str]:
    """Give each document table the structure of the Sarvam table at its place.

    A document table takes the Sarvam table on the same page that overlaps it
    most, when that overlap covers most of the smaller of the two boxes. Each
    Sarvam table is used once. Returns the references of the tables changed.
    """
    unused = list(tables)
    changed: set[str] = set()
    for item, _ in document.iterate_items(with_groups=False):
        if not isinstance(item, TableItem) or len(item.prov) != 1:
            continue
        prov = item.prov[0]
        page = document.pages.get(prov.page_no)
        if page is None:
            continue
        box = prov.bbox.to_top_left_origin(page_height=page.size.height)
        best, best_score = None, 0.0
        for candidate in unused:
            if candidate.page_no != prov.page_no:
                continue
            score = _overlap_of_smaller(box, candidate.bbox)
            if score >= _MIN_OVERLAP and score > best_score:
                best, best_score = candidate, score
        if best is None:
            continue
        data = table_data_from_html(best.html)
        if data is None:
            continue
        unused.remove(best)
        item.data = data
        changed.add(item.self_ref)
    return changed


def _overlap_of_smaller(a: BoundingBox, b: BoundingBox) -> float:
    assert a.coord_origin == b.coord_origin == CoordOrigin.TOPLEFT
    smaller = min(a.area(), b.area())
    if smaller <= 0:
        return 0.0
    return a.intersection_area_with(b) / smaller
