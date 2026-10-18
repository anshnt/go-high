import { ArrowDown, ArrowUp, Copy, GripVertical, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { Button, DropdownMenu, Input, MenuItem, MenuLabel, MenuSeparator } from "../ui";
import type { Definition, Field, FieldType, Step } from "../forms-runtime/types";
import { addField, addStep, allFields, duplicateField, locate, moveField, moveStep, newField, nudgeField, removeField, removeStep, updateStep } from "./edit.ts";
import { FIELD_TYPES, GROUPS, TYPE_META } from "./meta";

const FIELD = "application/x-gohigh-field";
const NEW = "application/x-gohigh-new";
const ours = (e: DragEvent) => e.dataTransfer.types.includes(FIELD) || e.dataTransfer.types.includes(NEW);

type Props = {
  def: Definition;
  onChange: (d: Definition) => void;
  selected: string | null;
  onSelect: (key: string | null) => void;
  issues: Record<string, string>;
};

/** The question types, to click or drag onto the form. */
export function Palette({ onAdd }: { onAdd: (type: FieldType) => void }) {
  return (
    <aside className="fm-palette" aria-label="Question types">
      {GROUPS.map((g) => (
        <div key={g} className="fm-palette-group">
          <h2>{g}</h2>
          {FIELD_TYPES.filter((t) => t.group === g).map((t) => (
            <button key={t.type} type="button" className="fm-palette-item" draggable onDragStart={(e) => { e.dataTransfer.setData(NEW, t.type); e.dataTransfer.effectAllowed = "copy"; }} onClick={() => onAdd(t.type)}>
              <t.icon size={16} aria-hidden />
              {t.label}
            </button>
          ))}
        </div>
      ))}
    </aside>
  );
}

export function AddMenu({ onAdd, label = "Add a question" }: { onAdd: (type: FieldType) => void; label?: string }) {
  return (
    <DropdownMenu
      align="start"
      label={label}
      trigger={
        <Button size="sm">
          <Plus size={16} aria-hidden />
          {label}
        </Button>
      }
    >
      {GROUPS.map((g, i) => (
        <div key={g}>
          {i > 0 && <MenuSeparator />}
          <MenuLabel>{g}</MenuLabel>
          {FIELD_TYPES.filter((t) => t.group === g).map((t) => (
            <MenuItem key={t.type} icon={<t.icon size={16} aria-hidden />} onSelect={() => onAdd(t.type)}>
              {t.label}
            </MenuItem>
          ))}
        </div>
      ))}
    </DropdownMenu>
  );
}

export function Canvas({ def, onChange, selected, onSelect, issues }: Props) {
  const [over, setOver] = useState<{ step: string; index: number } | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const refocus = useRef<string | null>(null);
  useEffect(() => {
    if (refocus.current) document.querySelector<HTMLElement>(`[data-card="${CSS.escape(refocus.current)}"] .fm-card-main`)?.focus();
    refocus.current = null;
  });
  const rules = (key: string) => (def.logic ?? []).filter((r) => r.target === key || r.from === key).length;

  const add = (stepKey: string, type: FieldType, index?: number) => {
    const f = newField(def, type);
    onChange(addField(def, stepKey, f, index));
    onSelect(f.key);
  };
  const drop = (e: DragEvent) => {
    if (!ours(e) || !over) return;
    e.preventDefault();
    const key = e.dataTransfer.getData(FIELD);
    const type = e.dataTransfer.getData(NEW);
    if (key) {
      const at = locate(def, key);
      const sameStep = at && def.steps[at.step]!.key === over.step;
      onChange(moveField(def, key, over.step, sameStep && at.index < over.index ? over.index - 1 : over.index));
      refocus.current = key;
    } else if (type) add(over.step, type as FieldType, over.index);
    setOver(null);
    setDragging(null);
  };
  const hover = (e: DragEvent, step: Step, index: number | null) => {
    if (!ours(e)) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = e.dataTransfer.types.includes(NEW) ? "copy" : "move";
    if (index === null) return setOver({ step: step.key, index: step.fields.length });
    const r = e.currentTarget.getBoundingClientRect();
    setOver({ step: step.key, index: index + (e.clientY > r.top + r.height / 2 ? 1 : 0) });
  };
  const keys = (e: KeyboardEvent, key: string) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    onChange(nudgeField(def, key, e.key === "ArrowUp" ? -1 : 1));
    refocus.current = key;
  };

  return (
    <div className="fm-canvas" onDrop={drop} onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setOver(null)}>
      {def.steps.map((step, i) => (
        <section key={step.key} className="fm-step" aria-label={`Step ${i + 1}`}>
          <header className="fm-step-head">
            <span className="fm-step-num" aria-hidden>
              {i + 1}
            </span>
            <Input aria-label={`Title of step ${i + 1}`} placeholder={`Step ${i + 1}`} value={step.title} onChange={(e) => onChange(updateStep(def, step.key, { title: e.target.value }))} maxLength={200} />
            <div className="fm-step-actions">
              <Button variant="ghost" size="icon" aria-label={`Move step ${i + 1} up`} disabled={i === 0} onClick={() => onChange(moveStep(def, step.key, -1))}>
                <ArrowUp size={16} aria-hidden />
              </Button>
              <Button variant="ghost" size="icon" aria-label={`Move step ${i + 1} down`} disabled={i === def.steps.length - 1} onClick={() => onChange(moveStep(def, step.key, 1))}>
                <ArrowDown size={16} aria-hidden />
              </Button>
              <Button variant="ghost" size="icon" aria-label={`Delete step ${i + 1}`} disabled={def.steps.length < 2} onClick={() => onChange(removeStep(def, step.key))}>
                <Trash2 size={16} aria-hidden />
              </Button>
            </div>
          </header>
          <div className="fm-fields" onDragOver={(e) => hover(e, step, null)}>
            {step.fields.map((f, j) => (
              <div key={f.key} className="fm-slot" onDragOver={(e) => hover(e, step, j)}>
                {over?.step === step.key && over.index === j && <div className="fm-drop" />}
                <FieldCard
                  f={f}
                  selected={selected === f.key}
                  dragging={dragging === f.key}
                  rules={rules(f.key)}
                  issue={issues[f.key]}
                  first={i === 0 && j === 0}
                  last={i === def.steps.length - 1 && j === step.fields.length - 1}
                  onSelect={() => onSelect(f.key)}
                  onKeyDown={(e) => keys(e, f.key)}
                  onDragStart={(e) => { e.dataTransfer.setData(FIELD, f.key); e.dataTransfer.effectAllowed = "move"; setDragging(f.key); }}
                  onDragEnd={() => { setDragging(null); setOver(null); }}
                  onNudge={(dir) => { onChange(nudgeField(def, f.key, dir)); refocus.current = f.key; }}
                  onCopy={() => {
                    const d = duplicateField(def, f.key);
                    const had = new Set(allFields(def).map((x) => x.key));
                    onChange(d);
                    onSelect(allFields(d).find((x) => !had.has(x.key))?.key ?? null);
                  }}
                  onDelete={() => { onChange(removeField(def, f.key)); if (selected === f.key) onSelect(null); }}
                />
              </div>
            ))}
            {over?.step === step.key && over.index === step.fields.length && step.fields.length > 0 && <div className="fm-drop" />}
            {step.fields.length === 0 && (
              <p className={over?.step === step.key ? "fm-empty fm-empty-over" : "fm-empty"}>Drag a question here, or add one below.</p>
            )}
          </div>
          <footer className="fm-step-foot">
            <AddMenu onAdd={(t) => add(step.key, t)} />
          </footer>
        </section>
      ))}
      <Button onClick={() => onChange(addStep(def, def.steps[def.steps.length - 1]!.key))}>
        <Plus size={16} aria-hidden />
        Add a step
      </Button>
    </div>
  );
}

