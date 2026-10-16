# ADR 0001: Stack and architecture

Status: accepted (2026-10-16)

## Context

go-high is a multi-tenant growth platform (CRM, inbox, sites, automation, payments, AI) for agencies and the businesses they run. It has to be fast to build with a small team, cheap to operate, and easy to reason about at 3am. The other SROT AI products already run on FastAPI + SQLAlchemy + React/Vite, so we reuse that stack and its tooling instead of starting a second one.

## Decision

| Concern | Choice | Why |
| --- | --- | --- |
| API | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, uv | Same as the other SROT AI apps; typed, async, OpenAPI for free (our public API docs come from it). |
| Database | PostgreSQL 17 | One database for everything. Tenant isolation with a `workspace_id` on every row plus Row Level Security. `jsonb` for custom fields, `tsvector` for search, `pgvector` for AI knowledge bases. |
| Jobs and workflows | Postgres-backed queue (`SELECT ... FOR UPDATE SKIP LOCKED`), one `worker` process | No Redis or broker to run. Workflow waits are rows with a `run_at`. Upgrade path: move hot queues to a broker only if measured throughput needs it. |
| Realtime | Server-Sent Events from the API, fed by Postgres `LISTEN/NOTIFY` | Inbox, notifications and dashboards update live without a websocket layer. |
| Web app | React 19, TypeScript, Vite, React Router, TanStack Query | Single page app; same toolchain as the other SROT AI frontends. |
| UI system | Our own components on Radix primitives, CSS variables for theming, Geist and Geist Mono | Light default plus dark mode, white-label theming is just a different token set. |
| Sites and funnels | Page = JSON block tree, edited in React, published as static HTML to object storage + CDN | Published pages are fast and survive API outages. |
| Files | S3-compatible object storage | Media library, attachments, published sites. |
| Messaging providers | Small adapters per channel: SMS/voice (Twilio, Telnyx), email (SES, Mailgun, SMTP), WhatsApp Cloud API, Meta, Google | We are not locked to one carrier and can rebill usage at a markup. |
| Payments | Stripe first (Connect for agencies), adapters later for PayPal, Razorpay, Square | Stripe covers invoices, subscriptions and Connect payouts. |
| AI | Claude via the Anthropic SDK (Sonnet for agents and writing, Haiku for classification and routing) | Tool use against our own read and write APIs, with every AI action logged and reversible. |
| Auth | Email + password, magic links, Google and Microsoft OAuth, TOTP 2FA, SAML SSO on higher plans | |
| Deploy | One Docker image (the API serves the built web app; the worker is the same image with another command), docker compose for local and small installs | Fewer artifacts to build and version; split the web app onto a CDN when traffic needs it. |

## Repository layout

```
backend/   FastAPI app, models, migrations, worker, provider adapters
frontend/  React app (agency view, workspace view, builders)
docs/      plan, module specs, research, ADRs
```

## Consequences

- One Postgres to back up, monitor and scale; read replicas and partitioning of the event tables are the first scaling steps.
- Python worker throughput is the likely first ceiling for bulk email and SMS; batching per provider and horizontal workers come before a broker.
