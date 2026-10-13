"""End-to-end behavior of the Extracta flow: validate, route, convert, export, check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from extracta.models import ConvertRequest
from extracta.options_schema import OptionsError, apply_overrides

TEST_DATA = Path(__file__).resolve().parents[3] / "tests" / "data"


def _convert(service, path, **request):
    return service.convert(
        path.name, path.read_bytes(), ConvertRequest.model_validate(request)
    )


def test_docx_goes_through_the_simple_pipeline_and_is_exported(service) -> None:
    envelope = _convert(
        service,
        TEST_DATA / "docx" / "sources" / "Transitional.docx",
        export={"to_formats": ["json", "html", "md"]},
    )
    assert envelope.status == "success"
    assert envelope.source.detected_format == "docx"
    assert envelope.processing.pipeline == "simple"
    assert envelope.validation.passed
    assert {output.format for output in envelope.outputs} == {"json", "html", "md"}

    json_output = next(output for output in envelope.outputs if output.format == "json")
    assert json.loads(json_output.content)["schema_name"] == "DoclingDocument"
    relative = json_output.url.split("/files/", 1)[1]
    assert service.job_file(envelope.job_id, relative) is not None
    assert service.job_file(envelope.job_id, "../../outside.txt") is None


def test_spreadsheet_is_converted_not_passed_through(service) -> None:
    envelope = _convert(
        service,
        TEST_DATA / "xlsx" / "sources" / "xlsx_01.xlsx",
        export={"to_formats": ["md"]},
    )
    assert envelope.status == "success"
    assert envelope.stats.tables > 0
    assert "|" in envelope.outputs[0].content


def test_disallowed_format_is_rejected(service) -> None:
    envelope = _convert(
        service,
        TEST_DATA / "docx" / "sources" / "Transitional.docx",
        settings={"allowed_formats": ["pdf"]},
    )
    assert envelope.status == "rejected"
    assert envelope.outputs == []


def test_invalid_options_are_rejected_with_the_field_path(service) -> None:
    envelope = _convert(
        service,
        TEST_DATA / "csv" / "sources" / "csv-comma.csv",
        formats={"pdf": {"pipeline_options": {"no_such_option": True}}},
    )
    assert envelope.status == "rejected"
    assert "pdf.pipeline.no_such_option" in envelope.errors[0].message


def test_empty_file_is_rejected(service) -> None:
    envelope = service.convert("empty.pdf", b"", ConvertRequest())
    assert envelope.status == "rejected"


def test_scanned_pdf_uses_sarvam_ocr(service, fake_sarvam) -> None:
    sarvam = {
        "__variant__": "SarvamOcrOptions",
        "api_key": "test-key",
        "base_url": fake_sarvam.base_url,
        "mode": "full_page",
        "lang": ["iso:hi"],
        "poll_interval_seconds": 0.05,
    }
    envelope = _convert(
        service,
        TEST_DATA / "ocr" / "sources" / "ocr_test.pdf",
        export={"to_formats": ["md"], "image_export_mode": "placeholder"},
        formats={"pdf": {"pipeline_options": {"ocr_options": sarvam}}},
    )
    assert envelope.status == "success", envelope.errors
    assert envelope.processing.ocr_engine == "sarvam"
    markdown = envelope.outputs[0].content
    for line in fake_sarvam.lines:
        assert line in markdown
    submission = fake_sarvam.submissions[-1]
    assert submission["language"] == "hi-IN"
    assert submission["output_format"] == "json"


def test_scanned_table_keeps_its_columns(service, fake_sarvam) -> None:
    """Sarvam has no word boxes; table regions are read locally so columns survive."""
    import io

    import pypdfium2

    page = pypdfium2.PdfDocument(
        TEST_DATA / "pdf" / "sources" / "2305.03393v1-pg9.pdf"
    )[0]
    scan = io.BytesIO()
    page.render(scale=2.0).to_pil().save(scan, format="PNG")
    sarvam = {
        "__variant__": "SarvamOcrOptions",
        "api_key": "test-key",
        "base_url": fake_sarvam.base_url,
        "poll_interval_seconds": 0.05,
    }
    envelope = service.convert(
        "scanned_table.png",
        scan.getvalue(),
        ConvertRequest.model_validate(
            {
                "export": {"to_formats": ["json"], "image_export_mode": "placeholder"},
                "formats": {"image": {"pipeline_options": {"ocr_options": sarvam}}},
            }
        ),
    )
    assert envelope.status == "success", envelope.errors
    document = json.loads(envelope.outputs[0].content)
    columns = [table["data"]["num_cols"] for table in document["tables"]]
    assert columns and max(columns) >= 4, columns
    checks = {check.id: check.status for check in envelope.validation.checks}
    assert checks["table_columns"] == "pass"


def test_sarvam_without_api_key_fails_with_a_clear_error(service, monkeypatch) -> None:
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    envelope = _convert(
        service,
        TEST_DATA / "pdf" / "sources" / "2305.03393v1-pg9.pdf",
        export={"to_formats": ["md"]},
        formats={
            "pdf": {
                "pipeline_options": {"ocr_options": {"__variant__": "SarvamOcrOptions"}}
            }
        },
    )
    assert envelope.status == "failure"
    assert "SARVAM_API_KEY" in envelope.errors[0].message


def test_catalog_offers_sarvam_and_model_presets(service) -> None:
    catalog = service.describe()
    fields = {
        field["name"]: field for field in catalog["pipelines"]["standard"]["fields"]
    }
    assert "SarvamOcrOptions" in {
        variant["id"] for variant in fields["ocr_options"]["variants"]
    }
    vlm_fields = {
        field["name"]: field for field in catalog["pipelines"]["vlm"]["fields"]
    }
    assert vlm_fields["vlm_options"]["presets"]
    asr_fields = {
        field["name"]: field for field in catalog["pipelines"]["asr"]["fields"]
    }
    assert any(
        preset["id"] == "asr:whisper_tiny"
        for preset in asr_fields["asr_options"]["presets"]
    )


def test_sparse_override_keeps_nested_defaults(service) -> None:
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

    service.describe()  # registers the variants and presets
    options = apply_overrides(
        PdfPipelineOptions(),
        {"table_structure_options": {"mode": "fast"}, "do_ocr": False},
    )
    assert options.table_structure_options.mode == TableFormerMode.FAST
    assert (
        options.table_structure_options.do_cell_matching
        is PdfPipelineOptions().table_structure_options.do_cell_matching
    )
    assert options.do_ocr is False

    with pytest.raises(OptionsError):
        apply_overrides(
            PdfPipelineOptions(), {"ocr_options": {"__variant__": "NotAnEngine"}}
        )
