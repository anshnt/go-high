import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { lazy, Suspense, useState } from "react";
import { workspaceId } from "../lib/api";
import { creatableOrgs, selectWorkspace, useMe, type Workspace } from "../lib/session";
import { useStore } from "../lib/store";
import { Badge, Button, DropdownMenu, MenuItem, MenuLabel, MenuSeparator } from "../ui";

const CreateWorkspace = lazy(() => import("./CreateWorkspace").then((m) => ({ default: m.CreateWorkspace })));

const roleLabel = (role: Workspace["role"]) => (role === "admin" ? "Admin" : "Member");

/** Top-bar menu: the user's real workspaces from /api/me, with a role badge each. */
export function WorkspaceSwitcher() {
  const me = useMe();
  const currentId = useStore(workspaceId);
  const [creating, setCreating] = useState(false);
  if (!me) return null;

  const active = me.workspaces.find((w) => w.id === currentId) ?? me.workspaces[0];
  // One organization: a plain list. Several: grouped under the organization name.
  const groups =
    me.orgs.length > 1
      ? me.orgs.map((o) => ({ label: o.name, items: me.workspaces.filter((w) => w.org_id === o.id) })).filter((g) => g.items.length)
      : [{ label: "Workspaces", items: me.workspaces }];

  return (
    <>
      <DropdownMenu
        align="start"
        label="Workspaces"
        trigger={
          <Button variant="ghost" className="sh-workspace" aria-label={`Switch workspace, current: ${active?.name ?? "none"}`}>
            <span className="sh-workspace-name">{active?.name ?? "No workspace"}</span>
            <ChevronsUpDown size={14} aria-hidden />
          </Button>
        }
      >
        {groups.map((g, i) => (
          <div key={g.label} role="group" aria-label={g.label}>
            {i > 0 && <MenuSeparator />}
            <MenuLabel>{g.label}</MenuLabel>
            {g.items.map((w) => (
              <MenuItem key={w.id} onSelect={() => selectWorkspace(w.id)}>
                <span className="sh-ws-name">{w.name}</span>
                {w.id === active?.id && <span className="sr-only">(current)</span>}
                <Badge tone={w.role === "admin" ? "accent" : "neutral"}>{roleLabel(w.role)}</Badge>
                <span className="sh-ws-check" aria-hidden>
                  {w.id === active?.id && <Check size={14} />}
                </span>
              </MenuItem>
            ))}
          </div>
        ))}
        {creatableOrgs(me).length > 0 && (
          <>
            <MenuSeparator />
            {/* Let the menu release focus before the dialog takes it. */}
            <MenuItem icon={<Plus size={16} aria-hidden />} onSelect={() => setTimeout(() => setCreating(true), 50)}>
              Create workspace
            </MenuItem>
          </>
        )}
      </DropdownMenu>
      {creating && (
        <Suspense fallback={null}>
          <CreateWorkspace me={me} onClose={() => setCreating(false)} />
        </Suspense>
      )}
    </>
  );
}
