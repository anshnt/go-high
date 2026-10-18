// The shape of a form definition (see backend/app/forms/definition.py) and of what the public API answers.
export type FieldType =
  | "short_text"
  | "long_text"
  | "email"
  | "phone"
  | "number"
  | "select"
  | "multi_select"
  | "checkbox"
  | "date"
  | "rating"
  | "yes_no"
  | "hidden"
  | "consent"
  | "heading"
  | "paragraph";

export type Option = { id: string; label: string };
export type Validation = { min_length?: number; max_length?: number; min?: number; max?: number; integer?: boolean; min_items?: number; max_items?: number; region?: string };

export type Field = {
  key: string;
  type: FieldType;
  label: string;
  help?: string;
  placeholder?: string;
  required?: boolean;
  options?: Option[];
  validation?: Validation;
  maps_to?: string;
  param?: string;
  quiz?: { correct: unknown; points: number };
};

export type Step = { key: string; title: string; description?: string; fields: Field[] };

export type Op = "is" | "is_not" | "contains" | "in" | "not_in" | "gt" | "gte" | "lt" | "lte" | "is_empty" | "is_not_empty";
export type Condition = { and: Condition[] } | { or: Condition[] } | { not: Condition } | { field: string; op: Op; value?: unknown };
export type Rule = { id?: string; when: Condition; do: "show" | "hide" | "jump" | "end"; target?: string; from?: string };
export type Band = { min: number; title: string; message: string };

export type Definition = {
  title?: string;
  description?: string;
  submit_label?: string;
  steps: Step[];
  logic?: Rule[];
  quiz?: { pass_mark?: number; bands?: Band[] };
};

export type Answers = Record<string, unknown>;
export type Flow = { steps: { key: string; fields: string[] }[]; ended: boolean; answers: Answers };

export type QuizResult = {
  score: number;
  max_score: number;
  percent: number;
  passed: boolean | null;
  band: { title: string; message: string } | null;
  review: Record<string, boolean>;
};

export type Published = {
  key: string;
  kind: "form" | "survey" | "quiz";
  name: string;
  version: number;
  definition: Definition;
  settings: { success_message: string; redirect_url: string | null };
};

export type Done = { id: string; status: "complete"; message: string; redirect_url: string | null; result: QuizResult | null };
