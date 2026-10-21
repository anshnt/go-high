// Settings > Team and roles: the people of the workspace and their roles, the roles of the organization, the teams and
// sub-teams, and the access check ("what can this user see?"). One page, four tabs, each with its own address
// (/settings/team/members, /roles, /roles/:id, /teams, /access).
import { useNavigate, useParams } from "react-router";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui";
import { AdminHeader, Denied, Loading, useGate } from "./common";
import { Members } from "./Members";
import { RoleEditor } from "./RoleEditor";
import { Roles } from "./Roles";
import { Simulator } from "./Simulator";
import { Teams } from "./Teams";
import "./admin.css";

const TABS = [
  { id: "members", label: "Members" },
  { id: "roles", label: "Roles" },
  { id: "teams", label: "Teams" },
  { id: "access", label: "Access check" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export function TeamSettings() {
  const { tab: raw, id } = useParams();
  const navigate = useNavigate();
  const gate = useGate("members.read");
  const tab: Tab = (TABS.find((t) => t.id === raw)?.id ?? "members") as Tab;

  if (tab === "roles" && id) return <RoleEditor id={id} />;

  const tabs = (
    <TabsList aria-label="Team and roles">
      {TABS.map((t) => (
        <TabsTrigger key={t.id} value={t.id}>
          {t.label}
        </TabsTrigger>
      ))}
    </TabsList>
  );

  return (
    <Tabs value={tab} onValueChange={(v) => navigate(`/settings/team/${v}`)} activationMode="manual" className="sh-page adm-page">
      <AdminHeader title="Team and roles" description="Who works in this workspace, what each role may see and do, and how people are grouped." views={tabs} />
      {gate === "wait" ? (
        <Loading label="Loading" rows={4} height={44} />
      ) : gate === "no" ? (
        <Denied what="see the people, roles and teams" capability="members.read" />
      ) : (
        <TabsContent value={tab} className="adm-tab">
          {tab === "members" && <Members />}
          {tab === "roles" && <Roles />}
          {tab === "teams" && <Teams />}
          {tab === "access" && <Simulator />}
        </TabsContent>
      )}
    </Tabs>
  );
}
