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
import { memo, useImperativeHandle, useRef, useState, type CSSProperties, type ReactNode, type Ref, type RefObject } from "react";
import { cn } from "../lib/cn";
import { DropdownMenu, MenuItem, MenuLabel, MenuSeparator } from "../ui";
import type { Catalog, StepStatus } from "./api";
import { branchLabel, ONLY_FOR, summary, title, triggerSummary, type Names } from "./describe";
import { slotKey, tree, type Chain, type Graph, type NodeType, type Placed, type Slot, type WfNode } from "./graph";
import { errorText } from "./schema";

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

export const iconOf = (n: Pick<WfNode, "type" | "action">): LucideIcon => (n.type === "action" ? (ACTION_ICONS[n.action ?? ""] ?? Zap) : (TYPE_ICONS[n.type] ?? Zap));

/** What the add menu can put on an edge. */
export type AddChoice = { type: Exclude<NodeType, "goal">; action?: string } | { type: "goto" };

type Props = {
  graph: Graph;
  names: Names;
  selected: string | null;
  onSelect: (id: string) => void;
  /** opens the step's settings (a sheet on phones) */
  onOpen: (id: string) => void;
  errors: Placed;
  /** false when the role may not edit: no add buttons, no unlinking */
  editable: boolean;
  /** a + was pressed: the builder opens the add menu at that button */
  onAddAt: (slot: Slot, button: HTMLElement) => void;
  onUnlink: (slot: Slot) => void;
  onAddGoal: () => void;
  /** a "go to" link: select its step and bring it into view */
  onGoto: (id: string) => void;
  /** a run's path: each node's last status, drawn on the cards */
  visits?: Record<string, StepStatus>;
  zoom: number;
};

type CardProps = { id: string; node: WfNode; names: Names; selected: boolean; errors?: Record<string, string>; visit?: StepStatus; onSelect: (id: string) => void; onOpen: (id: string) => void };

/** A step on the canvas. Memoized: selecting one step re-draws two cards, and an edit the cards it changed. */
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

const addLabel = (slot: Slot) => `Add a step here${slot.from === "start" ? ", first" : ` after ${slot.from}${"branch" in slot && slot.branch ? `, ${slot.branch} branch` : ""}`}`;

/** The + on an edge: a plain button (a workflow has hundreds); the one menu lives outside the canvas, in the builder.
 * Its props are strings, so the memo holds across renders. */
const AddButton = memo(function AddButton({ from, branch, onAddAt }: { from: string; branch?: string; onAddAt: (slot: Slot, button: HTMLElement) => void }) {
  const slot: Slot = branch === undefined ? { from } : { from, branch };
  return (
    <button type="button" className="wf-add" aria-haspopup="menu" aria-label={addLabel(slot)} onClick={(e) => onAddAt(slot, e.currentTarget)}>
      <Plus size={14} aria-hidden />
    </button>
  );
});

/** The whole workflow, top to bottom. Memoized with stable handlers. A run of steps is drawn as siblings, not nested
 * in each other, so adding or removing a step inserts or drops elements instead of redrawing all that follow it. */
export const Canvas = memo(function Canvas(p: Props) {
  const { main, goals } = tree(p.graph);

  const edge = (slot: Slot, tail = false) => (
    <div key={`edge:${slotKey(slot)}`} className={cn("wf-edge", tail && "wf-edge-tail")} data-slot={slotKey(slot)}>
      {p.editable && <AddButton from={slot.from} branch={"branch" in slot ? slot.branch : undefined} onAddAt={p.onAddAt} />}
    </div>
  );

  /** A chain as a flat list: each step, the edge after it, and at a branching step its branches side by side. */
  const column = (c: Chain): ReactNode[] => {
    const out: ReactNode[] = [];
    for (let cur: Chain | null = c; cur; ) {
      if (cur.kind === "end") {
        out.push(
          <div key={`end:${slotKey(cur.slot)}`} className="wf-stop">
            End
          </div>,
        );
        break;
      }
      if (cur.kind === "goto") {
        const at = cur;
        const target = p.graph.nodes[at.id];
        out.push(
          <div key={`goto:${slotKey(at.slot)}`} className="wf-goto">
            <button type="button" className="wf-goto-link" onClick={() => p.onGoto(at.id)}>
              <CornerDownRight size={14} aria-hidden />
              Go to {target ? title(target, p.names) : at.id}
              <span className="mono wf-muted">{at.id}</span>
            </button>
            {p.editable && (
              <button type="button" className="wf-goto-x" aria-label={`End here instead of going to ${at.id}`} onClick={() => p.onUnlink(at.slot)}>
                <X size={14} aria-hidden />
              </button>
            )}
          </div>,
        );
        break;
      }
      const id = cur.id;
      const node = p.graph.nodes[id]!;
      out.push(<NodeCard key={id} id={id} node={node} names={p.names} selected={p.selected === id} errors={p.errors.nodes[id]} visit={p.visits?.[id]} onSelect={p.onSelect} onOpen={p.onOpen} />);
      if (cur.out.kind === "next") {
        out.push(edge({ from: id }, cur.out.child.kind === "end"));
        cur = cur.out.child;
        continue;
      }
      if (cur.out.kind === "branches")
        out.push(
          <div key={`branches:${id}`} className="wf-branches" role="group" aria-label={`Branches of ${title(node, p.names)}`}>
            {cur.out.branches.map((b) => (
              <div key={b.name} className="wf-branch">
                <span className="wf-branch-label">{branchLabel(node, b.name)}</span>
                {edge({ from: id, branch: b.name }, b.child.kind === "end")}
                {column(b.child)}
              </div>
            ))}
          </div>,
        );
      break;
    }
    return out;
  };

  const t = p.graph.trigger;
  const triggerErrors = Object.keys(p.errors.trigger).length;
  return (
    <div className="wf-canvas" style={{ zoom: p.zoom } as CSSProperties}>
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
        {main.kind === "end" && p.editable ? <p className="wf-hint-start">Add the first step with the + above.</p> : column(main)}
      </div>
      {(goals.length > 0 || p.editable) && (
        <section className="wf-goals" aria-label="Goals">
          <h2>Goals</h2>
          <p className="wf-muted">A run jumps to a goal the moment its condition holds, wherever it is: "stop the follow-ups once they book".</p>
          <div className="wf-goal-list">
            {goals.map((g) => (
              <div key={g.kind === "node" ? g.id : ""} className="wf-goal wf-chain-item">
                {column(g)}
              </div>
            ))}
          </div>
          {p.editable && (
            <button type="button" className="wf-add-goal" onClick={p.onAddGoal}>
              <Flag size={14} aria-hidden /> Add a goal
            </button>
          )}
        </section>
      )}
    </div>
  );
});

