import { useMemo, useState, type ReactNode } from "react";
import type { DostIssue, DostReport, OutputItem, SentenceProblem, SentenceProblemKind } from "../types";

const KIND_LABELS: Record<SentenceProblemKind, string> = {
  not_translated: "Not translated",
  language_not_supported: "Language not supported",
  translation_off: "Translation off",
  numbers_differ: "Numbers missing",
  language_assumed: "Language assumed",
  retranslated: "Second try",
  ocr_suspect: "OCR text suspect",
};

const KIND_TONE: Record<SentenceProblemKind, "danger" | "warn" | "info"> = {
  not_translated: "danger",
  language_not_supported: "warn",
  translation_off: "warn",
  numbers_differ: "warn",
  language_assumed: "info",
  retranslated: "info",
  ocr_suspect: "warn",
};

const PAGE_SIZE = 50;

interface Group {
  kind: SentenceProblemKind;
  reason: string;
  action: string | null;
  rows: number[];
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** The DOST outputs and a readable account of what is missing or uncertain. */
export function DostSection({ report, outputs }: { report: DostReport; outputs: OutputItem[] }) {
  const file = (format: string) => outputs.find((output) => output.format === format);
  const downloads = [
    { item: file("dost_tables_md"), label: "Tables (Markdown)" },
    { item: file("dost_sentences_csv"), label: "Sentences (CSV)" },
    { item: file("dost_problems_csv"), label: "Sentences to check (CSV)" },
    { item: file("dost_report_json"), label: "Report (JSON)" },
  ];
  const reportFile = file("dost_report_json");
  // The images are next to the report: .../outputs/dost/images/<name>.
  const imageUrl = (name: string) => (reportFile ? reportFile.url.replace(/[^/]+$/, `images/${name}`) : "");

  const problems = report.sentence_problems ?? [];
  const groups = useMemo(() => {
    const byKey = new Map<string, Group>();
    for (const problem of problems) {
      const summary = problem.summary || problem.reason;
      const key = `${problem.kind}|${summary}`;
      const group = byKey.get(key) ?? { kind: problem.kind, reason: summary, action: problem.action, rows: [] };
      group.rows.push(problem.row);
      byKey.set(key, group);
    }
    const order: SentenceProblemKind[] = [
      "ocr_suspect",
      "not_translated",
      "language_not_supported",
      "translation_off",
      "numbers_differ",
      "language_assumed",
      "retranslated",
    ];
    return [...byKey.values()].sort(
      (a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || b.rows.length - a.rows.length,
    );
  }, [problems]);

  // Problems that are not about single sentences (tables, images, the document).
  const otherProblems = report.issues.filter((issue) => issue.severity !== "info" && issue.component !== "translation");
  const notes = report.issues.filter((issue) => issue.severity === "info" && issue.component !== "translation");

  const counts = report.sentences.by_status;
  const translated = (counts.translated ?? 0) + (counts.english ?? 0) + (counts.no_letters ?? 0);
  const empty = problems.filter((p) => !p.translation).length;
  const total = report.sentences.sentences;
  const needsReview = !report.complete;

  return (
    <section className="tables dost">
      <div className="tables-head">
        <h3>
          Tables, sentences and images{" "}
          <span className={`dost-status ${needsReview ? "dost-status-warn" : "dost-status-ok"}`}>
            {needsReview ? "Needs review" : "Complete"}
          </span>
        </h3>
        <div className="dost-actions">
          {downloads.map(
            ({ item, label }) =>
              item && (
                <a key={item.format} className="btn ghost" href={item.url} download={item.filename}>
                  {label}
                </a>
              ),
          )}
        </div>
      </div>

      <div className="dost-stats">
        <Stat value={report.tables.tables} label="tables" />
        <Stat
          value={total}
          label="sentences"
          detail={
            total > 0 ? (
              <>
                <div className="dost-bar" aria-hidden="true">
                  <span className="dost-bar-ok" style={{ width: `${(100 * translated) / total}%` }} />
                </div>
                {translated} with English{empty > 0 ? ` · ${empty} without` : ""}
              </>
            ) : null
          }
        />
        <Stat
          value={report.images.files}
          label="images"
          detail={`${report.images.embedded} stored, ${report.images.rendered} rendered`}
        />
        {report.pages > 0 && <Stat
          value={report.pages}
          label="pages"
          detail={
            report.scanned_pages.length > 0
              ? `${report.scanned_pages.length} scanned (read with OCR)`
              : report.source_language
                ? `language ${report.source_language}`
                : undefined
          }
        />}
      </div>

      {(groups.length > 0 || otherProblems.length > 0) && (
        <div className="dost-attention">
          <h4>What needs attention</h4>
          <ul>
            {groups.map((group) => (
              <li key={`${group.kind}|${group.reason}`} className={`dost-attn dost-attn-${KIND_TONE[group.kind]}`}>
                <strong>
                  {KIND_LABELS[group.kind]}: {plural(group.rows.length, "sentence")}
                </strong>
                <span>{group.reason}</span>
                {group.action && <span className="muted">What to do: {group.action}</span>}
              </li>
            ))}
            {otherProblems.map((issue, index) => (
              <IssueItem key={index} issue={issue} />
            ))}
          </ul>
        </div>
      )}

      {problems.length > 0 && <ProblemTable problems={problems} />}

      {notes.length > 0 && (
        <details className="small dost-notes">
          <summary>Notes and limits ({notes.length})</summary>
          <ul>
            {notes.map((issue, index) => (
              <li key={index}>{issue.message}</li>
            ))}
          </ul>
        </details>
      )}

      {report.image_files.length > 0 && (
        <details className="dost-images" open={report.image_files.length <= 24}>
          <summary>Images ({report.image_files.length})</summary>
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
        </details>
      )}
    </section>
  );
}

function Stat({ value, label, detail }: { value: number; label: string; detail?: ReactNode }) {
  return (
    <div className="dost-stat">
      <span className="dost-stat-value">{value.toLocaleString()}</span>
      <span className="dost-stat-label">{label}</span>
      {detail && <span className="dost-stat-detail">{detail}</span>}
    </div>
  );
}

function IssueItem({ issue }: { issue: DostIssue }) {
  const tone = issue.severity === "error" ? "danger" : "warn";
  return (
    <li className={`dost-attn dost-attn-${tone}`}>
      <strong>
        {issue.component === "document" ? "Document" : issue.component[0].toUpperCase() + issue.component.slice(1)}
        {issue.page !== null ? `, page ${issue.page}` : ""}
      </strong>
      <span>{issue.message}</span>
    </li>
  );
}

function ProblemTable({ problems }: { problems: SentenceProblem[] }) {
  const kinds = [...new Set(problems.map((p) => p.kind))];
  const [kind, setKind] = useState<SentenceProblemKind | "all">("all");
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(PAGE_SIZE);
  const [open, setOpen] = useState<number | null>(null);

  const filtered = problems.filter(
    (p) =>
      (kind === "all" || p.kind === kind) &&
      (!query ||
        p.original.toLowerCase().includes(query.toLowerCase()) ||
        p.translation.toLowerCase().includes(query.toLowerCase()) ||
        String(p.row) === query.trim()),
  );

  return (
    <div className="dost-problems">
      <div className="dost-problems-head">
        <h4>Sentences to check ({problems.length})</h4>
        <input
          type="search"
          className="dost-search"
          placeholder="Search text or row number"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setShown(PAGE_SIZE);
          }}
          aria-label="Search the sentences to check"
        />
      </div>
      <div className="dost-filters" role="group" aria-label="Filter by problem">
        <button type="button" className={kind === "all" ? "on" : ""} onClick={() => setKind("all")}>
          All {problems.length}
        </button>
        {kinds.map((k) => (
          <button
            key={k}
            type="button"
            className={`${kind === k ? "on" : ""} dost-filter-${KIND_TONE[k]}`}
            onClick={() => {
              setKind(k);
              setShown(PAGE_SIZE);
            }}
          >
            {KIND_LABELS[k]} {problems.filter((p) => p.kind === k).length}
          </button>
        ))}
      </div>
      <div className="dost-table-wrap">
        <table className="dost-table">
          <thead>
            <tr>
              <th>Row</th>
              <th>Page</th>
              <th>Original sentence</th>
              <th>English translation</th>
              <th>Problem</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, shown).map((p) => (
              <tr key={p.row}>
                <td className="num">{p.row}</td>
                <td className="num">{p.page ?? "–"}</td>
                <td dir="auto" className="dost-text">
                  <div className="dost-text-box">{p.original}</div>
                </td>
                <td className="dost-text">
                  <div className="dost-text-box">{p.translation || <span className="muted">(empty)</span>}</div>
                </td>
                <td>
                  <span className={`dost-badge dost-badge-${KIND_TONE[p.kind]}`}>{KIND_LABELS[p.kind]}</span>
                  <div className="small">{p.reason}</div>
                  {p.detail && p.detail !== p.reason && (
                    <button type="button" className="dost-link small" onClick={() => setOpen(open === p.row ? null : p.row)}>
                      {open === p.row ? "Hide details" : "Details"}
                    </button>
                  )}
                  {open === p.row && <pre className="dost-detail">{p.detail}</pre>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {filtered.length === 0 && <p className="muted small">No sentence matches.</p>}
      {filtered.length > shown && (
        <button type="button" className="btn ghost" onClick={() => setShown(shown + PAGE_SIZE)}>
          Show {Math.min(PAGE_SIZE, filtered.length - shown)} more of {filtered.length - shown}
        </button>
      )}
    </div>
  );
}
