"""The Sarvam result parser must accept the box and archive layouts it may receive.

Sarvam does not document the field names or units of the Digitise boxes, so
these tests pin down every layout the parser claims to support.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from extracta.sarvam.client import parse_digitise_archive, parse_page_blocks

IMAGE_SIZE = (1000, 2000)
EXPECTED = (0.1, 0.25, 0.5, 0.5)


@pytest.mark.parametrize(
    "block",
    [
        {"text": "a", "bbox": [100, 500, 500, 1000]},
        {"text": "a", "bbox": [0.1, 0.25, 0.5, 0.5]},
        {
            "text": "a",
            "bounding_box": {"x": 100, "y": 500, "width": 400, "height": 500},
        },
        {"text": "a", "bbox": {"left": 100, "top": 500, "right": 500, "bottom": 1000}},
        {"text": "a", "polygon": [[100, 500], [500, 500], [500, 1000], [100, 1000]]},
        {"text": "a", "polygon": [100, 500, 500, 500, 500, 1000, 100, 1000]},
        {
            "text": "a",
            "coordinates": {"points": [{"x": 100, "y": 500}, {"x": 500, "y": 1000}]},
        },
    ],
)
def test_box_layouts_normalize_to_the_same_box(block: dict) -> None:
    [parsed] = parse_page_blocks({"blocks": [block]}, image_size=IMAGE_SIZE)
    assert parsed.bbox == pytest.approx(EXPECTED)


def test_page_dimensions_in_payload_win_over_the_image_size() -> None:
    payload = {
        "width": 500,
        "height": 1000,
        "blocks": [{"text": "a", "bbox": [50, 250, 250, 500]}],
    }
    [parsed] = parse_page_blocks(payload, image_size=IMAGE_SIZE)
    assert parsed.bbox == pytest.approx(EXPECTED)


def test_table_html_becomes_one_line_per_row_and_images_are_skipped() -> None:
    payload = {
        "layout": {
            "elements": [
                {
                    "type": "table",
                    "html": "<table><tr><th>Name</th><th>Qty</th></tr><tr><td>A&amp;B</td><td>2</td></tr></table>",
                    "bbox": [0, 0, 10, 10],
                },
                {"type": "image", "text": "logo", "bbox": [0, 0, 10, 10]},
            ]
        }
    }
    [table] = parse_page_blocks(payload, image_size=IMAGE_SIZE)
    assert table.lines == ["Name Qty", "A&B 2"]


def test_archive_pages_map_to_upload_order_and_missing_pages_are_flagged() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "metadata/page_002.json",
            json.dumps({"blocks": [{"text": "two", "bbox": [0, 0, 1, 1]}]}),
        )
        archive.writestr("manifest.json", "{}")
    first, second = parse_digitise_archive(
        buffer.getvalue(), image_sizes=[IMAGE_SIZE, IMAGE_SIZE]
    )
    assert not first.ok
    assert second.ok and second.blocks[0].lines == ["two"]


def test_real_digitise_archive_layout() -> None:
    """The layout of a real Digitise result (checked 2026-10), pages out of order."""

    def block(tag: str, text: str, top: int) -> dict:
        return {
            "block_id": "b",
            "coordinates": {"x1": 100, "y1": top, "x2": 500, "y2": top + 100},
            "bbox_norm": [0.1, top / 2000, 0.5, (top + 100) / 2000],
            "layout_tag": tag,
            "confidence": 0.87,
            "reading_order": 1,
            "text": text,
        }

    document = {
        "document_id": "d",
        "filename": "pages.zip",
        "page_count": 2,
        "pages": [
            {
                "page_num": 2,
                "image_width": 1000,
                "image_height": 2000,
                "blocks": [block("paragraph", "second", 0)],
            },
            {
                "page_num": 1,
                "image_width": 1000,
                "image_height": 2000,
                "blocks": [
                    block("paragraph", "first", 500),
                    block("image", "chart label", 1000),
                ],
            },
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pages.zip/pages.json", json.dumps(document))
        archive.writestr(
            "manifest.json", json.dumps({"status": "completed", "page_count": 2})
        )

    first, second = parse_digitise_archive(
        buffer.getvalue(), image_sizes=[IMAGE_SIZE, IMAGE_SIZE]
    )
    assert [b.lines for b in first.blocks] == [["first"]]
    assert first.blocks[0].tag == "paragraph"
    assert first.blocks[0].confidence == pytest.approx(0.87)
    assert first.blocks[0].bbox == pytest.approx((0.1, 0.25, 0.5, 0.3))
    assert second.blocks[0].lines == ["second"]


def test_combined_json_with_page_list() -> None:
    document = {
        "pages": [
            {"page_number": 1, "blocks": [{"content": "one", "box": [0, 0, 0.5, 0.5]}]}
        ]
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("document.json", json.dumps(document))
    [page] = parse_digitise_archive(buffer.getvalue(), image_sizes=[IMAGE_SIZE])
    assert page.ok and page.blocks[0].bbox == pytest.approx((0, 0, 0.5, 0.5))
