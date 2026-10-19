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
  engine checks again where the data is (writes, deletes, every query), so workflows and AI tools, which will run as
  a named actor with a role (`Automation`), cannot reach further than the role says.
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
  admins of its organization) for member lists, team lists and the simulator. Password hashes are not in `users`: they
  are in `user_credentials`, where a session can read and change only its own user's row (sign up, sign in and the
  first magic link, which run in the pre-auth scope, do the rest), so even a SQL level bug in a handler cannot read a
  peer's hash. A test reads as a peer and as the app role to check it.
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

## Inbound webhooks (messaging)

- `/api/hooks/<provider>/<channel id>` is public, so nothing but the provider's signature lets a request in. The
  adapter verifies it on the raw body before the body is parsed, with a constant-time comparison: Twilio
  `X-Twilio-Signature` (HMAC-SHA1 over the URL as configured in the console and the parameters), Telnyx Ed25519 over
  `timestamp|body`, Mailgun HMAC-SHA256 over `timestamp + token`, Meta `X-Hub-Signature-256` (HMAC-SHA256). Where the
  provider sends a timestamp, one more than 5 minutes off is refused. Unsigned, wrongly signed, stale or tampered
  requests are a 401 and a log line that names the channel and carries neither the body nor any secret. An SMTP channel
  has no webhook, so every call to it is refused.
- The channel is found by its unguessable id in the system scope (a read-only policy on `channels`); the request moves
  into the channel's workspace only after the signature verified. An unknown, disabled or other provider's channel
  is a 404. Meta's handshake echoes the challenge only when the verify token matches and the challenge is a plain token.
