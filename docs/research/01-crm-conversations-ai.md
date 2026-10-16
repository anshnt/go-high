# GoHighLevel (HighLevel / LeadConnector) Research 01: CRM, Conversations, Phone, AI, Tasks, Mobile

Scope of this document: Contacts/CRM, Opportunities/Pipelines, Conversations (unified inbox), Phone system, AI features ("AI Employee"), Tasks, Notifications, Mobile app.

Research date: 2026-10-16. Product state described is "as of Sept/Oct 2026".

Sources used (summarized, not copied): official help center (help.gohighlevel.com solution articles), ideas.gohighlevel.com (public feature-request boards and changelog), HighLevel marketing blog posts, plus third-party agency/review blogs. Where a number comes only from a third-party blog or where sources conflict, it is flagged with "(unverified)" or "(conflicting)". Direct G2, Capterra and Reddit pages blocked automated fetching (HTTP 403), so the user-complaint sections rely on the public feature-request boards, review-aggregator summaries and agency blog posts, not on first-hand Reddit threads.

A note on naming: the company is HighLevel (gohighlevel.com). The mobile app and the white-labelled infrastructure are branded "LeadConnector" (LC). "Sub-account" and "location" mean the same thing (one client business). The "Agency" is the reseller level above sub-accounts. The new UI design system is called "HiRise" (articles mention "HiRise design" and "HighRise-based" pages; the migration is ongoing, so the product is mid-redesign).

---

## 0. Executive summary (what you are competing against)

1. HighLevel is an agency-first, multi-tenant CRM + marketing automation + phone + AI platform. Hierarchy: Agency -> Sub-account (location) -> Users. Almost every feature is per sub-account. This multi-tenant shape (SaaS mode, snapshots, rebilling) is as important as any single feature.
2. The CRM core is classic: contacts, companies, opportunities in pipelines, tasks, notes, tags, custom fields, smart lists, plus (newer) custom objects and associations. It is "good enough" for SMB service businesses, with obvious gaps (one company per contact historically, no helpdesk/ticketing, weak opportunity customization, search inside conversations).
3. The inbox is a four-panel unified inbox (SMS, MMS, email, WhatsApp, FB Messenger, Instagram DM, Google Business Profile chat, live chat, calls, voicemail, internal comments, internal chat). Many top requests are basic inbox hygiene (search inside conversations, "reply-to" address, paste images, unread counts).
4. The phone system (LC Phone, a Twilio-based white-label) is cheap at the unit level but burdened by compliance (A2P 10DLC registration with dozens of rejection codes), toll-free verification, regulatory bundles, and per-feature charges.
5. AI is the fastest-moving area: Ask AI (operator copilot), Conversation AI (customer bot, three build modes), Voice AI (inbound/outbound, flow builder, multi-language, prompt optimizer), Managed Agents (formerly Super Agents; autonomous CRM agents), Agent Studio (legacy flow-based agents), Workflow AI, Reviews AI, Content AI, Funnel/Website AI, Email AI, AI Studio (vibe-coding builder), Knowledge Bases, MCP server and connectors, Skills platform. Pricing: pay-per-use, or $50 Growth / $97 Unlimited AI Employee per sub-account.
6. The biggest consistent complaints: steep learning curve and clutter, uneven performance, features shipped half-finished/in "Labs", unpredictable support, deliverability (email and SMS), usage-based costs that stack on top of the plan, and a long tail of "obvious" missing basics on the ideas board.

---

## 1. Platform context and plans (needed to understand per-feature gating)

- Plans (per agency, monthly): Starter $97, Unlimited $297, Agency Pro $497. Rebilling (marking up usage to clients) and white-label mobile app tie to the $497 tier (third-party sources say the white-label app is an extra roughly $497/mo; unverified).
- AI add-on, per enabled sub-account: Pay-per-use ($0 fixed), AI Employee Growth ($50/mo), AI Employee Unlimited ($97/mo). See section 6.
- Labs: many newer features (opportunity forecasting, Internal Chat, conditional opportunity fields, Associate Records workflow action, Voice AI chat widget, Managed Agents until recently, Prompt Optimizers, Funnel/Website AI, Email AI, AI Studio) sit behind a "Labs" toggle per sub-account (and sometimes per agency). This is a UX and QA smell: functionality is discoverable only by knowing to look in Labs.
- Sample data: new sub-accounts get sample contacts, tasks, notes, companies and tags (names prefixed "(Example)") but no sample pipeline or opportunities.
- Audit logs: retained about 60 days (opportunity activity logs and pipeline permission changes).

---

## 2. Contacts / CRM

### 2.1 Navigation and layout

- Left nav module "Contacts" with sub-areas: Smart Lists (all contacts + saved lists), Bulk Actions (job history), Restore, Tasks, Companies, Manage Smart Lists, Import, Export, Trigger Links, and a Custom Objects entry per object (objects can be shown in nav).
- Contacts list view ("Contacts - Revamped List View & SmartLists", SmartLists 2.0, fully launched to all customers): modern table, searchable and drag-reorderable columns, an AND/OR filter builder, column layouts/filters/sorting persisted between sessions. Pagination size selector 20/50/100.
- Standard objects can be renamed ("How to Rename Standard Objects in Your CRM"), enabling vertical-specific vocabulary (e.g., Contacts -> Patients).
- The same list-view pattern is rolled out to Companies, Custom Objects, Tasks and Opportunities.

### 2.2 Contact record (the "all-new contact detail page")

Three-panel layout designed to cut scrolling; right panel collapsible; page remembers last tab and panel state.

- Left panel (Contact info): profile picture, name, email, phone(s), tags (changes applied only after clicking Apply), DND tab, Actions tab (manage opportunities, workflows, client portal), "Hide Empty Fields" toggle, "Search Fields & Folders" box. Custom fields are grouped in collapsible Folders.
- Center panel: unified timeline of messages, calls, notes, appointments, opportunity changes, activity log; quick compose for notes, messages, call logging. Activity section was upgraded ("Activity Section Upgrade").
- Right panel (action modules): Activities (appointments, form submissions, logs), Associations (companies, custom objects, other contacts), Opportunities, Tasks, Notes, Appointments, Documents (sent/received files), Payments (invoices, subscriptions, transactions).
- Auto-Save: sub-account-wide admin toggle (Settings -> Contacts -> Details tab). When off, Ctrl/Cmd+S saves. Edits logged in the activity log.
- Keyboard: left/right arrows move between contacts in the list, ESC collapses right panel.
- "How to Customize the Contact Detail Page" article exists: layout/section customization is available (admin).
- Contacts can have multiple phone numbers (dedicated article) and multiple additional emails.
- Contact engagement score shown in a dropdown in the contact profile and in the Conversations right panel.
- Create subscriptions and invoices directly from a contact's profile (payments tie-in).
- "Add Contact" form upgraded with customizations (configurable fields on the add-contact modal).
- Document privacy and access controls ("Enhanced Document Privacy & Access Controls") for files attached to contacts, sharing via Client Portal.

### 2.3 Core contact data (entity and fields)

From product docs, API v2 and import documentation (full API schema could not be fetched; list is a composite and may be incomplete):

Standard fields: id (contact ID), locationId, firstName, lastName, name, email, phone (E.164), additional emails, additional phones, companyName / businessName (and linked Company), address1, city, state, postalCode, country, timezone, dateOfBirth, website, source, type (Contact Type), assignedTo (owner user ID), followers (up to 10), tags (array of strings), dnd (global flag) + dndSettings (per channel: Call, Email, SMS, WhatsApp, GMB, FB Messenger, Inbound), customFields (array of id/value), dateAdded, dateUpdated, lastActivity, lastAppointment, lastEmailOpened/Clicked dates, email status (valid/invalid/bounce), engagement score, attribution (first and last: UTM, session source, medium, referrer, campaign, gclid/fbclid, landing page), profile photo, additional contacts (via associations).

Contact Types: single-select (dropdown-single custom field) classification such as Lead / Customer / Prospect / Supplier / Partner, admin-editable list, filterable in smart lists (appears as "Type"), updatable via workflow Update Contact Field, usable in imports, trigger "Contact Changed". Contrast with tags (many per contact).

Followers: up to 10 followers per contact or opportunity; followers see and edit a record even if their role is "Only Assigned Data"; they inherit the owner's permissions, cannot change owner; workflow actions add/remove followers.

Owner decoupling: setting to allow contact owner and opportunity owner to differ; optional sync of followers between them; workflow action "coming soon" at time of the article.

### 2.4 Custom fields

- Created at Settings -> Custom Fields; choose object (Contact or Opportunity, plus Company and Custom Object variants). The object type is permanent after creation (cannot convert contact field to opportunity field; must recreate).
- Field types documented: Short Text, Long Text, Dropdown (single), Dropdown (multiple; no practical option limit, 50+ options), Date Picker, Phone, Email, Radio Select, Checkbox Group, URL, plus numeric, monetary, text-box list, file upload, signature and others (the article states more types exist without listing them; the chat widget supports a subset: Text, Monetary, Phone, Numeric, Large Text, Date, capped at 5 fields).
- Folders: group fields into sections on the record, assignable at field creation, with a Live Preview panel on the create screen. Fields tab table sortable by column with icons for special states.
- Usage: forms, surveys, workflows (contact only), smart lists, merge fields in email/SMS, reports (availability depends on field type), imports (the field must pre-exist).
- File upload custom fields store files on contacts (article: "Adding Files To Contacts using a Custom Field"); ideas board asks for bulk download of those files.
- Conditional custom fields for opportunities (Labs): Admin rules show or require fields or folders based on pipeline, stage, status, or other field values (dropdown, radio, checkbox, multi-select), conditions combined with AND/OR, previewed before saving, managed at Settings -> Custom Fields -> Opportunity -> Conditional Rules or via the pipeline Actions menu. Validation applies in web and mobile, not to public API or workflow updates. Hidden fields keep values and skip mandatory checks. Contacts do not yet have equivalent conditional rules (ideas board: "Hideable Custom Fields/Folders" 104 votes, in progress).
- Lost Reason is itself a managed custom field (editable via Settings -> Custom Fields -> Lost Reason -> Bulk Actions -> Edit; rename propagates everywhere).

### 2.5 Custom values (not the same as custom fields)

