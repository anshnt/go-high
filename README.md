# go-high

> **Proprietary software. Copyright (c) 2026 SROT AI LLP. All rights reserved.** See [LICENSE](LICENSE).

An all-in-one growth platform for agencies and small businesses: CRM, unified inbox, phone and SMS, calendars, forms, automations, sites and funnels, email marketing, payments, reputation, social, reporting, courses and AI agents, plus an agency layer to run, template, white label and resell client workspaces.

**Status:** M0 Foundations in progress: platform scaffold (API, worker, job queue, web app, CI).

| Doc | What is in it |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | positioning, where we beat the incumbent, roadmap M0 to M4, how work is tracked |
| [docs/MODULES.md](docs/MODULES.md) | 44 modules: parity, improvements, done-when; one GitHub issue each |
| [docs/UI.md](docs/UI.md) | UI and UX principles, layout, visual language, PR checklist |
| [docs/adr](docs/adr/) | architecture decisions: [stack](docs/adr/0001-stack.md), [record engine](docs/adr/0002-record-engine.md), [events, webhooks and API](docs/adr/0003-events-webhooks-api.md), [permissions and audit](docs/adr/0004-permissions-audit.md), [conversations](docs/adr/0005-conversations.md), [workflows](docs/adr/0006-workflow-engine.md) |
| [docs/research](docs/research/) | four research reports on GoHighLevel's product, pricing, agency model and UX |

