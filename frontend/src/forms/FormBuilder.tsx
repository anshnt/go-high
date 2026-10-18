import { ChevronLeft, CircleAlert, Copy, EllipsisVertical, Eye, Share2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, DropdownMenu, EmptyState, MenuItem, MenuSeparator, Sheet, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, useToast } from "../ui";
import type { Definition } from "../forms-runtime/types";
import { forms, type ContactField, type FormDetail } from "./api";
import { Analytics } from "./Analytics";
import { Canvas, Palette } from "./Canvas";
import { addField, newField, updateField } from "./edit.ts";
import { FieldPanel } from "./FieldPanel";
import { KIND_LABEL, STATUS_LABEL, STATUS_TONE } from "./FormsPage";
import { Logic } from "./Logic";
import { Preview } from "./Preview";
import { Responses } from "./Responses";
import { SettingsTab, type Draft } from "./SettingsTab";
import { ShareDialog } from "./ShareDialog";
import "./forms.css";

const WIDE = "(min-width: 1100px)";
const useWide = () =>
  useSyncExternalStore(
    (fn) => {
      const m = matchMedia(WIDE);
      m.addEventListener("change", fn);
      return () => m.removeEventListener("change", fn);
    },
    () => matchMedia(WIDE).matches,
  );

/** The server's messages for a definition, put where they belong: on a question, on a rule, or in the list. */
function sort(def: Definition, fields: Record<string, string>) {
  const out = { questions: {} as Record<string, string>, rules: {} as Record<number, string>, settings: {} as Record<string, string>, general: [] as string[] };
  for (const [path, message] of Object.entries(fields)) {
    let m: RegExpExecArray | null;
    if ((m = /^definition\.steps\.(\d+)\.fields\.(\d+)\.(.+)$/.exec(path))) {
      const f = def.steps[Number(m[1])]?.fields[Number(m[2])];
      if (f) out.questions[f.key] = `${m[3]!.replace(/_/g, " ")}: ${message}`;
      else out.general.push(message);
    } else if ((m = /^definition\.steps\.(\d+)\.(.+)$/.exec(path))) out.general.push(`Step ${Number(m[1]) + 1}: ${m[2]!.replace(/_/g, " ")} ${message}`);
    else if ((m = /^definition\.logic\.(\d+)/.exec(path))) out.rules[Number(m[1])] = message;
    else if (path.startsWith("definition.quiz")) out.general.push(`Scoring: ${message}`);
    else if (path.startsWith("definition")) out.general.push(`${path.replace("definition.", "")}: ${message}`);
    else out.settings[path] = message;
  }
  return out;
}

