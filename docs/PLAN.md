# Product plan

## What we are building

go-high is an all-in-one growth platform for agencies and the small businesses they serve: CRM, unified inbox, phone and SMS, calendars, forms, automations, sites and funnels, email marketing, payments, reputation, social, reporting, courses and AI agents, with an agency layer to run many client workspaces, resell them under your own brand and bill usage with a markup.

The category leader is GoHighLevel (HighLevel, also white-labeled as LeadConnector). Our research on it is in [docs/research](research/):

| Report | Covers |
| --- | --- |
| [01 CRM, conversations, phone, AI](research/01-crm-conversations-ai.md) | contacts, objects, pipelines, inbox, SMS/A2P, calling, AI employee, tasks, mobile |
| [02 Marketing and sites](research/02-marketing-sites.md) | funnels and websites, forms, email, social, ads, reporting, media, affiliates, reputation, listings |
| [03 Commerce, calendars, automation](research/03-commerce-calendars-automation.md) | calendars, payments, invoices, contracts, stores, memberships, communities, workflows (89 triggers) |
| [04 Platform, agency, UX](research/04-platform-agency-ux.md) | company, pricing, agency layer, snapshots, SaaS mode, white label, permissions, API, MCP, UX, competitors |

## Positioning

> The growth platform with a real API, versioned templates, real permissions and a UI a new hire understands on day one.

Three public proofs at launch: an OpenAPI spec with SDKs, CLI and MCP server; a one-click "migrate from GoHighLevel" importer; and a public status, pricing and changelog page that is always current.

## Where we beat the incumbent

| Their pain (from the research) | Our answer | Module |
| --- | --- | --- |
| Cluttered 17-item sidebar, steep learning curve, menus that move | Small core, Apps to turn modules on, reorderable nav, Cmd+K, starter kits | 04, 29 |
| Snapshot pushes cannot be reverted, no diff or history | Declarative templates with plan, apply, rollback, drift report, Git export | 29 |
| Workflows and funnels read-only in the API | API parity rule: the UI uses the public API | 05, 33 |
| Agency-level granular permissions missing, 60-day audit log | Policy engine with record and field rules, simulator, 12+ month audit | 03 |
| Email and SMS deliverability, A2P rejections | Isolated domains, warm-up, reputation dashboard, A2P readiness wizard | 13, 14, 20 |
| Surprise usage bills, wallet deleted on plan change | One usage ledger, caps, cost shown before every send | 06 |
| Five overlapping AI products with different prices | One Agent object for chat, voice and background work; evals; budgets | 31 |
| No search inside conversations, basic inbox hygiene | Keyboard-first inbox, global search, views with counts, SLAs | 08, 12 |
| Slow published pages (about 55 to 65 mobile) | Static output on a CDN, 90+ budget enforced before publish | 19 |
| Silent failures (calendar sync, reminders, workflows) | Setup health, sync health badges, per-contact workflow traces | 04, 16, 18 |
| No staging, live edits risk enrolled contacts | Draft and published versions, time-travel testing, in-flight migration | 18 |
| Switching cost is the moat | Migration importer from GoHighLevel | 34 |

## Roadmap

| Milestone | Goal | Modules |
| --- | --- | --- |
| **M0 Foundations** | The app runs, is secure and multi-tenant, and has its design system | 01 platform, 02 tenancy and auth, 03 permissions and audit, 04 design system and shell, 05 API, events, webhooks |
| **M1 Core CRM** | First sellable product for one business: capture leads, talk to them, book them, automate follow-up | 06 usage ledger, 07 records, 08 search and views, 09 import and dedupe, 10 pipelines, 11 tasks and notifications, 12 inbox, 13 email channel, 14 SMS and compliance, 15 phone, 16 calendars, 17 forms, 18 workflows |
| **M2 Grow** | Marketing and revenue: pages, campaigns, payments, reviews, social, reporting | 19 sites and funnels, 20 email marketing, 21 payments, 22 documents, 23 WhatsApp and Meta, 24 reputation, 25 social, 26 reporting and attribution, 27 media and brand |
| **M3 Agency and AI** | Run many clients, resell, automate with AI | 28 agency console, 29 templates, 30 SaaS mode and white label, 31 AI agents, 32 Ask AI, 33 developer platform and MCP, 34 migration, 35 security baseline |
| **M4 Expand** | Long tail of modules | 36 courses and communities, 37 client portal, 38 store, 39 ads, 40 affiliates, 41 blogs, 42 helpdesk, 43 listings and prospecting, 44 native mobile |

Full scope, parity and "done when" for each module: [MODULES.md](MODULES.md). Stack: [ADR 0001](adr/0001-stack.md). UI rules: [UI.md](UI.md).

## How work is tracked

- One GitHub issue per module (label `epic`, the module's milestone, a priority label and an area label). The checklist in the issue is the task list; split a checklist item into its own issue when it needs more than one PR.
- Branches start with `ansh/` (`ansh/feature/<name>`, `ansh/fix/<name>`). Every change goes through a pull request that links its issue.
- A module is closed when its "done when" check passes in the running app.

## Open decisions

- Product name and domain (go-high is the codename; the final name must not echo the incumbent's trademark).
- First vertical for the starter kit and launch marketing (home services is the usual first buyer of this category).
- SMS carrier for launch (Twilio vs Telnyx: price vs ecosystem).
