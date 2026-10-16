# 03 - Commerce, Calendars, Memberships and Automation (HighLevel / GoHighLevel research)

Research date: October 2026. Scope: Calendars, Payments, E-commerce stores, Memberships (courses and Communities), Workflow automation builder, and the add-on surface (GoKollab, Marketplace apps, WordPress, Ad Manager, Prospecting, Events, Rentals, Certificates).

## 0. How to read this document

### 0.1 Source quality and confidence tags

Sources used, in order of trust:

1. HighLevel's own help portal (help.gohighlevel.com support solutions) and the ideas.gohighlevel.com changelog. Treated as authoritative. Marked **[official]**.
2. Third-party agency guides (Growthable, ConsultEvo, HL Growth Partner, GHL Experts, NetPartners, OneExpand, SupplyGem, The Stack Insiders, RSLA). Useful but often affiliate-driven and sometimes stale or contradictory. Marked **[3rd-party]**.
3. White-label help mirrors (mastermind.helpscoutdocs.com, agencysupport.ladesk.com, mycrmsupport.helpjuice.com and similar). These are agencies republishing HighLevel's docs. Treated as 3rd-party copies of official content.
4. Review aggregators (G2 blocked automated fetching with HTTP 403, so G2 and Capterra review text was NOT read directly; reddit r/gohighlevel was not reachable through search either). Pain points below therefore come from review-style blog posts, the HighLevel feature-request board, and an API report card. I flag this as a research gap in section 10.
5. Anything labelled **[inferred]** is my own reasoning about what the data model or UI must look like, based on the visible behavior. It is not documented fact.

Where two sources disagree I say so rather than pick one silently. The product moves fast (weekly release roundups), so any number or limit here may already have shifted.

### 0.2 What HighLevel is, in one paragraph

HighLevel is an agency-oriented all-in-one CRM and marketing platform. The unit of tenancy is the **sub-account** (also called a "location"), grouped under an **agency**. Everything in this document lives inside a sub-account (contacts, calendars, payments, stores, courses, workflows). Agencies resell the platform white-labeled ("SaaS Mode") and re-bill usage (SMS, email, AI, premium workflow executions). Published base plans are $97 (Starter), $297 (Unlimited) and $497 (Agency Pro) per month, with usage billed on top. Nearly every feature below is designed so that an agency can build it once, snapshot it, and push it to many client sub-accounts. That multi-tenant, snapshot-centric design is the single most important architectural fact for anyone building a competitor.

### 0.3 Cross-module spine (applies to everything below)

- **Contact** is the central entity. Appointments, orders, invoices, subscriptions, course enrollments, community memberships and workflow enrollments all hang off a contact id.
- **Custom values / merge fields** (for example `{{contact.first_name}}`, `{{appointment.start_time}}`, `{{appointment.meeting_location}}`) are the glue between modules and messaging.
- **Tags, pipelines/opportunities, custom fields** are the segmentation primitives that workflows branch on.
- **Workflows** are the integration bus. Almost every module emits triggers (appointment booked, payment received, lesson completed) and exposes actions (update appointment status, send invoice, grant course offer).
- **Snapshots** copy configuration (calendars, workflows, forms, stores, courses) between sub-accounts. Some things do not copy (products in stores, community groups, per The Stack Insiders / SearchSherpa notes), which is a recurring pain point.

---

## 1. Calendars (scheduling)

### 1.1 Feature overview

Scheduling is a first-class module that also doubles as a funnel step (booking widget embedded in sites, funnels, forms, surveys and chat). It is far broader than a Calendly clone because bookings become CRM objects that fire workflows, collect payment, and drive pipeline movement.

#### Calendar types (as of 2026)

| Type | Model | Key rules |
|---|---|---|
| Personal / Simple (one-on-one) | One host, one attendee per slot | Uses the host's availability and connected external calendar |
| Round Robin | A pool of team members, one is assigned per booking | Two distribution modes (below), per-member priority, optional staff selection by booker |
| Collective | Multiple hosts attend one meeting | Slots shown only when every selected member is free; first member added is the primary owner and cannot be removed; at least two members |
| Class Booking | One host, many attendees in the same slot | Seats per class, recurring availability plus date overrides, each date has its own capacity, no "Add guests", one host per class calendar |
| Service Calendar (Services v2, grouped under a Service Menu v1) | Appointment tied to a named service, duration, assigned staff, optional rooms and equipment | Belongs to a Group; services listed on a customer-facing Service Menu; supports multi-service booking in one visit |
| Rentals | Duration-based, inventory-driven multi-day bookings | GA mid-2026; separate section 1.7 |
| Event calendar | Listed in some third-party guides | Static meeting links only (no dynamic Zoom), otherwise barely documented. Could not confirm as a distinct current type from official docs |

Conflict note: third-party guides disagree on how Collective works. The better-sourced description (all hosts attend, combined availability) matches the Growthable and LadeSk write-ups. One ConsultEvo page describes "assign to one available user," which is round robin behavior.

#### Round robin distribution **[official]**

- **Optimize for Availability**: booking goes to a member who is free at that slot. If several are free, the higher priority member wins (High, then Medium, then Low). Good for support and urgent services.
- **Optimize for Equal Distribution**: balances counts across the team over a rolling one-month period. The member with the fewest appointments that month is picked; ties break by the team list order; no member can be more than 3 appointments ahead of another (a member who gets 3 ahead is temporarily hidden from the pool until others catch up). Only applies when the booker chooses "Any available"; if the booker picks a specific person, distribution is bypassed. The docs advise turning off "Allow Staff Selection" to get true equal distribution.
- Counts reset when you add or remove a member or flip between the two modes.
- Priority is three discrete levels, not numeric weights.
- Setting to keep the same assigned user when a booking is rescheduled exists. Contact-owner interactions are documented in separate articles I did not retrieve.

#### Calendar groups and Service Menus

- Calendars can be organized into **Groups** (a group has a name, description, URL slug and a template, Classic or Neo). A group gives one public URL listing several calendars.
- A **Service Menu** needs groups first, then service calendars assigned to groups, then the menu is configured. All services in one menu must use the same currency. The menu offers options for adding guests, selecting multiple services, and letting the customer choose staff.
- Staff must exist before a service can be saved because availability is derived from assigned staff (Settings, My Staff, with days and hours).

### 1.2 Settings and sub-features (per calendar)

Settings are organised into collapsible panels. For a class calendar the official panel list is Meeting Details, Availability and Booking Rules, Forms and Payment, Notifications and Additional Options, and Customizations. Other calendar types use the same structure.

**Meeting details**: calendar logo (PNG, JPEG or GIF), internal name, description shown on the booking page, group, custom URL slug, appointment title template (supports merge fields in double braces), event color on the staff calendar, optional custom domain for booking links.

**Team members**: for group calendars, each member has a linked user, a priority (availability mode) and a location. Equal distribution mode drops priority and uses list order.

**Availability and booking rules**:
- Slot duration, slot interval (how often start times are offered), pre and post buffer (a "buffer duration" gap), appointments per slot (capacity for a given user), appointments per day, minimum scheduling notice, date range (how far ahead can be booked), weekly office hours with multiple ranges per day, an "Apply all" copy action, date-specific overrides, and "Block off time".
- August 2026 added up to three selectable meeting lengths on one booking page.
- A "Look Busy" control hides some open slots so the calendar appears in demand (listed in the Growthable article index; behavior not fully documented in what I read).
- Time zone note from docs: if the user and the company are in different zones, set availability in the user's zone.
- Recurring availability (class calendars) and Recurring Meeting (see 1.4).

**Meeting location**: Zoom (native integration), Google Meet (auto-generated when Google Calendar sync is on), Microsoft Teams (weakest: users have asked for native link generation; older feedback says only the text "Microsoft Teams meeting" appears, no join link), phone, in-person address, custom link. Multiple meeting locations on one calendar exist. Dynamic per-booking Zoom links work only for Round Robin and Collective; Event and Class calendars use a static link. One Zoom connection per user per sub-account.

**Forms and payment**:
- Default form collects first name, last name, email and phone; it can be replaced by a custom form. "Sticky contact" prefills returning contacts. Consent checkbox for SMS and email. Widget field order is configurable.
- Payments at booking: collect full amount, deposit or card on file. Stripe is the baseline; PayPal works on all calendar types and new Services v2 but not the legacy v1 Service Menu; Authorize.net, NMI and Square card payments are supported per the provider matrix (NMI and Square are not supported on the Service Menu). Coupons work on calendars and services. Each class booking shows payment status in the Appointments dashboard. Payment for recurring appointments exists. Staff-booked appointments historically could not collect payment (a feature request is open); July 2026 added the ability to fully edit paid Services bookings (recalculated totals, payment status, refunds). September 2026 allows a custom price on a services appointment without changing the service's rate.

**Notifications and confirmation**:
- Auto-confirm toggle, alert emails to the assigned member, Google Calendar invitation emails, allow rescheduling, allow cancellation, "additional notes" with reschedule/cancel link, Meta pixel id.
- Booking, confirmation, reschedule and cancellation alerts by email, SMS, WhatsApp or in-app. Reminders and follow-ups are configured per calendar and can also be built as workflows.
- Cancellation and reschedule **policy**: a window (hours before the meeting) after which the self-service links stop working; blank means links never expire.
- Post-booking: thank-you message or redirect URL.
- Status labels are configurable per calendar.

