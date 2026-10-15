"""Join each label of a key/value region with the value on the same row.

Docling's layout model marks blocks such as

    A. Type of Calamity            :   Drought
    B. Time, Date(s) of Occurrence :   June, July & August 2002

as a `key_value_region`. The reading-order step puts its parts into a
`key_value_area` group column by column, so the output lists all labels first
and all values after them. Whether that happens depends on the OCR: an engine
that returns each row as one line keeps the pairs, one that returns the
columns as separate boxes splits them.

This step pairs them by position: a value is a text to the right of a label
whose vertical extent overlaps the label's row. The value text is appended to
the label ("Type of Calamity : Drought") and the value item is removed.
"""

from __future__ import annotations

import re

from docling_core.types.doc import (
    BoundingBox,
    DoclingDocument,
    GroupItem,
    GroupLabel,
    NodeItem,
    TextItem,
)

_DASHES = "\N{EN DASH}\N{EM DASH}"
_PUNCTUATION_ONLY = re.compile(r"^[\s:;.\-" + _DASHES + r"]*$")
_MIN_ROW_OVERLAP = 0.5


def _text_items(group: NodeItem, document: DoclingDocument) -> list[TextItem]:
    items: list[TextItem] = []
    for ref in group.children:
        child = ref.resolve(document)
        if isinstance(child, GroupItem):
            items.extend(_text_items(child, document))
        elif isinstance(child, TextItem) and len(child.prov) == 1:
            items.append(child)
    return items


def _box(item: TextItem, document: DoclingDocument) -> BoundingBox:
    prov = item.prov[0]
    return prov.bbox.to_top_left_origin(
        page_height=document.pages[prov.page_no].size.height
    )


def _row_overlap(a: BoundingBox, b: BoundingBox) -> float:
    shared = min(a.b, b.b) - max(a.t, b.t)
    return shared / max(min(a.height, b.height), 1e-6)


def _left_partner(
    item: TextItem, boxes: dict[str, BoundingBox], items: list[TextItem]
) -> TextItem | None:
    """The item on the same row that ends left of `item`, nearest first."""
    box = boxes[item.self_ref]
    best, best_gap = None, float("inf")
    for other in items:
        if other is item or other.prov[0].page_no != item.prov[0].page_no:
            continue
        other_box = boxes[other.self_ref]
        if other_box.r > box.l or _row_overlap(box, other_box) < _MIN_ROW_OVERLAP:
            continue
        gap = box.l - other_box.r
        if gap < best_gap:
            best, best_gap = other, gap
    return best


def join_key_values(document: DoclingDocument) -> int:
    """Join labels and values inside key/value groups. Returns the rows joined."""
    joined = 0
    for group in document.groups:
        if group.label != GroupLabel.KEY_VALUE_AREA:
            continue
        items = _text_items(group, document)
        boxes = {item.self_ref: _box(item, document) for item in items}

        # Walk each row from its first item (the label) to the right.
        values_of: dict[str, list[TextItem]] = {}
        for item in items:
            partner = _left_partner(item, boxes, items)
            if partner is None:
                continue
            while (left := _left_partner(partner, boxes, items)) is not None:
                partner = left
            values_of.setdefault(partner.self_ref, []).append(item)

        removed: list[NodeItem] = []
        for label in items:
            values = sorted(
                values_of.get(label.self_ref, []), key=lambda v: boxes[v.self_ref].l
            )
            if not values:
                continue
            words = [
                v.text.strip() for v in values if not _PUNCTUATION_ONLY.match(v.text)
            ]
            text = label.text.rstrip()
            if words:
                separator = (
                    " " if text.endswith(":") or words[0].startswith(":") else " : "
                )
                text = f"{text}{separator}{' '.join(words)}"
            label.text = label.orig = text
            label.prov[0] = label.prov[0].model_copy(
                update={"charspan": (0, len(text))}
            )
            removed.extend(values)
            joined += 1
        if removed:
            document.delete_items(node_items=removed)
    return joined
