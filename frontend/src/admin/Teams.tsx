// Team and roles > Teams: the teams of the workspace as a tree (a team may sit under another), each with its members.
// A role with the `team` scope sees what anyone in its holder's teams, or the teams below them, owns.
import { ChevronRight, Network, Pencil, Plus, Trash2, UserMinus, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, useToast } from "../ui";
import { Combobox } from "../ui/Combobox";
import { addTeamMember, createTeam, deleteTeam, getTeam, listMembers, listTeams, patchTeam, removeTeamMember, type Team } from "./api";
import { ConfirmDialog, LoadError, Loading, personName, useLoad } from "./common";
import { subtree, teamPath, teamTree } from "./logic.ts";

const TOP = "__top";

function TeamForm({ open, onOpenChange, teams, team, parent, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; teams: Team[]; team?: Team; parent?: string | null; onDone: (t: Team) => void }) {
  const [name, setName] = useState(team?.name ?? "");
  const [parentId, setParentId] = useState<string>(team ? (team.parent_team_id ?? TOP) : (parent ?? TOP));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const blocked = team ? subtree(teams, team.id) : new Set<string>();
  const parents = [{ value: TOP, label: "None (a top level team)" }, ...teamTree(teams).filter(({ team: t }) => !blocked.has(t.id)).map(({ team: t }) => ({ value: t.id, label: teamPath(teams, t.id) }))];

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setErrors({ name: "Give the team a name." });
    setBusy(true);
    setErrors({});
    const parent_team_id = parentId === TOP ? null : parentId;
    try {
      onDone(team ? await patchTeam(team.id, { name: name.trim(), parent_team_id }) : await createTeam({ name: name.trim(), parent_team_id }));
    } catch (err) {
      const f = err instanceof ApiError ? err.fields : undefined;
      if (f?.name) setErrors({ name: `This name ${f.name}.` });
      else if (f?.parent_team_id) setErrors({ parent: f.parent_team_id.charAt(0).toUpperCase() + f.parent_team_id.slice(1) + "." });
      else setErrors({ form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={team ? `Edit ${team.name}` : "New team"}
      description="A team may sit under another. Someone who sees their team's records sees the teams below it too."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form="team-form" loading={busy}>
            {team ? "Save" : "Create team"}
          </Button>
        </>
      }
    >
      <form id="team-form" className="adm-form" onSubmit={submit} noValidate>
        <Input label="Name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} error={errors.name} autoFocus />
        <Select label="Sits under" value={parentId} onValueChange={setParentId} options={parents} />
        {errors.parent && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.parent}
          </p>
        )}
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}

