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

```bash
docker compose up --build
```

Open http://localhost:8000 (API docs at `/api/docs`). The `worker` service runs background jobs from the same image.

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

Background jobs: register a handler with `@jobs.handler("kind")` and call `jobs.enqueue(db, "kind", payload, run_at=...)` inside your transaction. Failed jobs retry with exponential backoff (10 s doubling, capped at 1 hour) and become `dead` after `max_attempts`.

## Tenancy and auth

Organization > Brand > Workspace. A user belongs to orgs (`owner`, `admin`, `member`) and optionally to single workspaces (`admin`, `member`); org owners and admins are admins of every workspace in their org. Sign in with email + password or a magic link (`/api/auth/*`, `/api/me`); the session is an HttpOnly, SameSite=Lax cookie whose SHA-256 is the only thing stored. Sessions have an idle timeout and an absolute expiry, can be listed and revoked (`/api/auth/sessions`), and cookie-authenticated writes whose `Origin` header is not in `PUBLIC_URL` get a 403.

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
- **Idempotency**: send `Idempotency-Key` (1 to 255 characters) on a POST. The first successful response is stored for 24 hours per workspace. The same key with the same method, path, query and body returns that response again with `Idempotent-Replayed: true`; the same key with anything else is a 409 `idempotency_key_reused`. Failed requests store nothing, so they can be retried. A route opts in with `idem: Idem = Depends(idempotency)` (after its role dependency) and ends with `return idem.commit(201, body)`, which commits the work and the stored response in one transaction, so a retry can never repeat the work. A create that returns a secret returns the same secret on a replay.

## Events and webhooks

Every state change is an event, written by `events.emit(db, "type", "subject_type", subject_id, data, actor=("user", user_id))` in the same transaction as the change: it exists only if the change commits. The workspace is the request's (or pass `workspace_id=`). Each type needs a JSON schema in `backend/app/event_types/<type>.json`; `emit` refuses unknown types and data that misses required keys or adds unexpected ones, and a test fails when code emits a type without a schema. Types so far: `workspace.created`, `user.signed_up`, `webhook_endpoint.created`, `webhook.test`.

Consumers read the log with `events.read_batch(db, "name")` and `events.advance(db, "name", batch)` in one transaction. A plain `id > last_id` cursor can skip an event whose transaction commits late; `read_batch` only returns events of transactions older than every transaction still open (`txid < pg_snapshot_xmin(pg_current_snapshot())`, in `(txid, id)` order), so nothing is skipped. The price is that one long transaction delays every consumer: keep request transactions short and commit bulk work in batches. Register a batch processor with `@events.consumer("name")`; the `events.dispatch` job (queued by every `emit`, run by the worker) calls each one and asks to be run again while events are waiting behind an open transaction. Run the worker for any of this to happen.

Webhooks are managed by workspace admins at `/api/v1/webhooks`: `POST` (the signing secret is returned once, here only), `GET`, `GET /{id}`, `PATCH /{id}` (`url`, `event_types`, `filter`, `active`), `DELETE /{id}`, `POST /{id}/test` (emits `webhook.test` to that endpoint only), `GET /{id}/deliveries?status=` and `POST /deliveries/{id}/replay`. `event_types` is a list of registered types or `"*"`; `filter` is a JSON object that the event's `data` must contain. An endpoint only gets events from after it was created.

Each matching event becomes one delivery, sent by a `webhook.deliver` job as a `POST` of JSON (`id`, `type`, `workspace_id`, `occurred_at`, `subject`, `actor`, `data`) with the headers `GoHigh-Event-Id`, `GoHigh-Event-Type`, `GoHigh-Delivery-Id` and `GoHigh-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>`. Any 2xx is success. A timeout (10 s), a redirect (never followed) or another status is retried with the job queue backoff, up to 12 attempts; after 3 days of only failures the endpoint is disabled (`disabled_reason`; re-enable it with `PATCH`). The log keeps the status, attempts, response status, time and the first 2 KB of the response. A replay is a new delivery of the same event, with the same `GoHigh-Event-Id`, so receivers can dedupe. Verify a delivery on your side with the raw request body, before parsing it, and reject timestamps older than 5 minutes:

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
