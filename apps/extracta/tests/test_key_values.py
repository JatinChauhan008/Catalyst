"""Labels and values of a key/value block stay on one line.

The layout is the "A. Type of Calamity : Drought" block of a scanned annual
report, as Docling groups it when the OCR returns labels and values as
separate boxes: the labels in a list, the values after it.
"""

from __future__ import annotations

from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DoclingDocument,
    GroupLabel,
    ProvenanceItem,
    Size,
)
from extracta.key_values import join_key_values

H = 850.0


def _prov(left: float, top: float, right: float, text: str) -> ProvenanceItem:
    box = BoundingBox(
        l=left, t=top, r=right, b=top + 15, coord_origin=CoordOrigin.TOPLEFT
    )
    return ProvenanceItem(
        page_no=1, bbox=box.to_bottom_left_origin(H), charspan=(0, len(text))
    )


def _block(rows: list[tuple[str, str | None]]) -> DoclingDocument:
    doc = DoclingDocument(name="report")
    doc.add_page(page_no=1, size=Size(width=600, height=H))
    area = doc.add_group(label=GroupLabel.KEY_VALUE_AREA)
    labels = doc.add_group(label=GroupLabel.LIST, parent=area)
    for row, (label, _) in enumerate(rows):
        doc.add_list_item(
            text=label, parent=labels, prov=_prov(30, 487 + 17 * row, 180, label)
        )
    for row, (_, value) in enumerate(rows):
        if value is not None:
            doc.add_text(
                label="text",
                text=value,
                parent=area,
                prov=_prov(270, 490 + 17 * row, 410, value),
            )
    return doc


def test_each_label_gets_the_value_on_its_row() -> None:
    doc = _block(
        [
            ("Type of Calamity", "Drought"),
            ("Time, Date(s) of Occurrence", "June, July & August 2002"),
            ("Magnitude & Impact", "Drought was severest."),
            ("Intensity & Magnitude", None),
        ]
    )
    assert join_key_values(doc) == 3
    assert [item.text for item in doc.texts] == [
        "Type of Calamity : Drought",
        "Time, Date(s) of Occurrence : June, July & August 2002",
        "Magnitude & Impact : Drought was severest.",
        "Intensity & Magnitude",
    ]


def test_rows_that_are_already_joined_stay_as_they_are() -> None:
    doc = _block(
        [
            ("Type of Calamity : Drought", None),
            ("Magnitude & Impact : Drought was severest.", None),
        ]
    )
    assert join_key_values(doc) == 0
    assert [item.text for item in doc.texts] == [
        "Type of Calamity : Drought",
        "Magnitude & Impact : Drought was severest.",
    ]