Work is tracked in [issues](https://github.com/anshnt/go-high/issues) grouped by [milestones](https://github.com/anshnt/go-high/milestones).

## Quick start

From a clone, build and run everything locally:

```bash
docker compose up --build
```

Open http://localhost:8000 (API docs at `/api/docs`). The `worker` service runs background jobs from the same image.

### Run a release

Releases publish `ghcr.io/anshnt/go-high:<version>` (and `:latest`). With this repository's `docker-compose.yml` and a `.env` copied from [.env.example](.env.example):

```bash
docker compose pull && docker compose up -d
```

Put it behind a TLS reverse proxy, set `PUBLIC_URL` to the https origin, `COOKIE_SECURE=1`, a long random `SECRET_KEY`, and `FORWARDED_ALLOW_IPS` to the proxy's address. `/api/health` reports the running version.

### Cutting a release

Tag `main` and push the tag; the Release workflow builds and publishes the image and creates the GitHub release with notes from the merged pull requests:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

### Without Docker

Needs Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22 and a PostgreSQL 16+ server.

```bash
cd backend && uv sync && DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/gohigh uv run uvicorn app.main:app --reload
```

```bash
cd backend && uv run python -m app.worker
```

```bash
cd frontend && npm install && npm run dev
```

The dev server proxies `/api` to `127.0.0.1:8000`; set `VITE_API_TARGET` to use another API. Sign in at `/signin`, or create an account at `/signup` (cookie-authenticated writes need the page origin in `PUBLIC_URL`, `127.0.0.1:5173` and `localhost:5173` are in the default). With `DEV_EXPOSE_MAGIC_LINKS=1` the sign-in screen shows a "Dev only: open sign-in link" button, so no mail is needed locally.

Tests use a real Postgres and create the `gohigh_test` database if it is missing (`TEST_DATABASE_URL` overrides the server):

```bash
cd backend && uv run pytest
```

Tests marked `perf` check speed (20 000 contacts, a filtered, sorted page in under 300 ms) and depend on the machine; leave them out with `uv run pytest -m "not perf"`.

Background jobs: register a handler with `@jobs.handler("kind")` and call `jobs.enqueue(db, "kind", payload, run_at=...)` inside your transaction. Failed jobs retry with exponential backoff (10 s doubling, capped at 1 hour) and become `dead` after `max_attempts`.

## Tenancy and auth

Organization > Brand > Workspace. A user belongs to orgs and optionally to single workspaces, each with a role (see [Roles, permissions and audit](#roles-permissions-and-audit)); org owners and admins are admins of every workspace in their org. Sign in with email + password or a magic link (`/api/auth/*`, `/api/me`); the session is an HttpOnly, SameSite=Lax cookie whose SHA-256 is the only thing stored. Sessions have an idle timeout and an absolute expiry, can be listed and revoked (`/api/auth/sessions`), and cookie-authenticated writes whose `Origin` header is not in `PUBLIC_URL` get a 403.

Choose the workspace per request with the `X-Workspace-Id` header. The `in_workspace` dependency (`app/security.py`) answers 404 for any workspace the user cannot access, then sets `app.workspace_id` and `app.org_id` for the request; routes that only need the user take the `user` dependency. `GET /api/workspaces/current` echoes the active workspace.

Isolation is enforced by Postgres, not by remembering a `WHERE`. Request handlers get a session from `app.security.user`, which runs every transaction as the NOLOGIN, non-owner role `gohigh_app` (`SET LOCAL ROLE`) with `app.user_id`, `app.org_id`, `app.workspace_id` set, and all tenant tables use `FORCE ROW LEVEL SECURITY`. Superusers and table owners bypass RLS, so migrations and the worker keep the owner role and the API never queries tenant tables with it. Sign up, sign in and magic links run as `gohigh_app` with `app.system = 'on'` (the `system` policy on each auth table); nothing else sets it.

A new workspace-scoped table in a module migration:

```sql
CREATE TABLE contacts (id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                       workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE, ...);
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace ON contacts USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON contacts TO gohigh_app;
```

`tests/test_isolation.py` calls every `/api` route as a user of one org with the ids of another and runs the same checks in SQL. Settings: `PUBLIC_URL` (comma separated allowed origins, the first builds magic links), `COOKIE_SECURE` (default 1; use 0 on plain http), `SESSION_IDLE_MINUTES`, `SESSION_ABSOLUTE_HOURS`, `MAGIC_LINK_MINUTES`, `LOGIN_MAX_FAILURES`, `LOGIN_WINDOW_MINUTES`. Magic links are logged at INFO until the email module exists; `DEV_EXPOSE_MAGIC_LINKS=1` also returns them in the response, so never set it outside local development and tests.

## API conventions

Public routes live under `/api/v1/<resource>` (ADR 0003) and follow these rules; the older `/api/auth`, `/api/me` and `/api/workspaces` routes keep their `{"detail": ...}` errors. The workspace comes from `X-Workspace-Id`, as above.

- **Errors**: every error on `/api/v1` is `{"error": {"code": "validation_failed", "message": "...", "fields": {"url": "must use https"}, "trace_id": "..."}}`. `fields` appears for validation errors, with dotted paths such as `event_types.0`. `trace_id` equals the `x-request-id` response header and the id in the logs. Raise `app.api.ApiError(status, code, message, fields)` for a coded error.
- **Pagination**: cursor only, `?limit=50&cursor=...` (1 to 200); lists answer `{"data": [...], "next_cursor": "..." | null}`, newest first. The cursor is opaque, a base64 sort key plus id signed with HMAC-SHA256 under `SECRET_KEY`, so it cannot be edited or forged (a bad one is a 400 `invalid_cursor`). Set `SECRET_KEY` to the same value on every API replica; the development default logs a warning. Use `app.api.paginate`.
- **Idempotency**: send `Idempotency-Key` (1 to 255 characters) on a POST. The first successful response is stored for 24 hours per workspace. The same key from the same user with the same method, path, query and body returns that response again with `Idempotent-Replayed: true`; the same key with anything else (another user included, since a response depends on what its user may see) is a 409 `idempotency_key_reused`. Failed requests store nothing, so they can be retried. A route opts in with `idem: Idem = Depends(idempotency)` (after its role dependency) and ends with `return idem.commit(201, body)`, which commits the work and the stored response in one transaction, so a retry can never repeat the work. A create that returns a secret returns the same secret on a replay.

## Events and webhooks

Every state change is an event, written by `events.emit(db, "type", "subject_type", subject_id, data, actor=("user", user_id))` in the same transaction as the change: it exists only if the change commits. The workspace is the request's (or pass `workspace_id=`). Each type needs a JSON schema in `backend/app/event_types/<type>.json`; `emit` refuses unknown types and data that misses required keys or adds unexpected ones, and a test fails when code emits a type without a schema. Types so far: `workspace.created`, `user.signed_up`, `webhook_endpoint.created`, `webhook.test`, and the record engine's `record.created`, `record.updated`, `record.deleted`, `record.restored`, `deal.stage_changed`, `association.created`, `association.deleted`, `tag.created`, `tag.updated`, `tag.deleted`, `tag.merged`, `tag.added`, `tag.removed`, and the configuration and security events of the audit log (`object.*`, `field.*`, `association_type.*`, `role.*`, `team.*`, `member.role_changed`, `webhook_endpoint.updated` and `.deleted`, `user.password_changed`, `auth.sessions_revoked`, `audit.exported`). A bulk change uses `events.emit_many(db, type, subject_type, [(subject_id, data), ...])`: one insert and one dispatcher wake-up.

Consumers read the log with `events.read_batch(db, "name")` and `events.advance(db, "name", batch)` in one transaction. A plain `id > last_id` cursor can skip an event whose transaction commits late; `read_batch` only returns events of transactions older than every transaction still open (`txid < pg_snapshot_xmin(pg_current_snapshot())`, in `(txid, id)` order), so nothing is skipped. The price is that one long transaction delays every consumer: keep request transactions short and commit bulk work in batches. Register a batch processor with `@events.consumer("name")`; the `events.dispatch` job (queued by every `emit`, run by the worker) calls each one and asks to be run again while events are waiting behind an open transaction. Run the worker for any of this to happen.

Webhooks are managed by roles with `webhooks.manage` (workspace admins) at `/api/v1/webhooks`: `POST` (the signing secret is returned once, here only), `GET`, `GET /{id}`, `PATCH /{id}` (`url`, `event_types`, `filter`, `active`), `DELETE /{id}`, `POST /{id}/test` (emits `webhook.test` to that endpoint only), `GET /{id}/deliveries?status=` and `POST /deliveries/{id}/replay`. `event_types` is a list of registered types or `"*"`; `filter` is a JSON object that the event's `data` must contain. An endpoint only gets events from after it was created.

Each matching event becomes one delivery, sent by a `webhook.deliver` job as a `POST` of JSON (`id`, `type`, `workspace_id`, `occurred_at`, `subject`, `actor`, `data`) with the headers `GoHigh-Event-Id`, `GoHigh-Event-Type`, `GoHigh-Delivery-Id` and `GoHigh-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`. Any 2xx is success. A timeout (10 s), a redirect (never followed) or another status is retried with the job queue backoff, up to 12 attempts; after 3 days of only failures the endpoint is disabled (`disabled_reason`; re-enable it with `PATCH`). The log keeps the status, attempts, response status, time and the first 2 KB of the response. A replay is a new delivery of the same event, with the same `GoHigh-Event-Id`, so receivers can dedupe. Deliveries are not ordered: two events can arrive in either order, so compare `occurred_at` (or the event `id`, which increases) instead of relying on arrival order. Verify a delivery on your side with the raw request body, before parsing it, and reject timestamps older than 5 minutes:

```python
import hashlib, hmac, time

def verify(secret: str, signature_header: str, body: bytes, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in signature_header.split(","))
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
    return abs(time.time() - int(parts["t"])) <= tolerance and hmac.compare_digest(parts["v1"], expected)
```

Webhook URLs must be `https` and resolve to public addresses only (no private, loopback, link-local, CGNAT, multicast or reserved space, IPv4-mapped forms included). The check runs when the URL is saved and again before every send; the request then connects to the address it just checked, with the original host in the `Host` header and the TLS handshake, so a DNS answer that changes in between cannot redirect it. For local development, `ALLOW_HTTP_WEBHOOKS=1` allows plain http and `WEBHOOK_ALLOW_IPS=127.0.0.1` (exact addresses, comma separated, only honoured with the first setting) lets a receiver on your machine through. Never set either on a reachable server.

## Channel adapters

`app/channels/` is the messaging provider layer of ADR 0005: library code with no tables and no routes, so the inbox webhook handler and the `message.send` job call it the same way. One module per provider (`twilio`, `telnyx`, `smtp`, `mailgun`, `meta_whatsapp`); Amazon SES is the SMTP adapter pointed at its SMTP endpoint. `channels.ADAPTERS` maps a `channels.provider` value to its module, and every module has the same three functions:

```python
from app.channels import ADAPTERS
from app.channels.base import Channel, Outbound, Request

adapter = ADAPTERS[row.provider]
channel = Channel(address=row.address, config=row.config, secrets=decrypted_secret)  # secrets never live in config
ok = adapter.verify(channel, Request(url, headers, raw_body))  # False when unsigned, wrongly signed or stale
items = adapter.parse(Request(url, headers, raw_body))         # list[Inbound]; ValueError on a body the provider would not send
result = adapter.send(channel, Outbound(to=..., from_=..., body=..., idempotency_key=str(message.id)))  # SendResult
```

- `Request` is the webhook as received: the full URL it was called on (behind a proxy, the public one; Twilio signs it, so `twilio.verify` also takes `public_url=`), the headers and the raw body bytes. Verify before parsing, on the raw bytes. Meta's GET handshake is `meta_whatsapp.challenge(channel, request)`: answer 200 with the returned text, or 403 on `None`.
- `parse` returns `Inbound` items: kind `message` (status `received`) or `status` (`queued`, `sent`, `delivered`, `read`, `failed`; email adds `complained` and `unsubscribed`, which are opt-out signals, not message states). Reports can arrive out of order, so never move a message backwards. `thread_ref` is the provider id of the message being replied to; email ids are stored without angle brackets.
- `send` raises `ChannelError`. `retryable` is true for timeouts, connection errors, 408, 429, 5xx, SMTP 4xx replies and Meta's throttling codes, false for everything a retry cannot fix (bad credentials, an invalid number, a refused address). `code` is the provider's own, for example Twilio 21610 for a recipient who replied STOP. A retried job must reuse the same `idempotency_key`: Twilio gets it as a header, SMTP and Mailgun derive the Message-ID from it; Telnyx and WhatsApp have no idempotency, so the job checks for an existing provider id first.
- Provider hosts are fixed (stdlib `http.client`, 10 s timeouts). Hosts a user configures never are: the SMTP host goes through `app/ssrf.py` (public addresses only, connecting to the address that was checked while the name stays the TLS server name), as do the URLs of email attachments (10 MB in all). SMTP has no plaintext mode: `starttls` (587) or `tls` (465), and a server without STARTTLS is refused.
- Settings per provider (`config` and `secrets` keys) are listed at the top of each module. `send` takes a keyword-only `base_url` for tests.

`app/compliance.py` holds the pure rules the send path needs: `keyword(body)` (STOP, START, HELP lists, whole message only), `quiet_until(now, tz, start, end)` (next allowed time in the contact's zone, DST safe), `sms_segments(body)` (GSM-7 with the extension table, or UCS-2, as `(encoding, segments, chars)`) and `email_risk(subject, html, text, bulk)` (lint warnings). Their tests, with the adapter tests, are in `backend/tests/channels/` and need no database.

## Records and data model

One engine serves contacts, companies, deals and custom objects (ADR 0002), with the same routes, filters, views, associations, timeline and events for all of them. Everything is under `/api/v1`, uses the conventions above and the `X-Workspace-Id` header. What a user may do with them is their role's (capabilities, record scope and field rules, below): a Member reads and writes records and applies tags, changing the schema (objects, fields, association types) and renaming, merging or deleting tags is for admins.

- **Objects and fields are rows.** `GET/POST /objects`, `GET/PATCH/DELETE /objects/{key}` (DELETE archives; `PATCH {"archived": false}` brings it back) and `GET/POST /objects/{key}/fields`, `PATCH/DELETE /objects/{key}/fields/{field_key}`. A field's key and type never change; archiving hides it everywhere and keeps its values. There is no cap on custom objects (a new one starts with a required `name` field); changing an object's `primary_fields` renames every record at once. Every workspace starts with `contact`, `company` and `deal` and their fields, seeded by one function (`records.seed.seed_workspace`, called at sign up and by `POST /api/workspaces`; migration 0004 backfilled existing workspaces).
- **Field types**: `text`, `long_text`, `number`, `money` (`{"amount": 1999, "currency": "USD"}`: integer minor units, ISO 4217), `date`, `datetime` (ISO 8601 with a zone, stored in UTC), `boolean`, `select`, `multi_select` (they store choice ids), `stage` (a stage id, see Pipelines and deals), `email` (stored lower case), `phone` (stored as E.164; a number without `+` is read with the field's `options.region`, else `DEFAULT_PHONE_REGION`, default `US`), `url`, `user`, `record` (the id of a record of `options.object`), and `formula` and `rollup`, which are stored but read-only and not computed yet. `records.types.validate(field, value)` is the one validator; `rules` hold `required`, lengths, `min` and `max`.
- **Records**: `GET/POST /objects/{key}/records`, `GET/PATCH/DELETE /objects/{key}/records/{id}`, `POST /objects/{key}/records/{id}/restore` and `GET /trash?object={key}`. A patch sets the values it sends and a null clears one; an invalid record is a 422 whose `fields` are `values.<key>`. `display_name` (the object's primary fields, then email, then phone), `email_norm` and `phone_e164` are derived on every write. A delete goes to the trash and a record outside the caller's scope is a 404.
- **Listing**: `filter` (JSON), `sort` (`-updated_at,display_name`, up to three, empty values last), `q`, `limit`, `cursor`, `include` (`tags` and the key of any associated object), `count=true` for a `total`, and `view=<saved view id>`. A long filter goes in the body of `POST /objects/{key}/records/query`, which takes the same names. Cursors are signed and belong to the sort that made them. `q` is full text over the display name and every text value, each word matched as a prefix (`ada lov`, `ada@ex`, `+1415`), best match first.
- **Filters** are one JSON language (ADR 0002): `{"and": [...]}`, `{"or": [...]}`, `{"not": {...}}`, `{"tag": "vip"}` (a tag name or id) and `{"field": key, "op": op, "value": value}`. A field is one of the object, `display_name`, `owner_id`, `created_by`, `created_at`, `updated_at`, or a field of an associated object as `company.name` (compiled to `EXISTS`, in both directions). Every field, operator and value is checked against the field's type, and a mistake is a 400 `validation_failed` whose `fields` point at the node (`filter.and.1.field`); a filter never becomes SQL.

  | type | operators |
  | --- | --- |
  | `text`, `long_text`, `email`, `phone`, `url` | `is`, `is_not`, `contains`, `starts_with`, `in`, `not_in`, `is_empty`, `is_not_empty` |
  | `number`, `money` | `is`, `is_not`, `gt`, `gte`, `lt`, `lte`, `between`, `in`, `not_in`, `is_empty`, `is_not_empty` (money compares amounts of the same currency) |
  | `date`, `datetime` | the same, plus `within_last` and `older_than` with `{"days": 30}` (minutes, hours, days, weeks, months or years) |
  | `boolean` | `is`, `is_not`, `is_empty`, `is_not_empty` |
  | `select`, `stage`, `user`, `record` | `is`, `is_not`, `in`, `not_in`, `is_empty`, `is_not_empty` |
  | `multi_select` | `contains`, `in`, `not_in`, `is_empty`, `is_not_empty` |

  Recent leads that are tagged `vip` or have a deal over $5 000, newest first, with their tags and company:

  ```bash
  curl -G "$API/api/v1/objects/contact/records" -b cookies.txt -H "X-Workspace-Id: $WORKSPACE" \
    --data-urlencode 'filter={"and": [{"field": "lifecycle", "op": "is", "value": "lead"},
      {"field": "created_at", "op": "within_last", "value": {"days": 30}},
      {"or": [{"tag": "vip"}, {"field": "deal.amount", "op": "gt", "value": {"amount": 500000, "currency": "USD"}}]}]}' \
    --data-urlencode 'sort=-created_at' --data-urlencode 'include=tags,company' --data-urlencode 'limit=25'
  ```

- **Associations** link two records through a type with a label for each direction (contact "works at" company, company "employs" contact; deal to contact; deal to company). `GET/POST /association-types` and `DELETE /association-types/{id}` define more, between any two objects, so a custom Property links to contacts and deals; a type is `one_to_one`, `one_to_many` or `many_to_many`. `GET/POST /records/{id}/associations` lists links in both directions with the label as seen from that record, and creates one (the end that is the type's `from` side is found from the objects); `DELETE /associations/{id}` removes it. A link shows on the timeline of both records.
- **Tags** (any object): `GET/POST /tags` (usage counts, `q` prefix), `PATCH/DELETE /tags/{id}`, `POST /tags/{id}/merge` with `{"into": id, "preview": true}` to count what a merge would move and without `preview` to do it. `POST /records/{id}/tags` and `POST /records/tags` (up to 1000 `record_ids`) take `{"add": [tag ids], "remove": [tag ids]}` (ten tags in each list at most) and emit a `tag.added` or `tag.removed` event per change.
- **Saved views**: `GET/POST /views`, `GET/PATCH/DELETE /views/{id}` keep an object, a filter, columns and a sort; `?counts=true` adds a live `count`. A shared view belongs to the workspace and a private one to its owner (a row level security policy), and only the owner or an admin changes a shared one. A view is saved only if its filter compiles.
- **Timeline**: `GET /records/{id}/timeline` is the record's events, newest first, with a cursor. Events about its own subject are found by subject; events that touch several records (a link) are listed in `event_records` by whoever emits them, with `records.timeline.link(db, event, record_ids)`, which notes, calls and messages will use too.
- **Permissions**: every read and write passes the hooks of ADR 0004 in `app/permissions.py`: `scope_filter(ctx, obj)` (a filter AST that is ANDed into every list, count, search, lookup, include and path filter), `redact(ctx, obj, values)` and `check_write(ctx, obj, changes)`. See Roles, permissions and audit, below.

## Pipelines and deals

Module 10 on the record engine. A deal is a record of the `deal` object, so it lists, filters, links and has a timeline like any record, and it needs no contact. Everything is under `/api/v1`; any workspace member reads and works with deals and boards, and changing pipelines and stages is for workspace admins.

- **Pipelines and stages are rows.** Every workspace starts with a Sales pipeline (Lead 10 %, Qualified 25 %, Proposal 50 %, Negotiation 80 %, Won 100 %, Lost 0 %), seeded with the system objects (`records.seed.add_pipeline`; migration 0007 gave existing workspaces one and turned their placeholder deal stages into these). `GET/POST /pipelines`, `GET/PATCH/DELETE /pipelines/{id}`, `POST /pipelines/{id}/stages`, `PATCH/DELETE /pipelines/{id}/stages/{stage_id}` and `POST /pipelines/{id}/stages/reorder` with `{"stage_ids": [...]}`, the whole order in one call. A stage has `name`, `kind` (`open`, `won` or `lost`), `probability` (0 to 100; won is 100 and lost is 0), `rotting_days` (null: never), `color` and `exit_rules`. A new pipeline without `stages` gets the Sales stages. `DELETE` removes a pipeline without deals (204) and archives one with deals (200, `archived_at` set); `PATCH {"archived": false}` brings it back; the last active pipeline cannot be archived or deleted, and a stage that holds deals, trashed ones too, cannot be deleted (409).
- **The `stage` field** of a deal holds a stage id of an active pipeline (else a 422 on `values.stage`). A deal created without one starts in the first open stage of the first pipeline; send `"stage": null` to have none. It has no `options`, cannot be sorted, and `stage_id` is the same value as a typed column, kept in step on every write, so the board reads one stage through an index (row level security keeps Postgres from using an index on a jsonb expression). Filters: `stage` takes ids with `is`, `is_not`, `in`, `not_in`, `is_empty` and `is_not_empty`, and two paths describe the stage without naming it: `{"field": "stage.kind", "op": "is", "value": "open"}` (`open`, `won` or `lost`) and `stage.pipeline` (a pipeline id), both with `is`, `is_not`, `in` and `not_in`. A deal with no stage has neither, so `stage.kind is_not open` includes it.
- **Moving a deal**: `POST /deals/{id}/move` with `{"stage_id", "after_id"?, "before_id"?, "position"?, "lost_reason"?, "lost_note"?}` and the card back, or a PATCH of `values.stage`; both go through `records.store.update`, so the rules are the same. The deal must meet the **exit rules** of the stage it leaves: a filter on the deal, such as `{"and": [{"field": "amount", "op": "is_not_empty"}, {"field": "close_date", "op": "is_not_empty"}]}`, judged on the deal as it will be after the change (a PATCH may supply what is missing). Failing is a 422 whose `fields` name each top level condition that does not hold (`values.close_date`: "Close date is required to leave Proposal"; `contact.email` for an association path; `exit_rules` for a nested `or`), and nothing changes. Rules that no longer compile, a field archived since, are a 409 until an admin fixes them. A lost stage needs `lost_reason` (the seeded select: price, timing, competitor, no decision, other; a 422 on `values.lost_reason`) and takes a `lost_note`; leaving a lost stage clears both. A change of stage emits `deal.stage_changed` next to `record.updated`: from and to stage (ids, names, kinds), `pipeline_id` and `seconds_in_stage`, counted from the previous stage change, else from the deal's creation.
- **Board**: `GET /pipelines/{id}/board?limit=25` answers the pipeline with, per stage in order, `count`, `amount` and `weighted` (amount times probability, rounded half up), each a `{currency: minor units}` map, `deals` (the first `limit` cards, top first) and `next_cursor`. A card is `{id, display_name, amount, close_date, owner_id, board_position, stage_id, stage_entered_at, days_in_stage, rotting, last_activity_at, values}`: `rotting` is true when `days_in_stage` is more than the stage's `rotting_days`, and `last_activity_at` is the newest entry on the deal's timeline. The next page of one column is the same call with `stage` and that stage's `next_cursor`.
- **Order inside a stage**: each deal has a `board_position`, an exact decimal sent as text, lower is higher. A new deal, or one entering a stage, lands on top. To drop a card, send its neighbours, `after_id` the card above the drop and `before_id` the card below (either or both); the deal takes the midpoint of their positions, so a drop writes one record, with no event and no new `updated_at`. `position` sets a value of your own instead. A neighbour must be another deal of the target stage (422) and they must be in order (409: reload the board).
- **Forecast**: `GET /pipelines/{id}/forecast?period=month|quarter&from=&to=` groups deals by `close_date` and answers `{periods: [{label, start, end, pipeline, best_case, commit, weighted, won, owners: [{owner_id, ...the same five}]}]}`, each metric a `{currency: minor units}` map: `pipeline` is the open deals, `best_case` those in stages of 50 % or more, `commit` those of 80 % or more, `weighted` the open deals by probability, `won` the deals in won stages. Lost deals and deals with no close date or no amount are left out; `owner_id` is null for deals nobody owns.
- **Layouts**: `GET/PUT /pipelines/{id}/layout` keeps the caller's own `{collapsed: [stage ids], card_fields: [field keys]}` (default: nothing collapsed; `amount`, `close_date`, `owner_id`). Nobody else can read it, in SQL too.

## Roles, permissions and audit

Two layers (ADR 0004). Row level security keeps tenants apart; `app/permissions.py` decides what a user may do inside a workspace: which actions, which records, which fields. Workflows and AI tools, when they arrive, go through the same functions as a named actor with a role (the `Automation` system role by default), never as a superuser.

- **Roles** belong to the organization, so an agency defines "Account manager" once and uses it in every client workspace. Sign up seeds the system roles (`app/roles_seed.py`): **Owner** (everything), **Admin** (everything but billing), **Manager**, **Member** (what a member could always do), **Viewer** (reads, changes nothing) and **Automation**. Owner and Admin are locked and are what org owners and admins hold in every workspace; the others can be edited, and no system role can be deleted. A user's role is set per workspace: `PUT /api/v1/members/{user_id}` with `{"role_id"}` (`members.manage`; it also adds an org member to the workspace, and unless you are an org owner or admin you cannot hand out a role that can do more than yours). `GET /api/v1/members` lists the people who can act there. `GET/POST /api/v1/roles` and `GET/PATCH/DELETE /api/v1/roles/{id}`: a custom role starts as a copy (`{"name", "copy_from": "<role key>"}`), `PATCH` replaces `capabilities` and `object_rules`, and a role someone still holds cannot be deleted. Creating, changing and deleting roles needs an organization owner or admin as well as `roles.manage`, because a change reaches every workspace of the org; it applies on the next request of everyone who holds the role.
- **Capabilities** are plain strings, listed in one place, `permissions.CATALOG` (module, capability, description); a role that names an unknown one is a 422. `contacts`, `companies`, `deals` and `records` (custom objects) each have `.read`, `.write`, `.delete` (also the trash and restore) and `.export`; then `schema.read` (objects, fields, association types, tags, views), `objects.manage` (objects and association types), `fields.manage`, `tags.write` (create and apply), `tags.manage` (rename, merge, delete), `views.write`, `views.manage` (other people's shared views), `webhooks.manage`, `members.read`, `members.manage` (roles of members, teams, the simulator), `roles.manage`, `audit.read`, and `pipelines.manage`, `workflows.publish`, `messages.send` and `billing.manage` for the modules that will use them. A module that adds one lists it in the catalog and in `roles_seed.SYSTEM_ROLES`, and grants it to existing organizations in its migration.
- **Object rules** are per object key (`contact`, `deal`, a custom object) or `*` for any other, with a `scope`, `hidden_fields` and `readonly_fields`. A role with no rule for an object sees none of its records. Scopes: `all`; `own` (the record's owner is the user, or one of its `user` fields names them: an assignee); `own_and_unassigned` (own, and records with no owner); `team` (own, and records owned by anyone in the user's teams or the teams below them); `none`. Without the `.read` capability for an object's kind, the scope is `none`. A record the scope does not show is a **404 everywhere**, never a 403: reads, lists, counts, search (`q`), saved views and their counts, `include=` expansion, filters through associations (`company.name`), the trash, tag counts and the timeline, so its existence does not leak (a link to it is left out of the timeline of a record the user can see). A record created by someone whose scope would hide it, with no `owner_id` sent, is owned by its creator; send `"owner_id": null` for an unassigned one.
- **Hidden fields** are never returned, and for that role they are not fields at all: they are missing from the object's field list, a filter or sort that names one is a 400 `unknown field` (`filter.field`), a write that names one is a 422 `is not a field of contact`, and `q` does not search their values (a role that hides fields searches without the index, see `query.search_vector`). When a hidden field is part of a record's display name (a primary field, or the email or phone it falls back to), the name is rebuilt from the fields the role can read (`(hidden)` if none), and `display_name` cannot be searched, sorted or filtered on either. Saved views that use a hidden field do not exist for that role. A **read-only** field is returned, and a write to it is a 403 with `fields` naming it (`values.lifecycle`). Timeline and audit events carry a record's values, so they are served without the fields the role hides. A field a role cannot write but that is `required` makes creating that kind of record fail for it, so do not hide or lock required fields.
- **Enforcement** is declared by the route and applied again where the data is. Each route takes a dependency from `app.permissions`: `requires("fields.manage")`, `requires_object("write")` for `/objects/{key}/...`, `requires_trash("delete")` for `?object=`, `requires_records("read")` for `/records/{id}/...` (which turns away roles that could not do it on any kind of record; the precise check comes after the record is found, so a record out of scope is a 404 first). The 403 reads `Your role does not allow this: it needs the capability contacts.write`. `tests/test_permissions.py` walks every `/api/v1` route and fails on one that declares no capability, with an allowlist (`PUBLIC`) for routes that really are public, and calls each route as a Viewer to check it is refused exactly where it says. The record engine does the rest (`store.create` and `update` run `check_write`, `trash` and `restore` need `.delete`, every query starts from `store.live`). New code that reads records should use those, not a raw `Record` query, and anything that shows a record's content should go through `permissions.redact` (or `redact_event`). What a request works out (role, rules, teams) is cached in `ctx.cache` for that request only.
- **Teams**: `GET/POST /api/v1/teams`, `GET/PATCH/DELETE /api/v1/teams/{id}`, `PUT` and `DELETE /api/v1/teams/{id}/members/{user_id}`. A team may sit under another (`parent_team_id`, no cycles); deleting one moves its sub-teams up. Reading is `members.read`, changing is `members.manage`. The team scope is the filter node `{"team": [team ids]}` (the record's owner is in one of them), which any filter may use.
- **Simulator**: `GET /api/v1/permissions/explain?user_id=&record_id=` (`members.manage`) answers with the user's role, capabilities, the rule per object (scope, hidden and read-only fields, what they can do) and teams, and for a record whether they see it and why, for example `visible: owner is in team East, scope team`. It runs the same functions enforcement does, on a copy of the request with that user swapped in, so the two cannot drift; the tests compare it with the API on a matrix of users and records.
- **Audit log** is the event log (ADR 0003): every write already emits an event in its own transaction, and request handlers can only add to `events` (INSERT and SELECT, no UPDATE, DELETE or TRUNCATE). Configuration writes emit `object.*`, `field.*`, `association_type.*`, `role.*`, `team.*`, `member.role_changed` and `webhook_endpoint.updated` and `.deleted` (the URL is not in the event, only `url_changed`); a change that changes nothing emits nothing. Security events are written to every workspace the user can act in: `user.password_changed` and `auth.sessions_revoked` (with a `count` and a `reason`). Saved views are the user's own preferences and are not audited. `GET /api/v1/audit` (`audit.read`) filters by `actor`, `subject` (a record id: its events, and the links that touch it), `type` (`record.updated`, or `record.*`) and `from` and `to` (inclusive), newest first with a cursor, and `GET /api/v1/audit/export` is the same as CSV (up to 50 000 events) and is itself an `audit.exported` event. `audit.read` shows the events of every record whatever a role's scope says; the fields a role hides are still taken out.
