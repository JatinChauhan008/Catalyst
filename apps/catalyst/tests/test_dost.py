"""DOST: tables as Markdown, sentences with translations as CSV, images as files."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from catalyst.dost.models import DostReport, DostSettings
from catalyst.dost.pipeline import (
    IMAGES_DIR,
    REPORT_FILE,
    SENTENCES_FILE,
    TABLES_FILE,
    DostInput,
    run_dost,
)
from catalyst.dost.sentences import split_sentences
from catalyst.dost.translate import sentence_language
from catalyst.models import ConvertRequest, TableExtractionSettings, TableSource
from catalyst.tables import ExtractionContext, extract_tables
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    TableCell,
    TableData,
)

PAPER = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "data"
    / "pdf"
    / "sources"
    / "2206.01062.pdf"
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Dr. Rao met Mr. J. Smith at 5 p.m. on 3 Jan. The vote was 3.5% higher. Was it?",
            [
                "Dr. Rao met Mr. J. Smith at 5 p.m. on 3 Jan.",
                "The vote was 3.5% higher.",
                "Was it?",
            ],
        ),
        (
            "हिमाचल में वर्षा हुई। यह 12% अधिक है॥ अगला वाक्य",
            ["हिमाचल में वर्षा हुई।", "यह 12% अधिक है॥", "अगला वाक्य"],
        ),
        (
            "今日は晴れです。明日は雨\uff1fはい",
            ["今日は晴れです。", "明日は雨\uff1f", "はい"],
        ),
        (
            'He said "Stop." Then he left (quickly.) End',
            ['He said "Stop."', "Then he left (quickly.)", "End"],
        ),
        (
            "See e.g. the annex, etc. and Fig. 2 for details.",
            ["See e.g. the annex, etc. and Fig. 2 for details."],
        ),
    ],
)
def test_sentences_split_at_their_ends_and_keep_every_character(
    text: str, expected: list[str]
) -> None:
    sentences = split_sentences(text)
    assert sentences == expected
    assert "".join(sentences).replace(" ", "") == text.replace(" ", "")


@pytest.mark.parametrize(
    ("sentence", "document_language", "status", "code"),
    [
        ("The report was released in 2024.", None, "english", "en-IN"),
        ("12.5 / 7", None, "no_letters", None),
        ("हिमाचल प्रदेश में वर्षा हुई।", None, None, "auto"),  # Hindi or Marathi?
        ("महाराष्ट्रात पाऊस पडला.", "mr-IN", None, "mr-IN"),
        ("தமிழ்நாட்டில் 38 மாவட்டங்கள் உள்ளன.", None, None, "ta-IN"),
        ("The Gram Panchayat पंचायत meeting was held.", None, None, "auto"),
        ("Le rapport a été publié en décembre.", None, "unsupported", None),
        ("Привет, как дела?", None, "unsupported", None),
    ],
)
def test_the_script_decides_whether_and_how_a_sentence_is_translated(
    sentence: str, document_language: str | None, status: str | None, code: str | None
) -> None:
    language = sentence_language(sentence, document_language)
    assert (language.status, language.code) == (status, code)


def _document() -> DoclingDocument:
    document = DoclingDocument(name="sample")
    document.add_heading("वार्षिक रिपोर्ट 2023")
    document.add_text(
        label=DocItemLabel.TEXT,
        text="इस वर्ष 1,250 मिमी वर्षा हुई। The budget was approved. DROP 42 को देखें। FAIL यहाँ।",
    )
    cells = [
        TableCell(text=text, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                  start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r == 0)
        for r, row in enumerate([["जिला", "वर्षा"], ["शिमला", "1250"]])
        for c, text in enumerate(row)
    ]  # fmt: skip
    caption = document.add_text(
        label=DocItemLabel.CAPTION, text="तालिका 1: जिलेवार वर्षा"
    )
    document.add_table(
        data=TableData(num_rows=2, num_cols=2, table_cells=cells), caption=caption
    )
    document.add_code(text="print('code is not prose')")
    return document


def test_dost_writes_tables_translations_and_reports_what_is_uncertain(
    tmp_path: Path, fake_sarvam
) -> None:
    document = _document()
    context = ExtractionContext(
        source=TableSource(filename="s.docx", sha256="0" * 64, page_count=0),
        is_pdf=False,
        is_image=False,
    )
    records, items = extract_tables(
        document, context, TableExtractionSettings(join_continued=True)
    )
    report = run_dost(
        DostInput(
            document=document,
            source_name="sample.docx",
            tables=records,
            table_items=items,
            sarvam_api_key="test-key",
            sarvam_base_url=fake_sarvam.base_url,
        ),
        DostSettings(enabled=True, translate_workers=1),
        tmp_path,
    )

    # Tables: one Markdown file with the caption and the cells.
    markdown = (tmp_path / TABLES_FILE).read_text("utf-8")
    assert "## Table 1" in markdown and "तालिका 1: जिलेवार वर्षा" in markdown
    assert "| जिला | वर्षा |" in markdown and "| शिमला | 1250 |" in markdown

    # Sentences: exactly two columns, UTF-8, no table text, no code.
    with (tmp_path / SENTENCES_FILE).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == ["original_sentence", "english_translation"]
    assert all(len(row) == 2 for row in rows)
    assert [row[0] for row in rows[1:]] == [
        "वार्षिक रिपोर्ट 2023",
        "इस वर्ष 1,250 मिमी वर्षा हुई।",
        "The budget was approved.",
        "DROP 42 को देखें।",
        "FAIL यहाँ।",
    ]
    translations = dict(rows[1:])
    assert translations["इस वर्ष 1,250 मिमी वर्षा हुई।"].startswith("EN: ")
    assert translations["The budget was approved."] == "The budget was approved."
    assert translations["FAIL यहाँ।"] == ""  # never invented
    assert not any("तालिका" in row[0] or "शिमला" in row[0] for row in rows)

    # The report says what is missing or uncertain; the files are not "complete".
    saved = DostReport.model_validate(
        json.loads((tmp_path / REPORT_FILE).read_text("utf-8"))
    )
    assert saved == report
    assert not report.complete
    assert report.sentences.by_status == {"translated": 3, "english": 1, "failed": 1}
    assert report.sentences.numbers_differ == 1
    assert report.sentences.skipped_items == {"code": 1}
    messages = [issue.message for issue in report.issues]
    assert any("could not be translated" in m and "CSV rows 6" in m for m in messages)
    assert any(
        "do not contain all numbers" in m and "CSV rows 5" in m for m in messages
    )
    assert (tmp_path / IMAGES_DIR).is_dir()


def test_a_pdf_gives_one_markdown_file_a_csv_and_ordered_unique_images(
    service,
) -> None:
    request = ConvertRequest.model_validate(
        {
            "settings": {"page_range_start": 1, "page_range_end": 6},
            "export": {"to_formats": []},
            "dost": {"enabled": True, "translate": False},
        }
    )
    envelope = service.convert(PAPER.name, PAPER.read_bytes(), request)
    assert envelope.status == "success", envelope.errors
    report = envelope.dost
    assert report is not None and report.scanned_pages == []
    target = service.jobs_dir / envelope.job_id / "outputs" / "dost"

    markdown = (target / TABLES_FILE).read_text("utf-8")
    assert report.tables.tables == 2
    assert 'colspan="3">% of Total</th>' in markdown  # merged header cells kept

    with (target / SENTENCES_FILE).open(encoding="utf-8", newline="") as stream:
        sentences = [row[0] for row in csv.reader(stream)][1:]
    assert sentences[0].startswith("DocLayNet: A Large Human-Annotated Dataset")
    assert not any("1107470" in sentence for sentence in sentences)  # a table cell

    files = report.image_files
    assert [f.filename.split(".")[0] for f in files] == [
        f"image_{n:03d}" for n in range(1, len(files) + 1)
    ]
    assert [(f.page, f.bbox[1]) for f in files] == sorted(
        (f.page, f.bbox[1]) for f in files
    )
    assert {f.sha256 for f in files} and len({f.sha256 for f in files}) == len(files)
    # JPEG images stay JPEG; an image drawn several times is saved once.
    assert any(f.kind == "embedded" and f.format == "jpg" for f in files)
    assert any(f.occurrences > 1 for f in files)
    # Vector figures are rendered from the page.
    assert any(f.kind == "rendered" and f.caption for f in files)
    assert sorted(p.name for p in (target / IMAGES_DIR).iterdir()) == [
        f.filename for f in files
    ]
    kinds = {o.format for o in envelope.outputs}
    assert {"dost_tables_md", "dost_sentences_csv", "dost_report_json"} <= kinds
