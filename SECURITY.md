# Security

This is proprietary software of SROT AI LLP. Report a vulnerability privately to
sjain@srot-ai.com with steps to reproduce; do not open a public issue.

## Tenant isolation

- Every tenant table has row level security with `FORCE ROW LEVEL SECURITY`. Request handlers run as
  `gohigh_app`, a `NOLOGIN`, non-superuser, non-owner role without `BYPASSRLS`. The user, organization
  and workspace context is set with `SET LOCAL` per transaction, so a missing `WHERE` clause cannot leak
  another tenant's rows.
- The workspace a request acts on (`X-Workspace-Id`) is resolved through row level security first. A
  workspace the user cannot see is a 404 before any context is set.
- Tests call every `/api` route as one tenant with another tenant's ids, and query every tenant table
  unfiltered as `gohigh_app`, asserting nothing crosses over.

## Roles and permissions

Row level security separates tenants; what a user may do inside a workspace is `app/permissions.py` (ADR 0004).

- Every `/api/v1` route declares the capability it needs and refuses a role without it with a 403 that names it. A
  test walks the route table and fails on a route that declares none, and calls each route as a Viewer. The record
  engine checks again where the data is (writes, deletes, every query), so workflows and AI tools, which run as a
  named actor with a role (`Automation`), cannot reach further than the role says.
- A record outside a role's scope is a 404 on every path (reads, lists, counts, search, saved views, expansion,
  association filters, trash, tag counts, timeline), never a 403, so its existence does not leak. Out of scope is
  also the default: a role with no rule for an object sees none of its records.
- Hidden fields are not returned and, for that role, do not exist: not listed in the schema, not filterable,
  sortable, searchable (a role that hides fields searches without the full text index) or writable. A display name
  built from one is rebuilt from the rest, and the events of the timeline and the audit log are served without them.
- Roles belong to the organization and a change reaches every workspace, so only organization owners and admins
  create, change or delete them. The database enforces the dangerous parts too: request handlers cannot change a
  role's key or system flag, create or delete a system role, or edit Owner and Admin or their rules; a workspace
  member must be a member of its organization and hold one of its roles. Unless you are an organization owner or
  admin you cannot give someone a role that can do more than yours.
- Request handlers can read the name and email of the people of their workspace (its members and the owners and
  admins of its organization) for member lists, team lists and the simulator. The same `users` rows hold password
  hashes, which handlers never select outside sign in; a SQL level bug could still read a peer's hash. Move hashes to
  a table of their own if that is a risk you want closed.
- The simulator (`/api/v1/permissions/explain`) needs `members.manage`, because it says who owns records the asker
  may not see.

## Audit log

- The audit log is the event log. Request handlers (`gohigh_app`) have INSERT and SELECT on `events` and nothing
  else, not even in the broad scope sign up uses; only the owner role (migrations, the worker) could change it, and
  nothing does. A test attempts UPDATE, DELETE and TRUNCATE.
- Configuration writes (objects, fields, association types, roles, teams, role assignments, webhooks) and security
  events (password changes, ended sessions, written to every workspace the user can act in) are events, written in
  the transaction of the change. A webhook's URL, which may carry a token, is never put in an event.
- `audit.read` is an administrator's capability: it shows the events of every record of the workspace whatever a
  role's scope says, minus the fields the role hides. Exporting the log is itself an event (`audit.exported`).

## Accounts and sessions

- Passwords hashed with scrypt (per-user salt, parameters stored with the hash so they can be raised).
  Unknown emails burn a dummy hash so timing does not reveal which accounts exist.
- Sessions are random tokens; only their SHA-256 is stored. Idle timeout, absolute expiry and revocation
  are checked in SQL on every request; revoking a session takes effect on the next request.
- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure` unless `COOKIE_SECURE=0` (local http only).
- Cookie-authenticated writes whose `Origin` is not in `PUBLIC_URL` are refused (CSRF).
- Failed sign-ins are throttled per email and IP (5 per 15 minutes) and per email across all IPs (20).
  `X-Forwarded-For` is trusted only from `FORWARDED_ALLOW_IPS`; never set it to `*`.
- Magic links are single use, expire after 15 minutes, are consumed by POST (so mail scanners cannot burn
  them), and requesting one answers the same way whether or not the account exists.
- Sign up does not verify the address. The first magic-link sign-in does, and it clears any password and
  revokes every session created before it, so registering someone else's address gains nothing. Features
  that trust an email address (invitations, sending as the user) must require `email_verified`.
- `DEV_EXPOSE_MAGIC_LINKS=1` returns sign-in links in API responses. It is for tests and local development
  only and must never be set on a reachable server.

## Webhooks

- Targets must be `https` and resolve only to public addresses (no private, loopback, link-local, CGNAT,
  multicast or reserved space, IPv4-mapped forms included). The check runs at save time and again before every
  send, and the request connects to the address that was checked, so DNS rebinding cannot swap it. Redirects are
  never followed, every attempt has a 10 second total deadline, and only 2 KB of the response is kept.
- `ALLOW_HTTP_WEBHOOKS` and `WEBHOOK_ALLOW_IPS` switch parts of that off for tests and local development; never
  set them on a reachable server.
- Deliveries are signed with a per-endpoint secret generated by the server and shown once, at creation. It is
  stored readable (signing needs it) and never appears in events, the delivery log or responses other than the
  create response and a replay of that same create within 24 hours (idempotency keys).
- Request handlers (`gohigh_app`) can append to the event log and the job queue but cannot read the queue or
  change or delete events; only the worker (owner role) records delivery attempts.

## Repository

- `main` is protected: changes arrive by pull request with passing CI; force pushes and deletion are blocked.
- Dependabot watches Python, npm and Actions dependencies.
- Never commit secrets or `.env` files.
