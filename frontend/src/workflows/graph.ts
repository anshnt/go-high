// The workflow graph (backend/app/workflows/schema.py) and the edits the builder makes to it. Pure: no React, no
// Vite, so node tests import it as it is. The server validates every saved version; these functions only keep the
// shape the server expects (edges named as it names them, nothing orphaned), so an edit never produces a graph that
// is wrong for a reason the author cannot see.

export type Scalar = string | number | boolean | null;
export type NodeType = "action" | "wait" | "condition" | "split" | "goal" | "subflow" | "end";
export type WfNode = {
  type: NodeType;
  action?: string;
  config: Record<string, unknown>;
  next?: string | null;
  branches?: Record<string, string | null>;
  label?: string;
  ui?: Record<string, unknown>;
};
export type Trigger = { event: string; object?: string; filter?: Record<string, unknown>; data?: Record<string, Scalar> };
export type Graph = { trigger: Trigger; start: string | null; nodes: Record<string, WfNode> };

export const UNITS = ["minutes", "hours", "days", "weeks"] as const;
export type Unit = (typeof UNITS)[number];
export type Offset = Partial<Record<Unit, number>>;

/** Where a pointer to a node lives: the graph's start, a node's `next`, or one of its branches. */
export type Slot = { from: "start" } | { from: string; branch?: string };
export const slotKey = (s: Slot) => ("branch" in s && s.branch !== undefined ? `${s.from}:${s.branch}` : s.from);

/** How a node goes on, as the server decides it (schema.edges): `next`, these branch names, or not at all. */
export function exits(node: Pick<WfNode, "type" | "config">): { kind: "next" } | { kind: "branches"; names: string[] } | { kind: "none" } {
  switch (node.type) {
    case "end":
      return { kind: "none" };
    case "condition":
      return { kind: "branches", names: ["yes", "no"] };
    case "split": {
      const paths = Array.isArray(node.config.paths) ? (node.config.paths as { name?: unknown }[]) : [];
      return { kind: "branches", names: paths.map((p) => String(p.name ?? "")) };
    }
    case "wait":
      return node.config.event ? { kind: "branches", names: ["event", "timeout"] } : { kind: "next" };
    default:
      return { kind: "next" };
  }
}

/** The nodes a node leads to, in order (next, then its branches). */
export const targets = (node: WfNode): string[] => [node.next ?? null, ...Object.values(node.branches ?? {})].filter((t): t is string => !!t);

export function read(g: Graph, slot: Slot): string | null {
  if (slot.from === "start") return g.start;
  const node = g.nodes[slot.from];
  if (!node) return null;
  return "branch" in slot && slot.branch !== undefined ? (node.branches?.[slot.branch] ?? null) : (node.next ?? null);
}

function write(g: Graph, slot: Slot, target: string | null): Graph {
  if (slot.from === "start") return { ...g, start: target };
  const node = g.nodes[slot.from];
  if (!node) return g;
  const changed = "branch" in slot && slot.branch !== undefined ? { ...node, branches: { ...node.branches, [slot.branch]: target } } : { ...node, next: target };
  return { ...g, nodes: { ...g.nodes, [slot.from]: changed } };
}

/** What a run can reach: from the start and from every goal (runs jump to those). */
export function reachable(g: Graph): Set<string> {
  const seen = new Set<string>();
  const todo = [...(g.start ? [g.start] : []), ...Object.entries(g.nodes).filter(([, n]) => n.type === "goal").map(([id]) => id)];
  while (todo.length) {
    const id = todo.pop()!;
    if (seen.has(id) || !g.nodes[id]) continue;
    seen.add(id);
    todo.push(...targets(g.nodes[id]!));
  }
  return seen;
}

/** Drops the nodes nothing reaches any more, and edges to nodes that are gone. */
export function prune(g: Graph): Graph {
  const keep = reachable(g);
  const nodes: Record<string, WfNode> = {};
  const live = (t: string | null | undefined) => (t && keep.has(t) ? t : null);
  let changed = false;
  for (const [id, n] of Object.entries(g.nodes)) {
    if (!keep.has(id)) {
      changed = true;
      continue;
    }
    nodes[id] = relink(n, live);
    changed ||= nodes[id] !== n;
  }
  const start = live(g.start);
  return changed || start !== g.start ? { ...g, start, nodes } : g;
}

/** The node with each edge passed through `to`; the same object when no edge changes (the canvas redraws only the cards
 * whose node object changed, so an edit to one step must leave the others alone). */
