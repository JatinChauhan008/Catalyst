// Mirrors catalyst/options_schema.py, catalyst/catalog.py and catalyst/models.py.

export type FieldKind =
  | "bool"
  | "int"
  | "float"
  | "string"
  | "secret"
  | "enum"
  | "list"
  | "object"
  | "variant"
  | "json";

export interface PresetSpec {
  id: string;
  label: string;
  description: string | null;
  variant: string;
  values: Record<string, unknown>;
}

export interface VariantSpec {
  id: string;
  label: string;
  description: string | null;
  fields: FieldSpec[];
}

export interface FieldSpec {
  name: string;
  title: string;
  description: string | null;
  kind: FieldKind;
  nullable: boolean;
  default: unknown;
  has_default: boolean;
  default_is_null: boolean;
  unserializable_default: boolean;
  enum: unknown[] | null;
  item_kind: FieldKind | null;
  item_enum: unknown[] | null;
  constraints: Record<string, number>;
  examples: unknown[] | null;
  fields: FieldSpec[] | null;
  variants: VariantSpec[] | null;
  default_variant: string | null;
  presets: PresetSpec[] | null;
}

export interface FormatSpec {
  id: string;
  extensions: string[];
  mime_types: string[];
  pipelines: string[];
  default_pipeline: string;
  backends: string[];
  default_backend: string;
}

export interface PipelineSpec {
  id: string;
  label: string;
  description: string;
  fields: FieldSpec[];
}

export interface BackendSpec {
  id: string;
  label: string;
  fields: FieldSpec[] | null;
}

export interface Catalog {
  formats: FormatSpec[];
  pipelines: Record<string, PipelineSpec>;
  backends: Record<string, BackendSpec>;
  general: {
    settings: FieldSpec[];
    export: FieldSpec[];
    validation: FieldSpec[];
    envelope: FieldSpec[];
    tables: FieldSpec[];
    pictures: FieldSpec[];
    pages: FieldSpec[];
    dost: FieldSpec[];
  };
  server: {
    docling_version: string;
    sarvam_configured: boolean;
    max_upload_mb: number;
  };
}

/** Sparse form state: only the values the user changed. */
export type Overrides = Record<string, unknown>;

export interface FormatConfig {
  pipeline?: string;
  pipeline_options?: Overrides;
  backend?: string;
  backend_options?: Overrides;
}

export interface ConvertRequest {
  settings: Overrides;
  export: Overrides;
  validation: Overrides;
  envelope: Overrides;
  tables: Overrides;
  pages: Overrides;
  pictures: Overrides;
  dost: Overrides;
  formats: Record<string, FormatConfig>;
}

export interface DostIssue {
  severity: "info" | "warn" | "error";
  component: string;
  message: string;
  page: number | null;
}

export interface DostImage {
  filename: string;
  page: number | null;
  kind: "embedded" | "rendered";
  format: string;
  width_px: number;
  height_px: number;
  occurrences: number;
  caption: string | null;
}

export type SentenceProblemKind =
  | "not_translated"
  | "language_not_supported"
  | "translation_off"
  | "numbers_differ"
  | "language_assumed"
  | "retranslated"
  | "ocr_suspect";

/** One sentence without a translation, or with one to check. */
export interface SentenceProblem {
  row: number;
  page: number | null;
  original: string;
  translation: string;
  kind: SentenceProblemKind;
  reason: string;
  summary?: string;
  action: string | null;
  detail: string | null;
}

/** Tables as Markdown, sentences with English translations, images as files. */
export interface DostReport {
  complete: boolean;
  pages: number;
  scanned_pages: number[];
  ocr_engine: string | null;
  source_language: string | null;
  tables: { tables: number; html_tables: number; joined_parts: number; with_warnings: number };
  sentences: {
    sentences: number;
    by_status: Record<string, number>;
    numbers_differ: number;
    characters_sent: number;
    skipped_items: Record<string, number>;
  };
  images: {
    files: number;
    embedded: number;
    rendered: number;
    duplicates_skipped: number;
    too_small_skipped: number;
    page_scans_skipped: number;
    failed: number;
  };
  image_files: DostImage[];
  sentence_problems?: SentenceProblem[];
  issues: DostIssue[];
}

export interface ValidationCheck {
  id: string;
  status: "pass" | "warn" | "fail";
  message: string;
}

export interface OutputItem {
  format: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  url: string;
  content: string | null;
}

export interface TableRegion {
  page: number;
  bbox: [number, number, number, number];
  bbox_normalized: [number, number, number, number];
  page_width: number;
  page_height: number;
  units: "pt" | "cell";
}

export interface TableSummary {
  table_id: string;
  index: number;
  page: number | null;
  regions: TableRegion[];
  caption: string | null;
  title: string | null;
  section: string | null;
  units: string | null;
  footnotes: string[];
  num_rows: number;
  num_cols: number;
  header_rows: number;
  empty_cells_share: number;
  extraction: {
    method: string;
    ocr_engine: string | null;
    table_text: string | null;
    structure: "docling" | "sarvam";
  };
  quality: { status: "ok" | "warn"; reasons: string[] };
  continues_from: string | null;
  continues_to: string | null;
  joined_from: string[];
  files: Record<string, string>;
  preview: string[][];
}

export interface PictureSummary {
  picture_id: string;
  index: number;
  page: number | null;
  regions: TableRegion[];
  caption: string | null;
  section: string | null;
  width_px: number;
  height_px: number;
  files: Record<string, string>;
}

export interface PageLink {
  page: number;
  url: string;
  heading: string | null;
}

/** Sarvam bills Document Digitization per page; the price is the one in force when the job ran. */
export interface SarvamCost {
  jobs: number;
  pages: number;
  price_per_page: number;
  currency: string;
  cost: number;
}

/** Sarvam bills translation per character sent. */
export interface TranslationCost {
  characters: number;
  price_per_10k_characters: number;
  currency: string;
  cost: number;
}

export interface Envelope {
  schema_version: string;
  job_id: string;
  created_at: string;
  status: "success" | "partial_success" | "failure" | "rejected";
  source: { filename: string; size_bytes: number; sha256: string; detected_format: string | null };
  processing: {
    pipeline: string | null;
    backend: string | null;
    ocr_engine: string | null;
    sarvam?: SarvamCost | null;
    sarvam_translation?: TranslationCost | null;
    ocr_language_from_font?: string | null;
    docling_version: string;
    duration_seconds: number;
  } | null;
  stats: {
    pages: number;
    characters: number;
    text_items: number;
    headings: number;
    tables: number;
    pictures: number;
    empty_pages: number[];
  } | null;
  validation: { passed: boolean; checks: ValidationCheck[] } | null;
  outputs: OutputItem[];
  tables?: TableSummary[];
  pictures?: PictureSummary[];
  pages?: PageLink[];
  dost?: DostReport | null;
  bundle_url: string | null;
  original_url: string | null;
  errors: { component: string | null; module: string | null; message: string }[];
}

export interface JobSummary {
  job_id: string;
  created_at: string;
  status: Envelope["status"];
  filename: string;
  size_bytes: number;
  detected_format: string | null;
  pages: number;
  tables: number;
  pictures: number;
  ocr_engine: string | null;
  duration_seconds: number | null;
  sarvam?: SarvamCost | null;
}
