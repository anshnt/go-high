// Team and roles > Members: the people who can act in this workspace, with their role (changed here) and teams.
import { SearchX, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { fuzzy, rank } from "../lib/fuzzy";
import { useMe } from "../lib/session";
import { Badge, Button, EmptyState, Input, Select, Table, useToast, type Column } from "../ui";
import { assignRole, listMembers, listRoles, type Member, type Role } from "./api";
import { LoadError, Loading, personName, useLoad } from "./common";

export function Members() {
  const toast = useToast();
  const me = useMe();
  const { can } = useCan();
  const manage = can("members.manage");
  const members = useLoad(listMembers, []);
  const roles = useLoad(listRoles, []);
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState<string | null>(null);

  const shown = useMemo(() => rank(members.data ?? [], (m) => fuzzy(query, `${m.name ?? ""} ${m.email} ${m.role.name} ${m.teams.map((t) => t.name).join(" ")}`)), [members.data, query]);
  const options = (roles.data ?? []).map((r) => ({ value: r.id, label: r.name }));

  const change = async (m: Member, role: Role) => {
    setSaving(m.user_id);
    try {
      await assignRole(m.user_id, role.id);
      members.setData((list) => list?.map((x) => (x.user_id === m.user_id ? { ...x, role: { id: role.id, key: role.key, name: role.name } } : x)) ?? null);
      toast({ title: "Role changed", description: `${personName(m)} is now ${role.name}. It applies on their next request.`, tone: "success" });
    } catch (e) {
      toast({ title: "Could not change the role", description: whatWentWrong(e), tone: "danger", duration: 8000 });
    } finally {
      setSaving(null);
    }
  };

  if (members.error && !members.data) return <LoadError what="members" error={members.error} retry={members.reload} />;
  if (!members.data) return <Loading label="Loading members" rows={4} height={44} />;
  if (members.data.length === 0) return <EmptyState icon={Users} title="Nobody here yet" text="People appear here once they have a role in this workspace." />;

  const columns: Column<Member>[] = [
    {
      key: "person",
      header: "Person",
      cell: (m) => (
        <span className="adm-person">
          <strong>
            {personName(m)}
            {me?.user.id === m.user_id && <span className="adm-muted"> (you)</span>}
          </strong>
          <span className="adm-muted">{m.email}</span>
        </span>
      ),
    },
    {
      key: "role",
      header: "Role",
      cell: (m) =>
        m.implicit ? (
          <span className="adm-inline">
            {m.role.name} <Badge tone="accent">Organization {m.role.key}</Badge>
          </span>
        ) : manage && roles.data ? (
          <div className="adm-role-select" aria-busy={saving === m.user_id || undefined}>
            <Select
              aria-label={`Role of ${personName(m)}`}
              value={m.role.id}
              options={options}
              disabled={saving === m.user_id}
              onValueChange={(v) => {
                const role = roles.data?.find((r) => r.id === v);
                if (role && v !== m.role.id) void change(m, role);
              }}
            />
          </div>
        ) : (
          m.role.name
        ),
    },
    {
      key: "teams",
      header: "Teams",
      cell: (m) =>
        m.teams.length ? (
          <span className="adm-chips">
            {m.teams.map((t) => (
              <Badge key={t.id}>{t.name}</Badge>
            ))}
          </span>
        ) : (
          <span className="adm-muted">No team</span>
        ),
    },
  ];

  return (
    <div className="adm-stack">
      <div className="adm-toolbar">
        <div className="adm-search">
          <Input type="search" aria-label="Search members" placeholder="Search by name, email, role or team" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <p className="adm-muted adm-count" aria-live="polite">
          {shown.length === members.data.length ? `${members.data.length} ${members.data.length === 1 ? "person" : "people"}` : `${shown.length} of ${members.data.length}`}
        </p>
      </div>
      {roles.error ? <p className="adm-note" data-tone="warning">The roles could not be loaded, so roles cannot be changed right now. {whatWentWrong(roles.error)}</p> : null}
      <Table
        caption="Members of this workspace"
        columns={columns}
        rows={shown}
        rowId={(m) => m.user_id}
        className="adm-table"
        empty={<EmptyState icon={SearchX} title="Nobody matches" text={`No member matches "${query}".`} action={<Button onClick={() => setQuery("")}>Clear search</Button>} />}
      />
      <p className="adm-note">
        Organization owners and admins are admins of every workspace; change their role in the organization. A role decides what someone may do; see exactly what with the{" "}
        <Link to="/settings/team/access">access check</Link>.
      </p>
    </div>
  );
}
