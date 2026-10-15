# Catalyst

Catalyst is a document-processing service built on Docling. Docling is the
conversion engine; Catalyst adds upload validation, routing, Sarvam OCR,
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
| `server/catalyst/app.py` | FastAPI app: `/api/catalog`, `/api/convert`, job file downloads, the built UI |
| `server/catalyst/service.py` | The flow: validate, convert, export, check, envelope |
| `server/catalyst/catalog.py` | Pipelines and backends for each input format |
| `server/catalyst/options_schema.py` | Describes Docling's option models for the UI, and rebuilds them from form input |
| `server/catalyst/sarvam/` | Sarvam Vision as a Docling OCR engine |
| `server/catalyst/validation.py` | Content and structure checks |
| `web/` | React UI (Vite) |
| `tests/` | Tests, with a fake Sarvam server |

## Run it

From the repository root:

```bash
uv sync --frozen --group dev --group catalyst --extra standard
```

Build the UI once (Node.js 18 or later):

```bash
npm --prefix apps/catalyst/web install
```

```bash
npm --prefix apps/catalyst/web run build
```

Start the server. It serves the API and the built UI on http://127.0.0.1:8000:

```bash
uv run --no-sync uvicorn catalyst.app:app --app-dir apps/catalyst/server --port 8000
```

The first start takes one to two minutes, because Docling loads its model
libraries. The first conversion of a PDF also downloads the layout and table
models.

For UI development, run `npm --prefix apps/catalyst/web run dev` and open
http://localhost:5173. Vite sends `/api` requests to port 8000.

## Sarvam OCR

