"""Turn scanned pages upright and straight before Docling's models see them.

Docling's layout and table-structure models expect upright, straight pages. A
landscape table printed sideways on a portrait page gets no usable columns,
and a page scanned at an angle of one degree shifts the cells of long table
rows into the wrong row.

The correction applies to image-only pages: pages without a text layer that
are mostly covered by bitmaps (scans), and every page of an image file. For
each such page:

1. Sideways text. RapidOCR detects the text lines on a small render. When
   most lines are taller than wide, the page turns by 90 degrees.
2. Skew. A projection profile on the downscaled page finds the angle (up to
   5 degrees) at which the text rows are sharpest.
3. Which way is up. RapidOCR recognizes the longest lines of the straightened
   page as they are and turned over. When most lines read better turned over,
   the page turns by another 180 degrees.

The page backend is wrapped, so the page *is* the corrected page for all of
Docling: the page size, the rendered images, the bitmap regions and the
provenance of every item use the corrected frame. The stored page size and
page images in the DoclingDocument therefore match the boxes.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Optional

import numpy
from docling_core.types.doc import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.page import (
    BoundingRectangle,
    PdfPageBoundaryType,
    PdfPageGeometry,
    SegmentedPdfPage,
    TextCell,
)
from PIL import Image

from docling.backend.abstract_backend import AbstractDocumentBackend
from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
from docling.backend.image_backend import ImageDocumentBackend
from docling.backend.pdf_backend import PdfDocumentBackend, PdfPageBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.accelerator_options import AcceleratorOptions
from docling.datamodel.pipeline_options import RapidOcrOptions
from docling.document_converter import DocumentConverter, NativePdfFormatOption
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel

_log = logging.getLogger(__name__)

# A page is image-only when it has no text layer and bitmaps cover this share of it.
_MIN_BITMAP_COVERAGE = 0.5
# Long side, in pixels, of the render used for the decisions.
_PROBE_PIXELS = 1200
# Fewer clearly oriented text lines than this: the page is left as it is.
_MIN_LINES = 5
# Lines read both ways up to decide the direction (the longest ones), and the
# number of agreeing lines that ends the vote early.
_CLASSIFIED_LINES = 15
_UNANIMOUS_VOTES = 5
# Only this much of a line (width over height) is read in the vote.
_VOTE_ASPECT = 12
# A line votes only when one reading scores clearly higher. Text in a script
# that the recognizer does not know scores low both ways and does not vote.
_MIN_VOTE_MARGIN = 0.1
# An upright page is turned upside down only on a clear majority of the votes.
_UPSIDE_DOWN_SHARE = 0.75
_MAX_SKEW_DEGREES = 5.0
_MIN_SKEW_DEGREES = 0.2
# The sharpest projection must beat the unrotated one by this factor.
_MIN_SKEW_GAIN = 1.05
_PROFILE_PIXELS = 1000
_MAX_INK_SAMPLES = 200_000
_WHITE = (255, 255, 255)
# Full corrected renders kept per page (one per scale).
_CACHED_RENDERS = 2


@dataclass(frozen=True)
class PageCorrection:
    """How to turn a page upright, in PIL's counter-clockwise degrees.

    First the page turns by `quarter_turns` times 90 degrees (the page size
    swaps for odd turns), then it rotates by `skew_degrees` about its center
    (the page size stays).
    """

    quarter_turns: int = 0
    skew_degrees: float = 0.0

    @property
    def is_identity(self) -> bool:
        return self.quarter_turns == 0 and self.skew_degrees == 0.0

    def apply(self, image: Image.Image) -> Image.Image:
        if self.quarter_turns:
            image = image.transpose(_TRANSPOSE[self.quarter_turns])
        if self.skew_degrees:
            image = image.convert("RGB").rotate(
                self.skew_degrees,
                resample=Image.Resampling.BICUBIC,
                fillcolor=_WHITE,
            )
        return image


_TRANSPOSE = {
    1: Image.Transpose.ROTATE_90,
    2: Image.Transpose.ROTATE_180,
    3: Image.Transpose.ROTATE_270,
}


class _Frame:
    """Maps points between the original page and the corrected page."""

    def __init__(self, size: Size, correction: PageCorrection) -> None:
        self.width, self.height = size.width, size.height
        self.turns = correction.quarter_turns
        if self.turns % 2:
            self.out_width, self.out_height = self.height, self.width
        else:
            self.out_width, self.out_height = self.width, self.height
        angle = math.radians(correction.skew_degrees)
        self._cos, self._sin = math.cos(angle), math.sin(angle)
        self._cx, self._cy = self.out_width / 2, self.out_height / 2

    def forward(self, x: float, y: float) -> tuple[float, float]:
        w, h = self.width, self.height
        if self.turns == 1:
            x, y = y, w - x
        elif self.turns == 2:
            x, y = w - x, h - y
        elif self.turns == 3:
            x, y = h - y, x
        dx, dy = x - self._cx, y - self._cy
        # A counter-clockwise turn on screen, with the y axis pointing down.
        return (
            self._cx + dx * self._cos + dy * self._sin,
            self._cy - dx * self._sin + dy * self._cos,
        )

    def backward(self, x: float, y: float) -> tuple[float, float]:
        dx, dy = x - self._cx, y - self._cy
        x = self._cx + dx * self._cos - dy * self._sin
        y = self._cy + dx * self._sin + dy * self._cos
        w, h = self.width, self.height
        if self.turns == 1:
            return w - y, x
        if self.turns == 2:
            return w - x, h - y
        if self.turns == 3:
            return y, h - x
        return x, y

    def forward_box(self, box: BoundingBox, scale: float = 1.0) -> BoundingBox:
        """Original page to corrected page, both scaled by `scale`."""
        box = _top_left(box, self.height * scale)
        return _map_box(box, scale, self.forward, self.out_width, self.out_height)

    def backward_box(self, box: BoundingBox) -> BoundingBox:
        """Corrected page to original page."""
        box = _top_left(box, self.out_height)
        return _map_box(box, 1.0, self.backward, self.width, self.height)


def _top_left(box: BoundingBox, page_height: float) -> BoundingBox:
    if box.coord_origin == CoordOrigin.TOPLEFT:
        return box
    return box.to_top_left_origin(page_height)


def _map_box(
    box: BoundingBox,
    scale: float,
    point: Callable[[float, float], tuple[float, float]],
    width: float,
    height: float,
) -> BoundingBox:
    """The box around the mapped corners, clipped to the page (top-left origin)."""
    corners = [
        point(x / scale, y / scale) for x in (box.l, box.r) for y in (box.t, box.b)
    ]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    return BoundingBox(
        l=min(max(min(xs), 0.0), width) * scale,
        t=min(max(min(ys), 0.0), height) * scale,
        r=min(max(max(xs), 0.0), width) * scale,
        b=min(max(max(ys), 0.0), height) * scale,
        coord_origin=CoordOrigin.TOPLEFT,
    )


class _Detector:
    """Orientation and skew detection with a shared RapidOCR reader."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reader = None

    def _read(self, image: Image.Image, **kwargs):
        with self._lock:
            if self._reader is None:
                self._reader = RapidOcrModel(
                    enabled=True,
                    artifacts_path=None,
                    options=RapidOcrOptions(),
                    accelerator_options=AcceleratorOptions(),
                ).reader
            return self._reader(numpy.array(image.convert("RGB")), **kwargs)

    def correction(self, image: Image.Image) -> PageCorrection:
        """The correction of a page render; no correction when it has too little text."""
        lines = self._lines(image)
        if len(lines) < _MIN_LINES:
            return PageCorrection()
        tall = sum(1 for line in lines if line.tall)
        turns = 1 if tall > len(lines) - tall else 0
        # Lay the lines flat and straighten them before asking which way is up:
        # tilted lines do not fit their crop boxes.
        skew = -skew_angle(PageCorrection(quarter_turns=turns).apply(image)) or 0.0
        correction = PageCorrection(quarter_turns=turns, skew_degrees=skew)
        # The detected lines are rotated rectangles, so they can follow the
        # correction instead of being detected again.
        frame = _Frame(Size(width=image.width, height=image.height), correction)
        flat = [line.moved(frame.forward) for line in lines]
        share = self._upside_down_share(
            correction.apply(image), [line for line in flat if not line.tall]
        )
        # A sideways page must turn one way or the other: the majority decides.
        # An upright page turns over only on a clear majority.
        if share > (0.5 if turns else _UPSIDE_DOWN_SHARE):
            turns += 2
        return PageCorrection(quarter_turns=turns, skew_degrees=skew)

    def _lines(self, image: Image.Image) -> list[_Line]:
        """The detected text lines that are clearly longer than high (or the reverse)."""
        detected = self._read(image, use_det=True, use_cls=False, use_rec=False)
        if detected.boxes is None:
            return []
        lines = [
            _Line(tuple((float(x), float(y)) for x, y in box))
            for box in detected.boxes.tolist()
        ]
        return [line for line in lines if line.is_clear]

    def _upside_down_share(self, image: Image.Image, lines: list[_Line]) -> float:
        """The share of the longest lines that read better upside down.

        Each line is recognized as it is and turned over; the higher
        recognition score wins. RapidOCR's direction classifier is not used:
        it guesses near random on lines of digits, which fill statistical tables.
        """
        longest = sorted(lines, key=lambda line: line.length, reverse=True)
        votes = turned_over = 0
        for line in longest[:_CLASSIFIED_LINES]:
            left, top, right, bottom = line.box
            # The start of a long line is enough, and recognition time grows
            # with the line length.
            crop = image.crop(
                (left, top, min(right, left + _VOTE_ASPECT * (bottom - top)), bottom)
            )
            as_is = self._recognition_score(crop)
            over = self._recognition_score(crop.transpose(Image.Transpose.ROTATE_180))
            if abs(as_is - over) >= _MIN_VOTE_MARGIN:
                votes += 1
                turned_over += over > as_is
            if votes >= _UNANIMOUS_VOTES and turned_over in (0, votes):
                break  # clear enough; each line costs two recognitions
        return turned_over / votes if votes else 0.0

    def _recognition_score(self, line: Image.Image) -> float:
        read = self._read(line, use_det=False, use_cls=False, use_rec=True)
        return float(read.scores[0]) if read.scores else 0.0


