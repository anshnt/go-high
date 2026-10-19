# ADR 0005: Conversations, channels and realtime

Status: accepted (2026-10-17). Modules: 12 inbox, 13 email channel, 14 SMS and compliance, 15 phone, 23 WhatsApp and Meta. Builds on ADR 0002 (contacts are records) and ADR 0003 (events, jobs).

## Context

The incumbent's inbox is the module people live in, and its most voted gaps are hygiene: search inside conversations, a reply-to address, unread counts, messages out of order, retried webhooks that duplicate messages. Every channel should look the same to the inbox, the workflows and the API.

## Decision

### One thread per contact, every channel in it

```
channels       id, workspace_id, kind (sms, email, webchat, whatsapp, messenger, instagram, voice),
               provider (twilio, telnyx, ses, mailgun, smtp, gmail, microsoft, meta, internal),
               address (number, email address, widget key, page id), config jsonb, secret_ref,
               status (active, pending, failing, disabled), status_detail
conversations  id, workspace_id, contact_id, status (open, snoozed, closed), assignee_id, team_id,
               snooze_until, last_message_at, last_inbound_at, sla_due_at, created_at
conversation_reads  conversation_id, user_id, last_read_seq
messages       id, workspace_id, conversation_id, seq bigint, direction (in, out), channel_id,
               kind (message, note, call, voicemail, system), subject, body, html, attachments jsonb,
               status (queued, sent, delivered, read, failed, received), error,
               provider_message_id, thread_ref (email Message-ID / In-Reply-To), sent_by,
               occurred_at, created_at, search tsvector
               unique (channel_id, provider_message_id)
```

- A contact has at most one open conversation. Messages from every channel land in it, in `seq` order. `seq` comes from a per-conversation counter assigned on insert, so the order the inbox shows is the order the server stored. Provider timestamps (`occurred_at`) are shown but never used for ordering, which ends "messages out of order".
- `unique (channel_id, provider_message_id)` makes inbound webhooks and status callbacks idempotent. A retried webhook is a no-op.
- Internal notes are messages with `kind = note`, so they sit in the timeline, can be searched and edited, and are never sent.
- Unread is `last_message seq > conversation_reads.last_read_seq` for the user. Counts per saved view come from one indexed query.
- Secrets (provider API keys, SMTP passwords) are never stored in `config`. `secret_ref` points to an encrypted `secrets` table (AES-GCM with a key from `SECRET_KEY` derivation) that only the worker reads.

### Channel adapters

Each provider is one module in `app/channels/` with three functions:

- `verify(request) -> bool` checks the provider's signature on inbound webhooks: Twilio `X-Twilio-Signature`, Telnyx Ed25519, Mailgun HMAC, SNS signature for SES, and the Meta `X-Hub-Signature-256`. Unsigned requests are rejected.
- `parse(request) -> list[Inbound]` normalizes messages and status callbacks.
- `send(channel, message) -> provider_message_id` sends; errors are classified as retryable or permanent.

Inbound webhooks arrive at `/api/hooks/<provider>/<channel_id>`. The handler verifies, parses, then for each item matches the contact by `phone_e164` or `email_norm` (creating one if unknown, `source = channel`), appends the message, reopens the conversation, and emits `message.received`.

Outbound messages are inserted as `queued` in the request transaction, and a `message.send` job (ADR 0001) delivers them. The job's idempotency key is the message id, so a retry after a timeout never double-sends: the adapter passes it to providers that support idempotency keys and checks for an existing provider id first.

### Consent before every send

`compliance.can_send(contact, channel, now)` runs before queueing and again in the job. It checks:

- per-channel DND and opt-out (STOP, unsubscribe)
- quiet hours in the contact's time zone
- frequency caps
- A2P status for the sending number

A refusal returns a reason the composer shows ("Opted out by STOP on Oct 3"). Inbound STOP, START and HELP are handled before the message reaches the inbox. Workflows defer sends to the next allowed window instead of failing.

### Realtime

