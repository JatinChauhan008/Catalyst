import { useCallback, useEffect, useState } from "react";
import { convertFile, fetchCatalog } from "./api";
import { ConvertPage, type QueueItem } from "./pages/ConvertPage";
import type { Catalog, ConvertRequest } from "./types";

const STORAGE_KEY = "catalyst.request.v2";
// DOST (tables, sentences with English, images) is one of the output formats,
// selected by default.
const EMPTY_REQUEST: ConvertRequest = {
  settings: {},
  export: {},
  validation: {},
  envelope: {},
  tables: {},
  pages: {},
  pictures: {},
  dost: { enabled: true },
  formats: {},
};

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

  useEffect(() => {
    fetchCatalog().then(setCatalog, (error) => setLoadError(String(error)));
  }, []);

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

  return (
    <div className="shell single">
      <header className="topbar">
        <Logo />
      </header>

      <main className="content">
        <ConvertPage
          catalog={catalog}
          request={request}
          onRequestChange={updateRequest}
          onReset={() => updateRequest(EMPTY_REQUEST)}
          queue={queue}
          onAddFiles={addFiles}
          onRemove={(id) => setQueue((current) => current.filter((q) => q.id !== id))}
          onRun={run}
          running={running}
          openResult={openResult}
          onOpenResult={setOpenResult}
        />
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="logo">
      <span className="logo-name">Catalyst</span>
    </div>
  );
}