@dataclass(frozen=True)
class _Line:
    """A detected text line: the corners of a (possibly rotated) rectangle."""

    corners: tuple[tuple[float, float], ...]

    @property
    def box(self) -> tuple[int, int, int, int]:
        xs = [x for x, _ in self.corners]
        ys = [y for _, y in self.corners]
        return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))

    @property
    def length(self) -> int:
        left, top, right, bottom = self.box
        return max(right - left, bottom - top)

    @property
    def tall(self) -> bool:
        left, top, right, bottom = self.box
        return bottom - top > right - left

    @property
    def is_clear(self) -> bool:
        """Clearly longer than high, or the reverse."""
        left, top, right, bottom = self.box
        width, height = right - left, bottom - top
        return max(width, height) >= 1.5 * min(width, height) and min(width, height) > 0

    def moved(self, point: Callable[[float, float], tuple[float, float]]) -> _Line:
        return _Line(tuple(point(x, y) for x, y in self.corners))


_detector = _Detector()


def detect_correction(image: Image.Image) -> PageCorrection:
    """The correction that turns a page render upright and straight."""
    return _detector.correction(image)


def skew_angle(image: Image.Image) -> float:
    """The counter-clockwise tilt of the text rows, in degrees (0 when unsure).

    The ink pixels are projected onto the vertical axis at each candidate
    angle; text rows give the sharpest profile (largest sum of squares) when
    the projection follows them.
    """
    gray = image.convert("L")
    factor = _PROFILE_PIXELS / max(gray.size)
    if factor < 1:
        gray = gray.resize(
            (max(1, round(gray.width * factor)), max(1, round(gray.height * factor))),
            Image.Resampling.BILINEAR,
        )
    pixels = numpy.asarray(gray, dtype=numpy.uint8)
    ys, xs = numpy.nonzero(pixels < _otsu_threshold(pixels))
    if len(xs) < 500:
        return 0.0
    if len(xs) > _MAX_INK_SAMPLES:
        keep = numpy.random.default_rng(0).choice(
            len(xs), _MAX_INK_SAMPLES, replace=False
        )
        xs, ys = xs[keep], ys[keep]
    xs = xs - pixels.shape[1] / 2
    ys = ys - pixels.shape[0] / 2

    def sharpness(degrees: float) -> float:
        angle = math.radians(degrees)
        projected = ys * math.cos(angle) + xs * math.sin(angle)
        counts = numpy.bincount(
            numpy.round(projected - projected.min()).astype(numpy.int64)
        ).astype(numpy.float64)
        return float(numpy.dot(counts, counts))

    coarse = numpy.arange(-_MAX_SKEW_DEGREES, _MAX_SKEW_DEGREES + 1e-9, 0.25)
    best = float(coarse[numpy.argmax([sharpness(d) for d in coarse])])
    fine = numpy.arange(best - 0.25, best + 0.25 + 1e-9, 0.02)
    scores = [sharpness(d) for d in fine]
    best = float(fine[int(numpy.argmax(scores))])
    if abs(best) < _MIN_SKEW_DEGREES or max(scores) < _MIN_SKEW_GAIN * sharpness(0.0):
        return 0.0
    return round(best, 2)


