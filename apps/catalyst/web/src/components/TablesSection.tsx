import { useState } from "react";
import type { OutputItem, TableSummary } from "../types";

function where(table: TableSummary): string {
  const pages = [...new Set(table.regions.map((region) => region.page))];
  if (pages.length === 0) return "";
  const unit = table.regions[0]?.units === "cell" ? "sheet" : "page";
  return pages.length === 1 ? `${unit} ${pages[0]}` : `${unit}s ${pages.join(", ")}`;
}

function readFrom(table: TableSummary): string {
  const { method, ocr_engine } = table.extraction;
  const label = { text_layer: "PDF text", ocr: "OCR", mixed: "PDF text and OCR", structured: "file structure" }[method] ?? method;
  return (method === "ocr" || method === "mixed") && ocr_engine ? `${label} (${ocr_engine})` : label;
}

export function TablesSection({ tables, outputs }: { tables: TableSummary[]; outputs: OutputItem[] }) {
  const [open, setOpen] = useState<string | null>(tables[0]?.table_id ?? null);
  const workbook = outputs.find((output) => output.format === "tables_xlsx");
  const manifest = outputs.find((output) => output.format === "tables_json");
  const toCheck = tables.filter((table) => table.quality.status === "warn").length;

  return (
    <section className="tables">
      <div className="tables-head">
        <h3>
          Tables{" "}
          <span className="muted">
            ({tables.length}
            {toCheck ? `, ${toCheck} to check` : ""})
          </span>
        </h3>
        <div className="viewer-actions">
          {workbook && (
            <a className="btn" href={workbook.url} download={workbook.filename}>
              All tables (Excel)
            </a>
          )}
          {manifest && (
            <a className="btn ghost" href={manifest.url} download={manifest.filename}>
              Metadata (JSON)
            </a>
          )}
        </div>
      </div>
      <ul className="table-list">
        {tables.map((table) => {
          const expanded = open === table.table_id;
          return (
            <li key={table.table_id} className={`table-item ${table.quality.status === "warn" ? "table-warn" : ""}`}>
              <button
                type="button"
                className="table-row"
                aria-expanded={expanded}
                onClick={() => setOpen(expanded ? null : table.table_id)}
              >
                <span className="table-index">{table.index}</span>
                <span className="table-name">{table.title ?? table.caption ?? `Table ${table.index}`}</span>
                <span className="muted small">
                  {[where(table), `${table.num_rows} × ${table.num_cols}`].filter(Boolean).join(" · ")}
                </span>
                {table.quality.status === "warn" && <span className="tag tag-warn">Check</span>}
                <span className="chevron">{expanded ? "▴" : "▾"}</span>
              </button>
              {expanded && <TableDetail table={table} />}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function TableDetail({ table }: { table: TableSummary }) {
  const facts: [string, string | null][] = [
    ["Table ID", table.table_id],
    ["Location", where(table) || null],
    ["Title", table.title],
    ["Caption", table.caption],
    ["Section", table.section],
    ["Units", table.units],
    ["Read from", readFrom(table)],
    ["Continues from", table.continues_from],
    ["Continues on", table.continues_to],
  ];
  return (
    <div className="table-detail">
      {table.quality.reasons.length > 0 && <div className="notice notice-warn">{table.quality.reasons.join(" · ")}</div>}
      <div className="table-detail-grid">
        <dl>
          {facts
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label} className="fact">
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
        {table.files.image && (
          <img className="table-image" src={table.files.image} alt={`Table ${table.index} as it appears on the page`} />
        )}
      </div>
      {table.preview.length > 0 && (
        <div className="table-preview">
          <table>
            <tbody>
              {table.preview.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (r < table.header_rows ? <th key={c}>{cell}</th> : <td key={c}>{cell}</td>))}
                </tr>
              ))}
            </tbody>
          </table>
          {table.num_rows > table.preview.length && (
            <p className="muted small">
              First {table.preview.length} of {table.num_rows} rows.
            </p>
          )}
        </div>
      )}
      <div className="viewer-actions">
        {table.files.csv && (
          <a className="btn" href={table.files.csv} download>
            CSV
          </a>
        )}
        {table.files.image && (
          <a className="btn ghost" href={table.files.image} download>
            Image
          </a>
        )}
      </div>
    </div>
  );
}
