import { useMemo, useState } from "react";
import type { Catalog, FormatConfig, FormatSpec } from "../types";
import { FieldForm, countChanges } from "./FieldForm";

interface Props {
  catalog: Catalog;
  formats: Record<string, FormatConfig>;
  onChange: (formats: Record<string, FormatConfig>) => void;
}

function changes(config: FormatConfig | undefined): number {
  if (!config) return 0;
  return (
    (config.pipeline ? 1 : 0) +
    (config.backend ? 1 : 0) +
    countChanges(config.pipeline_options ?? {}) +
    countChanges(config.backend_options ?? {})
  );
}

function clean(config: FormatConfig): FormatConfig | undefined {
  const result: FormatConfig = {};
  if (config.pipeline) result.pipeline = config.pipeline;
  if (config.backend) result.backend = config.backend;
  if (config.pipeline_options && Object.keys(config.pipeline_options).length) result.pipeline_options = config.pipeline_options;
  if (config.backend_options && Object.keys(config.backend_options).length) result.backend_options = config.backend_options;
  return Object.keys(result).length ? result : undefined;
}

export function FormatsPanel({ catalog, formats, onChange }: Props) {
  const [selected, setSelected] = useState("pdf");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [copyTarget, setCopyTarget] = useState("");

  const visibleFormats = useMemo(
    () =>
      catalog.formats.filter(
        (fmt) =>
          !search ||
          fmt.id.includes(search.toLowerCase()) ||
          fmt.extensions.some((ext) => ext.toLowerCase().includes(search.toLowerCase())),
      ),
    [catalog.formats, search],
  );

  const spec = catalog.formats.find((fmt) => fmt.id === selected) ?? catalog.formats[0];
  const config = formats[spec.id] ?? {};
  const pipelineId = config.pipeline ?? spec.default_pipeline;
  const backendId = config.backend ?? spec.default_backend;
  const pipeline = catalog.pipelines[pipelineId];
  const backend = catalog.backends[backendId];

  const update = (fmt: string, next: FormatConfig) => {
    const result = { ...formats };
    const cleaned = clean(next);
    if (cleaned) result[fmt] = cleaned;
    else delete result[fmt];
    onChange(result);
  };

  const copyTargets = catalog.formats.filter(
    (fmt: FormatSpec) => fmt.id !== spec.id && fmt.pipelines.includes(pipelineId),
  );

  return (
    <div className="formats">
      <aside className="format-list">
        <input type="search" placeholder="Find a format or extension" value={search} onChange={(e) => setSearch(e.target.value)} />
        <ul>
          {visibleFormats.map((fmt) => {
            const count = changes(formats[fmt.id]);
            return (
              <li key={fmt.id}>
                <button type="button" className={fmt.id === spec.id ? "active" : ""} onClick={() => setSelected(fmt.id)}>
                  <span>{fmt.id}</span>
                  {count > 0 && <span className="badge">{count}</span>}
                  <span className="muted small ext">{fmt.extensions.slice(0, 4).join(" ")}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <section className="format-detail">
        <header className="format-head">
          <div>
            <h2>{spec.id}</h2>
            <p className="muted small">
              Extensions: {spec.extensions.join(", ") || "-"} · MIME: {spec.mime_types.join(", ") || "-"}
            </p>
          </div>
          <div className="row">
            {copyTargets.length > 0 && (
              <>
                <select value={copyTarget} onChange={(e) => setCopyTarget(e.target.value)}>
                  <option value="">Copy these options to…</option>
                  {copyTargets.map((fmt) => (
                    <option key={fmt.id} value={fmt.id}>
                      {fmt.id}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={!copyTarget}
                  onClick={() => {
                    const target = catalog.formats.find((fmt) => fmt.id === copyTarget);
                    if (!target) return;
                    // Backends differ between formats; copy only the pipeline part.
                    update(target.id, { ...formats[target.id], pipeline: config.pipeline, pipeline_options: config.pipeline_options });
                    setCopyTarget("");
                  }}
                >
                  Copy
                </button>
              </>
            )}
            <button type="button" disabled={!formats[spec.id]} onClick={() => update(spec.id, {})}>
              Reset {spec.id}
            </button>
          </div>
        </header>

        <div className="card">
          <h3>Pipeline</h3>
          <select
            value={pipelineId}
            onChange={(e) =>
              update(spec.id, {
                ...config,
                pipeline: e.target.value === spec.default_pipeline ? undefined : e.target.value,
                pipeline_options: {},
              })
            }
            disabled={spec.pipelines.length < 2}
          >
            {spec.pipelines.map((id) => (
              <option key={id} value={id}>
                {catalog.pipelines[id].label}
                {id === spec.default_pipeline ? " (default)" : ""}
              </option>
            ))}
          </select>
          <p className="help">{pipeline.description}</p>
          <input
            type="search"
            className="filter"
            placeholder="Filter options (name or description)"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <FieldForm
            fields={pipeline.fields}
            value={config.pipeline_options ?? {}}
            filter={filter}
            onChange={(next) => update(spec.id, { ...config, pipeline_options: next })}
          />
        </div>

        <div className="card">
          <h3>Backend (parser)</h3>
          <select
            value={backendId}
            disabled={spec.backends.length < 2}
            onChange={(e) =>
              update(spec.id, {
                ...config,
                backend: e.target.value === spec.default_backend ? undefined : e.target.value,
                backend_options: {},
              })
            }
          >
            {spec.backends.map((id) => (
              <option key={id} value={id}>
                {catalog.backends[id].label}
                {id === spec.default_backend ? " (default)" : ""}
              </option>
            ))}
          </select>
          {backend.fields ? (
            <FieldForm
              fields={backend.fields}
              value={config.backend_options ?? {}}
              filter={filter}
              onChange={(next) => update(spec.id, { ...config, backend_options: next })}
            />
          ) : (
            <p className="muted small">This backend has no options.</p>
          )}
        </div>
      </section>
    </div>
  );
}