**Calendar sync**: Google, Outlook (Microsoft 365), iCloud, plus Calendly import and Cal.com sync (May 2026). Per-user connection with a "linked calendar" for writing bookings and one or more external calendars that block availability. One-way vs two-way sync options are documented. Reserve with Google and Google Booking Redirect exist.

**Customizations**: widget style (Neo or Classic), primary color, background, button style, cover image, calendar colors, custom CSS in embed contexts.

### 1.3 Booking widget and embedding

- Embedded on funnels, websites, forms, surveys, chat widget, or shared as a direct link on a custom domain.
- Neo widget is the modern layout; Classic the legacy one. Group views also have a Neo template.
- Class calendars can show remaining seats per slot on the widget.
- Client Portal (Aug 2026): clients can book, reschedule and cancel from their portal.
- Round robin can optionally let the booker pick a specific staff member.

### 1.4 Recurring appointments **[official]**

- Two modes. **Calendar-configured**: only valid with a single assigned member and no date-specific hours; daily, weekly, monthly or custom repeat; max 24 recurrences; three options for blocked slots (Skip, Continue booking as confirmed or unconfirmed, Book next available, which gives up after 3 consecutive unavailable slots).
- **Custom recurrence** (in-app appointment modal only): bypasses availability entirely; patterns like "second Tuesday monthly"; ends never, on a date, or after N occurrences; not supported on class or service calendars.
- Series model: all occurrences link to one parent appointment; edit/delete one, this and following, or all.
- Known limits: in list view, contacts tab and conversations tab only the first custom occurrence shows; workflows trigger only for the first custom occurrence; one Zoom/Meet/Teams link per whole series; Outlook edits do not sync back; cancelling via link or contact tab cancels the entire series; "this and following" cancel sends no notification.
- October 2026: one confirmation email for the whole series, per-occurrence reminders.

### 1.5 Appointment statuses and automation

- Core statuses: New/Booked, Confirmed, Showed, No-Show, Cancelled, plus Rescheduled and (per some sources) Invalid. Staff must update status after the meeting, otherwise status-triggered workflows and reporting break.
- Workflow triggers: **Customer Booked Appointment**, **Appointment Status**, **Service Booking**, **Rental Booking**. Action: **Update Appointment Status**, **Generate One Time Booking Link**. Goal Event type "Appointment Status". Conversation AI and Voice AI can book into calendars in real time (Voice AI availability check added February 2026; Conversation AI supports multiple calendars).
- Reminder cadence commonly built by agencies: confirmation on booking, 24 hour, 2 hour, optional 15 minute, using "before appointment" waits rather than fixed delays; rebooking SMS within 10 minutes of a no-show.
- Calendar AI (Aug and Sep 2026): a setup assistant that picks calendar type, team, availability and location and offers a test booking; a "why can't this slot be booked" explainer.
- Appointment views: calendar view (day, week, month, filterable by user/calendar), Appointment List view (with payment info and quick actions), per-contact appointment tab, mobile app including service calendars. Rentals have their own calendar view.

### 1.6 Rooms and equipment (resources)

- Service calendars have a "Rooms and Equipment" step. **Rooms** are created resources linked to the service to prevent double booking (examples: detail bay, treatment room). **Equipment** is linked with an available quantity (polishers, extractors, devices). The service is bookable only when staff AND room AND equipment are free.
- Entities (inferred): Resource {id, type: room|equipment, name, quantity, location}, ServiceResourceLink {service_id, resource_id, qty_needed}.

### 1.7 Rentals (new in 2026)

Announced 24 June 2026 after a private beta; open to all accounts by 30 June per a secondary roundup.
- Listings with image, name, description, price, availability, categories, status.
- Inventory: quantity tracking and variants.
- Pricing rules by season, day of week, hour of day, duration and quantity; automatic discounts for long or bulk rentals; security deposits; per-booking invoice generated on confirmation (the docs warn rental invoices are not auto-sent when a booking is created).
- Duration controls from hours to months; lead time, buffer (turnover) time, booking window; business hours in global settings; external calendar sync (import blocks, export availability).
- Multi-item bookings and a multi-item checkout; tax articles exist.
- Public booking page showing listings in real time; calendar view with overlaps and blocked slots; appointments list view with per-listing rows.
- Notifications over email, SMS and WhatsApp for unconfirmed, booked, canceled, rescheduled, reminder and follow-up events (July 2026).
- Gaps in the docs I read: add-ons, listing status values, deposit rules, plan limits.

### 1.8 Key data entities and fields (documented or inferred)

- **Calendar**: id, type, name, slug, description, group_id, team members[{user_id, priority, location}], slot_duration(s), slot_interval, buffer_pre, buffer_post, max_per_slot, max_per_day, min_notice, date_range, hours[weekday -> ranges], overrides[date -> ranges], recurring settings, seats (class), form_id, payment{amount, currency, type: full|deposit}, notifications config, widget style/colors, sync settings, status labels, cancellation policy hours.
- **Appointment**: id, calendar_id, contact_id, assigned_user_id, start, end, timezone, status, source (widget, manual, API, AI), meeting location/link, notes, payment status/order ref, recurrence parent, guests (not for class), service ids and add-ons (services).
- **Group**, **Service**, **Service Menu**, **Resource (room/equipment)**, **Rental listing / variant / pricing rule / rental booking**, **User availability** (per-user hours, connected external calendars, Zoom connection).
- Merge fields available in templates: `{{appointment.start_time}}`, `{{appointment.meeting_location}}`, calendar name, reschedule and cancel links.

### 1.9 UI layout

- Settings, Calendars: tabs for Meetings (calendar list and groups), Service Calendars (v1 menu), Rentals, Calendar Settings/Preferences (account-level toggles such as enabling the Service Menu). "+ New Calendar" opens a short wizard (type, name, host, slug, duration, seats, location, accept payments) and then "Advanced Settings" opens the panel list above.
- Staff-facing calendar page: left filter rail (users, calendars, groups), main grid (day/week/month), "+ New appointment" modal with contact search, calendar, user, Default vs Custom date and time tab.

### 1.10 Pain points users report

