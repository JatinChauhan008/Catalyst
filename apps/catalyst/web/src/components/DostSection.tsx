import type { DostReport, OutputItem } from "../types";

const STATUS_LABELS: Record<string, string> = {
  translated: "translated",
  english: "already English",
  no_letters: "numbers only",
  failed: "failed",
  unsupported: "language not supported",
  disabled: "not translated",
};

/** The three DOST outputs and the report of what is missing or uncertain. */
export function DostSection({ report, outputs }: { report: DostReport; outputs: OutputItem[] }) {
  const file = (format: string) => outputs.find((output) => output.format === format);
  const tables = file("dost_tables_md");
  const sentences = file("dost_sentences_csv");
  const reportFile = file("dost_report_json");
  // The images are next to the report: .../outputs/dost/images/<name>.
  const imageUrl = (name: string) => (reportFile ? reportFile.url.replace(/[^/]+$/, `images/${name}`) : "");
  const problems = report.issues.filter((issue) => issue.severity !== "info");
  const notes = report.issues.filter((issue) => issue.severity === "info");
  const statuses = Object.entries(report.sentences.by_status)
    .map(([status, count]) => `${count} ${STATUS_LABELS[status] ?? status}`)
    .join(", ");

  return (
    <section className="tables">
      <div className="tables-head">
        <h3>
          Tables, sentences and images{" "}
          <span className={report.complete ? "muted" : "text-warn"}>
            ({report.complete ? "complete" : `${problems.length} problem${problems.length === 1 ? "" : "s"}`})
          </span>
        </h3>
        <div className="dost-actions">
          {tables && (
            <a className="btn ghost" href={tables.url} download={tables.filename}>
              Tables (Markdown)
            </a>
          )}
          {sentences && (
            <a className="btn ghost" href={sentences.url} download={sentences.filename}>
              Sentences (CSV)
            </a>
          )}
          {reportFile && (
            <a className="btn ghost" href={reportFile.url} download={reportFile.filename}>
              Report (JSON)
            </a>
          )}
        </div>
      </div>

      <p className="facts">
        {report.tables.tables} table{report.tables.tables === 1 ? "" : "s"} · {report.sentences.sentences} sentence
        {report.sentences.sentences === 1 ? "" : "s"}
        {statuses ? ` (${statuses})` : ""} · {report.images.files} image{report.images.files === 1 ? "" : "s"} (
        {report.images.embedded} embedded, {report.images.rendered} rendered)
        {report.scanned_pages.length > 0 ? ` · scanned pages: ${report.scanned_pages.join(", ")}` : ""}
      </p>

      {problems.length > 0 && (
        <div className="problems">
          {problems.map((issue, index) => (
            <div key={index} className={`notice notice-${issue.severity === "error" ? "danger" : "warn"}`}>
              {issue.page !== null ? `Page ${issue.page}: ` : ""}
              {issue.message}
            </div>
          ))}
        </div>
      )}
      {notes.length > 0 && (
        <details className="small">
          <summary>Notes and limits ({notes.length})</summary>
          <ul>
            {notes.map((issue, index) => (
              <li key={index}>{issue.message}</li>
            ))}
          </ul>
        </details>
      )}

      {report.image_files.length > 0 && (
        <div className="picture-grid">
          {report.image_files.map((image) => (
            <figure key={image.filename} className="picture-card">
              <a href={imageUrl(image.filename)} target="_blank" rel="noreferrer">
                <img src={imageUrl(image.filename)} alt={image.caption ?? image.filename} loading="lazy" />
              </a>
              <figcaption>
                <span className="small">
                  {image.filename} · {image.page !== null ? `page ${image.page} · ` : ""}
                  {image.kind} · {image.width_px}×{image.height_px}
                  {image.occurrences > 1 ? ` · used ${image.occurrences} times` : ""}
                </span>
                {image.caption && <span className="muted small picture-caption">{image.caption}</span>}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
