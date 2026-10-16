"""Command line: split a PDF into tables, translated sentences and images.

Run from the repository root:

    uv run --no-sync python apps/catalyst/server/catalyst/dost input.pdf -o output --lang hi-IN

Exit status: 0 when the extraction is complete, 2 when the files are written
but the report has warnings or errors (read `extraction_report.json`), 1 when
the document could not be converted.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # Run as a script path: make the `catalyst` package importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from catalyst.dost.pipeline import IMAGES_DIR, REPORT_FILE, SENTENCES_FILE, TABLES_FILE
from catalyst.models import ConvertRequest
from catalyst.options_schema import VARIANT_KEY
from catalyst.sarvam.ocr_model import SARVAM_API_KEY_ENV

_SARVAM = "SarvamOcrOptions"
_AUTO = "OcrAutoOptions"


def _request(args: argparse.Namespace) -> ConvertRequest:
    ocr: dict[str, Any] = {}
    pipeline: dict[str, Any] = {}
    engine = args.ocr
    if engine == "default":
        engine = "sarvam" if os.environ.get(SARVAM_API_KEY_ENV) else "auto"
    if engine == "off":
        pipeline["do_ocr"] = False
    else:
        ocr[VARIANT_KEY] = _SARVAM if engine == "sarvam" else _AUTO
        if args.lang and engine == "sarvam":
            ocr["lang"] = [args.lang]
        if args.scanned:
            ocr["mode"] = "full_page"
        pipeline["ocr_options"] = ocr
    formats = {fmt: {"pipeline_options": pipeline} for fmt in ("pdf", "image")}
    settings: dict[str, Any] = {}
    if args.scanned:
        settings["ignore_text_layer"] = True
    if args.pages:
        first, _, last = args.pages.partition("-")
        settings["page_range_start"] = int(first)
        if last:
            settings["page_range_end"] = int(last)
    dost: dict[str, Any] = {"enabled": True, "translate": not args.no_translate}
    if args.lang:
        dost["source_language"] = args.lang
    if args.include_page_scans:
        dost["include_page_scans"] = True
    return ConvertRequest.model_validate(
        {
            "settings": settings,
            "export": {"to_formats": []},
            "dost": dost,
            "formats": formats,
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m catalyst.dost",
        description=(
            "Write all tables of a PDF to document_tables.md, its sentences with an "
            "English translation to document_sentences.csv, and its images to images/."
        ),
    )
    parser.add_argument(
        "input", type=Path, help="The PDF (or another document) to process."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("output"),
        help="Output folder (default: output).",
    )
    parser.add_argument(
        "--lang",
        help="Document language as a Sarvam code: hi-IN, mr-IN, ta-IN, ... (OCR and translation).",
    )
    parser.add_argument(
        "--ocr",
        choices=["default", "sarvam", "auto", "off"],
        default="default",
        help="OCR engine. default: Sarvam when SARVAM_API_KEY is set, else Docling's choice.",
    )
    parser.add_argument(
        "--scanned",
        action="store_true",
        help="Read every page with OCR and ignore the PDF text layer.",
    )
    parser.add_argument("--pages", help="Page range, for example 1-5.")
    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="Do not call the translation service.",
    )
    parser.add_argument(
        "--include-page-scans",
        action="store_true",
        help="Also save the image of each scanned page.",
    )
    args = parser.parse_args(argv)

    try:  # read SARVAM_API_KEY from a local .env file, as the server does
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    except ImportError:
        pass
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    if not args.input.is_file():
        parser.error(f"{args.input} is not a file")

    from catalyst.service import CatalystService, ServerSettings

    with tempfile.TemporaryDirectory() as data_dir:
        service = CatalystService(
            ServerSettings(data_dir=Path(data_dir), max_upload_mb=2048, keep_jobs=1)
        )
        envelope = service.convert(
            args.input.name, args.input.read_bytes(), _request(args)
        )
        if envelope.dost is None:
            print(f"Status: {envelope.status}", file=sys.stderr)
            for error in envelope.errors:
                print(f"ERROR {error.component}: {error.message}", file=sys.stderr)
            return 1

        source = Path(data_dir) / "jobs" / envelope.job_id / "outputs" / "dost"
        args.output.mkdir(parents=True, exist_ok=True)
        # Replace the outputs of an earlier run, so that no old image stays.
        shutil.rmtree(args.output / IMAGES_DIR, ignore_errors=True)
        for name in (TABLES_FILE, SENTENCES_FILE, REPORT_FILE):
            (args.output / name).unlink(missing_ok=True)
        shutil.copytree(source, args.output, dirs_exist_ok=True)

    report = envelope.dost
    print(f"Output: {args.output.resolve()}")
    print(
        f"Pages: {report.pages} (scanned: {report.scanned_pages or 'none'}; OCR: {report.ocr_engine or 'off'})"
    )
    print(f"Tables: {report.tables.tables} -> {TABLES_FILE}")
    statuses = ", ".join(
        f"{k} {v}" for k, v in sorted(report.sentences.by_status.items())
    )
    print(
        f"Sentences: {report.sentences.sentences} ({statuses or 'none'}) -> {SENTENCES_FILE}"
    )
    print(
        f"Images: {report.images.files} ({report.images.embedded} embedded, {report.images.rendered} rendered) -> {IMAGES_DIR}/"
    )
    for issue in report.issues:
        if issue.severity != "info":
            page = f" (page {issue.page})" if issue.page else ""
            print(f"{issue.severity.upper()} {issue.component}{page}: {issue.message}")
    if report.complete:
        print("Complete: no warnings or errors.")
        return 0
    print(f"Not complete: read {REPORT_FILE} for the warnings and errors.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
