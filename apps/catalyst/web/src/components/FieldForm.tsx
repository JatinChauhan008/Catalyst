// A form generated from the server's FieldSpec tree.
//
// State is sparse: `value` holds only what the user changed. A field whose
// value equals its default is removed again, so the request sent to the
// server stays minimal and defaults that the UI cannot show (secrets,
// callables) stay untouched on the server.

import { useEffect, useState } from "react";
import type { FieldSpec, Overrides, VariantSpec } from "../types";

export const VARIANT = "__variant__";
export const PRESET = "__preset__";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function withoutMarkers(value: Record<string, unknown>): Overrides {
  const { [VARIANT]: _variant, [PRESET]: _preset, ...rest } = value;
  return rest;
}

/** Use a preset's values as the defaults of a field tree. */
function withDefaults(fields: FieldSpec[], values: Record<string, unknown>): FieldSpec[] {
  return fields.map((field) => {
    if (!(field.name in values)) return field;
    const value = values[field.name];
    if (field.kind === "object" && field.fields && isRecord(value)) {
      return { ...field, fields: withDefaults(field.fields, value) };
    }
    return { ...field, default: value, unserializable_default: false };
  });
}

export function fieldMatches(field: FieldSpec, query: string): boolean {
  const q = query.toLowerCase();
  if (
    field.name.toLowerCase().includes(q) ||
    field.title.toLowerCase().includes(q) ||
    (field.description ?? "").toLowerCase().includes(q)
  ) {
    return true;
  }
  if (field.fields?.some((child) => fieldMatches(child, q))) return true;
  return field.variants?.some((variant) => variant.fields.some((child) => fieldMatches(child, q))) ?? false;
}

/** Count changed leaf values, for the "n changed" badges. */
export function countChanges(value: unknown): number {
  if (!isRecord(value)) return value === undefined ? 0 : 1;
  let count = VARIANT in value || PRESET in value ? 1 : 0;
  for (const [key, child] of Object.entries(value)) {
    if (key !== VARIANT && key !== PRESET) count += countChanges(child);
  }
  return count;
}

interface FormProps {
  fields: FieldSpec[];
  value: Overrides;
  onChange: (value: Overrides) => void;
  filter?: string;
}

export function FieldForm({ fields, value, onChange, filter = "" }: FormProps) {
  const visible = filter ? fields.filter((field) => fieldMatches(field, filter)) : fields;
  const setField = (name: string, next: unknown) => {
    const updated = { ...value };
    if (next === undefined) delete updated[name];
    else updated[name] = next;
    onChange(updated);
  };
  if (visible.length === 0) return <p className="muted small">No options match the filter.</p>;
  return (
    <div className="fields">
      {visible.map((field) => (
        <FieldRow
          key={field.name}
          field={field}
          value={value[field.name]}
          onChange={(next) => setField(field.name, next)}
          filter={filter}
        />
      ))}
    </div>
  );
}

interface RowProps {
  field: FieldSpec;
  value: unknown;
  onChange: (value: unknown) => void;
  filter: string;
}

function FieldRow({ field, value, onChange, filter }: RowProps) {
  const changed = value !== undefined;
  const nested = field.kind === "object" || field.kind === "variant";
  const header = (
    <div className="field-head">
      <span className="field-title">{field.title}</span>
      <code className="field-name">{field.name}</code>
      {changed && (
        <button type="button" className="link" title="Back to the default" onClick={() => onChange(undefined)}>
          reset
        </button>
      )}
    </div>
  );

  if (nested) {
    return (
      <details className={`field nested ${changed ? "changed" : ""}`} open={changed || Boolean(filter)}>
        <summary>
          {header}
          {field.description && <p className="help">{field.description}</p>}
        </summary>
        {field.kind === "object" ? (
          <ObjectField field={field} value={value} onChange={onChange} filter={filter} />
        ) : (
          <VariantField field={field} value={value} onChange={onChange} filter={filter} />
        )}
      </details>
    );
  }

  return (
    <div className={`field ${changed ? "changed" : ""}`}>
      {header}
      <ScalarField field={field} value={value} onChange={onChange} />
      {field.description && <p className="help">{field.description}</p>}
    </div>
  );
}

function NullToggle({ enabled, onToggle, label }: { enabled: boolean; onToggle: (on: boolean) => void; label: string }) {
  return (
    <label className="inline">
      <input type="checkbox" checked={enabled} onChange={(event) => onToggle(event.target.checked)} /> {label}
    </label>
  );
}

