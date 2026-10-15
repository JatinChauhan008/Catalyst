"""Tables keep Sarvam's own structure, and legacy-font text layers go to OCR.

A Hindi PDF in a legacy font (Kruti Dev) has a text layer of Latin letters.
Docling took it as good text, skipped OCR, and its table model built tables
from those letters. Sarvam reads such a page correctly and returns each table
as HTML with its merged cells; that structure must reach the document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from catalyst.models import ConvertRequest
from catalyst.sarvam.tables import (
    SarvamTable,
    apply_sarvam_tables,
    table_data_from_html,
)
from catalyst.scripts import DEVANAGARI, is_garbled
from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableData,
)

TABLE_PAGE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "data"
    / "pdf"
    / "sources"
    / "2305.03393v1-pg9.pdf"
)

# Table 1 of a real Sarvam result for a Hindi PDF: a header cell over two
# rows and a header cell over four columns.
SARVAM_TABLE = (
    '<table>\n<thead>\n<tr>\n<th rowspan="2">पूर्व फसल</th>\n'
    '<th colspan="4">कृषि स्थितियां/सिंचाई का स्रोत</th>\n</tr>\n'
    "<tr>\n<th>कुएं</th>\n<th>नहर</th>\n<th>टैंक</th>\n<th>अवशिष्ट आर्द्रता</th>\n</tr>\n"
    "</thead>\n<tbody>\n<tr>\n<td>धान</td>\n<td>1</td>\n<td>2</td>\n<td>-</td>\n"
    "<td>-</td>\n</tr>\n<tr>\n<td>गैर-धान</td>\n<td>3</td>\n<td>4</td>\n<td>5</td>\n"
    "<td>6<br/>(रबी)</td>\n</tr>\n</tbody>\n</table>"
)


def test_html_spans_land_in_the_right_grid_cells() -> None:
    data = table_data_from_html(SARVAM_TABLE)
    assert data is not None
    assert (data.num_rows, data.num_cols) == (4, 5)
    grid = [[cell.text for cell in row] for row in data.grid]
    assert grid == [
        ["पूर्व फसल", *["कृषि स्थितियां/सिंचाई का स्रोत"] * 4],
        ["पूर्व फसल", "कुएं", "नहर", "टैंक", "अवशिष्ट आर्द्रता"],
        ["धान", "1", "2", "-", "-"],
        ["गैर-धान", "3", "4", "5", "6 (रबी)"],
    ]
    headers = [[cell.column_header for cell in row] for row in data.grid]
    assert headers[:2] == [[True] * 5] * 2 and not any(headers[2] + headers[3])


def _document_with_tables(*boxes: tuple[int, BoundingBox]) -> DoclingDocument:
    doc = DoclingDocument(name="t")
    for page_no in {page for page, _ in boxes}:
        doc.add_page(page_no=page_no, size=Size(width=600, height=800))
    for page_no, box in boxes:
        doc.add_table(
            data=TableData(num_rows=1, num_cols=1),
            label=DocItemLabel.TABLE,
            prov=ProvenanceItem(
                page_no=page_no, bbox=box.to_bottom_left_origin(800), charspan=(0, 0)
            ),
        )
    return doc


def _box(left: float, top: float, right: float, bottom: float) -> BoundingBox:
    return BoundingBox(
        l=left, t=top, r=right, b=bottom, coord_origin=CoordOrigin.TOPLEFT
    )


def test_each_table_takes_the_sarvam_table_at_its_place() -> None:
    doc = _document_with_tables(
        (1, _box(50, 100, 550, 300)),
        (1, _box(50, 500, 550, 700)),
        (2, _box(50, 100, 550, 300)),
    )
    sarvam = [
        # Slightly larger than the second table on page 1.
        SarvamTable(page_no=1, bbox=_box(40, 490, 560, 720), html=SARVAM_TABLE),
        # The same place as the first table, but on another page.
        SarvamTable(page_no=3, bbox=_box(50, 100, 550, 300), html=SARVAM_TABLE),
    ]
    changed = apply_sarvam_tables(doc, sarvam)
    assert changed == {doc.tables[1].self_ref}
    assert [t.data.num_cols for t in doc.tables] == [1, 5, 1]


@pytest.mark.parametrize(
    ("text", "garbled"),
    [
        # "कृषि स्थिति आधारित विस्तार" in the Kruti Dev font.
        ("d`f\"k fLFkfr vk/kkfjr foLrkj ¼,Q,lchbZ½ lajpuk mn~ns'; izLrkouk", True),
        ("कृषि स्थिति आधारित विस्तार (एफएसबीई) संरचना उद्देश्य प्रस्तावना", False),
        # Hindi text with English terms and numbers stays as it is.
        ("तालिका 2 : महबूबनगर जिले (Andhra Pradesh) की रेंडी फसल NARP 1958", False),
        ("4.0 FSBE", False),  # too short to judge
    ],
)
def test_legacy_font_text_is_garbled_for_devanagari(text: str, garbled: bool) -> None:
    assert is_garbled(text, DEVANAGARI) is garbled


def test_hindi_pdf_with_latin_text_layer_gets_ocr_and_sarvam_tables(
    service, fake_sarvam
) -> None:
    """The test page has a Latin text layer; for a `hi-IN` document that is a
    legacy-font layer. It must be read with Sarvam, and the table must take
    Sarvam's HTML structure instead of the table model's."""
    fake_sarvam.tables = [((0.22, 0.42, 0.78, 0.60), SARVAM_TABLE)]
    sarvam = {
        "__variant__": "SarvamOcrOptions",
        "lang": ["hi-IN"],
        "api_key": "test-key",
        "base_url": fake_sarvam.base_url,
        "poll_interval_seconds": 0.05,
    }
    try:
        envelope = service.convert(
            TABLE_PAGE.name,
            TABLE_PAGE.read_bytes(),
            ConvertRequest.model_validate(
                {
                    "export": {
                        "to_formats": ["json"],
                        "image_export_mode": "placeholder",
                    },
                    "tables": {"enabled": True},
                    "formats": {"pdf": {"pipeline_options": {"ocr_options": sarvam}}},
                }
            ),
        )
    finally:
        fake_sarvam.tables = []
    assert envelope.status == "success", envelope.errors
    document = json.loads(envelope.outputs[0].content)
    texts = " ".join(item["text"] for item in document["texts"])
    # Sarvam's text, not the PDF text layer ("Table" is a word of that layer).
    assert any(line in texts for line in fake_sarvam.lines)
    assert "Table" not in texts
    # The table text lives in the table only.
    assert "पूर्व फसल" not in texts and "रबी" not in texts
    assert envelope.processing.sarvam_tables == 1
    [table] = envelope.tables
    assert table.extraction.structure == "sarvam"
    assert table.extraction.method == "ocr"
    assert (table.num_rows, table.num_cols) == (4, 5)
    assert table.preview[2] == ["धान", "1", "2", "-", "-"]
