# Extracta

Extracta is a document-processing service built on Docling. Docling is the
conversion engine; Extracta adds upload validation, routing, Sarvam OCR,
content validation and a standardized output envelope. A web UI shows every
Docling option.

```text
Upload ─► Validate size and type ─► Docling DocumentConverter ─► DoclingDocument
                                     │ PDF / image → standard pipeline
                                     │   (text layer + OCR only where needed,
                                     │    Sarvam Vision or another OCR engine)
                                     │ Office, HTML, Markdown, CSV, XLSX, ... →
                                     │   simple pipeline
                                     │ audio / video → ASR / video pipeline
                                     ▼
                      Exports (JSON, HTML, Markdown, ...) ─► Validation ─► Envelope
```

## Parts

| Path | Content |
|---|---|
| `server/extracta/app.py` | FastAPI app: `/api/catalog`, `/api/convert`, job file downloads, the built UI |
| `server/extracta/service.py` | The flow: validate, convert, export, check, envelope |
| `server/extracta/catalog.py` | Pipelines and backends for each input format |
| `server/extracta/options_schema.py` | Describes Docling's option models for the UI, and rebuilds them from form input |
| `server/extracta/sarvam/` | Sarvam Vision as a Docling OCR engine |
| `server/extracta/validation.py` | Content and structure checks |
| `web/` | React UI (Vite) |
| `tests/` | Tests, with a fake Sarvam server |

## Run it

From the repository root:

```bash
uv sync --frozen --group dev --group extracta --extra standard
```

Build the UI once (Node.js 18 or later):

```bash
npm --prefix apps/extracta/web install
```

```bash
npm --prefix apps/extracta/web run build
```

Start the server. It serves the API and the built UI on http://127.0.0.1:8000:

```bash
uv run --no-sync uvicorn extracta.app:app --app-dir apps/extracta/server --port 8000
```

The first start takes one to two minutes, because Docling loads its model
libraries. The first conversion of a PDF also downloads the layout and table
models.

For UI development, run `npm --prefix apps/extracta/web run dev` and open
http://localhost:5173. Vite sends `/api` requests to port 8000.

## Sarvam OCR

Copy `apps/extracta/.env.example` to `apps/extracta/.env` (this file is not
committed) and set the key there, or set it in the environment:

```text
SARVAM_API_KEY=your-key
```

With a key, Sarvam is the default OCR engine for PDF and image files. Without
a key, Docling's automatic engine choice applies, and you can still select
Sarvam in the UI and enter a key there.

Docling still decides where OCR is necessary. With the default OCR mode, only
regions without a usable PDF text layer are sent to OCR. Set **OCR options →
Mode** to `full_page` to OCR whole pages. Pages are sent as images, up to 10
pages per Sarvam job (the Sarvam limit).

After conversion, running page headers and footers that the layout model
missed (the same words at the top or bottom of three or more pages) are moved
out of the document body. Turn it off with **Input and limits → Remove
repeated headers**.

In label/value blocks ("Type of Calamity : Drought"), each label is joined
with the value on its row. Docling's reading order otherwise lists all labels
first and all values after them when the OCR returns the two columns as
separate boxes. Turn it off with **Input and limits → Join key values**.

Limits that you must know:

- Sarvam returns one box per block (paragraph, table, heading), not per word
  or line. Extracta splits a block into equal-height lines, which is correct
  for running text. Table rows would then lose their columns, so by default
  (`table_text = local`) the text inside table regions is read with RapidOCR,
  which gives word boxes. Set `table_text = sarvam` for tables in Indic
  scripts; their columns can then merge.
- Tilted scans: Docling does not straighten pages. On a page scanned at a
  slight angle, one table column can move by one row.
- Each Sarvam job carries up to 10 pages (Extracta raises Docling's OCR batch
  size to 10 when Sarvam is used).
- Sarvam is a paid remote API. Page images leave your machine.

## Table extraction

Turn on **Extract tables** (main screen, or `"tables": {"enabled": true}` in
the API options) to get every table of the document as a package. It works the
same for normal PDFs (text layer), scanned PDFs and images (OCR), and files
with real tables (Word, Excel, HTML, Markdown, ...).

The package is in the job folder under `outputs/tables/` and in the
"Download all" ZIP:

| File | Content |
|---|---|
| `tables.json` | Manifest: the metadata and the cells of every table |
| `tables.xlsx` | One sheet per table, plus an "Index" sheet with the metadata |
| `<table_id>.csv` | One CSV per table (UTF-8 with BOM, opens in Excel) |
| `<table_id>.png` | The table cut from its page, to check the result |

