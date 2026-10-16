# go-high

> **Proprietary software. Copyright (c) 2026 SROT AI LLP. All rights reserved.** See [LICENSE](LICENSE).

An all-in-one growth platform for agencies and small businesses: CRM, unified inbox, phone and SMS, calendars, forms, automations, sites and funnels, email marketing, payments, reputation, social, reporting, courses and AI agents, plus an agency layer to run, template, white label and resell client workspaces.

**Status:** M0 Foundations in progress: platform scaffold (API, worker, job queue, web app, CI).

| Doc | What is in it |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | positioning, where we beat the incumbent, roadmap M0 to M4, how work is tracked |
| [docs/MODULES.md](docs/MODULES.md) | 44 modules: parity, improvements, done-when; one GitHub issue each |
| [docs/UI.md](docs/UI.md) | UI and UX principles, layout, visual language, PR checklist |
| [docs/adr/0001-stack.md](docs/adr/0001-stack.md) | stack and architecture |
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
