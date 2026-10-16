"""Save every image of a document as its own file, in reading order.

For a PDF, the images stored in the file are written as they are stored
(a JPEG stays a JPEG, at its own resolution); pdfium decodes and writes the
other encodings as PNG. One image that the PDF draws several times is
written once. A picture that the layout model finds but that is not a stored
image (a vector chart or diagram) is rendered from the page. On a scanned
page the one stored image is the page itself: it is not a picture of the
document, so the pictures that the layout model finds on it are cut out of it
instead (or the scan is saved when `include_page_scans` is on).

For other formats, the pictures that Docling found are written as PNG.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from docling_core.types.doc import DoclingDocument, PictureItem
from PIL import Image

from catalyst.dost.models import DostIssue, DostSettings, ImageCounts, ImageRecord

# One stored image that covers this share of the page makes the page a scan.
_SCAN_AREA_SHARE = 0.8
# ... when the page has fewer visible text objects than this. A scan with an
# OCR text layer ("searchable PDF") has invisible text only.
_SCAN_MAX_TEXT_OBJECTS = 5
# A picture is the stored image when that image covers this share of it.
_COVERED_SHARE = 0.5

Box = tuple[float, float, float, float]  # left, top, right, bottom; top-left origin


@dataclass
class _Candidate:
    page: int | None
    box: Box | None
    kind: str
    temp_file: Path
    width: int
    height: int
    caption: str | None = None
    occurrences: int = 1


@dataclass
class ImageResult:
    records: list[ImageRecord] = field(default_factory=list)
    counts: ImageCounts = field(default_factory=ImageCounts)
    issues: list[DostIssue] = field(default_factory=list)
    scanned_pages: list[int] = field(default_factory=list)


def extract_images(
    document: DoclingDocument,
    pdf_bytes: bytes | None,
    settings: DostSettings,
    target: Path,
) -> ImageResult:
    target.mkdir(parents=True, exist_ok=True)
    result = ImageResult()
    pictures = [
        item
        for item, _ in document.iterate_items(with_groups=False)
        if isinstance(item, PictureItem)
    ]
    with tempfile.TemporaryDirectory(dir=target) as temp:
        work = Path(temp)
        if pdf_bytes is not None:
            candidates = _from_pdf(
                document, pdf_bytes, pictures, settings, work, result
            )
        else:
            candidates = _from_pictures(document, pictures, work, result)
        candidates.sort(
            key=lambda c: (
                c.page if c.page is not None else 10**9,
                c.box[1] if c.box else 0.0,
                c.box[0] if c.box else 0.0,
            )
        )
        for number, candidate in enumerate(candidates, start=1):
            extension = candidate.temp_file.suffix.lower()
            if extension == ".jpeg":
                extension = ".jpg"
            name = f"image_{number:03d}{extension}"
            final = target / name
            shutil.move(candidate.temp_file, final)
            data = final.read_bytes()
            result.records.append(
                ImageRecord(
                    filename=name,
                    page=candidate.page,
                    bbox=tuple(round(v, 2) for v in candidate.box)
                    if candidate.box
                    else None,
                    kind=candidate.kind,
                    format=extension.lstrip("."),
                    width_px=candidate.width,
                    height_px=candidate.height,
                    sha256=hashlib.sha256(data).hexdigest(),
                    occurrences=candidate.occurrences,
                    caption=candidate.caption,
                )
            )
    result.counts.files = len(result.records)
    result.counts.embedded = sum(1 for r in result.records if r.kind == "embedded")
    result.counts.rendered = sum(1 for r in result.records if r.kind == "rendered")
    return result


# ---------------------------------------------------------------------- PDF
def _from_pdf(
    document: DoclingDocument,
    pdf_bytes: bytes,
    pictures: list[PictureItem],
    settings: DostSettings,
    work: Path,
    result: ImageResult,
) -> list[_Candidate]:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(io.BytesIO(pdf_bytes))
    candidates: list[_Candidate] = []
    seen: dict[str, _Candidate] = {}
    pictures_by_page: dict[int, list[PictureItem]] = {}
    for picture in pictures:
        if picture.prov:
            pictures_by_page.setdefault(picture.prov[0].page_no, []).append(picture)

    for page_no in sorted(document.pages):
        page = pdf[page_no - 1]
        width, height = page.get_size()
        page_area = max(width * height, 1.0)
        stored_boxes: list[Box] = []
        scanned = False
        placed, visible_text = _page_objects(page)
        for obj, (left, bottom, right, top) in placed:
            box: Box = (left, height - top, right, height - bottom)
            share = (right - left) * (top - bottom) / page_area
            if share >= _SCAN_AREA_SHARE and visible_text < _SCAN_MAX_TEXT_OBJECTS:
                scanned = True
                if not settings.include_page_scans:
                    result.counts.page_scans_skipped += 1
                    continue
            else:
                stored_boxes.append(box)
            try:
                px_width, px_height = obj.get_px_size()
                if min(px_width, px_height) < settings.min_image_px:
                    result.counts.too_small_skipped += 1
                    continue
                key = hashlib.sha256(
                    bytes(obj.get_data(decode_simple=False))
                    + repr((obj.get_filters(), px_width, px_height)).encode()
                ).hexdigest()
                if key in seen:
                    seen[key].occurrences += 1
                    result.counts.duplicates_skipped += 1
                    continue
                prefix = work / f"embedded-{len(candidates):05d}"
                obj.extract(prefix, fb_format="png")
                written = _written_file(work, prefix.name)
                written = _browser_format(written)
            except Exception as exc:
                result.counts.failed += 1
                result.issues.append(
                    DostIssue(
                        severity="error",
                        component="images",
                        page=page_no,
                        message=f"An embedded image could not be extracted: {type(exc).__name__}: {exc}",
                    )
                )
                continue
            candidate = _Candidate(
                page=page_no,
                box=box,
                kind="embedded",
                temp_file=written,
                width=px_width,
                height=px_height,
                caption=_caption_for(box, pictures_by_page.get(page_no, []), document),
            )
            seen[key] = candidate
            candidates.append(candidate)

        if scanned:
            result.scanned_pages.append(page_no)

        # Pictures that are not a stored image: render them from the page.
        for picture in pictures_by_page.get(page_no, []):
            box = _picture_box(picture, document)
            if box is None or any(
                _covered_share(box, stored) >= _COVERED_SHARE for stored in stored_boxes
            ):
                continue
            image = None
            if not scanned and page.get_rotation() == 0:
                scale = settings.render_dpi / 72
                left, top, right, bottom = box
                image = page.render(
                    scale=scale,
                    crop=(
                        max(left, 0),
                        max(height - bottom, 0),
                        max(width - right, 0),
                        max(top, 0),
                    ),
                ).to_pil()
            else:
                # A scan (possibly turned upright by Catalyst): cut the picture
                # out of Docling's page image, which uses the same frame.
                image = picture.get_image(document)
            candidate = _rendered(
                picture, document, image, box, work, len(candidates), result
            )
            if candidate is not None:
                candidates.append(candidate)
    pdf.close()
    return candidates


def _page_objects(page) -> tuple[list[tuple[object, Box]], int]:
    """The images of a page with their boxes in page space (PDF origin at the
    bottom left), and the number of visible text objects.

    pdfium gives the bounds of an object inside a form XObject in the form's
    own space, so the matrices of the enclosing forms are applied.
    """
    import pypdfium2
    import pypdfium2.raw as pdfium_c

    images: list[tuple[object, Box]] = []
    visible_text = 0
    forms: list[pypdfium2.PdfMatrix] = []  # page-space matrix of each form level
    for obj in page.get_objects():
        parent = forms[obj.level - 1] if obj.level else pypdfium2.PdfMatrix()
        if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            del forms[obj.level :]
            forms.append(obj.get_matrix().multiply(parent))
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            images.append((obj, parent.on_rect(*obj.get_bounds())))
        elif (
            obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT
            and pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw)
            != pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE
        ):
            visible_text += 1
    return images, visible_text


def _written_file(work: Path, stem: str) -> Path:
    found = sorted(work.glob(f"{stem}.*"))
    if not found:
        raise RuntimeError("pdfium wrote no file")
    return found[0]


def _browser_format(path: Path) -> Path:
    """JPEG 2000 (and other rare formats) become PNG when PIL can read them."""
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        return path
    try:
        with Image.open(path) as image:
            converted = path.with_suffix(".png")
            image.save(converted)
    except OSError:
        return path  # keep the original file; the format is in the report
    path.unlink()
    return converted


def _picture_box(picture: PictureItem, document: DoclingDocument) -> Box | None:
    if not picture.prov:
        return None
    prov = picture.prov[0]
    page = document.pages.get(prov.page_no)
    if page is None:
        return None
    box = prov.bbox.to_top_left_origin(page_height=page.size.height)
    return box.l, box.t, box.r, box.b


def _covered_share(picture: Box, stored: Box) -> float:
    """The share of the picture's area that the stored image covers."""
    left, top = max(picture[0], stored[0]), max(picture[1], stored[1])
    right, bottom = min(picture[2], stored[2]), min(picture[3], stored[3])
    area = (picture[2] - picture[0]) * (picture[3] - picture[1])
    if right <= left or bottom <= top or area <= 0:
        return 0.0
    return (right - left) * (bottom - top) / area