function relink(n: WfNode, to: (t: string | null | undefined) => string | null): WfNode {
  const next = "next" in n ? to(n.next) : undefined;
  const branches = n.branches ? Object.fromEntries(Object.entries(n.branches).map(([b, t]) => [b, to(t)])) : undefined;
  const same = (!("next" in n) || next === (n.next ?? null)) && (!n.branches || Object.entries(n.branches).every(([b, t]) => branches![b] === (t ?? null)));
  if (same) return n;
  const out: WfNode = { ...n };
  if ("next" in n) out.next = next;
  if (branches) out.branches = branches;
  return out;
}

/** Branch names the server accepts: path names are ids, and no two alike. A split being renamed passes through names
 * that are neither (empty while typing, or the same as another path's); its branches must not be reshaped then, or
 * the steps down the path would be dropped. */
export const validBranches = (names: string[]) => names.every((n) => /^[a-z][a-z0-9_]{0,39}$/.test(n)) && new Set(names).size === names.length;

/** The ids that removing `id` would take away: itself, and what only it led to. */
export const removalImpact = (g: Graph, id: string): string[] => dropped(g, remove(g, id));

/** A node's id from a readable base: `message_send`, then `message_send_2`. */
export function newId(g: Graph, base: string): string {
  let stem = base.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^[^a-z]+/, "").slice(0, 36) || "step";
  stem = stem.replace(/_+$/, "") || "step";
  if (!(stem in g.nodes)) return stem;
  for (let i = 2; ; i++) if (!(`${stem}_${i}` in g.nodes)) return `${stem}_${i}`;
}

/** Edges for a node of this type and config, keeping what `old` led to where the names still match. A node that gains
 * branches sends its old `next` down the first; one that loses them goes on down its first branch. */
export function shape(node: WfNode, old: WfNode): WfNode {
  const ex = exits(node);
  const out: WfNode = { ...node };
  delete out.next;
  delete out.branches;
  const oldBranches = old.branches ?? null;
  if (ex.kind === "next") out.next = oldBranches ? (Object.values(oldBranches).find((t) => t) ?? null) : (old.next ?? null);
  if (ex.kind === "branches" && old.branches && !validBranches(ex.names)) {
    out.branches = old.branches; // keep the edges until the names are sound again
    return out;
  }
  if (ex.kind === "branches") {
    const names = ex.names;
    const oldNames = Object.keys(oldBranches ?? {});
    out.branches = Object.fromEntries(
      names.map((name, i) => {
        if (!oldBranches) return [name, i === 0 ? (old.next ?? null) : null];
        if (name in oldBranches) return [name, oldBranches[name] ?? null];
        const was = oldNames[i]; // a renamed path keeps what it led to
        return [name, was !== undefined && !names.includes(was) ? (oldBranches[was] ?? null) : null];
      }),
    );
  }
  return out;
}

/** The node ids `before` has and `after` does not: what an edit would take away. */
export const dropped = (before: Graph, after: Graph): string[] => Object.keys(before.nodes).filter((id) => !(id in after.nodes));

/** Puts a new node where `slot` points; what was there follows it (down its first branch, for a branching node). */
export function insert(g: Graph, slot: Slot, id: string, node: WfNode): Graph {
  const target = read(g, slot);
  const ex = exits(node);
  const placed: WfNode = { ...node };
  delete placed.next;
  delete placed.branches;
  if (ex.kind === "next") placed.next = target;
  if (ex.kind === "branches") placed.branches = Object.fromEntries(ex.names.map((n, i) => [n, i === 0 ? target : null]));
  const withNode = { ...g, nodes: { ...g.nodes, [id]: placed } };
  return prune(write(withNode, slot, id));
}

/** A goal stands on its own: runs jump to it when its condition becomes true. */
export const addGoal = (g: Graph, id: string, node: WfNode): Graph => ({ ...g, nodes: { ...g.nodes, [id]: { ...node, next: null } } });

/** Takes a node out: whatever led to it now leads where it went on (its first branch, for a branching node). */
export function remove(g: Graph, id: string): Graph {
  const node = g.nodes[id];
  if (!node) return g;
  let then = node.next ?? (node.branches ? (Object.values(node.branches)[0] ?? null) : null);
  if (then === id) then = null;
  const swap = (t: string | null | undefined) => (t === id ? then : (t ?? null));
  const nodes: Record<string, WfNode> = {};
  for (const [nid, n] of Object.entries(g.nodes)) {
    if (nid !== id) nodes[nid] = relink(n, swap);
  }
  return prune({ ...g, start: swap(g.start), nodes });
}

/** A node with new settings (type and config), its edges reshaped to match. */
export function update(g: Graph, id: string, patch: Partial<WfNode>): Graph {
  const old = g.nodes[id];
  if (!old) return g;
  const next = shape({ ...old, ...patch }, old);
  if (next.label === "") delete next.label;
  return prune({ ...g, nodes: { ...g.nodes, [id]: next } });
}