function ObjectField({ field, value, onChange, filter }: RowProps) {
  const enabled = value === undefined ? !field.default_is_null : value !== null;
  const children = isRecord(value) ? value : {};
  return (
    <div className="nested-body">
      {field.nullable && (
        <NullToggle
          enabled={enabled}
          label="Set this option"
          onToggle={(on) => onChange(on ? (field.default_is_null ? {} : undefined) : field.default_is_null ? undefined : null)}
        />
      )}
      {enabled && field.fields && (
        <FieldForm
          fields={field.fields}
          value={children}
          filter={filter}
          onChange={(next) =>
            onChange(Object.keys(next).length > 0 ? next : field.default_is_null ? {} : undefined)
          }
        />
      )}
    </div>
  );
}

function VariantField({ field, value, onChange, filter }: RowProps) {
  const variants = field.variants ?? [];
  const presets = field.presets ?? [];
  const record = isRecord(value) ? value : undefined;
  const presetId = typeof record?.[PRESET] === "string" ? (record[PRESET] as string) : undefined;
  const preset = presets.find((item) => item.id === presetId);
  const variantId =
    (typeof record?.[VARIANT] === "string" ? (record[VARIANT] as string) : undefined) ??
    preset?.variant ??
    field.default_variant ??
    variants[0]?.id;
  const variant: VariantSpec | undefined = variants.find((item) => item.id === variantId);
  const enabled = value === undefined ? !field.default_is_null : value !== null;
  const children = record ? withoutMarkers(record) : {};
  const fields = variant ? (preset ? withDefaults(variant.fields, preset.values) : variant.fields) : [];

  const markers = (): Overrides => {
    if (presetId) return { [PRESET]: presetId };
    if (field.default_is_null || variantId !== field.default_variant) return { [VARIANT]: variantId };
    return {};
  };

  return (
    <div className="nested-body">
      {field.nullable && (
        <NullToggle
          enabled={enabled}
          label="Set this option"
          onToggle={(on) =>
            onChange(on ? (field.default_is_null ? { [VARIANT]: variantId } : undefined) : field.default_is_null ? undefined : null)
          }
        />
      )}
      {enabled && (
        <>
          <div className="variant-pickers">
            {presets.length > 0 && (
              <label>
                <span className="small muted">Preset</span>
                <select
                  value={presetId ?? ""}
                  onChange={(event) => onChange(event.target.value ? { [PRESET]: event.target.value } : undefined)}
                >
                  <option value="">(none: use the fields below)</option>
                  {presets.map((item) => (
                    <option key={item.id} value={item.id} title={item.description ?? ""}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {variants.length > 1 && (
              <label>
                <span className="small muted">Type</span>
                <select
                  value={variantId}
                  disabled={Boolean(presetId)}
                  onChange={(event) => {
                    const id = event.target.value;
                    onChange(id === field.default_variant && !field.default_is_null ? undefined : { [VARIANT]: id });
                  }}
                >
                  {variants.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                      {item.id === field.default_variant ? " (default)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {(preset?.description || variant?.description) && (
            <p className="help">{preset?.description ?? variant?.description}</p>
          )}
          <FieldForm
            fields={fields}
            value={children}
            filter={filter}
            onChange={(next) => {
              const merged = { ...markers(), ...next };
              onChange(Object.keys(merged).length > 0 ? merged : undefined);
            }}
          />
        </>
      )}
    </div>
  );
}

function ScalarField({ field, value, onChange }: Omit<RowProps, "filter">) {
  const current = value === undefined ? field.default : value;
  const commit = (next: unknown) => onChange(same(next, field.default) ? undefined : next);

  switch (field.kind) {
    case "bool":
      return (
        <label className="inline">
          <input type="checkbox" checked={Boolean(current)} onChange={(event) => commit(event.target.checked)} />
          {current ? "on" : "off"}
        </label>
      );
    case "int":
    case "float":
      return <NumberInput field={field} current={current} commit={commit} />;
    case "enum":
      return (
        <select
          value={current === null || current === undefined ? "" : String(current)}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") return commit(null);
            const option = (field.enum ?? []).find((item) => String(item) === raw);
            commit(option ?? raw);
          }}
        >
          {(field.nullable || current === null) && <option value="">(none)</option>}
          {(field.enum ?? []).map((item) => (
            <option key={String(item)} value={String(item)}>
              {String(item)}
            </option>
          ))}
        </select>
      );
    case "secret":
      return (
        <input
          type="password"
          autoComplete="off"
          placeholder="(not shown; leave empty to keep the default)"
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value)}
        />
      );
    case "list":
      return <ListInput field={field} current={current} commit={commit} />;
    case "string":
      return (
        <TextInput
          placeholder={field.nullable ? "(empty)" : ""}
          current={current === null || current === undefined ? "" : String(current)}
          commit={(text) => commit(text === "" && field.nullable ? null : text)}
        />
      );
    default:
      return <JsonInput field={field} value={value} onChange={onChange} />;
  }
}

/** A text input that commits on blur or Enter, so typing does not rebuild the form. */
function TextInput({ current, commit, placeholder }: { current: string; commit: (text: string) => void; placeholder?: string }) {
  const [draft, setDraft] = useState(current);
  useEffect(() => setDraft(current), [current]);
  return (
    <input
      type="text"
      value={draft}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => draft !== current && commit(draft)}
      onKeyDown={(event) => event.key === "Enter" && commit(draft)}
    />
  );
}

function NumberInput({ field, current, commit }: { field: FieldSpec; current: unknown; commit: (v: unknown) => void }) {
  const { ge, le, gt, lt } = field.constraints;
  const text = current === null || current === undefined ? "" : String(current);
  const [draft, setDraft] = useState(text);
  useEffect(() => setDraft(text), [text]);
  const apply = () => {
    if (draft.trim() === "") return commit(field.nullable ? null : field.default);
    const number = field.kind === "int" ? Number.parseInt(draft, 10) : Number.parseFloat(draft);
    if (Number.isNaN(number)) return setDraft(text);
    commit(number);
  };
  return (
    <input
      type="number"
      value={draft}
      step={field.kind === "int" ? 1 : "any"}
      min={ge ?? gt}
      max={le ?? lt}
      placeholder={field.nullable ? "(empty)" : ""}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={apply}
      onKeyDown={(event) => event.key === "Enter" && apply()}
    />
  );
}

function ListInput({ field, current, commit }: { field: FieldSpec; current: unknown; commit: (v: unknown) => void }) {
  const items = Array.isArray(current) ? current : [];
  if (field.item_enum) {
    return (
      <div className="checks">
        {field.item_enum.map((option) => {
          const checked = items.some((item) => same(item, option));
          return (
            <label key={String(option)} className="inline chip">
              <input
                type="checkbox"
                checked={checked}
                onChange={() =>
                  commit(checked ? items.filter((item) => !same(item, option)) : [...items, option])
                }
              />
              {String(option)}
            </label>
          );
        })}
        {field.nullable && current !== null && (
          <button type="button" className="link" onClick={() => commit(null)}>
            clear (none)
          </button>
        )}
      </div>
    );
  }
  const parse = (text: string): unknown => {
    if (text.trim() === "") return field.nullable && current === null ? null : [];
    const parts = text.split(",").map((part) => part.trim()).filter(Boolean);
    if (field.item_kind === "int") return parts.map((part) => Number.parseInt(part, 10));
    if (field.item_kind === "float") return parts.map((part) => Number.parseFloat(part));
    return parts;
  };
  return (
    <TextInput
      placeholder="comma-separated values"
      current={current === null || current === undefined ? "" : items.join(", ")}
      commit={(text) => commit(parse(text))}
    />
  );
}

function JsonInput({ field, value, onChange }: Omit<RowProps, "filter">) {
  const shown = value !== undefined ? value : field.unserializable_default ? undefined : field.default;
  const initial = shown === undefined ? "" : JSON.stringify(shown, null, 2);
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setDraft(initial), [initial]);
  const apply = () => {
    if (draft.trim() === "") {
      setError(null);
      return onChange(undefined);
    }
    try {
      const parsed = JSON.parse(draft);
      setError(null);
      onChange(same(parsed, field.default) && !field.unserializable_default ? undefined : parsed);
    } catch (exc) {
      setError(String(exc));
    }
  };
  return (
    <div>
      <textarea
        rows={Math.min(8, Math.max(2, draft.split("\n").length))}
        value={draft}
        spellCheck={false}
        placeholder={field.unserializable_default ? "The default is set in code. Leave empty to keep it." : "JSON value"}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={apply}
      />
      {error && <p className="error small">{error}</p>}
    </div>
  );
}
