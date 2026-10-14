import { useEffect, useState } from "react";
import { OUTPUT_LABELS } from "../quick";
import type { Envelope, OutputItem } from "../types";
import { PagesSection, PicturesSection } from "./PagesAndPictures";
import { TablesSection } from "./TablesSection";

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const STATUS_TEXT: Record<Envelope["status"], { title: string; tone: string }> = {
  success: { title: "Converted", tone: "success" },
  partial_success: { title: "Converted with problems", tone: "warn" },
  failure: { title: "Conversion failed", tone: "danger" },
  rejected: { title: "File not accepted", tone: "danger" },
};

export function statusOf(envelope: Envelope): { title: string; tone: string } {
  const base = STATUS_TEXT[envelope.status];
  const warnings = envelope.validation?.checks.some((check) => check.status !== "pass");
  if (envelope.status === "success" && warnings) return { title: "Converted with warnings", tone: "warn" };
  return base;
}

function OutputPreview({ output }: { output: OutputItem }) {
  if (output.content === null) {
    return (
      <div className="notice">
        This file is too large to show here ({formatBytes(output.size_bytes)}). Use the download button.
      </div>
    );
  }
  if (output.media_type === "text/html") {
    // An empty sandbox: the preview cannot run scripts.
    return <iframe className="preview-frame" sandbox="" srcDoc={output.content} title={output.filename} />;
  }
  let text = output.content;
  if (output.media_type === "application/json") {
    try {
      text = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      // keep the raw text
    }
  }
  return <pre className="preview-text">{text}</pre>;
}

export function ResultView({ envelope }: { envelope: Envelope }) {
  const preferred = ["html", "md", "text", "json"];
  // The table package has its own section.
  const documentOutputs = envelope.outputs.filter(
    (output) => !/^(tables|pictures|pages)_/.test(output.format),
  );
  const firstOutput =
    preferred.map((id) => documentOutputs.find((output) => output.format === id)).find(Boolean) ?? documentOutputs[0];
  const [active, setActive] = useState(firstOutput?.format ?? "");
  const [copied, setCopied] = useState(false);
  useEffect(() => setActive(firstOutput?.format ?? ""), [envelope.job_id, firstOutput?.format]);

  const output = documentOutputs.find((item) => item.format === active);
  const problems = envelope.validation?.checks.filter((check) => check.status !== "pass") ?? [];
  const { stats, processing } = envelope;

  const facts = [
    envelope.source.detected_format?.toUpperCase(),
    stats && stats.pages > 0 ? `${stats.pages} page${stats.pages === 1 ? "" : "s"}` : null,
    stats && stats.tables > 0 ? `${stats.tables} table${stats.tables === 1 ? "" : "s"}` : null,
    stats && stats.pictures > 0 ? `${stats.pictures} picture${stats.pictures === 1 ? "" : "s"}` : null,
    processing?.ocr_engine ? `OCR: ${processing.ocr_engine}` : null,
    processing ? `${processing.duration_seconds.toFixed(1)} s` : null,
  ].filter(Boolean);

  return (
    <div className="result-body">
      {(problems.length > 0 || envelope.errors.length > 0) && (
        <div className="problems">
          {problems.map((check) => (
            <div key={check.id} className={`notice notice-${check.status === "fail" ? "danger" : "warn"}`}>
              {check.message}
            </div>
          ))}
          {envelope.errors.map((error, index) => (
            <div key={index} className="notice notice-danger">
              {error.message}
            </div>
          ))}
        </div>
      )}

      {facts.length > 0 && <p className="facts">{facts.join(" · ")}</p>}

      {envelope.pages && envelope.pages.length > 0 && <PagesSection pages={envelope.pages} outputs={envelope.outputs} />}

      {envelope.pictures && envelope.pictures.length > 0 && (
        <PicturesSection pictures={envelope.pictures} outputs={envelope.outputs} />
      )}

      {envelope.tables && envelope.tables.length > 0 && (
        <TablesSection tables={envelope.tables} outputs={envelope.outputs} />
      )}

      {documentOutputs.length > 0 && (
        <div className="viewer">
          <div className="viewer-bar">
            <div className="segmented">
              {documentOutputs.map((item) => (
                <button
                  key={item.format}
                  type="button"
                  className={item.format === active ? "on" : ""}
                  onClick={() => setActive(item.format)}
                >
                  {OUTPUT_LABELS[item.format] ?? item.format}
                </button>
              ))}
            </div>
            <div className="viewer-actions">
              {output?.content && (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => {
                    navigator.clipboard?.writeText(output.content ?? "");
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }}
                >
                  {copied ? "Copied" : "Copy"}
                </button>
              )}
              {output && (
                <a className="btn" href={output.url} download={output.filename}>
                  Download
                </a>
              )}
              {envelope.bundle_url && documentOutputs.length > 1 && (
                <a className="btn" href={envelope.bundle_url}>
                  Download all
                </a>
              )}
            </div>
          </div>
          {output && <OutputPreview output={output} />}
        </div>
      )}

      <details className="tech">
        <summary>Technical details</summary>
        <dl>
          <dt>Pipeline</dt>
          <dd>{processing?.pipeline ?? "-"}</dd>
          <dt>Parser</dt>
          <dd>{processing?.backend ?? "-"}</dd>
          <dt>Characters</dt>
          <dd>{stats?.characters.toLocaleString() ?? "-"}</dd>
          <dt>Headings</dt>
          <dd>{stats?.headings ?? "-"}</dd>
          <dt>Checks</dt>
          <dd>{envelope.validation?.checks.map((check) => `${check.id}: ${check.status}`).join(", ") ?? "-"}</dd>
          <dt>Job</dt>
          <dd>
            <code>{envelope.job_id}</code>
          </dd>
          <dt>Docling</dt>
          <dd>{processing?.docling_version ?? "-"}</dd>
        </dl>
        {envelope.original_url && (
          <p>
            <a href={envelope.original_url}>Original file</a>
          </p>
        )}
        <pre className="preview-text small">
          {JSON.stringify(envelope, (key, value) => (key === "content" ? undefined : value), 2)}
        </pre>
      </details>
    </div>
  );
}
