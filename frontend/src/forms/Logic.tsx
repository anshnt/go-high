import { GitBranch, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Checkbox, EmptyState, Input, Select, Textarea } from "../ui";
import type { Condition, Definition, Field, Op, Rule } from "../forms-runtime/types";
import { allFields, earlierFields, problems, summarize } from "./edit.ts";
import { LogicMap } from "./LogicMap";
import { OPS_BY_TYPE, OP_LABEL } from "./meta";

type Leaf = Extract<Condition, { field: string }>;
type Flat = { mode: "and" | "or"; items: { not: boolean; leaf: Leaf }[] };
const isLeaf = (c: Condition): c is Leaf => "field" in c;
const ACTIONS = [
  { value: "show", label: "Show a question or step" }, { value: "hide", label: "Hide a question or step" },
  { value: "jump", label: "Jump to a step" }, { value: "end", label: "End the form" },
];

/** A condition the editor can show as rows: one test, or a list of tests (each maybe negated) joined by all or any. */
function toFlat(c: Condition): Flat | null {
  const item = (x: Condition) => (isLeaf(x) ? { not: false, leaf: x } : "not" in x && isLeaf(x.not) ? { not: true, leaf: x.not } : null);
  if (item(c)) return { mode: "and", items: [item(c)!] };
  const list = "and" in c ? c.and : "or" in c ? c.or : null;
  const items = list?.map(item);
  return list && items!.every(Boolean) ? { mode: "and" in c ? "and" : "or", items: items as Flat["items"] } : null;
}
function fromFlat(f: Flat): Condition {
  const parts = f.items.map((i): Condition => (i.not ? { not: i.leaf } : i.leaf));
  return parts.length === 1 ? parts[0]! : f.mode === "and" ? { and: parts } : { or: parts };
}

function defaultValue(f: Field, op: Op): unknown {
  if (op === "is_empty" || op === "is_not_empty") return undefined;
  const list = op === "in" || op === "not_in" || (f.type === "multi_select" && op === "is");
  if (f.type === "select" || f.type === "multi_select") return list ? [f.options?.[0]?.id] : f.options?.[0]?.id;
  if (f.type === "yes_no" || f.type === "checkbox" || f.type === "consent") return true;
  if (f.type === "number" || f.type === "rating") return list ? [f.type === "rating" ? 5 : 0] : f.type === "rating" ? 5 : 0;
  if (f.type === "date") return "2026-01-01";
  return list ? [""] : "";
}

function ValueInput({ f, op, value, onChange }: { f: Field; op: Op; value: unknown; onChange: (v: unknown) => void }) {
  if (op === "is_empty" || op === "is_not_empty") return null;
  const list = op === "in" || op === "not_in" || (f.type === "multi_select" && op === "is");
  const label = `Value for ${f.label}`;
  if ((f.type === "select" || f.type === "multi_select") && list) {
    const on = Array.isArray(value) ? value : [];
    return (
      <fieldset className="fm-checks" aria-label={label}>
        {(f.options ?? []).map((o) => (
          <Checkbox key={o.id} label={o.label} checked={on.includes(o.id)} onCheckedChange={(c) => onChange(c ? [...on, o.id] : on.filter((x) => x !== o.id))} />
        ))}
      </fieldset>
    );
  }
  if (f.type === "select" || f.type === "multi_select") return <Select value={String(value ?? "")} onValueChange={onChange} options={(f.options ?? []).map((o) => ({ value: o.id, label: o.label }))} placeholder="Choose" />;
  if (f.type === "yes_no" || f.type === "checkbox" || f.type === "consent") {
    const labels = f.type === "yes_no" ? ["Yes", "No"] : ["Ticked", "Not ticked"];
    return <Select value={value === false ? "no" : "yes"} onValueChange={(v) => onChange(v === "yes")} options={[{ value: "yes", label: labels[0]! }, { value: "no", label: labels[1]! }]} />;
  }
  const numeric = f.type === "number" || f.type === "rating";
  if (list) {
    return (
      <Input
        aria-label={label}
        placeholder="One, two, three"
        value={Array.isArray(value) ? value.join(", ") : ""}
        onChange={(e) => onChange(e.target.value.split(",").map((s) => (numeric ? Number(s.trim()) : s.trim())).filter((x) => x !== "" && !Number.isNaN(x)))}
      />
    );
  }
  if (numeric) return <Input aria-label={label} type="number" value={typeof value === "number" ? value : ""} onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))} />;
  return <Input aria-label={label} type={f.type === "date" ? "date" : "text"} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />;
}

