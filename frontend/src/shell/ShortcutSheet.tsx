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
const BOARD: typeof GENERAL = [
  { keys: ["Enter"], label: "Open the deal" },
  { keys: ["M"], label: "Move the deal to a stage" },
  { keys: ["Arrows"], label: "Move between deals" },
  { keys: ["Shift", "Up or Down"], label: "Move the deal within its stage" },
  { keys: ["Shift", "Left or Right"], label: "Move the deal to the next stage" },
];
const WORKFLOWS: typeof GENERAL = [
  { keys: ["J"], label: "Next workflow" },
  { keys: ["K"], label: "Previous workflow" },
  { keys: ["Enter"], label: "Open the workflow" },
  { keys: ["/"], label: "Search workflows" },
  { keys: ["N"], label: "New workflow" },
];
const BUILDER: typeof GENERAL = [
  { keys: ["J"], label: "Next step (Down on a step)" },
  { keys: ["K"], label: "Previous step (Up on a step)" },
  { keys: ["E"], label: "Edit the selected step" },
  { keys: ["A"], label: "Add a step after the selected one" },
  { keys: ["Del"], label: "Remove the selected step" },
  { keys: ["Alt", "Up or Down"], label: "Move the step up or down" },
  { keys: ["T"], label: "Test on a record" },
  { keys: [MOD, "S"], label: "Save as a version" },
  { keys: [MOD, "Z"], label: "Undo (add Shift to redo)" },
  { keys: ["+ or -"], label: "Zoom in or out (0 resets)" },
  { keys: ["F"], label: "Zoom to fit the width" },
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
      <Group title="Pipeline board (focus a deal)" rows={BOARD} />
      <Group title="Automations" rows={WORKFLOWS} />
      <Group title="Workflow builder" rows={BUILDER} />
    </Sheet>
  );
}
