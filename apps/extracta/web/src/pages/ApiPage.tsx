import { useEffect, useState } from "react";
import type { ConvertRequest } from "../types";

const ENDPOINTS: [string, string, string][] = [
  ["POST", "/api/convert", "Convert one file. Form fields: file, options (JSON). Returns the result envelope."],
  ["GET", "/api/catalog", "Every format, pipeline and option, as the settings pages use them."],
  ["GET", "/api/jobs", "Past conversions, newest first (limit=50)."],
  ["GET", "/api/jobs/{job_id}", "The result envelope of one conversion."],
  ["GET", "/api/jobs/{job_id}/files/{path}", "An output file: exports, tables, images, pages, bundle.zip."],
  ["GET", "/api/health", "Server state: Docling version, Sarvam set up, upload limit."],
];

export function ApiPage({
  request,
  onChange,
  emptyRequest,
}: {
  request: ConvertRequest;
  onChange: (request: ConvertRequest) => void;
  emptyRequest: ConvertRequest;
}) {
  const text = JSON.stringify(request, null, 2);
  const [draft, setDraft] = useState(text);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => setDraft(text), [text]);

  const origin = window.location.origin;
  const curl = `curl -F "file=@document.pdf" \\\n     -F 'options=${JSON.stringify(request)}' \\\n     ${origin}/api/convert`;
  const copy = (label: string, value: string) => {
    navigator.clipboard?.writeText(value);
    setCopied(label);
    setTimeout(() => setCopied(null), 1500);
  };

  return (
    <div className="page-narrow">
      <header className="page-head">
        <div>
          <h1>API</h1>
          <p className="muted">Use Extracta from your own code. The API takes the same settings as this page.</p>
        </div>
      </header>

      <section className="card">
        <h2 className="section-title">Convert with your current settings</h2>
        <pre className="preview-text code-block">{curl}</pre>
        <div className="row">
          <button type="button" className="btn" onClick={() => copy("curl", curl)}>
            {copied === "curl" ? "Copied" : "Copy command"}
          </button>
        </div>
      </section>

      <section className="card">
        <h2 className="section-title">Endpoints</h2>
        <table className="history-table endpoints">
          <tbody>
            {ENDPOINTS.map(([method, path, help]) => (
              <tr key={method + path}>
                <td>
                  <span className={`method method-${method.toLowerCase()}`}>{method}</span>
                </td>
                <td>
                  <code>{path}</code>
                </td>
                <td className="muted small">{help}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h2 className="section-title">Settings as JSON</h2>
        <p className="help">
          Only your changes to the defaults. Send this as the <code>options</code> field, or paste saved settings here and apply them.
        </p>
        <textarea className="json-editor" spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
        {error && <p className="text-danger small">{error}</p>}
        <div className="row">
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              try {
                onChange({ ...emptyRequest, ...JSON.parse(draft) });
                setError(null);
              } catch (exc) {
                setError(String(exc));
              }
            }}
          >
            Apply
          </button>
          <button type="button" className="btn ghost" onClick={() => copy("json", text)}>
            {copied === "json" ? "Copied" : "Copy"}
          </button>
        </div>
      </section>
    </div>
  );
}
