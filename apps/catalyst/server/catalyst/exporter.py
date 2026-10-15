"""Write the requested output formats of a converted document.

This follows `docling.cli.main.export_documents`, with two differences: each
format goes into its own folder (the HTML and split-page HTML outputs share a
file name), and partially converted documents are exported too.
"""

from __future__ import annotations

import json
from pathlib import Path

from docling_core.transforms.chunker.hierarchical_chunker import (
    DocChunk,
    HierarchicalChunker,
)
from docling_core.transforms.serializer.html import (
    HTMLDocSerializer,
    HTMLOutputStyle,
    HTMLParams,
)
from docling_core.transforms.serializer.latex import LaTeXDocSerializer
from docling_core.transforms.visualizer.layout_visualizer import LayoutVisualizer
from docling_core.types.doc import DoclingDocument, ImageRefMode

from catalyst.models import ChunkerType, ExportSettings
from docling.datamodel.base_models import OutputFormat
from docling.datamodel.service.responses import ChunkedDocumentResultItem

MEDIA_TYPES: dict[OutputFormat, str] = {
    OutputFormat.MARKDOWN: "text/markdown",
    OutputFormat.JSON: "application/json",
    OutputFormat.YAML: "application/yaml",
    OutputFormat.HTML: "text/html",
    OutputFormat.HTML_SPLIT_PAGE: "text/html",
    OutputFormat.TEXT: "text/plain",
    OutputFormat.DOCTAGS: "text/plain",
    OutputFormat.VTT: "text/vtt",
    OutputFormat.DOCLANG: "application/xml",
    OutputFormat.DCLX: "application/zip",
    OutputFormat.CHUNKS: "application/x-ndjson",
    OutputFormat.LATEX: "application/x-tex",
}

FILE_SUFFIXES: dict[OutputFormat, str] = {
    OutputFormat.MARKDOWN: ".md",
    OutputFormat.JSON: ".json",
    OutputFormat.YAML: ".yaml",
    OutputFormat.HTML: ".html",
    OutputFormat.HTML_SPLIT_PAGE: ".html",
    OutputFormat.TEXT: ".txt",
    OutputFormat.DOCTAGS: ".doctags",
    OutputFormat.VTT: ".vtt",
    OutputFormat.DOCLANG: ".dclg.xml",
    OutputFormat.DCLX: ".dclx",
    OutputFormat.CHUNKS: ".chunks.jsonl",
    OutputFormat.LATEX: ".tex",
}

BINARY_FORMATS = frozenset({OutputFormat.DCLX})


def export_document(
    document: DoclingDocument,
    to_format: OutputFormat,
    target_dir: Path,
    stem: str,
    settings: ExportSettings,
) -> Path:
    """Write one output format into `target_dir` and return the main file."""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{stem}{FILE_SUFFIXES[to_format]}"
    image_mode = settings.image_export_mode

    if (
        to_format in (OutputFormat.JSON, OutputFormat.YAML)
        and image_mode == ImageRefMode.PLACEHOLDER
    ):
        # Docling keeps page and picture images in JSON/YAML even with
        # placeholders; they are rendered for the image and table files.
        document = _without_images(document)
    if to_format == OutputFormat.JSON:
        document.save_as_json(filename=path, image_mode=image_mode)
    elif to_format == OutputFormat.YAML:
        document.save_as_yaml(filename=path, image_mode=image_mode)
    elif to_format == OutputFormat.HTML:
        document.save_as_html(
            filename=path, image_mode=image_mode, split_page_view=False
        )
    elif to_format == OutputFormat.HTML_SPLIT_PAGE:
        if settings.show_layout:
            serializer = HTMLDocSerializer(
                doc=document,
                params=HTMLParams(
                    image_mode=image_mode, output_style=HTMLOutputStyle.SPLIT_PAGE
                ),
            )
            visualizer = LayoutVisualizer()
            visualizer.params.show_label = False
            path.write_text(
                serializer.serialize(visualizer=visualizer).text, encoding="utf-8"
            )
        else:
            document.save_as_html(
                filename=path, image_mode=image_mode, split_page_view=True
            )
    elif to_format == OutputFormat.TEXT:
        path.write_text(document.export_to_text(), encoding="utf-8")
    elif to_format == OutputFormat.MARKDOWN:
        document.save_as_markdown(filename=path, image_mode=image_mode)
    elif to_format == OutputFormat.DOCTAGS:
        document.save_as_doctags(filename=path)
    elif to_format == OutputFormat.VTT:
        document.save_as_vtt(filename=path)
    elif to_format == OutputFormat.DOCLANG:
        path.write_text(document.export_to_doclang(), encoding="utf-8")
    elif to_format == OutputFormat.DCLX:
        document.save_as_doclang_archive(filename=path)
    elif to_format == OutputFormat.LATEX:
        path.write_text(
            LaTeXDocSerializer(doc=document).serialize().text, encoding="utf-8"
        )
    elif to_format == OutputFormat.CHUNKS:
        _write_chunks(document, path, stem, settings)
    else:
        raise ValueError(f"Unsupported output format {to_format}")
    return path


def _without_images(document: DoclingDocument) -> DoclingDocument:
    copy = document.model_copy(deep=True)
    for page in copy.pages.values():
        page.image = None
    for picture in copy.pictures:
        picture.image = None
    return copy


def _write_chunks(
    document: DoclingDocument, path: Path, stem: str, settings: ExportSettings
) -> None:
    if settings.chunker_type == ChunkerType.HIERARCHICAL:
        chunker: HierarchicalChunker = HierarchicalChunker()
        count_tokens = None
    else:
        from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
        from docling_core.transforms.chunker.tokenizer.huggingface import (
            HuggingFaceTokenizer,
        )

        tokenizer = HuggingFaceTokenizer.from_pretrained(
            model_name=settings.chunk_tokenizer, max_tokens=settings.chunk_max_tokens
        )
        chunker = HybridChunker(tokenizer=tokenizer)
        count_tokens = tokenizer.count_tokens

    with path.open("w", encoding="utf-8") as stream:
        for index, chunk in enumerate(chunker.chunk(dl_doc=document)):
            assert isinstance(chunk, DocChunk)
            page_numbers = sorted(
                {prov.page_no for item in chunk.meta.doc_items for prov in item.prov}
            )
            metadata = {}
            if chunk.meta.origin:
                metadata["origin"] = chunk.meta.origin.model_dump(mode="json")
            text = chunker.contextualize(chunk)
            record = ChunkedDocumentResultItem(
                filename=stem,
                chunk_index=index,
                text=text,
                raw_text=chunk.text,
                num_tokens=count_tokens(text) if count_tokens else None,
                headings=chunk.meta.headings,
                captions=chunk.meta.captions,
                doc_items=[item.self_ref for item in chunk.meta.doc_items],
                page_numbers=page_numbers,
                metadata=metadata,
            )
            stream.write(
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n"
            )
