# ADR 0003: Event log, webhooks and API conventions

Status: accepted (2026-10-16). Modules: 05 API, events and webhooks; used by 07 (timeline), 11 (notifications), 18 (workflows), 26 (reporting), 33 (developer platform).

## Context

The incumbent's API cannot write workflows, funnels or many settings. It emits about 70 webhook events, its rate limits are per app, and a failed webhook can only be resent from the latest attempt. Developers end up building workarounds through workflow webhook actions. We want every state change to be an event, every UI action to be an API call, and webhook delivery that can be inspected and replayed.

## Decision

### Event log (transactional outbox)

```
events   id bigserial, txid xid8 DEFAULT pg_current_xact_id(), workspace_id, type,
         subject_type, subject_id, actor_type, actor_id, data jsonb, occurred_at
```

- Every write emits its events through one function, `events.emit(db, type, subject, data)`, **in the same transaction** as the change. If the change rolls back, the event never existed. If it commits, the event cannot be lost.
- Event types are dotted and past tense: `contact.created`, `deal.stage_changed`, `message.received`, `form.submitted`, `booking.created`, `invoice.paid`, `workflow.run_failed`, `user.role_changed`. Each type has a JSON schema in `backend/app/event_types/`. CI fails if an emitted type has no schema, and the public event catalog is generated from those schemas.
- `data` carries the full new state of the subject, plus `changes` (field to old and new value) for updates, so consumers rarely need a follow-up read.

### Consumers read with a snapshot-safe cursor

Consumers (webhook fan-out, workflow triggers, notifications, search indexing, the SSE stream) each keep a cursor in `event_cursors (consumer, last_txid, last_id)`.

A plain `id > last_id` cursor silently skips events: a transaction can take id 101, commit after id 102 has been read, and be missed forever. Each consumer therefore reads only events from transactions older than every transaction still in flight:

```sql
SELECT * FROM events
WHERE (txid, id) > (:last_txid, :last_id)
  AND txid < pg_snapshot_xmin(pg_current_snapshot())
ORDER BY txid, id
LIMIT 500
```

The consumer processes the batch and advances the cursor in one transaction. Consumers run as recurring jobs on the queue from ADR 0001, woken early by `NOTIFY events`. Events are kept 90 days hot, then moved to cold storage by partition (monthly partitions on `occurred_at`).

### Webhooks

```
webhook_endpoints   id, workspace_id, url, event_types text[], filter jsonb, secret, active,
                    created_by, disabled_reason
webhook_deliveries  id, endpoint_id, event_id, status, attempts, next_attempt_at,
                    response_status, response_ms, response_body_excerpt, created_at
```

- Fan-out is a consumer that creates one delivery per matching endpoint. Each delivery is a job, retried on the backoff schedule over about 24 hours (12 attempts). After 3 days of only failures the endpoint is disabled, with an email to the workspace admins.
- **Signature**: header `GoHigh-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>` plus `GoHigh-Event-Id`. The docs carry verification snippets. Receivers reject timestamps older than 5 minutes.
- **SSRF guard**: the URL must be https in production and resolve to a public address. Private, loopback, link-local and metadata ranges are refused at save time and again at send time, after DNS resolution, so DNS rebinding cannot bypass the check. Redirects are not followed.
- **Delivery log**: search by event type, status and date; view the request and response excerpt; replay one delivery or every failed delivery in a time range. A replay is a new delivery of the same event id, so receivers can dedupe.

### API conventions

- **Paths**: `/api/v1/<resource>`; the UI calls the same routes (module 05 parity rule). Breaking changes go behind a dated `GoHigh-Version` header, with a 12 month deprecation notice.
- **Auth**: session cookie for the web app; `Authorization: Bearer` with workspace API keys (scoped, hashed at rest, prefix `gh_live_`) or OAuth app tokens for integrations. The workspace comes from the key, or from `X-Workspace-Id` for multi-workspace users.
- **Pagination**: cursor only. `?limit=50&cursor=<opaque>`; responses are `{"data": [...], "next_cursor": "..." | null}`. The cursor is a signed, base64 encoded sort key plus id, never an offset.
- **Errors**: `{"error": {"code": "validation_failed", "message": "...", "fields": {"email": "..."}, "trace_id": "..."}}` with the same trace id as the `x-request-id` header and the logs.
- **Idempotency**: `Idempotency-Key` on any POST. The first response is stored for 24 hours in `idempotency_keys (workspace_id, key, request_hash, status, response)`. A retry with the same key and body returns the stored response; the same key with a different body is a 409.
- **Rate limits**: per workspace and per key, a token bucket in Postgres (`rate_buckets`) for now. Every response sends `RateLimit-Remaining`; a 429 adds `Retry-After`.
- **Expansion**: `?include=company,owner` loads associations in one call instead of N follow-ups.
- **Bulk**: `POST /api/v1/<resource>/bulk` takes up to 1000 items and returns a job id; progress and per-item errors come from `/api/v1/jobs/<id>`.

## Consequences

- One write path per resource, which emits its events, makes the timeline, workflows, webhooks and audit consistent by construction.
- Consumers lag behind the oldest open transaction. A long-running transaction delays every consumer, so request transactions must stay short, and bulk jobs commit in batches.
- The Postgres token bucket and the events table are the first scaling pressure points. Moving them to Redis or a log broker later changes no public contract.