- Custom values are sub-account-level key/value constants (business name, address, review link, calendar link, etc.) used as merge fields in emails, SMS, sites and workflows ({{custom_values.xxx}}). They can be organized in folders. In snapshots they carry default values. Not per-contact data.
- Merge fields library: article "List of Merge Fields", plus a "Merge Fields & Custom Variables" help category and pre-built "Custom Object Templates" (one-click CRM setups for verticals).
- Missing: custom values inside Conversation AI Q&A is a 99-vote request (planned).

### 2.6 Tags

- Free-form strings on contacts; created on the fly or in Settings -> Tags; add/remove manually, in bulk (bulk add and bulk remove articles), from workflows, forms, imports, voice AI "Update Tag" action, managed-agent trigger "Tag Changed".
- Tags drive workflows (Contact Tag trigger), smart lists, conversation filters, and opportunity filtering (but "Filter Opportunities by Tags" is a 254-vote request, so it is weak at the opportunity level). "Smart List Contains option for tags" is also a request.
- Pain: tags are a flat namespace with no governance (no tag groups, no descriptions, no usage count in-line), which leads to tag sprawl.

### 2.7 Smart lists

- Dynamic saved filters. Created in Contacts -> Smart Lists -> "+ Add smart list". Filter groups use AND, nested filter (AND) and "+ Add Filter" (OR) builder; AND/OR between groups in SmartLists 2.0.
- Filter fields: nearly any standard or custom field, tags, DND flags per channel, pipeline/stage/status, email status, last activity/updated/created, email open/click dates, appointments, engagement score, "Last Updated By", contact type, etc.
- Operators by type:
  - String: Is, Is Not, Contains, Does Not Contain, Is Any Of, Is None Of, Is Empty, Is Not Empty.
  - Numeric: Equal, Not equal, Between, >, >=, <, <=, Is Empty/Not Empty.
  - Date: Today/Tomorrow/Yesterday/This Week/Month/Quarter/Year, On, Between, More Than / Less Than (relative), In the Next / In the Last, After/Before, Is Not variants, Is Empty.
  - DND: Enabled/Disabled for All, SMS, Email, Calls & Voicemails, WhatsApp, Inbound, FB Messenger, GMB.
- Management: duplicate, rename, share with admins, delete, reorder columns (layout persists once saved), global (account-visible) vs personal lists, sharing controls (view/edit per user in 2.0).
- Caveats: contacts cannot be manually added (membership is purely rule-based, so there is no "static list"); no audit trail of who created or shared lists; lists cannot be moved to another account or included in snapshots (as documented); there is no public smart-list API; recipient set for email campaigns is evaluated at send time; managing smart lists needs settings access.
- Also exists: Smart Lists for Opportunities, Companies, and Custom Objects ("Smart Lists in Opportunities").
- Ideas board: "Save Smart List (Contacts) Columns" and "custom columns on the contacts page to stay permanent" show column persistence on the plain "All Contacts" view has been a long-running complaint.

### 2.8 Bulk actions (Contacts and SmartLists)

Bulk Actions page is a job log with filters (status, action type, user, date range), per-job Show Stats (totals, success/error counts, delivery outcomes) and downloadable error logs.

Available actions: Import (contacts, contacts + opportunities, companies), Delete contacts (only action with restore, about 60 days, run as a restore job), Add tag, Remove tag, Bulk SMS/MMS, Bulk Email, Bulk Email Verification, Bulk update contacts to Company, Add to / remove from workflow, add to / remove from campaign, update fields (including custom), apply/clear DND, WhatsApp bulk send, opportunity updates.

Job controls: Pause, Edit (reschedule), Cancel on eligible running jobs (e.g., queued SMS). Records already processed stay processed. No undo for tags, SMS, email.

Drip mode (new architecture): Batch quantity 1 to 10,000 contacts per run; Repeat After (minutes/hours/days); Send On (days of week); Process Between (hours window in account timezone); End At (daily cutoff); previous 720-hour cap removed; checkpointed after every batch so restarts resume; each batch is a separate workflow-history execution; DND contacts deferred; works for SMS/MMS, email, tag changes, add to workflow, opportunity updates, and the "Action - Drip" workflow step. Example platform cap: 1,000 SMS per minute at 1-minute frequency.

### 2.9 Import / export

- Import: Contacts -> Import. Admin only. CSV only (no XLSX/Google Sheets), under 30 MB, single sheet, header row must match system fields, each row needs at least one of name/email/phone. Steps: choose objects (Contacts only or Contacts + Opportunities) -> upload and choose add-new vs update-existing -> map columns (custom fields must exist beforehand) -> optional actions (create a Smart List of imported contacts, add to workflow, add tag) -> review -> start.
- Matching order when updating: Contact ID, then email, then phone. "Don't update empty values" checkbox protects data. "Skip unmapped columns" option.
- Opportunity columns (pipeline, stage, status, name, etc.) can be in the same row; contact and opportunity are linked automatically.
- Common failure modes documented: header mismatch, blank required fields, formatted phone numbers, duplicates inside the file.
- Progress shows in Bulk Actions with stats and an error log tab.
- Companies and custom objects have their own CSV import: modes Create, Update, Create & Update; dedup by Record ID or a configured unique field; "update empty values" toggle; cannot be reversed; Company import does not create associations to contacts or opportunities; bulk import of associations is not available.
- HubSpot import tool exists ("Import data from HubSpot").
- Export: from Contacts list (selected or all), Opportunities three-dot menu "Export Opportunities". Export includes all opportunity fields even if the card shows only 7.

### 2.10 Duplicates and merging

- Setting "Allow Duplicate Contact" (Settings -> Business Profile -> Contact Duplication Preferences, auto-saving). When OFF, a new form/Zapier/Messenger submission that matches the primary field (Email default or Phone) updates the existing contact; optional second preference field (e.g., Email then Phone). When ON, separate records are created and can be merged later with the Merge Contacts feature.
- CSV imports always merge by phone/email regardless of the setting.
- FB/IG messenger contacts: when disabled they auto-merge on matching email/phone; when enabled you merge manually.
- Merge: manual merge of two contacts; third-party sources say there is no native merge undo and the most recently updated value wins on conflicts (unverified). Duplicate WhatsApp contact resolution has its own article, which suggests this is a recurring support issue.
- Opportunity duplicates: "Allow duplicate opportunities" toggle in settings; without it a contact cannot appear in two opportunities (primary or additional). Workflow toggle "Multiple Opportunities" and "Create New Opportunity" toggle semantics are documented separately (indicating confusion).

### 2.11 Companies (Business) object

- Companies module under Contacts -> Companies; required company fields plus custom company fields; Company Record ID; configurable unique fields used for dedup; list view with sort/filter; CSV import; bulk action "update contacts to company"; Smart Lists for Companies; tasks and notes across companies.
- A contact has one primary company in practice (one of the most-voted requests on the whole ideas board is "Assign multiple companies to a single contact", 383 votes, in progress). The Company object can be associated with contacts, opportunities and custom objects via association labels.
- "Company Object Feature: A Manual Way to Organize Contacts" article shows it started as a manual grouping, then gained workflow actions: "Create and Associate Company" (three association patterns), auto-link actions that connect contacts/companies/custom objects with earliest/latest/all matching rule.
- Company custom fields exist (separate from contact fields). Company mobile support is requested (6 votes).

### 2.12 Custom objects and associations

- Custom objects: user-defined record types (Properties, Pets, Vehicles, Policies...). Available on all plans (official), limit 10 custom objects per location; admins create/edit, others read-only. Each needs singular name, plural name, internal name, primary display field + label, icon, description. Internal name and primary field are not changeable after creation (FAQ; article text is inconsistent).
- Fields: standard custom-field types; up to 10 "unique" fields per object (Single Line, Multi Line, Number, Phone), uniqueness enforced across UI, workflows, forms and API; once unique cannot be re-enabled after turning off.
- Supported surfaces: contact and opportunity associations, workflows, forms, surveys, quizzes, smart lists, list view, advanced filters, reporting, API, webhooks, tasks. Not supported (as documented): email/SMS campaigns, conversations, calendars, reviews, payments, funnels/website dynamic data. Coming soon: notes, dynamic site binding, AI knowledge base, emails to associated contacts.
- Deleting an object permanently removes records, associations, workflows and fields.
- Pre-built "Custom Object Templates" for vertical setups; snapshots can carry custom objects (with limits).
- Associations (Settings -> Objects -> [object] -> Associations): single label (e.g., "Colleague") or paired labels (e.g., "Buyer <-> Seller"); relationship types one-to-one, one-to-many, many-to-one, many-to-many, and N-to-N; per-label limits up to 1,000 linked records per side; up to 10 labels per object pair; removed automatically when a record is deleted; renaming a label is cosmetic; association info available in Kanban cards (Association Label field), list columns, filters, bulk actions, exports.
- Supported pairs: Contact<->Contact, Contact<->Company, Contact<->Custom Object, Opportunity<->Custom Object, Opportunity<->Company, Company<->Custom Object.
- Workflow actions: Add Associated Records to Workflow, Remove Associated Records from Workflow, Associate Records (Labs beta), Create and Associate Company, link contacts/companies/custom objects automatically.
- API/automation support for some association paths was "coming soon", and association bulk import is not available (fragmented rollout).
- Mobile app does not support objects yet (99 votes, under review).

### 2.13 Notes

- Notes on contacts, opportunities, companies (articles: "HighLevel Notes for Managing Contacts, Opportunities and Company Records", "CRM Notes Association - Link Notes Across Contacts & Opportunities", "How to Use Opportunity Notes"). Notes can be linked across contacts and opportunities. Primary-contact notes can appear as an opportunity list-view column. Custom objects notes are "coming soon". Notes show in timeline; @mentions notify.

### 2.14 Tasks (CRM)

- Tasks list page, plus Tasks tab on contacts/opportunities/companies/custom objects. Fields: title, description, due date/time, assignee, status (Open, Completed, Overdue), associated records.
- Multi-object task associations: one task links to up to 10 records of each type (Contacts, Opportunities, Companies, Custom Objects). Defaults: from a contact, links contact + its primary company; from an opportunity, links the opportunity + primary contact + that contact's primary company. Visibility: a user sees a task if they can access at least one linked record. Recurring instances inherit associations. Workflow association actions not yet available.
- Contactless (internal) tasks are possible; "Unassigned" contact filter finds them; workflow "Add Task" action creates contactless tasks when the workflow has no contact; dynamic due dates ("2 days from now at 5:00 PM") are configured in workflows.
- Recurring tasks (third-party description): intervals from hourly to yearly; end never/date/count; option to create next instance even when previous is overdue; edit all future vs this instance; deleted tasks restorable within about two months. Unified task management across contacts and opportunities in one list.
- Project Management (private beta) is a separate module (spaces, folders, lists, subtasks).
- Ideas board: Helpdesk/Ticketing is the most-voted CRM request (1.0k votes, in progress) which implies users bolt ticketing onto tasks today.

