// What a node does, in a line: the text on its card, in the trace and in the diff. Pure, with names looked up through
// the context the screen passes in, so node tests can check the words.
import { eventLabel, offsetOf, offsetText, type Trigger, type WfNode } from "./graph.ts";

export type Names = {
  user?: (id: string) => string | undefined;
  tag?: (idOrName: string) => string | undefined;
  channel?: (id: string) => string | undefined;
  stage?: (id: string) => string | undefined;
  field?: (key: string) => string | undefined;
  form?: (id: string) => string | undefined;
  calendar?: (id: string) => string | undefined;
  /** a filter in words (records/filter.ts filterToText, with the screen's fields) */
  filter?: (ast: Record<string, unknown>) => string;
  action?: (key: string) => string | undefined;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const clip = (s: string, n = 60) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const str = (v: unknown) => (typeof v === "string" ? v : "");

export const TYPE_LABEL: Record<string, string> = {
  action: "Action",
  wait: "Wait",
  condition: "If / else",
  split: "A/B split",
  goal: "Goal",
  subflow: "Sub-workflow",
  end: "End",
};

/** What each kind of step does, for the panel (the catalog's own words are written for developers). */
export const TYPE_HELP: Record<string, string> = {
  wait: "Holds the run for a while, until a date on the record, or until something happens.",
  condition: "Checks the record: records that match go down Yes, the rest down No.",
  split: "Sends runs down paths by percentage, for an A/B test. A run always takes the same path.",
  goal: "A run jumps here the moment its condition holds, wherever it is in the workflow.",
  subflow: "Runs another workflow. Not built yet: it can be saved, not published.",
  end: "Ends the run.",
};

/** What an action does, in the panel's words; the catalog's description is the fallback for actions added later. */
export const ACTION_HELP: Record<string, string> = {
  "record.update": "Sets fields of the record. An empty value clears the field. Text may hold {{field_key}}.",
  "tag.add": "Adds a tag to the record.",
  "tag.remove": "Takes a tag off the record.",
  "task.create": "Creates a task on the record, for its owner or a person you pick. Text may hold {{field_key}}.",
  "webhook.send": "Posts what you map to an https address, signed with the workflow's secret.",
};
/** Actions that only work on one kind of record; the server refuses them on the others. */
export const ONLY_FOR: Record<string, string> = { "deal.move_stage": "deal", "message.send": "contact" };

/** The card's title: its own label, else what kind of step it is. */
export function title(node: WfNode, names: Names = {}): string {
  if (node.label) return node.label;
  if (node.type === "action") return (node.action && (names.action?.(node.action) ?? node.action)) || "Action";
  return TYPE_LABEL[node.type] ?? node.type;
}

const person = (v: unknown, names: Names) => (v === "owner" ? "the record's owner" : (names.user?.(str(v)) ?? (v ? "a person who is no longer here" : "nobody yet")));

/** The card's line: what it is set to do. Empty settings say what is missing instead. */
export function summary(node: WfNode, names: Names = {}): string {
  const line = describeStep(node, names);
  return line.charAt(0).toUpperCase() + line.slice(1);
}

function describeStep(node: WfNode, names: Names): string {
  const c = node.config ?? {};
  switch (node.type) {
    case "action":
      return actionSummary(node.action ?? "", c, names);
    case "wait": {
      if (c.duration) return `For ${offsetText(c.duration)}`;
      const until = c.until_field as { field?: string; offset?: unknown; at?: string } | undefined;
      if (until) {
        const o = offsetOf(until.offset);
        const when = o ? `${offsetText(until.offset)} ${o.count < 0 ? "before" : "after"} ` : "";
        return `Until ${when}${names.field?.(str(until.field)) ?? (until.field || "a date field")}${until.at && until.at !== "09:00" ? ` at ${until.at}` : ""}`;
      }
      const ev = c.event as { event?: string; timeout?: unknown } | undefined;
      if (ev) return `Until ${ev.event ? eventLabel(ev.event).toLowerCase() : "an event"}, at most ${offsetText(ev.timeout) || "…"}`;
      return "Set how long to wait";
    }
    case "condition":
    case "goal": {
      const f = c.filter as Record<string, unknown> | undefined;
      const text = f && Object.keys(f).length ? (names.filter?.(f) ?? "A condition") : "";
      if (node.type === "condition") return text ? `If ${text}` : "Set the condition";
      return text ? `When ${text}${c.otherwise === "end" ? "; reaching it otherwise ends the run" : ""}` : "Set when the goal is met";
    }
    case "split": {
      const paths = Array.isArray(c.paths) ? (c.paths as { name?: string; percent?: number }[]) : [];
      return `Paths ${paths.map((p) => `${p.name} ${p.percent ?? 0}%`).join(", ")}`;
    }
    case "subflow":
      return "Sub-workflows are not built yet: it can be saved, not published";
    case "end":
      return "The run ends here";
    default:
      return "";
  }
}

function actionSummary(key: string, c: Record<string, unknown>, names: Names): string {
  switch (key) {
    case "record.update": {
      const keys = Object.keys((c.values as object) ?? {});
      return keys.length ? `Set ${keys.map((k) => names.field?.(k) ?? k).join(", ")}` : "Choose the fields to set";
    }
    case "tag.add":
    case "tag.remove":
      if (!c.tag) return "Choose a tag";
      return `${key === "tag.add" ? "Add" : "Remove"} ${names.tag?.(str(c.tag)) ? `"${names.tag(str(c.tag))}"` : UUID.test(str(c.tag)) ? "a tag that no longer exists" : `"${str(c.tag)}"`}`;
    case "owner.assign": {
      const rr = Array.isArray(c.round_robin) ? c.round_robin : null;
      if (rr) return `Round robin over ${rr.length} ${rr.length === 1 ? "person" : "people"}`;
      return c.user_id ? `To ${person(c.user_id, names)}` : "Choose who owns it";
    }
    case "deal.move_stage":
      return c.stage_id ? `To ${names.stage?.(str(c.stage_id)) ?? "a stage that is no longer here"}` : "Choose a stage";
    case "task.create":
      return c.title ? `"${clip(str(c.title), 48)}"${c.due ? `, due in ${offsetText(c.due)}` : ""}, for ${person(c.assignee ?? "owner", names)}` : "Give the task a title";
    case "message.send": {
      const ch = c.channel_id ? (names.channel?.(str(c.channel_id)) ?? "a channel that is no longer here") : "";
      if (!ch && !c.body) return "Choose a channel and write the message";
      return `${ch || "No channel yet"}: ${c.body ? `"${clip(str(c.subject) || str(c.body), 48)}"` : "no message yet"}`;
    }
    case "notify.user":
      return c.title ? `${person(c.user_id, names)}: "${clip(str(c.title), 48)}"` : "Write the notification";
    case "webhook.send": {
      try {
        return c.url ? `POST to ${new URL(str(c.url)).host}` : "Set the address";
      } catch {
        return `POST to ${clip(str(c.url), 40)}`;
      }
    }
    default:
      return "";
  }
}

/** The trigger in a line: "Form submitted (Get a quote), when Tagged VIP". */
export function triggerSummary(t: Trigger, names: Names = {}): string {
  const data = t.data ?? {};
  const bits: string[] = [];
  if (data.form_id) bits.push(names.form?.(String(data.form_id)) ?? "a form");
  if (data.calendar_id) bits.push(names.calendar?.(String(data.calendar_id)) ?? "a calendar");
  if (data.to_stage_id) bits.push(`to ${names.stage?.(String(data.to_stage_id)) ?? "a stage"}`);
  if (data.tag_id) bits.push(names.tag?.(String(data.tag_id)) ?? "a tag");
  const other = Object.keys(data).filter((k) => !["form_id", "calendar_id", "to_stage_id", "tag_id"].includes(k));
  if (other.length) bits.push(other.map((k) => `${k.replace(/_/g, " ")} is ${String(data[k])}`).join(", "));
  const filter = t.filter && Object.keys(t.filter).length ? (names.filter?.(t.filter) ?? "a condition holds") : "";
  return `${eventLabel(t.event)}${bits.length ? ` (${bits.join(", ")})` : ""}${filter ? `, when ${filter}` : ""}`;
}

/** A step's branch in words: "Yes", "No", "If the event happens", "a (50%)". */
export function branchLabel(node: WfNode, name: string): string {
  if (node.type === "condition") return name === "yes" ? "Yes" : "No";
  if (node.type === "wait") return name === "event" ? "When it happens" : "If it times out";
  if (node.type === "split") {
    const p = (node.config.paths as { name: string; percent: number }[] | undefined)?.find((x) => x.name === name);
    return `Path ${name}${p ? ` (${p.percent}%)` : ""}`;
  }
  return name;
}
