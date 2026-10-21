// One-click starters for an empty Automations page (docs/UI.md: empty states teach). Each is a graph the server accepts
// in any workspace: it names only system fields and the record's owner, nothing a workspace may not have.
import { blank, type Graph } from "./graph.ts";

export type Starter = { id: string; name: string; text: string; graph: Graph };

const customer = { field: "lifecycle", op: "is", value: "customer" };

export const STARTERS: Starter[] = [
  {
    id: "form_follow_up",
    name: "Follow up a form submission",
    text: "Gives the owner a call task, waits 2 days, and tells them if the contact has not become a customer.",
    graph: {
      trigger: { event: "form.submitted", object: "contact", filter: {}, data: {} },
      start: "call_task",
      nodes: {
        call_task: { type: "action", action: "task.create", config: { title: "Call {{display_name}}", due: { days: 1 }, assignee: "owner", priority: "high" }, next: "wait_2_days" },
        wait_2_days: { type: "wait", config: { duration: { days: 2 } }, next: "is_customer" },
        is_customer: { type: "condition", config: { filter: customer }, branches: { yes: null, no: "nudge_owner" } },
        nudge_owner: { type: "action", action: "notify.user", config: { user_id: "owner", title: "{{display_name}} has not become a customer yet", body: "" }, next: null },
        became_customer: { type: "goal", label: "Became a customer", config: { filter: customer, otherwise: "end" }, next: null },
      },
    },
  },
  {
    id: "new_lead",
    name: "Welcome a new lead",
    text: "When a lead is created, gives the owner a welcome task and a reminder a day later.",
    graph: {
      trigger: { event: "record.created", object: "contact", filter: { field: "lifecycle", op: "is", value: "lead" }, data: {} },
      start: "welcome_task",
      nodes: {
        welcome_task: { type: "action", action: "task.create", config: { title: "Welcome {{display_name}}", due: { hours: 4 }, assignee: "owner", priority: "medium" }, next: "wait_1_day" },
        wait_1_day: { type: "wait", config: { duration: { days: 1 } }, next: "remind_owner" },
        remind_owner: { type: "action", action: "notify.user", config: { user_id: "owner", title: "Check in with {{display_name}}", body: "" }, next: null },
      },
    },
  },
  {
    id: "deal_moved",
    name: "Hand over a moved deal",
    text: "When a deal changes stage, gives its owner a task to follow it up.",
    graph: {
      trigger: { event: "deal.stage_changed", object: "deal", filter: {}, data: {} },
      start: "follow_up",
      nodes: { follow_up: { type: "action", action: "task.create", config: { title: "Follow up {{display_name}}", due: { days: 1 }, assignee: "owner", priority: "none" }, next: null } },
    },
  },
  { id: "blank", name: "Start from scratch", text: "An empty workflow: pick what starts it, then add steps.", graph: blank() },
];
