"""Save every picture of a converted document as its own file, with metadata.

Each picture gets a stable ID (file hash, page, number on the page), its page
and box, caption and section, and its size in pixels. The images are cut from
the rendered pages, so the pipeline must generate picture images.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from docling_core.types.doc import DoclingDocument, NodeItem, PictureItem

from catalyst.models import (
    PictureExtractionSettings,
    PictureManifest,
    PictureSummary,
    TableSource,
)
from catalyst.tables import _regions, _section


def extract_pictures(
    document: DoclingDocument,
    source: TableSource,
    settings: PictureExtractionSettings,
    target: Path,
    url_for: Callable[[Path], str],
) -> tuple[list[PictureSummary], dict[str, Path], Path | None]:
    """Write the pictures and their manifest.

    Returns the summaries, the file of each picture by its Docling reference
    (for linking from the page HTML) and the manifest path.
    """
    items: list[NodeItem] = [
        item for item, _ in document.iterate_items(with_groups=False)
    ]
    target.mkdir(parents=True, exist_ok=True)
    summaries: list[PictureSummary] = []
    files: dict[str, Path] = {}
    per_page: dict[int, int] = {}

    for position, item in enumerate(items):
        if not isinstance(item, PictureItem):
            continue
        image = item.get_image(document)
        if image is None or min(image.size) < settings.min_size_px:
            continue
        regions = _regions(item, document, "pt")
        page = regions[0].page if regions else None
        if page is not None:
            per_page[page] = per_page.get(page, 0) + 1
            picture_id = f"{source.sha256[:12]}-p{page:03d}-i{per_page[page]:02d}"
        else:
            picture_id = f"{source.sha256[:12]}-i{len(summaries) + 1:03d}"

        path = target / f"{picture_id}.png"
        image.save(path)
        files[item.self_ref] = path
        summaries.append(
            PictureSummary(
                picture_id=picture_id,
                index=len(summaries) + 1,
                source=source,
                page=page,
                regions=regions,
                caption=item.caption_text(document) or None,
                section=_section(items, position, None),
                width_px=image.width,
                height_px=image.height,
                files={"image": url_for(path)},
            )
        )

    manifest = None
    if summaries:
        manifest = target / "pictures.json"
        manifest.write_text(
            PictureManifest(source=source, pictures=summaries).model_dump_json(
                indent=2
            ),
            encoding="utf-8",
        )
    return summaries, files, manifest