1. **Sync reliability**: Outlook is the worst offender (recurring events fail to sync, token expiry after password changes, busy-status events not blocking, two sub-accounts reading the same Outlook calendar show different blocks). Google sync gaps cause "phantom availability" and double bookings. Each team member must connect their own calendar for round robin to route correctly.
2. **Integration gaps**: Zapier / LeadConnector app lacked a "new calendar booking" trigger (2024 report); Teams links are weak; Zoom limited to one connection and static links on some types.
3. **Round robin surprises**: default availability mode overloads the most available person; equal distribution only applies to "any available" and needs staff selection disabled; counts reset when the team changes.
4. **Recurring appointment limits** (24 occurrences, first-occurrence-only visibility, workflows fire once per series, no indefinite series). Users keep requesting unlimited recurrences and series-level cancel.
5. **Status hygiene**: if reps do not mark showed / no-show, automations and reports silently fail. No auto-status from the meeting actually happening.
6. **Reminders fail silently** when sender registration (A2P 10DLC for US SMS, sender domain for email) is incomplete.
7. **Payments**: cannot collect payment on manually booked appointments (request open as of the sources); PayPal and several providers not supported on legacy Service Menu; coupons incompatible with estimates and invoices.
8. **UI feel**: booking widget described as dated; some timezone quirks; service menu v1 and services v2 coexist, which is confusing.
9. **Round-robin plus contact owner interplay** is covered only in scattered articles.
10. Agencies report no-show rates of 25-35 percent on cold traffic without the full reminder playbook (author's own numbers, unverified).

---

## 2. Payments

### 2.1 Feature map

Payments is a suite of sub-modules under a left-nav "Payments" section. Official tutorials list roughly 45 articles. Sub-features:

- **Integrations (payment providers)**
- **Products and Prices** (including coupons and tax)
- **Invoices and Estimates** (including recurring invoices, templates, payment schedules, late fees, tips, auto-pay)
- **Documents and Contracts** (proposals, e-signature, product lists with payment)
- **Order Forms** and **Payment Links**
- **Text2Pay** (payment request via SMS from Conversations)
- **Subscriptions**
- **Orders**, **Transactions**, **Refunds**
- **Taxes** (tax settings, Tax Zones, Stripe Tax)
- **Tap to Pay / POS**, card readers
- **Coupons**
- **Sales receipts**
- SaaS mode billing (agency level; out of scope here)

### 2.2 Providers and what works where **[official matrix, condensed]**

Providers supported in 2026: Stripe (primary), PayPal, Square, NMI, Authorize.net, Razorpay (India), Adyen and Mercado Pago (appear in newer notes, mostly AI Studio hosted checkout), Manual payment methods, and "3rd party integrations".

Matrix highlights (product areas: order forms, form payments, survey payments, email direct checkout, ecom store, invoices, recurring invoices, payment links, courses, communities, contact-page charge, SaaS mode, calendar/services, service menu, POS):

- **Stripe cards**: supported everywhere including POS.
- **Stripe Apple Pay / Google Pay**: everywhere except contact-page charge and Service Menu.
- **Stripe BNPL (Affirm, Klarna, Afterpay)**: one-time only, not recurring invoices, courses, calendars.
- **Stripe ACH direct debit**: invoices and recurring invoices only.
- **Stripe SEPA, iDEAL/Bancontact, Link, Amazon Pay, Revolut Pay**: broad but not calendars (SEPA/Link) or contact-page charge.
- **Stripe card readers (M2, BBPOS Wisepad 3)** and Square card reader: POS only.
- **PayPal**: order forms, form payments, email checkout, ecom, invoices, recurring invoices, payment links, courses, communities; NOT survey payments, SaaS mode, calendars (legacy), POS. (A newer help article adds PayPal for calendars and Services v2.)
- **Authorize.net**: all areas; USD and CAD only (3rd-party claim).
- **NMI**: broad; no Service Menu support; no subscriptions in one doc version though a later matrix shows recurring invoices as supported.
- **Square**: broad, not Service Menu.
- **Razorpay**: no contact charge, SaaS mode, service menu, POS; cannot be active at the same time as PayPal (per one source).
- Each sub-account connects ONE Stripe account at a time. Stripe is the only way to use SaaS-mode billing, rebilling, and several wallet features.
- Fees: HighLevel states no platform transaction fee on payments in the platform; processor fees apply (Stripe about 2.9 percent plus 30 cents US, PayPal about 3.49 percent plus 49 cents, Authorize.net $25 monthly plus per transaction, Razorpay 2 percent plus 18 percent GST). Stripe Billing adds about 0.7 percent on recurring charges per one 3rd-party comparison. [3rd-party fee table, may be stale.]
- Conflicting claims in old blog posts ("Stripe only", "refunds must be done in Stripe") are outdated; the official tutorial list shows in-CRM full and partial refunds and several providers.

### 2.3 Products and prices

- Created under Payments, Products. A product has name, description, images, type (physical or digital; digital shows a download button only if a file is uploaded to the product or variant), one or more **prices**, optional **variants** (options such as size and color, each with own price, compare-at price, SKU, weight, dimensions, image and inventory).
- Price types: one-time or recurring (billing interval and count, setup fee supported per coupon doc), plus payment plans / installments. Currency is fixed per product and cannot be changed after creation. Price is a separate object from product in the API (create product with price via public API).
- Bulk import by CSV. Recurring products can be added to documents and contracts. Editable quantities in payment links.
- Inventory tracking is a per-variant setting with available quantity ("Continue selling when out of stock" toggle). Inventory page at Payments, Products, Inventory with SKU search.
- Collections (store grouping) and product reviews (storefront review collection with approval, and a "Product Review Submitted" workflow trigger).
- Product catalog is shared across funnels, order forms, stores, invoices, calendars, courses and communities.

### 2.4 Coupons **[official]**

- Fields: internal name, code (alphanumeric, unique, case-insensitive, auto-generate button), discount type (percentage or fixed), currency (locked to sub-account currency), optional start and end datetime, applies to whole cart or specific products/prices/variants, usage limits (total redemptions, one per customer), recurring behavior ("apply to future payments": forever or N months), applies to setup fees, per-builder visibility toggle.
- Works on funnels, stores, websites, payment links, calendars, services and subscription creation. NOT on estimates and invoices, NOT on one-click upsells. Can reduce total to zero (card requirement depends on builder). 100 percent discounts work with most providers except PayPal; PayPal subscriptions have several unsupported coupon configurations (multi-month duration, zero-total).
- Workflow triggers for coupon lifecycle (applied, redeemed, limit reached, expired).

### 2.5 Invoices and estimates

- Create from Payments, Invoices and Estimates, "+ New", or from a contact record. Fields: business details, customer (must be a contact), line items from catalog, discount, tax, notes/terms, due date, **late fees**, **tips**, **payment schedule** (installments), reminders, payment methods accepted (card, ACH, wallets), currency.
- Revamped invoice UI (opt in via Labs): split panel editor with live preview, inline product add by typing, recurring detected automatically when you add a recurring product. Sept 2026 added an AI invoice layout builder with visual editing and restore points.
- **Recurring invoices**: name, description, start date, frequency (weekly, monthly, quarterly, yearly), end date or occurrence count, how many days before due to send, optional **auto-pay** once the customer saves a card; editable after creation; templates can be sent from workflows; Send Invoice action in workflows.
- **Estimates**: send, accept, convert to invoice; multiple recipients; since May 2025 estimates support deposit and installment payment schedules that become an automatic invoice after acceptance (percentage or fixed schedule; first payment at acceptance or a custom date).
- **Invoice statuses** commonly seen: Draft, Sent, Viewed, Partially Paid, Paid, Overdue, Void (names partly inferred; official status list not retrieved). Workflow triggers on invoice events and a Goal Event type "Invoice Paid" (paid or partially paid) exist. A "Wait until invoice paid" request was resolved by using the Goal Event (March 2026).
- Sales receipts for order forms, calendars and invoice payments. Email and SMS invoice notifications and automated reminders. Apple Pay and Google Pay on invoices and Text2Pay.

### 2.6 Text2Pay

- From the Conversations composer or a contact record, a dollar-sign icon opens a "Request Payment" modal: add products or custom amounts, tax, discounts; HighLevel inserts a hosted payment link in the SMS draft. Customer pays via card or wallet, sees a receipt. Needs a connected gateway (Stripe, plus NMI and Authorize.net are listed for text-to-pay in one source).
- Apple Pay domain registration is automatic once Stripe connects.

### 2.7 Order forms, payment links and checkout

- **Order form element** (inside funnel or website pages) with product selector, one-time or recurring products, quantity, coupon field, shipping when physical, tax, test mode, **order bumps** (checkbox add-on on the same page) and **one-click upsells/downsells** on following pages (constraints from 3rd-party notes: V2 funnels, native form elements to pass the payment token, same domain, one upsell product per step, quantity one).
- **Payment links**: shareable hosted checkout; editable quantity; BNPL; direct-checkout links in emails.
- **Form and Survey payments**: unified payment configuration with price levels and variant selection (July 2026), $0 checkout for product forms.
- Store checkout does not have bumps/upsells per agencies; those live on funnel order forms.
- AI Studio apps get a hosted checkout with PayPal Express, coupons, subscriptions and upsells across Stripe, Square, Authorize.net, NMI, Adyen, Mercado Pago (Oct 2026).

### 2.8 Subscriptions

- A **Subscriptions** page lists active/paused/unpaid/cancelled subscriptions. Pause and resume (Stripe, Q1 2026 along with proration and dunning automation via workflows).
- Failed-payment retry settings (Payments, Settings, Subscription): attempts up to 3 (default 3), gap of 1, 3, 5 or 7 days (default 1), checkbox to mark the subscription Cancelled after the last failure otherwise it stays Unpaid; changes apply to existing subscriptions mid-retry. Documented for NMI, Authorize.net and Square (Stripe uses Stripe's own smart retries).
- Sept 2026: manual retry of failed payments, with a saved or new payment method, on NMI, Authorize.net, Square and Mercado Pago once automatic retries are exhausted.
- Workflow triggers: Subscription, Payment Failed, Refund. 

### 2.9 Orders, transactions, refunds

- **Orders** tab (export supported, shows items, tax collected, fulfillment for stores), **Transactions** tab (payment-level, per provider), **Payments** tab setup. Refunds: full and partial from the CRM. Manual payments (cash, cheque) can be recorded. Partial payments on invoices recorded manually. Cards on file per contact (add, view, delete).
- Raw transaction fields (inferred from API/behavior): amount, currency, provider, provider_txn_id, status, source (invoice, order form, subscription, calendar, course), contact_id, product lines, tax, fees, refund records, receipt.

### 2.10 Tax

- Settings, Taxes: named tax rates attached to products (inclusive or exclusive). Automatic tax by location via Stripe Tax (2026) with modes Automatic (Stripe determines) and Manual (merchant handles), registered jurisdictions synced from Stripe with status Active/Pending/Scheduled/Expired; HighLevel disclaims accuracy. Sept 2026 "Tax Zones" group regions with up to 10 manual rates each. Automatic tax available on invoices, payment links and fast payment links. HighLevel is not merchant of record; filing is the seller's job.

### 2.11 Documents and Contracts

- Under Payments, Documents and Contracts: tabs for All Documents (Drafts, Waiting for Others, Completed, Payments), Templates, and settings.
- **Template editor**: rich text, images/logo, custom values/merge fields, product list pulled from catalog (can show/hide images, include recurring products), signature, date, name, text, checkbox and other fillable fields assignable "to be signed by" the sender, a named staff member, or the recipient. Multiple-recipient support (several signers in one doc). Editing a template does not alter documents already sent.
- **Proposals/estimates** are document templates with product lists and optional payment collection at signing (Stripe or other provider).
- **Sending**: manually, from a contact, or with the workflow action **Send Documents and Contracts** (fields: from user, template, send directly vs create as draft, channel email/SMS/both; contact needs an email even for SMS delivery; "Assign sender fields to" chooses the From user or the template owner). Draft mode lets you review before sending; directly sent docs are locked.
- Signing happens in a browser without login on desktop or mobile. Statuses: Draft, Sent, Viewed, Signed/Completed, Declined, Expired/Cancelled. Goal Event can wait on Viewed, Signed, Declined, Completed. Workflow trigger **Documents and Contracts**.
- Not clearly documented (gap): expiry rules, signing order, audit trail/certificate, reminder automation (agencies build reminders in workflows).

### 2.12 Data entities (inferred plus API-visible)

Product, Price, Variant, Coupon, Invoice (with schedule, late fee, tip, recurrence rule), Estimate, Document/Contract (template, recipients, fields, signatures), Order, Order Item, Transaction, Subscription (status, retry state, next billing), Payment Method on file, Tax Rate/Tax Zone, Refund, Receipt, Provider Connection (Stripe account id, mode live/test), Payment Link.

### 2.13 UI layout

Left rail "Payments": Invoices and Estimates, Documents and Contracts, Orders, Subscriptions, Transactions, Payment Links, Products (with Inventory, Collections, Reviews), Coupons, Integrations, Settings (Taxes, Subscription retries, Shipping and Delivery for stores, Receipts, Notifications). Contacts details page has "Payments" panel for charging a card or sending Text2Pay.

### 2.14 Pain points

- **Provider fragmentation**: the support matrix is huge and full of holes (ACH only on invoices, BNPL one-time only, PayPal limits, NMI not on service menu). Users need the matrix to know what will work.
- **Coupons not usable on invoices/estimates**; PayPal coupon edge cases; coupons not on one-click upsells.
- **Stripe re-authorization drops** reported by reviewers; one Stripe account per sub-account.
- **Usage billing surprises** (rebilling premium workflow actions, SMS, email). Agencies must also pay Stripe Billing's recurring surcharge for SaaS.
- **No merchant of record**: tax handling and filings remain on the seller; automatic tax is Stripe-only.
- **Feature requests on the board**: automated partial payments (deposit percent on invoices plus trigger), collecting payment on manually booked appointments, wait steps keyed to invoice status (now via Goal Event).
- **Rental invoices are not auto-sent**, a classic "surprise" gap.
- **Inconsistent UI generations**: old invoice UI vs revamped (Labs), Service Menu v1 vs Services v2.
- **Documents**: thin e-signature feature set compared to PandaDoc/DocuSign (no documented signing order or audit trail); expiry not clearly exposed.
- **Refund and dispute handling** is split between HighLevel and the provider dashboard.

---

## 3. E-commerce stores

### 3.1 What exists

- **Store builder** under Sites, Stores: create a store from one of about seven templates, or add store pages (product list, product detail, cart, checkout, thank-you) to any HighLevel website. Unlimited stores per sub-account. Store analytics (sales, top products, conversion).
- **Catalog** is shared with Payments, Products: physical and digital products, variants, collections, product images, reviews and ratings (approval before publishing), SKU, weight, dimensions, display currency.
- **Inventory** per variant, with oversell toggle. No multi-location inventory, no centralized locations, no low-stock alerting documented.
- **Shipping and delivery** (Payments, Settings, Shipping and Delivery): **zones** (country, state/province, optionally postcode lists) each holding **rates**: flat, free over threshold, or conditional on cart total or on product weight. No zone means checkout is blocked for that region. Shipping rates only in the default currency (older review). Manual fulfillment: orders are fulfilled outside HighLevel and tracking numbers entered manually; a shipment/fulfillment status exists on the order (workflow trigger Order Fulfilled).
- **Taxes**: named rates and Stripe Tax automation.
- **Discounts**: coupons (section 2.4).
- **Payments**: Stripe, PayPal, Authorize.net, NMI, Square; manual payment methods; Apple/Google Pay.
- **Abandoned cart / checkout recovery**: workflow trigger **Abandoned Checkout** (timing configured in Payments), plus a built-in default recovery email that cannot be previewed, and a cart element in the email builder with optional coupons. Agencies run 3-touch sequences over 48 hours and claim an 8-15 percent recovery (anecdotal).
- **Product Review Submitted** trigger, **Order Placed**, **Order Fulfilled** triggers (Shopify specific ones are being deprecated in favor of generic ones).
- **Google Merchant Center sync** (Aug 2026): store products to Google Shopping. **Meta Pixel** InitiateCheckout/AddPaymentInfo events (Oct 2026).
- Snapshots carry store templates, automations and coupons but not product catalogs.

### 3.2 Shopify and WooCommerce

- **Shopify integration** (Settings, Integrations, Shopify): imports and keeps syncing products, collections, contacts, orders and transactions; one-click OAuth connection since late May 2026 (earlier custom-app access-token method still works for existing connections). Disconnect and reconnect to re-import missed data. Notes from guides: taxes are not mapped when syncing products; one transaction per order; Shopify-specific triggers (Order Placed, Order Fulfilled, Abandoned Cart) exist, with two marked as deprecating. A "migrate Shopify store to HighLevel" import path exists (products, collections, orders, contacts, transactions).
- **WooCommerce**: no official HighLevel sync found. Options are the LeadConnector WordPress plugin (contacts, forms, Gravity Forms, WooCommerce hooks per the plugin tag description), third-party "GHL Connect" plugins, WP Fusion, Pabbly and Zapier. Treat WooCommerce as "partner/community integration" not a native module.

### 3.3 Entities (inferred)

Store, Store Theme/Template, Collection, Product, Variant, Inventory Item, Shipping Zone, Shipping Rate (rule type, min/max, weight bands), Cart, Checkout Session, Order, Order Line, Fulfillment (carrier, tracking), Review.

### 3.4 Pain points

1. Not a Shopify replacement: suited to a few hundred SKUs; weak for thousands, multi-warehouse, POS and 3PL, app marketplace.
2. No native fulfillment or carrier integrations (labels, tracking auto-sync); manual tracking number entry.
3. No dropshipping, print-on-demand integrations.
4. Inventory is basic: no locations, no bundles, limited reporting.
5. Collections require adding products one by one; all products appear in every store (older review).
6. Shipping rates locked to the default currency; fewer rate types than Shopify.
7. Upsells/bumps not available on store checkout.
8. Default abandoned-cart email cannot be previewed.
9. Reviewers say serious e-commerce users still pair Shopify with Klaviyo; HighLevel's email builder is plainer.
10. Shopify sync gaps (tax mapping, single transaction per order).
11. Source caveat: SupplyGem's review is older and says digital products are unsupported; current docs show digital delivery on products and variants.

---

## 4. Memberships (courses, offers, Communities, GoKollab, mobile apps)

### 4.1 Course platform ("Memberships" module, formerly Memberships/Courses)

**Structure**: Product (a whole course or membership area) -> Categories (modules; subcategories exist in recent versions) -> Lessons/Posts. Each product has its own branded portal. Lessons can contain video (hosted by HighLevel with captions/subtitles added 2025, or embedded), audio, rich text, files/PDFs, custom HTML embeds (forms, quizzes), thumbnails.

**Offers**: access and pricing wrapper separate from the product. One product can sit in many offers; offers can bundle products. Models: free, one-time, subscription, payment plan / fixed installments, trial then paid. Offer-level coupons (percentage or fixed, expiry, caps). Access expiry was a long-running request (workflow grant, wait, revoke is the common workaround); the board shows it complete but the shipped shape is unclear. Workflow actions: **Course Grant Offer**, **Course Revoke Offer**; triggers include Offer Access Granted/Removed, Product Access Granted/Removed, Product/Category/Lesson Started/Completed, New Signup, User Login (and an April 2026 access expiry trigger per a secondary roundup).

**Drip**: per category or lesson, by days after enrollment (day 0 immediate) or fixed date; lessons can be gated until prior completion. In-app notifications when drip content unlocks. Workflows can email on unlock.

**Assessments (quizzes and assignments)** **[official]**:
- Add to a course, category or lesson. Quiz settings: title, thumbnail, optional passing grade percent, pass and fail confirmation messages, status Published/Draft/Locked. Question types: single choice and multiple choice, each with correct answers and an optional explanation. Retakes allowed (max attempts not documented). If a passing grade is on, learners see which answers were right or wrong but not the correct answers; if off, they see the answers and explanations.
- Assignments: title, ungraded checkbox, thumbnail, instructions (rich text), uploadable template files, confirmation message. A graded-assignment workflow (manual grading with feedback) is not documented in what I read.
- Admin analytics: Memberships, Analytics, Assessments with per-learner answers, Processing/Passed/Failed, CSV export (over 500 rows emailed as a link valid 24 hours). Automated emails go to learners and instructors on submissions and feedback.
- Weaknesses: no branching, no randomized question banks, only two question types.

**Certificates**: Certificate Builder (text, frames, images, signatures, QR codes, background, canvas size, layers) with dynamic recipient fields; attach a template to a course for automatic issuance, or use the workflow action **Issue Certificate** (for example on quiz pass via Lesson Completed). Trigger **Certificates Issued**. July 2026 added badge templates and flexible expiry (never, fixed date, or 3 to 36 months) and reminder offsets; Aug 2026 Certificate AI (beta) designs a certificate from a prompt. QR verification available.

**Analytics**: Course Progress Analytics dashboard (rebuilt July 2026) with enrolments, completion, per-student progress. Reviewers still describe it as progress percent without time-on-content depth.

**Other**: instructors/roles, video testimonial triggers (Sept 2026), course filtering, Ask AI course management (structures, drip, headers/footers, CSS), no SCORM/xAPI, no native affiliate tracking inside courses (separate Affiliate Manager with its own triggers and actions), membership content cannot be embedded in a normal site page, video size/length ceilings.

**Branding and domain**: logo, colors, favicon, hero image, per-lesson thumbnails, layout themes (Neue, New Classic and others), custom domain, SEO meta, magic-link login (passwordless). Client Portal unifies Courses, Communities, Dashboard, Billing, Shared Files, Affiliates and Account Settings.

### 4.2 Communities

- **Groups** (name, slug, description, cover image, public or private, free or paid). **Channels** inside groups (admin-created; public or private; restricted to paid tiers; nested channels added May 2026). **Home** feed (all posts), posts with text, images, video, files, polls (announced, not yet shipped in the sources), likes, comments, replies, emoji reactions (beta refresh), pinning, banning, moderation tools, voice notes (Sept 2026), comment management, direct messages between members, member directory and profiles, **Events** (members schedule and promote, with notifications), **Go Live** (collaborative meeting rooms or encoder broadcast, optional recording and replay saved as a post, host controls for chat and speaking permissions; Labs).
- **Gamification** **[official]**: points (documented value: 1 point per like received on a post, comment or reply), 9 levels per group with thresholds (0, 5, 20, 65, 155, 515, 2015, 8015, 33015; renamable, not configurable), badges, leaderboard, up to 3 text rewards (fulfilled offline, not tied to levels), setup under Memberships, Communities, Groups, Settings, Gamification and Rewards. Levels are per group. Courses can unlock by level, time since joining, or purchase. Workflow trigger **Community Group Member Leaderboard Level Changed**.
- **Paid access**: create a product in Memberships and link it to the group; one-time or recurring; failed payment recovery and access control handled by the platform. Triggers and actions: Group Access Granted/Revoked, Private Channel Access Granted/Revoked, actions Grant Group Access, Revoke Group Access.
- **Course integration**: attach courses to a group so they appear inside it.
- **Social Planner API** can schedule and publish Community posts (Oct 2026).
- **Importers**: Skool importer (skips members without email and their posts; courses rebuilt manually; paying members must resubscribe).
- Limits and gaps: community groups cannot be copied by snapshots (planned), polls not live, lighter gamification than Skool (points only from likes, fixed levels).

### 4.3 GoKollab (public marketplace and app)

- GoKollab is HighLevel's consumer-facing discovery marketplace and member app (published under the LeadConnector developer name). Creators activate it from Memberships, Kollab Marketplace ("Activate now"). Groups with roughly 10 or more members can be listed; ranking is based on active members; owners choose which groups to spotlight. Members sign up with Google or email, search free and paid groups, can create their own, and switch between Courses and Communities via a bottom nav and group switcher. Advertised as zero commission on creator earnings (the cost to creators is their own payment processor fees).
- A beta UI refresh built on the "HighRise" design system (July 2026) merges Communities and Courses into the unified Client Portal: group switcher, All Posts home, bigger post layout, unified search, member tab with DM, emoji reactions, inline moderation.

### 4.4 ClientClub and mobile app branding

- "ClientClub" is HighLevel's older name for the client portal / membership app experience (not found as a current official term in 2026 sources; treat as legacy naming). 
- **Branded Client Portal App** $49 per month per sub-account (HighLevel's own pricing guide) lets an agency ship a branded member app (own name, icon, splash); needs the agency's own Apple and Google developer accounts and typically goes live in 7 to 10 working days. Older sources cite a separate fully white-labeled **Mobile App** upgrade of $497 per month; a pricing tracker lists lower figures, so confirm the current rate before using these numbers.
- Standard plans use the HighLevel-branded member app (GoKollab / LeadConnector). Push notifications and notification controls exist; students can view lessons, progress and communities in the app.

### 4.5 Entities (inferred)

Product, Category, Lesson (content blocks), Offer (price refs, access rule, expiry), Enrollment/Access Grant (contact, offer, product, granted_at, expires_at, source), Progress (contact, lesson, status, completed_at, time), Quiz, Question, Attempt, Assignment, Submission, Certificate Template, Issued Certificate (verification id), Group, Channel, Post, Comment, Reaction, Event, Member Role, Level/Points ledger, Badge, Reward.

### 4.6 Pain points

- Course player and community UX trail Kajabi, Teachable, Skool and Circle; analytics are shallow; no SCORM.
- Assessment depth is thin (two question types, no question banks, grading flow for assignments unclear).
- Gamification is basic and rewards are manual.
- Mobile app: shared branded app vs separate paid white-label app; Apple/Google developer accounts required; long review lead time; some features only in the web portal.
- Snapshot gaps (communities not copied).
- Migration is manual (no one-click importer from Kajabi/Teachable; Skool importer is partial).
- Video size/length ceilings and no advanced video analytics.
- Hidden costs: email and SMS usage, Stripe Billing add-on, per-sub-account fees.
- Beta and Labs features keep appearing before parity (community comment management, Go Live in Labs, UI refresh in beta).

---

## 5. Workflow automation builder

### 5.1 Overview

Workflows (Automation, Workflows) are the automation engine and replaced the legacy **Campaigns** and **Triggers** features, which are deprecated and hidden unless the sub-account was created from a snapshot that used them (agencies created after November 2021 cannot even re-enable them). Workflows added what legacy lacked: If/Else, Go To, Math Operation, Goal Event, more triggers, more actions, CRM actions inside the same flow. Campaigns only had messaging steps, Wait and Webhook; triggers only had email/SMS and campaign add/remove.

Landing page offers three paths: **Build using AI**, **Browse Templates** (recipes), **Create Workflow**. A workflow has one or more **triggers** (any one enrolls a contact, each with optional **trigger filters**) followed by a list or canvas of **actions**. Lifecycle states: Draft and Published. Typical top bar: Builder, Settings, Enrollment History, Execution Logs tabs (named in third-party material; official article did not describe the tabs but references enrollment history and execution logs).

Two builders exist: the **Standard** list builder and the **Advanced** drag-and-drop canvas (delinked nodes, multiple independent paths, Go-To connections for triggers). Defaults can be set at agency or sub-account level (Global Workflow Settings), switching rights are permissioned, and switching back to Standard is blocked until Advanced-only items are removed. Action limit raised to 600 per workflow in both builders (Nov 2025). Right-click context actions, Highlight Contact Path (shows entry, exit, skipped and error nodes), and expanded validation (48 actions and 28 triggers validated on save, Feb 2026) exist. Sept 2026: publishing is blocked while unresolved configuration errors remain (save still works); validation errors appear in a sidebar.

### 5.2 Triggers (official list, 89 total, grouped as the product shows them)

**Contact (12)**: Birthday Reminder, Contact Changed, Contact Created, Contact DND, Contact Tag, Custom Date Reminder, Note Added, Note Changed, Task Added, Task Reminder, Task Completed, Contact Engagement Score.

**Events (22)**: Inbound Webhook, Scheduler, Call Details, Email Events, Customer Replied, Conversation AI Trigger, Custom Trigger, Form Submitted, Survey Submitted, Trigger Link Clicked, Facebook Lead Form Submitted, TikTok Form Submitted, Video Tracking, Number Validation, Messaging Error (SMS), LinkedIn Lead Form Submitted, Funnel/Website PageView, Quiz Submitted, New Review Received, Prospect Generated, Click To WhatsApp Ads, External Tracking Event.

**Appointments (4)**: Appointment Status, Customer Booked Appointment, Service Booking, Rental Booking.

**Opportunities (5)**: Opportunity Status Changed, Opportunity Created, Opportunity Changed, Pipeline Stage Changed, Stale Opportunities.

**Affiliate (4)**: Affiliate Created, New Affiliate Sales, Affiliate Enrolled In Campaign, Lead Created.

**Courses (12)**: Category Started, Category Completed, Lesson Started, Lesson Completed, New Signup, Offer Access Granted, Offer Access Removed, Product Access Granted, Product Access Removed, Product Started, Product Completed, User Login.

**Payments (12)**: Invoice, Payment Received, Order Form Submission, Order Submitted, Documents and Contracts, Estimates, Subscription, Refund, Coupon Code Applied, Coupon Redemption Limit Reached, Coupon Code Expired, Coupon Code Redeemed.

**Ecommerce Stores (6)**: Shopify Abandoned Cart (deprecating), Shopify Order Placed, Shopify Order Fulfilled (deprecating), Order Fulfilled, Product Review Submitted, Abandoned Checkout.

**IVR (1)**: Start IVR Trigger. **Facebook/Instagram (2)**: Facebook Comment(s) On A Post, Instagram Comment(s) On A Post. **Communities (5)**: Group Access Granted, Group Access Revoked, Private Channel Access Granted, Private Channel Access Revoked, Community Group Member Leaderboard Level Changed. **Certificates (1)**: Certificates Issued. **Communication (2)**: TikTok Comment(s) On A Video, Transcript Generated. **Google Ads (1)**: Google Lead Form Submitted.

Added later per 2026 notes (secondary sources, not all present in the Feb 2026 official list): Payment Failed, Review Received, Form Partially Completed, SLA trigger for conversations, Client Portal file-upload trigger, video testimonial received, membership access expiry, plus native app triggers (HubSpot, Klaviyo with polling every 5 minutes, Calendly, Housecall Pro, Jira, Todoist, Jotform, Manus, Browse AI, Fathom). Advanced tag filtering now applies to opportunity and invoice triggers.

Trigger concepts: **filters** on each trigger, "execute once per contact" vs re-entry, and for opportunity triggers an "allow multiple opportunities" toggle (on by default in new workflows).

### 5.3 Actions (official list, grouped)

**Contact**: Create Contact, Find Contact, Update Contact Field, Add Contact Tag, Remove Contact Tag, Assign to User, Remove Assigned User, Edit Conversation (mark read/unread/archive), Enable/Disable DND, Add Note, Add Task, Copy Contact (to another sub-account), Delete Contact, Modify Contact Engagement Score, Add/Remove Contact Followers.

**Communication**: Send Email, Send SMS, Send Slack Message, Call (rings staff then connects), Messenger, Instagram DM, Manual Action (task for human), Manual Call/Manual SMS, GMB Messaging, Send Internal Notification (to users or the contact), Send Review Request, Conversation AI, Facebook Interactive Messenger, Instagram Interactive Messenger, Reply in Comments, WhatsApp, Send Live Chat Message, Voicemail drop.

**Send Data**: Webhook / Custom Webhook (premium), Google Sheets (premium).

**Internal tools / logic**: If/Else (nested AND/OR since Q1 2026; conditions on contact fields, tags, appointment status, custom values, replies, opportunity owner/follower, and so on), Wait (time delay, event/appointment time, or wait-for conditions such as Condition, Contact Reply, Trigger Link Clicked, Email Event), Goal Event, Split (random A/B), Update Custom Value, Go To (jump to a step), Remove from Workflow, Add to Workflow, Remove from All Workflows, Arrays (find/filter/transform lists), Drip Mode (batch release: 1 to 10,000 per batch, interval 1 minute to 7 days), Text Formatter, Math Operation, Custom Code (JavaScript, and Python since June 2026), Associate Records (Labs, links contacts, companies, opportunities, custom objects).

**AI (Workflow AI folder)**: GPT Powered by OpenAI / AI Prompt, AI Decision Maker, AI Intent Detection, AI Summarize, AI Translate, AI Agent, AI Extract Data, Update Conversation AI Bot and Status, AI Image Generation, AI Analyze Image, AI Email Parser, Eliza AI Appointment Booking (legacy), Send to Eliza Agent Platform.

**Appointments**: Update Appointment Status, Generate One Time Booking Link.

**Opportunities**: Create/Update Opportunity, Remove Opportunity.

**Payments**: Stripe One-Time Charge, Send Invoice, Send Documents and Contracts, (recurring invoice send), and per the Goal Event types: payment received, invoice paid, document status.

**Marketing**: Add to Google Analytics, Add to Google AdWords, Facebook Add/Remove Custom Audience, Facebook Conversion API.

**Affiliate**: Add to Affiliate Manager, Update Affiliate, Add/Remove from Affiliate Campaign. **Courses**: Course Grant Offer, Course Revoke Offer, Issue Certificate. **Communities**: Grant Group Access, Revoke Group Access. **IVR**: Gather Input on Call, Play Message, Connect to Call, End Call, Record Voicemail.

**Third-party/native app actions** (premium): Klaviyo (17 actions), Todoist (12), Jira (11), Housecall Pro (14), Calendly (9), Browse AI (4), HubSpot (create/find contact), Jotform (create submission), Manus, Slack, Google Sheets, ClickUp/Airtable/Notion (usable as AI Agent tools).

### 5.4 The AI Agent action and Workflow AI

- **AI Agent** action: write a goal in plain language (with an "Enhance prompt" helper and 11 templates such as Form Lead Follow Up, No Show Appointment Recovery, Stale Deal Nudge), give it up to 10 tools (CRM actions, calendar, messaging, apps), optional conversation memory (rolling per-contact summary), output as text or JSON schema (string/number/boolean) that later steps can branch on. Per-tool toggle "let AI decide all field values" or lock specific fields. Execution logs show each reasoning step, tool call, tokens and timestamps. Models: GPT family plus (Aug 2026) Anthropic and Google models with reasoning effort. Billing: LLM tokens plus premium tool executions; standard CRM tools are not charged extra.
- **Workflow AI Builder**: describe in text or voice, get a workflow in under 30 seconds; chat mode to plan; edit existing workflows conversationally (including If/Else and Wait), targeted bulk edits, "Point and Edit" visual selection, undo/redo and restorable version cards per build, post-generation to-do list for credentials and pipelines, up to three clarifying questions; cannot test workflows itself; can be disabled at agency Labs or sub-account level. Ask AI (the platform assistant) can also build workflows.
- Pricing model for AI is token-based pass-through at various markups; Sept 2026 notes AI Agent and GPT actions moved to cheaper models.

### 5.5 Settings (Settings tab) **[official]**

- **Allow Re-entry** (contacts may re-enter only after finishing or being removed; appointment and invoice triggers always allow re-entry per new appointment/invoice).
- **Allow multiple opportunities** (opportunity triggers).
- **Stop on Response**: ends the workflow for a contact who replies on any channel; voicemail detection stops voicemails counting as replies, with a "disable voicemail detect" option; "User replied" can also be a Goal Event so a human reply stops automation.
- **Timezone**: account timezone or contact timezone (falls back to account).
- **Time window**: restrict communication actions (email, SMS, calls) to chosen start/end and weekdays; out-of-window actions pause and resume at next slot; internal actions are unaffected.
- **Sender details**: sender domain (all domains weighted, or a specific dedicated domain), from name, from email, from number; per-action values override; domain selection also supported from Aug 2026.
- **Conversations: mark as read** for workflow-sent messages.
- **Error notifications**, **Workflow AI** toggle, default builder, Global Workflow Settings (sub-account) and agency Workflow Settings.
- Bulk enrol/remove contacts from the Contacts list; Smart List filter on workflow enrollment (Q1 2026).

### 5.6 Version history, enrollment history, execution logs, folders

- **Version History** **[official, Labs beta at launch]**: versions are created on manual save, unsaved-changes confirm, "Save Version", and status changes (draft/publish). Auto-saves do not create versions. History retains up to 10 versions or 30 days, whichever comes first; filter by editor; each entry has label (v12), timestamp, editor, status. Restore reopens the old version as a **new draft** (live workflow unchanged until publish) and requires the workflow to be in Draft with no enrolled contacts; "Create new workflow from version" branches it. Shortcut Shift+V per a 3rd-party blog. Compare/preview exists.
- **Enrollment History**: per-workflow list of every enrolled contact with status and filters by time and status; per-row actions (view execution history, move to next step, remove). Statuses include active, completed, and "removed by workflow action / by external workflow action", plus failed/skipped (inferred).
- **Execution Logs**: step-by-step log with filters, errors and skipped steps; AI Agent steps show reasoning.
- **Folders**: workflows are organized into folders and sub-folders on the Workflows list page (name, status, last updated, stats such as total enrolled, active, executed); bulk move and archive. I could not retrieve an official folders article, so details are [inferred]. Third-party advice: archive rather than delete because deleting removes stats and history.
- **Test workflow**: run a test contact in test mode with execution logs. Templates/recipes gallery and snapshot distribution.

### 5.7 Premium actions, pricing and limits

- Premium triggers and actions (webhooks, Google Sheets, custom code, Text Formatter-class utilities, Find/Create Contact, native third-party apps, marketplace apps) cost $0.01 per execution, with 100 free lifetime executions per sub-account. **Workflow Pro** bundles: Free (100 lifetime), Starter $10 per month for 10,000 (overage $0.008), Growth $25 for 30,000 ($0.006), Scale $50 for 65,000 ($0.004). AI actions are NOT in Workflow Pro (pay as you go by model and tokens). Agencies can rebill premium costs (markup needs the top plan).
- Marketplace developers can price their own custom actions per execution; HighLevel waived its $0.01 fee for some developers as an experiment (Apr 2025).
- Limits: 600 actions per workflow; Drip batch 1 to 10,000; no stated cap on workflow count; one Goal Event per workflow; Goal Event criteria within an action are OR logic; each contact is not re-evaluated for the same goal.
- Comms prerequisites: US texting needs A2P 10DLC registration, email needs SPF/DKIM/DMARC; failures are often silent.

### 5.8 Goal Event, Wait, Split, Go To details **[official/3rd-party]**

- **Goal Event** types: Form Submitted, Payment Received (success/failure, product filter), Invoice Paid (paid or partially paid; any invoice or the one sent by a specific action), Document Status (Viewed, Signed, Declined, Completed), Email Events (Opened, Clicked, Unsubscribed (Mailgun only), Complained, Spam), Trigger Link Clicked, Review Request Clicked, Contact Tag Added/Removed, Appointment Status, User Replied (specific user and channel limits, met on delivery). Behavior for contacts reaching the goal step without meeting it: End workflow, Continue anyway, or Wait until goal met. Continuous monitoring even outside business hours; no reversal when conditions later change.
- **Wait** forms: fixed duration, until a specific time/day, relative to an appointment or event date ("before appointment"), or until a condition/event (reply, link click, email event). 
- **Go To** jumps to another step or workflow; Advanced builder adds Go-To connections for triggers (enter at a chosen node).
- **Split** randomizes paths for A/B tests.

### 5.9 Entities (inferred)

Workflow {id, name, folder_id, status, builder_type, triggers[{type, filters}], nodes/edges, settings{reentry, stop_on_response, timezone, window, sender}, version_id}, WorkflowVersion, Enrollment {contact_id, workflow_id, status, current_node, entered_at}, ExecutionLog {enrollment_id, node_id, status, input/output, error, ts}, Custom Values, Template/Recipe, Premium Execution meter.

### 5.10 Pain points

- **Silent failures and quirks**: duplicate sends when re-entry is on (default), stuck contacts, triggers firing multiple times, messages going out in the wrong timezone, appointment reminders using fixed delays instead of "before appointment" waits.
- **Learning curve and sprawl**: "everything is a workflow"; large canvases get slow and unmaintainable; no real modularity (sub-workflows are done with Add to Workflow / Go To), no variables scoped like code, limited debugging beyond logs.
- **Version history is shallow**: 10 versions or 30 days, restore requires no enrolled contacts and draft status, Labs-gated at launch; no true diff, no environments (draft/prod), no review or approval flow, no git-like branching beyond "create from version".
- **Publish semantics**: edits to a live workflow affect in-flight contacts in ways agencies have to learn by experiment; the Sept 2026 validation gate was added because bad snapshots were being pushed.
- **Integrations**: about 80 native versus thousands in Zapier/Make; agencies pay $30 to 100 per month per client for bridges. Webhook action docs are thin; inbound webhook payload mapping is manual.
- **Premium action metering** surprises customers; AI costs are variable.
- **Limited data operations**: Arrays and Math Operation are recent; no first-class loops over records, joins, or data tables; custom objects are only just reachable (Associate Records in Labs).
- **API/webhook ceiling for builders**: API report card grades the API D: 200,000 daily requests per resource and burst of 100 per 10 seconds, no bulk export, 24 hour tokens with rotating refresh tokens, docs lag features, v1 API sunset forced rebuilds, UI-only features not exposed.
- **Stability**: reviewers report minor regressions every 2 to 4 weeks (stalled workflows, inbox issues, sync failures) and frequent UI changes shipped without notice.
- **Support**: ticket support slow, no phone.

---

## 6. Add-ons and ecosystem

### 6.1 HighLevel App Marketplace

- Third-party developers build **OAuth apps** with scopes (least privilege recommended), installable by agency, sub-account or both; **private apps** for internal use and **public apps** after review; a **white-label** listing type with no HighLevel branding on user-facing surfaces. App surfaces: **Custom Pages** (externally hosted iframes appearing in the app detail page or the left nav, per distribution type), custom menu links, webhooks, **custom workflow triggers and actions** (needs `workflows.readonly`; counted as LC Premium Triggers and Actions, billed per execution; sub-account must have the premium feature enabled; actions appear only if the app is installed), external authentication, custom fields, payment provider integrations.
- Marketplace gets "Ask AI" app discovery (Sept 2026) with agency visibility controls. A community request asks for a white-labeled marketplace for SaaS-mode resellers.
- Developer experience: REST API v2 with Marketplace App OAuth or Private Integration Token; official MCP server exists; docs lag features; rate limits as above.
- Entities: App {id, scopes, distribution, listing type, pricing model, webhooks, custom pages}, Install {app_id, agency/location id, tokens}.

### 6.2 WordPress

- **HighLevel WordPress hosting**: managed WP infrastructure resold by agencies, advertised with Cloudflare Enterprise CDN, daily backups, SSL, security and pooled storage; list tiers $10 per month (Standard), $220 (Utility), $497 (Truly Unlimited) per HighLevel's pricing guide. WordPress "AI Generated Pages" (Feb 2026, early) generate a landing page from niche, goal and aesthetic. The **LeadConnector WordPress plugin** connects forms, chat widget, calendar embeds and contact sync (includes hooks for Gravity Forms, WooCommerce, LearnDash, BuddyBoss, Elementor, webhooks).

### 6.3 Ad Manager / Ad Publishing

- Marketing, Ad Manager: connect Meta (Facebook and Instagram) and Google (Search and Display) accounts; create campaigns inside HighLevel (Facebook: up to 10 ad sets and 10 ads per campaign; Google Search: up to 10 ad groups and 3 ads per group); templates with headlines, CTAs, creative and tracking URLs that can be cloned across sub-accounts; audiences (retargeting, lookalikes from CRM data, behavioral segments, geo); bidding manual or automatic; A/B tests; Facebook lead form import with drafts and multi-level preview; statistics tab (impressions, CTR, CPL, conversions, budget use) side by side; leads flow into pipelines and workflows. 2026 additions: Meta budget optimizer, Opportunity Score pre-publish readiness check, custom values in ad copy, LinkedIn campaigns via Ask AI, Google Ads dashboard widgets. Ad Manager costs agencies $0 on the pricing guide (ad spend is paid to the platforms).

### 6.4 Prospecting

- Free (agency only): 5 premium reports per month and 50 basic reports per day; basic reports cover business listing audit, basic Google Business Profile analysis and reputation snapshot; no CRM integration or outreach.
- Premium Prospecting $29 per month per agency (includes one sub-account): unlimited reports (refresh once per week), full audits (website speed/SEO/mobile, local SEO heatmaps with competitors), AI prospecting that finds leads by area and niche (up to 3 niches, weekly suggestions), lead-gen widget (embeddable audit as lead magnet), and for sub-accounts: send prospects to CRM/opportunities, workflows, email/SMS outreach with AI templates. July 2026 added an activity center, auto pipeline routing, contact enrichment, duplicate prevention. Trigger **Prospect Generated**.

### 6.5 Events (beta, Labs)

- Open to all agencies from Labs (Aug 2026): branded event pages with sections, layouts and custom CSS; RSVP (free) vs ticketed events with multiple ticket tiers, inventory, sales windows, coupon codes; checkout; attendee management including manual add; QR-code check-in via the mobile app; attendance dashboard; pre and post event automations; Meta Pixel tracking.

### 6.6 Other add-ons and metered services

- Branded Client Portal App $49 per month per sub-account; SEO (Search Atlas) $79; Premium Prospecting $29; WhatsApp $10 plus usage (5 percent processing fee removed Oct 2026); Dedicated IP $59 per domain; Online Listings $30 per month ($150 per 6 months, $300 per year); WordPress hosting tiers; AI Employee Unlimited $97 per location per month (Conversation AI, Voice AI, Reviews AI, Content AI) and Growth $50; email $0.675 per 1,000; email validation $2.50 per 1,000; phone at Twilio-like rates; Workflow Pro tiers.
- **Affiliate Manager**, **Reputation (52+ platforms)**, **Social Planner**, **Snapshots**, **SaaS Mode**, **HubSpot importer**, **AI Studio** (AI site and app builder with Cloud database, user accounts and hosted checkout) are adjacent but out of this file's scope.
- **Certificates** (builder, AI, badges) were covered in section 4.1.
- **Gokollab** (section 4.3) is the discovery app for communities.

---

## 7. Cross-cutting pricing and packaging model (what competitors must understand)

1. Flat subscription ($97, $297, $497 per month). Almost every feature is "included" at the plan level, but **metered consumption** (SMS, voice, email, AI tokens, premium workflow executions, WhatsApp) is billed separately and can be re-billed by agencies with markup (markup on the highest plan only).
2. Per-sub-account add-ons multiply with client count (branded app, AI Employee, prospecting, SEO).
3. No payments platform fee, but processor fees and Stripe Billing surcharges apply.
4. Snapshots and SaaS mode are the growth loop: build in one account, resell to many.

---

## 8. Consolidated pain points, ranked by how often they appear

1. Steep learning curve and module sprawl (most-cited complaint). Too many places to configure the same thing (calendar notifications vs workflows; Service Menu v1 vs Services v2; invoice old vs new UI; standard vs advanced builder; Campaigns vs Workflows legacy).
2. Reliability: calendar sync failures (Outlook especially), stalled workflows, regressions every few weeks.
3. Surprise usage costs and metering complexity.
4. Support quality and no phone support.
5. Deliverability and compliance setup (A2P 10DLC, SPF/DKIM/DMARC) failing silently.
6. Depth gaps in individual modules ("adequate not excellent"): LMS (no SCORM, thin quizzes), e-commerce (no fulfillment, thin inventory), documents (no signing order/audit trail documented), community gamification, workflow versioning and debugging.
7. Integration breadth and API limits (about 80 native integrations, v2 API rate limits, no bulk export, UI-only features).
8. Frequent unannounced UI changes that break agency SOPs and snapshots; mobile app lags web.
9. Snapshot incompleteness (products, community groups).
10. Provider/feature matrix complexity in payments.

---

## 9. Opportunities to do better (concrete ideas for our product)

### 9.1 Platform-wide

1. **One scheduling-payments-automation model, not three.** HighLevel bolts notifications into calendars, reminders into workflows, and payments into five different builders. Make appointment reminders, receipts, dunning and drip notices one **"communication policy"** object per entity with clear precedence, and expose it in a single timeline view per contact.
2. **Transparent usage meter.** Show estimated monthly cost before enabling a workflow (premium executions, SMS segments, AI tokens) and a live meter per workflow. HighLevel's top complaint after complexity is bill surprise.
3. **Never ship parallel generations.** Migrate old calendars/invoices/builders automatically instead of keeping v1 and v2 side by side with different capability matrices.
4. **Silent failure detection.** A "health" panel that flags unregistered senders, expired calendar tokens, missing statuses, and dead triggers before a customer notices. HighLevel's reminders and sync fail silently.
5. **Snapshots that are complete and diffable.** Include products, community groups, courses, stores, payment settings (minus secrets), with a dry-run diff and rollback per target account.

### 9.2 Calendars

6. **Reliable two-way sync as a headline feature.** Webhook-driven (Google push notifications, Microsoft Graph subscriptions) with a visible sync health badge per user, automatic re-auth prompts, and a conflict audit log ("why was this slot shown/hidden").
7. **First-class recurring and series.** Unlimited or rule-based series with proper exception handling, series-level cancel, and workflows that fire per occurrence and per series. HighLevel caps at 24 and fires workflows on the first occurrence only.
8. **Real resource scheduling** (rooms, equipment, vehicles, practitioners) unified with Rentals under one availability engine with quantity and lead/turnover time, instead of Service resources and Rentals being separate modules.
9. **Smarter routing.** Weighted round robin with numeric weights, capacity caps, skill/territory routing, lead-owner stickiness, working-hours fairness, and a "simulate next 20 bookings" preview. HighLevel only has three priority levels plus a 3-appointment equality cap.
10. **Auto-status.** Infer Showed/No-show from video join events, call logs, or check-in rather than relying on reps (HighLevel depends on manual updates).
11. **Payments on every booking path**, including staff-created bookings, deposits that become balance invoices, and package/credit bundles (session packs, memberships that include N bookings).
12. **Better meeting links**: native Teams, Zoom, Meet, plus dynamic links for all types, and per-booking location choice by the invitee.
13. **Calendar AI that explains and fixes**: "why is no slot offered" with one-click remedies (HighLevel started this in Sept 2026; make it deterministic and testable).

### 9.3 Payments

14. **Provider-neutral payment abstraction.** One checkout, one payment-method capability matrix auto-resolved at runtime ("this wallet isn't available here because X") so merchants never read a 15-column table.
15. **Coupons everywhere** including invoices and estimates, stackable rules, and per-customer/per-cycle semantics that behave identically across providers.
16. **Deposits and schedules as a single concept** (deposit percent, milestones, installments) shared by calendars, estimates, invoices, orders and contracts, with auto-created balance invoices and workflow triggers on each milestone.
17. **Dunning that is configurable by rule** (more than three retries, smart timing, card updater, SMS/email sequences, grace period, automatic pause) with manual retry across all providers from day one.
18. **Merchant-of-record optional mode** or built-in tax filing partners (Stripe Tax, Avalara) with nexus monitoring, so small sellers are not left to do filings.
19. **Contracts with a real e-sign trail**: signing order, audit certificate, expiry, reminders, templates with conditional clauses, redlines, and automatic invoice/subscription creation on signature.
20. **Unified ledger**: orders, invoices, subscriptions, refunds and disputes in one transaction model with reconciliation exports (Stripe payouts match), instead of separate Orders/Transactions/Invoices views.

### 9.4 E-commerce

21. **Be honest about scope**: target service-plus-product businesses, not Shopify competitors. Win on CRM-native commerce: lifetime value per contact, reorder automations, subscriptions-and-boxes, local pickup and delivery slots tied to the scheduling engine.
22. **Fulfillment basics**: carrier rate shopping/labels (Shippo, EasyPost), automatic tracking sync, pick-and-pack lists, multi-location inventory, low-stock alerts, bundles.
23. **Native Shopify/Woo two-way sync** (including taxes, multiple transactions, refunds, inventory) rather than one-way imports.
24. **Checkout parity**: bumps, upsells, subscriptions and abandoned-cart recovery on store checkout, with a previewable default recovery email.

### 9.5 Memberships and Communities

25. **A proper LMS core**: more question types, question banks and randomization, assignment grading with rubrics and feedback, cohorts and live sessions, SCORM/xAPI import-export, per-learner time analytics, video analytics.
26. **Gamification that creators can configure**: points for posting, commenting, completing lessons, attending events; configurable levels and badges; real reward fulfillment (discount codes, course unlocks) automated via workflows.
27. **One app, one login** for courses, communities, events and bookings, with a low-cost white-label option included in higher tiers rather than $49 to $497 add-ons; remove Apple/Google developer-account friction by offering a managed publishing service.
28. **Complete snapshots and importers** (Kajabi, Teachable, Thinkific, Skool, Circle) with course structure, members and progress.
29. **Community polls, nested spaces, member-to-member DMs, and discovery** on day one, plus an open, commission-free marketplace like GoKollab but with ranking transparency.
30. **Access policy engine**: expiry, drip, cohort start dates, and revocation on failed payment as declarative rules on the offer, not workflow workarounds.

### 9.6 Workflows

31. **Versioning like software**: unlimited named versions, diff view, draft vs published environments, approval flow, test with sample contacts and time-travel simulation (fast-forward waits), rollback with in-flight contact migration rules. HighLevel keeps 10 versions or 30 days.
32. **Safe edits of live workflows**: show how many contacts are at each step and offer "migrate contacts" when a node is removed or changed.
33. **Better debugging**: per-contact timeline with variable values at each node, replay, "why didn't this contact enter" explainer (trigger filter evaluation trace), and bulk retry of failed steps.
34. **Real modularity**: reusable sub-workflows with inputs/outputs, shared variables, and libraries distributed via snapshots; first-class loops over records and a lightweight data table/object store.
35. **Open, documented triggers and actions** with typed schemas, rate-limit visibility, and an SDK for custom nodes; support both code (JS/Python, already a start in HighLevel) and no-code mapping for inbound webhooks with sample-payload capture.
36. **Pricing clarity**: include a generous execution quota; charge only for external/AI cost at transparent rates; show per-workflow cost.
37. **Native deduplication and idempotency**: protect against double enrollment and double sends by default (re-entry off by default for transactional flows), with clear guardrails around time windows and quiet hours.
38. **AI that is testable**: AI-generated workflows should come with auto-generated test cases and a dry-run, and agent steps should have deterministic fallbacks and spend caps.
39. **Folder/search/governance**: tags, owners, dependency graph ("what uses this tag/field/calendar?"), usage and error dashboards, and permissioned publishing.

### 9.7 Ecosystem

40. **Developer-first marketplace**: stable OAuth, generous rate limits, bulk export endpoints, webhooks with signatures and retries, first-class sandbox sub-accounts, and a revenue-share model that is simple and transparent. HighLevel's API grades poorly on limits, bulk export and docs freshness.
41. **Ad and prospecting modules** are crowded; prefer deep integrations (Meta/Google/LinkedIn conversion APIs, offline conversions from payments and appointments) over rebuilding ad managers.

---

## 10. Gaps, caveats and suggested follow-up research

- G2, Capterra and reddit r/gohighlevel were not directly readable (G2 returned 403; search did not surface reddit threads). A manual pass on those would sharpen the pain-point ranking and quantify frequency.
- No hands-on access to the product UI: layout descriptions are assembled from help-article steps and third-party screenshots' text. A trial account walkthrough should confirm tab names, field labels, and defaults.
- Items I could not confirm from official docs: Event calendar as a distinct current type, exact invoice status list, Documents expiry and signing order, workflow folder features, Custom Webhook and Inbound Webhook configuration details (methods, headers, auth, mapping), Custom Code runtime limits (timeouts, packages), If/Else condition catalog, Service add-ons, rental add-ons and deposit rules, ClientClub as a current term, WooCommerce native support.
- Numbers (fees, tier prices, caps) come from help pages and 3rd-party tables that change often; re-verify before using in pricing decisions.
- YouTube walkthroughs were not analyzed.
- Suggested next steps: (1) trial account teardown of calendars, workflow builder and payments, with screen recordings; (2) pull the ideas.gohighlevel.com boards sorted by top votes for scheduling-calendar, automations, invoicing and memberships to rank unmet needs; (3) read G2 "cons" filters and Capterra 1-3 star reviews; (4) inspect the public API v2 reference (stoplight / marketplace docs) to derive concrete schemas for the entities listed above.

## Appendix A. Source list

Official (help.gohighlevel.com and ideas.gohighlevel.com):
- Workflow triggers list (article 155000002292) and actions list (155000002294), Workflow settings overview (48001239875), Goal Event (155000003328), Version History (155000006656), Workflow AI Builder (155000006100), Standard vs Advanced builder (155000007323), Workflows vs Campaigns vs Triggers (48001229927), Workflow AI folder (155000000752), Getting started with workflows (155000002288), AI Agent action changelog.
- HighLevel pricing guide (155000001156), supported payment providers matrix (155000006075), Getting started with coupons (155000007524), documents and contracts workflow article (155000001301), Class booking calendars (155000003554), Recurring appointments (155000003450), Round robin distribution logic (155000001484), Service calendar setup guides (e.g. 155000001619), Rentals overview (155000006649), Inventory management (155000003435), Shipping and delivery (155000002428/2842), Shopify integration (48001203620), Gamification in communities (155000002487), Communities UI refresh (155000008223), Certificate AI (155000008577), Quiz/assignment article (48001224429), Free vs Premium Prospecting (155000005458), Events (155000008071), Stripe Tax for SaaS (155000007789), Ad Manager articles (155000002433, 155000002435, 155000004543).
- Marketplace developer docs (marketplace.gohighlevel.com): workflow actions and triggers, custom pages, app creation guide.

Third-party:
- Growthable guides (calendar, payments, ecommerce), HL Growth Partner (workflows, calendars, ecommerce, memberships 2026), ConsultEvo, NetPartners weekly update posts, RSLA and The Stack Insiders 2026 update roundups, GHL Experts roundups, OneExpand and SearchSherpa memberships/communities comparisons, SupplyGem (payments, ecommerce review), aigohighlevel.com review, freelancer.com workflow failure article, supergood.ai API report card, agencysupport.ladesk.com and other white-label mirrors.