/** Points a slot at another node (a "go to"), or at nothing (end). */
export const connect = (g: Graph, slot: Slot, target: string | null): Graph => prune(write(g, slot, target));

/** Moves a node one place up or down its chain: swaps it with the node it follows (or the one that follows it). */
export function move(g: Graph, id: string, dir: "up" | "down"): Graph {
  const node = g.nodes[id];
  if (!node || node.type === "goal" || exits(node).kind !== "next") return g;
  if (dir === "down") {
    const after = node.next;
    if (!after || exits(g.nodes[after]!).kind !== "next") return g;
    return move(g, after, "up");
  }
  const parents = slotsTo(g, id);
  if (parents.length !== 1 || parents[0]!.from === "start") return g;
  const parentId = parents[0]!.from;
  const parent = g.nodes[parentId]!;
  if (exits(parent).kind !== "next" || parent.type === "goal" || slotsTo(g, parentId).length !== 1) return g;
  const grand = slotsTo(g, parentId)[0]!;
  // grand -> parent -> node -> rest   becomes   grand -> node -> parent -> rest
  let out = write(g, grand, id);
  out = { ...out, nodes: { ...out.nodes, [id]: { ...out.nodes[id]!, next: parentId }, [parentId]: { ...out.nodes[parentId]!, next: node.next ?? null } } };
  return out;
}

/** Every slot that points at a node. */
export function slotsTo(g: Graph, id: string): Slot[] {
  const out: Slot[] = g.start === id ? [{ from: "start" }] : [];
  for (const [nid, n] of Object.entries(g.nodes)) {
    if (n.next === id) out.push({ from: nid });
    for (const [b, t] of Object.entries(n.branches ?? {})) if (t === id) out.push({ from: nid, branch: b });
  }
  return out;
}

// ---- drawing: the graph as a tree, top to bottom ----

export type Chain =
  | { kind: "node"; id: string; slot: Slot; out: Out }
  | { kind: "goto"; id: string; slot: Slot }
  | { kind: "end"; slot: Slot };
export type Out = { kind: "next"; child: Chain } | { kind: "branches"; branches: { name: string; child: Chain }[] } | { kind: "none" };

/** The graph as the builder draws it: a tree from the start, each node drawn once (where a walk first meets it), every
 * later edge to it a "go to"; then each goal not met on the way as its own tree. */
export function tree(g: Graph): { main: Chain; goals: Chain[] } {
  const seen = new Set<string>();
  const walk = (slot: Slot): Chain => {
    const id = read(g, slot);
    if (!id || !g.nodes[id]) return { kind: "end", slot };
    if (seen.has(id)) return { kind: "goto", id, slot };
    seen.add(id);
    const node = g.nodes[id]!;
    const ex = exits(node);
    const out: Out =
      ex.kind === "next" ? { kind: "next", child: walk({ from: id }) } : ex.kind === "branches" ? { kind: "branches", branches: (validBranches(ex.names) ? ex.names : Object.keys(node.branches ?? {})).map((name) => ({ name, child: walk({ from: id, branch: name }) })) } : { kind: "none" };
    return { kind: "node", id, slot, out };
  };
  const main = walk({ from: "start" });
  const goals: Chain[] = [];
  for (const [id, n] of Object.entries(g.nodes)) {
    if (n.type !== "goal" || seen.has(id)) continue;
    seen.add(id);
    goals.push({ kind: "node", id, slot: { from: id }, out: { kind: "next", child: walk({ from: id }) } });
  }
  return { main, goals };
}

/** The node ids in the order the tree draws them: what j and k walk through. */
export function order(g: Graph): string[] {
  const { main, goals } = tree(g);
  const out: string[] = [];
  const walk = (c: Chain) => {
    if (c.kind !== "node") return;
    out.push(c.id);
    if (c.out.kind === "next") walk(c.out.child);
    if (c.out.kind === "branches") c.out.branches.forEach((b) => walk(b.child));
  };
  walk(main);
  goals.forEach(walk);
  return out;
}

// ---- the server's errors, where they belong ----

export type Placed = { trigger: Record<string, string>; nodes: Record<string, Record<string, string>>; general: string[] };

/** Sorts a 422's `fields` ("graph.nodes.send.config.body") into the trigger, each node (by the rest of the path:
 * "config.body", "branches", "" for the node itself) and what belongs to neither. */
