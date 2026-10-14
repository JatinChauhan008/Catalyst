import { useRef, useState, type ReactNode } from "react";
import { Segmented, Toggle } from "../components/Controls";
import { HeroArt } from "../components/HeroArt";
import {
  ArrowRightIcon,
  BracesIcon,
  CheckIcon,
  CubeIcon,
  FileIcon,
  FormatBadge,
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

  return (
    <div className="convert-layout">
      <div className="convert-main">
        <section className="hero">
          <div className="hero-text">
            <p className="eyebrow">Turn documents into clean, structured text</p>
            <h1>
              Upload, extract, and convert your <em>documents.</em>
            </h1>
            <p className="hero-sub">
              Convert PDFs, images, Word files and more to clean, structured text or HTML.
              {catalog.server.sarvam_configured ? " Powered by Sarvam OCR for Indian documents." : ""}
            </p>
          </div>
          <HeroArt />
        </section>

        <UploadCard maxMb={catalog.server.max_upload_mb} {...props} />

        <SettingsCard catalog={catalog} request={props.request} onChange={props.onRequestChange} onReset={props.onReset} />

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

      <aside className="convert-side">
        <GetStarted
          hasFiles={queue.length > 0}
          pending={pending.length}
          running={running}
          done={finished.some((item) => item.state === "done")}
          onRun={props.onRun}
        />
      </aside>
    </div>
  );
}

const FORMATS: [Parameters<typeof FormatBadge>[0]["kind"], string][] = [
  ["pdf", "PDF"],
  ["word", "Word"],
  ["excel", "Excel"],
  ["ppt", "PowerPoint"],
  ["image", "Images"],
  ["html", "HTML"],
  ["text", "Text"],
];

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

      <div className="formats-row">
        <span className="formats-label">Supported formats</span>
        {FORMATS.map(([kind, label]) => (
          <span key={kind} className="format-chip">
            <FormatBadge kind={kind} />
            {label}
          </span>
        ))}
      </div>
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

const OUTPUT_CARDS: [string, string, string, ReactNode][] = [
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
  const toggleOutput = (id: string) =>
    set({ outputs: quick.outputs.includes(id) ? quick.outputs.filter((item) => item !== id) : [...quick.outputs, id] });

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
              const on = quick.outputs.includes(id);
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
          {quick.outputs.length === 0 && <span className="text-danger small">Select at least one format.</span>}
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
                <span className="text-warn small">Sarvam has no API key on the server. Add it to apps/extracta/.env.</span>
              ))}
            {quick.engine === "custom" && <span className="muted small">Set in Settings.</span>}
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

function GetStarted({
  hasFiles,
  pending,
  running,
  done,
  onRun,
}: {
  hasFiles: boolean;
  pending: number;
  running: boolean;
  done: boolean;
  onRun: () => void;
}) {
  const current = !hasFiles ? 1 : running || done ? 3 : 2;
  const steps: [string, string][] = [
    ["Upload", "Add your document files"],
    ["Configure", "Choose output format and settings"],
    ["Convert", "Get clean, structured results"],
  ];
  return (
    <section className="card get-started">
      <header className="get-started-head">
        <span className="card-head-icon soft">
          <FileIcon size={24} />
        </span>
        <div>
          <h2>Get started</h2>
          <p className="muted small">Upload a document and configure settings to extract clean, structured output.</p>
        </div>
      </header>
      <ol className="steps">
        {steps.map(([title, help], index) => {
          const number = index + 1;
          const state = number < current || (number === 3 && done && !running) ? "done" : number === current ? "active" : "";
          return (
            <li key={title} className={`step ${state}`}>
              <span className="step-number">{state === "done" ? <CheckIcon size={14} /> : number}</span>
              <span className="step-text">
                <strong>{title}</strong>
                <span className="muted small">{help}</span>
              </span>
            </li>
          );
        })}
      </ol>
      <button type="button" className="btn primary convert-btn" disabled={running || pending === 0} onClick={onRun}>
        <SparkleIcon size={20} />
        {running ? "Converting…" : pending > 1 ? `Convert ${pending} documents` : "Convert document"}
        {!running && <ArrowRightIcon />}
      </button>
      <p className="muted small center-text">
        {running
          ? "Large PDFs can take a few minutes."
          : pending === 0
            ? hasFiles
              ? "All files are converted. Add more to continue."
              : "Add a document to start."
            : `${pending} file${pending === 1 ? "" : "s"} ready.`}
      </p>
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