type CardProps = {
  f: Field;
  selected: boolean;
  dragging: boolean;
  rules: number;
  issue?: string;
  first: boolean;
  last: boolean;
  onSelect: () => void;
  onKeyDown: (e: KeyboardEvent) => void;
  onDragStart: (e: DragEvent) => void;
  onDragEnd: () => void;
  onNudge: (dir: -1 | 1) => void;
  onCopy: () => void;
  onDelete: () => void;
};

function FieldCard({ f, selected, dragging, rules, issue, first, last, onSelect, onKeyDown, onDragStart, onDragEnd, onNudge, onCopy, onDelete }: CardProps) {
  const meta = TYPE_META[f.type];
  return (
    <div className="fm-card" data-card={f.key} data-selected={selected || undefined} data-dragging={dragging || undefined} draggable onDragStart={onDragStart} onDragEnd={onDragEnd} onKeyDown={onKeyDown}>
      <span className="fm-handle" aria-hidden title="Drag to move">
        <GripVertical size={16} />
      </span>
      <button type="button" className="fm-card-main" aria-pressed={selected} onClick={onSelect} aria-describedby={issue ? `issue-${f.key}` : undefined}>
        <meta.icon size={16} aria-hidden />
        <span className="fm-card-text">
          <span className="fm-card-label">
            {f.label || "Untitled"}
            {f.required && <span className="fm-req" aria-label="required"> *</span>}
          </span>
          <span className="fm-card-meta">
            {meta.label}
            {f.maps_to && <span className="fm-chip">saves to {f.maps_to}</span>}
            {rules > 0 && <span className="fm-chip">{rules} rule{rules === 1 ? "" : "s"}</span>}
            {f.quiz && <span className="fm-chip">{f.quiz.points} pt{f.quiz.points === 1 ? "" : "s"}</span>}
            {f.type === "hidden" && <span className="fm-chip">from ?{f.param ?? f.key}</span>}
          </span>
        </span>
      </button>
      <div className="fm-card-actions">
        <Button variant="ghost" size="icon" aria-label={`Move ${f.label} up`} disabled={first} onClick={() => onNudge(-1)}>
          <ArrowUp size={16} aria-hidden />
        </Button>
        <Button variant="ghost" size="icon" aria-label={`Move ${f.label} down`} disabled={last} onClick={() => onNudge(1)}>
          <ArrowDown size={16} aria-hidden />
        </Button>
        <Button variant="ghost" size="icon" aria-label={`Duplicate ${f.label}`} onClick={onCopy}>
          <Copy size={16} aria-hidden />
        </Button>
        <Button variant="ghost" size="icon" aria-label={`Delete ${f.label}`} onClick={onDelete}>
          <Trash2 size={16} aria-hidden />
        </Button>
      </div>
      {issue && (
        <p id={`issue-${f.key}`} className="fm-issue" role="alert">
          {issue}
        </p>
      )}
    </div>
  );
}
