"""HTML per page, with pictures saved as separate image files."""

from __future__ import annotations

import json
import re
from pathlib import Path

from extracta.models import ConvertRequest, PictureManifest

PAPER = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "data"
    / "pdf"
    / "sources"
    / "2206.01062.pdf"
)


def _file(service, envelope, url: str) -> Path:
    path = service.job_file(envelope.job_id, url.split("/files/", 1)[1])
    assert path is not None, url
    return path


def test_each_page_gets_html_that_links_its_pictures_as_files(service) -> None:
    request = {
        "settings": {"page_range_start": 1, "page_range_end": 3},
        "export": {"to_formats": ["md"]},
        "pictures": {"enabled": True},
        "pages": {"enabled": True},
    }
    envelope = service.convert(
        PAPER.name, PAPER.read_bytes(), ConvertRequest.model_validate(request)
    )
    assert envelope.status == "success", envelope.errors

    # Pictures: one PNG each, with page, box and caption.
    assert envelope.pictures
    figure = envelope.pictures[0]
    assert figure.picture_id.startswith(envelope.source.sha256[:12])
    assert figure.page == 1 and figure.regions and figure.caption.startswith("Figure 1")
    picture_file = _file(service, envelope, figure.files["image"])
    assert picture_file.suffix == ".png" and picture_file.stat().st_size > 0
    manifest = next(o for o in envelope.outputs if o.format == "pictures_json")
    parsed = PictureManifest.model_validate(
        json.loads(_file(service, envelope, manifest.url).read_text("utf-8"))
    )
    assert [p.picture_id for p in parsed.pictures] == [
        p.picture_id for p in envelope.pictures
    ]

    # Pages: one HTML file per page, linked from the index, pictures as files.
    assert [link.page for link in envelope.pages] == [1, 2, 3]
    first_page = _file(service, envelope, envelope.pages[0].url)
    page_html = first_page.read_text("utf-8")
    sources = re.findall(r'<img[^>]*src="([^"]+)"', page_html)
    assert sources and not any(src.startswith("data:") for src in sources)
    assert (first_page.parent / sources[0]).resolve() == picture_file.resolve()
    assert 'href="page-002.html"' in page_html
    assert '<html lang="en"' in page_html
    index = next(o for o in envelope.outputs if o.format == "pages_html")
    assert "page-003.html" in _file(service, envelope, index.url).read_text("utf-8")
