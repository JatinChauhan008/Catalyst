# Catalyst

Catalyst is a document-processing service with a web UI. You upload a
document, and Catalyst converts it to structured output: JSON, HTML, Markdown,
tables as Excel and CSV, and images as files. Every result comes in a
standard envelope with validation checks.

Catalyst uses [Docling](https://github.com/docling-project/docling) as its
conversion engine. This repository contains the Catalyst app and the Docling
source that it runs on.

## Features

- Converts PDF, scanned PDF, images, Word, Excel, PowerPoint, HTML, Markdown,
  CSV, audio, video and more (36 input formats).
- Uses OCR only where a page has no usable text layer. Sarvam Vision is
  available as an OCR engine for Indic scripts.
- Turns scanned pages upright and straightens them before it reads them.
- Extracts every table as a package: a manifest, an Excel file, one CSV and
  one image per table, with stable IDs and metadata.
- Writes HTML per page and saves pictures as separate image files.
- Removes repeated page headers and footers, and joins label/value pairs.
- Reads PDFs with garbled legacy-font text (for example Kruti Dev Hindi)
  through full-page OCR.
- Shows every Docling option in the UI. New Docling options appear
  automatically.
- Keeps a history of recent jobs, with a ZIP download of all outputs.

## Quick start

From the repository root, install the dependencies:

```bash
uv sync --frozen --group dev --group catalyst --extra standard
```

Build the UI (Node.js 18 or later):

```bash
npm --prefix apps/catalyst/web install
```

```bash
npm --prefix apps/catalyst/web run build
```

Start the server:

```bash
uv run --no-sync uvicorn catalyst.app:app --app-dir apps/catalyst/server --port 8000
```

Open http://127.0.0.1:8000. The first start takes one to two minutes, because
Docling loads its model libraries.

To use Sarvam OCR, copy `apps/catalyst/.env.example` to `apps/catalyst/.env`
and set `SARVAM_API_KEY`.

## API

```bash
curl -F "file=@document.pdf" -F 'options={"export":{"to_formats":["json","md"]}}' http://127.0.0.1:8000/api/convert
```

The response is a JSON envelope with the status, source details, statistics,
validation results and links to the output files.

## Documentation

The [Catalyst README](apps/catalyst/README.md) gives the full details: the
processing flow, all options, table extraction, Sarvam OCR and its limits, the
API envelope and the configuration variables.

## Repository layout

| Path | Content |
|---|---|
| `apps/catalyst/server/catalyst/` | FastAPI service: validation, conversion, exports, envelope |
| `apps/catalyst/web/` | React UI (Vite) |
| `apps/catalyst/tests/` | Catalyst tests |
| `docling/` | Docling conversion engine |
| `tests/` | Docling tests |

## Tests

```bash
uv run --no-sync pytest apps/catalyst/tests --rootdir apps/catalyst
```

## License

Catalyst is built on Docling, which is released under the MIT license. See
[LICENSE](LICENSE).
