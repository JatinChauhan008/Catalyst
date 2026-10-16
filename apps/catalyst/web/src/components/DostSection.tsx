import { useState, type ReactNode } from "react";
import type { DostReport, SentenceProblem, SentenceProblemKind } from "../types";

const KIND_LABELS: Record<SentenceProblemKind, string> = {
  ocr_suspect: "OCR text suspect",
  not_translated: "Not translated",
  language_not_supported: "Language not supported",
  translation_off: "Translation off",
  numbers_differ: "Numbers missing",
  language_assumed: "Language assumed",
  retranslated: "Second try",
};

const KIND_TONE: Record<SentenceProblemKind, "danger" | "warn" | "info"> = {
  ocr_suspect: "warn",
  not_translated: "danger",
  language_not_supported: "warn",
  translation_off: "warn",
  numbers_differ: "warn",
  language_assumed: "info",
  retranslated: "info",
};

const PAGE_SIZE = 50;

function Stat({ value, label, detail }: { value: number; label: string; detail?: ReactNode }) {
  return (
    <div className="dost-stat">
      <span className="dost-stat-value">{value.toLocaleString()}</span>
      <span className="dost-stat-label">{label}</span>
      {detail && <span className="dost-stat-detail">{detail}</span>}
    </div>
  );
}

/** Counts of the DOST outputs: tables, sentences (with English or not), images, pages. */
export function DostStats({ report }: { report: DostReport }) {
  const counts = report.sentences.by_status;
  const total = report.sentences.sentences;
  const withEnglish = (counts.translated ?? 0) + (counts.english ?? 0) + (counts.no_letters ?? 0);
  const toCheck = report.sentence_problems?.length ?? 0;
  return (
    <div className="dost-stats">
      <Stat value={report.tables.tables} label="tables" />
      <Stat
        value={total}
        label="sentences"
        detail={
          total > 0 ? (
            <>
              <div className="dost-bar" aria-hidden="true">
                <span className="dost-bar-ok" style={{ width: `${(100 * withEnglish) / total}%` }} />
              </div>
              {withEnglish} with English{toCheck > 0 ? ` · ${toCheck} to check` : ""}
            </>
          ) : null
        }
      />
      <Stat value={report.images.files} label="images" detail={`${report.images.embedded} stored, ${report.images.rendered} rendered`} />
      {report.pages > 0 && (
        <Stat
          value={report.pages}
          label="pages"
          detail={report.scanned_pages.length > 0 ? `${report.scanned_pages.length} scanned (read with OCR)` : undefined}
        />
      )}
    </div>
  );
}

/** Every sentence without a translation, or with one to check, with its reason. */
export function ProblemTable({ problems }: { problems: SentenceProblem[] }) {
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
    <section className="dost-problems">
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
            className={kind === k ? "on" : ""}
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
                <td className="dost-why">
                  <span className={`dost-badge dost-badge-${KIND_TONE[p.kind]}`}>{KIND_LABELS[p.kind]}</span>
                  <div className="small">{p.reason}</div>
                  {p.action && <div className="small muted">What to do: {p.action}</div>}
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
    </section>
  );
}
