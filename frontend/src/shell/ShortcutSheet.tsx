import { CORE, MY_DAY_NAV } from "../lib/nav";
import { MOD } from "../lib/platform";
import { Kbd, Sheet } from "../ui";

const GENERAL: { keys: string[]; label: string }[] = [
  { keys: [MOD, "K"], label: "Open the command palette" },
  { keys: ["?"], label: "Show this list" },
  { keys: ["Esc"], label: "Close a dialog, sheet or menu" },
];
const LISTS: { keys: string[]; label: string }[] = [
  { keys: ["/"], label: "Search the list" },
  { keys: ["J"], label: "Next row" },
  { keys: ["K"], label: "Previous row" },
  { keys: ["X"], label: "Select or unselect the row" },
  { keys: ["Enter"], label: "Open the row" },
  { keys: ["Esc"], label: "Close the open record, or clear the selection" },
];
const TASKS: typeof GENERAL = [
  { keys: ["J"], label: "Next task" },
  { keys: ["K"], label: "Previous task" },
  { keys: ["X"], label: "Complete or reopen the task" },
  { keys: ["E"], label: "Edit the task" },
  { keys: ["N"], label: "Add a task" },
];
const INBOX: typeof GENERAL = [
  { keys: ["J"], label: "Next conversation" },
  { keys: ["K"], label: "Previous conversation" },
  { keys: ["Enter"], label: "Open the conversation (or jump to the reply box)" },
  { keys: ["O"], label: "Open the conversation" },
  { keys: ["E"], label: "Close the conversation" },
  { keys: ["S"], label: "Snooze" },
  { keys: ["A"], label: "Assign to a person or team" },
  { keys: ["R"], label: "Reply" },
  { keys: ["N"], label: "Write an internal note" },
  { keys: ["U"], label: "Mark as unread, or read" },
  { keys: ["/"], label: "Search conversations" },
  { keys: ["F"], label: "Find in this conversation" },
  { keys: ["I"], label: "Show or hide the contact card" },
  { keys: [MOD, "Enter"], label: "Send the message" },
  { keys: ["Esc"], label: "Leave the reply box, or go back to the list" },
];
const GO = [MY_DAY_NAV, ...CORE].filter((c) => c.gKey).map((c) => ({ keys: ["G", c.gKey!.toUpperCase()], label: `Go to ${c.label}` }));

function Group({ title, rows }: { title: string; rows: typeof GENERAL }) {
  return (
    <section className="sh-keys-group">
      <h3>{title}</h3>
      <dl>
        {rows.map((r) => (
          <div key={r.label} className="sh-keys-row">
            <dt>{r.label}</dt>
            <dd>
              {r.keys.map((k, i) => (
                <span key={k}>
                  {i > 0 && r.keys[0] === "G" && <span className="sh-keys-then">then</span>}
                  <Kbd>{k}</Kbd>
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" description="Single-key shortcuts pause while you type in a field.">
      <Group title="General" rows={GENERAL} />
      <Group title="Navigation" rows={GO} />
      <Group title="Inbox" rows={INBOX} />
      <Group title="Lists and records" rows={LISTS} />
      <Group title="Tasks" rows={TASKS} />
    </Sheet>
  );
}
