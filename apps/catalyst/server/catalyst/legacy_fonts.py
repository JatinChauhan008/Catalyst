"""Find legacy (non-Unicode) Indic fonts in a PDF by their names.

Fonts such as Kruti Dev (Hindi) or Akruti Oriya Sarala (Odia) draw Indic
letters for Latin code points, so the PDF text layer is garbage
("fgekpy çns'k" for "हिमाचल प्रदेश"). Catalyst reads such pages with OCR, but
only when it knows the document language. The font name tells the language,
so a document converted without a language can still be read correctly, and a
document read without OCR can be reported instead of giving garbage.

Fonts without a usable name (Type 3 fonts such as "TT3B3t00") cannot be
recognized; such documents still need the language set by hand.
"""

from __future__ import annotations

import ctypes
import io
import re
from collections import Counter
from dataclasses import dataclass

# Patterns on the normalized font name (lower case, no subset prefix, no
# spaces, dashes or underscores) and the Sarvam language of the font family.
_FAMILIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), language)
    for p, language in [
        # Devanagari (Hindi; Marathi documents use the same fonts).
        (r"krutidev|devlys|chanakya|shusha|kundli|apsdv|shreedev|shivaji", "hi-IN"),
        (r"^(akruti|akp)dev|^dvtt", "hi-IN"),
        # Odia.
        (r"^(akruti|akp)ori|^ortt", "od-IN"),
        # Bengali script (Bengali; Assamese documents use some of them).
        (r"sutonny|bijoy|^(akruti|akp)b(e)?ng|^bntt", "bn-IN"),
        (r"^(akruti|akp)asm", "as-IN"),
        # Gujarati, Gurmukhi, Tamil, Telugu, Kannada, Malayalam.
        (r"^(akruti|akp)guj|^gutt|terafont|^lmg(arun|bharati)", "gu-IN"),
        (r"^(akruti|akp)(pun|gur)|anmollipi|gurbaniakhar|^pntt", "pa-IN"),
        (r"^(akruti|akp)tam|bamini|^tamtt|^tatt", "ta-IN"),
        (r"^(akruti|akp)tel|^tett", "te-IN"),
        (r"^(akruti|akp)kan|^kntt", "kn-IN"),
        (r"^(akruti|akp)mal|^mltt", "ml-IN"),
    ]
]
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")


@dataclass(frozen=True)
class LegacyFont:
    name: str
    language: str
    text_objects: int


def font_language(name: str) -> str | None:
    """The Sarvam language of a legacy font family, or None for other fonts."""
    normalized = re.sub(r"[\s_\-]+", "", _SUBSET_PREFIX.sub("", name)).lower()
    for pattern, language in _FAMILIES:
        if pattern.search(normalized):
            return language
    return None


def find_legacy_fonts(pdf_bytes: bytes) -> list[LegacyFont]:
    """The legacy Indic fonts of a PDF, most used first."""
    import pypdfium2
    import pypdfium2.raw as pdfium_c

    counts: Counter[str] = Counter()
    pdf = pypdfium2.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        for page in pdf:
            for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_TEXT,)):
                font = pdfium_c.FPDFTextObj_GetFont(obj.raw)
                if font:
                    counts[_font_name(font)] += 1
    finally:
        pdf.close()
    found = [
        LegacyFont(name=name, language=language, text_objects=count)
        for name, count in counts.most_common()
        if (language := font_language(name)) is not None
    ]
    return found


def dominant_language(fonts: list[LegacyFont]) -> str | None:
    """The language of the legacy fonts, when (almost) all agree."""
    by_language: Counter[str] = Counter()
    for font in fonts:
        by_language[font.language] += font.text_objects
    if not by_language:
        return None
    language, count = by_language.most_common(1)[0]
    return language if count >= 0.9 * sum(by_language.values()) else None


def _font_name(font) -> str:
    import pypdfium2.raw as pdfium_c

    size = pdfium_c.FPDFFont_GetBaseFontName(font, None, 0)
    if size <= 0:
        return ""
    buffer = ctypes.create_string_buffer(size)
    pdfium_c.FPDFFont_GetBaseFontName(font, buffer, size)
    return buffer.value.decode("utf-8", "replace")
