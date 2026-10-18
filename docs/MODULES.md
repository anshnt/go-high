# Modules

Every module has: what the incumbent ships (parity), what we do better, and when it is done. Each `##` section is tracked as one GitHub issue with the same number and title (label `epic`). Research behind each module is in [docs/research](research/).

Milestones: **M0 Foundations**, **M1 Core CRM** (first sellable product), **M2 Grow**, **M3 Agency and AI**, **M4 Expand**. Priorities: P0 must ship in its milestone, P1 should, P2 can slip.

---

## 01. Platform foundation
**Milestone:** M0 Foundations. **Priority:** P0. **Area:** platform. **Research:** 04

**Parity**
- Hosted multi-tenant SaaS with background jobs, file storage and realtime updates.

**Better**
- [ ] Monorepo `backend/` (FastAPI, SQLAlchemy 2, Alembic, uv) and `frontend/` (React, Vite, TypeScript) per [ADR 0001](adr/0001-stack.md)
- [ ] Docker images for api, worker and web; `docker compose up` gives a working app with seed data
- [ ] Postgres job queue (`FOR UPDATE SKIP LOCKED`) with retries, backoff, dead-letter view and scheduled `run_at`
- [ ] SSE endpoint fed by `LISTEN/NOTIFY` for live updates
- [ ] S3-compatible file storage with signed URLs
- [ ] CI: lint, type check, tests, build; performance budget check on key routes
- [ ] Public status page and structured logs with trace ids

**Done when** a fresh clone runs with one command, CI is green and a job scheduled for later runs on time.

## 02. Tenancy and authentication
**Milestone:** M0 Foundations. **Priority:** P0. **Area:** platform. **Research:** 04

**Parity**
- Agency (company) > sub-account (location) > users; agency users can switch into any sub-account.

**Better**
- [x] Organization > Brand > Workspace from day one (multi-brand white label without a second account)
- [x] `workspace_id` on every row plus Postgres Row Level Security, enforced in tests
- [ ] Sign in with email + password, magic link, Google, Microsoft; TOTP and passkeys; org-enforced 2FA policy
- [ ] Session list with revoke, idle timeout, IP allowlist (higher plans)
- [ ] Workspace switcher that remembers the last page per workspace
- [ ] Sandbox workspaces (copy of config, fake data) for testing changes safely

**Done when** two workspaces in one org cannot read each other's data through any API route (tested), and 2FA can be required org wide.

## 03. Roles, permissions and audit log
**Milestone:** M0 Foundations. **Priority:** P0. **Area:** platform. **Research:** 04

**Parity**
- Admin and user roles with per-module checkboxes; "only assigned data" toggle; audit logs kept about 60 days.

**Better**
- [x] Named, reusable roles at org and workspace level (agency-level granular roles are the top request)
- [x] Policies on module, record (owner, team, assigned + unassigned) and field (hide PII per role)
- [x] Teams and sub-teams
- [x] "What can this user see?" simulator
- [x] Append-only audit log for every write, 12+ months retention, filter by record, user and action, CSV export
  (saved views are not audited; nothing deletes or archives events yet, so retention is unlimited until the
  partitions of ADR 0003 arrive)
- [ ] Login-as (impersonation) is always audited and visible to the workspace

**Done when** a role can be limited to its own team's deals with a hidden field, the simulator agrees, and every change shows in the audit log.

## 04. Design system and app shell
**Milestone:** M0 Foundations. **Priority:** P0. **Area:** ui. **Research:** 04, 02

**Parity**
- Left sidebar with about 17 fixed modules, top bar with search, Ask AI, notifications; settings in a long list.

**Better** (see [UI.md](UI.md))
- [ ] Tokens (color, type, space, radius, shadow) in CSS variables; light default, complete dark mode; density toggle
- [ ] Component library on Radix: button, input, select, combobox, date, dialog, sheet, menu, tabs, toast, table, board, timeline, empty state, skeleton
- [ ] Sidebar with a small default core, pin, hide and reorder per user and per role; Apps page to turn modules on
- [ ] `Ctrl/Cmd+K` palette for navigation, records, settings and actions; `?` shortcut sheet; configurable shortcuts
- [ ] One searchable settings hub with deep links
- [ ] Setup health checklist that verifies real completion
- [ ] Theme editor (logo, favicon, colors, fonts, login screen) that drives white label
- [ ] Phone layout: bottom tabs, sheets, installable PWA

**Done when** every M1 screen is built only from these components and passes the UI checklist at 1280 and 375 px in both themes.

## 05. API, events and webhooks
**Milestone:** M0 Foundations. **Priority:** P0. **Area:** developer. **Research:** 04

**Parity**
- REST API v2 with OAuth and private tokens, about 70 webhook events, workflows and funnels read-only, 100 requests per 10 seconds.

