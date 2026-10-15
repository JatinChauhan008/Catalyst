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
  formats: Record<string, FormatConfig>;
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
  extraction: { method: string; ocr_engine: string | null; table_text: string | null };
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