export function FormBuilder() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const wide = useWide();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "build";
  const [form, setForm] = useState<FormDetail | null>(null);
  const [loadError, setLoadError] = useState<string>();
  const [def, setDef] = useState<Definition | null>(null);
  const [savedDef, setSavedDef] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [savedDraft, setSavedDraft] = useState("");
  const [contact, setContact] = useState<ContactField[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [sheet, setSheet] = useState(false); // phones edit a question in a sheet; closing it keeps the question selected
  const [side, setSide] = useState<"question" | "preview">("question");
  const [busy, setBusy] = useState<"save" | "publish" | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [questionIssues, setQuestionIssues] = useState<Record<string, string>>({});
  const [ruleIssues, setRuleIssues] = useState<Record<number, string>>({});
  const [settingsErrors, setSettingsErrors] = useState<Record<string, string>>({});
  const [share, setShare] = useState(false);
  const [trash, setTrash] = useState(false);

  const load = useCallback(() => {
    setLoadError(undefined);
    Promise.all([forms.get(id), forms.contactFields().catch(() => [])])
      .then(([f, fields]) => {
        setForm(f);
        setDef(f.definition);
        setSavedDef(JSON.stringify(f.definition));
        const d = { name: f.name, slug: f.slug, settings: f.settings };
        setDraft(d);
        setSavedDraft(JSON.stringify(d));
        setContact(fields);
      })
      .catch((e) => setLoadError(e instanceof ApiError && e.status === 404 ? "This form does not exist, or it is in the trash." : errorText(e)));
  }, [id]);
  useEffect(load, [load]);

  const dirty = !!def && !!draft && (JSON.stringify(def) !== savedDef || JSON.stringify(draft) !== savedDraft);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname); // tabs only change the query
  useEffect(() => {
    if (!dirty) return;
    const stop = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", stop);
    return () => window.removeEventListener("beforeunload", stop);
  }, [dirty]);

  const clear = () => {
    setProblems([]);
    setQuestionIssues({});
    setRuleIssues({});
    setSettingsErrors({});
  };
  const fail = (e: unknown) => {
    if (e instanceof ApiError && e.fields && def) {
      const s = sort(def, e.fields);
      setQuestionIssues(s.questions);
      setRuleIssues(s.rules);
      setSettingsErrors(s.settings);
      const labelOf = (key: string) => def.steps.flatMap((x) => x.fields).find((f) => f.key === key)?.label ?? key;
      setProblems([
        ...s.general,
        ...Object.values(s.settings),
        ...Object.entries(s.rules).map(([n, m]) => `Rule ${Number(n) + 1}: ${m}`),
        ...Object.entries(s.questions).map(([k, m]) => `${labelOf(k)}, ${m}`),
      ]);
      toast({ title: "The form has problems", description: "They are listed above the form.", tone: "danger" });
    } else toast({ title: "Could not save", description: errorText(e), tone: "danger" });
  };

  const save = useCallback(async (): Promise<boolean> => {
    if (!form || !def || !draft) return true;
    setBusy("save");
    clear();
    try {
      if (JSON.stringify(draft) !== savedDraft) {
        const row = await forms.patch(form.id, { name: draft.name, slug: draft.slug, settings: draft.settings });
        const next = { name: row.name, slug: row.slug, settings: row.settings };
        setDraft(next);
        setSavedDraft(JSON.stringify(next));
      }
      if (JSON.stringify(def) !== savedDef) {
        const v = await forms.save(form.id, def);
        setDef(v.definition);
        setSavedDef(JSON.stringify(v.definition));
      }
      const fresh = await forms.get(form.id);
      setForm((old) => ({ ...fresh, definition: old?.definition ?? fresh.definition }));
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(null);
    }
  }, [form, def, draft, savedDef, savedDraft]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dirty, save]);

  async function publish() {
    if (!form) return;
    setBusy("publish");
    try {
      if (!(await save())) return;
      const row = await forms.publish(form.id);
      setForm((old) => (old ? { ...old, ...row } : old));
      setShare(true);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }
  async function setStatus(status: "draft" | "closed") {
    if (!form) return;
    try {
      const row = await forms.patch(form.id, { status });
      setForm({ ...form, ...row });
      toast({ title: status === "closed" ? "Form closed" : "Form taken offline", description: status === "closed" ? "It shows its closed message until you publish it again." : "Its link stops working until you publish it again.", tone: "success" });
    } catch (e) {
      toast({ title: "Could not change it", description: errorText(e), tone: "danger" });
    }
  }
  async function duplicate() {
    if (!form) return;
    try {
      navigate(`/forms/${(await forms.duplicate(form.id)).id}`);
    } catch (e) {
      toast({ title: "Could not duplicate", description: errorText(e), tone: "danger" });
    }
  }

  if (loadError)
    return (
      <div className="sh-page">
        <EmptyState icon={CircleAlert} title="We could not open this form" text={loadError} action={<Link to="/forms" className="ui-btn" data-variant="secondary" data-size="md">Back to forms</Link>} />
      </div>
    );
  if (!form || !def || !draft)
    return (
      <div className="sh-page">
        <Skeleton style={{ height: 24, width: 240 }} />
      </div>
    );

  const field = def.steps.flatMap((s) => s.fields).find((f) => f.key === selected) ?? null;
  const pick = (key: string | null) => {
    setSelected(key);
    setSheet(key !== null);
  };
  const addAtEnd = (type: Parameters<typeof newField>[1]) => {
    const home = def.steps.find((s) => s.fields.some((f) => f.key === selected)) ?? def.steps[def.steps.length - 1]!;
    const f = newField(def, type);
    setDef(addField(def, home.key, f));
    pick(f.key);
  };
  const panel = field ? (
    <FieldPanel field={field} kind={form.kind} contact={contact} error={questionIssues[field.key]} onChange={(patch) => setDef(updateField(def, field.key, patch))} />
  ) : (
    <p className="fm-hint">Select a question to change its settings, or add one from the list.</p>
  );
  const live = form.status !== "draft";
  const preview = <Preview def={def} name={draft.name} kind={form.kind} settings={draft.settings} />;

  return (
    <div className="sh-page fm-page">
      <Link to="/forms" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Forms
      </Link>
      <Tabs value={tab} onValueChange={(t) => setParams(t === "build" ? {} : { tab: t }, { replace: true })}>
        <PageHeader
          title={draft.name || "Untitled form"}
          description={`${KIND_LABEL[form.kind]}${form.status === "published" ? `, live on version ${form.published_version}` : ""}`}
          actions={
            <>
              <Badge tone={STATUS_TONE[form.status]}>{STATUS_LABEL[form.status]}</Badge>
              {form.has_draft_changes && !dirty && <Badge tone="accent">Unpublished changes</Badge>}
              <span className="fm-saved" role="status">
                {busy === "save" ? "Saving" : dirty ? "Unsaved changes" : "Saved"}
              </span>
              <Button onClick={() => void save()} disabled={!dirty || !!busy} loading={busy === "save"}>
                Save draft
              </Button>
              <Button variant="primary" onClick={() => void publish()} loading={busy === "publish"} disabled={busy === "save"}>
                {form.status === "published" && !form.has_draft_changes && !dirty ? "Republish" : "Publish"}
              </Button>
              <DropdownMenu
                label="More"
                trigger={
                  <Button variant="ghost" size="icon" aria-label="More actions">
                    <EllipsisVertical size={16} aria-hidden />
                  </Button>
                }
              >
                <MenuItem icon={<Share2 size={16} aria-hidden />} onSelect={() => setShare(true)} disabled={!live}>
                  Link and embed code
                </MenuItem>
                <MenuItem icon={<Copy size={16} aria-hidden />} onSelect={() => void duplicate()}>
                  Duplicate
                </MenuItem>
                {form.status === "published" && <MenuItem onSelect={() => void setStatus("closed")}>Close the form</MenuItem>}
                {live && <MenuItem onSelect={() => void setStatus("draft")}>Take it offline</MenuItem>}
                <MenuSeparator />
                <MenuItem icon={<Trash2 size={16} aria-hidden />} onSelect={() => setTrash(true)}>
                  Move to trash
                </MenuItem>
              </DropdownMenu>
            </>
          }
          views={
            <TabsList aria-label="Form sections">
              <TabsTrigger value="build">Build</TabsTrigger>
              {!wide && <TabsTrigger value="preview">Preview</TabsTrigger>}
              <TabsTrigger value="logic">Logic</TabsTrigger>
              <TabsTrigger value="settings">Settings</TabsTrigger>
              <TabsTrigger value="responses">Responses ({form.responses})</TabsTrigger>
              <TabsTrigger value="analytics">Analytics</TabsTrigger>
            </TabsList>
          }
        />
        {problems.length > 0 && (
          <div className="fm-problems" role="alert">
            <strong>Fix these, then save again:</strong>
            <ul>
              {problems.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        )}
        <TabsContent value="build">
          <div className="fm-build">
            <Palette onAdd={addAtEnd} />
            <Canvas def={def} onChange={setDef} selected={selected} onSelect={pick} issues={questionIssues} />
            {wide && (
              <aside className="fm-side" aria-label="Question and preview">
                <div className="fm-seg" role="group" aria-label="Side panel">
                  <button type="button" aria-pressed={side === "question"} onClick={() => setSide("question")}>
                    Question
                  </button>
                  <button type="button" aria-pressed={side === "preview"} onClick={() => setSide("preview")}>
                    <Eye size={14} aria-hidden /> Preview
                  </button>
                </div>
                {side === "question" ? panel : preview}
              </aside>
            )}
          </div>
          {!wide && (
            <Sheet open={!!field && sheet} onOpenChange={setSheet} title="Question settings">
              {panel}
            </Sheet>
          )}
        </TabsContent>
        <TabsContent value="preview">{preview}</TabsContent>
        <TabsContent value="logic">
          <Logic def={def} onChange={setDef} serverProblems={ruleIssues} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab kind={form.kind} draft={draft} onDraft={setDraft} def={def} onDef={setDef} contact={contact} errors={settingsErrors} />
        </TabsContent>
        <TabsContent value="responses">
          <Responses form={form} def={def} />
        </TabsContent>
        <TabsContent value="analytics">
          <Analytics form={form} />
        </TabsContent>
      </Tabs>

      <ShareDialog form={form} open={share} onOpenChange={setShare} />
      <Dialog
        open={trash}
        onOpenChange={setTrash}
        title={`Move "${form.name}" to the trash?`}
        description={`Its link stops working now. ${form.responses ? `Its ${form.responses.toLocaleString()} response${form.responses === 1 ? "" : "s"} are kept.` : ""} You can restore it from the trash on the Forms page.`}
        footer={
          <>
            <Button onClick={() => setTrash(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={async () => {
                try {
                  setSavedDef(JSON.stringify(def));
                  setSavedDraft(JSON.stringify(draft));
                  await forms.remove(form.id);
                  navigate("/forms");
                } catch (e) {
                  toast({ title: "Could not move it", description: errorText(e), tone: "danger" });
                }
              }}
            >
              Move to trash
            </Button>
          </>
        }
      />
      <Dialog
        open={blocker.state === "blocked"}
        onOpenChange={(o) => !o && blocker.state === "blocked" && blocker.reset()}
        title="Leave without saving?"
        description="You have changes that are not saved yet."
        footer={
          <>
            <Button onClick={() => blocker.state === "blocked" && blocker.reset()}>Keep editing</Button>
            <Button variant="danger" onClick={() => blocker.state === "blocked" && blocker.proceed()}>
              Leave without saving
            </Button>
          </>
        }
      />
    </div>
  );
}
