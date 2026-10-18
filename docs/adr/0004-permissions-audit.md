# ADR 0004: Roles, record and field permissions, and the audit log

Status: accepted (2026-10-16). Module: 03 roles, permissions and audit log. Builds on ADR 0002 (filter language) and ADR 0003 (event log).

## Context

The incumbent has admin and user roles with per-module checkboxes and an "only assigned data" toggle. It keeps audit logs for about 60 days. Its most requested permissions feature (1.2k votes) is granular, reusable roles at the agency level. Field-level hiding of personal data and team-based visibility come up again and again. Row level security (module 02) already isolates tenants. This ADR covers what a user may do inside a tenant.

## Decision

### Two layers, two jobs

1. **Tenant isolation** stays in Postgres row level security (ADR 0001, module 02). It answers "which workspace's rows exist for this request" and never depends on application code.
2. **Permissions** live in the application, in one module (`app/permissions.py`). They answer which actions a user may take, which records they see, and which fields they can read or change. Every list, read, write, export and bulk job goes through it, including the API, workflows and AI tools.

### Roles

```
roles             id, org_id, key, name, description, is_system, capabilities text[], created_at
role_object_rules id, role_id, object_key, scope, hidden_fields text[], readonly_fields text[]
teams             id, workspace_id, name, parent_team_id
team_members      team_id, user_id
org_members.role_id, workspace_members.role_id   -- replace the fixed role strings
```

- Roles belong to the **organization**, so an agency defines "Account manager" once and uses it in every client workspace. A user's role is set per workspace membership. Org owners and admins keep implicit admin everywhere (module 02).
- System roles are seeded per org: Owner, Admin, Manager, Member, Viewer. They cannot be deleted. Custom roles start as a copy of one and are edited freely.
- **Capabilities** are plain strings, checked by name: `contacts.read`, `contacts.write`, `contacts.delete`, `contacts.export`, `deals.write`, `pipelines.manage`, `fields.manage`, `workflows.publish`, `messages.send`, `billing.manage`, `members.manage`, `webhooks.manage`, `audit.read`. The catalog is one Python list, and the UI groups it by module. An unknown capability in a role is a validation error, so typos cannot grant or hide anything silently.
- **Object rules** set, per object (`contact`, `deal`, custom objects), a record scope and field restrictions:
  - `scope`: `all`, `team` (owner is in one of my teams or their sub-teams), `own` (I am the owner or an assignee), `own_and_unassigned`, `none`.
  - `hidden_fields`: never returned, never filterable or sortable, never exported, never given to AI tools.
  - `readonly_fields`: returned, but writes are rejected with a field error.

### Enforcement