**Better**
- [ ] API parity rule: the UI uses the same public API, so every UI action is an API call
- [ ] OpenAPI 3.1 generated from the code; versioned by date; 12 month deprecation policy
- [x] Cursor pagination, idempotency keys, consistent errors with trace id (on `/api/v1`)
- [ ] `Retry-After` on 429 for `/api/v1` (the error envelope passes it through; needs the per-workspace rate limits)
- [x] Outbox table (`events`, written in the same transaction as the change) with snapshot-safe consumers, so events never get lost
- [ ] Event catalog with JSON schemas for every state change (4 types so far; the public catalog page is generated from `backend/app/event_types`)
- [x] Webhook subscriptions with filters, signed (HMAC), retries with backoff, delivery log with status filter and replay
- [ ] Delivery log search by event type and date, bulk replay of failed deliveries, email to admins when an endpoint is disabled
- [ ] API keys per workspace with scopes; OAuth apps for third parties
- [ ] Event stream (SSE) for realtime integrations (`GET /api/v1/stream` serves the signed-in inbox, ids only; integrations need API keys first)

**Done when** creating a contact through the UI emits `contact.created`, a subscribed webhook receives a signed payload, and a failed delivery can be replayed from the log.

## 06. Usage ledger, wallet and cost preview
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** billing. **Research:** 04, 01, 03

**Parity**
- Plan fee plus a wallet charged for SMS, calls, email, AI, premium workflow actions; agencies can mark up usage on the top plan only.

**Better**
- [ ] One metered ledger (event, unit, cost, price, markup) behind every paid action
- [ ] Prepaid wallet and postpaid modes, auto top-up, low balance alerts, never deleted on plan change
- [ ] Per-workspace monthly caps with hard stop and alerts
- [ ] Cost estimate shown before any send, campaign, call or AI run
- [ ] Usage dashboard per workspace and per feature; statements that itemize carrier fees
- [ ] Markup rules available on every plan

**Done when** a bulk SMS shows its estimated cost before sending, the ledger records the real cost after, and a cap stops sends when reached.

## 07. Records and data model
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** crm. **Research:** 01

**Parity**
- Contacts with standard and custom fields, custom values, tags, companies (late multi-company), custom objects (10 per workspace), associations, notes, tasks, activity timeline, DND per channel, engagement score.

**Better**
- [ ] One record engine for contacts, companies, deals and custom objects: same list, filters, views, associations, notes, files, timeline, permissions and API (lists, filters, views, associations, timeline and API are done on one `records` table; notes, files and permissions are not)
- [x] No object cap; many-to-many associations with labels (contact has many companies, deal has many contacts with roles; a role is an association type, so "decision maker" is one more type between deal and contact)
- [ ] Typed fields: text, number, money (currency aware), date, select, multi-select, user, record link, file, formula, rollup; validation; conditional visibility and required rules; per-field history (all of these but file are typed and validated, with required, length and range rules; formula and rollup are stored but not computed; conditional rules and field history are not)
- [ ] Workspace variables (custom values) kept separate from fields and named clearly
- [x] Tags with groups, colors, descriptions, usage counts, rename and merge with preview
- [ ] Consent and eligibility card per channel: source, timestamp, DND, quiet hours, "can I contact now?" (the consent rows, DND and the refusal reasons are in the API under `/api/v1/contacts/{id}/consents`; the card is not built)
- [ ] Configurable lead scoring with decay and an explainable breakdown
- [ ] Trash with 30-day restore for every record type (trash and restore work for every object; the purge after 30 days is not built)
- [ ] Record page per [UI.md](UI.md): properties, timeline, associations, tasks, AI summary

**Done when** a custom "Property" object can be created, linked to contacts and deals, filtered, and shows on both timelines.

## 08. Search, lists and saved views
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** crm. **Research:** 01

**Parity**
- Smart lists (saved filters) with bulk actions; no search inside messages (a top request).

**Better**
- [ ] Global full-text search over records, messages, notes, files and call transcripts, permission aware (Postgres FTS first) (records are searched by word prefix, best match first, through the permission scope hook; messages, notes, files and transcripts are not)
- [ ] Saved views shared with a team, stored server side, with counts in the sidebar (stored server side with live counts, shared with the workspace or private; teams come with module 03)
- [ ] Dynamic lists (rules) and static lists (hand picked), with membership history (a saved view is a dynamic list; static lists and membership history are not)
- [ ] Filter builder with AND/OR groups, relative dates, association filters (the filter language and its compiler are done, with AND, OR, NOT, relative dates and association paths; the builder screen is not)
- [ ] Natural language filters ("leads who asked about pricing and did not book") via AI, always shown as editable rules
- [ ] Bulk actions as jobs with preview, progress and undo

**Done when** searching a phrase from an SMS finds the conversation in under 300 ms on 1M messages, and a saved view shows a live count.

## 09. Import, export, dedupe and data rights
**Milestone:** M1 Core CRM. **Priority:** P1. **Area:** crm. **Research:** 01

**Parity**
- CSV import with mapping and limits, duplicate rules that differ by source, merge contacts, export CSV.

**Better**
- [ ] CSV, XLSX and Google Sheets import; fuzzy header matching; create missing fields inline
- [ ] Dry run showing creates, updates and skips; roll back an entire import
- [ ] Import associations, notes and activities in one file set; scheduled imports from a URL or Sheet
- [ ] One duplicate rule set for forms, imports, API and integrations; review queue with fuzzy matching
- [ ] Field-level merge with preview and undo for 30 days
- [ ] Full workspace export in open formats; GDPR export and erase per contact in two clicks

