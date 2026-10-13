"""Scanned pages are turned upright and straightened before Docling reads them.

A table page is rendered to an image, then turned or tilted the way scanners
and sideways-printed tables do it. Each image is converted with RapidOCR, and
its table must come out like the table of the upright image: the same columns,
every value in the same row and column, and at the same place on the page.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pypdfium2
import pytest
from extracta.models import ConvertRequest
from extracta.upright import detect_correction
from PIL import Image

TABLE_PAGE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "data"
    / "pdf"
    / "sources"
    / "2305.03393v1-pg9.pdf"
)


@pytest.fixture(scope="module")
def page_image() -> Image.Image:
    return pypdfium2.PdfDocument(TABLE_PAGE)[0].render(scale=2.0).to_pil()


def _turned(image: Image.Image, degrees: float) -> Image.Image:
    """Turn counter-clockwise; quarter turns change the page size, tilts do not."""
    return image.rotate(
        degrees,
        expand=degrees % 90 == 0,
        resample=Image.Resampling.BICUBIC,
        fillcolor="white",
    )


def _convert(service, image: Image.Image, straighten: bool = True) -> dict:
    data = io.BytesIO()
    image.save(data, format="PNG")
    envelope = service.convert(
        "scan.png",
        data.getvalue(),
        ConvertRequest.model_validate(
            {
                "settings": {"straighten_scanned_pages": straighten},
                "export": {"to_formats": ["json"], "image_export_mode": "placeholder"},
                "formats": {
                    "image": {
                        "pipeline_options": {
                            "ocr_options": {"__variant__": "RapidOcrOptions"}
                        }
                    }
                },
            }
        ),
    )
    assert envelope.status == "success", envelope.errors
    return json.loads(envelope.outputs[0].content)


def _grid(table: dict) -> list[list[str]]:
    data = table["data"]
    rows = [[""] * data["num_cols"] for _ in range(data["num_rows"])]
    for cell in data["table_cells"]:
        rows[cell["start_row_offset_idx"]][cell["start_col_offset_idx"]] = cell["text"]
    return rows


@pytest.fixture(scope="module")
def upright(service, page_image) -> dict:
    return _convert(service, page_image)


@pytest.mark.parametrize(
    ("turn", "tilt"),
    [(90, 0.0), (180, 0.0), (270, 0.0), (0, 1.0), (0, -3.0), (90, 1.0)],
)
def test_turns_and_tilts_are_detected(page_image, turn: int, tilt: float) -> None:
    probe = page_image.resize((page_image.width // 2, page_image.height // 2))
    correction = detect_correction(_turned(_turned(probe, tilt), turn))
    assert (correction.quarter_turns * 90 + turn) % 360 == 0
    assert correction.skew_degrees == pytest.approx(-tilt, abs=0.15)


def test_upright_page_is_left_as_it_is(page_image) -> None:
    assert detect_correction(page_image).is_identity


@pytest.mark.parametrize("degrees", [90, 1.0])
def test_turned_or_tilted_scan_keeps_its_table(
    service, page_image, upright, degrees: float
) -> None:
    document = _convert(service, _turned(page_image, degrees))

    # The stored page is the upright page, so the boxes fit the stored size.
    assert document["pages"]["1"]["size"] == upright["pages"]["1"]["size"]
    assert len(document["tables"]) == len(upright["tables"]) == 1
    table, expected = document["tables"][0], upright["tables"][0]
    assert table["data"]["num_cols"] >= 4
    assert _grid(table) == _grid(expected)
    box, expected_box = table["prov"][0]["bbox"], expected["prov"][0]["bbox"]
    for side in ("l", "t", "r", "b"):
        assert box[side] == pytest.approx(expected_box[side], abs=8), side