- `permissions.require(ctx, "contacts.export")` guards actions and returns 403 with the missing capability named.
- `permissions.record_filter(ctx, object)` returns a filter AST (ADR 0002) for the user's scope. The record engine ANDs it into every query, so lists, counts, search, saved views, exports and association expansion all see the same set. A record outside scope is a 404, never a 403, so its existence does not leak.
- `permissions.redact(ctx, object, values)` drops hidden fields on the way out. `permissions.check_write(ctx, object, changes)` rejects hidden and read-only fields on the way in. Filters and sorts on hidden fields are rejected at compile time.
- Workflows and AI agents run as a named actor with their own role (default: the workspace's "Automation" system role), never as "superuser", so their reach is visible and editable.
- Permission data is cached per request. A change to roles, memberships or teams applies on the user's next request.

### Simulator

`GET /api/v1/permissions/explain?user_id=&record_id=` (and the UI "What can this user see?") returns the user's role, capabilities, the scope rule per object, and for a given record the decision with its reason: "visible: owner is in team East, scope team". It uses the same functions as enforcement, so it cannot drift.

### Audit log is the event log

There is no separate audit table. Every write already emits an event in the same transaction (ADR 0003), with actor, subject and field changes. The audit UI and API are filtered views over `events`:

- Retention for audit is **13 months hot** (monthly partitions), then archived. This overrides the 90-day default in ADR 0003 for all event types.
- Reads are not audited, except sensitive ones that emit their own events: `record.exported`, `user.impersonated` (login-as, also shown to the workspace), `audit.viewed`, `api_key.created`.
- Events are append only: `gohigh_app` has INSERT but no UPDATE or DELETE on `events`, enforced by grants.
- Filters: actor, subject (record), type and time range. The CSV export emits `record.exported` itself.

## Consequences

- One permission module means one place to test. The isolation sweep in `test_isolation.py` gets a sibling: every `/api/v1` route is called as a Viewer and as a scope-`own` Member, asserting they see no out-of-scope record and no hidden field.
- Scope filters add `EXISTS` subqueries for `team` scope. That is fine at our sizes; materialize team membership per user if it shows up in profiles.
- Moving roles from fixed strings to `role_id` is a migration of `org_members` and `workspace_members`. It ships with this ADR's first slice, while there is no production data.

## As built in the first slice (2026-10-18)

Where the code differs from the sketch above:

- **Tables**: `role_object_rules` also carries `org_id` (like every reference between these tables carries its parent's id), and `roles` are created per organization at sign up by `roles_seed.add`, with the six system roles Owner, Admin, Manager, Member, Viewer and Automation. `org_members.role_id` and `workspace_members.role_id` replaced the role strings (migration 0005 mapped `owner`, `admin` and `member` to the system roles, and turns the custom ones back into `member` on the way down). Owner and Admin are locked (API and row level security); Manager, Member, Viewer and Automation can be edited; no system role can be deleted. Roles are changed by organization owners and admins only, since they reach every workspace.
- **Capabilities** are grouped per kind of record: `contacts`, `companies`, `deals` and `records` (custom objects), each with `read`, `write`, `delete` and `export`, and `delete` also covers the trash and restore. The rest of the catalog is in `permissions.CATALOG`; `export`, `pipelines.manage`, `workflows.publish`, `messages.send` and `billing.manage` guard routes that later modules add.
- **Object rules**: the `*` rule applies to any object without a rule of its own, and a role with no rule at all sees none of the records. Without `<kind>.read` the scope is `none`. `team` and `own_and_unassigned` include the records the user owns, and `own` also counts the user fields of an object as assignees. Hidden and read-only field lists may not name the built-in columns (`owner_id`, `display_name`, ...).
- **Hook names**: the scope hook is `scope_filter`, not `record_filter`. A team scope is the new filter node `{"team": [ids]}`, compiled to an `EXISTS` over `team_members`; the filter compiler takes `trusted=True` for the scope, which may name fields the caller cannot see.
- **Hidden fields** are, for the role, not fields at all (unknown field on a filter or sort, `is not a field` on a write, absent from the field list), and `q` searches without them. A hidden field that is part of the display name makes `display_name` hidden too; the name shown is rebuilt from the readable fields. Read-only fields are a 403 with field errors; hidden ones a 422. Timeline and audit event data is redacted the same way, a link to a record out of scope is dropped from a timeline, and saved views that use a hidden field do not exist for the role. Tag usage counts the records the caller may see.
- **Simulator** needs `members.manage`, and its reason strings come from the facts of the scope while its decision comes from the same SQL condition the engine uses.
- **Audit**: not done yet are the 13 month retention and archive (events are kept), `audit.viewed`, `record.exported` (there is no export route yet) and `user.impersonated` and `api_key.created` (the features do not exist). `audit.read` shows events of every record regardless of scope, with hidden fields removed. Saved views are not audited. Security events are written once per workspace the user can act in.
- **People**: the `users` table has a policy that lets request handlers read the people of the current workspace (its members and the owners and admins of its organization), for member and team lists. A person can only be made a member of a workspace of an organization they belong to, with a role of that organization (policy), and unless the person assigning is an organization owner or admin the role cannot hold a capability they lack.