**Done when** a 50k row XLSX imports with a dry-run preview and can be rolled back, and merging two contacts can be undone.

## 10. Pipelines and deals
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** crm. **Research:** 01

**Parity**
- Multiple pipelines and stages, board and list views, card fields, lost reasons, forecasting in Labs, opportunities need a contact.

**Better**
- [x] Deals can exist without a contact and link many contacts with roles (a role is an association type between deal and contact, as in module 07)
- [ ] Board with drag, swimlanes, rotting and aging indicators, per-stage probability (the server side is done: stage columns with counts and sums, drag ordering in one write, days in stage, rotting flags and probabilities; swimlanes and the board screen are not)
- [x] Stage exit rules (required fields), mandatory structured lost reasons
- [ ] Line items from the product catalog, quotes
- [ ] Forecast view: weighted, commit, best case, history of changes, quota per rep (weighted, commit and best case by month or quarter, currency and owner are done, and stage changes are events; the history view and quotas are not)
- [ ] Board layouts saved per user and team on the server (per user is done; teams come with module 03)
- [ ] Card shows last message and next task (it has the time of the last timeline entry; messages and tasks come with modules 11 and 12)

**Done when** a deal can be dragged through stages with exit rules enforced and the forecast updates live.

## 11. Tasks and notifications
**Milestone:** M1 Core CRM. **Priority:** P1. **Area:** crm. **Research:** 01

**Parity**
- Tasks on contacts with due dates and assignment, notification bell, mobile push that users report as unreliable.

