"""Explain, sentence by sentence, what went wrong with a translation.

Each problem sentence gets a plain reason and an action for the user. The
technical message (for example the API error) is kept as a detail. The
problems are also written as a CSV file that opens in Excel.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from catalyst import scripts
from catalyst.dost.models import DostIssue, SentenceProblem, SentenceProblemKind
from catalyst.dost.translate import (
    BROKEN_PREFIX,
    RETRANSLATED_PREFIX,
    Translation,
    is_detection_failure,
    numbers_of,
)
from catalyst.sarvam.ocr_model import language_script
from catalyst.scripts import Script

PROBLEMS_FILE = "document_sentence_problems.csv"

_SEVERITY = {
    "not_translated": "error",
    "language_not_supported": "warn",
    "translation_off": "warn",
    "numbers_differ": "warn",
    "language_assumed": "info",
    "retranslated": "info",
    "ocr_suspect": "warn",
}
_TITLES = {
    "not_translated": "not translated",
    "language_not_supported": "in a language that Sarvam does not translate",
    "translation_off": "not translated",
    "numbers_differ": "translated, but numbers are missing",
    "language_assumed": "translated in an assumed language",
    "retranslated": "translated on a second try",
    "ocr_suspect": "with OCR text in the wrong script",
}


def find_problems(
    originals: list[str],
    translations: list[Translation],
    pages: list[int | None],
    document_language: str | None = None,
) -> list[SentenceProblem]:
    expected = language_script(document_language) if document_language else None
    problems = []
    for row, (original, translation, page) in enumerate(
        zip(originals, translations, pages),
        start=2,  # the header is row 1
    ):
        explained = _wrong_script(original, translation, document_language, expected)
        explained = explained or _explain(original, translation)
        if explained is None:
            continue
        kind, reason, action = explained
        problems.append(
            SentenceProblem(
                row=row,
                page=page,
                original=original,
                translation=translation.text,
                kind=kind,
                reason=reason,
                summary=_GENERAL_REASONS.get(kind, reason),
                action=action,
                detail=translation.detail,
            )
        )
    return problems


# For kinds whose reason names details of the sentence (its numbers, its
# script), the reason that groups the sentences.
_GENERAL_REASONS: dict[str, str] = {
    "numbers_differ": "The translation does not contain all numbers of the original.",
    "ocr_suspect": (
        "The OCR text is in another script than the document language: the OCR "
        "probably misread these pages, and a translation of it is invented."
    ),
}


# Indian scripts by name, to say which script a sentence is in.
_INDIC_SCRIPTS: list[tuple[str, Script]] = [
    ("Devanagari", scripts.DEVANAGARI),
    ("Bengali", scripts.BENGALI),
    ("Gurmukhi", scripts.GURMUKHI),
    ("Gujarati", scripts.GUJARATI),
    ("Odia", scripts.ORIYA),
    ("Tamil", scripts.TAMIL),
    ("Telugu", scripts.TELUGU),
    ("Kannada", scripts.KANNADA),
    ("Malayalam", scripts.MALAYALAM),
    ("Arabic", scripts.ARABIC),
]
# Signs shared by several scripts (the dandas) say nothing about the script.
_SHARED_SIGNS = frozenset("।॥")
# Fewer letters than this in an Indian script are too few to judge.
_MIN_SCRIPT_LETTERS = 4


def main_indic_script(text: str) -> tuple[str, Script] | None:
    """The Indian script with the most letters in the text, if any."""
    counts: Counter[str] = Counter()
    for char in text:
        if char in _SHARED_SIGNS:
            continue
        code = ord(char)
        for name, (first, last) in _INDIC_SCRIPTS:
            if first <= code <= last:
                counts[name] += 1
                break
    if not counts:
        return None
    name, count = counts.most_common(1)[0]
    if count < _MIN_SCRIPT_LETTERS:
        return None
    return name, dict(_INDIC_SCRIPTS)[name]


def _wrong_script(
    original: str,
    translation: Translation,
    document_language: str | None,
    expected: Script | None,
) -> tuple[SentenceProblemKind, str, str | None] | None:
    """A sentence in another Indian script than the document language.

    OCR in the wrong script gives text that only looks like words; a
    translation of it is invented. Such sentences are flagged, whatever their
    translation status.
    """
    if expected is None:
        return None
    found = main_indic_script(original)
    if found is None or found[1] == expected:
        return None
    expected_name = next(
        (name for name, script in _INDIC_SCRIPTS if script == expected), "another"
    )
    translated = (
        "Its translation is probably invented."
        if translation.text
        else "It has no translation."
    )
    return (
        "ocr_suspect",
        f"This sentence is in {found[0]} script, but {document_language} is written "
        f"in {expected_name} script: the OCR probably misread this page. {translated}",
        "Check this page in the PDF. If it is in another language, convert it "
        "again with that language; else read this sentence by hand.",
    )


def wrong_script_pages(problems: list[SentenceProblem]) -> list[DostIssue]:
    """One issue that names the pages with sentences in the wrong script."""
    suspect = [p for p in problems if p.kind == "ocr_suspect"]
    if not suspect:
        return []
    pages = sorted({p.page for p in suspect if p.page is not None})
    where = f"pages {', '.join(map(str, pages))}" if pages else "some pages"
    return [
        DostIssue(
            severity="warn",
            component="document",
            message=(
                f"The OCR text of {where} ({len(suspect)} sentences) is in another "
                "script than the document language, so the OCR probably misread "
                "these pages. Check them in the PDF."
            ),
        )
    ]


def _explain(
    original: str, translation: Translation
) -> tuple[SentenceProblemKind, str, str | None] | None:
    status, detail = translation.status, translation.detail or ""
    if status == "failed":
        return ("not_translated", *_failure_reason(detail))
    if status == "unsupported":
        return (
            "language_not_supported",
            detail or "Sarvam does not translate the language of this sentence.",
            "Translate this sentence by hand.",
        )
    if status == "disabled":
        action = (
            "Set SARVAM_API_KEY and convert again."
            if "key" in detail.lower()
            else "Turn on translation and convert again."
        )
        return "translation_off", detail or "Translation was off.", action
    if status == "translated":
        missing = numbers_of(original) - numbers_of(translation.text)
        if missing:
            numbers = ", ".join(sorted(missing))
            return (
                "numbers_differ",
                f"The translation does not contain these numbers of the original: {numbers}.",
                "Compare the translation with the original and correct it.",
            )
        if detail.startswith(RETRANSLATED_PREFIX):
            return (
                "retranslated",
                "Sarvam's first translation was broken (it repeated itself or "
                "added its own words); this one comes from a second try.",
                "Check that the translation is right.",
            )
        if detail:
            return "language_assumed", detail, "Check that the translation is right."
    return None


def _failure_reason(detail: str) -> tuple[str, str | None]:
    lowered = detail.lower()
    if detail.startswith(BROKEN_PREFIX):
        return (
            "Sarvam's translation was broken (it repeated the same words again "
            "and again, or added its own text), so it was discarded.",
            "Translate this sentence by hand. If the original is a long list, OCR "
            "may have joined many lines into one sentence.",
        )
    if is_detection_failure(detail):
        return (
            "Sarvam could not tell which language this sentence is in.",
            "Set the document language (for example hi-IN) and convert again.",
        )
    if "http 429" in lowered or "rate limit" in lowered:
        return (
            "Sarvam was busy (too many requests) and did not answer in time.",
            "Convert the document again later.",
        )
    if "cannot reach sarvam" in lowered or "request to" in lowered:
        return (
            "Sarvam could not be reached (network problem).",
            "Check the internet connection and convert again.",
        )
    if "http 401" in lowered or "http 403" in lowered:
        return "Sarvam refused the API key.", "Check the SARVAM_API_KEY setting."
    if "empty translation" in lowered:
        return (
            "Sarvam returned an empty translation.",
            "Translate this sentence by hand.",
        )
    message = _api_message(detail)
    if message:
        return (
            f"Sarvam refused this sentence: {message}",
            "Check the sentence against the PDF; OCR may have damaged it.",
        )
    return "The translation failed.", "Convert the document again."


def _api_message(detail: str) -> str | None:
    """The `message` of a Sarvam error body in "Sarvam Translate HTTP 422: {...}"."""
    _, _, body = detail.partition(": ")
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    error = parsed.get("error") if isinstance(parsed, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message) if message else None


def summarize(problems: list[SentenceProblem]) -> list[DostIssue]:
    """One issue per kind and general reason, with the number of sentences."""
    groups: Counter[tuple[str, str]] = Counter(
        (problem.kind, problem.summary or problem.reason) for problem in problems
    )
    first_rows: dict[tuple[str, str], list[int]] = {}
    for problem in problems:
        first_rows.setdefault(
            (problem.kind, problem.summary or problem.reason), []
        ).append(problem.row)
    issues = []
    for (kind, reason), count in groups.most_common():
        rows = first_rows[(kind, reason)]
        shown = ", ".join(map(str, rows[:10])) + (
            f" and {len(rows) - 10} more" if len(rows) > 10 else ""
        )
        sentences = "sentence" if count == 1 else "sentences"
        issues.append(
            DostIssue(
                severity=_SEVERITY[kind],
                component="translation",
                message=(
                    f"{count} {sentences} {_TITLES[kind]}: {reason} "
                    f"(CSV rows {shown}; all are listed in {PROBLEMS_FILE})."
                ),
            )
        )
    return issues


def write_problems(problems: list[SentenceProblem], path: Path) -> None:
    """The problem sentences as a CSV file (UTF-8 with a BOM, for Excel)."""
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["csv_row", "page", "problem", "original_sentence",
             "english_translation", "reason", "what_to_do", "technical_detail"]
        )  # fmt: skip
        writer.writerows(
            [
                problem.row,
                problem.page or "",
                problem.kind,
                problem.original,
                problem.translation,
                problem.reason,
                problem.action or "",
                problem.detail or "",
            ]
            for problem in problems
        )