### 2.15 Activity timeline

- Contact timeline and the Conversations center panel include Activity Cards (opportunity created/updated/deleted, appointment booked/rescheduled/canceled, DND on/off with actor: workflow, user or contact, invoice sent/payment received). Timeline filter: All, Conversations, Activities, Email, Internal Comments, Contacts, Opportunities, Payments, Invoices, AI Action Logs.
- Every field change via Auto-Save is logged. Opportunity IDs expose a 60-day audit log.

### 2.16 DND (Do Not Disturb)

- Per-contact DND for All channels or per channel: Email, SMS, Calls & Voicemails, plus Facebook Messenger, Google Business, WhatsApp (after integration). Statuses: enabled/disabled/partial. Inbound DND: blocks inbound calls and SMS from that number, applies to all channels together, inbound SMS blocked at system level (messages may still bill).
- Email DND exceptions: invoice payments, calendar notifications and transactional notifications still go out; marketing blocked.
- Auto-DND: SMS opt-out keywords (STOP, UNSUBSCRIBE, etc.) and carrier error codes 30003-30006 set DND automatically; temporary DND removable by user; permanent DND requires contact opt-in or proof of opt-in to support. Email DND set on unsubscribe, spam report, permanent bounce.
- Workflow integration: Contact DND trigger (filter by channel/direction), Enable/Disable DND action (channel + direction), trigger-link-based unsubscribe flows. Smart-list filters on each DND flag. Ideas: "DND incoming to also be in automations" (9 votes, in progress), "DND for phishing and spam emails" (20).
- Voice AI outbound note: the platform does not check per-contact consent at call time; the business is responsible, even though DND exists.

### 2.17 Contact scoring (engagement score)

- Rules at Settings -> Manage Scoring. Each rule = action type (email events: open/click/bounce/unsubscribe, form submissions, payments, appointment bookings, etc.) + points (positive or negative). Draft then publish to apply to all contacts.
- No automatic decay; reducing for inactivity needs a timed workflow. No defined tiers or levels; the score is a numeric value usable in smart lists (numeric operators) and workflow triggers (e.g., "score > 20"). Displayed in the contact profile and the Conversations right panel; also an optional Kanban card field for opportunities created or updated after 2025-03-19.
- Gaps vs mature CRMs: no lead-vs-account scoring, no predictive scoring, no score history chart in docs, no decay, no negative-demographic scoring in docs.

### 2.18 Client portal and documents on contacts

- Documents tab on contact; Documents & Contracts module; client portal sharing of documents (article "How to Share and Manage Documents via Client Portal and CRM").

### 2.19 CRM pain points

- Search: "Search inside contact conversations" (128 votes), "Search past conversations for specific text" (332 votes, in progress), meaning global text search of messages has been missing for years.
- Companies: only one company per contact until recently (383 votes).
- Custom fields: no conditional/hide logic for contacts (104 votes), no field sync between fields, no way to hide sensitive contact info for specific users (requested), no country-code filtering (requested), no multi-currency (217 votes on opportunity value).
- Smart lists: no static lists, no smart-list API, cannot be snapshotted, no audit log, column persistence on "All Contacts".
- Imports: CSV only, 30 MB cap, headers must match, custom fields must pre-exist, no undo; companies and association import is separate and does not associate.
- Duplicates: behavior depends on source (form vs CSV vs messenger), requiring explanation in six help articles. No native merge undo (unverified).
- Permissions: ability to deactivate users (60 votes), manage notifications only for assigned user (10 votes), compliance center requests.
- Inconsistent nomenclature: contact fields vs custom values vs merge fields vs trigger links; "business" vs "company"; "location" vs "sub-account".
- Several features exist in both a legacy and a new version (contact list, smart lists, pipelines, snippets) with Labs toggles, producing support confusion.

---

## 3. Opportunities and Pipelines

### 3.1 Concepts

