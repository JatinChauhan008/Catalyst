"""The Extracta flow: validate the upload, convert with Docling, export, check, wrap."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from docling.cli.export_utils import _should_generate_export_images
from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter
from docling.exceptions import ConversionError
from extracta.catalog import AppDefaults, Catalog, FormatConfig
from extracta.exporter import BINARY_FORMATS, MEDIA_TYPES, export_document
from extracta.furniture import move_repeated_furniture
from extracta.key_values import join_key_values
from extracta.models import (
    ConvertRequest,
    ConvertSettings,
    Envelope,
    EnvelopeSettings,
    ErrorInfo,
    ExportSettings,
    JobSummary,
    OutputItem,
    PageHtmlSettings,
    PictureExtractionSettings,
    ProcessingInfo,
    SourceInfo,
    TableExtractionSettings,
    TableSource,
    TableSummary,
    ValidationSettings,
)
from extracta.options_schema import (
    OptionsError,
    apply_overrides,
    describe_model,
    warm_factories,
)
from extracta.pages import write_page_html
from extracta.pictures import extract_pictures
from extracta.presets import register_presets
from extracta.sarvam import SarvamOcrOptions, register_sarvam_ocr
from extracta.sarvam.ocr_model import SARVAM_API_KEY_ENV
from extracta.tables import ExtractionContext, extract_tables, write_table_package
from extracta.upright import use_upright_backends
from extracta.validation import document_stats, validate

_log = logging.getLogger(__name__)

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_UNSAFE_NAME_RE = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


class ServerSettings(BaseSettings):
    """Server configuration, read from `EXTRACTA_*` environment variables."""

    model_config = SettingsConfigDict(env_prefix="EXTRACTA_", extra="ignore")

    data_dir: Path = Path(__file__).resolve().parents[2] / ".data"
    max_upload_mb: float = 200.0
    keep_jobs: int = 200
    converter_cache_size: int = 4
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    web_dist: Path | None = None


def _docling_version() -> str:
    try:
        return version("docling-slim")
    except PackageNotFoundError:
        return version("docling")


def _safe_filename(name: str) -> str:
    cleaned = _UNSAFE_NAME_RE.sub("_", Path(name).name).strip(" .")
    return cleaned or "upload"


class ExtractaService:
    def __init__(self, settings: ServerSettings) -> None:
        self.settings = settings
        register_sarvam_ocr()
        register_presets()
        warm_factories()
        self.sarvam_configured = bool(os.environ.get(SARVAM_API_KEY_ENV))
        self.catalog = Catalog(AppDefaults(use_sarvam_ocr=self.sarvam_configured))
        # Describing the options also registers the variant and preset ids that
        # requests refer to, so do it before the first request.
        self.catalog.describe()
        self.jobs_dir = settings.data_dir.resolve() / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._converters: OrderedDict[str, tuple[DocumentConverter, threading.Lock]] = (
            OrderedDict()
        )
        self._converters_lock = threading.Lock()

    # ----------------------------------------------------------------- catalog
    def describe(self) -> dict[str, Any]:
        description = dict(self.catalog.describe())
        description["general"] = {
            "settings": [
                f.model_dump()
                for f in describe_model(
                    ConvertSettings(max_file_size_mb=self.settings.max_upload_mb)
                )
            ],
            "export": [f.model_dump() for f in describe_model(ExportSettings())],
            "validation": [
                f.model_dump() for f in describe_model(ValidationSettings())
            ],
            "envelope": [f.model_dump() for f in describe_model(EnvelopeSettings())],
            "tables": [
                f.model_dump() for f in describe_model(TableExtractionSettings())
            ],
            "pictures": [
                f.model_dump() for f in describe_model(PictureExtractionSettings())
            ],
            "pages": [f.model_dump() for f in describe_model(PageHtmlSettings())],
        }
        description["server"] = {
            "docling_version": _docling_version(),
            "sarvam_configured": self.sarvam_configured,
            "max_upload_mb": self.settings.max_upload_mb,
        }
        return description

    # -------------------------------------------------------------- converters
    def _converter(
        self,
        formats: dict[str, FormatConfig],
        allowed: list[InputFormat] | None,
        images_needed: bool,
        straighten_pages: bool,
        ignore_text_layer: bool = False,
    ) -> tuple[DocumentConverter, threading.Lock]:
        unknown = set(formats) - {fmt.value for fmt in InputFormat}
        if unknown:
            raise OptionsError(f"Unknown input formats: {', '.join(sorted(unknown))}")
        key = json.dumps(
            {
                "formats": {k: v.model_dump(mode="json") for k, v in formats.items()},
                "allowed": [fmt.value for fmt in allowed] if allowed else None,
                "images": images_needed,
                "straighten": straighten_pages,
                "ignore_text": ignore_text_layer,
            },
            sort_keys=True,
        )
        with self._converters_lock:
            cached = self._converters.get(key)
            if cached is not None:
                self._converters.move_to_end(key)
                return cached

        format_options = {}
        for fmt in InputFormat:
            try:
                format_options[fmt] = self.catalog.build_format_option(
                    fmt,
                    formats.get(fmt.value, FormatConfig()),
                    images_needed=images_needed,
                )
            except OptionsError:
                raise
            except ValueError as exc:
                raise OptionsError(str(exc)) from exc
        converter = DocumentConverter(
            allowed_formats=allowed or None, format_options=format_options
        )
        if straighten_pages or ignore_text_layer:
            use_upright_backends(
                converter, straighten=straighten_pages, ignore_text=ignore_text_layer
            )
        entry = (converter, threading.Lock())
        with self._converters_lock:
            self._converters[key] = entry
            while len(self._converters) > self.settings.converter_cache_size:
                self._converters.popitem(last=False)
        return entry

    # ----------------------------------------------------------------- convert
    def convert(self, filename: str, data: bytes, request: ConvertRequest) -> Envelope:
        job_id = uuid.uuid4().hex
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True)
        source = SourceInfo(
            filename=_safe_filename(filename),
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        envelope = Envelope(
            job_id=job_id,
            created_at=datetime.now(timezone.utc),
            status="rejected",
            source=source,
        )
        try:
            envelope = self._convert(job_dir, data, request, envelope)
        finally:
            (job_dir / "envelope.json").write_text(
                envelope.model_dump_json(indent=2), encoding="utf-8"
            )
            self._prune_jobs()
        return envelope

    def _convert(
        self, job_dir: Path, data: bytes, request: ConvertRequest, envelope: Envelope
    ) -> Envelope:
        def reject(message: str) -> Envelope:
            envelope.status = "rejected"
            envelope.errors.append(ErrorInfo(component="validation", message=message))
            return envelope

        try:
            settings = _apply(ConvertSettings(), request.settings)
            export = _apply(ExportSettings(), request.export)
            checks = _apply(ValidationSettings(), request.validation)
            envelope_settings = _apply(EnvelopeSettings(), request.envelope)
            table_settings = _apply(TableExtractionSettings(), request.tables)
            picture_settings = _apply(PictureExtractionSettings(), request.pictures)
            page_settings = _apply(PageHtmlSettings(), request.pages)
        except OptionsError as exc:
            return reject(f"Invalid options: {exc}")

        size_limit_mb = min(settings.max_file_size_mb, self.settings.max_upload_mb)
        if not data:
            return reject("The file is empty.")
        if len(data) > size_limit_mb * 1024 * 1024:
            return reject(f"The file is larger than {size_limit_mb:g} MB.")
        if (
            settings.page_range_end is not None
            and settings.page_range_end < settings.page_range_start
        ):
            return reject("The last page is before the first page.")

        if envelope_settings.include_original:
            original = job_dir / "original" / envelope.source.filename
            original.parent.mkdir()
            original.write_bytes(data)
            envelope.original_url = self._file_url(
                envelope.job_id, original.relative_to(job_dir)
            )

        images_needed = _should_generate_export_images(
            export.image_export_mode, export.to_formats
        ) or (
            (table_settings.enabled and table_settings.include_images)
            or picture_settings.enabled
            or page_settings.enabled
        )
        try:
            converter, lock = self._converter(
                request.formats,
                settings.allowed_formats,
                images_needed,
                settings.straighten_scanned_pages,
                settings.ignore_text_layer,
            )
        except OptionsError as exc:
            return reject(f"Invalid options: {exc}")

        started = time.monotonic()
        stream = DocumentStream(name=envelope.source.filename, stream=BytesIO(data))
        try:
            with lock:
                result = converter.convert(
                    stream,
                    raises_on_error=False,
                    max_num_pages=settings.max_num_pages or sys.maxsize,
                    max_file_size=int(size_limit_mb * 1024 * 1024),
                    page_range=(
                        settings.page_range_start,
                        settings.page_range_end or sys.maxsize,
                    ),
                )
        except ConversionError as exc:
            return reject(str(exc))
        except Exception as exc:
            # For example a pipeline that cannot start: a missing API key or model.
            _log.exception("Conversion of %s failed", envelope.source.filename)
            envelope.status = "failure"
            envelope.errors.append(
                ErrorInfo(component="pipeline", message=f"{type(exc).__name__}: {exc}")
            )
            return envelope
        duration = time.monotonic() - started

        fmt = result.input.format
        envelope.source.detected_format = fmt.value if fmt else None
        envelope.errors.extend(
            ErrorInfo(
                component=str(error.component_type.value),
                module=error.module_name,
                message=error.error_message,
            )
            for error in result.errors
        )
        envelope.processing = self._processing_info(
            converter, fmt, request.formats, duration
        )

        if fmt is None or result.status in (
            ConversionStatus.SKIPPED,
            ConversionStatus.PENDING,
        ):
            if not envelope.errors:
                envelope.errors.append(
                    ErrorInfo(
                        component="validation",
                        message="The file type is not supported or not allowed.",
                    )
                )
            envelope.status = "rejected"
            return envelope
        if result.status == ConversionStatus.FAILURE:
            envelope.status = "failure"
            return envelope

        if settings.remove_repeated_headers:
            cleanup = move_repeated_furniture(result.document)
            envelope.processing.headers_removed = cleanup.moved + cleanup.trimmed

        if settings.join_key_values:
            envelope.processing.key_values_joined = join_key_values(result.document)

        stem = Path(envelope.source.filename).stem or "document"
        outputs_dir = job_dir / "outputs"
        for to_format in export.to_formats:
            try:
                path = export_document(
                    result.document,
                    to_format,
                    outputs_dir / to_format.value,
                    stem,
                    export,
                )
            except Exception as exc:
                _log.exception("Export to %s failed", to_format.value)
                envelope.errors.append(
                    ErrorInfo(
                        component="export", module=to_format.value, message=str(exc)
                    )
                )
                continue
            size = path.stat().st_size
            content = None
            if to_format not in BINARY_FORMATS and size <= export.inline_max_kb * 1024:
                content = path.read_text(encoding="utf-8")
            envelope.outputs.append(
                OutputItem(
                    format=to_format.value,
                    filename=path.name,
                    media_type=MEDIA_TYPES[to_format],
                    size_bytes=size,
                    url=self._file_url(envelope.job_id, path.relative_to(job_dir)),
                    content=content,
                )
            )

        if table_settings.enabled:
            self._extract_tables(
                result,
                envelope,
                job_dir,
                outputs_dir,
                data,
                converter,
                table_settings,
                export,
                text_layer_ignored=settings.ignore_text_layer,
            )

        if picture_settings.enabled or page_settings.enabled:
            self._write_pictures_and_pages(
                result,
                envelope,
                job_dir,
                outputs_dir,
                converter,
                picture_settings,
                page_settings,
            )

        if outputs_dir.exists():
            bundle = job_dir / "bundle.zip"
            with zipfile.ZipFile(
                bundle, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for file in sorted(outputs_dir.rglob("*")):
                    if file.is_file():
                        archive.write(file, file.relative_to(outputs_dir))
            envelope.bundle_url = self._file_url(envelope.job_id, Path("bundle.zip"))

        envelope.stats = document_stats(result.document)
        envelope.validation = validate(
            result.document, result.status, envelope.stats, envelope.outputs, checks
        )
        envelope.status = (
            "success"
            if result.status == ConversionStatus.SUCCESS
            else "partial_success"
        )
        return envelope

    def _write_pictures_and_pages(
        self,
        result: Any,
        envelope: Envelope,
        job_dir: Path,
        outputs_dir: Path,
        converter: DocumentConverter,
        picture_settings: PictureExtractionSettings,
        page_settings: PageHtmlSettings,
    ) -> None:
        def url_for(path: Path) -> str:
            return self._file_url(envelope.job_id, path.relative_to(job_dir))

        source = TableSource(
            filename=envelope.source.filename,
            sha256=envelope.source.sha256,
            detected_format=envelope.source.detected_format,
            page_count=len(result.document.pages),
        )
        picture_files: dict[str, Path] = {}
        try:
            if picture_settings.enabled:
                pictures, picture_files, manifest = extract_pictures(
                    result.document,
                    source,
                    picture_settings,
                    outputs_dir / "pictures",
                    url_for,
                )
                envelope.pictures = pictures
                if manifest is not None:
                    envelope.outputs.append(
                        OutputItem(
                            format="pictures_json",
                            filename=manifest.name,
                            media_type="application/json",
                            size_bytes=manifest.stat().st_size,
                            url=url_for(manifest),
                        )
                    )
            if page_settings.enabled:
                lang = page_settings.html_lang or _ocr_html_lang(
                    converter, result.input.format
                )
                envelope.pages, index = write_page_html(
                    result.document, outputs_dir / "pages", picture_files, lang, url_for
                )
                if index is not None:
                    envelope.outputs.append(
                        OutputItem(
                            format="pages_html",
                            filename=index.name,
                            media_type="text/html",
                            size_bytes=index.stat().st_size,
                            url=url_for(index),
                        )
                    )
        except Exception as exc:
            _log.exception("Picture or page export failed")
            envelope.errors.append(
                ErrorInfo(component="pages", message=f"{type(exc).__name__}: {exc}")
            )

    def _extract_tables(
        self,
        result: Any,
        envelope: Envelope,
        job_dir: Path,
        outputs_dir: Path,
        data: bytes,
        converter: DocumentConverter,
        settings: TableExtractionSettings,
        export: ExportSettings,
        *,
        text_layer_ignored: bool = False,
    ) -> None:
        fmt = result.input.format
        option = converter.format_to_options.get(fmt)
        pipeline_options = option.pipeline_options if option else None
        ocr = (
            pipeline_options.ocr_options
            if isinstance(pipeline_options, PdfPipelineOptions)
            else None
        )
        context = ExtractionContext(
            source=TableSource(
                filename=envelope.source.filename,
                sha256=envelope.source.sha256,
                detected_format=fmt.value,
                page_count=len(result.document.pages),
            ),
            is_pdf=fmt == InputFormat.PDF,
            is_image=fmt == InputFormat.IMAGE,
            text_layer_ignored=text_layer_ignored,
            pdf_bytes=data if fmt == InputFormat.PDF else None,
            ocr_engine=envelope.processing.ocr_engine if envelope.processing else None,
            table_text=ocr.table_text if isinstance(ocr, SarvamOcrOptions) else None,
        )

        def url_for(path: Path) -> str:
            return self._file_url(envelope.job_id, path.relative_to(job_dir))

        try:
            records, items = extract_tables(result.document, context, settings)
            package = write_table_package(
                records,
                items,
                result.document,
                outputs_dir / "tables",
                settings,
                url_for,
            )
        except Exception as exc:
            _log.exception("Table extraction failed")
            envelope.errors.append(
                ErrorInfo(component="tables", message=f"{type(exc).__name__}: {exc}")
            )
            return
        envelope.tables = [
            TableSummary.model_validate(record.model_dump(exclude={"rows"}))
            for record in records
        ]
        media = {
            "tables_json": "application/json",
            "tables_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        for kind, path in package.items():
            size = path.stat().st_size
            inline = kind == "tables_json" and size <= export.inline_max_kb * 1024
            envelope.outputs.append(
                OutputItem(
                    format=kind,
                    filename=path.name,
                    media_type=media[kind],
                    size_bytes=size,
                    url=url_for(path),
                    content=path.read_text(encoding="utf-8") if inline else None,
                )
            )

    def _processing_info(
        self,
        converter: DocumentConverter,
        fmt: InputFormat | None,
        formats: dict[str, FormatConfig],
        duration: float,
    ) -> ProcessingInfo:
        info = ProcessingInfo(
            docling_version=_docling_version(), duration_seconds=round(duration, 3)
        )
        if fmt is None:
            return info
        info.pipeline, info.backend = self.catalog.pipeline_label(
            fmt, formats.get(fmt.value)
        )
        option = converter.format_to_options.get(fmt)
        pipeline_options = option.pipeline_options if option else None
        if isinstance(pipeline_options, PdfPipelineOptions) and pipeline_options.do_ocr:
            info.ocr_engine = pipeline_options.ocr_options.kind
        return info

    # -------------------------------------------------------------------- jobs
    @staticmethod
    def _file_url(job_id: str, relative: Path) -> str:
        return f"/api/jobs/{job_id}/files/{relative.as_posix()}"

    def list_jobs(self, limit: int = 50) -> list[JobSummary]:
        """The newest jobs first, read from their saved envelopes."""
        envelopes = sorted(
            self.jobs_dir.glob("*/envelope.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        jobs = []
        for path in envelopes[:limit]:
            try:
                envelope = Envelope.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except ValueError:
                continue  # an envelope from an older version
            jobs.append(JobSummary.from_envelope(envelope))
        return jobs

    def job_envelope(self, job_id: str) -> Envelope | None:
        path = self.job_file(job_id, "envelope.json")
        if path is None:
            return None
        return Envelope.model_validate_json(path.read_text(encoding="utf-8"))

    def job_file(self, job_id: str, relative: str) -> Path | None:
        if not _JOB_ID_RE.match(job_id):
            return None
        job_dir = (self.jobs_dir / job_id).resolve()
        target = (job_dir / relative).resolve()
        if not target.is_relative_to(job_dir) or not target.is_file():
            return None
        return target

    def _prune_jobs(self) -> None:
        jobs = sorted(
            (path for path in self.jobs_dir.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in jobs[self.settings.keep_jobs :]:
            shutil.rmtree(stale, ignore_errors=True)


def _apply(model: BaseModel, overrides: dict[str, Any]) -> Any:
    return apply_overrides(model, overrides) if overrides else model


def _ocr_html_lang(converter: DocumentConverter, fmt: InputFormat | None) -> str:
    """The HTML `lang` of the OCR language ("hi-IN" -> "hi"), else "en"."""
    option = converter.format_to_options.get(fmt) if fmt else None
    pipeline_options = option.pipeline_options if option else None
    if isinstance(pipeline_options, PdfPipelineOptions) and pipeline_options.do_ocr:
        lang = pipeline_options.ocr_options.lang
        if lang and isinstance(pipeline_options.ocr_options, SarvamOcrOptions):
            return lang[0].removeprefix("iso:").split("-")[0]
    return "en"
