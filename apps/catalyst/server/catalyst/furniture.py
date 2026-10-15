"""Move repeated page headers and footers out of the document body.

On scanned documents the layout model does not always recognize running
headers and footers ("Annual Report : 2002-03", "Special Relief, Orissa : 3").
They then land in the body as ordinary text, between paragraphs and tables.
Docling can also join such a line to text on another page, because it joins
paragraphs across page breaks.

A text part counts as page furniture when it lies in the top or bottom band of
its page and the same words, with digits ignored, appear in that band on
several pages. Items that Docling already marked as headers or footers count
too, as evidence. Each page part (provenance) of an item is checked by itself:
furniture parts are removed, the other parts and their text stay.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from docling_core.types.doc import (
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    TextItem,
)

_FURNITURE_LABELS = (DocItemLabel.PAGE_HEADER, DocItemLabel.PAGE_FOOTER)
_TOKEN_STRIP = re.compile(r"[^\w#]+", re.UNICODE)

Key = tuple[str, ...]


@dataclass(frozen=True)
class FurnitureResult:
    moved: int
    trimmed: int


@dataclass
class _Part:
    prov: ProvenanceItem
    text: str
    band: DocItemLabel | None
    key: Key


def _key(text: str) -> Key:
    """The words of a line, lowercase, digits as #, punctuation dropped."""
    tokens = []
    for word in text.split():
        normalized = _TOKEN_STRIP.sub("", re.sub(r"\d+", "#", word.lower()))
        if normalized:
            tokens.append(normalized)
    return tuple(tokens)


def _is_distinctive(key: Key) -> bool:
    # A district name and a number ("Sundargarh 254.2") can repeat at the foot of
    # several tables; a running header has at least two words with letters.
    return sum(1 for token in key if any(char.isalpha() for char in token)) >= 2


def _band(
    prov: ProvenanceItem, document: DoclingDocument, band: float
) -> DocItemLabel | None:
    page = document.pages.get(prov.page_no)
    if page is None:
        return None
    height = page.size.height
    box = prov.bbox.to_top_left_origin(page_height=height)
    # Scans have wide, uneven margins: test where the line starts, not all of it.
    if box.t <= band * height:
        return DocItemLabel.PAGE_HEADER
    if box.b >= (1 - band) * height:
        return DocItemLabel.PAGE_FOOTER
    return None


def _parts(item: TextItem, document: DoclingDocument, band: float) -> list[_Part]:
    if len(item.prov) == 1:
        texts = [item.text]
    else:
        texts = [item.orig[prov.charspan[0] : prov.charspan[1]] for prov in item.prov]
    return [
        _Part(
            prov=prov,
            text=text.strip(),
            band=_band(prov, document, band),
            key=_key(text),
        )
        for prov, text in zip(item.prov, texts)
    ]


def move_repeated_furniture(
    document: DoclingDocument, *, band: float = 0.18, min_pages: int = 3
) -> FurnitureResult:
    """Mark repeated header and footer text as furniture. Changes `document` in place."""
    if len(document.pages) < min_pages:
        return FurnitureResult(0, 0)

    candidates: list[tuple[TextItem, list[_Part]]] = []
    pages_by_key: dict[Key, set[int]] = defaultdict(set)
    for item in document.texts:
        if not item.prov:
            continue
        if item.label in _FURNITURE_LABELS:
            pages_by_key[_key(item.text)].add(item.prov[0].page_no)
            continue
        if item.content_layer != ContentLayer.BODY:
            continue
        parts = _parts(item, document, band)
        if any(part.band for part in parts):
            candidates.append((item, parts))
            for part in parts:
                if part.band:
                    pages_by_key[part.key].add(part.prov.page_no)

    repeated = {
        key
        for key, pages in pages_by_key.items()
        if len(pages) >= min_pages and _is_distinctive(key)
    }

    moved = trimmed = 0
    for item, parts in candidates:
        furniture = [part.band is not None and part.key in repeated for part in parts]
        if all(furniture):
            item.label = parts[0].band or DocItemLabel.PAGE_HEADER
            item.content_layer = ContentLayer.FURNITURE
            moved += 1
        elif any(furniture):
            _keep_parts(
                item, [part for part, drop in zip(parts, furniture) if not drop]
            )
            trimmed += 1
    return FurnitureResult(moved, trimmed)


def _keep_parts(item: TextItem, parts: list[_Part]) -> None:
    """Rebuild the text and provenance of an item from the parts that stay."""
    texts, provs, start = [], [], 0
    for part in parts:
        end = start + len(part.text)
        provs.append(part.prov.model_copy(update={"charspan": (start, end)}))
        texts.append(part.text)
        start = end + 1  # the joining space
    item.text = item.orig = " ".join(texts)
    item.prov = provs
