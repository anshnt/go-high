// The inbox keyboard: which key does what, and where the cursor goes. Pure, so the rules can be tested.

export type InboxAction =
  | "next"
  | "prev"
  | "open"
  | "close"
  | "snooze"
  | "assign"
  | "reply"
  | "note"
  | "unread"
  | "search"
  | "find"
  | "card"
  | "escape";

type Keys = { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean; shiftKey?: boolean };

/** What a key press means in the inbox, or null. Chords (Ctrl, Cmd, Alt) are never ours. */
export function actionFor(e: Keys): InboxAction | null {
  if (e.ctrlKey || e.metaKey || e.altKey) return null;
  switch (e.key) {
    case "j":
    case "ArrowDown":
      return "next";
    case "k":
    case "ArrowUp":
      return "prev";
    case "Enter":
    case "o":
      return "open";
    case "e":
      return "close";
    case "s":
      return "snooze";
    case "a":
      return "assign";
    case "r":
      return "reply";
    case "n":
      return "note";
    case "u":
      return "unread";
    case "/":
      return "search";
    case "f":
      return "find";
    case "i":
      return "card";
    case "Escape":
      return "escape";
    default:
      return null;
  }
}

/** The id the cursor lands on after moving `delta` rows from `current` (the first row when it is on none). Stops at the ends. */
export function moveActive(ids: string[], current: string | null, delta: 1 | -1): string | null {
  if (!ids.length) return null;
  const at = current ? ids.indexOf(current) : -1;
  if (at < 0) return ids[delta === 1 ? 0 : ids.length - 1]!;
  return ids[Math.max(0, Math.min(ids.length - 1, at + delta))]!;
}

/** Where the cursor goes when `removed` leaves the list (closed, snoozed, assigned away): the row that takes its place, else the one above. */
export function nextAfterRemoval(ids: string[], removed: string): string | null {
  const at = ids.indexOf(removed);
  if (at < 0) return ids[0] ?? null;
  return ids[at + 1] ?? ids[at - 1] ?? null;
}