`GET /api/v1/stream` is a Server-Sent Events stream per signed-in user and workspace. Each API process runs one `LISTEN gohigh_events` connection, and an events consumer `NOTIFY`s compact payloads (`{type, workspace_id, ids}`). The process forwards them to the matching streams. Payloads carry ids only. The client refetches through the normal API, so permissions (ADR 0004) apply and nothing leaks over the stream. Reconnects resume with `Last-Event-ID`.

### Webchat widget

`/widget.js` (under 30 KB, loaded on interaction) talks to `/api/public/chat/<widget_key>` with a signed visitor token in its own storage. A visitor becomes a contact when they leave an email or phone number. Rate limits per widget key and per IP, plus a honeypot field, keep bots out.

### Search

`messages.search` (body and subject) is GIN indexed. Inbox search combines it with contact search (ADR 0002), so "invoice 1043" finds the thread.

## Consequences

- One thread per contact keeps the inbox simple. Businesses that want separate threads per channel or per topic get "split conversation" later as a view, not a schema change.
- Per-conversation `seq` needs a row lock on the conversation while inserting a message, which is fine at conversation scale. Bulk sends insert into many conversations, not one.
- The SSE design means a busy workspace refetches small lists often; the inbox list endpoint must stay cheap (p95 under 100 ms).

## As built in the backend slice (2026-10-18)

Where the code differs from the sketch above:

- A contact has at most one *live* (open or snoozed) conversation, enforced by a partial unique index; the next message
  reopens the contact's closed conversation instead of making a second one, so in practice a contact has one
  conversation. Conversations also keep the columns the list needs (`last_seq`, `last_inbound_seq`, `last_channel_id`,
  `last_preview`, `last_direction`) and a `visitor_id` for a webchat visitor.
- Unread is `last_inbound_seq > read mark`: only the contact's messages are unread, so a reply, a note or a colleague's
  message never lights a conversation up. Notes and system lines take a `seq` but do not move the conversation in the list.
- Consent has its own table, `consents (contact, channel kind, status: opted_out | opted_in | dnd, source, time)`, and
  the webchat rate counters their own, `chat_limits`. `messages` also keep `attempts`, `segments` and `cost`.
- `secret_ref` points at a row of `secrets` whose ciphertext the request role cannot read (column grants); the worker and
  the verify, send and test code read it on the owner role. The channel API creates `sms`, `email`, `webchat` and `whatsapp`
  channels; the other kinds are allowed by the table for later.
- STOP, START and HELP are stored as `system` lines (so a retried webhook cannot answer twice), do not emit
  `message.received` and, for a stranger, start no open conversation. The auto reply is a `system` message sent without
  the consent check, because it answers the STOP itself.
- The contact's time zone for quiet hours is its `timezone` value when the workspace has such a field, else the zones its
  phone number can be in. Quiet hours do not bind a contact who wrote in the last 24 hours, email or chat. The A2P status of
  the sending number is not checked until the readiness wizard exists.
- Teams do not exist yet (module 03), so `team_id` is stored as given. The contact `source` of ADR 0002 is filled in only
  when the workspace has a text field with that key; the system objects do not define one.
- The web app (module 12 UI) keeps to the ADR and adds a few things: `POST /conversations/{id}/unread` (the read mark only moved forward, and a keyboard first inbox needs `u`), `GET /api/v1/me/capabilities` (what the caller's role may do, so screens hide what the server would refuse), a single `EventSource` per tab that exists only while the inbox is open (browsers allow few connections per host, so the sidebar badge polls instead), and refetching by id: a payload is turned into the rows, counts and open thread it names (`inbox/stream.ts`), and `stream.resync` or a reconnect reads everything shown again. A send shows at once as a draft keyed by its `Idempotency-Key`, so a retry after a dropped connection cannot send twice.
- The stream's `LISTEN` connection is read on a thread inside one asyncio task: psycopg's async API needs a selector event
  loop, which Windows does not use by default. A process keeps its last 1000 notifications for `Last-Event-ID`.