- Pipeline = ordered stages left to right. List of pipelines is available at Opportunities -> Pipelines. An updated HighRise-based Pipelines experience can be enabled from Labs.
- Opportunity = a deal linked to a primary contact (up to 10 additional contacts per opportunity; a primary cannot also be additional; lists and workflows currently only use the primary contact's details). Opportunities can also link to companies and custom objects through associations.
- Status values: Open, Won, Lost, Abandoned.

### 3.2 Opportunity fields (entity)

Standard: opportunity ID, name, pipeline, stage, status, monetary value, source, owner (assignedTo), followers, primary contact (name/phone/email/business name), additional contacts, expected close date, probability (stage default or manual override), lost reason (managed field), tags (on contact, weak on opportunity), created/updated dates, days since last stage change/status change, notes, tasks, appointments, conversation counters, engagement score, association labels.
Custom: opportunity custom fields (folder grouping, "Hide empty fields", conditional show/require rules in Labs). Field types: Single Line, Multi Line, Dropdown, Radio, Number, Monetary, Phone, Date, etc. (sort supported for these in list view).

### 3.3 Views

- Board (Kanban) view: cards with up to 7 configurable fields (standard fields, custom fields, primary-contact details, activity dates, association label, engagement score), a Quick Actions tab to choose the bottom icon counters (conversations with unread count, tasks, notes, tags, calls, appointments with next date). Card layouts: Default (labels+values), Compact (values only; labels on hover), Unlabeled (values only, one per line). Stage columns collapse/expand and resize by dragging. Settings are per user and stored in browser local storage, so they do not follow the user across browsers or devices (a notable design weakness). Smart tags can color-code pipelines; stage colors are customizable. Multiple pipelines supported; customization applies per pipeline or to all.
- List view: table with Customize Columns (resize, reorder), sort by default or supported custom fields, filters with parity to board, search, export. "All Pipelines" option merges all pipelines in one list (list view only; no sort by stage, falls back to created date; saved All Pipelines views are list-type smartlists). Optional Primary Contact Notes column.
- Opportunity forecasting (Labs, early access): Summary dashboard with Maximum Potential Revenue, Expected Revenue (weighted by stage probability or manual override), Won Revenue; Forecast Timeline by week/month/quarter driven by Expected Close Date; drilldown to underlying deals; risk classification High/Medium/Low from delay and slippage with configurable thresholds; data hygiene insights (missing amounts or dates, stale deals); filters by pipeline/owner; group by owner or close date. Formula details are not documented.
- Search, advanced filters (including by status, pipeline, stage, owner, custom fields, dates), smart lists for opportunities (saved views), pipeline reorder, duplicate/copy pipelines to other sub-accounts.

### 3.4 Pipeline settings and governance

- Stage edit: rename, reorder, add, delete (moves its deals to a chosen stage), per-stage "show in funnel/pie chart" reporting visibility toggle.
- Pipeline permissions (key icon): sharing modes All users / Selected users or roles / Exclude users; access levels View Only (work existing deals but cannot change stages/pipeline), Edit (change stages and pipeline), No Access (hidden across web, mobile and API). Admins always have full access. Cannot remove access from a user who owns deals in that pipeline. Changes in audit log for 60 days. API with token lacking access returns empty list.
- Bulk edit: Select on cards or in list; Edit button allows changing owner, pipeline and stage, status, value. Select-all-on-page appears at 20+ items; "select all N" for the whole view; drag-drop disabled in selection mode.
- Automations: triggers for opportunity created, stage change, status change, stale deals (stale-opportunity automation pattern), Create/Update Opportunity actions with "allow multiple opportunities" toggles, opportunity workflow actions, Add Task, notifications.
- Import opportunities via CSV along with contacts.
- Prospecting tool integration: add prospects to a pipeline from the prospecting tool.
- Payments: opportunities connect to invoices/subscriptions through the contact.

### 3.5 Lost reasons

- Lost Reason is a dropdown-like managed list in Settings -> Custom Fields; editing via Bulk Actions -> Edit; rename propagates; used as filter and as card field; lost deals found via Advanced Filters -> Status = Lost. No built-in win/loss analytics page documented beyond reports.

### 3.6 Opportunity pain points (from ideas board votes)

- "Show conversations on the opportunity card" (280 votes, in progress).
- "Filter opportunities by tags" (254 votes).
- "Make fields on opportunity card required" (181 votes, in progress). Conditional rules (Labs) partially address it.
- "Opportunities scheduling; not simply contact scheduling" (129).
- "Create opportunities without a contact attached" (45, planned). Everything in the CRM keys off the contact, which limits B2B account-based sales.
- "Customize/reorder standard opportunity fields", "customize opportunity detail view as for contacts", "restrict user from deleting opportunity", number formatter for custom fields, "last contacted / last activity date filter in card view".
- Card view preferences stored in local storage (not synced to user profile).
- No currency per opportunity (217 votes for multi-currency lead value).
- Forecasting is Labs and thinly documented.

---

## 4. Conversations / unified inbox

### 4.1 Layout (four panels, HiRise)

1. Inbox panel (far left): My Inbox (assigned to or followed by you), Team Inbox (all conversations, needs full data access), Internal Chat (private team chat, Labs). Users with "assigned data only" see My Inbox + Internal Chat, not Team Inbox. Saved views/folders also appear here.
2. Chat list: conversation rows with checkbox (select all), unread dot/count, star icons, channel icon, snippet preview. Tabs: Unread, Recents, Starred, All, plus quick tabs like Mine (per article, "All" and "Mine"). Real-time unread counter. Sorting: Latest/Oldest All Messages, Latest/Oldest Manual Messages (human-sent only), Longest SLA Overdue, Next SLA Target. Bulk actions: Mark read/unread, Star/Unstar, Delete (permanent). Archive removes from Recents but keeps in All; new messages move it back to Unread.
3. Message history (center): single timeline mixing Email, SMS, WhatsApp, FB/IG messages, calls, voicemails, internal comments, AI action logs and activity cards. "New" divider and jump to first unread (only for messages after 2026-04-23). Composer: channel selector (remembers last), formatting, attachments, clipboard paste, full-screen mode, drafts persisted across channel switches and conversations (and across conversations), inline email replies, CC/BCC support, internal comment tab, snippets button, schedule/send options. Timeline filter (top right): All, Conversations, Activities, Email, Internal Comments, Contacts, Opportunities, Payments, Invoices, AI Action Logs. Message details show source (marketplace app or custom provider). Call transcripts open in this panel.
4. Right panel: contact fields (edit in place), custom fields/folders, tags, owner, engagement score, tabs Contact / Activities / Associations / Documents / Payments, create opportunity/appointment/invoice/payment. Collapsible. Expandable sidebar variant.

### 4.2 Filters and views

Filter builder (session-based, must be re-applied; can be saved as a view): Assigned (incl. Logged-in user), Follower, Mention, Last Message Direction (inbound/outbound), Last Outbound Message Type (manual or automated), Last Message Channel (SMS, Email, Calls, Voicemail, Live Chat, WhatsApp, Facebook, Instagram, GBP; multi-select), Tag. Operators Is / Is not. AND/OR within and between groups. Quick filters for "mentions me". SLA-based sorting exists (SLAs; but ideas board shows "SLAs are useless, need these 3 features", 12 votes).

Keyboard shortcuts: Ctrl/Cmd+K global search, Ctrl/Cmd+Enter send, Ctrl/Cmd+Shift+E full-screen composer, "?" lists the rest (not customizable).

### 4.3 Channels

- SMS and MMS: via LC Phone (Twilio under the hood) or direct Twilio; From/To number selection per conversation (article "Select SMS To and From Numbers"); multiple numbers per contact (additional phones); number pools; scheduling; segment counting and billing; opt-out keyword handling; MMS attachments with carrier size limits; Number Intelligence validates numbers before first SMS (landlines blocked).
- Group SMS: 2 to 9 participants, US/Canada long codes only (no toll-free or short codes), no add/remove after creation, DND contacts cannot be added, participants fixed once created, mobile and desktop.
- Email: 2-way email via HighLevel's sending infrastructure (Mailgun/LC Email, SPF/DKIM/DMARC required for custom sending domains) or SMTP / Gmail and Outlook sync ("2-way Gmail Sync and Outlook sync with excluded domains" 230 votes, planned). Composer: CC/BCC, templates, snippets, signatures, inline replies, full-screen expand. Missing for years: "Reply-to email address" configuration (541 votes, the top Conversations request, "upcoming").
- WhatsApp: WhatsApp Business via Meta Cloud API; $10 per sub-account per month agency fee; per-delivered-message billing since 2025-07-01; rebilling multiplier 1x to 10x (default 1.05x); templates in categories Marketing, Utility, Authentication, Service (free-form only). Customer-service window 24 hours; templates required outside it; Click-to-WhatsApp ads give free 72-hour windows; WhatsApp calling (inbound free, outbound per minute in 6-second increments, not available for US/Canada/Egypt/Vietnam/Nigeria-registered numbers). Changes announced for 2026-10-01: service messages billable after first 1,000 per number per month, utility messages inside window become billable, rate changes in several markets. Oct 2026 changelog: rebuilt template builder with live preview and per-contact media headers, "limited time offer" templates with countdown/copy-code.
- Facebook Messenger and Instagram DM: via Meta page connections; quick replies for FB/IG; chat widget can route to Messenger or IG DM; personal-profile messaging via a marketplace integration only; "pause Conversation AI when a native IG/FB reply is detected" is a 67-vote request.
- Google Business Profile (GBP/GMB) chat/messages and Google reviews threads: GBP page name shown on review threads; Google Business Messages itself was retired by Google in 2024, so "GBP" in the inbox now mainly covers reviews and call/message features.
- RCS Messaging: a board exists on the ideas site; RCS carrier fees are mentioned in billing pass-through (5% markup). Treat as emerging.
- Live Chat / Chat Widget: Sites -> Chat Widget; types Live Chat, SMS chat, Email chat, FB/IG, Voice AI widget. Settings: intro message (collect visitor details), agent avatar/branding, inactivity fallback message (asks for contact details), chat timeout message, auto-close inactivity, End Chat. Messages appear in inbox with chat icon and "Live Chat" filter. Assignment via workflow (trigger Customer Replied or New Chat Message, filter channel and widget, action Assign to User). Embedding via script; WordPress plugin. A2P pre-built campaign registration with chat widget is a documented path. "Video chat bubble" is a 372-vote request.
- Calls and voicemail in the same timeline (call recordings, transcripts, AI summaries; "why calls or messages appear incorrectly in Conversations" is a documented troubleshooting article).
- Custom provider/marketplace channels: messages can show the marketplace app that sent them (custom conversation providers via API).

### 4.4 Collaboration

- Internal comments: private notes in the thread with @mentions (cannot be edited or deleted, no attachments; filterable via Mentions quick filter; notifications per user profile settings). New workflow action (2026-10-14) posts internal comments including @mentions without messaging the customer.
- Internal Chat (Labs): private team chat in the Conversations module, subject lines, text, emoji, attachments, add users with or without history, members cannot be removed, notifications configurable; only sub-account users; "Login As" users cannot view; no extra cost.
- Assignment: conversation owner = contact owner; manual or workflow "Assign to User", round-robin via workflows; followers; unassigned filter; SLA metrics.
- Snippets: text and email snippets with folders, search and filter by type, merge custom values, trigger links, editable after insert, duplicate/move/edit; also reachable from Marketing -> Snippets; requires "View & manage conversation" permission. Quick replies for FB/IG are separate.
- Templates: email templates (builder), SMS templates (Marketing -> Templates), WhatsApp templates (Meta-approved).
- Drafts: save draft messages (article exists).
- Read/unread management: mark as read/unread, auto-mark rules, unread count in navigation is a long-standing request ("Number of unread messages in conversations menu bar" open since 2022/2023).
- Attachments: paste images (105 votes), upload, "Attachments made easy" article.
- Manual Actions: Conversations -> Manual Actions tab lists manual call and manual SMS tasks generated by workflow steps (see power dialer below).
- Conversation AI inline: AI Response sidebar (click AI icon under any AI message) shows the response, the prompt followed, detected intent, and the sources (trained URL or FAQ); prompt and KB entries can be edited in place (changes apply to future responses and show an "Edited" label; no undo, re-edit to restore).
- Contact Engagement score visible in the right panel.
- Trigger links in conversations (HiRise: "Understanding Trigger Links").

### 4.5 Conversation pain points

- No full-text search across messages historically (332 + 128 votes). Search was "in progress".
- Email handling: weak reply-to control (541 votes), email-sync exclusions, "nightmare to read emails" comments, no real shared-mailbox features, no per-user signatures parity, large HTML emails render poorly (anecdotal).
- Message ordering/lag bug reported in 2024 board ("texts received out of order"), delayed delivery, "delay sending SMS in conversations" request.
- Filters reset every session (session-based) unless saved as views.
- Delete in bulk is permanent; no recycle bin for conversations.
- Internal comments cannot be edited/deleted.
- Group SMS is limited and fixed.
- Many shipping pieces are "HiRise" vs classic variants, causing inconsistent UI.
- Tags, owners and DND logic mean that "who may text this contact" is hard to see in one place (the DND status sits on the left panel tab of the contact and is not always shown in the composer).
- Unread counter and notification noise: desktop pop-up notifications are a 263-vote request.

---

## 5. Phone system (LC Phone and calling)

### 5.1 Architecture

- LC Phone (LeadConnector Phone) is HighLevel's own telephony layer, running on Twilio infrastructure, enabled by a toggle with no external accounts or API keys. Direct Twilio connection (bring your own Twilio, with webhooks for incoming calls/messages/status) is still supported. Migration paths: Twilio -> LC Phone for agency and sub-accounts; moving numbers between sub-accounts (same agency or across accounts); porting numbers in.
- Compliance steps by region: regulatory bundle and address for sub-accounts (non-US), UK KYC, toll-free verification (needs the business website), Geo permissions for voice, account suspension rules ("Why is your account suspended" article).
- Real-time error monitoring, number ramp-up protection, opt-out link management, DND thresholds based on error rates, SenderID configuration, Voice Integrity (number reputation) and Number Intelligence tools.

### 5.2 Number management

- Buy numbers (local or toll-free) in Settings -> Phone System -> Phone Numbers; also purchasable from the Voice AI deploy screen. Per-number Edit Configuration: name/label; Calls Go To (external number, business number, Voice AI, or ring multiple team members up to 6 or 7 (documentation conflicts) simultaneously; first to answer wins); team member devices (web app, mobile app, phone number, VoIP desk phone); Call recording toggle with "play recording message" whisper; Incoming call timeout (blank = 60 seconds; recommended about 20 seconds so CRM voicemail answers before personal voicemail); Outgoing call timeout (blank = 60 seconds); Backup (voicemail or Voice AI); Advanced: Call Connect (recipient presses a key to accept, confirms human answer; helps Missed Call Text Back logic and call status accuracy), Whisper message (TTS), Bring Your Own Number / verified caller ID, caller ID shown on received calls (caller vs dialed number), "Prefer forwarding calls to" (contact owner or phone number owner), connect behavior for outbound (immediately vs after recording message).
- Default phone preferences for new sub-accounts can be preset by the agency.
- Call forwarding to a HighLevel number (conditional forwarding recommended for missed call text back).

### 5.3 Inbound routing order

1. IVR / workflow routing / Voice AI set to "Answer calls directly" (handled first, stops further routing).
2. Owner-based routing (contact's assigned user or number's assigned user), if "Prefer forwarding calls to" is set.
3. Team members and devices; Ring More Team Members (up to 6 more).
4. Forwarding destination (external or business number).
5. Timeout -> Backup: Voice AI (as backup) or voicemail.

### 5.4 IVR / call menus

- IVR is built in Workflows: "Start IVR" trigger and actions such as Send Call to Number, Send Call to Call Menu, gather keypad input, play prompts, route to users, departments or other workflows ("Press 1 for Sales"). It is connected on the number's routing configuration as the first routing option. There is no standalone visual IVR designer in Phone settings (third-party guides call this out; it lives in the workflow builder).
- Ask AI can buy numbers but cannot configure IVR or call routing.

### 5.5 Voicemail

- Company voicemail (Settings -> Phone System -> Call & Voicemail Settings), user voicemail (Settings -> Users, takes precedence for assigned contacts/numbers), workflow Voicemail Drop action. Audio MP3 or WAV, recommended 64 kbps (higher bitrate can reduce delivery). Voicemail transcription (priced at $0.024/min in the billing guide). "Ability to delete voicemails" is a 4-vote request.
- Ringless voicemail / voicemail drops: workflow action; implemented as a call plus a quick second call leading to voicemail; delivery not guaranteed; needs prerecorded-call consent; has daily limits that increase with usage history; voicemail drops billed at $0.018/min.

### 5.6 Call recording and AI call features

- Call recording at number level with disclosure whisper; $0.0025/min record + $0.0005/min/month storage. Transcription $0.024/min. Call summaries via AI. Answering machine detection $0.0075 per call. Conference calls $0.0018 to $0.0040 per participant-minute by region. Amazon Polly TTS for whispers $0.00084 per 100 characters.
- Call scripts: Settings -> Phone System -> Voice -> Call Scripts; plain text only; assignable to users/teams; shown in web dialer, app dialer and LeadConnector app during live calls.
- Web dialer and app dialer with audio device settings, auto-minimize/pin/drag, call transfer (blind and warm via the legacy Eliza dialer), logging external calls (workflow action "Log External Call"). "Call Connect" ensures accurate call status.
- Workflow trigger "Call Details" for call outcomes (status, duration, direction, etc.); call reports with keyword attribution for number pools.

### 5.7 Power dialer (native)

- Native "power dialer" is a workflow-driven call list: add a Manual Action -> Call step in a workflow; triggers (tag added, pipeline stage changes, form submit, appointment) add the contact to the rep's call list in Conversations -> Manual Actions, optionally assigned to a specific user. The dialer works through the list, log outcome (No Answer, Busy, Voicemail, Completed), progress bar. It is not a true parallel/predictive dialer; third-party tools (Kixie, PhoneBurner, Aloware) are commonly bolted on. A "Manual SMS" action works similarly.
- Competitive gaps: no parallel dialing, no local-presence caller ID rotation (partially via number pools), no AI voice detection to skip IVRs, no spam-reputation dashboard beyond Number Intelligence.

### 5.8 Missed Call Text Back (MCTB)

- Implemented as a workflow with trigger "Call Status / Missed Call" (statuses such as no-answer, busy, failed, voicemail, cancelled) followed by Send SMS (and optionally Conversation AI to carry the thread); also a one-click toggle in settings per some third-party guides (conflicting menu paths). Call Connect improves accuracy so voicemail pickups are not counted as answered. Needs A2P registration for SMS delivery. Recommended text under 160 characters.

### 5.9 Call tracking and number pools

- Number pool (Settings -> Phone Numbers -> add number pool, "Visitors Activity"): minimum 4 numbers per pool; swap number shown on site for visitors from chosen sources (paid search, all except direct, etc.); calls to pool numbers forward to a forwarding number (not a Twilio/LC number, to avoid loops, and cannot be routed to web/mobile app); whisper message for the answerer; optional recording; tracking snippet (body tracking code) or per-page footer code; group IDs for multi-pool pages; keyword capture via `?keyword={keyword}` on Google Ads URLs; reporting in Call Report (Keyword column) and contact activity (landing page); each pool number billed as a standard number. tel: link formats must match swap number format.
- Dedicated tracking numbers per source are also used, with attribution reports.

### 5.10 SMS compliance (A2P 10DLC) and deliverability

- US carriers require registering a Brand (business identity) and a Campaign (use case, samples, opt-in evidence) per sub-account; Sole Proprietor, Low Volume, High Volume (Standard) types. Fees (billing guide): Sole Proprietor 3,000 daily segment limit, up to $2.10/campaign/mo, $22.50 one-time (includes $3 Fast Track fee, non-refundable); Low Volume 6,000/day, $1.50-$10.50/mo, $22.50 one-time; High Volume $10.50/mo, $64.00 one-time. Resubmissions free as of 2026-02-01 (the earlier $15 was removed).
- Rejection ecosystem: dozens of numeric codes (30881-30995). Resubmittable families: opt-in and consent (30909, 30913, 30917, 30923-30925, 30931, 30932, 30887, 30890), website (30919-30922, 30907, 30908, 30888), identity (30914, 30915, 30918, 30926, 30927, 30971, 30972), use-case content (30910-30912, 30916, 30886, 30892-30893, 30889), registration (30895, 30898, 30930 for 100-campaign cap). Non-resubmittable: SHAFT content (30953-30958), disallowed categories (30940-30952: cannabis, loans, debt collection, gambling, crypto, credit repair, third-party lead gen, MLM), high-risk (30959-30964: fraud, URL shorteners, HTTP links). Legacy codes were replaced with granular codes on 2026-03-23. "Maximum 3 tries exhausted" requires EIN letter (CP 575 or 147c) and support intervention.
- Form requirements: separate unchecked optional consent checkboxes for marketing vs non-marketing, visible Privacy Policy and Terms links with non-sharing clause, matching brand details, DBA disclosure, subdomain relation.
- Error 30034 (linking number to approved campaign) and "From number not SMS-capable" and "Inbound SMS showing as calls" are common documented troubleshooting items.
- Number Intelligence bundle (on/off together): spam detection ($0.005/test), name lookup ($0.01), number validation ($0.005) before first SMS; format lookups free.

### 5.11 Pricing (LC Phone, billing guide)

- Numbers: local $1.15/mo, toll-free $2.15/mo.
- SMS (US/Canada): $0.00747 per segment out and in (10% discount off an $0.0083 list), plus carrier pass-through fees per segment: AT&T $0.0035 out, T-Mobile $0.0045 out ($0.0025 in), Verizon $0.0050 out ($0.0070 in), US Cellular $0.0050 out ($0.0100 in), others $0.0042 out ($0.0100 in).
- MMS (US/Canada): outbound $0.0220, inbound local $0.0165, inbound toll-free $0.0200, plus carrier fees ($0.007 to $0.010).
- Voice per minute (US/Canada): outbound about $0.0166, inbound about $0.01165, inbound toll-free $0.0198, inbound to forwarding number $0.02; billed in full-minute increments, rounded up.
- Extras listed above (recording, storage, transcription, AMD, voicemail drop, conference, TTS).
- 5% markup on pass-through fees (A2P, carrier fees, verified caller ID, RCS) only when rebilling is on for the sub-account. Agency can rebill at a markup of own choosing for most usage (requires Agency Pro for AI rebilling).
- Third-party sources quote an all-in effective SMS cost of about $0.011+ per segment after carrier fees (unverified, from a competitor page).

### 5.12 Phone pain points

- A2P/toll-free registration friction: dozens of rejection codes, per-sub-account brand + campaign, EIN mismatches, "3 tries exhausted", content-category bans; this is the number-one onboarding blocker for agencies.
- Account suspensions and usage-based pauses (e.g., Voice AI outbound auto-pauses on Acceptable Use thresholds).
- Billing in full-minute rounding for voice versus Voice AI per 6-second billing.
- IVR lives in the workflow builder, not in phone settings; Ask AI cannot set up routing; call routing options spread over three screens (number config, Voice AI Deploy tab, workflow IVR), which the help center needs a whole article ("Inbound Call Handling: IVR, AI Routing, Call Flow Explained") to explain.
- Mobile "direct SIM card integration" is a 418-vote request (the app uses VoIP or call forwarding, not native carrier calls).
- Call quality/status accuracy issues (Call Connect was added to solve false "answered" status).
- Number pools: minimum 4 numbers, forwarding only to external number, no routing to app.
- UAE and other country coverage requests.
- Ringless voicemail not guaranteed; limits.
- Ring group inconsistent documentation (6 vs 7 users).

---

## 6. AI features ("AI Employee")

### 6.1 Product map (2026)

| Product | Audience | Purpose | Maturity |
|---|---|---|---|
| Ask AI | Operator (logged-in user) | In-app copilot: content, data retrieval, CRM actions, bulk actions, builds agents/funnels | GA |
| Conversation AI | Customer/lead | Text/chat bot that answers, qualifies, books | GA, most mature |
| Voice AI | Caller | Inbound/outbound phone agents, web widget | GA, rapidly iterating |
| Managed Agents (formerly Super Agents) | Owner/marketer | Autonomous CRM agents from plain-language spec, event-triggered | Early access/Labs, GA planned 1 Sept 2026 per article |
| Agent Studio | Builder | Visual node-based builder for existing flow agents (legacy; new agents should use Managed Agents) | GA (maintenance) |
| Workflow AI | Builder | Natural-language workflow builder + AI actions (Decision Maker, Intent Detection, Summarize, Translate) + SMS AI | GA/partly Labs |
| Reviews AI | Reputation | Suggest/auto-post replies to reviews, drip backlog replies, insights | GA |
| Content AI | Marketer | Text and images in social planner, email builder, blogs | GA |
| Funnel & Website AI | Builder | Generate/edit pages in builder with chat refinement, SEO suggestions | Labs |
| Email AI | Marketer | Brand-aware email generation (Email Campaign Agent Beta) | Labs |
| AI Studio | Builder | Conversational workspace to build sites, landing pages, forms, booking, interactive web apps; GitHub sync (Oct 2026), chat widgets, payments checkout | Labs, shipping weekly |
| Knowledge Bases | Shared | Central store for AI-ready content | GA |
| MCP Server/Connectors | Developer | HighLevel MCP server, MCP connectors for managed agents, Skills platform | GA/early |

### 6.2 Pricing (verify before quoting; third-party blogs disagree in places)

Official help center summary (HighLevel AI Product Pricing / "AI tools" article):
- Pay-per-use: no monthly AI fee, billed by token, action, response, minute, image, word count.
- AI Employee Growth: $50 per enabled sub-account per month. Allowances: 1,000 Conversation AI responses, 100 Voice AI minutes, 100 Managed Agent runs, Reviews AI and Content AI unlimited (fair use), Ask AI and AI Studio included usage (measured in 5-hour windows), prompt optimizer allowances. Overages at pay-per-use rates.
- AI Employee Unlimited: $97 per enabled sub-account per month. Unlimited (fair use) Conversation AI, Voice AI, Reviews AI, Content AI; 1,000 Managed Agent runs; 3x Ask AI and AI Studio usage.
- Agent Studio: pay-per-use on every plan (web search $0.01 each; model cost by provider).
- Funnel/Website AI and Workflow AI builder: free with daily limits; premium workflow actions ("Premium Workflow Actions") $0.01 per execution (third-party summary); external models billed by provider.
- Email AI and Knowledge Base: no extra cost, fair use.
- Phone system charges (LC Phone) are always separate from the AI plan.
- Rebilling AI to clients requires Agency Pro ($497).

Voice AI pay-per-use component pricing (effective 2026-05-20 per blog citing the help article): voice engine $0.045/min (lowered from $0.06); TTS $0.015/min (OpenAI/Cartesia standard) or $0.035 (ElevenLabs V2.5) or $0.170 (ElevenLabs V3); speech-to-speech alternative $0.10/min (Gemini live) or $0.20/min (OpenAI realtime); LLM tokens extra; phone minutes extra (about $0.0128 inbound, $0.021 outbound per one blog). Totals: about $0.06/min base for standard voice, $0.08 for ElevenLabs V2.5, $0.215 for V3, before tokens and phone. Older figure still quoted widely: $0.13/min flat (6-second billing, 1-minute minimum per call) - treat as legacy.
Break-even guidance from blogs: Growth cheaper than Unlimited until about 883 voice minutes/mo at $0.06/min (about 319 at V3), flat plans beat pay-per-use above roughly 40-60 inbound interactions per month (unverified).
Conversation AI pay-per-use: token-based per message exchange; blog estimates about $0.002-0.005 per short SMS reply, $0.02-0.08 per 5-10 message chat (unverified).
Reviews AI pay-per-use: about $0.01 per review (single blog). Content AI pay-per-use: about $0.063 per image and $0.0945 per 1,000 words (single blog).
WhatsApp is separate: $10 per sub-account per month plus Meta usage.

### 6.3 Conversation AI (customer-facing bot)

Setup methods:
1. Guided Form Setup (Conversation AI V3): choose General Q&A or Appointment Booking; select/create Brand Voice; configure Bot Settings (name, channels, initial message, primary bot toggle, response wait time such as 2 seconds), information to collect (name, email, phone, street address, city, custom questions), objectives (collect details, Yes/No qualifying questions, offer scheduling link, "skip if already filled"), appointment booking (calendar, post-booking workflows, allow cancel/reschedule), email alerts when bot cannot answer, conversation summary (inactivity time, minimum messages, workflow trigger, store in custom field, or email). Additional Instructions limit 2,000 characters (up from 1,200).
2. Prompt Based Bot: start from General Q&A, Appointment Booking, Marketplace template or scratch; Bot Settings, Bot Training, Bot Goals; model selection; custom prompts; actions.
3. Flow Based Builder: visual branching with global behavior (tone, style, conversation intent, business info), actions, appointment options, summaries.

Modes: Off (default for new bots; training/trial remain active), Suggestive (draft in composer for human approval), Auto-Pilot (auto-send after delay). Mobile app supports pause/reactivate schedule per conversation (Edit AI Settings).
Channels: SMS, Email, Facebook, Instagram, WhatsApp, Chat Widget/SMS Chat, Live Chat; one primary bot handles general inbound per channel.
Actions: stop bot, transfer bot, human handover, auto follow-up, workflow triggers, appointment booking/reschedule/cancel (multi-calendar), conversation summaries, lead capture, custom actions (requested), update fields.
Training: knowledge base, documents, URLs (with auto-refresh of trained links), FAQs/Q&A pairs, brand voice, bot goals; "View & Edit AI Response Info" for in-place correction. Prompt Optimizer (Labs): clones the agent, simulates customer chats, suggests prompt variants; production prompt unchanged until approved.
Governance: per-contact bot status (pause for specific contacts), sleep/reactivation behavior, message limits, wait time, email notification on unanswered questions, AI action logs in timeline, Marketplace templates for installable bots (agencies can sell templates; templates bundle workflows, calendars, custom fields/values, KB).
Pain points / requests (ideas board): human handoff message at max replies (194 votes), MCP server usage in bots (158), direct webhook integration (114), custom values in Q&A (99), pause when a native IG/FB reply is detected (67), custom actions (60), conversation context (37), word limit increase (17), summary in platform language (17).

### 6.4 Voice AI

Creation paths: Browse Marketplace (installable agents), Create Custom Agent (full-screen builder), Flow Based Builder (node-based; starts with Start Call node + AI Agent node; five guided templates: Business FAQ Assistant, Front Desk Receptionist, Lead Qualification, Post-Call Automation, SMS Follow-Up; "Build with AI" generation).
Builder tabs and settings: Agent name, voice, model (LLM), language (multi-language: exact set of languages selectable; voices adjust; incompatible combos flagged), timezone, prompt (+ Prompt Optimizer), welcome message (inbound/outbound), who speaks first, pre-speech pause; Outbound settings for S2S agents (welcome message, AI disclosure, verbal opt-out); Knowledge Base selection; Actions; Advanced settings (call duration, idle reminders, silence handling, response speed, interruption sensitivity, response style, transcription/pronunciation/keywords, translation, voice speed/volume, post-call notifications/workflows/summaries and note saving, system prompts).
Actions: Call Transfer (to a human number, with transfer conditions and pre-message; not testable in web call), Agent Transfer (to another Voice AI agent), Trigger Workflow, Send SMS, Send Email, Update Contact Field, Update Tag (call outcome as tag), Appointment Booking (calendar availability + book), Custom Action/Custom API webhook, After-call actions.
Skills platform: shared capability layer across Voice AI, Conversation AI, Agent Studio, Managed Agents: CRM and data, communication, knowledge, workflow/automation, external operations, with action-level permissions (delete records, send outbound messages, change billing), tenant isolation and logs. No custom skills at launch; no separate skills API (use Agents API and MCP).
Testing: Web Call (browser), Phone Call (full telephony path), inbound/outbound scenarios; call history, transcript, recording, summary, action results; Prompt Optimizer runs scenario-based test calls and proposes variants.
Deployment (Deploy tab): number or Number Pool (LC Phone, Twilio), call routing (Answer directly or Use as backup), working hours (all hours or custom schedule, can cross midnight), chat widget connection; Voice AI Chat Widget (Labs): visitors speak to the agent in the browser (no transfer, not recorded, 10 connect/disconnect cycles in 60 seconds triggers reCAPTCHA).
Limits: up to 100 Voice AI agents per account (per widget article).
Outbound calling (workflow action "Voice AI Outbound Call"): terms accepted once per location in the action drawer; KYC/location verification required; calls scheduled 8:00 AM to 8:00 PM in the contact's timezone; up to 10 calls/minute per location; 5,000 calls/day per location; each number called once per day and up to 14 times in 14 days; same-country domestic numbers only; business responsible for consent (platform does not validate); automatic pause if Acceptable Use thresholds exceeded; dashboard under AI Agents -> Voice AI -> Dashboard & Logs -> Outbound (attempted, connected, voicemail, no answer, failed, actions triggered, sentiment, workflow name).
Analytics: dashboard and call logs, sentiment, action outcomes.
Pain points: realism (311 votes, "improve Voice AI realism"), embeddable push-to-talk widget (309, in progress), voice cloning (171), send call summary and recording after call (139, upcoming), transfers to another bot without a phone number (116), optional outbound AI disclosure (61), caller recognition (per third-party blog 174 votes), spam/robocall contacts created in CRM (91), UAE numbers. Third-party reviews mention legacy vs "new voice AI experience" quality gap and recommend third-party voice vendors (e.g., Retell/Vapi-style) for high-end use.

### 6.5 Managed Agents and Agent Studio

- Managed Agents: describe the agent in plain language in AI Agents -> Agent Studio -> Managed Agents -> Create Agent. The builder drafts goal, triggers, channels, knowledge, CRM actions. Refine via chat; test in sandbox panel; Draft -> Published. Triggers: Tag Changed, Form Submitted (file uploads can pass PNG), Chat Interface, Facebook Lead Form, Survey Submitted, plus schedule, appointment, contact created, opportunity created/status changed. Actions: update fields/tags, trigger workflows, create tasks/notes/appointments, external apps via MCP connectors (Monday.com, Cal.com, Higgsfield and growing catalog), media generation (images with quality tiers and aspect ratios up to 21:9, audio with voice and tone instructions, 8-second 16:9 videos saved to Media Storage), web search with citations, human approval guardrails via instructions. Templates for Social Media Assistant, Knowledge Base Assistant, Community Moderator, Email Campaign Manager, Day-to-Day Task Automation. Runs: 100/mo (Growth), 1,000/mo (Unlimited). Deploy to API (publish, attach Private Integration token, call from your own app). Ask AI Agent Mapping: map an agent into Ask AI.
- Agent Studio (flow agents): nodes AI Agent, Router (conditions or AI intent), Sequential, End, Search Knowledge Base, Search Web, API Call, MCP Server, text/image/audio generation, data collection nodes (email, phone, single choice, text input); Start Triggers (chat message, form submission, lead tag added); variables (global, runtime, input), Global Prompt; Staging vs Production versioning; Test tab; folders and Template Library. Now positioned as legacy: "new agents should be Managed Agents".
- Gap: two overlapping agent builders plus Conversation AI flow builder plus Voice AI flow builder equals four visual builders (confusing).

### 6.6 Workflow AI, Ask AI, others

- Workflow AI Builder: type a goal, it generates triggers and actions; refine by chat or point-and-edit; voice dictation; AI actions in workflows: Decision Maker, Intent Detection, Summarize Text, Translate, Generate Content; new Advanced Workflow Builder (node-based canvas) enabled via Labs; MCP + n8n automation guides.
- Ask AI: top-nav icon, sidebar or full-screen workspace, typed or voice input, persistent memory of preferences, saved conversations, live task tracker for multi-step tasks, responses with tables/charts/interactive inputs. Connects to 50+ modules (contacts, opportunities, pipelines, associations, custom objects, email templates and campaigns, bulk actions, SMS onboarding, blogs, social planner, ad manager, forms, surveys, calendars, invoices/payments/products, courses, Conversation/Voice AI/Agent Studio, reviews, phone numbers, WhatsApp templates, A2P registration, dashboards, users, sub-accounts, snapshots, SaaS plans, email domains, marketplace). Confirmation before writes and bulk actions; scheduling (future/recurring tasks); contact summary agent; funnel creation agent; support search; ad campaign review for Google/Facebook/LinkedIn. Limits: workflows/campaigns read-only, no chat widget config, no raw call/SMS logs, cannot configure IVR/call routing, not connected to Affiliate Manager, Listings, full Sites builder. Agency admins full access; sub-accounts need a paid AI plan or pay-per-use; mobile access limited to agency admins. Skills and connectors are per user per company; access tokens minted per call and never exposed to the model.
- Reviews AI: suggest or auto-reply to Google reviews with sentiment-matched tone, star-rating filters, wait time, brand voice; Drip Mode for backlog (older-than threshold, daily cap, frequency, business-hours window, agent and tone; pause/edit/delete); review insights.
- Content AI: in Social Planner, Email Builder, Blogs; text + image generation; Brand Boards/Brand Voice (Marketing -> Branded Content) feed all content products.
- Funnel/Website AI and AI Studio: generate pages and entire interactive apps from conversation; AI Studio supports GitHub two-way sync with secret scanning, native chat widgets landing in Conversations, payments checkout with CRM contact capture.
- Knowledge Base: sources include documents (PDF, DOC, DOCX), rich text articles, CSV/tables (indexed by record), website crawler content with auto refresh of trained links, FAQs; content is extracted, chunked, indexed; Retrieval Tester lets you ask sample questions and see returned chunks before going live; shared across Conversation AI, Voice AI, Managed Agents. No documented size limits.
- MCP: HighLevel exposes an MCP server (tools for CRM), MCP connectors for managed agents, 6-article help category.

### 6.7 AI pain points

- Cost opacity: pay-per-use components (engine + TTS + LLM tokens + phone) vs flat plans vs Labs products; multiple help articles needed for pricing; per-location multiplication ($97 x 10 locations = $970/mo).
- Sprawl and naming churn (Super Agents -> Managed Agents; Agent Studio vs Managed Agents; Conversation AI V1/V2/V3; Voice AI legacy vs new; Eliza as an unrelated older call center platform name).
- Hallucination risk without a good KB (all guides stress it); handoff controls limited; "AI Disclosure" forced on outbound.
- Voice realism/latency; limited customization of voices/cloning; transfer features not testable in web calls.
- Conversation AI cannot yet use MCP or custom actions natively (requests), custom values in Q&A missing, limited summary languages.
- Outbound call limits (10/min, 5,000/day, 14 calls per 14 days) good for compliance but limit use cases.

---

## 7. Notifications and Tasks (cross-cutting)

- User notification preferences at Settings -> My Profile -> Notifications: per-event toggles for new inbound message, assigned conversation, @mentions, internal chat, opportunity changes, appointments, etc., delivered via in-app, email, and mobile push. Internal chat notifications can be "every message" or "only when added". Manage notifications "only for assigned user" is a request (10 votes); desktop pop-up notifications are a 263-vote request; unread count in the nav is a multi-year request.
- Workflow actions "Send Internal Notification" (email/SMS/in-app/push to users) and "Send Inbound SMS notification" patterns are the mainstream way to alert staff.
- Tasks notifications: assignment and due reminders (workflow-based due dates).
- Agency notifications: usage/billing alerts for AI, phone failures, compliance alerts from LC Phone.

---

## 8. LeadConnector mobile app

- Free iOS/Android app (LeadConnector brand; also white-label app at an extra fee, third-party price about $497/mo, unverified). Same login as web. Core: conversations (SMS, email, FB/IG, WhatsApp, GBP), notifications, contacts (add, edit, call), opportunities pipeline with moving deals, calendar and appointments, Point of Sale / invoices (Stripe required), send review requests, team invites, tasks, dialer with call scripts, voicemail, group SMS chat, Conversation AI controls (Edit AI Settings: activate/pause/schedule reactivation per conversation), Ask AI (agency admins only), DND management, manual actions.
- Desktop app also exists.
- Missing/requested: direct SIM card calling integration (418 votes), custom menu links (148), objects/custom objects (99, under review), retain opportunity filters (71, planned), gift card redemption, company functionality (6), filter by contact tag.
- Complaints (third-party reviews, unverified): crashes during active calls, unreliable push notifications.

---

## 9. UI layout summary (for design inspiration)

- Global shell: left vertical nav (module icons, collapsible; agency and sub-account switchers at top), top bar with global search (Ctrl/Cmd+K), Ask AI icon, notifications bell, help (?), profile. Settings gear at bottom-left.
- Most modules follow: list/table view with filter builder and saved "smart" views; detail drawer or page with three panels; right side "action modules".
- Inbox: 4 panels (inbox selector, list, thread, context panel).
- Builders (workflow, funnel, email, agent studio) are separate full-screen canvases with their own visual language; the redesign (HiRise) is not complete across them.
- Settings are fragmented: Business Profile (dedup settings), Phone System, Custom Fields, Custom Values, Tags, Scoring, Labs, Integrations, Objects, Notifications, Audit logs.

---

## 10. Cross-cutting pain points users report (themes)

(Source quality: aggregator and agency blogs, plus HighLevel's own ideas boards; direct Reddit/G2 pages were not fetchable.)

1. Learning curve and clutter: G2-style tags highlight "not intuitive" and learning curve; blogs quote 30-90 days to be productive. Duplicate concepts and legacy/new versions.
2. Performance: complaints of slow loads (a claim of 10-60 second loads was quoted from Reddit by one compilation, unverified); heavy pages like contacts and workflows.
3. Instability from rapid shipping: UI changes without notice, half-finished features, Labs dependence. Changelog is daily (e.g., Oct 12-15, 2026 had WhatsApp template builder, AI Studio Git sync, internal comments in workflows).
4. Support: inconsistent, long waits (claims of 30-minute chats unverified), billing disputes; higher plan customers fare better.
5. Deliverability: email (shared infrastructure, SPF/DKIM/DMARC manual setup, Mailgun verification states, send limits) and SMS (A2P rejections, carrier filtering).
6. Hidden costs: usage-based SMS/phone/AI/WhatsApp/email stacks on the $97-$497 plan; per-location AI fees; rebilling requires top plan.
7. Missing basics: message search, reply-to address, multi-company, helpdesk, opportunity customization, multi-currency, user deactivation, desktop notifications.
8. White-label dependence: mobile app and branding cost extra.
9. Data portability: no real undo for merges and bulk actions (except deletes), snapshots cannot carry some objects (smart lists), exports are CSV only.

---

## 11. Opportunities to do better (concrete product ideas)

### 11.1 CRM core

1. Unified, schema-first data model: one "record" abstraction for contacts, companies, deals, tickets and custom objects, each with the same list view, filters, saved views, associations, notes, tasks, files, activity, permissions and API. HighLevel bolted objects onto a contact-centric core (e.g., opportunities require a contact, multi-company arrived late, tasks, notes and imports are inconsistent across objects). Make everything an object from day one, including many-to-many association labels, with deals allowed to exist without a contact.
2. Real search: global full-text across messages, notes, files, call transcripts, with filters and saved searches (HighLevel's top missing feature). Use a search engine (Postgres FTS, Typesense, or Elasticsearch/OpenSearch) from the start, with permission-aware results.
3. Static and dynamic lists: support both manual (static) lists and rule-based smart lists, with snapshots of membership, list history ("who entered/exited and when"), shareable and exportable via API and in templates.
4. Field system: conditional visibility and requiredness for all objects (contacts, companies, deals), field-level permissions (hide sensitive PII per role), computed/formula fields, field sync/mapping, per-field audit history, currency-aware money fields, validation rules, and global field library with tags. Persist layouts per user in the account, not browser local storage.
5. Tags with governance: tag groups, colors, descriptions, usage counts, merge and rename with preview, optional "tag types" (system vs user), auto-expire tags; clear separation between Contact Type (single) and tags (multi).
6. Duplicate handling as a first-class workflow: continuous duplicate detection with a review queue, fuzzy matching, field-level merge with preview and one-click undo (keep a merge log and allow restoration for 30+ days), uniform behavior across forms, imports, API and integrations (one rule set rather than source-specific behavior).
7. Imports: XLSX and Google Sheets support, in-place column auto-mapping with fuzzy header match, create-missing-fields on the fly, dry run with preview of creates/updates/skips, rollback of an import job, scheduled imports from URLs/Sheets, and import of associations, notes and activities in one file set.
8. Scoring: configurable scoring with decay, fit vs engagement, explainable breakdown per contact, and score history; optional AI-predicted likelihood to convert trained on the account's own won/lost data.
9. Compliance-aware contact record: one consolidated "consent and eligibility" card showing, per channel (SMS, email, voice, WhatsApp), consent source and timestamp, DND state, quiet-hours, number validity, A2P status, and "can I contact right now?" computed at compose time. HighLevel splits this across DND tab, activity cards and settings.
10. Contacts-as-people vs accounts: first-class B2B model (accounts with hierarchy, multiple contacts with roles, buying committees) and B2C model; let tenants pick a template (vertical CRM templates, like HighLevel's custom object templates but stronger with demo data).
11. Audit and data governance: full audit log per record for 1+ year (not 60 days), restore deleted records and bulk jobs broadly (HighLevel restores only contact deletes for 60 days), data export in open formats, GDPR/CCPA subject requests (export/erase) with a few clicks.

### 11.2 Pipelines

12. Opportunity cards that show conversation snippets and next-step, required-field gates per stage (stage-exit criteria), mandatory lost reason with structured categories, per-stage probability and aging alerts, and rotting indicators out of the box.
13. Forecasting as a core, not Labs: weighted pipeline, commit/best case/pipeline categories, snapshots over time (how forecast changed), rep-level quota attainment, and AI risk scoring with explainable reasons, multi-currency.
14. Per-user and per-team saved board layouts stored server-side; multi-pipeline "universe" board with swimlanes; pipeline templates; copy pipelines across workspaces easily.
15. Deals not tied to a single contact; multiple contacts with roles; deal-level scheduling and mutual action plans; line items and quotes tied to the products catalog.

### 11.3 Conversations

16. Treat the inbox as the product's heart: sub-100 ms interactions, optimistic UI, virtualized lists, instant search, keyboard-first (command palette, j/k navigation, snooze, assign with hotkeys), configurable shortcuts (HighLevel shortcuts cannot be customized).
17. Saved views as first-class persistent objects (shared with team) including unread counts per view in the nav and browser tab badge; desktop push notifications; "snooze until" and reminders; follow-up SLAs with breach alerts and routing rules (HighLevel's SLA features reportedly lack basics).
18. Email done right: configurable reply-to, Gmail/Outlook 2-way sync with domain/contact exclusions, per-user signatures, shared mailbox with collision detection ("Alex is typing"), send-as aliases, email threading that matches clients, tracked-links controls, and a proper HTML rendering pipeline. Dedicated deliverability dashboard (domain reputation, DMARC alignment checks, warm-up scheduler, blocklist monitors, bounce taxonomy) with guided DNS setup that verifies records live.
19. Channel abstraction: pluggable channel connectors (SMS, MMS, email, WhatsApp, Messenger, IG, RCS, Telegram, webchat, voice, custom providers via a public SDK) all normalized to one conversation model with delivery receipts, retries, and consistent status. Make idempotent message ordering a guarantee (HighLevel has out-of-order reports).
20. Unified timeline with AI assist everywhere: smart reply suggestions, conversation summaries, intent/sentiment tags, auto-translation per message with original toggle, and "why did the AI say this" provenance with one-click correction (HighLevel's AI Response Info sidebar is a good idea to copy and generalize to all AI actions).
21. Collaboration: threaded internal comments that can be edited, deleted and attached; internal chat integrated; assignment rules (round-robin, load-based, skill-based, time-zone/hours-based), team-level inboxes, escalation paths; private notes with @mentions across all objects.
22. Bulk safety: soft-delete with a trash bin for conversations, bulk-action previews, and undo for tag/message operations.
23. Group messaging that allows adding/removing participants and supports any sender type when carriers allow.

### 11.4 Phone and compliance

24. Compliance as a guided product: an "SMS readiness" wizard that pre-validates website, privacy policy, terms, opt-in form language, consent checkbox pattern and brand data against the known rejection-code catalog before submission (HighLevel lists 60+ codes post-fact). Auto-generate compliant opt-in form blocks and policy pages, store opt-in evidence (screenshot + timestamp + IP) per contact, and run continuous compliance monitoring (quiet hours, frequency caps, content scans for SHAFT terms and shorteners).
25. Single "call routing" canvas: visual IVR/hours/ring-group/AI-agent flow designer in the phone settings (not hidden inside workflows), with simulation ("call this number as caller X at 8 pm") to show exactly where a call ends up, versus HighLevel's three-screen routing spread and long explainer article.
26. True power/parallel dialer with local-presence, AMD, voicemail drop with prerecorded variations, disposition workflows, call recording consent by state, live coaching (listen/whisper/barge), and call scoring via AI.
27. Transparent usage and cost: show per-segment, per-minute cost including carrier fees before sending, a daily budget cap with hard stop, alerts, and an "estimated cost for this campaign" preview. Pass-through pricing with simple flat markup for agencies/resellers.
28. Number lifecycle: number health scoring (spam labels, answer rate), automated rotation/ramp-up, pool management with fewer than 4-number minimum or per-source numbers that route to app users, and call tracking with offline conversion upload to ad platforms (Google Ads, Meta CAPI).
29. Mobile: native cellular dialing option (SIM integration is the top mobile request), robust push notifications, offline drafts, full object support (companies, custom objects), widgets, and call-recording-aware notes.

### 11.5 AI

30. One agent platform, not five: a single "Agent" abstraction (instructions, knowledge, tools/skills, channels, triggers, guardrails, memory, evaluation) that can run as chat, voice, or background automation, with one builder (chat-first generation + visual graph for power users), one test harness, one version/deploy model (draft/stage/prod), and one billing meter. HighLevel's Conversation AI bots, Voice AI agents, Agent Studio flows, Managed Agents, Workflow AI and Ask AI overlap with different capabilities and prices.
31. Transparent AI pricing: one usage unit (e.g., "agent credits") with a live cost estimator, per-conversation cost breakdown in logs, budget caps per agent, and predictable flat tiers; avoid per-location multiplication traps. Show real cost per booked appointment.
32. Evaluation and safety: built-in eval suites (golden conversations, simulated customers, regression tests before publish), guardrail policies (never promise price, escalate on legal terms), PII redaction, human-in-the-loop approval queues for sensitive actions, confidence-based handoff, "max replies then handoff message" (top Conversation AI request), pause bot automatically when a human replies on any channel (including native IG/FB), and per-contact/per-conversation AI state visible at a glance.
33. Knowledge: managed ingestion with source freshness, automatic re-crawl, conflict detection between sources, gap analysis from unanswered questions ("questions the bot could not answer this week, click to add an answer"), versioning, per-agent scoping, and a retrieval tester built into the agent test panel (HighLevel has it as a separate page).
34. Voice: low-latency pipeline (target sub-700 ms turn latency), voice cloning, accent/language per call auto-detect, caller recognition (look up contact by ANI and greet by name), spam/robocall filtering before contact creation, call summaries and recordings emailed/SMSed after call (139 votes), agent-to-agent transfers without phone numbers, optional configurable AI disclosure per jurisdiction, consent checks and DNC/DND enforcement before outbound dial (HighLevel leaves consent to the business), calling-hour guard by local state rules, A/B prompt tests with live metrics.
35. AI-native CRM: auto-enrichment, auto-summarized timelines, next-best-action suggestions on every contact/deal, AI-written follow-ups in Suggestive mode that learn from edits, AI field extraction from calls/emails into custom fields, duplicate detection, meeting notes, and natural-language smart lists and reports ("show leads who asked about pricing and did not book").
36. MCP and open tool standards from day one: first-class MCP server and client, webhooks and custom actions for agents (top requests: MCP in Conversation AI 158 votes, direct webhooks 114, custom actions 60), a skills registry with scoped permissions and audit, and an SDK so partners publish agents and templates (HighLevel has a marketplace for agent templates; make revenue share and versioning/update flows stronger).
37. Ask-AI copilot that can do everything the UI can (HighLevel's Ask AI is read-only for workflows/campaigns, cannot configure IVR or chat widgets, lacks raw logs). Provide confirmation, dry-run previews, and undo for AI-initiated changes.
38. Reviews: unify reputation (Google, Facebook, Yelp, industry sites) in the inbox with AI replies, sentiment alerts, review request automation by outcome, and publishing guidelines to prevent tone problems.

### 11.6 Tasks, notifications, mobile

39. Tasks that matter: first-class tasks across all objects with kanban/calendar/list views, templates (task playbooks per stage), recurring and dependent tasks, SLAs, and integration with helpdesk/ticketing (the 1,000-vote CRM request) via a "ticket" object with queues, macros, SLAs and CSAT, reusing the inbox.
40. Notification center: per-event, per-channel, per-record-scope rules ("only my assigned"), digests, quiet hours, push/desktop/email/SMS, and a unified notification inbox with mark-all-read. Fix the "unread count in nav/tab title" basics.
41. Mobile-first parity: full CRM objects, conversation search, push that actually arrives, offline mode, call via SIM or VoIP, voice-to-note, and AI assistant for agents (summaries before calling).

### 11.7 Platform-level differentiation (agency/reseller model)

42. Make multi-tenancy delightful: snapshots with diff, selective sync and rollback (the top ideas-board item overall is "revert snapshot update" with 492 votes), template marketplace with versioning, sub-account health dashboards (A2P status, deliverability, AI spend, errors), and one-click feature toggles for many sub-accounts.
43. Unified billing: clear wallet, per-feature usage dashboards, rebilling with any markup on any usage line without requiring the top plan, usage alerts, and invoices that itemize carrier fees.
44. Reduce UI clutter: opinionated defaults, progressive disclosure (basic vs advanced mode per user), role-based navigation (hide modules a role cannot use), consistent settings architecture (one searchable settings hub with deep links), and an in-app onboarding checklist that verifies real completion (DNS verified, A2P approved, first pipeline created) instead of static docs.
45. Operational quality as a feature: public status page, performance budgets (p95 page load targets), feature flags that avoid indefinite "Labs" limbo, a visible changelog with "what changed in my account" diffs, and the ability to pin a UI version for a sub-account for a grace period (agencies complain about UI changes breaking their client trainings and workflows).
46. Data portability and trust: one-click full export (contacts, conversations, files, automations, configurations) in open formats, as well as an import path from HighLevel (CSV, API, snapshots mapping) to lower switching cost for agencies. Competing on migration tooling is a cheap way to win customers.

---

## 12. Open questions and verification list (could not be confirmed)

- Exact current SMS/Voice AI per-minute numbers beyond the billing guide (third-party blogs conflict: $0.13/min legacy vs $0.045 engine + TTS + tokens).
- Whether Voice AI "inbound + outbound in the US only" (a November 2025 claim) is still true; the 2026 outbound article says same-country domestic numbers only, which suggests multi-country support exists but is limited.
- Ring-group maximum (6 vs 7 users).
- Power dialer scope (workflow-based manual call tasks versus a continuous auto-dialer; sources conflict).
- Missed Call Text Back menu location (toggle vs workflow only).
- Contact custom field type list completeness (file upload, signature, text-box list exist per other articles but are not in the field-type article).
- Merge undo and "most recent wins" behavior (from a consultancy blog).
- Mobile app crash/push complaints (from review blogs).
- Reddit/G2/Capterra raw review text could not be retrieved (HTTP 403); consider a second pass using a browser session or an archive service to quantify top complaint categories.
- Opportunity forecasting formulas and risk thresholds are not documented publicly.
- Contact-level API schema (full field list and dndSettings structure) needs direct review of the marketplace.gohighlevel.com / highlevel.stoplight.io API reference in a browser, because the pages render dynamically and only partial fields were retrievable.

## 13. Source index (selected)

Official help center (help.gohighlevel.com/support/solutions/articles/...): 155000006651 (contact detail page), 155000004432 and 155000003905 (imports), 48001167703 (bulk actions), 155000006472 (drip mode), 155000007530 (smart list advanced filters), 48001062094 (smart lists), 155000006504 (revamped list view and SmartLists 2.0), 155000001302 (contact types), 155000001362 (followers), 155000001251 (engagement score), 155000003918 (contact associations), 155000004033 and 155000005346 (associations and limits), 155000003897 (custom objects), 155000008031 (custom fields), 155000006643 (tasks across objects), 48001181714 (duplicate preferences), 48001214849 (DND), 155000001982, 155000001983, 155000002000, 155000003910, 155000002432, 155000002270, 155000005536, 155000007688, 155000008427, 155000006523 (pipelines and opportunities), 155000006610, 48001222121, 155000003707, 155000001320, 155000004686, 155000003877, 155000003973, 155000004603, 155000004183 (conversations), 48001223546, 48001223556, 48001229976, 155000007498, 48000981393, 48000981433, 48000981430, 48001153968, 155000004935, 155000007237, 155000007572 (phone and compliance), 155000001428 (WhatsApp billing), 155000002166, 155000008362, 155000004401, 155000005382, 155000002669, 155000004107, 155000006598, 155000008604, 155000006648, 155000008315, 155000006058, 155000007931, 155000007393, 155000005327, 155000007758, 155000005555 (AI), 48001236572 (Eliza).
Other: ideas.gohighlevel.com boards (conversations, crm, contacts, opportunities, conversation-ai, voice-ai, mobile-app, changelog), gohighlevel.com blog (power dialer, mobile app), netpartners.marketing and botpenguin.com (AI pricing blogs), ghlexperts.com, growthable.io, consultevo.com, supplygem.com and other agency blogs (setup practices, reviews).