def _otsu_threshold(pixels: numpy.ndarray) -> int:
    histogram = numpy.bincount(pixels.ravel(), minlength=256).astype(numpy.float64)
    levels = numpy.arange(256)
    weight = numpy.cumsum(histogram)
    mass = numpy.cumsum(histogram * levels)
    total, total_mass = weight[-1], mass[-1]
    with numpy.errstate(divide="ignore", invalid="ignore"):
        between = (total_mass * weight / total - mass) ** 2 / (
            weight * (total - weight)
        )
    return int(numpy.nanargmax(between[:-1])) + 1


class UprightPageBackend(PdfPageBackend):
    """A page backend that shows an image-only page upright and straight."""

    def __init__(self, inner: PdfPageBackend) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self._frame: _Frame | None = None
        self._decided = False
        self._correction = PageCorrection()
        self._renders: dict[float, Image.Image] = {}

    # ------------------------------------------------------------- decision
    @property
    def correction_frame(self) -> _Frame | None:
        """The page frame mapping, or None when the page is used as it is."""
        with self._lock:
            if not self._decided:
                self._decided = True
                self._frame = self._decide()
            return self._frame

    def _decide(self) -> _Frame | None:
        inner = self._inner
        if not inner.is_valid() or not _is_image_only(inner):
            return None
        size = inner.get_size()
        scale = min(2.0, _PROBE_PIXELS / max(size.width, size.height, 1.0))
        try:
            correction = detect_correction(inner.get_page_image(scale=scale))
        except Exception:
            _log.exception("Page %s: orientation check failed", inner.page_no)
            return None
        if correction.is_identity:
            return None
        _log.info(
            "Page %s is image-only: turned by %d degrees and deskewed by %.2f degrees.",
            inner.page_no,
            correction.quarter_turns * 90,
            correction.skew_degrees,
        )
        self._correction = correction
        return _Frame(size, correction)

    # ----------------------------------------------------------- delegation
    @property
    def page_no(self) -> int:
        return self._inner.page_no

    def is_valid(self) -> bool:
        return self._inner.is_valid()

    def get_error_message(self) -> str:
        return self._inner.get_error_message()

    def get_size(self) -> Size:
        frame = self.correction_frame
        if frame is None:
            return self._inner.get_size()
        return Size(width=frame.out_width, height=frame.out_height)

    def get_page_image(
        self, scale: float = 1, cropbox: Optional[BoundingBox] = None
    ) -> Image.Image:
        frame = self.correction_frame
        if frame is None:
            return self._inner.get_page_image(scale=scale, cropbox=cropbox)
        full = self._render(scale)
        if cropbox is None:
            return full.copy()
        if cropbox.coord_origin != CoordOrigin.TOPLEFT:
            cropbox = cropbox.to_top_left_origin(frame.out_height)
        left = min(max(0.0, cropbox.l), frame.out_width)
        top = min(max(0.0, cropbox.t), frame.out_height)
        right = min(max(0.0, cropbox.r), frame.out_width)
        bottom = min(max(0.0, cropbox.b), frame.out_height)
        target = (
            max(1, round((right - left) * scale)),
            max(1, round((bottom - top) * scale)),
        )
        ratio_x = full.width / frame.out_width
        ratio_y = full.height / frame.out_height
        return full.resize(
            target,
            resample=Image.Resampling.BICUBIC,
            box=(left * ratio_x, top * ratio_y, right * ratio_x, bottom * ratio_y),
        )

    def _render(self, scale: float) -> Image.Image:
        with self._lock:
            cached = self._renders.get(scale)
        if cached is not None:
            return cached
        render = self._correction.apply(self._inner.get_page_image(scale=scale))
        with self._lock:
            self._renders[scale] = render
            while len(self._renders) > _CACHED_RENDERS:
                self._renders.pop(next(iter(self._renders)))
        return render

    def get_text_in_rect(self, bbox: BoundingBox) -> str:
        if self.correction_frame is None:
            return self._inner.get_text_in_rect(bbox)
        return ""  # an image-only page has no text layer

    def get_segmented_page(self) -> Optional[SegmentedPdfPage]:
        frame = self.correction_frame
        if frame is None:
            return self._inner.get_segmented_page()
        page = BoundingBox(
            l=0.0,
            t=0.0,
            r=frame.out_width,
            b=frame.out_height,
            coord_origin=CoordOrigin.BOTTOMLEFT,
        )
        return SegmentedPdfPage(
            dimension=PdfPageGeometry(
                angle=0.0,
                rect=BoundingRectangle.from_bounding_box(page),
                boundary_type=PdfPageBoundaryType.CROP_BOX,
                art_bbox=page,
                bleed_bbox=page,
                crop_bbox=page,
                media_bbox=page,
                trim_bbox=page,
            ),
            char_cells=[],
            word_cells=[],
            textline_cells=[],
            has_chars=False,
            has_words=False,
            has_lines=False,
        )

    def get_text_cells(self) -> Iterable[TextCell]:
        if self.correction_frame is None:
            return self._inner.get_text_cells()
        return []

    def get_visible_text_cells(self) -> Optional[list[TextCell]]:
        if self.correction_frame is None:
            return self._inner.get_visible_text_cells()
        return []

    def get_bitmap_rects(self, scale: float = 1) -> Iterable[BoundingBox]:
        frame = self.correction_frame
        if frame is None:
            return self._inner.get_bitmap_rects(scale=scale)
        return [
            frame.forward_box(rect, scale)
            for rect in self._inner.get_bitmap_rects(scale=scale)
        ]

    def has_content_in(
        self,
        *,
        bbox: BoundingBox,
        chars: bool = False,
        shapes: bool = True,
        bitmaps: bool = True,
    ) -> Optional[bool]:
        frame = self.correction_frame
        if frame is not None:
            if bbox.coord_origin != CoordOrigin.TOPLEFT:
                bbox = bbox.to_top_left_origin(frame.out_height)
            bbox = frame.backward_box(bbox)
        return self._inner.has_content_in(
            bbox=bbox, chars=chars, shapes=shapes, bitmaps=bitmaps
        )

    def get_shape_lines(
        self,
        *,
        horizontal: bool = True,
        vertical: bool = True,
        tolerance: float = 1e-3,
    ) -> Optional[list[BoundingBox]]:
        frame = self.correction_frame
        if frame is None:
            return self._inner.get_shape_lines(
                horizontal=horizontal, vertical=vertical, tolerance=tolerance
            )
        # Rotated rules are no longer horizontal or vertical segments.
        return None

    def get_connected_shape_bounding_boxes(
        self, *, tolerance: float = 0.0
    ) -> Optional[list[BoundingBox]]:
        boxes = self._inner.get_connected_shape_bounding_boxes(tolerance=tolerance)
        frame = self.correction_frame
        if frame is None or boxes is None:
            return boxes
        return [frame.forward_box(box) for box in boxes]

    def unload(self) -> None:
        with self._lock:
            self._renders.clear()
        self._inner.unload()


