"""Translate sentences into English with the Sarvam Translate API.

API reference: https://docs.sarvam.ai/api-reference/text/translate-text

The language of each sentence comes from its script (Devanagari, Tamil,
...), or from the document language when that language uses the script.
`mayura:v1` finds the language itself (`auto`); `sarvam-translate:v1` covers
more languages but needs the language code. English sentences and sentences
without letters are copied, not sent. A sentence in a language that Sarvam
does not translate keeps an empty translation and is reported.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from catalyst.dost.models import TranslationStatus

_log = logging.getLogger(__name__)

TRANSLATE_PATH = "/translate"
TARGET_LANGUAGE = "en-IN"

# Input limits of the two models (characters).
_LIMITS = {"mayura:v1": 1000, "sarvam-translate:v1": 2000}
_MAYURA_LANGUAGES = frozenset(
    {"bn-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
)  # fmt: skip
_SARVAM_TRANSLATE_LANGUAGES = _MAYURA_LANGUAGES | {
    "as-IN", "brx-IN", "doi-IN", "kok-IN", "ks-IN", "mai-IN", "mni-IN", "ne-IN",
    "sa-IN", "sat-IN", "sd-IN", "ur-IN",
}  # fmt: skip

# Unicode blocks and the languages that are written in them. The first
# language is the one to use when the document language is not one of them.
# None: more than one common language uses the script, so let Sarvam find it.
_SCRIPTS: list[tuple[str, int, int, list[str], str | None]] = [
    ("devanagari", 0x0900, 0x097F,
     ["hi-IN", "mr-IN", "ne-IN", "sa-IN", "mai-IN", "kok-IN", "doi-IN", "brx-IN"], None),
    ("bengali", 0x0980, 0x09FF, ["bn-IN", "as-IN", "mni-IN"], None),
    ("gurmukhi", 0x0A00, 0x0A7F, ["pa-IN"], "pa-IN"),
    ("gujarati", 0x0A80, 0x0AFF, ["gu-IN"], "gu-IN"),
    ("oriya", 0x0B00, 0x0B7F, ["od-IN"], "od-IN"),
    ("tamil", 0x0B80, 0x0BFF, ["ta-IN"], "ta-IN"),
    ("telugu", 0x0C00, 0x0C7F, ["te-IN"], "te-IN"),
    ("kannada", 0x0C80, 0x0CFF, ["kn-IN"], "kn-IN"),
    ("malayalam", 0x0D00, 0x0D7F, ["ml-IN"], "ml-IN"),
    ("arabic", 0x0600, 0x06FF, ["ur-IN", "ks-IN", "sd-IN"], "ur-IN"),
    ("ol chiki", 0x1C50, 0x1C7F, ["sat-IN"], "sat-IN"),
    ("meetei mayek", 0xABC0, 0xABFF, ["mni-IN"], "mni-IN"),
]  # fmt: skip

_ENGLISH_WORDS = frozenset(
    "the of and to in is are was were for on with by as at from that this be or "
    "an it not which have has will shall under per all any its their".split()
)
# Letters in an Indian script that make a mostly English sentence non-English.
_MIN_MIXED_LETTERS = 3
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Translation:
    text: str
    status: TranslationStatus
    language: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class _Language:
    """Where a sentence goes: its status if it is not sent, else its code and model."""

    status: TranslationStatus | None
    code: str | None = None
    model: str | None = None
    detail: str | None = None


def sentence_language(sentence: str, document_language: str | None) -> _Language:
    """Decide from the script of the letters whether and how to translate."""
    counts: Counter[str] = Counter()
    latin_extra = 0
    for char in sentence:
        if not (char.isalpha() or unicodedata.category(char).startswith("M")):
            continue
        code = ord(char)
        for name, first, last, _, _ in _SCRIPTS:
            if first <= code <= last:
                counts[name] += 1
                break
        else:
            if char.isascii():
                counts["latin"] += 1
            elif "LATIN" in unicodedata.name(char, ""):
                counts["latin"] += 1
                latin_extra += 1
            else:
                counts["other"] += 1
    if not counts:
        return _Language("no_letters")

    script, _ = counts.most_common(1)[0]
    indic = [(n, c) for n, c in counts.most_common() if n not in ("latin", "other")]
    if script == "latin" and indic and indic[0][1] >= _MIN_MIXED_LETTERS:
        # Mostly English words with some words in an Indian script: translate.
        script = indic[0][0]
    if script == "latin":
        words = {word.lower() for word in re.findall(r"[A-Za-z]+", sentence)}
        if latin_extra == 0 or words & _ENGLISH_WORDS:
            return _Language("english", code="en-IN")
        return _Language(
            "unsupported",
            detail="Latin script, but not English: Sarvam does not translate this language.",
        )
    if script == "other":
        return _Language(
            "unsupported", detail="Sarvam does not translate text in this script."
        )

    _, _, _, languages, default = next(s for s in _SCRIPTS if s[0] == script)
    if document_language in languages:
        code = document_language
    elif default is not None:
        code = default
    else:
        # Hindi or Marathi, Bengali or Assamese: mayura finds the language.
        return _Language(None, code="auto", model="mayura:v1")
    model = "sarvam-translate:v1"
    if code not in _SARVAM_TRANSLATE_LANGUAGES:
        return _Language("unsupported", detail=f"Sarvam does not translate {code}.")
    return _Language(None, code=code, model=model)


def numbers_of(text: str) -> Counter[str]:
    """The numbers of a text, with Indic digits read as 0 to 9 and separators removed."""
    ascii_text = "".join(
        str(unicodedata.digit(char)) if char.isdigit() else char for char in text
    )
    return Counter(number.replace(",", "") for number in _NUMBER.findall(ascii_text))


def numbers_differ(original: str, translation: str) -> bool:
    """True when a number of the original is missing from the translation."""
    return bool(numbers_of(original) - numbers_of(translation))


@dataclass
class SarvamTranslator:
    """Translates sentences one by one, in parallel; a repeated sentence is sent once."""

    api_key: str
    base_url: str = "https://api.sarvam.ai"
    workers: int = 4
    request_timeout_seconds: float = 60.0
    max_retries: int = 3
    characters_sent: int = 0
    _session: requests.Session = field(default_factory=requests.Session)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def translate_all(
        self, sentences: list[str], document_language: str | None
    ) -> list[Translation]:
        unique = list(dict.fromkeys(sentences))
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            results = list(
                pool.map(lambda s: self._translate(s, document_language), unique)
            )
        by_text = dict(zip(unique, results))
        return [by_text[sentence] for sentence in sentences]

    def _translate(self, sentence: str, document_language: str | None) -> Translation:
        language = sentence_language(sentence, document_language)
        if language.status is not None:
            copied = language.status in ("english", "no_letters")
            return Translation(
                text=sentence if copied else "",
                status=language.status,
                language=language.code,
                detail=language.detail,
            )
        assert language.code is not None and language.model is not None
        try:
            pieces = [
                self._request(piece, language.code, language.model)
                for piece in _pieces(sentence, _LIMITS[language.model])
            ]
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            return Translation(
                text="", status="failed", language=language.code, detail=str(exc)
            )
        text = " ".join(piece for piece, _ in pieces).strip()
        detected = pieces[0][1] if pieces else language.code
        if not text:
            return Translation(
                text="",
                status="failed",
                language=detected,
                detail="Sarvam returned an empty translation.",
            )
        return Translation(text=text, status="translated", language=detected)

    def _request(self, text: str, source: str, model: str) -> tuple[str, str]:
        payload = {
            "input": text,
            "source_language_code": source,
            "target_language_code": TARGET_LANGUAGE,
            "model": model,
            "mode": "formal",
            "numerals_format": "international",
        }
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            response = self._session.post(
                f"{self.base_url.rstrip('/')}{TRANSLATE_PATH}",
                json=payload,
                headers={"api-subscription-key": self.api_key},
                timeout=self.request_timeout_seconds,
            )
            if response.status_code in (429, 500, 503) and attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2
                continue
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Sarvam Translate HTTP {response.status_code}: {response.text[:300]}"
                )
            with self._lock:
                self.characters_sent += len(text)
            body = response.json()
            return str(body.get("translated_text") or ""), str(
                body.get("source_language_code") or source
            )
        raise RuntimeError("Sarvam Translate retries exhausted.")


def _pieces(sentence: str, limit: int) -> list[str]:
    """Cut a sentence that is longer than the API limit at commas or spaces."""
    if len(sentence) <= limit:
        return [sentence]
    pieces: list[str] = []
    rest = sentence
    while len(rest) > limit:
        cut = max(rest.rfind(mark, 0, limit) for mark in (", ", "; ", ": "))
        if cut <= 0:
            cut = rest.rfind(" ", 0, limit)
        cut = cut + 1 if cut > 0 else limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:]
    if rest.strip():
        pieces.append(rest.strip())
    return pieces


def copy_or_skip(sentence: str, reason: TranslationStatus, detail: str) -> Translation:
    """The result when no translation service runs: copy English, else leave empty."""
    language = sentence_language(sentence, None)
    if language.status in ("english", "no_letters"):
        return Translation(
            text=sentence, status=language.status, language=language.code
        )
    return Translation(text="", status=reason, detail=detail)
