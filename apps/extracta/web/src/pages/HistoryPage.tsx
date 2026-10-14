import { useEffect, useState } from "react";
import { fetchJob, fetchJobs } from "../api";
import { ResultView, formatBytes, statusOf } from "../components/ResultView";
import type { Envelope, JobSummary } from "../types";

function when(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function HistoryPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [envelope, setEnvelope] = useState<Envelope | null>(null);

  const load = () => fetchJobs(100).then(setJobs, (exc) => setError(String(exc)));
  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    setEnvelope(null);
    if (selected) fetchJob(selected).then(setEnvelope, (exc) => setError(String(exc)));
  }, [selected]);

  return (
    <div className="page-narrow">
      <header className="page-head">
        <div>
          <h1>History</h1>
          <p className="muted">Past conversions on this server, newest first. The server keeps the latest 200.</p>
        </div>
        <button type="button" className="btn ghost" onClick={load}>
          Refresh
        </button>
      </header>
      {error && <div className="notice notice-danger">{error}</div>}
      {!jobs && !error && (
        <p className="muted">
          <span className="spinner" /> Loading…
        </p>
      )}
      {jobs && jobs.length === 0 && <div className="card empty-state">No conversions yet.</div>}
      {jobs && jobs.length > 0 && (
        <div className="card history-card">
          <table className="history-table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th>Pages</th>
                <th>Tables</th>
                <th>OCR</th>
                <th>Time</th>
                <th>Converted</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const tone =
                  job.status === "success" ? "success" : job.status === "partial_success" ? "warn" : "danger";
                return (
                  <tr
                    key={job.job_id}
                    className={job.job_id === selected ? "selected" : ""}
                    onClick={() => setSelected(job.job_id === selected ? null : job.job_id)}
                  >
                    <td>
                      <span className="history-name">{job.filename}</span>
                      <span className="muted small">
                        {(job.detected_format ?? "?").toUpperCase()} · {formatBytes(job.size_bytes)}
                      </span>
                    </td>
                    <td>
                      <span className={`tag tag-${tone}`}>{job.status.replace("_", " ")}</span>
                    </td>
                    <td>{job.pages || "–"}</td>
                    <td>{job.tables || "–"}</td>
                    <td>{job.ocr_engine ?? "–"}</td>
                    <td>{job.duration_seconds != null ? `${job.duration_seconds.toFixed(1)} s` : "–"}</td>
                    <td className="muted small">{when(job.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selected && (
        <section className="card">
          {envelope ? (
            <>
              <h2 className="section-title">
                {envelope.source.filename} <span className={`status-text text-${statusOf(envelope).tone}`}>{statusOf(envelope).title}</span>
              </h2>
              <ResultView envelope={envelope} />
            </>
          ) : (
            <p className="muted">
              <span className="spinner" /> Loading the result…
            </p>
          )}
        </section>
      )}
    </div>
  );
}