The envelope lists the tables under `tables`, without the cells. Metadata of
each table:

| Field | Meaning |
|---|---|
| `table_id` | Stable ID: the first 12 characters of the file's SHA-256 hash, the page and the table's number on that page (`a07f5c34601b-p005-t01`). The same file always gives the same IDs. |
| `source` | File name, SHA-256 hash, detected format, page count |
| `page`, `regions` | Page(s) and box of each part: PDF points with the origin at the top-left corner, and as fractions of the page. For spreadsheets the page is the sheet and the box is in cells (`units: "cell"`). |
| `title` | The short text right above the table (not a body sentence) |
| `caption`, `footnotes` | As Docling found them |
| `section` | The nearest heading before the table |
| `units` | A units note found in the title, caption, header or just above ("(Rs in lakh)", "(IN MM)") |
| `num_rows`, `num_cols`, `header_rows`, `empty_cells_share` | Shape of the table |
| `extraction` | `text_layer`, `ocr`, `mixed` or `structured`, plus the OCR engine and the Sarvam `table_text` setting |
| `quality` | `ok`, or `warn` with reasons (one column, mostly empty, no cells) |
| `continues_from`, `continues_to` | Links between the parts of a table that runs over a page break. A part with its own title or a caption above it starts a new table. Set `join_continued` to join the parts into one table. |

## Options

The main screen has three steps: add documents, choose settings, see results.
The settings there are the common ones: output formats, OCR engine (Sarvam,
built-in, off), document language, "scanned document" (full-page OCR), table
detection and images. They apply to PDF and image files.

**Advanced settings** (top right) opens every other option. It has no
hard-coded Docling options: `/api/catalog` describes the option models of every
pipeline and backend, so new Docling options appear automatically. The simple
settings and the advanced settings edit the same state.

- **Limits, outputs and checks**: allowed formats, size and page limits, page
  range, output formats, image mode, chunking, validation rules, envelope content.
- **Per file type**: for each of the 36 input formats, the pipeline
  (standard, VLM, native, legacy, ASR, video, simple), all its options
  (OCR engine and its settings, layout model, table model, picture
  description, enrichment, accelerator, ...), the backend and all its options.
  Model presets (VLM, picture description, ASR, ...) appear as a "Preset"
  choice.
- **Settings as JSON**: your changes as JSON, to save or reuse in API calls.

Options that point at server files or remote services (`artifacts_path`,
`enable_local_fetch`, `enable_remote_services`, ...) apply on the server.
Do not expose this service to untrusted users without access control.

## API

```bash
curl -F "file=@document.pdf" -F 'options={"export":{"to_formats":["json","md"]}}' http://127.0.0.1:8000/api/convert
```

`options` is sparse: send only the changes to the defaults. The response is
the envelope:

```json
{
  "schema_version": "1.0",
  "job_id": "…",
  "status": "success | partial_success | failure | rejected",
  "source": { "filename": "…", "size_bytes": 0, "sha256": "…", "detected_format": "pdf" },
  "processing": { "pipeline": "standard", "backend": "docling_parse", "ocr_engine": "sarvam", "duration_seconds": 0 },
  "stats": { "pages": 0, "characters": 0, "headings": 0, "tables": 0, "pictures": 0, "empty_pages": [] },
  "validation": { "passed": true, "checks": [{ "id": "has_content", "status": "pass", "message": "…" }] },
  "outputs": [{ "format": "json", "url": "/api/jobs/…/files/…", "content": "…" }],
  "bundle_url": "/api/jobs/…/files/bundle.zip",
  "errors": []
}
```

Job files stay in `apps/extracta/.data/jobs` (the newest 200 jobs).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SARVAM_API_KEY` | – | Sarvam key; makes Sarvam the default OCR engine |
| `EXTRACTA_MAX_UPLOAD_MB` | 200 | Upload size limit |
| `EXTRACTA_DATA_DIR` | `apps/extracta/.data` | Job storage |
| `EXTRACTA_KEEP_JOBS` | 200 | Jobs to keep |
| `EXTRACTA_CONVERTER_CACHE_SIZE` | 4 | Option sets that keep their loaded models |
| `EXTRACTA_CORS_ORIGINS` | localhost:5173 | Allowed browser origins (JSON list) |

## Tests

```bash
uv run --no-sync pytest apps/extracta/tests --rootdir apps/extracta
```

The Sarvam tests use a local fake server; they do not call the real API.
