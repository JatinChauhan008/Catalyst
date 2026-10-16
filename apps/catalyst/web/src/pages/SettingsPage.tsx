import { useState } from "react";
import { FieldForm } from "../components/FieldForm";
import { FormatsPanel } from "../components/FormatsPanel";
import type { Catalog, ConvertRequest, FieldSpec, Overrides } from "../types";

type Tab = "general" | "formats";

const GENERAL_SECTIONS: { key: keyof Catalog["general"] & keyof ConvertRequest; title: string; help: string }[] = [
  { key: "settings", title: "Input and limits", help: "Allowed formats, size and page limits, page range, cleanup." },
  { key: "export", title: "Outputs", help: "Output formats, image handling and chunking." },
  { key: "tables", title: "Table extraction", help: "Files and metadata for every table." },
  { key: "pictures", title: "Image extraction", help: "Every picture as its own file." },
  { key: "pages", title: "HTML per page", help: "One HTML file per page." },
  {
    key: "dost",
    title: "Tables, sentences and images",
    help: "Tables as Markdown, sentences with English translations as CSV, images as files.",
  },
  { key: "validation", title: "Validation", help: "Checks on the converted content and structure." },
  { key: "envelope", title: "Result envelope", help: "What the result keeps." },
];

export function SettingsPage({
  catalog,
  request,
  onChange,
  onReset,
}: {
  catalog: Catalog;
  request: ConvertRequest;
  onChange: (request: ConvertRequest) => void;
  onReset: () => void;
}) {
  const [tab, setTab] = useState<Tab>("general");
  return (
    <div className="page-wide">
      <header className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">
            Every Docling option. Changed options are highlighted, and the settings on the Convert page stay in sync.
          </p>
        </div>
        <button
          type="button"
          className="btn ghost"
          onClick={() => window.confirm("Reset all settings to the defaults?") && onReset()}
        >
          Reset all
        </button>
      </header>

      <div className="segmented page-tabs">
        <button type="button" className={tab === "general" ? "on" : ""} onClick={() => setTab("general")}>
          Limits, outputs and checks
        </button>
        <button type="button" className={tab === "formats" ? "on" : ""} onClick={() => setTab("formats")}>
          Per file type
        </button>
      </div>

      {tab === "general" && (
        <div className="settings-columns">
          {GENERAL_SECTIONS.map((section) => (
            <section className="card" key={section.key}>
              <h2 className="section-title">{section.title}</h2>
              <p className="help">{section.help}</p>
              <FieldForm
                fields={catalog.general[section.key] as FieldSpec[]}
                value={request[section.key] as Overrides}
                onChange={(next) => onChange({ ...request, [section.key]: next })}
              />
            </section>
          ))}
        </div>
      )}
      {tab === "formats" && (
        <FormatsPanel catalog={catalog} formats={request.formats} onChange={(formats) => onChange({ ...request, formats })} />
      )}
    </div>
  );
}
