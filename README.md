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
