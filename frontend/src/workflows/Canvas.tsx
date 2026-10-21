import {
  Bell,
  CircleAlert,
  CircleStop,
  Clock,
  CornerDownRight,
  Flag,
  GitBranch,
  Kanban,
  ListChecks,
  MessageSquare,
  PencilLine,
  Plus,
  Split,
  Tag,
  Tags,
  UserCheck,
  Webhook,
  Workflow,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { memo, useRef, type ReactNode } from "react";
import { cn } from "../lib/cn";
import { DropdownMenu, MenuItem, MenuLabel, MenuSeparator } from "../ui";
import type { Catalog, StepStatus } from "./api";
import { branchLabel, ONLY_FOR, summary, title, triggerSummary, type Names } from "./describe";
import { errorText } from "./schema";
import { read, slotKey, tree, type Chain, type Graph, type NodeType, type Placed, type Slot, type WfNode } from "./graph";

const ACTION_ICONS: Record<string, LucideIcon> = {
  "record.update": PencilLine,
  "tag.add": Tag,
  "tag.remove": Tags,
  "owner.assign": UserCheck,
  "deal.move_stage": Kanban,
  "task.create": ListChecks,
  "message.send": MessageSquare,
  "notify.user": Bell,
  "webhook.send": Webhook,
};
const TYPE_ICONS: Record<string, LucideIcon> = { wait: Clock, condition: GitBranch, split: Split, goal: Flag, end: CircleStop, subflow: Workflow };
/** The first of a step's problems as a sentence, and how many more there are. */
export function firstError(errs: Record<string, string>): string {
  const all = Object.entries(errs);
  if (!all.length) return "";
  const [path, message] = all[0]!;
  return `${errorText(path, message)}${all.length > 1 ? ` (and ${all.length - 1} more)` : ""}`;
}

export const iconOf =(n: Pick<WfNode, "type" | "action">): LucideIcon => (n.type === "action" ? (ACTION_ICONS[n.action ?? ""] ?? Zap) : (TYPE_ICONS[n.type] ?? Zap));

/** What the add menu can put on an edge. */
export type AddChoice = { type: Exclude<NodeType, "goal">; action?: string } | { type: "goto" };

type Props = {
  graph: Graph;
  catalog: Catalog;
  names: Names;
  selected: string | null;
  onSelect: (id: string) => void;
  /** opens the step's settings (a sheet on phones) */
  onOpen: (id: string) => void;
  errors: Placed;
  /** null when the role may not edit: no add buttons */
  onAdd: ((slot: Slot, choice: AddChoice) => void) | null;
  onUnlink: ((slot: Slot) => void) | null;
  onAddGoal: (() => void) | null;
  /** the add menu that a shortcut opened, by slot key */
  menuOpen: string | null;
  onMenuOpen: (key: string | null) => void;
  /** a run's path: each node's last status, drawn on the cards */
  visits?: Record<string, StepStatus>;
  zoom: number;
};

type CardProps = { id: string; node: WfNode; names: Names; selected: boolean; errors?: Record<string, string>; visit?: StepStatus; onSelect: (id: string) => void; onOpen: (id: string) => void };

/** A step on the canvas. Memoized: selecting one step re-draws two cards, not all of them. */
const NodeCard = memo(function NodeCard({ id, node, names, selected, errors, visit, onSelect, onOpen }: CardProps) {
  const Icon = iconOf(node);
  const errs = Object.keys(errors ?? {}).length;
  const line = summary(node, names);
  const name = title(node, names);
  return (
    <button
      type="button"
      className={cn("wf-node", `wf-node-${node.type}`)}
      data-node={id}
      data-selected={selected || undefined}
      data-invalid={errs > 0 || undefined}
      data-visit={visit}
      aria-pressed={selected}
      aria-label={`${name}: ${line}${errs ? `. ${errs} ${errs === 1 ? "problem" : "problems"}` : ""}${visit ? `. In this run: ${visit}` : ""}`}
      onClick={() => {
        onSelect(id);
        onOpen(id);
      }}
      onFocus={() => onSelect(id)}
    >
      <span className="wf-node-icon" aria-hidden>
        <Icon size={16} />
      </span>
      <span className="wf-node-text">
        <span className="wf-node-title">{name}</span>
        <span className="wf-node-line">{line}</span>
        {errs > 0 && (
          <span className="wf-node-error">
            <CircleAlert size={12} aria-hidden /> {firstError(errors!)}
          </span>
        )}
      </span>
      <span className="wf-node-id mono" aria-hidden>
        {id}
      </span>
    </button>
  );
});

/** The + on an edge, closed (most of them, always): a plain button, memoized. */
const AddButton = memo(function AddButton({ slotKey: key, label, onOpen }: { slotKey: string; label: string; onOpen: (key: string) => void }) {
  return (
    <button type="button" className="wf-add" aria-haspopup="menu" aria-label={label} onClick={() => onOpen(key)}>
      <Plus size={14} aria-hidden />
    </button>
  );
});

export function Canvas(p: Props) {
  const picked = useRef(false);
  const { main, goals } = tree(p.graph);
  const editable = !!p.onAdd;

  const card = (id: string): ReactNode => (
    <NodeCard key={id} id={id} node={p.graph.nodes[id]!} names={p.names} selected={p.selected === id} errors={p.errors.nodes[id]} visit={p.visits?.[id]} onSelect={p.onSelect} onOpen={p.onOpen} />
  );

  const addMenu = (slot: Slot): ReactNode => {
    if (!p.onAdd) return null;
    const key = slotKey(slot);
    const empty = read(p.graph, slot) === null;
    const onAdd = p.onAdd;
    const add = (slot: Slot, choice: AddChoice) => {
      picked.current = true; // the new step takes the focus, not this button
      onAdd(slot, choice);
    };
    const label = `Add a step here${slot.from === "start" ? ", first" : ` after ${slot.from}${"branch" in slot && slot.branch ? `, ${slot.branch} branch` : ""}`}`;
    // One menu at a time: a workflow has hundreds of edges, and a menu on each would make every render slow.
    if (p.menuOpen !== key) return <AddButton slotKey={key} label={label} onOpen={p.onMenuOpen} />;
    return (
      <DropdownMenu
        label="Add a step"
        align="start"
        open
        onOpenChange={(o) => !o && p.onMenuOpen(null)}
        onCloseAutoFocus={(e) => {
          e.preventDefault(); // the plain button takes the menu's place: focus it once it is back
          if (picked.current) picked.current = false;
          else requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-slot="${key}"] .wf-add`)?.focus());
        }}
        trigger={
          <button type="button" className="wf-add" aria-haspopup="menu" aria-label={label}>
            <Plus size={14} aria-hidden />
          </button>
        }
      >
        <MenuLabel>Actions</MenuLabel>
        {p.catalog.actions.map((a) => {
          const Icon = ACTION_ICONS[a.key] ?? Zap;
          const only = ONLY_FOR[a.key];
          const off = !!only && only !== (p.graph.trigger.object ?? "contact");
          return (
            <MenuItem key={a.key} icon={<Icon size={16} aria-hidden />} disabled={off} onSelect={() => add(slot, { type: "action", action: a.key })}>
              {a.label}
              {off && <span className="wf-menu-note">{only === "deal" ? "deals only" : "contacts only"}</span>}
            </MenuItem>
          );
        })}
        <MenuSeparator />
        <MenuLabel>Flow</MenuLabel>
        <MenuItem icon={<Clock size={16} aria-hidden />} onSelect={() => add(slot, { type: "wait" })}>
          Wait
        </MenuItem>
        <MenuItem icon={<GitBranch size={16} aria-hidden />} onSelect={() => add(slot, { type: "condition" })}>
          If / else
        </MenuItem>
        <MenuItem icon={<Split size={16} aria-hidden />} onSelect={() => add(slot, { type: "split" })}>
          A/B split
        </MenuItem>
        {empty && Object.keys(p.graph.nodes).length > 0 && (
          <MenuItem icon={<CornerDownRight size={16} aria-hidden />} onSelect={() => add(slot, { type: "goto" })}>
            Go to a step
          </MenuItem>
        )}
        <MenuItem icon={<CircleStop size={16} aria-hidden />} onSelect={() => add(slot, { type: "end" })}>
          End
        </MenuItem>
      </DropdownMenu>
    );
  };

  const edge = (slot: Slot, tail = false) => (
    <div className={cn("wf-edge", tail && "wf-edge-tail")} data-slot={slotKey(slot)}>
      {addMenu(slot)}
    </div>
  );

  const chain = (c: Chain): ReactNode => {
    if (c.kind === "end") return <div className="wf-stop">End</div>;
    if (c.kind === "goto") {
      const target = p.graph.nodes[c.id];
      return (
        <div className="wf-goto">
          <button type="button" className="wf-goto-link" onClick={() => p.onSelect(c.id)}>
            <CornerDownRight size={14} aria-hidden />
            Go to {target ? title(target, p.names) : c.id}
            <span className="mono wf-muted">{c.id}</span>
          </button>
          {p.onUnlink && (
            <button type="button" className="wf-goto-x" aria-label={`End here instead of going to ${c.id}`} onClick={() => p.onUnlink!(c.slot)}>
              <X size={14} aria-hidden />
            </button>
          )}
        </div>
      );
    }
    const node = p.graph.nodes[c.id]!;
    return (
      <div className="wf-chain-item">
        {card(c.id)}
        {c.out.kind === "next" && (
          <>
            {edge({ from: c.id }, c.out.child.kind === "end")}
            {chain(c.out.child)}
          </>
        )}
        {c.out.kind === "branches" && (
          <div className="wf-branches" role="group" aria-label={`Branches of ${title(node, p.names)}`}>
            {c.out.branches.map((b) => (
              <div key={b.name} className="wf-branch">
                <span className="wf-branch-label">{branchLabel(node, b.name)}</span>
                {edge({ from: c.id, branch: b.name }, b.child.kind === "end")}
                {chain(b.child)}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const t = p.graph.trigger;
  const triggerErrors = Object.keys(p.errors.trigger).length;
  return (
    <div className="wf-canvas" style={{ zoom: p.zoom }}>
      <div className="wf-chain-item">
        <button
          type="button"
          className="wf-node wf-node-trigger"
          data-node="trigger"
          data-selected={p.selected === "trigger" || undefined}
          data-invalid={triggerErrors > 0 || undefined}
          aria-pressed={p.selected === "trigger"}
          onClick={() => {
            p.onSelect("trigger");
            p.onOpen("trigger");
          }}
          onFocus={() => p.onSelect("trigger")}
        >
          <span className="wf-node-icon" aria-hidden>
            <Zap size={16} />
          </span>
          <span className="wf-node-text">
            <span className="wf-node-title">Starts when</span>
            <span className="wf-node-line">{triggerSummary(t, p.names)}</span>
            {triggerErrors > 0 && (
              <span className="wf-node-error">
                <CircleAlert size={12} aria-hidden /> {firstError(p.errors.trigger)}
              </span>
            )}
          </span>
        </button>
        {edge({ from: "start" }, main.kind === "end")}
        {main.kind === "end" && editable ? <p className="wf-hint-start">Add the first step with the + above.</p> : chain(main)}
      </div>
      {(goals.length > 0 || p.onAddGoal) && (
        <section className="wf-goals" aria-label="Goals">
          <h2>Goals</h2>
          <p className="wf-muted">A run jumps to a goal the moment its condition holds, wherever it is: "stop the follow-ups once they book".</p>
          <div className="wf-goal-list">
            {goals.map((g) => (
              <div key={g.kind === "node" ? g.id : ""} className="wf-goal">
                {chain(g)}
              </div>
            ))}
          </div>
          {p.onAddGoal && (
            <button type="button" className="wf-add-goal" onClick={p.onAddGoal}>
              <Flag size={14} aria-hidden /> Add a goal
            </button>
          )}
        </section>
      )}
    </div>
  );
}
