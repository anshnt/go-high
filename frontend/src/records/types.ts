// The record contract. Mirrors docs/adr/0002-record-engine.md; the API client must return exactly these shapes.
// Pure types only, so every module (and node) can import this file for free.

export type FieldType =
  | "text"
  | "long_text"
  | "number"
  | "money"
  | "date"
  | "datetime"
  | "boolean"
  | "select"
  | "multi_select"
  | "email"
  | "phone"
  | "url"
  | "user"
  | "record"
  | "formula"
  | "rollup"
  | "stage";

/** Color names are theme tokens, never hex, so dark mode keeps working (see fields/tone.ts). */
export type ColorName = "gray" | "blue" | "green" | "amber" | "orange" | "red" | "pink" | "purple" | "indigo" | "teal";

export type Choice = { id: string; label: string; color?: ColorName; /** stage only, 0 to 1 */ probability?: number };

export type FieldOptions = {
  /** select, multi_select, stage */
  choices?: Choice[];
  /** money: default currency (ISO 4217) */
  currency?: string;
  /** record: key of the linked object */
  object?: string;
  /** formula, rollup: the type of the computed value */
  result?: FieldType;
};

export type FieldRules = {
  required?: boolean;
  min?: number;
  max?: number;
  max_length?: number;
  /** system columns such as created_at */
  read_only?: boolean;
};

export type FieldDef = {
  key: string;
  label: string;
  type: FieldType;
  options: FieldOptions;
  rules: FieldRules;
  is_system: boolean;
  position: number;
  archived: boolean;
};

export type ObjectDef = {
  key: string;
  singular: string;
  plural: string;
  /** a name from records/paths.ts */
  icon: string;
  is_system: boolean;
  /** the fields that make up a record's name (a contact's first and last name); the name itself is `display_name` */
  primary_fields: string[];
};

/** A kind of link between two objects ("contact works at company"); `label` reads from `from`, `inverse_label` from `to`. */
export type LinkType = { from: string; to: string; label: string; inverse_label: string };

export type Tag = { id: string; name: string; color: ColorName };
export type UserRef = { id: string; name: string; email?: string };

export type Money = { amount: number; currency: string };

export type RecordRow = {
  id: string;
  object: string;
  display_name: string;
  values: Record<string, unknown>;
  owner_id: string | null;
  created_at: string;
  updated_at: string;
  tags: Tag[];
};

// ---- Filter AST (ADR 0002 "Filter language") ----

export type Op =
  | "is"
  | "is_not"
  | "contains"
  | "starts_with"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "between"
  | "is_empty"
  | "is_not_empty"
  | "within_last"
  | "older_than"
  | "in"
  | "not_in";

/**
 * Value shapes: text string; number; money {amount, currency}; date "YYYY-MM-DD"; datetime ISO string;
 * boolean; select, stage, user, record: the id; between: [low, high] (inclusive); in and not_in: array of ids;
 * within_last and older_than: {days}; is_empty and is_not_empty: no value.
 */
export type FilterValue = unknown;

export type FilterCondition = { field: string; op: Op; value?: FilterValue };
export type FilterTag = { tag: string };
export type FilterGroup = { and: Filter[] } | { or: Filter[] };
export type Filter = FilterGroup | FilterCondition | FilterTag;

// ---- Lists ----

export type SortSpec = { field: string; dir: "asc" | "desc" };

export type Page<T> = {
  data: T[];
  next_cursor: string | null;
  /** Rows matching the whole query (not only this page). Optional: the UI shows "N+" without it. */
  total?: number;
};

export type QueryParams = {
  filter?: Filter | null;
  sort?: SortSpec[];
  /** full-text search */
  q?: string;
  limit?: number;
  cursor?: string | null;
};

export type SavedView = {
  id: string;
  object: string;
  name: string;
  filter: Filter | null;
  columns: string[];
  sort: SortSpec[];
  shared: boolean;
  /** who made it; shared views made by someone else are read-only */
  owner_id?: string | null;
};

export type TimelineEvent = {
  id: string;
  record_id: string;
  at: string;
  actor_id: string | null;
  type: "created" | "updated" | "tagged" | "untagged" | "linked" | "unlinked";
  /** updated */
  changes?: { field: string; from: unknown; to: unknown }[];
  /** tagged, untagged */
  tag?: Tag;
  /** linked, unlinked: the other record and the label as seen from this one ("works at") */
  link?: { label: string; object: string; id: string };
};

export type NewRecord = { values: Record<string, unknown>; owner_id?: string | null; tags?: string[] };
