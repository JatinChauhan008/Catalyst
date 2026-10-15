"""Write one HTML file per page, plus an index page.

Pictures are linked as separate image files: the files of the picture
extraction when it ran, else images written next to the pages. Running page
headers and footers are left out, as in the whole-document HTML.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Callable
from pathlib import Path

from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    TextItem,
)

from catalyst.models import PageLink

_BODY_OPEN = re.compile(r"<body[^>]*>", re.IGNORECASE)
_HTML_OPEN_WITHOUT_LANG = re.compile(r"<html(?![^>]*lang=)", re.IGNORECASE)
_ENCODED_BACKSLASH_IN_SRC = re.compile(r'src="[^"]*%5C[^"]*"')
_NAV_STYLE = (
    "<style>.catalyst-nav{display:flex;gap:16px;align-items:center;font:14px system-ui,"
    "sans-serif;padding:10px 16px;border-bottom:1px solid #e2e8f0;background:#f8fafc;"
    "position:sticky;top:0}.catalyst-nav a{color:#2563eb;text-decoration:none}"
    ".catalyst-nav span{color:#64748b;margin-left:auto}</style>"
)


def _page_name(page: int) -> str:
    return f"page-{page:03d}.html"


def _nav(page: int, pages: list[int]) -> str:
    index = pages.index(page)
    links = ['<a href="index.html">All pages</a>']
    if index > 0:
        links.append(
            f'<a href="{_page_name(pages[index - 1])}">&larr; Page {pages[index - 1]}</a>'
        )
    if index < len(pages) - 1:
        links.append(
            f'<a href="{_page_name(pages[index + 1])}">Page {pages[index + 1]} &rarr;</a>'
        )
    links.append(f"<span>Page {page} of {len(pages)}</span>")
    return f'<nav class="catalyst-nav">{"".join(links)}</nav>'


def _first_headings(document: DoclingDocument) -> dict[int, str]:
    headings: dict[int, str] = {}
    for item, _ in document.iterate_items(with_groups=False):
        if (
            isinstance(item, TextItem)
            and item.label in (DocItemLabel.SECTION_HEADER, DocItemLabel.TITLE)
            and item.prov
            and item.prov[0].page_no not in headings
        ):
            headings[item.prov[0].page_no] = item.text.strip()
    return headings


def write_page_html(
    document: DoclingDocument,
    target: Path,
    picture_files: dict[str, Path],
    html_lang: str,
    url_for: Callable[[Path], str],
) -> tuple[list[PageLink], Path | None]:
    """Write `page-NNN.html` for every page and `index.html`. Returns the links and the index."""
    pages = sorted(document.pages)
    if not pages:
        return [], None
    target.mkdir(parents=True, exist_ok=True)

    # Point every picture at an image file; work on a copy so the other
    # outputs keep their own image references.
    linked = document.model_copy(deep=True)
    images_dir = target / "images"
    for number, picture in enumerate(linked.pictures, start=1):
        if picture.image is None:
            continue
        path = picture_files.get(picture.self_ref)
        if path is None:
            image = picture.get_image(linked)
            if image is None:
                continue
            images_dir.mkdir(exist_ok=True)
            path = images_dir / f"picture-{number:03d}.png"
            image.save(path)
        relative = Path(os.path.relpath(path, target).replace(os.sep, "/"))
        picture.image = picture.image.model_copy(update={"uri": relative})

    headings = _first_headings(document)
    links: list[PageLink] = []
    for page in pages:
        page_html = linked.export_to_html(
            page_no=page, image_mode=ImageRefMode.REFERENCED, html_lang=html_lang
        )
        # Docling accepts html_lang but does not write it; screen readers and
        # browsers need it to pick the right voice and fonts.
        page_html = _HTML_OPEN_WITHOUT_LANG.sub(
            f'<html lang="{html.escape(html_lang)}"', page_html, count=1
        )
        # On Windows the image path comes back with backslashes, URL-encoded.
        page_html = _ENCODED_BACKSLASH_IN_SRC.sub(
            lambda m: m.group(0).replace("%5C", "/"), page_html
        )
        page_html = _BODY_OPEN.sub(
            lambda m: m.group(0) + _NAV_STYLE + _nav(page, pages), page_html, count=1
        )
        path = target / _page_name(page)
        path.write_text(page_html, encoding="utf-8")
        links.append(PageLink(page=page, url=url_for(path), heading=headings.get(page)))

    rows = "\n".join(
        f'<li><a href="{_page_name(link.page)}">Page {link.page}</a>'
        + (f" &mdash; {html.escape(link.heading)}" if link.heading else "")
        + "</li>"
        for link in links
    )
    title = html.escape(document.name or "Document")
    index = target / "index.html"
    index.write_text(
        f'<!DOCTYPE html>\n<html lang="{html.escape(html_lang)}"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>body{{font:15px system-ui,sans-serif;max-width:760px;"
        f"margin:40px auto;padding:0 16px}}li{{margin:6px 0}}a{{color:#2563eb}}</style></head>"
        f"<body><h1>{title}</h1><p>{len(links)} pages</p><ul>\n{rows}\n</ul></body></html>\n",
        encoding="utf-8",
    )
    return links, index