export type AddMenuHandle = { open: (slot: Slot, button: HTMLElement) => void };

/** The add menu, opened at one + at a time: an invisible anchor laid where that button is. It keeps its own state, so
 * opening it redraws only the menu, not the builder. */
export function AddMenu({ ref, scroller, isEmpty, catalog, object, hasNodes, onPick }: { ref: Ref<AddMenuHandle>; scroller: RefObject<HTMLElement | null>; isEmpty: (slot: Slot) => boolean; catalog: Catalog; object: string; hasNodes: boolean; onPick: (slot: Slot, choice: AddChoice) => void }) {
  const [at, setAt] = useState<{ slot: Slot; empty: boolean; style: CSSProperties } | null>(null);
  const picked = useRef(false);
  useImperativeHandle(ref, () => ({
    open: (slot, button) => {
      const el = scroller.current;
      if (!el) return;
      const box = el.getBoundingClientRect();
      const r = button.getBoundingClientRect();
      picked.current = false;
      setAt({ slot, empty: isEmpty(slot), style: { left: r.left - box.left + el.scrollLeft, top: r.top - box.top + el.scrollTop, width: r.width, height: r.height } });
    },
  }));
  if (!at) return null;
  const pick = (choice: AddChoice) => {
    picked.current = true;
    setAt(null);
    onPick(at.slot, choice);
  };
  const close = () => {
    setAt(null);
    // back to the + it came from (a pick moves the focus to the new step instead)
    if (!picked.current) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-slot="${slotKey(at.slot)}"] .wf-add`)?.focus());
  };
  return (
    <DropdownMenu
      label="Add a step"
      align="start"
      open
      onOpenChange={(o) => !o && close()}
      onCloseAutoFocus={(e) => e.preventDefault()}
      trigger={<span className="wf-menu-anchor" style={at.style} aria-hidden />}
    >
      <MenuLabel>Actions</MenuLabel>
      {catalog.actions.map((a) => {
        const Icon = ACTION_ICONS[a.key] ?? Zap;
        const only = ONLY_FOR[a.key];
        const off = !!only && only !== object;
        return (
          <MenuItem key={a.key} icon={<Icon size={16} aria-hidden />} disabled={off} onSelect={() => pick({ type: "action", action: a.key })}>
            {a.label}
            {off && <span className="wf-menu-note">{only === "deal" ? "deals only" : "contacts only"}</span>}
          </MenuItem>
        );
      })}
      <MenuSeparator />
      <MenuLabel>Flow</MenuLabel>
      <MenuItem icon={<Clock size={16} aria-hidden />} onSelect={() => pick({ type: "wait" })}>
        Wait
      </MenuItem>
      <MenuItem icon={<GitBranch size={16} aria-hidden />} onSelect={() => pick({ type: "condition" })}>
        If / else
      </MenuItem>
      <MenuItem icon={<Split size={16} aria-hidden />} onSelect={() => pick({ type: "split" })}>
        A/B split
      </MenuItem>
      {at.empty && hasNodes && (
        <MenuItem icon={<CornerDownRight size={16} aria-hidden />} onSelect={() => pick({ type: "goto" })}>
          Go to a step
        </MenuItem>
      )}
      <MenuItem icon={<CircleStop size={16} aria-hidden />} onSelect={() => pick({ type: "end" })}>
        End
      </MenuItem>
    </DropdownMenu>
  );
}
