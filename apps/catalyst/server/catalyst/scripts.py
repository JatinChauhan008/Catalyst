"""Tell a usable PDF text layer from a legacy-font one by its Unicode script.

Legacy Indic fonts (Kruti Dev, Chanakya, DevLys and similar) draw Hindi
glyphs for Latin code points: the text layer of "कृषि स्थिति" reads
`d`f"k fLFkfr`. Docling takes such a text layer as good text and skips OCR.
When the document language is known, a text layer with many letters but
almost none in the script of that language is such a layer.
"""

from __future__ import annotations

# First and last code point of a Unicode block.
Script = tuple[int, int]

DEVANAGARI: Script = (0x0900, 0x097F)
BENGALI: Script = (0x0980, 0x09FF)
GURMUKHI: Script = (0x0A00, 0x0A7F)
GUJARATI: Script = (0x0A80, 0x0AFF)
ORIYA: Script = (0x0B00, 0x0B7F)
TAMIL: Script = (0x0B80, 0x0BFF)
TELUGU: Script = (0x0C00, 0x0C7F)
KANNADA: Script = (0x0C80, 0x0CFF)
MALAYALAM: Script = (0x0D00, 0x0D7F)
ARABIC: Script = (0x0600, 0x06FF)

# A text with fewer letters than this is too short to judge.
_MIN_LETTERS = 20
# Below this share of letters in the expected script, the text is garbled.
_MIN_SCRIPT_SHARE = 0.2


def is_garbled(text: str, script: Script) -> bool:
    """True when the text has enough letters and almost none in ``script``.

    Devanagari vowel signs are not letters for `str.isalpha`, so marks of
    the script count as well.
    """
    first, last = script
    letters = in_script = 0
    for char in text:
        inside = first <= ord(char) <= last
        if inside or char.isalpha():
            letters += 1
            in_script += inside
    return letters >= _MIN_LETTERS and in_script < _MIN_SCRIPT_SHARE * letters
