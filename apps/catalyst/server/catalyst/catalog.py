"""Which pipelines and backends each input format can use, and how to build them.

This is the routing layer of Catalyst. Every supported format goes through
Docling; the catalog only decides which Docling pipeline and backend a format
may use, and with which option models.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from docling.backend.abstract_backend import AbstractDocumentBackend
from docling.backend.docling_parse_backend import ThreadedDoclingParseDocumentBackend
from docling.backend.image_backend import ImageDocumentBackend
from docling.backend.mets_gbs_backend import MetsGbsDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.backend_options import (
    MetsGbsBackendOptions,
    PdfBackendOptions,
    ThreadedDoclingParseBackendOptions,
)
from docling.datamodel.base_models import (
    FormatToExtensions,
    FormatToMimeType,
    InputFormat,
)
from docling.datamodel.pipeline_options import (
    AsrPipelineOptions,
    ConvertPipelineOptions,
    NativePdfPipelineOptions,
    PaginatedPipelineOptions,
    PdfPipelineOptions,
    PipelineOptions,
    ThreadedPdfPipelineOptions,
    VideoPipelineOptions,
    VlmPipelineOptions,
)
from docling.document_converter import (
    FormatOption,
    NativePdfFormatOption,
    _get_default_option,
)
from docling.pipeline.asr_pipeline import AsrPipeline
from docling.pipeline.base_pipeline import BasePipeline
from docling.pipeline.legacy_standard_pdf_pipeline import LegacyStandardPdfPipeline
from docling.pipeline.native_pdf_pipeline import NativePdfPipeline
from docling.pipeline.simple_pipeline import SimplePipeline
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline
from docling.pipeline.video_pipeline import VideoPipeline
from docling.pipeline.vlm_pipeline import VlmPipeline
from catalyst.options_schema import (
    FieldSpec,
    _unwrap,
    apply_overrides,
    describe_model,
    describe_model_class,
)
from catalyst.sarvam import SarvamOcrOptions


@dataclass(frozen=True)
class PipelineChoice:
    id: str
    label: str
    description: str
    pipeline_cls: type[BasePipeline]
    default_options: Callable[[], PipelineOptions]


@dataclass(frozen=True)
class BackendChoice:
    id: str
    label: str
    backend_cls: type[AbstractDocumentBackend]
    options_cls: type[BaseModel] | None


class PipelineSpec(BaseModel):
    id: str
    label: str
    description: str
    fields: list[FieldSpec]


class BackendSpec(BaseModel):
    id: str
    label: str
    fields: list[FieldSpec] | None


class FormatSpec(BaseModel):
    id: str
    extensions: list[str]
    mime_types: list[str]
    pipelines: list[str]
    default_pipeline: str
    backends: list[str]
    default_backend: str


class FormatConfig(BaseModel):
    """The form input for one input format. All parts are optional."""

    pipeline: str | None = None
    pipeline_options: dict[str, Any] = {}
    backend: str | None = None
    backend_options: dict[str, Any] = {}


class AppDefaults(BaseModel):
    """Catalyst's own defaults on top of Docling's defaults."""

    use_sarvam_ocr: bool = False


def _paginated_defaults(
    cls: type[PdfPipelineOptions], defaults: AppDefaults
) -> PdfPipelineOptions:
    options = cls()
    if defaults.use_sarvam_ocr:
        options.ocr_options = SarvamOcrOptions()
    return options


def pipeline_choices(defaults: AppDefaults) -> dict[str, PipelineChoice]:
    choices = [
        PipelineChoice(
            "standard",
            "Standard (layout + OCR + tables)",
            "Docling's model pipeline: PDF text layer, layout analysis, OCR where needed, "
            "table structure and reading order.",
            StandardPdfPipeline,
            lambda: _paginated_defaults(ThreadedPdfPipelineOptions, defaults),
        ),
        PipelineChoice(
            "vlm",
            "Vision-language model",
            "One VLM converts each page image. No separate layout or OCR stage.",
            VlmPipeline,
            VlmPipelineOptions,
        ),
        PipelineChoice(
            "native",
            "Native PDF (no models)",
            "Reads the PDF text layer only. Fast, but no OCR, no layout or table models.",
            NativePdfPipeline,
            NativePdfPipelineOptions,
        ),
        PipelineChoice(
            "legacy",
            "Legacy standard",
            "The previous, single-threaded standard pipeline.",
            LegacyStandardPdfPipeline,
            lambda: _paginated_defaults(PdfPipelineOptions, defaults),
        ),
        PipelineChoice(
            "asr",
            "Speech recognition",
            "Transcribes audio with a Whisper model.",
            AsrPipeline,
            AsrPipelineOptions,
        ),
        PipelineChoice(
            "video",
            "Video",
            "Transcribes the audio track and samples representative frames.",
            VideoPipeline,
            VideoPipelineOptions,
        ),
        PipelineChoice(
            "simple",
            "Simple (structured formats)",
            "Reads the structure of the file directly. Optional enrichment models only.",
            SimplePipeline,
            ConvertPipelineOptions,
        ),
    ]
    return {choice.id: choice for choice in choices}


def _format_pipelines(fmt: InputFormat) -> list[str]:
    if fmt == InputFormat.PDF:
        return ["standard", "vlm", "native", "legacy"]
    if fmt == InputFormat.IMAGE:
        return ["standard", "vlm", "legacy"]
    if fmt == InputFormat.METS_GBS:
        return ["standard", "legacy"]
    if fmt == InputFormat.AUDIO:
        return ["asr"]
    if fmt == InputFormat.VIDEO:
        return ["video"]
    return ["simple"]


def _single_model(annotation: Any) -> type[BaseModel] | None:
    core, _ = _unwrap(annotation)
    if inspect.isclass(core) and issubclass(core, BaseModel):
        return core
    return None


def _options_class_of_backend(
    backend_cls: type[AbstractDocumentBackend],
) -> type[BaseModel] | None:
    """The options model that a backend's constructor accepts, if it names exactly one."""
    try:
        hints = typing.get_type_hints(backend_cls.__init__)
    except Exception:
        return None
    return _single_model(hints.get("options"))


