import { useRef, useState, type ReactNode } from "react";
import { Segmented, Toggle } from "../components/Controls";
import {
  ArrowRightIcon,
  BracesIcon,
  CheckIcon,
  CubeIcon,
  FileIcon,
  GlobeIcon,
  ImageIcon,
  MarkdownIcon,
  PagesIcon,
  ResetIcon,
  ScanTextIcon,
  SlidersIcon,
  SparkleIcon,
  TableIcon,
  TextLinesIcon,
  UploadCloudIcon,
  UploadIcon,
  CodeIcon,
} from "../components/Icons";
import { ResultView, formatBytes, statusOf } from "../components/ResultView";
import { OUTPUT_LABELS, SARVAM_LANGUAGES, readQuick, writeQuick, type Engine } from "../quick";
import type { Catalog, ConvertRequest, Envelope } from "../types";

export interface QueueItem {
  id: string;
  file: File;
  state: "queued" | "running" | "done" | "error";
  envelope?: Envelope;
  error?: string;
}

interface Props {
  catalog: Catalog;
  request: ConvertRequest;
  onRequestChange: (request: ConvertRequest) => void;
  onReset: () => void;
  queue: QueueItem[];
  onAddFiles: (files: FileList | null) => void;
  onRemove: (id: string) => void;
  onRun: () => void;
  running: boolean;
  openResult: string | null;
  onOpenResult: (id: string | null) => void;
}

export function ConvertPage(props: Props) {
  const { catalog, queue, running } = props;
  const pending = queue.filter((item) => item.state === "queued" || item.state === "error");
  const finished = queue.filter((item) => item.state !== "queued");

  const quick = readQuick(props.request, catalog);
  const nothingSelected = quick.outputs.length === 0 && !quick.dost;

  return (
    <div className="convert-main">
      <UploadCard maxMb={catalog.server.max_upload_mb} {...props} />

      <SettingsCard catalog={catalog} request={props.request} onChange={props.onRequestChange} onReset={props.onReset} />

      <div className="convert-bar">
        <span className="muted small">
          {running
            ? "Converting… Large PDFs can take a few minutes."
            : pending.length === 0
              ? queue.length > 0
                ? "All files are converted. Add more to continue."
                : "Add a document to start."
              : `${pending.length} file${pending.length === 1 ? "" : "s"} ready.`}
        </span>
        <button
          type="button"
          className="btn primary convert-btn"
          disabled={running || pending.length === 0 || nothingSelected}
          onClick={props.onRun}
        >
          <SparkleIcon size={20} />
          {running ? "Converting…" : pending.length > 1 ? `Convert ${pending.length} documents` : "Convert document"}
          {!running && <ArrowRightIcon />}
        </button>
      </div>

      {finished.length > 0 && (
        <section className="results">
          <h2 className="section-title">Results</h2>
          {finished.map((item) => (
            <ResultCard
              key={item.id}
              item={item}
              open={props.openResult === item.id}
              onToggle={() => props.onOpenResult(props.openResult === item.id ? null : item.id)}
            />
          ))}
        </section>
      )}
    </div>
  );
}

