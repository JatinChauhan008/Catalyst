"""Collect the written text outside tables, in reading order, and split it into sentences.

Table cells, table captions, table footnotes and the title line found above a
table go to the tables file, not here. Text that the layout model found
inside a picture (labels of a chart) and code or formulas are left out and
counted in the report. Page headers and footers are not body text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from docling_core.types.doc import (
    DocItem,
    DocItemLabel,
    DoclingDocument,
    NodeItem,
    PictureItem,
    TableItem,
    TextItem,
)

from catalyst.models import TableRecord

# Prose labels. Headings are kept whole (one row); the others are split.
_HEADINGS = frozenset({DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER})
_PROSE = frozenset(
    {
        DocItemLabel.TEXT,
        DocItemLabel.PARAGRAPH,
        DocItemLabel.LIST_ITEM,
        DocItemLabel.CAPTION,
        DocItemLabel.FOOTNOTE,
        DocItemLabel.REFERENCE,
        DocItemLabel.HANDWRITTEN_TEXT,
        DocItemLabel.CHECKBOX_SELECTED,
        DocItemLabel.CHECKBOX_UNSELECTED,
    }
)
_SKIPPED_KINDS = {
    DocItemLabel.CODE: "code",
    DocItemLabel.FORMULA: "formula",
}


@dataclass(frozen=True)
class Sentence:
    text: str
    page: int | None


@dataclass
class CollectedText:
    sentences: list[Sentence]
    skipped: dict[str, int]
    duplicates_removed: int


def collect_sentences(
    document: DoclingDocument, tables: list[TableRecord]
) -> CollectedText:
    items: list[NodeItem] = [
        item for item, _ in document.iterate_items(with_groups=False)
    ]
    excluded = _table_text_refs(document, items, tables)
    inside_pictures = _descendant_refs(
        document, [item for item in items if isinstance(item, PictureItem)]
    )

    sentences: list[Sentence] = []
    skipped: dict[str, int] = {}
    seen: set[tuple[int | None, str, tuple[float, ...] | None]] = set()
    duplicates = 0
    for item in items:
        if item.self_ref in excluded or isinstance(item, TableItem | PictureItem):
            continue
        if not isinstance(item, TextItem):
            # Key-value areas, forms and other structured items.
            kind = item.label.value if isinstance(item, DocItem) else "other"
            skipped[kind] = skipped.get(kind, 0) + 1
            continue
        text = " ".join(item.text.split())
        if not text:
            continue
        if item.self_ref in inside_pictures and item.label != DocItemLabel.CAPTION:
            skipped["text inside a picture"] = (
                skipped.get("text inside a picture", 0) + 1
            )
            continue
        if item.label in _SKIPPED_KINDS:
            kind = _SKIPPED_KINDS[item.label]
            skipped[kind] = skipped.get(kind, 0) + 1
            continue
        if item.label not in _HEADINGS and item.label not in _PROSE:
            kind = str(item.label.value)
            skipped[kind] = skipped.get(kind, 0) + 1
            continue

        page = item.prov[0].page_no if item.prov else None
        # The same text at the same place twice is one text read twice
        # (for example by the text layer and by OCR).
        box = (
            tuple(round(v) for v in item.prov[0].bbox.as_tuple()) if item.prov else None
        )
        key = (page, text, box)
        if box is not None and key in seen:
            duplicates += 1
            continue
        seen.add(key)

        if item.label in _HEADINGS:
            sentences.append(Sentence(text, page))
        else:
            sentences.extend(Sentence(part, page) for part in split_sentences(text))
    return CollectedText(sentences, skipped, duplicates)


def _descendant_refs(document: DoclingDocument, roots: list[NodeItem]) -> set[str]:
    refs: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        for child in node.children:
            resolved = child.resolve(document)
            refs.add(resolved.self_ref)
            stack.append(resolved)
    return refs


def _table_text_refs(
    document: DoclingDocument, items: list[NodeItem], tables: list[TableRecord]
) -> set[str]:
    """Text that belongs to a table: its cells' items, captions, footnotes and title."""
    table_items = [item for item in items if isinstance(item, TableItem)]
    refs = _descendant_refs(document, table_items)
    for table in table_items:
        refs.update(ref.cref for ref in table.captions)
        refs.update(ref.cref for ref in table.footnotes)
    titles = {record.title for record in tables if record.title}
    for position, item in enumerate(items):
        if not isinstance(item, TableItem):
            continue
        # The title is one of the few items right above the table.
        for before in reversed(items[max(0, position - 4) : position]):
            if isinstance(before, TextItem) and before.text.strip() in titles:
                refs.add(before.self_ref)
                break
    return refs


# --------------------------------------------------------------- splitting
# Abbreviations that are always followed by more of the sentence ("Dr. Rao",
# "Fig. 2", "e.g. this").
_ABBREVIATIONS = frozenset(
    """
    mr mrs ms dr prof sr jr st mt smt shri sh vs viz e.g i.e cf ca al op fig
    figs eq eqs no nos vol vols pp p ch sec art ref refs rs inr approx
    """.split()
)
# Abbreviations that can end a sentence: they do when a capital follows
# ("on 3 Jan. The vote", "and so on, etc. Then").
_FINAL_ABBREVIATIONS = frozenset(
    """
    etc ltd inc co corp dept govt est min max km cm mm kg gm hr hrs ed eds
    jan feb mar apr jun jul aug sep sept oct nov dec
    """.split()
)

# A sentence ends at ., ! or ? before a space (with closing quotes or brackets
# kept), at the Devanagari dandas, the Urdu full stop, the Arabic question
# mark, and at the CJK full stop, exclamation and question marks.
_BOUNDARY = re.compile(
    r"""(?:
        [.!?]+["'\u2019\u201d)\]]*(?=\s)      # Latin end, then a space
      | [\u0964\u0965\u06d4\u061f]+["'\u2019\u201d)\]]*  # danda, Urdu stop, Arabic ?
      | [\u3002\uff01\uff1f]+["'\u2019\u201d\u300d\u300f)\]]*  # CJK
    )""",
    re.VERBOSE,
)
_WORD_BEFORE = re.compile(r"([\w.]+)[.!?]*[\"'\u2019\u201d)\]]*$")


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into sentences, keeping every character.

    Only white space between sentences is dropped, so splitting never loses text.
    """
    text = " ".join(text.split())
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        end = match.end()
        candidate = text[start:end]
        if match.group(0)[0] == "." and not _ends_sentence(candidate, text[end:]):
            continue
        if candidate.strip():
            sentences.append(candidate.strip())
        start = end
    rest = text[start:].strip()
    if rest:
        sentences.append(rest)
    return sentences


def _ends_sentence(candidate: str, after: str) -> bool:
    """False for a full stop after an abbreviation, an initial or a list number."""
    match = _WORD_BEFORE.search(candidate.rstrip())
    word = match.group(1).rstrip(".") if match else ""
    following = after.lstrip()
    next_char = following[:1]
    if word.lower() in _ABBREVIATIONS:
        return False
    if word.lower() in _FINAL_ABBREVIATIONS:
        return next_char.isupper()
    if len(word) == 1 and word.isalpha() and word.isupper():
        return False  # an initial: "J. Smith"
    if word.isdigit() and len(word) <= 2 and len(candidate.strip()) <= len(word) + 1:
        return False  # a list number at the start: "1. The first point"
    if next_char and next_char.islower():
        return False  # the next word starts in lower case: not a new sentence
    return True
