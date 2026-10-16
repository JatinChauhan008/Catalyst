import type { Envelope, OutputItem } from "../types";
import { OUTPUT_LABELS } from "../quick";
import { DostStats, ProblemTable } from "./DostSection";

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function formatMoney(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
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
  if (envelope.status === "success" && (warnings || (envelope.dost && !envelope.dost.complete))) {
    return { title: "Converted, needs review", tone: "warn" };
  }
  return base;
}

// Download labels, in the order they are listed.
const DOWNLOADS: [string, string][] = [
  ["dost_tables_md", "Tables (Markdown)"],
  ["dost_sentences_csv", "Sentences with English translation (CSV)"],
  ["dost_problems_csv", "Sentences to check (CSV)"],
  ["dost_images_zip", "All images (ZIP)"],
  ["dost_report_json", "Extraction report (JSON)"],
  ["tables_xlsx", "Table package (Excel)"],
  ["tables_json", "Table package (JSON)"],
  ["pictures_json", "Picture list (JSON)"],
  ["pages_html", "HTML per page (index)"],
];

function downloadLabel(output: OutputItem): string {
  const known = DOWNLOADS.find(([format]) => format === output.format);
  if (known) return known[1];
  return `Document (${OUTPUT_LABELS[output.format] ?? output.format})`;
}

function Downloads({ envelope }: { envelope: Envelope }) {
  const order = (output: OutputItem) => {
    const index = DOWNLOADS.findIndex(([format]) => format === output.format);
    return index === -1 ? DOWNLOADS.length : index;
  };
  const outputs = [...envelope.outputs].sort((a, b) => order(a) - order(b));
  const images = envelope.dost?.images.files ?? 0;
  if (outputs.length === 0) return null;
  return (
    <section className="downloads">
      <h4>Downloads</h4>
      <ul>
        {outputs.map((output) => (
          <li key={output.format}>
            <span className="download-name">
              <strong>{downloadLabel(output)}</strong>
              <span className="muted small">
                {output.filename} · {formatBytes(output.size_bytes)}
                {output.format === "dost_images_zip" ? ` · ${images} image${images === 1 ? "" : "s"}` : ""}
              </span>
            </span>
            <a className="btn" href={output.url} download={output.filename}>
              Download
            </a>
          </li>
        ))}
        {envelope.bundle_url && outputs.length > 1 && (
          <li className="download-all">
            <span className="download-name">
              <strong>Everything (ZIP)</strong>
              <span className="muted small">All the files above in one archive</span>
            </span>
            <a className="btn primary" href={envelope.bundle_url}>
              Download all
            </a>
          </li>
        )}
      </ul>
    </section>
  );
}

function Summary({ envelope }: { envelope: Envelope }) {
  const { stats, processing } = envelope;
  const ocr = processing?.sarvam;
  const translation = processing?.sarvam_translation;
  const currency = ocr?.currency ?? translation?.currency;
  const facts = [
    envelope.source.detected_format?.toUpperCase(),
    !envelope.dost && stats && stats.pages > 0 ? `${stats.pages} page${stats.pages === 1 ? "" : "s"}` : null,
    processing?.ocr_engine ? `OCR: ${processing.ocr_engine}` : null,
    processing?.ocr_language_from_font
      ? `Language: ${processing.ocr_language_from_font}`
      : envelope.dost?.source_language
        ? `Language: ${envelope.dost.source_language}`
        : null,
    processing ? `${processing.duration_seconds.toFixed(1)} s` : null,
  ].filter(Boolean);

  return (
    <section className="summary">
      <h4>Summary</h4>
      {envelope.dost && <DostStats report={envelope.dost} />}
      {facts.length > 0 && <p className="facts">{facts.join(" · ")}</p>}
      {currency && (
        <p className="cost">
          <strong>Sarvam cost:</strong>{" "}
          {[
            ocr ? `OCR ${formatMoney(ocr.cost, ocr.currency)} (${ocr.pages} page${ocr.pages === 1 ? "" : "s"})` : null,
            translation
              ? `translation ${formatMoney(translation.cost, translation.currency)} (${translation.characters.toLocaleString()} characters)`
              : null,
          ]
            .filter(Boolean)
            .join(" + ")}
          {" = "}
          <strong>{formatMoney((ocr?.cost ?? 0) + (translation?.cost ?? 0), currency)}</strong>
          <span className="muted small"> (estimate; check the Sarvam dashboard for the billed amount)</span>
        </p>
      )}
    </section>
  );
}

export function ResultView({ envelope }: { envelope: Envelope }) {
  const warnings = envelope.validation?.checks.filter((check) => check.status !== "pass") ?? [];
  const problems = envelope.dost?.sentence_problems ?? [];

  return (
    <div className="result-body">
      {(warnings.length > 0 || envelope.errors.length > 0) && (
        <div className="problems">
          {envelope.errors.map((error, index) => (
            <div key={`e${index}`} className="notice notice-danger">
              {error.message}
            </div>
          ))}
          {warnings.map((check) => (
            <div key={check.id} className={`notice notice-${check.status === "fail" ? "danger" : "warn"}`}>
              {check.message}
            </div>
          ))}
        </div>
      )}

      <Downloads envelope={envelope} />
      <Summary envelope={envelope} />
      {problems.length > 0 && <ProblemTable problems={problems} />}
      {envelope.dost && problems.length === 0 && (
        <p className="muted">Every sentence has an English translation; no sentence needs a check.</p>
      )}
    </div>
  );
}
