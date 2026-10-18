import { Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Button, Input, Select, Switch, Textarea } from "../ui";
import type { Band, Definition } from "../forms-runtime/types";
import { allFields } from "./edit.ts";
import type { ContactField, Kind, Settings } from "./api";

export type Draft = { name: string; slug: string; settings: Settings };

const local = (iso: string | null) => {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
const int = (s: string) => (s === "" || Number.isNaN(Number(s)) ? null : Math.round(Number(s)));

function Card({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="fm-card-section">
      <h2>{title}</h2>
      {hint && <p className="ui-hint">{hint}</p>}
      <div className="fm-card-fields">{children}</div>
    </section>
  );
}

type Props = { kind: Kind; draft: Draft; onDraft: (d: Draft) => void; def: Definition; onDef: (d: Definition) => void; contact: ContactField[]; errors: Record<string, string> };

export function SettingsTab({ kind, draft, onDraft, def, onDef, contact, errors }: Props) {
  const s = draft.settings;
  const set = (patch: Partial<Settings>) => onDraft({ ...draft, settings: { ...s, ...patch } });
  const mapped = allFields(def).filter((f) => f.maps_to);
  const label = (key: string) => contact.find((c) => c.key === key)?.label ?? key;
  const bands = def.quiz?.bands ?? [];
  const setQuiz = (patch: Partial<NonNullable<Definition["quiz"]>>) => onDef({ ...def, quiz: { ...def.quiz, ...patch } });
  const setBands = (next: Band[]) => setQuiz({ bands: next });

  return (
    <div className="fm-settings">
      <Card title="Basics">
        <Input label="Name" value={draft.name} error={errors["name"]} onChange={(e) => onDraft({ ...draft, name: e.target.value })} maxLength={200} />
        <Input label="Short name" hint="Lower case letters, digits and dashes. It only helps you find the form; visitors use the public link." value={draft.slug} error={errors["slug"]} onChange={(e) => onDraft({ ...draft, slug: e.target.value })} maxLength={80} />
      </Card>

      <Card title="After someone sends it">
        <Textarea label="Thank you message" value={s.success_message} error={errors["settings.success_message"]} onChange={(e) => set({ success_message: e.target.value })} maxLength={1000} rows={3} />
        <Input label="Send them to a page instead" hint="A full address starting with https://. Quizzes show the result first." type="url" placeholder="https://example.com/thanks" value={s.redirect_url ?? ""} error={errors["settings.redirect_url"]} onChange={(e) => set({ redirect_url: e.target.value.trim() || null })} />
        <Input label="Tell these people about each response" hint="Email addresses, separated by commas. Sending arrives with the email module; for now it is noted in the server log." value={s.notify_emails.join(", ")} error={errors["settings.notify_emails"]} onChange={(e) => set({ notify_emails: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} />
      </Card>

      <Card title="Contacts" hint="A response finds the contact with the same email or phone, or creates one. An empty answer never clears a field. A contact the form creates gets its Source set to Form (when your contacts have a Source field); a contact you already had keeps its Source.">
        <Switch label="Create or update a contact from the answers" checked={s.contact.create} onCheckedChange={(create) => set({ contact: { ...s.contact, create } })} />
        <Select label="When the contact already exists" value={s.contact.existing} onValueChange={(existing) => set({ contact: { ...s.contact, existing: existing as "update" | "fill_empty" } })} disabled={!s.contact.create} options={[{ value: "fill_empty", label: "Only fill fields that are empty (recommended)" }, { value: "update", label: "Update the fields the answers fill in" }]} />
        {s.contact.create && (
          <p className="ui-hint">
            {s.contact.existing === "fill_empty"
              ? "A stranger's answer never overwrites what you already know: only fields that are empty on the contact are filled in."
              : "Every answer replaces the contact's value. Use this only for a form people fill in about themselves, because anyone who knows an email address can send a response with it."}
          </p>
        )}
        <Select label="Someone who already answered" value={s.double_submission} onValueChange={(double_submission) => set({ double_submission: double_submission as "allow" | "block" })} options={[{ value: "allow", label: "May answer again" }, { value: "block", label: "Cannot answer again" }]} />
        <div className="fm-mapping">
          <h3>Answers that fill contact fields</h3>
          {mapped.length === 0 ? (
            <p className="ui-hint">No question saves to a contact field yet. Choose one under Contact in a question's settings.</p>
          ) : (
            <table className="fm-table">
              <caption className="sr-only">Questions and the contact fields they fill</caption>
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Contact field</th>
                </tr>
              </thead>
              <tbody>
                {mapped.map((f) => (
                  <tr key={f.key}>
                    <td>{f.label}</td>
                    <td>{label(f.maps_to!)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Card>

      {kind === "quiz" && (
        <Card title="Scoring" hint="Each scored question has its points and right answer in its settings. Results are by percentage of the points.">
          <Input label="Pass mark (percent)" type="number" min={0} max={100} value={def.quiz?.pass_mark ?? ""} onChange={(e) => setQuiz({ pass_mark: e.target.value === "" ? undefined : Math.max(0, Math.min(100, int(e.target.value) ?? 0)) })} />
          <div className="fm-bands">
            <h3>Result by score</h3>
            {bands.map((b, i) => (
              <div key={i} className="fm-band">
                <Input label="From percent" type="number" min={0} max={100} value={b.min} onChange={(e) => setBands(bands.map((x, j) => (j === i ? { ...x, min: Math.max(0, Math.min(100, int(e.target.value) ?? 0)) } : x)))} />
                <Input label="Title" value={b.title} onChange={(e) => setBands(bands.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} maxLength={100} />
                <Textarea label="Message" value={b.message} rows={2} onChange={(e) => setBands(bands.map((x, j) => (j === i ? { ...x, message: e.target.value } : x)))} maxLength={1000} />
                <Button variant="ghost" size="icon" aria-label={`Remove band ${i + 1}`} onClick={() => setBands(bands.filter((_, j) => j !== i))}>
                  <Trash2 size={16} aria-hidden />
                </Button>
              </div>
            ))}
            <Button size="sm" disabled={bands.length >= 10} onClick={() => setBands([...bands, { min: bands.length ? Math.min(100, Math.max(...bands.map((b) => b.min)) + 25) : 0, title: "", message: "" }])}>
              <Plus size={16} aria-hidden />
              Add a band
            </Button>
          </div>
        </Card>
      )}

      <Card title="Closing" hint="A published form can stop taking responses by itself.">
        <Input label="Close on" type="datetime-local" value={local(s.close_at)} error={errors["settings.close_at"]} onChange={(e) => set({ close_at: e.target.value ? new Date(e.target.value).toISOString() : null })} />
        <Input label="Close after this many responses" type="number" min={1} value={s.max_responses ?? ""} error={errors["settings.max_responses"]} onChange={(e) => set({ max_responses: int(e.target.value) })} />
        <Textarea label="Message when it is closed" value={s.closed_message} rows={2} onChange={(e) => set({ closed_message: e.target.value })} maxLength={500} />
      </Card>

      <Card title="Spam protection" hint="Always on: a limit on requests per visitor and a size limit on what is sent.">
        <Switch label="Hidden trap field and a minimum fill time" checked={s.spam_protection} onCheckedChange={(spam_protection) => set({ spam_protection })} />
        <Input label="Requests per visitor per minute" type="number" min={1} max={600} value={s.rate_limit_per_minute} error={errors["settings.rate_limit_per_minute"]} onChange={(e) => set({ rate_limit_per_minute: int(e.target.value) ?? 30 })} />
        <Input label="Largest request (KB)" type="number" min={4} max={1024} value={s.max_body_kb} error={errors["settings.max_body_kb"]} onChange={(e) => set({ max_body_kb: int(e.target.value) ?? 64 })} />
      </Card>
    </div>
  );
}