export function place(fields: Record<string, string> | undefined, prefix = "graph"): Placed {
  const out: Placed = { trigger: {}, nodes: {}, general: [] };
  for (const [path, message] of Object.entries(fields ?? {})) {
    const p = path === prefix ? "" : path.startsWith(`${prefix}.`) ? path.slice(prefix.length + 1) : null;
    if (p === null) {
      out.general.push(`${path}: ${message}`);
      continue;
    }
    let m: RegExpExecArray | null;
    if ((m = /^nodes\.([^.]+)(?:\.(.*))?$/.exec(p))) (out.nodes[m[1]!] ??= {})[m[2] ?? ""] = message;
    else if ((m = /^trigger(?:\.(.*))?$/.exec(p))) out.trigger[m[1] ?? ""] = message;
    else if (p === "start") out.general.push(`The first step ${message}`);
    else if (p === "nodes") out.general.push(message.charAt(0).toUpperCase() + message.slice(1));
    else out.general.push(p ? `${p}: ${message}` : message);
  }
  return out;
}

// ---- reading values ----

export const offsetOf = (v: unknown): { unit: Unit; count: number } | null => {
  if (!v || typeof v !== "object") return null;
  const [entry] = Object.entries(v as Record<string, unknown>);
  if (!entry || !(UNITS as readonly string[]).includes(entry[0]) || typeof entry[1] !== "number") return null;
  return { unit: entry[0] as Unit, count: entry[1] };
};

const SINGULAR: Record<Unit, string> = { minutes: "minute", hours: "hour", days: "day", weeks: "week" };
export function offsetText(v: unknown): string {
  const o = offsetOf(v);
  if (!o) return "";
  const n = Math.abs(o.count);
  return `${n.toLocaleString("en-US")} ${n === 1 ? SINGULAR[o.unit] : o.unit}`;
}

export function secondsText(total: number): string {
  if (total <= 0) return "no time";
  const parts: string[] = [];
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (d) parts.push(`${d} ${d === 1 ? "day" : "days"}`);
  if (h) parts.push(`${h} ${h === 1 ? "hour" : "hours"}`);
  if (m && !d) parts.push(`${m} ${m === 1 ? "minute" : "minutes"}`);
  return parts.join(" ") || `${total} seconds`;
}

/** Event types in words: "form.submitted" is "Form submitted". */
const EVENT_WORDS: Record<string, string> = {
  "record.created": "Record created",
  "record.updated": "Record updated",
  "record.restored": "Record restored from the trash",
  "deal.stage_changed": "Deal changed stage",
  "tag.added": "Tag added",
  "tag.removed": "Tag removed",
  "form.submitted": "Form submitted",
  "booking.created": "Appointment booked",
  "booking.cancelled": "Appointment cancelled",
  "booking.rescheduled": "Appointment rescheduled",
  "booking.status_changed": "Appointment status changed",
  "booking.reminder_due": "Appointment reminder due",
  "message.received": "Message received",
  "message.sent": "Message sent",
  "message.queued": "Message queued",
  "message.failed": "Message failed",
  "message.status_changed": "Message status changed",
  "message.updated": "Message updated",
  "message.note_added": "Note added to a conversation",
  "conversation.created": "Conversation started",
  "conversation.updated": "Conversation updated",
  "consent.changed": "Consent changed",
  "task.created": "Task created",
  "task.updated": "Task updated",
  "task.completed": "Task completed",
};
const GROUPS: Record<string, string> = { record: "Records", deal: "Deals", tag: "Tags", form: "Forms", booking: "Appointments", message: "Messages", conversation: "Messages", consent: "Messages", task: "Tasks" };
export const eventLabel = (e: string) => EVENT_WORDS[e] ?? (e.charAt(0).toUpperCase() + e.slice(1).replace(/[._]/g, " "));
/** An event type's description for people: its first sentence (the rest is written for developers). */
export const eventHelp = (description: string | undefined) => (description ? (/^.*?[.!?](\s|$)/.exec(description.replace(/`([^`]*)`/g, "$1"))?.[0].trim() ?? description) : "");
export const eventGroup =(e: string) => GROUPS[e.split(".")[0]!] ?? "Other";

/** The record an event of this kind names decides which objects a workflow on it can run on. */
export function objectsFor(record: "subject" | "contact_id" | "record_id", event: string, all: string[]): string[] {
  if (event === "deal.stage_changed") return ["deal"];
  return record === "contact_id" ? ["contact"] : all;
}

/** An empty graph, ready for its first step. */
export const blank = (event = "record.created"): Graph => ({ trigger: { event, object: event === "deal.stage_changed" ? "deal" : "contact", filter: {}, data: {} }, start: null, nodes: {} });

/** A stable string of a graph, for "has it changed" (key order does not matter). */
export function same(a: unknown, b: unknown): boolean {
  return canon(a) === canon(b);
}
function canon(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (v && typeof v === "object")
    return `{${Object.keys(v as object)
      .filter((k) => (v as Record<string, unknown>)[k] !== undefined)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canon((v as Record<string, unknown>)[k])}`)
      .join(",")}}`;
  return JSON.stringify(v);
}
