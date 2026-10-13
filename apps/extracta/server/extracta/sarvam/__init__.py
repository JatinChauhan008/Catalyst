"""Sarvam Vision OCR engine for Docling."""

from docling.models.factories import get_ocr_factory
from extracta.sarvam.ocr_model import SarvamOcrModel, SarvamOcrOptions


def ocr_engines() -> dict[str, list[type[SarvamOcrModel]]]:
    """Docling plugin hook, for use through a `docling` entry point."""
    return {"ocr_engines": [SarvamOcrModel]}


def register_sarvam_ocr() -> None:
    """Register the engine in the process-wide Docling OCR factories.

    Docling caches one factory per `allow_external_plugins` value, so the engine
    is added to both. Registering twice is harmless.
    """
    for allow_external_plugins in (False, True):
        factory = get_ocr_factory(allow_external_plugins=allow_external_plugins)
        if SarvamOcrOptions not in factory.classes:
            factory.register(SarvamOcrModel, "extracta", __name__)


__all__ = ["SarvamOcrModel", "SarvamOcrOptions", "ocr_engines", "register_sarvam_ocr"]