def backend_choices() -> dict[str, BackendChoice]:
    choices: dict[str, BackendChoice] = {
        "docling_parse": BackendChoice(
            "docling_parse",
            "docling-parse (threaded, default)",
            ThreadedDoclingParseDocumentBackend,
            ThreadedDoclingParseBackendOptions,
        ),
        "pypdfium2": BackendChoice(
            "pypdfium2", "pypdfium2", PyPdfiumDocumentBackend, PdfBackendOptions
        ),
        "image": BackendChoice("image", "Image", ImageDocumentBackend, None),
        "mets_gbs": BackendChoice(
            "mets_gbs", "METS/GBS", MetsGbsDocumentBackend, MetsGbsBackendOptions
        ),
    }
    for fmt in InputFormat:
        if fmt in (InputFormat.PDF, InputFormat.IMAGE, InputFormat.METS_GBS):
            continue
        default_option = _get_default_option(fmt)
        backend_cls = default_option.backend
        backend_id = backend_cls.__name__
        if backend_id not in choices:
            options_cls = _options_class_of_backend(backend_cls) or _single_model(
                type(default_option).model_fields["backend_options"].annotation
            )
            choices[backend_id] = BackendChoice(
                backend_id, backend_id, backend_cls, options_cls
            )
    return choices


def _format_backends(fmt: InputFormat) -> list[str]:
    if fmt == InputFormat.PDF:
        return ["docling_parse", "pypdfium2"]
    if fmt == InputFormat.IMAGE:
        return ["image"]
    if fmt == InputFormat.METS_GBS:
        return ["mets_gbs"]
    return [_get_default_option(fmt).backend.__name__]


