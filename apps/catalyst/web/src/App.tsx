import { useCallback, useEffect, useState, type ReactNode } from "react";
import { convertFile, fetchCatalog } from "./api";
import { countChanges } from "./components/FieldForm";
import { CodeIcon, FileIcon, GearIcon, HistoryIcon, SparkleIcon } from "./components/Icons";
import { ApiPage } from "./pages/ApiPage";
import { ConvertPage, type QueueItem } from "./pages/ConvertPage";
import { HistoryPage } from "./pages/HistoryPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { Catalog, ConvertRequest } from "./types";

const STORAGE_KEY = "catalyst.request.v1";
const EMPTY_REQUEST: ConvertRequest = {
  settings: {},
  export: {},
  validation: {},
  envelope: {},
  tables: {},
  pages: {},
  pictures: {},
  dost: {},
  formats: {},
};

type Page = "convert" | "history" | "api" | "settings";
const PAGES: Page[] = ["convert", "history", "api", "settings"];

function pageFromHash(): Page {
  const hash = window.location.hash.replace("#", "") as Page;
  return PAGES.includes(hash) ? hash : "convert";
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
  const [page, setPage] = useState<Page>(pageFromHash);

  useEffect(() => {
    fetchCatalog().then(setCatalog, (error) => setLoadError(String(error)));
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (next: Page) => {
    window.location.hash = next;
    setPage(next);
    window.scrollTo(0, 0);
  };

  const updateRequest = useCallback((next: ConvertRequest) => {
    setRequest(next);
    saveRequest(next);
  }, []);

  if (loadError || !catalog) {
    return (
      <div className="splash">
        <Logo />
        {loadError ? (
          <>
            <div className="notice notice-danger">The Catalyst server is not reachable. Start it, then reload this page.</div>
            <p className="muted small">{loadError}</p>
          </>
        ) : (
          <p className="muted">
            <span className="spinner" /> Loading…
          </p>
        )}
      </div>
    );
  }

  const changes =
    countChanges(request.settings) +
    countChanges(request.validation) +
    countChanges(request.envelope) +
    countChanges(request.tables ?? {}) +
    countChanges(request.pages ?? {}) +
    countChanges(request.pictures ?? {}) +
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
    const pending = queue.filter((item) => item.state === "queued" || item.state === "error");
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

  const reset = () => updateRequest(EMPTY_REQUEST);

  return (
    <div className="shell">
      <header className="topbar">
        <Logo />
        <span className={`pill ${catalog.server.sarvam_configured ? "pill-on" : ""}`}>
          <span className="pill-dot" />
          {catalog.server.sarvam_configured ? "Sarvam OCR ready" : "Sarvam OCR not set up"}
        </span>
        <div className="topbar-actions">
          <button type="button" className="icon-round" aria-label="Settings" onClick={() => go("settings")}>
            <GearIcon />
          </button>
          <button type="button" className="btn pill-btn" onClick={() => go("settings")}>
            Advanced settings
            {changes > 0 && <span className="count">{changes}</span>}
          </button>
        </div>
      </header>

      <nav className="sidebar" aria-label="Main">
        <NavItem active={page === "convert"} icon={<FileIcon size={22} />} title="Convert" help="Document to text/HTML" onClick={() => go("convert")} />
        <NavItem active={page === "history"} icon={<HistoryIcon size={22} />} title="History" help="Past conversions" onClick={() => go("history")} />
        <NavItem active={page === "api"} icon={<CodeIcon size={22} />} title="API" help="Integrate with Catalyst" onClick={() => go("api")} />
        <NavItem active={page === "settings"} icon={<GearIcon size={22} />} title="Settings" help="Preferences" onClick={() => go("settings")} />
        <div className="sidebar-card">
          <span className="sidebar-card-icon">
            <SparkleIcon size={22} />
          </span>
          {catalog.server.sarvam_configured ? (
            <>
              <strong>Powered by Sarvam OCR</strong>
              <span className="muted small">Accurate text extraction for Indian documents</span>
            </>
          ) : (
            <>
              <strong>Powered by Docling</strong>
              <span className="muted small">Add a Sarvam key for Indian-language OCR</span>
            </>
          )}
        </div>
      </nav>

      <main className="content">
        {page === "convert" && (
          <ConvertPage
            catalog={catalog}
            request={request}
            onRequestChange={updateRequest}
            onReset={reset}
            queue={queue}
            onAddFiles={addFiles}
            onRemove={(id) => setQueue((current) => current.filter((q) => q.id !== id))}
            onRun={run}
            running={running}
            openResult={openResult}
            onOpenResult={setOpenResult}
          />
        )}
        {page === "history" && <HistoryPage />}
        {page === "api" && <ApiPage request={request} onChange={updateRequest} emptyRequest={EMPTY_REQUEST} />}
        {page === "settings" && <SettingsPage catalog={catalog} request={request} onChange={updateRequest} onReset={reset} />}
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="logo">
      <span className="logo-mark">E</span>
      <span className="logo-name">Catalyst</span>
    </div>
  );
}

function NavItem({
  active,
  icon,
  title,
  help,
  onClick,
}: {
  active: boolean;
  icon: ReactNode;
  title: string;
  help: string;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`nav-item ${active ? "active" : ""}`} aria-current={active ? "page" : undefined} onClick={onClick}>
      <span className="nav-icon">{icon}</span>
      <span className="nav-text">
        <strong>{title}</strong>
        <span className="small">{help}</span>
      </span>
    </button>
  );
}
