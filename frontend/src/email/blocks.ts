// Pure helpers for the email screens: editing a block document, reading the server's error paths, and the words and
// numbers the screens show. No React and no browser globals, so node tests them directly.
import type { Block, BlockType, CampaignStatus, Doc, Issue } from "./api";

export const BLOCK_LABEL: Record<BlockType, string> = {
  heading: "Heading",
  text: "Text",
  button: "Button",
  image: "Image",
  divider: "Divider",
  spacer: "Spacer",
  columns: "Two columns",
};

let counter = 0;
/** A short id for a new block (the builder's keys and selection; the server keeps it). */
export const blockId = () => `b${Date.now().toString(36)}${(counter++).toString(36)}`;

export function newBlock(type: BlockType): Block {
  const id = blockId();
  switch (type) {
    case "heading":
      return { type, id, text: "A clear headline", level: 1, align: "left" };
    case "text":
      return { type, id, text: "Say one thing well. **Bold**, _italic_ and [links](https://example.com) work.", align: "left" };
    case "button":
      return { type, id, label: "Read more", url: "https://example.com", align: "center" };
    case "image":
      return { type, id, src: "https://placehold.co/1200x600/png", alt: "", width: 600, align: "center" };
    case "divider":
      return { type, id };
    case "spacer":
      return { type, id, height: 24 };
    case "columns":
      return { type, id, columns: [{ blocks: [newBlock("text")] }, { blocks: [newBlock("text")] }] };
  }
}

export const emptyDoc = (): Doc => ({ version: 1, blocks: [] });

/** Gives every block an id, so a document from the server can be selected and reordered by id. */
export function withIds(doc: Doc | undefined | null): Doc {
  const fix = (b: Block): Block => ({ ...b, id: b.id ?? blockId(), ...(b.type === "columns" ? { columns: b.columns.map((c) => ({ blocks: c.blocks.map(fix) })) } : {}) } as Block);
  return { version: 1, ...(doc ?? {}), blocks: (doc?.blocks ?? []).map(fix) };
}

export function insertAt(doc: Doc, index: number, block: Block): Doc {
  const blocks = [...doc.blocks];
  blocks.splice(Math.max(0, Math.min(index, blocks.length)), 0, block);
  return { ...doc, blocks };
}

export function removeBlock(doc: Doc, id: string): Doc {
  return { ...doc, blocks: doc.blocks.filter((b) => b.id !== id) };
}

/** Moves a block up (-1) or down (+1); at either end nothing changes. */
export function moveBlock(doc: Doc, id: string, by: -1 | 1): Doc {
  const i = doc.blocks.findIndex((b) => b.id === id);
  const j = i + by;
  if (i < 0 || j < 0 || j >= doc.blocks.length) return doc;
  const blocks = [...doc.blocks];
  [blocks[i], blocks[j]] = [blocks[j]!, blocks[i]!];
  return { ...doc, blocks };
}

export function duplicateBlock(doc: Doc, id: string): Doc {
  const i = doc.blocks.findIndex((b) => b.id === id);
  if (i < 0) return doc;
  const copy = withIds({ blocks: [JSON.parse(JSON.stringify({ ...doc.blocks[i], id: undefined }))] }).blocks[0]!;
  return insertAt(doc, i + 1, copy);
}

export function updateBlock(doc: Doc, id: string, patch: Partial<Block>): Doc {
  return { ...doc, blocks: doc.blocks.map((b) => (b.id === id ? ({ ...b, ...patch } as Block) : b)) };
}

/** A one line description of a block for the outline. */
export function summary(b: Block): string {
  const clip = (s: string) => (s.length > 60 ? `${s.slice(0, 57)}...` : s);
  switch (b.type) {
    case "heading":
    case "text":
      return clip(b.text.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/\*\*(.+?)\*\*/g, "$1").replace(/(^|[^\w{])_(.+?)_(?![\w}])/g, "$1$2"));
    case "button":
      return clip(b.label);
    case "image":
      return clip(b.alt || b.src);
    case "spacer":
      return `${b.height ?? 24} px`;
    case "columns":
      return `${b.columns.length} columns`;
    default:
      return "";
  }
}

/** The server's errors (`document.blocks.2.url`) by block id, and the rest as a list. */
export function issuesByBlock(doc: Doc, fields: Record<string, string>, root = "document"): { blocks: Record<string, string>; other: string[] } {
  const out = { blocks: {} as Record<string, string>, other: [] as string[] };
  for (const [path, message] of Object.entries(fields)) {
    const m = new RegExp(`^${root.replace(/\./g, "\\.")}\\.blocks\\.(\\d+)(?:\\.(.+))?$`).exec(path);
    const block = m ? doc.blocks[Number(m[1])] : undefined;
    if (block?.id) out.blocks[block.id] = m![2] ? `${m![2].replace(/\.\d+\./g, " ").replace(/_/g, " ")}: ${message}` : message;
    else out.other.push(path === "subject" || path === "preheader" ? `${path[0]!.toUpperCase()}${path.slice(1)}: ${message}` : message);
  }
  return out;
}

export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "Draft",
  scheduled: "Scheduled",
  sending: "Sending",
  testing: "A/B testing",
  paused: "Paused",
  sent: "Sent",
  cancelled: "Cancelled",
  failed: "Failed",
};
export const STATUS_TONE: Record<CampaignStatus, "neutral" | "accent" | "success" | "warning" | "danger" | "info"> = {
  draft: "neutral",
  scheduled: "info",
  sending: "accent",
  testing: "accent",
  paused: "warning",
  sent: "success",
  cancelled: "neutral",
  failed: "danger",
};

/** 0.4567 → "45.7%"; nothing to divide by → "None yet". */
export function percent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined || Number.isNaN(rate)) return "None yet";
  const p = rate * 100;
  return `${p >= 10 || p === 0 ? p.toFixed(0) : p.toFixed(1)}%`;
}

export const ratio = (n: number, of: number) => (of ? n / of : null);

/** Issues in the order a person fixes them: errors, then warnings, then information. */
export function byLevel(issues: Issue[]): Issue[] {
  const rank = { error: 0, warning: 1, info: 2 };
  return [...issues].sort((a, b) => rank[a.level] - rank[b.level]);
}

/** What the schedule call takes for a date and time typed on a wall clock in `zone` ("2026-11-02", "09:30"). */
export function scheduleBody(date: string, time: string, zone: string): { scheduled_at: string; timezone: string } | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) return null;
  return { scheduled_at: `${date}T${time}:00`, timezone: zone };
}

export const SUPPRESSION_LABEL = { hard_bounce: "Hard bounce", complaint: "Spam complaint", unsubscribe: "Unsubscribed", manual: "Added by hand" } as const;

/**
 * The email as a mail app in dark mode shows it: the renderer's `prefers-color-scheme: dark` rules applied outright.
 * A preview frame cannot be told to prefer dark, so the rules are lifted out of their media query.
 */
export function asDark(html: string): string {
  const start = html.indexOf("@media (prefers-color-scheme:dark){");
  if (start < 0) return html;
  let depth = 0;
  let i = html.indexOf("{", start);
  const from = i + 1;
  for (; i < html.length; i++) {
    if (html[i] === "{") depth++;
    else if (html[i] === "}" && --depth === 0) break;
  }
  const rules = html.slice(from, i);
  return html.replace("</head>", `<style>:root{color-scheme:dark}${rules}</style></head>`);
}