function ConditionEditor({ def, rule, onChange }: { def: Definition; rule: Rule; onChange: (c: Condition) => void }) {
  const flat = toFlat(rule.when);
  const fields = earlierFields(def, rule);
  const [raw, setRaw] = useState<string | null>(null);
  if (!flat) {
    return (
      <div className="fm-raw">
        <p className="ui-hint">This rule uses nested groups. Edit it as JSON, or replace it with simple tests.</p>
        <Textarea aria-label="Condition as JSON" value={raw ?? JSON.stringify(rule.when, null, 2)} onChange={(e) => { setRaw(e.target.value); try { onChange(JSON.parse(e.target.value)); } catch { /* keep typing */ } }} rows={6} spellCheck={false} />
      </div>
    );
  }
  const set = (next: Flat) => onChange(fromFlat(next));
  const setItem = (i: number, patch: Partial<Flat["items"][number]>) => set({ ...flat, items: flat.items.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const first = fields[0];
  return (
    <div className="fm-cond">
      {flat.items.length > 1 && (
        <Select value={flat.mode} onValueChange={(m) => set({ ...flat, mode: m as "and" | "or" })} options={[{ value: "and", label: "All of these are true" }, { value: "or", label: "Any of these is true" }]} />
      )}
      {flat.items.map(({ not, leaf }, i) => {
        const f = fields.find((x) => x.key === leaf.field);
        const ops = (f && OPS_BY_TYPE[f.type]) ?? [];
        return (
          <div key={i} className="fm-leaf">
            <Select value={f ? leaf.field : ""} placeholder="A question that comes earlier" onValueChange={(key) => { const g = fields.find((x) => x.key === key)!; const op = (OPS_BY_TYPE[g.type] ?? ["is"])[0]!; setItem(i, { leaf: { field: key, op, value: defaultValue(g, op) } }); }} options={fields.map((x) => ({ value: x.key, label: x.label }))} />
            {f && (
              <Select value={leaf.op} onValueChange={(op) => setItem(i, { leaf: { field: leaf.field, op: op as Op, value: defaultValue(f, op as Op) } })} options={ops.map((o) => ({ value: o, label: OP_LABEL[o] }))} />
            )}
            {f && <ValueInput f={f} op={leaf.op} value={leaf.value} onChange={(value) => setItem(i, { leaf: { ...leaf, value } })} />}
            <Checkbox label="Not" aria-label="Reverse this test" checked={not} onCheckedChange={(on) => setItem(i, { not: on })} />
            <Button variant="ghost" size="icon" aria-label="Remove this test" disabled={flat.items.length < 2} onClick={() => set({ ...flat, items: flat.items.filter((_, j) => j !== i) })}>
              <X size={16} aria-hidden />
            </Button>
          </div>
        );
      })}
      <Button size="sm" disabled={!first} onClick={() => set({ ...flat, items: [...flat.items, { not: false, leaf: { field: first!.key, op: "is_not_empty" } }] })}>
        <Plus size={16} aria-hidden />
        Add a test
      </Button>
    </div>
  );
}

function newRule(def: Definition): Rule | null {
  const answers = allFields(def).filter((f) => !["heading", "paragraph"].includes(f.type));
  const first = def.steps[0]!.fields.find((f) => !["heading", "paragraph"].includes(f.type));
  const id = `r${(def.logic ?? []).length + 1}_${Date.now().toString(36).slice(-3)}`;
  if (def.steps.length > 1 && first) return { id, do: "jump", from: def.steps[0]!.key, target: def.steps[1]!.key, when: { field: first.key, op: "is_not_empty" } };
  if (answers.length > 1) return { id, do: "hide", target: answers[1]!.key, when: { field: answers[0]!.key, op: "is_not_empty" } };
  return null;
}

export function Logic({ def, onChange, serverProblems }: { def: Definition; onChange: (d: Definition) => void; serverProblems: Record<number, string> }) {
  const rules = def.logic ?? [];
  const issues = problems(def);
  const setRules = (next: Rule[]) => onChange({ ...def, logic: next.length ? next : undefined });
  const setRule = (i: number, patch: Partial<Rule>) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const stepOptions = def.steps.map((s, i) => ({ value: s.key, label: `Step ${i + 1}${s.title ? `: ${s.title}` : ""}` }));
  const targets = [...stepOptions, ...def.steps.flatMap((s) => s.fields.map((f) => ({ value: f.key, label: `Question: ${f.label}` })))];
  const add = newRule(def);
  const changeAction = (i: number, next: Rule["do"]) => {
    const r = rules[i]!;
    const wasStep = r.do === "jump" || r.do === "end";
    const toStep = next === "jump" || next === "end";
    const later = (def.steps[1] ?? def.steps[0]!).key;
    const patch: Partial<Rule> = { do: next };
    if (toStep && !wasStep) Object.assign(patch, { from: def.steps[0]!.key, target: next === "jump" ? later : undefined });
    if (!toStep && wasStep) Object.assign(patch, { from: undefined, target: allFields(def).slice(-1)[0]?.key });
    if (next === "end") patch.target = undefined;
    if (next === "jump" && wasStep && !r.target) patch.target = later;
    setRule(i, patch);
  };

  return (
    <div className="fm-logic">
      <section className="fm-logic-map" aria-labelledby="map-title">
        <h2 id="map-title">Flow</h2>
        <p className="ui-hint">Visitors go down the steps. A numbered curve is a jump, a green stop ends the form early.</p>
        <LogicMap def={def} />
      </section>
      <section className="fm-logic-rules" aria-labelledby="rules-title">
        <div className="fm-logic-head">
          <h2 id="rules-title">Rules</h2>
          <Button variant="primary" disabled={!add} onClick={() => add && setRules([...rules, add])}>
            <Plus size={16} aria-hidden />
            Add a rule
          </Button>
        </div>
        {rules.length === 0 && (
          <EmptyState icon={GitBranch} title="No rules yet" text={add ? "Show or hide questions, skip ahead to a later step, or end the form early, based on earlier answers." : "Add at least two questions or two steps first. A rule looks at an earlier answer."} />
        )}
        <ol className="fm-rules">
          {rules.map((r, i) => {
            const problem = issues[i] ?? serverProblems[i];
            const jump = r.do === "jump" || r.do === "end";
            return (
              <li key={r.id ?? i} className="fm-rule" data-problem={problem ? "" : undefined}>
                <div className="fm-rule-head">
                  <Badge tone="accent">Rule {i + 1}</Badge>
                  <span className="fm-rule-sum">{summarize(r.when, def)}</span>
                  <Button variant="ghost" size="icon" aria-label={`Delete rule ${i + 1}`} onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                    <Trash2 size={16} aria-hidden />
                  </Button>
                </div>
                {problem && <p className="fm-issue" role="alert">{problem}</p>}
                <div className="fm-rule-body">
                  <div className="fm-rule-then">
                    <span className="fm-when">Then</span>
                    <Select value={r.do} onValueChange={(v) => changeAction(i, v as Rule["do"])} options={ACTIONS} />
                    {jump ? (
                      <>
                        <span className="fm-when">after</span>
                        <Select value={r.from ?? ""} onValueChange={(from) => setRule(i, { from })} options={stepOptions} placeholder="Step" />
                        {r.do === "jump" && (
                          <>
                            <span className="fm-when">go to</span>
                            <Select value={r.target ?? ""} onValueChange={(target) => setRule(i, { target })} options={stepOptions} placeholder="Step" />
                          </>
                        )}
                      </>
                    ) : (
                      <Select value={r.target ?? ""} onValueChange={(target) => setRule(i, { target })} options={targets} placeholder="Choose what to show or hide" />
                    )}
                  </div>
                  <div className="fm-rule-if">
                    <span className="fm-when">When</span>
                    <ConditionEditor def={def} rule={r} onChange={(when) => setRule(i, { when })} />
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