Copy `apps/catalyst/.env.example` to `apps/catalyst/.env` (this file is not
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

Before layout, OCR and table analysis, image-only pages (scans without a text
layer, and image files) are turned upright and straightened. Pages with a
landscape table printed sideways turn by 90 or 270 degrees, upside-down pages
by 180 degrees, and pages scanned at an angle of up to 5 degrees rotate back.
The stored page (size and images) is the corrected page, so all boxes match
it. Turn it off with **Input and limits → Straighten scanned pages**.

Limits that you must know:

- Sarvam returns one box per block (paragraph, table, heading), not per word
  or line. Catalyst splits a block into equal-height lines, which is correct
  for running text. For a table, Sarvam also returns an HTML table with its
  merged cells. By default (`table_structure = sarvam`) that table replaces
  the table that Docling's table model builds, so the rows, columns and text
  come from Sarvam. A table that Sarvam did not return as HTML is built by
  Docling's table model: by default (`table_text = local`) its text is read
  with RapidOCR, which gives word boxes. Set `table_text = sarvam` to use
  Sarvam's text instead; the columns can then merge.
- A Sarvam table replaces a Docling table only when the two boxes overlap on
  the same page. When Docling's layout model does not find a table, Sarvam's
  table text stays as plain text.
- Straightening applies only to image-only pages. A scan with a text layer
  (a "searchable" PDF) is used as it is, because its text boxes would no
  longer fit a turned page. The check costs about 2 to 4 seconds per
  image-only page on a CPU. Angles of less than 0.2 degrees and more than
  5 degrees are not corrected, and a page with less than five text lines is
  left as it is.
- Which way is up is decided by reading lines with RapidOCR's Latin
  recognizer. For pages in other scripts the decision can fail; an upright
  page then stays as it is, but a sideways page can end upside down.
- When straightening is off (or the page has a text layer), a table printed
  sideways keeps Sarvam's text: RapidOCR cannot read sideways text, and
  Docling cannot find its columns.
- Each Sarvam job carries up to 10 pages (Catalyst raises Docling's OCR batch
  size to 10 when Sarvam is used).
- Sarvam is a paid remote API. Page images leave your machine.

### Sarvam cost

Sarvam bills Document Digitization per page, not per token. For each
conversion, Catalyst counts the pages that Sarvam processed (`usage.pages_processed`
of each Sarvam job, or the pages sent when Sarvam does not report usage) and
stores the cost in the envelope under `processing.sarvam`:

```json
{ "jobs": 1, "pages": 3, "price_per_page": 0.5, "currency": "INR", "cost": 1.5 }
```

The **History** page shows this cost for each job and the total for the
listed jobs. The price is the server price when the job ran
(`CATALYST_SARVAM_PRICE_PER_PAGE`, ₹0.5 per page from the Sarvam price list
of 2026-10). It is an estimate: check your Sarvam dashboard for the billed
amount. A Sarvam job that fails is not counted.

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
| `extraction` | `text_layer`, `ocr`, `mixed` or `structured`, plus the OCR engine, the Sarvam `table_text` setting, and `structure`: `sarvam` when the rows and columns come from Sarvam's HTML table, else `docling` |
| `quality` | `ok`, or `warn` with reasons (one column, mostly empty, no cells) |
| `continues_from`, `continues_to` | Links between the parts of a table that runs over a page break. A part with its own title or a caption above it starts a new table. Set `join_continued` to join the parts into one table. |

## HTML per page and images as files

- **HTML per page** (`"pages": {"enabled": true}`): `outputs/pages/page-001.html`
  and so on, with links to the previous and next page, and `index.html` with
  the first heading of each page. Pictures are linked image files, not
  embedded.
- **Extract images** (`"pictures": {"enabled": true}`): every picture as
  `outputs/pictures/<id>.png` (ID: file hash, page, number on the page), with
  `pictures.json` listing page, position, caption, section and pixel size.
  `min_size_px` skips small decorations.

## PDFs with garbled text

Some PDFs, often Hindi documents made with legacy fonts such as Kruti Dev,
have a text layer of Latin letters that only look like Hindi on screen
("fgekpy çns'k" for "हिमाचल प्रदेश"). With Sarvam OCR and an Indic language
(`hi-IN` for Hindi), Catalyst finds such pages itself
(`"settings": {"ignore_garbled_text_layer": true}`, the default): a page whose
text layer has almost no letters in the script of the language hides that
layer and is read with OCR. Other pages keep their text layer. A page in
another language (for example English in a Hindi document) is also read with
OCR. Each such page is sent to Sarvam and billed.

For other OCR engines, turn on **Scanned document** (or
`"settings": {"ignore_text_layer": true}` with OCR mode `full_page`): every page
is then read with OCR. Without it, tables keep the garbled letters, because
Docling's table model takes its words from the PDF text layer even in
full-page OCR mode.

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
  "processing": { "pipeline": "standard", "backend": "docling_parse", "ocr_engine": "sarvam", "sarvam": { "pages": 0, "cost": 0, "…": "…" }, "duration_seconds": 0 },
  "stats": { "pages": 0, "characters": 0, "headings": 0, "tables": 0, "pictures": 0, "empty_pages": [] },
  "validation": { "passed": true, "checks": [{ "id": "has_content", "status": "pass", "message": "…" }] },
  "outputs": [{ "format": "json", "url": "/api/jobs/…/files/…", "content": "…" }],
  "bundle_url": "/api/jobs/…/files/bundle.zip",
  "errors": []
}
```

Job files stay in `apps/catalyst/.data/jobs` (the newest 200 jobs).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SARVAM_API_KEY` | – | Sarvam key; makes Sarvam the default OCR engine |
| `CATALYST_MAX_UPLOAD_MB` | 200 | Upload size limit |
| `CATALYST_DATA_DIR` | `apps/catalyst/.data` | Job storage |
| `CATALYST_KEEP_JOBS` | 200 | Jobs to keep |
| `CATALYST_CONVERTER_CACHE_SIZE` | 4 | Option sets that keep their loaded models |
| `CATALYST_CORS_ORIGINS` | localhost:5173 | Allowed browser origins (JSON list) |
| `CATALYST_SARVAM_PRICE_PER_PAGE` | 0.5 | Sarvam price per page, for the cost in the envelope and the history |
| `CATALYST_SARVAM_CURRENCY` | INR | Currency of that price (ISO 4217 code) |

## Tests

```bash
uv run --no-sync pytest apps/catalyst/tests --rootdir apps/catalyst
```

The Sarvam tests use a local fake server; they do not call the real API.