def _caption_for(
    box: Box, pictures: list[PictureItem], document: DoclingDocument
) -> str | None:
    for picture in pictures:
        picture_box = _picture_box(picture, document)
        if picture_box and _covered_share(picture_box, box) >= _COVERED_SHARE:
            return picture.caption_text(document) or None
    return None


# ----------------------------------------------------------- other formats
def _from_pictures(
    document: DoclingDocument,
    pictures: list[PictureItem],
    work: Path,
    result: ImageResult,
) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for picture in pictures:
        candidate = _rendered(
            picture,
            document,
            picture.get_image(document),
            _picture_box(picture, document),
            work,
            len(candidates),
            result,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _rendered(
    picture: PictureItem,
    document: DoclingDocument,
    image: Image.Image | None,
    box: Box | None,
    work: Path,
    number: int,
    result: ImageResult,
) -> _Candidate | None:
    page = picture.prov[0].page_no if picture.prov else None
    if image is None:
        result.counts.failed += 1
        result.issues.append(
            DostIssue(
                severity="error",
                component="images",
                page=page,
                message=f"Picture {picture.self_ref} has no image data and could not be rendered.",
            )
        )
        return None
    path = work / f"rendered-{number:05d}.png"
    image.save(path)
    return _Candidate(
        page=page,
        box=box,
        kind="rendered",
        temp_file=path,
        width=image.width,
        height=image.height,
        caption=picture.caption_text(document) or None,
    )