export function Teams() {
  const toast = useToast();
  const { can } = useCan();
  const manage = can("members.manage");
  const teams = useLoad(listTeams, []);
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("team");
  const [form, setForm] = useState<{ team?: Team; parent?: string | null } | null>(null);
  const tree = useMemo(() => teamTree(teams.data ?? []), [teams.data]);
  const selected = teams.data?.find((t) => t.id === selectedId) ?? null;
  const select = (id: string | null) => setParams(id ? { team: id } : {}, { replace: true });

  if (teams.error && !teams.data) return <LoadError what="teams" error={teams.error} retry={teams.reload} />;
  if (!teams.data) return <Loading label="Loading teams" rows={4} height={44} />;

  const done = (t: Team, verb: string) => {
    setForm(null);
    teams.reload();
    select(t.id);
    toast({ title: `Team ${verb}`, description: t.name, tone: "success" });
  };

  return (
    <div className="adm-stack">
      <div className="adm-toolbar">
        <p className="adm-muted">Group people to share records: a role scoped to its team sees what anyone in the team, or a team below it, owns.</p>
        {manage && (
          <Button variant="primary" onClick={() => setForm({})}>
            <Plus size={16} aria-hidden /> New team
          </Button>
        )}
      </div>
      {teams.data.length === 0 ? (
        <EmptyState icon={Network} title="No teams yet" text="Make a team for each group that shares its records, like East and West, then sub-teams under them." action={manage ? <Button onClick={() => setForm({})}>Create a team</Button> : undefined} />
      ) : (
        <div className="adm-split">
          <nav aria-label="Teams" className="adm-split-nav">
            <ul className="adm-tree">
              {tree.map(({ team: t, depth }) => (
                <li key={t.id}>
                  <button type="button" className="adm-tree-item" aria-current={t.id === selectedId || undefined} style={{ paddingLeft: `calc(var(--space-3) + ${depth} * var(--space-5))` }} onClick={() => select(t.id)}>
                    {depth > 0 && <ChevronRight size={14} aria-hidden className="adm-muted" />}
                    <span className="adm-tree-name">{t.name}</span>
                    <span className="adm-muted">{t.member_count}</span>
                    <span className="sr-only">{t.member_count === 1 ? "member" : "members"}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="adm-split-main">
            {selected ? (
              <TeamPanel key={selected.id} team={selected} teams={teams.data} manage={manage} onEdit={() => setForm({ team: selected })} onAddSub={() => setForm({ parent: selected.id })} onChanged={teams.reload} onDeleted={() => (select(null), teams.reload())} />
            ) : (
              <EmptyState icon={Network} title="Pick a team" text="See and change its members, or where it sits." />
            )}
          </div>
        </div>
      )}
      {form && <TeamForm open onOpenChange={(o) => !o && setForm(null)} teams={teams.data} team={form.team} parent={form.parent} onDone={(t) => done(t, form.team ? "saved" : "created")} />}
    </div>
  );
}

function TeamPanel({ team, teams, manage, onEdit, onAddSub, onChanged, onDeleted }: { team: Team; teams: Team[]; manage: boolean; onEdit: () => void; onAddSub: () => void; onChanged: () => void; onDeleted: () => void }) {
  const toast = useToast();
  const detail = useLoad(() => getTeam(team.id), [team.id, team.member_count, team.name, team.parent_team_id]);
  const members = useLoad(listMembers, [], manage);
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [removing, setRemoving] = useState(false);
  const subs = teams.filter((t) => t.parent_team_id === team.id);
  const inTeam = new Set((detail.data?.members ?? []).map((m) => m.user_id));
  const addable = (members.data ?? []).filter((m) => !inTeam.has(m.user_id));
  useEffect(() => setBusy(null), [team.id]);

  const add = async (userId: string) => {
    setBusy("add");
    try {
      await addTeamMember(team.id, userId);
      detail.reload();
      onChanged();
    } catch (e) {
      toast({ title: "Could not add them", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };
  const remove = async (userId: string, name: string) => {
    setBusy(userId);
    try {
      await removeTeamMember(team.id, userId);
      detail.reload();
      onChanged();
      toast({
        title: "Removed from the team",
        description: name,
        tone: "success",
        action: { label: "Undo", onClick: () => void addTeamMember(team.id, userId).then(() => (detail.reload(), onChanged())) },
      });
    } catch (e) {
      toast({ title: "Could not remove them", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };
  const destroy = async () => {
    setRemoving(true);
    try {
      await deleteTeam(team.id);
      toast({ title: "Team deleted", description: team.name, tone: "success" });
      onDeleted();
    } catch (e) {
      toast({ title: "Could not delete the team", description: whatWentWrong(e), tone: "danger" });
      setRemoving(false);
      setDeleting(false);
    }
  };

  const path = teamPath(teams, team.id);
  return (
    <section className="adm-panel" aria-labelledby="team-title">
      <div className="adm-panel-head">
        <div>
          <h2 id="team-title" className="adm-h2">
            {team.name}
          </h2>
          <p className="adm-muted">{path === team.name ? "A top level team" : path}</p>
        </div>
        {manage && (
          <div className="adm-actions">
            <Button size="sm" onClick={onEdit}>
              <Pencil size={14} aria-hidden /> Edit
            </Button>
            <Button size="sm" onClick={onAddSub}>
              <Plus size={14} aria-hidden /> Sub-team
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDeleting(true)} aria-label={`Delete ${team.name}`}>
              <Trash2 size={14} aria-hidden /> Delete
            </Button>
          </div>
        )}
      </div>
      {subs.length > 0 && (
        <p className="adm-chips">
          <span className="adm-muted">Sub-teams:</span>
          {subs.map((s) => (
            <Badge key={s.id}>{s.name}</Badge>
          ))}
        </p>
      )}
      <h3 className="adm-h3">Members</h3>
      {detail.error ? (
        <LoadError what="the team" error={detail.error} retry={detail.reload} />
      ) : !detail.data ? (
        <Loading label="Loading members" rows={2} height={40} />
      ) : detail.data.members.length === 0 ? (
        <p className="adm-muted">Nobody is in this team yet.</p>
      ) : (
        <ul className="adm-people">
          {detail.data.members.map((m) => (
            <li key={m.user_id}>
              <span className="adm-person">
                <strong>{personName(m)}</strong>
                <span className="adm-muted">{m.email}</span>
              </span>
              {manage && (
                <Button size="sm" variant="ghost" loading={busy === m.user_id} onClick={() => void remove(m.user_id, personName(m))} aria-label={`Remove ${personName(m)} from ${team.name}`}>
                  <UserMinus size={14} aria-hidden /> Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {manage && detail.data && (
        members.error ? (
          <p className="adm-note" data-tone="warning">The people of the workspace could not be loaded. {whatWentWrong(members.error)}</p>
        ) : addable.length > 0 ? (
          <Combobox
            label={`Add to ${team.name}`}
            items={addable.map((m) => ({ value: m.user_id, label: personName(m), hint: m.email }))}
            value={null}
            onChange={(v) => void add(v)}
            disabled={busy === "add"}
            trigger={
              <Button loading={busy === "add"}>
                <UserPlus size={16} aria-hidden /> Add member
              </Button>
            }
          />
        ) : members.data ? (
          <p className="adm-muted">Everyone in the workspace is in this team.</p>
        ) : null
      )}
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${team.name}?`}
        description={`Its ${detail.data?.members.length ?? team.member_count} memberships go with it.${subs.length ? ` Its sub-teams (${subs.map((s) => s.name).join(", ")}) move up a level.` : ""} Roles scoped to the team stop seeing what its members own.`}
        confirm="Delete team"
        busy={removing}
        onConfirm={() => void destroy()}
      />
    </section>
  );
}
