"""Running headers and footers that the layout model missed leave the body.

The cases come from a scanned annual report: headers and footers labelled as
plain text, a footer joined to body text from an earlier page, and a chart
label that repeats near the foot of several pages but is real content.
"""

from __future__ import annotations

from docling_core.types.doc import (
    BoundingBox,
    ContentLayer,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)
from catalyst.furniture import move_repeated_furniture

W, H = 600.0, 850.0


def _prov(
    page: int, top: float, bottom: float, text: str, start: int = 0
) -> ProvenanceItem:
    box = BoundingBox(l=50, t=top, r=550, b=bottom, coord_origin=CoordOrigin.TOPLEFT)
    return ProvenanceItem(
        page_no=page,
        bbox=box.to_bottom_left_origin(H),
        charspan=(start, start + len(text)),
    )


def _text(
    doc: DoclingDocument, text: str, page: int, top: float, label=DocItemLabel.TEXT
):
    layer = ContentLayer.BODY if label == DocItemLabel.TEXT else ContentLayer.FURNITURE
    return doc.add_text(
        label=label,
        text=text,
        prov=_prov(page, top, top + 14, text),
        content_layer=layer,
    )


def _report() -> DoclingDocument:
    doc = DoclingDocument(name="report")
    for page in range(1, 6):
        doc.add_page(page_no=page, size=Size(width=W, height=H))
        # Header 9-12% from the top, footer at 88-93%: a scan's wide margins.
        _text(doc, "Annual Report : 2002-03", page, 80 + page * 4)
        _text(doc, f"The body text of page {page}.", page, 400)
        _text(doc, f"Special Relief, Orissa : {page}", page, 750 + page * 4)
    # One footer that Docling did recognize counts as evidence too.
    _text(doc, "Special Relief, Orissa : 9", 5, 790, label=DocItemLabel.PAGE_FOOTER)
    # The last district of a list, near the foot of three pages: content.
    for page in (2, 3, 4):
        _text(doc, "Sundargarh 254.2", page, 735)
    return doc


def test_repeated_headers_and_footers_leave_the_body() -> None:
    doc = _report()
    result = move_repeated_furniture(doc)

    body = [item.text for item in doc.texts if item.content_layer == ContentLayer.BODY]
    assert not any("Annual Report" in text or "Special Relief" in text for text in body)
    assert body.count("Sundargarh 254.2") == 3
    assert "The body text of page 3." in body
    assert result.moved == 10
    footer = next(
        item for item in doc.texts if item.text == "Special Relief, Orissa : 2"
    )
    assert footer.label == DocItemLabel.PAGE_FOOTER


def test_footer_joined_to_text_of_another_page_is_cut_off() -> None:
    doc = _report()
    # Docling joined a chart label (page 2, mid page) and the footer of page 3.
    first, second = "Districts Rainfall in mm", "Special Relief, Orissa : 7"
    item = doc.add_text(
        label=DocItemLabel.TEXT,
        text=f"{first} {second}",
        prov=_prov(2, 300, 314, first),
    )
    item.prov.append(_prov(3, 790, 804, second, start=len(first) + 1))

    result = move_repeated_furniture(doc)

    assert result.trimmed == 1
    assert item.text == first
    assert item.content_layer == ContentLayer.BODY
    assert [prov.page_no for prov in item.prov] == [2]
    assert item.prov[0].charspan == (0, len(first))


def test_short_documents_are_left_alone() -> None:
    doc = DoclingDocument(name="letter")
    for page in (1, 2):
        doc.add_page(page_no=page, size=Size(width=W, height=H))
        _text(doc, "Annual Report : 2002-03", page, 80)
    assert move_repeated_furniture(doc).moved == 0