class Catalog:
    """All routing choices, plus their option descriptions for the UI."""

    def __init__(self, defaults: AppDefaults) -> None:
        self.defaults = defaults
        self.pipelines = pipeline_choices(defaults)
        self.backends = backend_choices()
        self._description: dict[str, Any] | None = None

    def describe(self) -> dict[str, Any]:
        if self._description is None:
            self._description = self._build_description()
        return self._description

    def _build_description(self) -> dict[str, Any]:
        formats = [
            FormatSpec(
                id=fmt.value,
                extensions=FormatToExtensions.get(fmt, []),
                mime_types=FormatToMimeType.get(fmt, []),
                pipelines=_format_pipelines(fmt),
                default_pipeline=_format_pipelines(fmt)[0],
                backends=_format_backends(fmt),
                default_backend=_format_backends(fmt)[0],
            )
            for fmt in InputFormat
        ]
        pipelines = {
            choice.id: PipelineSpec(
                id=choice.id,
                label=choice.label,
                description=choice.description,
                fields=describe_model(choice.default_options()),
            )
            for choice in self.pipelines.values()
        }
        backends = {
            choice.id: BackendSpec(
                id=choice.id,
                label=choice.label,
                fields=describe_model_class(choice.options_cls)
                if choice.options_cls
                else None,
            )
            for choice in self.backends.values()
        }
        return {
            "formats": [spec.model_dump() for spec in formats],
            "pipelines": {key: spec.model_dump() for key, spec in pipelines.items()},
            "backends": {key: spec.model_dump() for key, spec in backends.items()},
        }

    def build_format_option(
        self, fmt: InputFormat, config: FormatConfig, *, images_needed: bool
    ) -> FormatOption:
        pipeline_ids = _format_pipelines(fmt)
        pipeline_id = config.pipeline or pipeline_ids[0]
        if pipeline_id not in pipeline_ids:
            raise ValueError(f"{fmt.value}: pipeline {pipeline_id!r} is not available.")
        backend_ids = _format_backends(fmt)
        backend_id = config.backend or backend_ids[0]
        if backend_id not in backend_ids:
            raise ValueError(f"{fmt.value}: backend {backend_id!r} is not available.")

        pipeline = self.pipelines[pipeline_id]
        backend = self.backends[backend_id]

        base_options = pipeline.default_options()
        if isinstance(base_options, PaginatedPipelineOptions):
            # Same rule as the CLI: render images only when an output embeds them.
            if images_needed:
                base_options.generate_page_images = True
                base_options.generate_picture_images = True
                base_options.images_scale = 2
            elif isinstance(base_options, NativePdfPipelineOptions):
                base_options.generate_page_images = False
        pipeline_options = apply_overrides(
            base_options, config.pipeline_options, f"{fmt.value}.pipeline."
        )
        if (
            isinstance(pipeline_options, ThreadedPdfPipelineOptions)
            and isinstance(pipeline_options.ocr_options, SarvamOcrOptions)
            and "ocr_batch_size" not in config.pipeline_options
        ):
            # The OCR stage receives this many pages at a time; let one Sarvam job
            # carry as many pages as it may (10) instead of the default 4.
            pipeline_options.ocr_batch_size = max(
                pipeline_options.ocr_batch_size,
                pipeline_options.ocr_options.pages_per_job,
            )

        backend_options = None
        if config.backend_options:
            if backend.options_cls is None:
                raise ValueError(f"{fmt.value}: backend {backend_id!r} has no options.")
            backend_options = apply_overrides(
                backend.options_cls(), config.backend_options, f"{fmt.value}.backend."
            )

        if pipeline_id == "native":
            if backend_id != "docling_parse":
                raise ValueError("The native pipeline needs the docling_parse backend.")
            return NativePdfFormatOption(
                pipeline_options=pipeline_options, backend_options=backend_options
            )

        option_cls = type(_get_default_option(fmt))
        return option_cls(
            pipeline_cls=pipeline.pipeline_cls,
            pipeline_options=pipeline_options,
            backend=backend.backend_cls,
            backend_options=backend_options,
        )

    def pipeline_label(
        self, fmt: InputFormat, config: FormatConfig | None
    ) -> tuple[str, str]:
        pipeline = (config.pipeline if config else None) or _format_pipelines(fmt)[0]
        backend = (config.backend if config else None) or _format_backends(fmt)[0]
        return pipeline, backend
