// Mirrors extracta/options_schema.py, extracta/catalog.py and extracta/models.py.

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
  bundle_url: string | null;
  original_url: string | null;
  errors: { component: string | null; module: string | null; message: string }[];
}
