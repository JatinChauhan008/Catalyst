import { useCallback, useEffect, useRef, useState } from "react";
import { convertFile, fetchCatalog } from "./api";
import { FieldForm, countChanges } from "./components/FieldForm";
import { FormatsPanel } from "./components/FormatsPanel";
import { ResultView, formatBytes, statusOf } from "./components/ResultView";
import { MAIN_OUTPUTS, OUTPUT_LABELS, SARVAM_LANGUAGES, readQuick, writeQuick, type Engine } from "./quick";
import type { Catalog, ConvertRequest, Envelope, FieldSpec, Overrides } from "./types";

const STORAGE_KEY = "extracta.request.v1";
const EMPTY_REQUEST: ConvertRequest = {
  settings: {},
  export: {},
  validation: {},
  envelope: {},
  tables: {},
  formats: {},
};

interface QueueItem {
  id: string;
  file: File;
  state: "queued" | "running" | "done" | "error";
  envelope?: Envelope;
  error?: string;
}

function loadRequest(): ConvertRequest {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? { ...EMPTY_REQUEST, ...JSON.parse(stored) } : EMPTY_REQUEST;
  } catch {
    return EMPTY_REQUEST;
  }
}

function saveRequest(request: ConvertRequest) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(request));
  } catch {
    // storage is optional
  }
}

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [request, setRequest] = useState<ConvertRequest>(loadRequest);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [openResult, setOpenResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [advanced, setAdvanced] = useState(false);

  useEffect(() => {
    fetchCatalog().then(setCatalog, (error) => setLoadError(String(error)));
  }, []);

  const updateRequest = useCallback((next: ConvertRequest) => {
    setRequest(next);
    saveRequest(next);
  }, []);

  if (loadError) {
    return (
      <div className="splash">
        <Logo />
        <div className="notice notice-danger">The Extracta server is not reachable. Start it, then reload this page.</div>
        <p className="muted small">{loadError}</p>
      </div>
    );
  }
  if (!catalog) {
    return (
      <div className="splash">
        <Logo />
        <p className="muted">
          <span className="spinner" /> Loading…
        </p>
      </div>
    );
  }

  const pending = queue.filter((item) => item.state === "queued" || item.state === "error");
  const advancedChanges =
    countChanges(request.settings) +
    countChanges(request.validation) +
    countChanges(request.envelope) +
    countChanges(request.tables ?? {}) +
    Object.keys(request.formats).length;

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const items = Array.from(files).map((file) => ({
      id: `${file.name}-${crypto.randomUUID()}`,
      file,
      state: "queued" as const,
    }));
    setQueue((current) => [...current, ...items]);
  };

  const run = async () => {
    setRunning(true);
    for (const item of pending) {
      setQueue((current) => current.map((q) => (q.id === item.id ? { ...q, state: "running", error: undefined } : q)));
      setOpenResult(item.id);
      try {
        const envelope = await convertFile(item.file, request);
        setQueue((current) => current.map((q) => (q.id === item.id ? { ...q, state: "done", envelope } : q)));
      } catch (error) {
        setQueue((current) => current.map((q) => (q.id === item.id ? { ...q, state: "error", error: String(error) } : q)));
      }
    }
    setRunning(false);
  };

  return (
    <div className="app">
      <header className="topbar">
        <Logo />
        <span className={`pill ${catalog.server.sarvam_configured ? "pill-on" : ""}`}>
          {catalog.server.sarvam_configured ? "Sarvam OCR ready" : "Sarvam OCR not set up"}
        </span>
        <button type="button" className="btn ghost topbar-action" onClick={() => setAdvanced(true)}>
          Advanced settings{advancedChanges > 0 && <span className="count">{advancedChanges}</span>}
        </button>
      </header>

      <main className="page">
        <section className="panel">
          <h2>1. Add documents</h2>
          <DropZone maxMb={catalog.server.max_upload_mb} onFiles={addFiles} />
          {queue.length > 0 && (
            <ul className="files">
              {queue.map((item) => (
                <li key={item.id}>
                  <span className="file-name">{item.file.name}</span>
                  <span className="muted small">{formatBytes(item.file.size)}</span>
                  <FileState item={item} />
                  {item.state !== "running" && (
                    <button
                      type="button"
                      className="icon-btn"
                      aria-label={`Remove ${item.file.name}`}
                      onClick={() => setQueue((current) => current.filter((q) => q.id !== item.id))}
                    >
                      ×
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel">
          <h2>2. Choose settings</h2>
          <QuickSettings catalog={catalog} request={request} onChange={updateRequest} />
        </section>

        <div className="run-row">
          <button type="button" className="btn primary big" disabled={running || pending.length === 0} onClick={run}>
            {running
              ? "Converting…"
              : pending.length > 0
                ? `Convert ${pending.length} document${pending.length === 1 ? "" : "s"}`
                : "Convert"}
          </button>
          {!running && pending.length === 0 && <span className="muted small">Add a document first.</span>}
          {running && <span className="muted small">Large PDFs can take a few minutes.</span>}
        </div>

        {queue.some((item) => item.state !== "queued") && (
          <section className="results">
            <h2>3. Results</h2>
            {queue
              .filter((item) => item.state !== "queued")
              .map((item) => {
                const status = item.envelope
                  ? statusOf(item.envelope)
                  : item.state === "error"
                    ? { title: "Request failed", tone: "danger" }
                    : { title: "Converting…", tone: "busy" };
                const open = openResult === item.id;
                return (
                  <article key={item.id} className={`result tone-${status.tone}`}>
                    <button
                      type="button"
                      className="result-head"
                      aria-expanded={open}
                      onClick={() => setOpenResult(open ? null : item.id)}
                    >
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
              })}
          </section>
        )}
      </main>

      {advanced && (
        <AdvancedDrawer
          catalog={catalog}
          request={request}
          onChange={updateRequest}
          onClose={() => setAdvanced(false)}
        />
      )}
    </div>
  );
}

function Logo() {
  return (
    <div className="logo">
      <span className="logo-mark">E</span>
      <span>Extracta</span>
    </div>
  );
}

function DropZone({ maxMb, onFiles }: { maxMb: number; onFiles: (files: FileList | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""}`}
      role="button"
      tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(event) => (event.key === "Enter" || event.key === " ") && input.current?.click()}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        onFiles(event.dataTransfer.files);
      }}
    >
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
        <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <strong>Drop files here, or click to choose</strong>
      <span className="muted small">PDF, Word, Excel, PowerPoint, images, HTML, and more · up to {maxMb} MB each</span>
      <input
        ref={input}
        type="file"
        multiple
        hidden
        onChange={(event) => {
          onFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </div>
  );
}

function FileState({ item }: { item: QueueItem }) {
  if (item.state === "queued") return <span className="tag">Ready</span>;
  if (item.state === "running") return <span className="spinner" aria-label="Converting" />;
  if (item.state === "error") return <span className="tag tag-danger">Failed</span>;
  const status = statusOf(item.envelope!);
  return <span className={`tag tag-${status.tone}`}>{status.title}</span>;
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented">
      {options.map(([id, label]) => (
        <button key={id} type="button" className={value === id ? "on" : ""} onClick={() => onChange(id)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span className="track" aria-hidden />
      <span>{label}</span>
    </label>
  );
}

function QuickSettings({
  catalog,
  request,
  onChange,
}: {
  catalog: Catalog;
  request: ConvertRequest;
  onChange: (request: ConvertRequest) => void;
}) {
  const quick = readQuick(request, catalog);
  const [moreFormats, setMoreFormats] = useState(false);
  const set = (change: Parameters<typeof writeQuick>[2]) => onChange(writeQuick(request, catalog, change));
  const allOutputs = Object.keys(OUTPUT_LABELS);
  const shownOutputs = moreFormats ? allOutputs : MAIN_OUTPUTS;
  const ocrOff = quick.engine === "off";

  const engines: [Engine, string][] = [
    ["sarvam", "Sarvam"],
    ["auto", "Built-in"],
    ["off", "Off"],
  ];
  if (quick.engine === "custom") engines.push(["custom", "Custom"]);

  return (
    <div className="settings">
      <div className="setting">
        <div className="setting-label">
          <strong>Output formats</strong>
          <span className="muted small">What you get back. Pick one or more.</span>
        </div>
        <div className="setting-control">
          <div className="chips">
            {shownOutputs.map((id) => {
              const on = quick.outputs.includes(id);
              return (
                <button
                  key={id}
                  type="button"
                  className={`chip ${on ? "on" : ""}`}
                  aria-pressed={on}
                  onClick={() =>
                    set({ outputs: on ? quick.outputs.filter((item) => item !== id) : [...quick.outputs, id] })
                  }
                >
                  {on && "✓ "}
                  {OUTPUT_LABELS[id]}
                </button>
              );
            })}
            <button type="button" className="link" onClick={() => setMoreFormats(!moreFormats)}>
              {moreFormats ? "Fewer formats" : "More formats"}
            </button>
          </div>
          {quick.outputs.length === 0 && <span className="text-danger small">Select at least one format.</span>}
        </div>
      </div>

      <div className="setting">
        <div className="setting-label">
          <strong>Text recognition (OCR)</strong>
          <span className="muted small">Reads text from scans and photos. Pages with real text are not affected.</span>
        </div>
        <div className="setting-control">
          <Segmented value={quick.engine} options={engines} onChange={(engine) => engine !== "custom" && set({ engine })} />
          {quick.engine === "sarvam" && !catalog.server.sarvam_configured && (
            <span className="text-warn small">Sarvam has no API key on the server. Add it to apps/extracta/.env.</span>
          )}
          {quick.engine === "custom" && <span className="muted small">Set in Advanced settings.</span>}
        </div>
      </div>

      {quick.engine === "sarvam" && (
        <div className="setting">
          <div className="setting-label">
            <strong>Document language</strong>
            <span className="muted small">The main language of the text.</span>
          </div>
          <div className="setting-control">
            <select value={quick.language} onChange={(event) => set({ language: event.target.value })}>
              {SARVAM_LANGUAGES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className={`setting ${ocrOff ? "disabled" : ""}`}>
        <div className="setting-label">
          <strong>Scanned document</strong>
          <span className="muted small">Read every page as an image. Use it when the text in the result is wrong or missing.</span>
        </div>
        <div className="setting-control">
          <Toggle checked={quick.scanned} onChange={(scanned) => set({ scanned })} label={quick.scanned ? "On" : "Off"} />
        </div>
      </div>

      <div className="setting">
        <div className="setting-label">
          <strong>Detect tables</strong>
          <span className="muted small">Rebuild table rows and columns in PDFs and images.</span>
        </div>
        <div className="setting-control">
          <Toggle checked={quick.tables} onChange={(tables) => set({ tables })} label={quick.tables ? "On" : "Off"} />
        </div>
      </div>

      <div className="setting">
        <div className="setting-label">
          <strong>Extract tables</strong>
          <span className="muted small">
            Every table as CSV and Excel, with its page, position, title and section. Works for scans too.
          </span>
        </div>
        <div className="setting-control">
          <Toggle
            checked={quick.extractTables}
            onChange={(extractTables) => set({ extractTables })}
            label={quick.extractTables ? "On" : "Off"}
          />
        </div>
      </div>

      <div className="setting">
        <div className="setting-label">
          <strong>Images in the output</strong>
          <span className="muted small">Include pictures, or leave a marker where they were.</span>
        </div>
        <div className="setting-control">
          <Segmented
            value={quick.images}
            options={[
              ["embedded", "Include"],
              ["placeholder", "Marker only"],
              ["referenced", "Separate files"],
            ]}
            onChange={(images) => set({ images })}
          />
        </div>
      </div>

      {quick.pipelineNote && <div className="notice">{quick.pipelineNote}</div>}
    </div>
  );
}

type AdvancedTab = "formats" | "general" | "json";

const GENERAL_SECTIONS: { key: keyof Catalog["general"] & keyof ConvertRequest; title: string; help: string }[] = [
  { key: "settings", title: "Input and limits", help: "Allowed formats, size and page limits, page range." },
  { key: "export", title: "Outputs", help: "Output formats, image handling and chunking." },
  { key: "validation", title: "Validation", help: "Checks on the converted content and structure." },
  { key: "tables", title: "Table extraction", help: "Files and metadata for every table." },
  { key: "envelope", title: "Result envelope", help: "What the result keeps." },
];

function AdvancedDrawer({
  catalog,
  request,
  onChange,
  onClose,
}: {
  catalog: Catalog;
  request: ConvertRequest;
  onChange: (request: ConvertRequest) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<AdvancedTab>("formats");
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label="Advanced settings" onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <h2>Advanced settings</h2>
            <p className="muted small">
              Every Docling option. Changed options are highlighted. The simple settings on the main page stay in sync.
            </p>
          </div>
          <div className="drawer-actions">
            <button
              type="button"
              className="btn ghost"
              onClick={() => window.confirm("Reset all settings to the defaults?") && onChange(EMPTY_REQUEST)}
            >
              Reset all
            </button>
            <button type="button" className="btn primary" onClick={onClose}>
              Done
            </button>
          </div>
        </header>
        <div className="segmented drawer-tabs">
          <button type="button" className={tab === "formats" ? "on" : ""} onClick={() => setTab("formats")}>
            Per file type
          </button>
          <button type="button" className={tab === "general" ? "on" : ""} onClick={() => setTab("general")}>
            Limits, outputs and checks
          </button>
          <button type="button" className={tab === "json" ? "on" : ""} onClick={() => setTab("json")}>
            Settings as JSON
          </button>
        </div>
        <div className="drawer-body">
          {tab === "formats" && (
            <FormatsPanel
              catalog={catalog}
              formats={request.formats}
              onChange={(formats) => onChange({ ...request, formats })}
            />
          )}
          {tab === "general" &&
            GENERAL_SECTIONS.map((section) => (
              <div className="card" key={section.key}>
                <h3>{section.title}</h3>
                <p className="help">{section.help}</p>
                <FieldForm
                  fields={catalog.general[section.key] as FieldSpec[]}
                  value={request[section.key] as Overrides}
                  onChange={(next) => onChange({ ...request, [section.key]: next })}
                />
              </div>
            ))}
          {tab === "json" && <RequestJson request={request} onChange={onChange} />}
        </div>
      </aside>
    </div>
  );
}

function RequestJson({ request, onChange }: { request: ConvertRequest; onChange: (r: ConvertRequest) => void }) {
  const text = JSON.stringify(request, null, 2);
  const [draft, setDraft] = useState(text);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(text), [text]);
  const curl = `curl -F "file=@document.pdf" -F 'options=${JSON.stringify(request)}' http://127.0.0.1:8000/api/convert`;
  return (
    <div className="card">
      <h3>Your settings as JSON</h3>
      <p className="help">
        Only your changes to the defaults. Save this text to reuse the settings, or send it as the <code>options</code>{" "}
        field of an API call.
      </p>
      <textarea className="json-editor" spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
      {error && <p className="text-danger small">{error}</p>}
      <div className="row">
        <button
          type="button"
          className="btn primary"
          onClick={() => {
            try {
              onChange({ ...EMPTY_REQUEST, ...JSON.parse(draft) });
              setError(null);
            } catch (exc) {
              setError(String(exc));
            }
          }}
        >
          Apply
        </button>
        <button type="button" className="btn ghost" onClick={() => navigator.clipboard?.writeText(text)}>
          Copy
        </button>
      </div>
      <h3>API call</h3>
      <pre className="preview-text">{curl}</pre>
    </div>
  );
}