function UploadCard({ maxMb, queue, onAddFiles, onRemove }: Props & { maxMb: number }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <section className="card upload-card">
      <div
        className={`dropzone ${dragging ? "dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          onAddFiles(event.dataTransfer.files);
        }}
      >
        <span className="dropzone-icon">
          <UploadCloudIcon size={44} />
        </span>
        <strong className="dropzone-title">Drag &amp; drop files here</strong>
        <span className="muted small">or</span>
        <button type="button" className="btn primary" onClick={() => input.current?.click()}>
          <UploadIcon size={18} /> Browse files
        </button>
        <span className="muted small">
          PDF, Word, Excel, PowerPoint, images, HTML, and more — up to {maxMb} MB each
        </span>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            onAddFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {queue.length > 0 && (
        <ul className="files">
          {queue.map((item) => (
            <li key={item.id}>
              <span className="file-icon">
                <FileIcon size={18} />
              </span>
              <span className="file-name">{item.file.name}</span>
              <span className="muted small">{formatBytes(item.file.size)}</span>
              <FileState item={item} />
              {item.state !== "running" && (
                <button type="button" className="icon-btn" aria-label={`Remove ${item.file.name}`} onClick={() => onRemove(item.id)}>
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FileState({ item }: { item: QueueItem }) {
  if (item.state === "queued") return <span className="tag">Ready</span>;
  if (item.state === "running") return <span className="spinner" aria-label="Converting" />;
  if (item.state === "error") return <span className="tag tag-danger">Failed</span>;
  const status = statusOf(item.envelope!);
  return <span className={`tag tag-${status.tone}`}>{status.title}</span>;
}

// "dost" is not a Docling export format: it turns on the DOST outputs (all
// tables as Markdown, sentences with English as CSV, images as a ZIP).
const DOST = "dost";

const OUTPUT_CARDS: [string, string, string, ReactNode][] = [
  [DOST, "DOST", "Tables, sentences with English, images", <SparkleIcon key="dost" size={22} />],
  ["md", "Markdown", "Clean and readable", <MarkdownIcon key="md" />],
  ["html", "HTML", "Preserve structure", <CodeIcon key="html" size={22} />],
  ["json", "JSON", "Structured data", <BracesIcon key="json" />],
  ["text", "Plain text", "Raw text only", <TextLinesIcon key="text" />],
];

function Setting({ icon, title, help, children }: { icon: ReactNode; title: string; help: string; children: ReactNode }) {
  return (
    <div className="setting-tile">
      <span className="setting-icon">{icon}</span>
      <div className="setting-body">
        <strong>{title}</strong>
        <span className="muted small">{help}</span>
        <div className="setting-control">{children}</div>
      </div>
    </div>
  );
}

function SettingsCard({
  catalog,
  request,
  onChange,
  onReset,
}: {
  catalog: Catalog;
  request: ConvertRequest;
  onChange: (request: ConvertRequest) => void;
  onReset: () => void;
}) {
  const quick = readQuick(request, catalog);
  const [moreFormats, setMoreFormats] = useState(false);
  const set = (change: Parameters<typeof writeQuick>[2]) => onChange(writeQuick(request, catalog, change));
  const isOn = (id: string) => (id === DOST ? quick.dost : quick.outputs.includes(id));
  const toggleOutput = (id: string) =>
    id === DOST
      ? set({ dost: !quick.dost })
      : set({ outputs: quick.outputs.includes(id) ? quick.outputs.filter((item) => item !== id) : [...quick.outputs, id] });

  const engines: [Engine, string][] = [
    ["sarvam", "Sarvam"],
    ["auto", "Built-in"],
    ["off", "Off"],
  ];
  if (quick.engine === "custom") engines.push(["custom", "Custom"]);
  const extraOutputs = Object.keys(OUTPUT_LABELS).filter((id) => !OUTPUT_CARDS.some(([card]) => card === id));

  return (
    <section className="card settings-card">
      <header className="card-head">
        <span className="card-head-icon">
          <SlidersIcon size={24} />
        </span>
        <div>
          <h2>Conversion settings</h2>
          <p className="muted small">Choose how your document should be processed.</p>
        </div>
        <button type="button" className="btn ghost small-btn" onClick={onReset}>
          <ResetIcon /> Reset to defaults
        </button>
      </header>

      <div className="settings-top">
        <div className="output-block">
          <div className="block-label">
            <CubeIcon /> <strong>Output format</strong>
          </div>
          <div className="output-cards">
            {OUTPUT_CARDS.map(([id, title, help, icon]) => {
              const on = isOn(id);
              return (
                <button
                  key={id}
                  type="button"
                  className={`output-card ${on ? "on" : ""}`}
                  aria-pressed={on}
                  onClick={() => toggleOutput(id)}
                >
                  <span className="output-icon">{icon}</span>
                  <span className="output-text">
                    <strong>{title}</strong>
                    <span className="muted small">{help}</span>
                  </span>
                  {on && (
                    <span className="check-badge">
                      <CheckIcon size={12} />
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <button type="button" className="link" onClick={() => setMoreFormats(!moreFormats)}>
            {moreFormats ? "Fewer formats" : "More formats"}
          </button>
          {moreFormats && (
            <div className="chips">
              {extraOutputs.map((id) => {
                const on = quick.outputs.includes(id);
                return (
                  <button key={id} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on} onClick={() => toggleOutput(id)}>
                    {on && "✓ "}
                    {OUTPUT_LABELS[id]}
                  </button>
                );
              })}
            </div>
          )}
          {quick.outputs.length === 0 && !quick.dost && <span className="text-danger small">Select at least one format.</span>}
        </div>

        <div className="ocr-block">
          <Setting icon={<ScanTextIcon />} title="Text recognition (OCR)" help="Reads text from scans and images.">
            <Segmented label="OCR engine" value={quick.engine} options={engines} onChange={(engine) => engine !== "custom" && set({ engine })} />
            {quick.engine === "sarvam" &&
              (catalog.server.sarvam_configured ? (
                <span className="muted small">
                  Uses <span className="accent-underline">Sarvam OCR</span> for high accuracy on Indian documents.
                </span>
              ) : (
                <span className="text-warn small">Sarvam has no API key on the server. Add it to apps/catalyst/.env.</span>
              ))}
            {quick.engine === "custom" && <span className="muted small">A custom OCR setup is in use.</span>}
          </Setting>
        </div>
      </div>

      <div className="settings-grid">
        <Setting icon={<GlobeIcon />} title="Document language" help="The main language of the text.">
          <select
            value={quick.language}
            disabled={quick.engine !== "sarvam"}
            onChange={(event) => set({ language: event.target.value })}
          >
            {SARVAM_LANGUAGES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </Setting>
        <Setting
          icon={<ImageIcon />}
          title="Scanned document handling"
          help="Read every page as an image (useful if text is missing or garbled). May be slower."
        >
          <Toggle checked={quick.scanned} onChange={(scanned) => set({ scanned })} />
        </Setting>
        <Setting icon={<TableIcon />} title="Detect tables" help="Rebuild table rows and columns in PDFs and images.">
          <Toggle checked={quick.tables} onChange={(tables) => set({ tables })} />
        </Setting>
        <Setting icon={<ImageIcon />} title="Images in the output" help="Include pictures or add a marker where they were.">
          <Segmented
            label="Images in the output"
            value={quick.images}
            options={[
              ["embedded", "Include"],
              ["placeholder", "Marker only"],
              ["referenced", "Separate files"],
            ]}
            onChange={(images) => set({ images })}
          />
        </Setting>
      </div>

      <div className="extras">
        <div className="block-label">
          <SparkleIcon size={18} /> <strong>Extra outputs</strong>
        </div>
        <div className="settings-grid three">
          <Setting icon={<TableIcon />} title="Extract tables" help="Every table as CSV and Excel, with its page, position, title and section.">
            <Toggle checked={quick.extractTables} onChange={(extractTables) => set({ extractTables })} />
          </Setting>
          <Setting icon={<ImageIcon />} title="Extract images" help="Every picture as its own PNG file, with its page and caption.">
            <Toggle checked={quick.extractImages} onChange={(extractImages) => set({ extractImages })} />
          </Setting>
          <Setting icon={<PagesIcon />} title="HTML per page" help="One HTML file per page with links between pages.">
            <Toggle checked={quick.htmlPerPage} onChange={(htmlPerPage) => set({ htmlPerPage })} />
          </Setting>
        </div>
      </div>

      {quick.pipelineNote && <div className="notice">{quick.pipelineNote}</div>}
    </section>
  );
}

function ResultCard({ item, open, onToggle }: { item: QueueItem; open: boolean; onToggle: () => void }) {
  const status = item.envelope
    ? statusOf(item.envelope)
    : item.state === "error"
      ? { title: "Request failed", tone: "danger" }
      : { title: "Converting…", tone: "busy" };
  return (
    <article className={`result tone-${status.tone}`}>
      <button type="button" className="result-head" aria-expanded={open} onClick={onToggle}>
        <span className={`status-dot dot-${status.tone}`} />
        <span className="result-name">{item.file.name}</span>
        <span className={`status-text text-${status.tone}`}>{status.title}</span>
        <span className="chevron">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="result-content">
          {item.state === "running" && (
            <p className="muted">
              <span className="spinner" /> Reading the document…
            </p>
          )}
          {item.error && <div className="notice notice-danger">{item.error}</div>}
          {item.envelope && <ResultView envelope={item.envelope} />}
        </div>
      )}
    </article>
  );
}
