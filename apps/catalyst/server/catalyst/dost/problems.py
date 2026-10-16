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

from catalyst.dost.models import DostIssue, SentenceProblem, SentenceProblemKind
from catalyst.dost.translate import Translation, is_detection_failure, numbers_of

PROBLEMS_FILE = "document_sentence_problems.csv"

_SEVERITY = {
    "not_translated": "error",
    "language_not_supported": "warn",
    "translation_off": "warn",
    "numbers_differ": "warn",
    "language_assumed": "info",
}
_TITLES = {
    "not_translated": "not translated",
    "language_not_supported": "in a language that Sarvam does not translate",
    "translation_off": "not translated",
    "numbers_differ": "translated, but numbers are missing",
    "language_assumed": "translated in an assumed language",
}


def find_problems(
    originals: list[str], translations: list[Translation], pages: list[int | None]
) -> list[SentenceProblem]:
    problems = []
    for row, (original, translation, page) in enumerate(
        zip(originals, translations, pages),
        start=2,  # the header is row 1
    ):
        explained = _explain(original, translation)
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
                action=action,
                detail=translation.detail,
            )
        )
    return problems


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
        if detail:
            return "language_assumed", detail, "Check that the translation is right."
    return None


def _failure_reason(detail: str) -> tuple[str, str | None]:
    lowered = detail.lower()
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
    """One issue per kind and reason, with the number of sentences."""
    groups: Counter[tuple[str, str]] = Counter(
        (problem.kind, problem.reason) for problem in problems
    )
    first_rows: dict[tuple[str, str], list[int]] = {}
    for problem in problems:
        first_rows.setdefault((problem.kind, problem.reason), []).append(problem.row)
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