- A replayed webhook (Mailgun's token is not remembered) changes nothing: a message is unique per channel and provider
  message id, and a delivery report only moves a message forward.
- STOP, START and HELP are handled before the inbox. An opt-out (STOP, an email unsubscribe or complaint) blocks sends on
  that channel kind until the contact's own START, and staff cannot clear it. Consent is checked when a reply is queued
  and again when the worker sends it.

## Secrets at rest

- A channel's API keys and passwords are encrypted with AES-256-GCM under a key derived (HKDF-SHA256) from `SECRET_KEY`,
  with the row and workspace as associated data, so a ciphertext copied to another row does not open. They are never in
  a channel's `config`, which refuses settings it does not know.
- Request handlers (`gohigh_app`) can write the `secrets` table but have no `SELECT` on its ciphertext column, so a bug in
  a route cannot return one. Only the worker and the code that verifies a webhook, sends or tests a channel decrypt, on
  the owner role. No API response, event, job payload or log line carries a secret; the API says only whether a channel
  has any.
- Set `SECRET_KEY` in production, to the same value on every replica and the worker. Changing it makes stored secrets
  unreadable until they are re-encrypted (there is no rotation job yet). The signing secrets of webhook endpoints
  (above) are still stored readable.

## Webchat and realtime

- The public chat endpoints take no cookie. A visitor is a token signed with `SECRET_KEY` for one widget key and 30 days;
  it reads only its own conversation and never internal notes. Any origin may call them because there is no ambient
  credential to abuse. Requests are limited per minute per IP and per widget key in Postgres (refused calls from one IP do
  not use up the widget's budget), and a hidden field that only a bot fills in is dropped silently. The widget renders
  text with `textContent` only. A widget key is public by design: it opens a chat, nothing else.
- `GET /api/v1/stream` carries ids only and no content, so permissions apply when the client refetches. A stream ends
  after 30 minutes, which is when a revoked session stops it.

## Public forms

- The public endpoints (`/api/public/forms/...`, the hosted page `/f/{key}` and `/embed.js`) need no session. A request
  starts in a narrow system scope that can only read `forms` (the one policy that scope has; every other table shows it
  nothing), finds the form by its public key (a random URL-safe string, never the internal id) and then moves to that
  form's workspace, so every later query is confined by row level security like any other. A guessed id, another
  workspace's key, a response id of another form or a resume token used on another form is a 404; a draft or trashed
  form is a 404 and a closed one a 410. Every public answer is `Cache-Control: no-store`.
- CORS: any origin may call these endpoints (`Access-Control-Allow-Origin: *`) and `Access-Control-Allow-Credentials` is
  never sent; the runtime calls with `credentials: "omit"`. The admin API (`/api/v1/forms`) is not opened up.
- Spam protection is on by default. A filled honeypot field is told it worked and nothing is stored. A response completed
  faster than `FORM_MIN_FILL_SECONDS` (3) after the page was opened is refused (429); the time comes from a signed
  token (HMAC under `SECRET_KEY`, bound to the form, valid for 7 days), so it cannot be forged or moved to another
  form, though one token may be reused inside its week: the rate limit bounds that. Requests are limited per form,
  visitor and minute by a Postgres counter, and every form has a body size limit that is enforced while the body streams
  in (413). The visitor is a keyed hash of the client address, so counters and consent evidence never hold a raw address;
  behind a proxy set `FORWARDED_ALLOW_IPS` or every visitor looks like the proxy.
- A response in progress is addressed by its resume token: random, stored only as a SHA-256, returned once when the
  response starts. Whoever holds the link can read the answers saved so far and complete that response, so treat resume
  links as secrets. A completed response can no longer be resumed or changed, and completing it twice does nothing.
- A public form writes to contacts, so it is a way for anyone to change data. It can only write the contact fields its
  questions map to (checked when a version is saved and validated by the record engine's own types), an empty answer
  never clears a field, and `settings.contact.existing` defaults to `fill_empty`, which adds to a known contact without
  overwriting anything. Someone who knows a contact's email can still submit a form and, in the explicit `update` mode,
  change those mapped fields; choose `update` only for forms people fill in about themselves.
  `settings.double_submission = block` stops one contact from answering twice. The contact is written as the
  organization's Automation role, so what a form may do to contacts is what that role may do, and removing
  `contacts.write` from it stops forms from writing contacts.
- Forms are governed by `forms.read`, `forms.write`, `forms.publish`, `forms.delete`, `responses.read` and
  `responses.export`. Changing the status of a form or the settings of a live one needs `forms.publish`, so a Member
  cannot redirect or reopen a live form. Responses and the timeline show a role only what its record permissions allow of
  the contact (hidden fields, out of scope contacts).
- Quiz right answers, points and the contact mapping are not in the public definition, and scores are computed on the
  server. The runtime builds its page from text nodes (nothing in a definition or an answer is ever markup), refuses a
  redirect that is not http or https (the server refuses to save one too) and the hosted page carries a strict
  Content-Security-Policy.
- Consent boxes are stored as evidence of opt-in (the words shown, when, the form and the visitor hash); the hash is not
  put in events or sent to webhooks.
- CSV export neutralizes spreadsheet formula injection: any text cell or header that starts with `=`, `+`, `-`, `@`, a
  tab, a carriage return or a line feed gets a leading apostrophe (numbers are written as they are), so a response
  cannot run a formula when someone opens the file.
- Form versions are immutable: `gohigh_app` can insert but not update or delete them, nor delete forms, responses or
  views (a form goes to the trash); only the per-minute rate counters are deleted by requests.

## Public booking endpoints

`/api/public/calendars`, `/api/public/bookings` and `/api/public/feeds` need no sign in (calendars and booking, module
16), so they are kept narrow.

- The workspace comes from the link and nothing else: the handler resolves the workspace handle in the pre-auth scope,
  then narrows the session to that workspace, so row level security confines every later query. A visitor can reach
  only what a link names: a calendar's public settings (its name, description, lengths, locations, questions, host
  names for personal, collective and class calendars) and its open times.
- A booking's link carries a 256 bit secret after the workspace id, and a private feed link carries one too. Only their
  SHA-256 is stored, so a database read does not give out working links; a feed link is shown once and a new one
  replaces it. Looking a link up needs the secret: a token with the right workspace and a wrong secret, or another
  workspace's id, is a 404, the same as no booking.
- Booking requests are held back by a honeypot field (a filled one gets a believable 201 and stores nothing) and a rate
  limit per calendar and visitor, with a ceiling per calendar. The visitor is a SHA-256 of their address keyed with
  `SECRET_KEY`, so the table that counts attempts holds no addresses. Refused and failed attempts count too.
- Writes by a visitor run as the workspace's Automation role, with no user, so the contact a booking makes or fills in
  is bound by that role's permissions and appears in the audit log as written by the system. An existing contact is
  filled in where a field is blank and never overwritten.
- Two bookings for one time are serialized by row locks taken before anyone reads who is free, and a test books the same
  time from eight threads at once. Cancel and reschedule links stop working inside the calendar's cutoff and after the
  meeting.
- The routes answer any origin (`Access-Control-Allow-Origin: *`) because the booking widget is embedded in other
  people's sites without an iframe. They set no cookies and read none, so the open origin exposes nothing a link does
  not, and responses are `Cache-Control: no-store`. Booking events carry ids, times and the calendar name, never the
  invitee's name, email or phone, which belong to the contact.
- Inside the app a booking shows the invitee's name, email and phone to anyone with `calendars.read`, as the person
  who made it gave them for that meeting; the link to the contact record is shown only when the caller's record scope
  lets them see that contact, and hidden fields stay hidden there.

## Workflows

- A workflow acts as a named actor with a role, never as a superuser: its steps run as the organization's Automation
  role (ADR 0004) through the record engine's own write paths, so what a workflow may do is what that role may do, and an
  admin can read and edit it. Every change it makes is an event with `actor_type` `workflow` and the workflow's id, so
  the timeline and the audit log say "by workflow X" (the audit filter by actor finds all of a workflow's work). Taking
  `tags.write`, `tasks.write`, `contacts.write` or `messages.send` from Automation makes those steps fail naming the
  capability; its record scope and hidden or read-only fields apply to what a step reads and writes.
- A workflow cannot be used to read or write what its author may not: the filters, update values and `{{field_key}}`
  text of a graph are checked against the fields the author can see when it is saved (a hidden field does not exist for
  them), and a hidden field of the Automation role cannot be merged into text at run time either.
- Runs and traces are shown only while the caller may see the run's record (a 404 otherwise, so a run does not give its
  record away), and a role that hides any field gets the trace without its `input` and `output`, which carry what was
  set and sent. A test run of a record needs the same visibility. Reading workflows is `workflows.read`; editing,
  testing, cancelling and retrying is `workflows.write`; publishing, pausing, resuming, archiving, rotating the signing
  secret and changing the settings of a live workflow is `workflows.publish`.
- The webhook action leaves the system with workspace data, so it is as guarded as a webhook: the address must be https
  and resolve to public addresses only, checked when the version is saved, again when the step queues the delivery and
  again, after DNS, when the worker posts (no redirects, 10 second deadline, 2 KB of the response kept; the same switches
  as webhooks for local development). What leaves is the run, the record's id, type and name, and only the `payload`
  keys the author mapped. A delivery is signed with the workflow's own secret (`whsec_...`, shown once when the workflow
  is created, replaced by `rotate-secret`; stored readable because signing needs it, like a webhook endpoint's) and
  carries an idempotency key, so a receiver can drop a repeat. Request handlers can queue deliveries but only the worker
  updates them.
- A webhook's address is part of the graph, so whoever has `workflows.read` can read it (and the step's trace shows
  it; the delivery list shows the host only): keep tokens out of the URL until secret references exist (module 33). The
  check log behind "why did it not enter" quotes what a record has, so a role that hides fields gets the outcome and no
  reason.
- Sending is exactly once and consent-bound: a message is queued through the inbox's own path, with the opt-out, do not
  disturb, frequency cap and quiet hours checks of any reply (again when the worker sends), under a unique idempotency
  key `run:node`; a step that runs twice finds its row. A STOP is never overridden by a workflow.
- Enrollment is confined by row level security (the consumer works inside `acting`, the same scope a request gets), a
  workflow's own changes cannot start it, workflow events cannot start workflows, and a broken workflow is a logged miss,
  never an error that holds back the event consumers. Per workspace, at most `WORKFLOW_CONCURRENCY` steps run at once and
  a run is cut off at 500 steps.
- Versions are immutable (request handlers can insert them and set only the time one was published), the trace is append
  only, and nothing is deleted by a request; the check log is pruned by the worker after 7 days. A test of the sweep in
  `tests/test_isolation.py` calls every workflow route with another tenant's ids and checks every table and grant.

## Repository

- `main` is protected: changes arrive by pull request with passing CI; force pushes and deletion are blocked.
- Dependabot watches Python, npm and Actions dependencies.
- Never commit secrets or `.env` files.
