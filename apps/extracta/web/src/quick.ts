// The simple settings on the main screen, mapped onto the full (sparse) request.
//
// They write into the same structure as the advanced editor, so both views
// always show the same state. OCR settings apply to PDF and image files.

import { PRESET, VARIANT } from "./components/FieldForm";
import type { Catalog, ConvertRequest, FieldSpec, FormatConfig, Overrides } from "./types";

const PAGED_FORMATS = ["pdf", "image"] as const;
const SARVAM = "SarvamOcrOptions";
const AUTO = "OcrAutoOptions";

export type Engine = "sarvam" | "auto" | "off" | "custom";

export interface Quick {
  outputs: string[];
  images: string;
  engine: Engine;
  language: string;
  scanned: boolean;
  tables: boolean;
  extractTables: boolean;
  /** Set when PDFs use a pipeline that the simple settings do not cover. */
  pipelineNote: string | null;
}

export const OUTPUT_LABELS: Record<string, string> = {
  md: "Markdown",
  html: "HTML",
  json: "JSON",
  text: "Plain text",
  html_split_page: "HTML side by side",
  yaml: "YAML",
  doctags: "DocTags",
  doclang: "DocLang XML",
  dclx: "DocLang archive",
  vtt: "Subtitles (VTT)",
  chunks: "Chunks (RAG)",
  latex: "LaTeX",
};
export const MAIN_OUTPUTS = ["md", "html", "json", "text"];

export const SARVAM_LANGUAGES: [string, string][] = [
  ["en-IN", "English"],
  ["hi-IN", "Hindi"],
  ["bn-IN", "Bengali"],
  ["ta-IN", "Tamil"],
  ["te-IN", "Telugu"],
  ["mr-IN", "Marathi"],
  ["gu-IN", "Gujarati"],
  ["kn-IN", "Kannada"],
  ["ml-IN", "Malayalam"],
  ["od-IN", "Odia"],
  ["pa-IN", "Punjabi"],
  ["as-IN", "Assamese"],
  ["ur-IN", "Urdu"],
  ["ne-IN", "Nepali"],
  ["sa-IN", "Sanskrit"],
  ["mai-IN", "Maithili"],
  ["kok-IN", "Konkani"],
  ["doi-IN", "Dogri"],
  ["ks-IN", "Kashmiri"],
  ["mni-IN", "Manipuri"],
  ["sat-IN", "Santali"],
  ["sd-IN", "Sindhi"],
  ["brx-IN", "Bodo"],
];

function field(fields: FieldSpec[], name: string): FieldSpec | undefined {
  return fields.find((item) => item.name === name);
}

function record(value: unknown): Overrides {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Overrides) : {};
}

function defaultOcrVariant(catalog: Catalog): string {
  return field(catalog.pipelines.standard.fields, "ocr_options")?.default_variant ?? AUTO;
}

export function readQuick(request: ConvertRequest, catalog: Catalog): Quick {
  const exportFields = catalog.general.export;
  const pdf = request.formats.pdf ?? {};
  const options = record(pdf.pipeline_options);
  const ocr = record(options.ocr_options);
  const variant = (ocr[VARIANT] as string | undefined) ?? (ocr[PRESET] ? "custom" : defaultOcrVariant(catalog));

  let engine: Engine = variant === SARVAM ? "sarvam" : variant === AUTO ? "auto" : "custom";
  if (options.do_ocr === false) engine = "off";

  const pipeline = pdf.pipeline ?? "standard";
  return {
    outputs: (request.export.to_formats as string[] | undefined) ?? (field(exportFields, "to_formats")?.default as string[]),
    images: (request.export.image_export_mode as string | undefined) ?? String(field(exportFields, "image_export_mode")?.default),
    engine,
    language: (Array.isArray(ocr.lang) ? (ocr.lang[0] as string) : undefined) ?? "en-IN",
    scanned: ocr.mode === "full_page",
    tables: options.do_table_structure !== false,
    extractTables: request.tables?.enabled === true,
    pipelineNote:
      pipeline === "standard" ? null : `PDFs use the "${catalog.pipelines[pipeline].label}" pipeline (Advanced settings).`,
  };
}

function updatePaged(request: ConvertRequest, change: (options: Overrides, ocr: Overrides) => void): ConvertRequest {
  const formats = { ...request.formats };
  for (const fmt of PAGED_FORMATS) {
    const config: FormatConfig = { ...(formats[fmt] ?? {}) };
    const options = { ...record(config.pipeline_options) };
    const ocr = { ...record(options.ocr_options) };
    change(options, ocr);
    if (Object.keys(ocr).length > 0) options.ocr_options = ocr;
    else delete options.ocr_options;
    if (Object.keys(options).length > 0) config.pipeline_options = options;
    else delete config.pipeline_options;
    if (Object.keys(config).length > 0) formats[fmt] = config;
    else delete formats[fmt];
  }
  return { ...request, formats };
}

export function writeQuick(request: ConvertRequest, catalog: Catalog, change: Partial<Quick>): ConvertRequest {
  let next = request;
  if (change.outputs) next = { ...next, export: { ...next.export, to_formats: change.outputs } };
  if (change.images) next = { ...next, export: { ...next.export, image_export_mode: change.images } };
  if (change.extractTables !== undefined) {
    const tables = { ...(next.tables ?? {}) };
    if (change.extractTables) tables.enabled = true;
    else delete tables.enabled;
    next = { ...next, tables };
  }

  if (change.engine) {
    const engine = change.engine;
    next = updatePaged(next, (options, ocr) => {
      if (engine === "off") {
        options.do_ocr = false;
        return;
      }
      delete options.do_ocr;
      const variant = engine === "sarvam" ? SARVAM : AUTO;
      const mode = ocr.mode;
      for (const key of Object.keys(ocr)) delete ocr[key];
      if (variant !== defaultOcrVariant(catalog)) ocr[VARIANT] = variant;
      if (mode !== undefined) ocr.mode = mode; // "scanned document" is valid for every engine
    });
  }
  if (change.language !== undefined) {
    const language = change.language;
    next = updatePaged(next, (_options, ocr) => {
      if (language === "en-IN") delete ocr.lang;
      else ocr.lang = [language];
    });
  }
  if (change.scanned !== undefined) {
    const scanned = change.scanned;
    next = updatePaged(next, (_options, ocr) => {
      if (scanned) ocr.mode = "full_page";
      else delete ocr.mode;
    });
  }
  if (change.tables !== undefined) {
    const tables = change.tables;
    next = updatePaged(next, (options) => {
      if (tables) delete options.do_table_structure;
      else options.do_table_structure = false;
    });
  }
  return next;
}