def _is_image_only(page: PdfPageBackend) -> bool:
    if any(cell.text.strip() for cell in page.get_text_cells()):
        return False
    size = page.get_size()
    area = size.width * size.height
    if area <= 0:
        return False
    page_box = BoundingBox(
        l=0, t=0, r=size.width, b=size.height, coord_origin=CoordOrigin.TOPLEFT
    )
    covered = sum(
        rect.intersection_area_with(page_box) for rect in page.get_bitmap_rects()
    )
    return covered >= _MIN_BITMAP_COVERAGE * area


class _UprightPages(PdfDocumentBackend):
    """Mixin for PDF document backends: every page comes wrapped."""

    def load_page(self, page_no: int) -> PdfPageBackend:
        return UprightPageBackend(super().load_page(page_no))

    def iter_pages(self) -> Iterator[PdfPageBackend]:
        for page in super().iter_pages():
            # The default iter_pages() goes through load_page(), which wraps already.
            yield (
                page
                if isinstance(page, UprightPageBackend)
                else UprightPageBackend(page)
            )


class UprightDoclingParseBackend(_UprightPages, ThreadedDoclingParseDocumentBackend):
    pass


class UprightPyPdfiumBackend(_UprightPages, PyPdfiumDocumentBackend):
    pass


class UprightImageBackend(_UprightPages, ImageDocumentBackend):
    pass


UPRIGHT_BACKENDS: dict[type[AbstractDocumentBackend], type[PdfDocumentBackend]] = {
    ThreadedDoclingParseDocumentBackend: UprightDoclingParseBackend,
    PyPdfiumDocumentBackend: UprightPyPdfiumBackend,
    ImageDocumentBackend: UprightImageBackend,
}


def use_upright_backends(converter: DocumentConverter) -> None:
    """Let the paginated formats of a converter read their pages upright.

    Set after the converter is built: DocumentConverter replaces any image
    backend other than ImageDocumentBackend itself (even a subclass) when it
    normalizes its format options.
    """
    for option in converter.format_to_options.values():
        if isinstance(option, NativePdfFormatOption):
            continue  # the native pipeline renders no pages and runs no models
        upright = UPRIGHT_BACKENDS.get(option.backend)
        if upright is not None:
            option.backend = upright