**Better**
- [x] Tasks on any record; list, board and calendar views; recurring and dependent tasks
- [ ] Task playbooks per pipeline stage
- [ ] Notification center with per-event, per-channel, per-scope rules, digests, quiet hours (in-app is done: a bell, three kinds of event, a rule per kind for who hears about it and whether the bell shows it, quiet hours that hold notifications until they end; the email channel and the digests are stored but not sent)
- [ ] Web push and email notifications; unread counts in the tab title (the tab title shows the unread count; push and email wait for the email module and a service worker)
- [ ] My Day view: tasks, appointments and assigned conversations in one list (the landing page lists my overdue and today's tasks; appointments and conversations have their place and join when calendars and the inbox exist)

**Done when** a user gets exactly the notifications their rules say, on web push and email, and can work their day from one screen.

## 12. Unified inbox
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** conversations. **Research:** 01

**Parity**
- Four-panel inbox across SMS, email, WhatsApp, Messenger, Instagram, GBP chat, live chat, calls and voicemail; internal comments; snippets; assignment; unread and starred filters.

**Better**
- [x] One conversation model; channels are adapters with delivery receipts, retries and guaranteed ordering
- [ ] Keyboard-first: `j/k`, `e` close, `a` assign, `s` snooze, `r` reply; optimistic UI under 100 ms (the API has a route for each of these actions; the screen is not built)
- [ ] Saved views with live unread counts; snooze; follow-up SLAs with breach alerts (the built in views, their live counts, per-user unread and snooze are done; custom saved views and SLAs are not)
- [ ] Assignment rules: round robin, load based, skills, hours (conversations are assigned by hand to a member or a team id; no rules)
- [ ] Internal comments with @mentions that can be edited; "someone is replying" collision guard (internal notes that only their author edits are done; mentions and the collision guard are not)
- [ ] Snippets with variables; paste images; scheduled send
- [ ] AI: reply suggestions, thread summary, intent and sentiment tags, translation with original toggle
- [ ] Trash for conversations; search inside conversations (search over message text, notes and the contact's name, email and phone, and inside one conversation, is done; a conversation goes with its contact to the trash and has no trash of its own)
- [x] Live chat widget (deferred load, under 30 KB) as the first channel (a 9 KB script that builds its panel on the first click, signed visitor tokens, rate limits and a honeypot)

**Done when** a support agent can triage 50 conversations from the keyboard alone, and a chat widget message arrives live.

## 13. Email channel and mailbox sync
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** conversations. **Research:** 01, 02

**Parity**
- Send 1:1 email from the inbox via a shared provider or SMTP, Gmail/Outlook sync, no configurable reply-to (top request).

**Better**
- [ ] Gmail and Microsoft 365 two-way sync with domain and contact exclusions
- [x] Sending through SES, Mailgun or SMTP adapters; per-workspace sending domain (each channel has its own host or domain; delivery events from SES are not read)
- [ ] Reply-to, per-user signatures, send-as aliases, threading that matches mail clients (reply-to per channel and threading by In-Reply-To and References, both ways, are done; signatures and aliases are not)
- [ ] Open and click tracking with per-message opt out
- [ ] Domain auth wizard that checks SPF, DKIM and DMARC live

**Done when** a reply from Gmail threads correctly into the contact's conversation and our reply lands in the same Gmail thread.

## 14. SMS, MMS and messaging compliance
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** conversations. **Research:** 01

**Parity**
- LC Phone (Twilio) numbers, A2P 10DLC registration per sub-account with 60+ rejection codes, toll-free verification, STOP handling, DND.

**Better**
- [x] Carrier adapters: Twilio and Telnyx
- [ ] Buy, port and release numbers in-app
- [ ] A2P readiness wizard that pre-checks website, privacy policy, opt-in language and brand data before submitting; status tracking with plain-language next steps
- [ ] Brand profile inherited from the org with per-workspace overrides
- [ ] Opt-in evidence stored per contact; STOP/START/HELP; quiet hours and frequency caps; content checks (STOP, START and HELP, opt-outs and do not disturb per channel, quiet hours in the contact's time zone and frequency caps are done; evidence is only the START mark, and the content checks are not run on a reply yet)
- [ ] Segment count and cost shown while typing (every SMS reply answers with both and `POST /api/v1/channels/{id}/estimate` does it for a draft; the composer does not show it yet)

**Done when** a new workspace can register, get approved and send compliant SMS without reading a help article.

## 15. Phone and calling
**Milestone:** M1 Core CRM. **Priority:** P1. **Area:** conversations. **Research:** 01

**Parity**
- Browser and app calling, routing spread over three screens, IVR built inside workflows, voicemail, recording, missed-call text back, call tracking number pools, a workflow-driven "power dialer".

**Better**
- [ ] WebRTC calling in the browser with click to call from any record
- [ ] One visual call routing canvas: hours, IVR, ring groups, AI agent, voicemail
- [ ] Routing simulator ("caller X at 8 pm ends up here")
- [ ] Recording with per-state consent rules; transcripts and AI summaries on the timeline
- [ ] Missed-call text back as a routing node
- [ ] Call tracking numbers per source with offline conversion upload (module 26)
- [ ] Power and parallel dialer with voicemail drop and dispositions (M4)

**Done when** an inbound call follows the canvas exactly as the simulator predicted, and the recording, transcript and summary appear on the contact.

## 16. Calendars and booking
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** scheduling. **Research:** 03

**Parity**
- Personal, round robin, class, collective, service and event calendars; availability, buffers, booking widget; Google, Outlook, iCloud sync; Zoom and Meet; reminders; payments at booking; rooms and equipment; recurring capped at 24; rentals.

**Better**
- [ ] One availability engine for people, rooms, equipment and rentals (quantity, lead and turnover time)
- [ ] Push-based Google and Microsoft sync with a health badge and a "why is this slot hidden" explainer
- [ ] Weighted round robin with caps, skills, territory and owner stickiness; "simulate next 20 bookings"
- [ ] Unlimited recurring series with exceptions; automations fire per occurrence
- [ ] Payments and deposits on every booking path, packages and session credits
- [ ] Auto status from video join, call or check-in
- [ ] Booking page from the design system, fast and accessible; embed without iframe
- [ ] Reminders through one communication policy shared with workflows

**Done when** a round robin booking page books the right rep, syncs to their Google calendar within seconds and sends reminders that can be traced.

## 17. Forms, surveys and quizzes
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** marketing. **Research:** 02

**Parity**
- Form builder, surveys, quizzes with scoring, conditional logic v2, embeds by iframe or script, payment and calendar fields.

**Better**
- [ ] One engine for forms, surveys and quizzes: multi-step, scoring, payments, file upload, e-signature (forms, surveys and quizzes are one engine with steps, branching, scoring, versions, contact mapping and events; payments, file upload and e-signature are not)
- [ ] Visual logic map (branching diagram), including calendar and payment fields (the map of steps, jumps and early ends is done, with a rules editor; calendar and payment fields do not exist yet)
- [x] Shadow DOM embed (no iframe) that keeps host analytics working; embeds update live
- [x] Partial submissions, drop-off per field, save and resume links
- [ ] Spam protection on by default (honeypot, rate limit, invisible challenge) (honeypot, minimum fill time, rate limit per form and visitor and a size limit are done and on by default; an invisible challenge is not)
- [ ] Results pages built in the page builder (module 19) when available

**Done when** an embedded multi-step form with branching creates a contact, attributes the source and triggers a workflow.

## 18. Workflow automation
**Milestone:** M1 Core CRM. **Priority:** P0. **Area:** automation. **Research:** 03

**Parity**
- Visual builder with 89 triggers and many actions (messages, CRM updates, waits, if/else, goals, webhooks, custom code, AI agent), re-entry and time window settings, 10 versions or 30 days of history, premium actions billed per run, legacy campaigns.

**Better**
- [ ] Typed trigger and action catalog generated from module 05 events, documented and available to apps
- [ ] Canvas builder: branches, waits, goals, loops over records, sub-workflows with inputs and outputs
- [ ] Draft and published versions, unlimited history, diff, rollback; migrate in-flight contacts when steps change
- [ ] Test run with sample contacts and time travel (fast-forward waits)
- [ ] Per-contact trace with variable values at each step; "why did this contact not enter" explainer; bulk retry
- [ ] Idempotency and double-send protection by default; quiet hours respected
- [ ] Inbound webhook trigger with sample payload capture and mapping; outbound webhook and code steps
- [ ] Cost preview per workflow from the usage ledger
- [ ] "What uses this tag/field/calendar" dependency graph
- [ ] AI: describe a workflow in words, get a draft with test cases

**Done when** a form submission workflow with a 2 day wait can be tested in seconds with time travel, published, edited live without losing enrolled contacts, and traced per contact.

## 19. Sites and funnels builder
**Milestone:** M2 Grow. **Priority:** P0. **Area:** sites. **Research:** 02

**Parity**
- Separate funnel and website builders, sections/rows/elements, templates, custom domains, page-level split tests, order form steps, upsells, custom code, SEO settings, page analytics; scores around 55 to 65 on mobile with chat and pixels.

**Better**
- [ ] One builder for funnels and websites; every feature works in both
- [ ] Block tree stored as JSON, published as static HTML to a CDN
- [ ] Desktop, tablet and mobile breakpoints with side-by-side preview; fluid type and spacing tokens
- [ ] Brand tokens from module 27 propagate live
- [ ] Performance by default: image resizing to AVIF/WebP, lazy loading, critical CSS, chat loads on interaction; 90+ mobile budget shown before publish
- [ ] Custom domains with automatic SSL; redirects manager; sitemap, robots, schema.org blocks, OG preview
- [ ] A/B and multivariate tests on pages or blocks with significance and guardrails
- [ ] Funnel graph with drop-off and revenue per step
- [ ] Version history and restore for every page
- [ ] AI page generation that outputs editable blocks wired to forms and tracking
- [ ] Accessibility lint (contrast, alt text, headings)

**Done when** a two-step funnel (opt-in, thank you) built from a template publishes on a custom domain and scores 90+ on mobile Lighthouse with the chat widget.

## 20. Email marketing and deliverability
**Milestone:** M2 Grow. **Priority:** P0. **Area:** marketing. **Research:** 02

**Parity**
- Drag and drop and HTML builders, templates, campaigns, scheduling and batch sends, A/B tests, LC Email on a shared Mailgun pool, dedicated domains, email verification, basic stats. Deliverability is the top complaint.

**Better**
- [ ] Block email builder from the design system; global blocks; dynamic content per segment; dark mode and client previews
- [ ] Spam word, link and alt-text lint before send
- [ ] Segment evaluated at send time with exact count and sample contacts
- [ ] A/B on subject, content and sender with auto winner; send-time optimization; holdout groups
- [ ] Isolated sending domain per workspace by default; warm-up schedule visible in UI
- [ ] Deliverability dashboard: reputation by mailbox provider, blocklist monitoring, bounce and complaint auto-suppression, Google and Microsoft postmaster data
- [ ] Revenue attribution with configurable windows; Apple MPP aware open rates

**Done when** a campaign to a segment sends with throttling from a warmed domain and the dashboard shows placement signals and revenue.

## 21. Payments and commerce core
**Milestone:** M2 Grow. **Priority:** P0. **Area:** payments. **Research:** 03

**Parity**
- Stripe, PayPal, Square, Authorize.net, NMI with different capabilities per area; products and prices; invoices, recurring invoices, estimates; Text2Pay; subscriptions; coupons; order forms with bumps and upsells; transactions and refunds; tax.

**Better**
- [ ] Stripe first (Connect for agencies); provider adapter interface for PayPal, Razorpay, Square
- [ ] Capability matrix resolved at runtime with a plain reason when something is unavailable
- [ ] Products, prices (one time, recurring, tiered), coupons that work everywhere including invoices
- [ ] Checkout and order forms with bumps, one-click upsells and downsells
- [ ] Invoices, estimates, recurring invoices, payment links by SMS or email
- [ ] Deposits, milestones and installments as one schedule concept shared with calendars and contracts
- [ ] Subscriptions with rule-based dunning, card updater and pause
- [ ] One ledger for orders, invoices, subscriptions, refunds and disputes; payout reconciliation export
- [ ] Tax via Stripe Tax

**Done when** an estimate converts to a deposit invoice, the deposit is paid by link, the balance invoice is created automatically and both reconcile with the Stripe payout.

## 22. Documents and contracts
**Milestone:** M2 Grow. **Priority:** P1. **Area:** payments. **Research:** 03

**Parity**
- Proposal and contract templates, e-signature, products in documents, payment on signing.

**Better**
- [ ] Block editor templates with conditional clauses and variables
- [ ] Signing order, reminders, expiry, audit certificate PDF
- [ ] Signature creates the invoice or subscription automatically
- [ ] Redlines and comments from the recipient

**Done when** a proposal with two signers is signed in order, produces an audit certificate and starts the subscription.

## 23. Messaging channels: WhatsApp, Meta, Google
**Milestone:** M2 Grow. **Priority:** P1. **Area:** conversations. **Research:** 01

**Parity**
- WhatsApp (new billing from October 2026), Facebook Messenger, Instagram DM, Google Business Profile chat in the inbox.

**Better**
- [ ] WhatsApp Cloud API adapter with template management and approval status
- [ ] Messenger and Instagram DM including comments to DM
- [ ] Google Business Profile messages
- [ ] Telegram and RCS adapters
- [ ] Per-channel cost in the usage ledger

**Done when** WhatsApp, Messenger and Instagram threads show in the same conversation as SMS and email for one contact.

## 24. Reputation and reviews
**Milestone:** M2 Grow. **Priority:** P1. **Area:** marketing. **Research:** 02, 01

**Parity**
- Review requests by SMS and email, Google and Facebook reviews with replies, Reviews AI, review widgets by script, listings via partners.

**Better**
- [ ] Google, Facebook, Yelp and Trustpilot sources; reviews in the inbox
- [ ] Policy-compliant request flows triggered by outcomes (job done, paid, appointment showed)
- [ ] AI replies in brand voice with approval queue; negative sentiment opens a task
- [ ] Server-rendered review widgets with schema markup
- [ ] Response time and review velocity metrics; review to social image

**Done when** a completed appointment sends a review request, the review arrives in the inbox and an approved AI reply posts to Google.

## 25. Social planner
**Milestone:** M2 Grow. **Priority:** P1. **Area:** marketing. **Research:** 02

**Parity**
- Facebook, Instagram, LinkedIn, Google Business, TikTok, YouTube, Pinterest, X scheduling; calendar; RSS; CSV bulk upload (90 posts); approvals; weekly analytics without export; no comment moderation.

**Better**
- [ ] Composer with per-network previews and pre-flight media checks
- [ ] Calendar with drag to reschedule; evergreen queue with recycling
- [ ] Approval chains and client approval links without login
- [ ] Proactive token refresh, readable errors with a fix action, failed post inbox
- [ ] Daily analytics with export; UTM auto tagging tied to revenue
- [ ] Comments in the inbox with hide and delete
- [ ] AI repurposing (blog to posts, review to image)

**Done when** a week of posts for three networks is scheduled from a CSV, approved by a client link and published with analytics.

## 26. Reporting, attribution and dashboards
**Milestone:** M2 Grow. **Priority:** P0. **Area:** reporting. **Research:** 02

**Parity**
- Fixed reports (ads, calls, agents, appointments, attribution), custom dashboards with widgets, first and last touch attribution only, PDF exports.

**Better**
- [ ] Dashboard builder: free grid, drill down, cross filter, dashboard-level date and segment controls
- [ ] Governed metrics layer used by dashboards, workflows and API; formulas
- [ ] First-party tracking script that stores click ids (gclid, fbclid, ttclid, msclkid) on sessions and contacts
- [ ] Attribution models: first, last, linear, position based, time decay; per contact journey view
- [ ] Automatic conversion upload to Meta CAPI and Google offline conversions, deduplicated
- [ ] Closed loop on collected revenue with refunds and LTV
- [ ] Scheduled white-label client reports (web link and PDF) with AI commentary
- [ ] Warehouse export (BigQuery, Snowflake, S3)

**Done when** a paid ad click becomes a contact, then a paid invoice, and the dashboard attributes revenue to the campaign under two models.

## 27. Media library and brand kit
**Milestone:** M2 Grow. **Priority:** P1. **Area:** marketing. **Research:** 02

**Parity**
- Media storage with folders; brand boards (10 colors, 5 fonts) that do not update existing assets.

**Better**
- [ ] Media library with tags, AI auto tags and search, duplicate detection, crop and resize presets, background removal
- [ ] Responsive image derivatives via CDN; video transcoding with captions
- [ ] "Used in" graph for every file
- [ ] Brand kit as semantic tokens with live propagation and a diff preview; multiple brands per workspace; voice guidelines for AI

**Done when** changing the brand accent color previews every affected page, form and email before applying.

## 28. Agency console and fleet operations
**Milestone:** M3 Agency and AI. **Priority:** P0. **Area:** agency. **Research:** 04

**Parity**
- Agency view: sub-account list and creation, login-as, agency dashboard, bulk actions limited.

**Better**
- [ ] Fleet health: A2P status, domain auth, deliverability, wallet, failed workflows, API errors across all workspaces
- [ ] Any workspace action available on a selection of workspaces with preview, progress, partial failure handling and undo
- [ ] Workspace creation from a template in one step with brand profile inheritance
- [ ] Cross-workspace reporting with formulas
- [ ] Client onboarding checklist the agency can customize

**Done when** an agency sees every client's setup health on one page and can fix one issue across 20 workspaces in one action.

## 29. Templates (snapshot replacement)
**Milestone:** M3 Agency and AI. **Priority:** P0. **Area:** agency. **Research:** 04

**Parity**
- Snapshots copy assets (funnels, workflows, calendars, fields...) into sub-accounts; push updates cannot be reverted (top request, 492 votes); no diff or history.

**Better**
- [ ] Template = typed, declarative description of workspace config (fields, pipelines, workflows, pages, forms, calendars, products, courses)
- [ ] Plan, apply and roll back pushes to many workspaces with a diff per workspace
- [ ] Per-asset lock or allow local overrides; drift report
- [ ] Automatic backup before every push; history with author and time
- [ ] Export and import as YAML or JSON so agencies keep templates in Git
- [ ] Vertical starter kits (home services, dental, real estate, coaching, agency) built as templates

**Done when** a template change pushed to 10 workspaces shows a diff first, and one workspace can be rolled back alone.

## 30. SaaS mode, rebilling and white label
**Milestone:** M3 Agency and AI. **Priority:** P0. **Area:** agency. **Research:** 04

**Parity**
- SaaS configurator on the top plan: plans, Stripe billing of clients, usage markup, trials; white-label app domain, custom CSS/JS (unsupported), white-label mobile app as a paid add-on.

**Better**
- [ ] Plan catalog with feature entitlements and usage meters as real objects; editable by API
- [ ] Trials, coupons, proration, dunning, tax, multi-currency; hosted checkout and pricing embed
- [ ] Per-brand storefront and customer self-service billing portal
- [ ] Markup on any usage line, fixed bundles for AI and SMS
- [ ] White label from the theme editor: app domain, login page, emails, PDFs, client portal, PWA; no CSS hacks needed
- [ ] UI extension slots instead of DOM injection

**Done when** an agency publishes a plan, a client buys it from the brand's storefront, gets a workspace from a template and is billed usage with markup.

## 31. AI agents (chat and voice)
**Milestone:** M3 Agency and AI. **Priority:** P0. **Area:** ai. **Research:** 01

**Parity**
- Conversation AI bots, Voice AI agents, Agent Studio, Managed Agents, Workflow AI, Reviews AI, Content AI; knowledge bases; priced pay-per-use or $50 / $97 per sub-account.

**Better**
- [ ] One Agent object: instructions, knowledge, tools, channels, triggers, guardrails, memory; runs as chat, voice or background job
- [ ] One builder (chat first, graph view for power users), one test panel, draft and published versions
- [ ] Knowledge bases with re-crawl, source freshness, and "questions it could not answer this week"
- [ ] Eval suites with golden conversations and simulated customers before publish
- [ ] Guardrails, PII redaction, approval queue for sensitive actions, max replies then hand off, pause when a human replies
- [ ] Per-agent budget, cost per conversation and per booked appointment
- [ ] Voice: low latency pipeline, caller recognition, consent and calling-hour checks before outbound
- [ ] Every AI action logged with "why" and undo

**Done when** one agent answers website chat and phone calls from the same knowledge, books appointments, hands off to a human correctly and shows its cost per booking.

## 32. Ask AI copilot
**Milestone:** M3 Agency and AI. **Priority:** P1. **Area:** ai. **Research:** 01, 04

**Parity**
- Ask AI assistant that is read-only for workflows and campaigns.

**Better**
- [ ] Copilot in the command palette and on every record, using the same public API (anything the UI can do)
- [ ] Dry-run preview and confirmation for every change; undo
- [ ] Record summaries, next best action, drafted follow-ups that learn from edits
- [ ] AI field extraction from calls and emails into fields
- [ ] Natural language reports and lists

**Done when** "move all deals idle 30 days in Proposal to Nurture and draft a check-in email" shows a preview, applies on confirm and can be undone.

## 33. Developer platform, MCP and marketplace
**Milestone:** M3 Agency and AI. **Priority:** P1. **Area:** developer. **Research:** 04

**Parity**
- API v2 docs, marketplace with OAuth apps and iframe custom pages, official MCP server with 550+ operations via 4 tools.

**Better**
- [ ] API reference with live try-it, request logs and replay
- [ ] Generated SDKs (TypeScript, Python) and a CLI with webhook tunnel and fixtures
- [ ] MCP server (search, describe, execute) across workspaces, with dry-run and approval for writes
- [ ] App SDK with UI slots (sidebar item, record panel, record action, settings page) and host context
- [ ] Marketplace with native app billing and public revenue share

**Done when** a third-party app installs by OAuth, adds a panel to the contact page and is billed per workspace.

## 34. Migration from GoHighLevel
**Milestone:** M3 Agency and AI. **Priority:** P1. **Area:** agency. **Research:** 04

**Parity**
- None. Agency switching cost is the incumbent's moat.

**Better**
- [ ] Connect a HighLevel sub-account through its API and import contacts, companies, custom fields, tags, pipelines, opportunities, calendars, appointments, forms metadata, notes and tasks
- [ ] Workflow JSON exports recreated as drafts with AI and a parity checklist
- [ ] Side-by-side report of what mapped and what needs attention
- [ ] Bulk mode for agencies (many sub-accounts at once)

**Done when** a sample sub-account imports with a fidelity report and its main workflow is recreated as a reviewable draft.

## 35. Security and compliance baseline
**Milestone:** M3 Agency and AI. **Priority:** P1. **Area:** platform. **Research:** 04

**Parity**
- 2FA (enforcement long requested), no documented SSO, 60-day audit logs, HIPAA as a $297 irreversible add-on.

**Better**
- [ ] SAML and OIDC SSO, SCIM provisioning
- [ ] Audit log streaming (S3, webhook, SIEM)
- [ ] Data residency (US, EU)
- [ ] DPA, consent logs, DSAR workflows, double opt-in
- [ ] HIPAA mode per workspace (BAA, PHI controls), reversible
- [ ] Pen test and security page

**Done when** an org signs in with SSO, users are provisioned by SCIM and audit events stream to S3.

## 36. Courses, memberships and communities
**Milestone:** M4 Expand. **Priority:** P1. **Area:** memberships. **Research:** 03

**Parity**
- Courses, offers, drip, quizzes, certificates, communities with channels, gamification (9 levels), events, branded mobile app as an add-on.

**Better**
- [ ] LMS core: lessons, video analytics, question banks, assignments with rubrics, cohorts and live sessions
- [ ] Access rules on offers: drip, expiry, cohort start, revoke on failed payment
- [ ] Communities: spaces, threads, polls, DMs, events, configurable points and badges with real rewards
- [ ] One login and one PWA for courses, community, bookings and invoices
- [ ] Importers for Kajabi, Teachable, Thinkific, Skool, Circle

**Done when** a member buys an offer, gets drip access, completes a course with a certificate and posts in the community from the same app.

## 37. Client portal
**Milestone:** M4 Expand. **Priority:** P2. **Area:** memberships. **Research:** 02

**Parity**
- Client portal for courses, communities and some account data.

**Better**
- [ ] Appointments, invoices, proposals, files, tasks, project status and messages in one branded portal
- [ ] Custom navigation and widgets; portal on a custom domain; magic link sign in

**Done when** a client can pay an invoice, sign a proposal and message the business from the portal.

## 38. E-commerce store
**Milestone:** M4 Expand. **Priority:** P2. **Area:** payments. **Research:** 03

**Parity**
- Store pages, products with variants, inventory, shipping rates, Shopify import, abandoned cart; no fulfillment.

**Better**
- [ ] Service-plus-product commerce: reorder automations, subscriptions and boxes, local pickup slots from the availability engine
- [ ] Carrier rates and labels (Shippo or EasyPost), tracking sync, low stock alerts, bundles
- [ ] Two-way Shopify sync
- [ ] Abandoned cart recovery with bumps and upsells at checkout

**Done when** an order with shipping is placed, labelled and tracked, and an abandoned cart is recovered by a workflow.

## 39. Ads manager and conversions
**Milestone:** M4 Expand. **Priority:** P2. **Area:** marketing. **Research:** 02

**Parity**
- Ads manager for Meta, Google Search and LinkedIn; ad reporting; conversion APIs set up by workflows.

**Better**
- [ ] Deep integrations first: conversions from module 26, offline conversions from payments and appointments
- [ ] Campaign reporting with spend, CAC, ROAS and payback per channel
- [ ] Automated rules (pause when CPA above X), budget pacing alerts
- [ ] Simple campaign creation for Meta and Google later

**Done when** spend and attributed revenue show per campaign and a pause rule fires on CPA.

## 40. Affiliate manager
**Milestone:** M4 Expand. **Priority:** P2. **Area:** marketing. **Research:** 02

**Parity**
- Affiliate campaigns, commissions by product, payouts recorded manually, affiliate portal.

**Better**
- [ ] Link and coupon attribution with cookie windows, fraud checks, refund clawbacks
- [ ] Tiered commission rules with simulation
- [ ] Automated payouts (Stripe Connect, PayPal); affiliate portal with assets and leaderboard

**Done when** an affiliate sale is attributed, a refund claws back the commission and payouts run automatically.

## 41. Blogs and content
**Milestone:** M4 Expand. **Priority:** P2. **Area:** sites. **Research:** 02

**Parity**
- Blog posts on sites, no category pages, no forms inside posts.

**Better**
- [ ] Posts with categories, tags, authors, archives, RSS, related posts
- [ ] Forms and blocks inside posts; scheduled publish; redirects on import
- [ ] AI drafts from an SEO brief, internal link suggestions

**Done when** a blog with categories imports from WordPress with redirects and keeps its search traffic paths.

## 42. Helpdesk and tickets
**Milestone:** M4 Expand. **Priority:** P2. **Area:** conversations. **Research:** 01

**Parity**
- None (1,000+ vote request).

**Better**
- [ ] Ticket object on the record engine with queues, SLAs, macros and CSAT, reusing the inbox
- [ ] Knowledge base articles shared with AI agents

**Done when** an email to support@ becomes a ticket with an SLA timer and a CSAT survey on close.

## 43. Listings, local SEO and prospecting
**Milestone:** M4 Expand. **Priority:** P2. **Area:** marketing. **Research:** 02, 03

**Parity**
- Listings via Yext or Uberall, prospecting tool with GBP audits.

**Better**
- [ ] GBP management (posts, photos, Q&A, attributes); local rank grid
- [ ] Prospecting audits as shareable web pages; prospects flow into sequences and pipelines
- [ ] Listings through a partner integration

**Done when** a prospect audit page is generated, shared and its lead flows into a pipeline.

## 44. Native mobile apps
**Milestone:** M4 Expand. **Priority:** P2. **Area:** ui. **Research:** 01, 04

**Parity**
- LeadConnector app (inbox, contacts, calendar, calls) with unreliable push; white-label app needs the agency's own developer accounts.

**Better**
- [ ] PWA from module 04 wrapped as native apps for app store presence
- [ ] Reliable push, offline drafts, SIM or VoIP calling, voice notes
- [ ] Managed white-label publishing (no agency developer account needed)

**Done when** the app is in both stores, push arrives within seconds and a white-label build ships without the agency's own developer account.
