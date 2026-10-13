"""A table printed sideways keeps Sarvam's text instead of RapidOCR's.

RapidOCR reads a landscape table on a portrait page as vertical fragments,
which became garbage cells in a scanned annual report. The check runs on what
RapidOCR itself returns, so it is tested against the real engine.
"""

from __future__ import annotations

from pathlib import Path

import numpy
import pypdfium2
import pytest
from extracta.sarvam.ocr_model import _runs_sideways

from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.pipeline_options import RapidOcrOptions
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

TABLE_PAGE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "data"
    / "pdf"
    / "sources"
    / "2305.03393v1-pg9.pdf"
)


@pytest.fixture(scope="module")
def reader():
    return RapidOcrModel(
        enabled=True,
        artifacts_path=None,
        options=RapidOcrOptions(),
        accelerator_options=AcceleratorOptions(),
    ).reader


@pytest.mark.parametrize(("angle", "sideways"), [(0, False), (90, True), (270, True)])
def test_sideways_text_is_detected(reader, angle: int, sideways: bool) -> None:
    image = (
        pypdfium2.PdfDocument(TABLE_PAGE)[0]
        .render(scale=2.0)
        .to_pil()
        .rotate(angle, expand=True)
    )
    result = reader(numpy.array(image))
    assert _runs_sideways(result.boxes.tolist(), result.txts) is sideways
