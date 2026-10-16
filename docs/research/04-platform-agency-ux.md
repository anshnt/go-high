# GoHighLevel (HighLevel / LeadConnector): Platform, Agency Layer, Developer Platform and UX Research

Research date: 2026-10-16. Scope: company overview, pricing, agency layer, platform settings, developer platform, UI/UX and review sentiment, competitive landscape, and opportunities for a better product.

## 0. How to read this document

### Source quality legend

Every claim below carries an implicit confidence level. Where it matters, I tag it.

- **[Official]** Read directly from HighLevel's own pages (gohighlevel.com/pricing, help.gohighlevel.com, marketplace.gohighlevel.com docs, the public GitHub repo `GoHighLevel/highlevel-api-docs`, ideas.gohighlevel.com feature board and changelog).
- **[Official-indirect]** Official GitHub raw docs or official help articles that were summarized by a fetch tool, so exact wording was not inspected.
- **[3rd-party]** Agency blogs, affiliate sites, comparison sites. Most of these have a commercial interest (they sell GHL setup, earn affiliate commission, or sell a competing product). Treat as directional.
- **[Unverified]** Claims that appeared in only one weak source or that conflict between sources.
- **[Background]** Knowledge from my training, not re-verified in this research pass. Use as hypotheses to check in a live trial account.

### Known limits of this research

- Reddit (r/gohighlevel) could not be fetched directly (blocked by the tooling). Reddit sentiment below is second-hand via blog syntheses. Do a manual pass on the subreddit before finalizing product decisions.
- G2 and Capterra review pages returned 403 on direct fetch. Their numbers come from search-result summaries.
- Several help-center articles are JS-rendered and returned only titles. The marketplace docs site (marketplace.gohighlevel.com/docs) renders client-side, so I used the public GitHub mirror of the docs instead.
- I did not log into a live account. The sidebar order and some UI details are partly from help-center text and partly from background knowledge. A hands-on trial (14-day free trial exists, card required) is strongly recommended to confirm UI specifics with screenshots.

---

## 1. Company overview

### 1.1 Identity and naming

- Product names in the wild: **HighLevel** (current official brand, used on pricing and help pages), **GoHighLevel** or **Go High Level** (legacy brand, still dominates SEO and community), **GHL** (community shorthand), **LeadConnector** (the white-label-friendly engine name; appears in API hostnames such as `services.leadconnectorhq.com`, the MCP endpoint, the "LeadConnector" mobile app, and "LC Phone" / "LC Email" product names). [Official]
- Company tagline in 2026 press: "AI-powered business operating system for agencies and growing businesses". [Official-indirect, via Inc. ranking press release]

### 1.2 History and founders

- Founded **2018**, Dallas, Texas area (some aggregators say Eugene, Oregon; treat location as inconsistent). Co-founders: **Shaun Clark** (CEO), **Varun Vairavan**, **Robin Alex**. [3rd-party, consistent across sources]
- Origin story (from an interview summary on Latka): Shaun Clark previously built InvoiceSherpa. The first product found early customers through a medical apps marketplace listing, then pivoted to serve **marketing agencies**, which became the core. [3rd-party]
- Positioning journey: (1) CRM and automation for local-business marketing agencies, (2) white-label "agency in a box" software the agency re-brands and resells (the "SaaS mode" play), (3) 2024-2026 repositioning as an **AI business operating system** (Conversation AI, Voice AI, AI Employee, Agent Studio, Super Agents, AI Studio) while keeping the agency channel as the primary go-to-market.
- The official go-to-market doc says it plainly: HighLevel sells mainly to **digital marketing agencies and consultants**, not directly to end businesses. Agencies buy licenses, white-label the platform under their own brand and domain, and resell to small-business clients. Agencies own the relationship; clients often believe they are using the agency's own software. [Official, marketplace docs "Understanding HighLevel's Go-To-Market Model"]

### 1.3 Funding, revenue, users (what is knowable)

| Item | Finding | Confidence |
|---|---|---|
| Funding | Nov 2021 round of about $60M led by PeakEquity Partners (per Latka/CB Insights style data). April 11, 2024: minority growth investment from General Atlantic, terms undisclosed. | General Atlantic [Official press]; $60M [3rd-party] |
| Valuation | Not found in any reliable source. A "$3B" figure circulated in my query but I found no source. Do not cite. | Unverified |
| Revenue | Latka estimates: 2021 about $8M, 2022 about $20M, 2023 about $38.5M, 2024 about $82.7M estimated ARR. Another aggregator claims "$1B revenue by 2026", which is not credible. HighLevel itself said "strong growth and profitability" with no figures. | Low; use order of magnitude only (tens to low hundreds of millions) |
| Headcount | About 560 (Dec 2023), about 785 (May 2025, LinkedIn via Latka). | [3rd-party] |
| Customers | Wildly inconsistent: "20,000 agency owners", "70,000 agencies, 600,000 businesses" (older developer docs), "2 million+ businesses" (a 2026 job posting), "more than 1 million businesses". Website-detection tooling shows the HighLevel stack detected on about 109,000 active domains (Aug 2026). | Directional only |
| Press 2026 | Inc. 2026 Regionals Southwest list, No. 13 (March 31, 2026). | [Official press via newswire] |
| Release cadence | A third-party count (affiliate-authored) found about 500 "new feature" changelog entries between March 3 and Aug 5, 2026, about 22.7 per week. | [3rd-party, promotional] |

Take-away for us: the incumbent is a profitable, fast-shipping, tens-of-thousands-of-agencies business with a 6-year head start, a huge feature surface, and an affiliate-driven acquisition engine. Competing head-on on breadth is a trap. Competing on UX, developer experience, reliability and trust is the opening.

### 1.4 Target customers

1. **Primary: marketing agencies and consultants** (the "agency owner" persona) who want a single stack to resell, with white-label branding and per-client sub-accounts.
2. **Secondary: SaaS-mode resellers** who package the platform into priced plans with automatic sub-account creation (a "SaaS in a box" business). This is where the $497 tier matters.
3. **Tertiary: direct SMB users** (service businesses: home services, clinics, gyms, real estate, insurance) who use HighLevel as their own CRM/marketing stack, typically on Starter or Unlimited with a single sub-account.
4. **Emerging: AI agencies** selling Voice AI receptionists and AI employees, which ties into usage-based rebilling.

### 1.5 Go-to-market engine

- **Affiliate program:** 40% recurring commission on referred agency subscriptions, with a reported 5% second tier on recruited affiliates, paid monthly (about the 15th) via Tipalti with a $50 minimum. Cookie window reported as 90 days by most sources (one says 30). Some sources say add-ons (white-label app, certification, AI Employee) also pay 40%. The Starter/Unlimited example: $297 plan pays about $118.80 per month. [3rd-party; verify at signup]
- There is also an in-product **Affiliate Manager** and **HL Affiliate Portal** (agencies can run affiliate programs for their own SaaS customers) and a "Sub-account Affiliate Manager" board on the ideas portal. [Official, ideas board category names]
- Massive third-party content ecosystem (YouTube, agency "snapshot" sellers, courses, Facebook groups, "GHL experts"), partly financed by the affiliate program. Most "reviews" you find are affiliate content. That biases public sentiment positively and also biases the "learning curve" narrative toward "you need an expert", which sustains a consultant economy around the product.
- HighLevel Certification Program: $97/month add-on. [Official, pricing page]

---

## 2. Pricing as of 2026

### 2.1 Subscription plans (official pricing page, fetched 2026-10-16) [Official]

| Plan | Monthly | Annual | Sub-accounts | Notable inclusions |
|---|---|---|---|---|
| **Starter** | $97 | $970 | 3 | Unlimited contacts, unlimited users, 24/7 support, all core features |
| **Unlimited** ("Most Popular") | $297 | $2,970 | Unlimited | Starter plus unlimited sub-accounts, **phone and email rebilling with no markup**, **basic API access** |
| **Agency Pro** (older name: "SaaS Pro") | $497 | $4,970 | Unlimited | Unlimited plus **SaaS Mode**, **automated sub-account creation**, **rebilling with markup**, user/agent reporting, **advanced API access** |
| **Enterprise** | Custom | Custom | Not stated | Dedicated customer success and account managers, custom development, dedicated Slack channel, premium support, higher API limits on request, quarterly business reviews, enterprise reporting, **white-label mobile app and HIPAA compliance included** |

Notes:

- 14-day free trial on any plan, card required, auto-bills at the end unless canceled, month-to-month contracts.
- Annual billing is about two months free (about 16.7% discount).
- The plan names drifted: the third tier was "SaaS Pro" for years and the pricing page now says "Agency Pro". Many blogs still say SaaS Pro. Expect confusion in any competitive content.
- Third-party guides disagree on whether Starter has 1 or 3 sub-accounts. The pricing page says 3. [Official wins]
- White label of the web app (domain, logo) is mentioned in the pricing FAQ without naming the tier. Third parties describe it as available from Unlimited. Branded **mobile** app is separate (see add-ons).

### 2.2 Add-ons (official pricing page) [Official]

| Add-on | Price |
|---|---|
| AI Employee Growth plan | $50/month per sub-account |
| AI Employee Unlimited plan | $97/month per sub-account |
| Branded Client Portal App | $49/month per sub-account (introductory price per the changelog; requires an opt-in form) |
| Dedicated email IPs | $59/month per IP (third-party billing guide says per dedicated domain and only on $297/$497 plans; inconsistent) |
| Domain purchasing | "Market leading prices", no figure |
| HighLevel Certification Program | $97/month |
| HIPAA compliance | $297/month, agency-wide, covers unlimited sub-accounts |
| Online listings management | $30/month per sub-account |
| Premium prospecting tool | $29/month per sub-account |
| Premium support | $500/month ($5,000/year per a third-party) |
| SEO (Search Atlas) | $79/month per sub-account |
| WhatsApp integration | $10/month per sub-account plus Meta conversation rates |
| White-label mobile app | $497/month (or $1,491 per quarter per a third-party) |
| WordPress hosting | From $10/month per site |

The page says most add-ons can be resold with your own markup on Agency Pro.

Payment providers listed: Stripe, PayPal, NMI, Authorize.net, Square, Adyen, Razorpay and "many more".

### 2.3 Usage-based charges (rebillable), US/Canada

The official pricing page states usage billing exists for email, SMS, calls, Conversation AI, Voice AI, Reviews AI, phone numbers and premium AI, but does not list the rates there. Rates below are from official help articles where marked and from third-party calculators otherwise. Rates change often. HighLevel itself tells users to confirm in-app.

**Phone and messaging (LC Phone)** [3rd-party calculators, mostly consistent]

- Local number: about $1.15/month. Toll-free: about $2.15/month.
- SMS: about $0.00747 per segment plus carrier pass-through ($0.0025 to $0.0045 per segment). MMS about $0.022 per segment.
- Outbound call: about $0.0126/min plus about $0.004/min for client minutes (another guide: $0.0166 or $0.021). Inbound: about $0.01165 to $0.0128/min. Forwarded inbound about $0.02/min.
- Call recording: $0.0025/min plus storage. Transcription extra.
- Carrier fee increases: AT&T (from April 1) and Verizon (from May 1, 2026) per a billing guide.
- One source claims a fixed 5% HighLevel surcharge on LC Phone charges. Only one source. [Unverified]
- Another source says phone is "Twilio pass-through without markup". Combined with the above, treat the exact margin as unclear.
- A2P 10DLC registration is required for US SMS. Reported costs: brand fee up to about $23.5 one-time plus $1.50 to $10.50 per campaign per month at low volume. Registration is **per sub-account** and takes about a week end to end in practice. [3rd-party]

**Email (LC Email)** [3rd-party]

- About $0.675 per 1,000 emails sent. Validation about $2.50 per 1,000.
- Dedicated IP $59/month.
- Whether LC Email is Mailgun underneath is disputed (one page contradicts itself). Historically a Mailgun integration was a "global integration" an agency could connect (listed in the agency role matrix: "Global Integrations e.g. Mailgun, Twilio Rebilling"). [Official-indirect]
- Custom conversation providers via marketplace apps can replace the default SMS/email provider (Twilio/LC Phone, Mailgun/LC Email). [Official, GitHub docs]

**AI pricing (official help article "AI Product Pricing", fetched)** [Official]

- Three modes per enabled location: **Pay-Per-Use** (no monthly fee, token cost), **AI Employee Growth** ($50/mo), **AI Employee Unlimited** ($97/mo, fair use).
- Growth includes 1,000 Conversation AI responses and 100 Voice AI minutes per month, usage for Ask AI and AI Studio, unlimited Reviews AI and Content AI. Overage at pay-per-use rates.
- Unlimited: unlimited Conversation AI, Voice AI, Reviews AI, Content AI and both Prompt Optimizers (fair use), 3x Ask AI and AI Studio allowance.
- **Agent Studio** is pay-per-use on every plan. **Managed Agents** metered in runs (100/month Growth, 1,000/month Unlimited, token cost on pay-per-use, 30 free test runs per location per month).
- Conversation AI pay-per-use is billed per 1M input/output tokens with a model menu (example: GPT-5 at $1.25 in and $10.00 out per 1M tokens; GPT-5 Mini at $0.25 / $2.00).
- **Voice AI pay-per-use** = voice engine ($0.045/min from May 20, 2026) + TTS ($0.015/min OpenAI or Cartesia; $0.035 ElevenLabs V2.5; $0.17 ElevenLabs V3) + LLM tokens + phone system charges. Speech-to-speech flat options: $0.10/min (Gemini live preview), $0.20/min (OpenAI realtime). Prompts capped at 15K tokens.
- Content AI: $0.063 per image, $0.0945 per 1,000 words. Reviews AI: $0.01 per AI-assisted reply sent (suggestions free). Workflow AI premium actions: $0.01 per execution (Decision Maker, Intent Detection, Summarize, Translate). Workflow Pro bundles: $10 (10,000 executions), $25 (30,000), $50 (65,000) per month.
- Free on all plans: Funnel & Website AI (1,000 prompts/day/location), Workflow AI builder, Email AI, Knowledge Base.
- Important line from the page: phone system charges still apply to all calls regardless of plan.
- Rebilling AI tiers to clients requires Agency Pro. AI Employee plan tiers can be selected inside the SaaS Configurator (own help article exists).

### 2.4 Wallet and credits model

- Usage is billed through a **prepaid wallet** per account. The agency has an agency wallet; SaaS-mode sub-accounts get their own wallet when rebilling is on. When the balance drops below a threshold, the card on file is auto-charged to recharge. Usage therefore never appears as a separate invoice. [3rd-party, consistent with official SaaS FAQ]
- Official SaaS FAQ gotchas: auto-recharge **fails with 3DS-only cards** (use a card that supports 3DS without requiring it, or manual recharge). **Disabling SaaS on a sub-account permanently deletes its wallet**; the balance is emailed to the agency and refunds/credits are manual. Idea-board bug: "Stop auto recharge when account is disabled" (63 votes). [Official]
- Rebilling mechanics: for each service (phone, email, AI) you set a **markup multiplier** per SaaS plan feature via a slider that shows agency cost, client price, and profit per $10. Bulk rebilling configuration across many sub-accounts overwrites existing markups. Rebilling goes live immediately for sub-accounts with a card on file; otherwise a customer profile is created at the payment provider and rebilling starts when a card is added. Bulk can enable; **disabling must be done per sub-account**. [Official, help article "SaaS Bulk Rebilling Setup"]
- Plan gate: rebilling **without markup** on Unlimited, **with markup** on Agency Pro.

### 2.5 Realistic monthly bill examples (3rd-party calculator, one source) [3rd-party]

| Scenario | Setup | Approx total |
|---|---|---|
| Solo operator | Starter, 1 number, 500 SMS, 2,000 emails | about $107/month |
| Agency | Unlimited, 10 numbers, 5,000 SMS, 20,000 emails, about $50 AI | about $412/month |
| SaaS agency | Agency Pro, 10 numbers, 10,000 SMS, 50,000 emails, AI Employee Unlimited on 10 sub-accounts | about $1,591/month |

Another agency source states most Unlimited agencies pay $370 to $450 per month all-in. A single business with one sub-account and moderate texting is about $110 to $150 per month.

### 2.6 Pricing insights worth acting on

1. The headline price ($97/$297/$497) is a customer-acquisition price. Real cost is usage, A2P fees, add-ons ($497 white-label app, $297 HIPAA, $59 IP, $500 premium support). Surprise-bill anxiety is a recurring review theme.
2. Plan gates are scattered: API depth, rebilling markup, SaaS mode, dedicated IP and per-sub-account Labs controls are all tier-gated in different places. Customers struggle to know "what do I get at which tier".
3. The AI pricing has already been re-cut multiple times in 2026 (per-minute rates, a "Voice engine" fee effective May 20, 2026, three-tier AI Employee). Pricing volatility is a trust problem for resellers who have promised clients fixed prices (a top idea on the board is fixed-rate AI rebilling).
4. The legally awkward items: HIPAA is non-cancellable and non-refundable once enabled and cannot be turned off per sub-account. [3rd-party, plausible; confirm]

---

## 3. Agency layer

### 3.1 Mental model: agency view vs sub-account (location) view

- **Company/Agency** = the paying HighLevel customer (an "agency"). Technically `companyId` in the API.
- **Sub-account / Location** = a client workspace with its own contacts, pipelines, funnels, workflows, calendars, phone numbers, reporting. Technically `locationId` in the API. Data is isolated per sub-account. [Official-indirect]
- Agency level cannot build funnels or workflows directly and does not hold contacts. It holds: sub-account roster, snapshots, billing, white-label settings, SaaS plans, agency-wide reporting, the marketplace, templates and prospecting. [3rd-party, consistent with official help]
- Users have two axes: **User Type** (Agency or Account) and **Role** (Admin or User). Account-type users are assigned to specific sub-accounts. An agency admin can "Login As" a user inside a sub-account. [Official]
- A feature must be enabled at sub-account level before user permissions can grant it. "A user cannot have more permissions than the sub-account level allows." For SaaS-mode sub-accounts, the sub-account feature set is dictated by the SaaS plan. [Official]

### 3.2 Sub-account creation

Official/3rd-party consistent flow:

1. Agency View > Sub-Accounts > Create Sub-Account.
2. Choose **blank** or a **snapshot** to pre-load.
3. Enter business details (name, address, time zone, etc.), optionally mark prospect/client and set features and limits.
4. Post-creation checklist (all manual): custom domain, buy a phone number, register A2P 10DLC, connect Stripe (per sub-account), connect social accounts, add users with restricted permissions, test forms/workflows/SMS/bookings.
5. Alternatives: auto-creation via **SaaS Mode** checkout, API (`POST /locations`), "Convert existing sub-account to SaaS plan", or bulk create via SaaS bulk enable.

Constraints and gotchas:

- Starter plan caps at 3 sub-accounts (the fourth client forces an upgrade).
- Transferring a sub-account between agencies requires support or a sub-account transfer request flow with specific permission (named permission "Sub-Account Transfers"). [Official]
- Deleting a sub-account is irreversible. Export contacts first. [3rd-party]
- Standard (non-SaaS) sub-accounts must be paused/resumed manually. [3rd-party]
- Bulk actions across sub-accounts are limited. Many tasks are still one-at-a-time. [3rd-party]
- Unused pause durations limited (up to about two months before support is needed). [3rd-party]

### 3.3 Snapshots

A snapshot is a reusable, agency-level blueprint of a sub-account's configuration, stored in the agency. [Official-indirect + 3rd-party detail]

**Included** (per a detailed 3rd-party guide that tracks HighLevel docs): workflows, AI features (Conversation AI, Voice AI, Agent Studio, Brand Voice), funnels, websites, blogs, forms, surveys, email templates, campaigns, Social Planner settings, calendars, pipelines, custom fields, custom values, custom objects, tags, dashboards and reports, memberships, knowledge bases, ad campaign setups.

**Not included:** contacts, appointments, conversations, reputation data, integrations and connected accounts (Stripe, social), phone numbers (including those assigned to Voice AI agents), private dashboards. WordPress sites transfer but need their license re-authenticated. Custom menu links are not included. Contacts must be moved separately (CSV or the "Copy Contact" workflow action).

**Sharing:** six share-link types: permanent, one-time, email-restricted, agency-restricted, sub-account-restricted, marketplace. Importing a share link only adds the snapshot to an "Imported Snapshots" tab; nothing changes in any sub-account until you **load** it. Marketplace listings default to "assets protected" (usable, not re-shareable or re-snapshottable).

**Loading:** Manage Client > Actions > Load Snapshot. A conflict list is shown, per asset choose Override or Skip, then type "confirm". Existing contacts remain.

**Updates:** "Refresh" creates a new snapshot version (version history exists). "Push Update" sends changes to selected sub-accounts and selected assets. Pushes only reach sub-accounts in your own agency; people you shared with must re-import. You can deselect hand-customized locations to avoid overwriting.

**Permissions:** Snapshot scopes per team member (view, create, edit, share/import, push, refresh, delete). Creating a sub-account from a snapshot needs Agency Admin.

**Known painful gotchas (3rd-party, matches idea-board demand):**

- Custom values transfer with their contents, so a previous client's name can leak into the next client's emails.
- Copying a single workflow strips references that cannot be mapped and lands it as a draft.
- An hour of manual post-load review is normal.
- There is **no rollback of a snapshot push**. The top-voted Snapshots idea (492 votes, Planned) is "Revert snapshot update like you have with bulk actions". Also: Global Smart List in snapshots (382 votes, In Progress), folders and sub-folders everywhere (242 votes), snapshot insights/history/audit logs (151 votes), backup of individual accounts (118 votes), ability to see which snapshots are tied to which sub-accounts (75 votes), ability to unlink a sub-account from a snapshot. [Official, ideas board]

Key insight: snapshots are HighLevel's core agency-leverage feature and also its weakest-engineered one (no diffing, no revert, no lineage, no drift detection). That is a design opening (see section 9).

### 3.4 SaaS Mode and the SaaS Configurator

Gate: **Agency Pro ($497)** and up. [Official]

Two architectures coexist (official help "Getting Started with the SaaS Configurator"):

| | SaaS V1 | SaaS V2 |
|---|---|---|
| System of record | **Stripe** (agency-level connection) | An **Agency Sub-Account** with a supported payment provider |
| Providers | Stripe only | Stripe, NMI, Authorize.net, Square |
| Setup | Agency View > Settings > Stripe, then import Stripe product/price into the selling sub-account, add to funnel order form | Select an Agency Sub-Account in SaaS Configurator > Configure; select products from that sub-account's Payments and funnel tools |
| Plan changes | Monthly and annual switchable; sync to Stripe for eligible subs | Same-interval only (monthly to monthly, yearly to yearly) |
| Migration | None. V1 and V2 can run side by side. A sub-account uses one mode at a time. |

Plan configuration (official + 3rd-party): categories (shared currency, define upgrade/downgrade paths), plans with at least one feature, pricing (monthly/annual), **trial or credits**, **snapshots attached to plans**, add-ons, **marketplace apps resold as plan items**, usage billing and **rebilling per service with markup**, user limits per sub-account, manual-approval pause for new sub-accounts, custom values via Advanced Settings, naming conventions for new sub-accounts, onboarding email customization, automatic tax via Stripe, currencies other than USD, special per-client prices, 2FA enforced for new SaaS sub-accounts, and a "Copy Sale Link" checkout link. A bulk manage screen exists, and there is a public SaaS API (below).

Customer flow: after checkout (funnel order form or sale link), a sub-account is created or linked, the attached snapshot is loaded, and the subscription becomes active or trialing. Existing sub-accounts can be converted ("Switch to SaaS") and sit "On Hold" until a payment method is added.

Official SaaS FAQ constraints worth noting for design:

- Email verification is mandatory for new SaaS sub-accounts. Phone verification is the only verification that can be disabled. Pending verification does not block access but is required before the first phone number purchase.
- Each sub-account needs its **own Stripe Customer ID**. Shared IDs cause card changes to cascade across sub-accounts.
- Disabling SaaS cancels the subscription and permanently deletes the wallet.
- Currency cannot change while sale links or active subscriptions exist.
- Custom values must be set in the configurator, not edited directly in sub-accounts.
- Test-mode purchases do not create sub-accounts.
- Default welcome email subject "Activate your account".

Public SaaS API [Official help]: `GET /saas/agency/plans`, `GET /saas/location/{locationId}/subscription`, `POST /saas/bulk-enable`, `GET /saas/agency/sub-accounts`, `GET /saas/agency/plan/{planId}`. OAuth `saas/*` scopes, and a **10 requests per second** rate limit on these endpoints. **Plans can only be read through the API; creating or deleting them requires the UI.**

Top SaaS-mode ideas (board): **multiple brands with different price/features under one agency (944 votes, Planned)**, customize Launchpad (412, In Progress), use company name for new SaaS location (293, Planned), stop auto recharge when account disabled (63, bug), double opt-in for EU users (56). [Official]

2026 additions seen in changelog/roundups: enable/disable features for multiple sub-accounts at once (Oct 14, 2026), usage dashboard, white-label client portal domain, snapshot marketplace and selling marketplace snapshots with SaaS plans, fixed-rate AI rebilling and multi-brand white labeling (study claims). [Official + 3rd-party]

### 3.5 White label

Agency Settings > Company has three tabs: Basic Details, **Whitelabel**, Advanced Settings (official help "Agency Company Settings", fetched). [Official]

**Basic Details:** company name, email, phone, website, business category/niche, usage type (agency vs direct business), address, time zone. Feature toggles: AI Employee, Workflow AI, auto-complete address, LC Premium Triggers & Actions, Domain Purchase, Template Library.

**Whitelabel tab:**

- Logo (recommended 350x180 px, max 2.5 MB) used on login screen, app header, notification emails, some widgets and form footers.
- **No agency-wide favicon**. Favicons are set per asset (funnels/sites, client portal, course site theme). A real gap.
- **Whitelabel Domain**: branded domain for the desktop login portal (removes HighLevel branding from client login).
- **API Domain**: branded domain for system-generated links (tracking links in SMS/email), configurable at agency and sub-account level.
- Privacy Policy URL and Terms URL (required for compliance on most public widgets).
- **Custom JavaScript** and **Custom CSS** fields. HighLevel states these are **unsupported** and core UI updates can break them. Safe areas: login page, sidebar, header bar, form widgets, funnel/site CSS panels. Avoid: mobile apps, React pop-ups such as payment modals, back-end PDF invoices/receipts, the core drag-and-drop builder, elements without stable classes. Fonts and color themes are only possible through custom CSS.
- **Theme selection:** Light or Dark for the **agency-level dashboard only**. Sub-account dashboards are not affected.

**Advanced Settings:** preloaded example data (personal booking calendar for new users), **Enhanced Account Security** (stops auto-generation of legacy API keys and restricts CRUD on sensitive endpoints), **session timeout** (15 min to 3 days or never), "Optimize Experience" toggles (NPS surveys, product guides, daily updates) and Beta Features.

**Custom menu links** (Settings > Custom Menu Links, requires "Manage Custom Menu Links" permission): icon, title, URL (http/https, supports merge fields for location and custom values), open as **embedded iframe**, **new browser tab** or **current tab**; visible in agency sidebar, sub-account sidebar (for chosen accounts), or both; role visibility All/User/Admin; drag to rearrange. Gotchas: destinations sending `X-Frame-Options`/`frame-ancestors` render blank in iframe; after white-labeling, the embedding origin changes, which breaks allowlists; merge-field parameters identify but do not authenticate (there is a separate "Client Portal SSO Magic Links" feature); links are **not in snapshots** and must be assigned per sub-account or attached to a SaaS plan; renaming a custom value breaks a link; more than about five custom items is a menu problem. Sub-accounts cannot create their own links. Idea board has "Custom menu links in mobile app" (148 votes) and "ability to reorder menu items" (built-in items cannot be natively reordered; a CSS workaround circulates). [Official + 3rd-party]

**White-label mobile app** [Official help "How to Promote and Customize Your Whitelabel Mobile App"]:

- Agency View > Mobile App > Customise App. Self-serve customizer: app name, logo, primary color, font, light/dark splash screens, login screen content, top/bottom nav modules (add/remove/reorder), app drawer modules, custom modules (title, URL, icon, in-app or browser, account selection, role-based visibility).
- Requires a HighLevel **Custom Agency App** subscription ($497/month add-on, included in Enterprise), an **Apple Developer Program Organization account with a D-U-N-S number**, and a **Google Play Console Organization account**. Connect both stores under Distribution > Channels. Store profile under Distribution > Profile. Build via Launch App, keep package/bundle IDs stable after first production release.
- Fully branded **Client Portal app** for end customers (courses, community, resources, push notifications): $49/month/location introductory price, opt-in form required, no coding.
- Mobile v4.0.0 redesign: App Drawer replaces left menu (4-column grid, groups Insights & Productivity, Communication, Sales & Operations, Marketing & Growth), true-black dark mode, homepage widgets, universal search (conversations, contacts, opportunities). Applies to the HighLevel app, the LeadConnector app and white-label apps; existing customizations may break; enabled via Labs (Agency Settings > Labs > Subaccounts). [Official]

### 3.6 Agency reselling beyond SaaS mode

- Resell **add-ons** inside SaaS plans (AI Employee tiers, WhatsApp, listings, SEO, WordPress hosting, Ad Manager, domains) and **marketplace apps and snapshots** as plan items. Developers' apps can be sold per sub-account or usage-based; HighLevel invoices the agency and remits revenue share to the developer. [Official]
- Agencies can run **their own affiliate program** for SaaS customers (Affiliate Manager). Agency users cannot pay affiliate payouts unless granted the "Pay Affiliate Manager Payout" permission (on by default for Agency Admins). [Official]
- **Template Library** and **snapshot marketplace**: share funnels/sites/templates, sell or distribute snapshots. [Official]
- Prospecting tool: free vs premium ($29/month per sub-account) for lead lists and local marketing audits. [Official]

### 3.7 HighLevel as affiliate/partner target (their own program)

See section 1.5. Also "Official Premium Support" ($500/month) and the "Enterprise" tier.

---

## 4. Platform and settings

### 4.1 Users, roles, permissions

[Official, help articles 155000002543 and 48001078296]

- **Agency-level:** User Type = Agency or Account; Role = Admin or User. There is also an implicit **Agency Owner** with special rights (transfers, ownership), not selectable as a role in the article.
- Agency users are managed at Agency View > Settings > Users (Team). Sub-account users at Settings > My Staff.
- **Granular permissions** exist on top of role: you turn off whole **modules**, then configure granular flags inside enabled modules. Documented module permission areas: AI Agents, Account Settings, Account Tools, Automation, Blogs, Calendars, Certificates, Communities, Contacts, Conversations, Dashboard, Forms, Funnels, GoKollab, Integrations, Launchpad, Marketing, Media, Memberships, Opportunities, Orders, Payments, Payment Settings, Products, QR Codes, Quizzes, Reputation, Subscriptions, Sub-Account Transfers, Surveys, Taxes, Transactions, WordPress.
- Named granular permissions: Pay Affiliate Manager Payout, Enable Login As, Create Sub-Accounts and Delete, View & Manage (Forms/Surveys/Quizzes/QR Codes), Export data (Dashboard), **Only Assigned Data**, View & Manage Users / View Users (user-management API), Sub-Accounts List Page, Manage Client Page (Basic Details), Sub-Account Billing, Sub-Account Company Settings. Separate articles exist for granular permissions for Payments, Snapshots, WordPress, Calendars, Pipelines, Dashboards, Voice AI agents, Conversation AI agents, WhatsApp, Loyalty & Referral, Gift Cards, and Developer users.
- Roles stack: a user with an agency role and an account role has both, the broader agency permissions take precedence.
- **Assigned data visibility:** "Only Assigned Data" limits records to those assigned to the user (contacts, opportunities, conversations, tasks).
- Enhanced Security mode restricts some API-based user management.
- **Gaps visible on the ideas board:** the top Users and Permissions idea is "Granular Permissions at the Agency Level for Agency Admins/Users" (**1.2k votes**, In Progress). Others: merge contacts (166), field-level lockable custom fields (106), "Allow user to see only assigned data AND unassigned data" (96), enterprise-grade field-level / record-level / resource-level access control (1 vote, but notable as the enterprise gap), teams, sub-teams and group-based permissions (1 vote).
- No real RBAC with named custom roles reusable across sub-accounts is documented as a first-class object; permissions are set per user. (Third-party guides claim "custom roles". The help article lists only Admin and User.) [Official wins; verify in a trial]

### 4.2 Teams and "Login As"

- "Login As User" is an agency-admin-only feature, controlled by the permission "Enable Login As". Used heavily for support and for demos. [Official]
- The idea board shows "teams and sub-teams" as a 1-vote request, which suggests real team entities do not exist (assignment is to individual users plus round-robin in calendars).

### 4.3 Business profile, custom fields, values, tags, objects

- **Business profile** (Settings > Business Profile): name, address, logo, time zone, branding fields used in invoices, email footers, and for A2P registration. [Background]
- **Custom Fields** (contact-level and opportunity-level, with folders) and **Custom Values** (global key-value merge fields per sub-account used in templates). **Tags** (flat labels used for segmentation and workflow triggers). **Smart Lists** (saved filters on contacts). [Background; custom values referenced by SaaS and menu-link docs]
- **Custom Objects and Associations** (official help article, Nov 2025): available on all plans per the article, limit **10 custom objects per location**, up to **10 unique fields per object**, unique types limited to single-line text, multi-line text, number and phone. Associations and labels link objects; there are webhook events for ObjectSchemaCreate/Update, RecordCreate/Update/Delete, RelationCreate/Delete, and Association events. Idea board: "Assign multiple companies to a single contact" (383 votes, In Progress) shows the **Company** object is thin. [Official]
- Basic math operations in dashboards (399 votes, In Progress), custom fields in dashboards (86) and "add all GHL data as dashboard widgets" (279) signal reporting depth is a recurring pain.

### 4.4 Integrations

- Native integrations include Stripe, PayPal, NMI, Authorize.net, Square, Adyen, Razorpay (payments), Google (Calendar, Business Profile, Ads, GA4), Meta (Facebook/Instagram/WhatsApp, Ads), Zapier, Make, n8n, Calendly import, Shopify, Xero, LinkedIn Ads, TikTok etc. One comparison claims "about 500 integrations" versus HubSpot's 2,000+. [3rd-party]
- Gmail/Outlook two-way sync is a long-running request area (230 votes for excluding domains and contacts from sync). [Official]
- Private Integrations (a Settings page, behind a Labs flag originally) for PIT tokens. Marketplace apps for OAuth installs.

### 4.5 Audit logs, security, compliance

- **Audit Logs** [Official help article, fetched]: time-stamped records with user, module, action; entries cover users, accounts, contacts, settings; drawer shows **field-level before/after values**; deleted page-builder assets logged; Conversation AI activity logged; filters by user, module, action type (create/update/delete) and time range. **Retention is 60 days**, then purged. Viewable by Agency Admins at Agency > Settings > Audit Logs and by account admins at sub-account level. **CSV export** is async (Exports tab). Module-specific audit logs exist for funnels/websites/stores, custom objects, listings entity history, email preferences, WhatsApp, WordPress access/activity, AI action logging and Voice AI agent logs. Gap: 60-day retention is short for SOC 2-style evidence.
- **2FA** [Official help + ideas board]: authenticator-app (TOTP) support exists (Google/Microsoft Authenticator, Authy), 10 one-time backup codes, set up under Settings > My Profile > Security, only the user can set up their own (admins cannot via Login As). Email and SMS codes are the older methods. The idea "Allow more 2FA options" (294 votes) has been Planned since 2023 and asks for passkeys, security keys, agency-enforced policy, and sub-account-admin-enforced policy. New SaaS sub-accounts can be forced to set up 2FA on first login. Mandatory 2FA exists for phone number updates and "phone number change security alerts and reversal" are new 2026 articles. **No documented agency-wide 2FA enforcement policy.** [Official]
- **SSO:** I found no documented SAML/OIDC SSO for HighLevel staff or agency users. What exists is **"Client Portal SSO Magic Links"** (one-click access from the portal to client apps). Treat enterprise SSO as an absent or enterprise-only capability. [Official title only; unconfirmed depth]
- **Session timeout** setting (15 min to 3 days or never). [Official]
- **HIPAA** [3rd-party detail]: $297/month agency-level add-on, covers unlimited sub-accounts, non-cancellable and non-refundable, cannot be turned off for a sub-account once enabled, BAA signed in Documents & Contracts under Settings > Compliance, then per-sub-account HIPAA toggle (Advanced Settings). When on: AES-256 at rest, TLS 1.2+, audit logging, mandatory 2FA, idle logout, database isolation from non-compliant sub-accounts; migrating an existing sub-account can cause 24 to 48 hours downtime. BAA covers only HighLevel's own infrastructure, so integrations (Zapier, Slack, etc.) need their own BAA. Intake forms are safe only if HIPAA was on before data collection. The pricing page lists HIPAA as included in Enterprise.
- **GDPR / data residency:** Ideas board has "Data residency" and "HIPAA Compliance" categories. I did not find an official GDPR product page, DPA workflow, or EU data region. Idea-board "For European Users: Double Opt-In" (56 votes) implies consent tooling is partial. [Unverified; plan to verify]
- **Enhanced Account Security** agency toggle: disables legacy API key auto-generation and restricts CRUD on sensitive endpoints. [Official]

### 4.6 Labs (feature flags)

[Official help "Labs Features - Complete Overview"]

- Path: Agency View > Settings > Labs (tabs: Agency and Sub-account) and Sub-Account View > Settings > Labs. Early-access toggles with card format (title, description, release estimate, toggle, feedback link). Anyone with "View & Manage Settings" can access Labs.
- Agency-level: Agency Owners/Admins enable agency features. Sub-account level: sub-account admins or agency users.
- **Per-sub-account assignment (visibility and enablement) is available on Unlimited and Pro**; Starter shows features visible by default with no per-sub-account control.
- Real examples of Labs-gated features seen in docs: Private Integrations section, Global Search V2 (Cmd/Ctrl+K, searches 530+ routes and records across 8 products with voice commands), Mobile v4 (until Dec 31, 2025), various AI and workflow betas. This means **core platform surfaces regularly ship behind Labs flags**, including things developers need (Private Integrations).
- Design takeaway: feature flags are exposed to customers as a product surface, which creates "my screen differs from the tutorial" support load.

### 4.7 URL redirects, domains, email and phone services

- **Domains:** Whitelabel (app) domain, API domain (tracking links), per-funnel/site custom domains (Settings > Domains), domain purchase add-on. Email sending domains need SPF/DKIM/DMARC setup. [Official + 3rd-party]
- **URL redirects:** Funnels/sites have a redirect manager; API exposes `funnels/redirect.readonly` and `funnels/redirect.write` scopes (create/update/delete redirects). [Official, scopes]
- **Trigger links** are tracked short links used in workflows (API group "Trigger Links", scope `links.*`). [Official]
- **Email services:** LC Email (default), dedicated sending domain/IP ($59), SMTP integrations (Mailgun, SendGrid, custom SMTP) as alternatives, custom conversation providers via marketplace. Deliverability is the #1 technical complaint (section 6). [3rd-party + Official]
- **Phone services:** LC Phone (Twilio-backed default), bring-your-own Twilio, A2P 10DLC "Trust Center" per sub-account, toll-free verification, call tracking/whisper/voicemail, WhatsApp via Meta, RCS via Twilio (2026), custom call providers that log calls but do not replace SIP/voice. [Official + 3rd-party]

---

## 5. Developer platform

### 5.1 API v2: structure

- Base: `https://services.leadconnectorhq.com`. Docs live at `marketplace.gohighlevel.com/docs`; the OpenAPI-based source docs are public at **github.com/GoHighLevel/highlevel-api-docs** (CC0 license, 153 stars, 76 forks, 79 open issues, 89 commits; folders `apps/v3`, `docs`, `models`, `common`, `toc.json`). The repo README points issues at a different repo name (`api-v2-docs`), a small sign of docs drift. [Official]
- Versioning is via a **`Version` header** (a dated string such as `2021-07-28` or `2021-04-15`; docs site keeps several dated doc versions). A `traceId` is returned with every response for debugging. [Official + 3rd-party]
- **API v1 is deprecated** (official post, June 26, 2026): no security patches, bug fixes or features; support will no longer troubleshoot v1; **new v1 API keys can no longer be generated**; existing integrations continue "for now". Some third parties report an end-of-support of Dec 31, 2025 and a shutdown date of Nov 30, 2026 (not confirmed officially). A "Enhanced Account Security" toggle also stops legacy key generation. [Official + Unverified]
- Documented API groups in `toc.json`: Country List, Businesses, Calendars, Campaigns, Companies, Contacts, Objects, Associations, Custom Fields V2, Conversations, Courses, Emails, Forms, Invoices, Trigger Links, Sub-Accounts (Locations), Media Library, Marketplace, Blogs, Funnels, Opportunities, Payments, Products, Store, SaaS, Snapshots, Social Planner, Surveys, Users, Workflows, LC Email, Custom Menus. Docs sections: OAuth 2.0, APIs, Webhook Events, Custom JS. [Official]

### 5.2 Authentication

1. **OAuth 2.0 authorization code flow** for Marketplace/multi-account apps. Two authorization URLs exist: standard and a **white-labeled** one. Admin picks a location (or installs agency-wide/bulk), browser redirects with `code`, app exchanges for tokens. **Access token life about 1 day. Refresh token valid 1 year if unused; each refresh issues a new refresh token (rotating).** Resources are **Company-level** (agency) or **Location-level** tokens; agency tokens can mint location tokens (a known pattern). [Official]
2. **Private Integration Tokens (PIT)** for internal tools: static token generated in the UI, used like an access token in the `Authorization` header; scopes chosen at creation and editable later without changing the token; shown **once**; recommended rotation every 90 days with a **7-day dual-valid window** ("rotate and expire later") plus an immediate-rotate option for compromise; created by agency admins by default, restrictable under Settings > Team > Roles & Permissions to agency integrations, sub-account integrations or both; feature may require enabling in Labs. Available at both agency and sub-account level. [Official, fetched]
3. **Legacy API keys (v1)**: deprecated, generation disabled. 

### 5.3 Scopes

The public repo documents these scope families (all `*.readonly` and/or `*.write` unless noted) [Official-indirect, `docs/oauth/Scopes.md`]:

- businesses; calendars (plus `calendars/groups`, `calendars/resources`, `calendars/events`); campaigns (readonly); contacts; objects (`objects/schema`, `objects/record`); conversations (plus `conversations/message`, `conversations/livechat.write`); forms (readonly); invoices (plus `invoices/schedule`, `invoices/template`); links; locations (plus `locations/customValues`, `customFields`, `tags`, `templates.readonly`, `tasks.readonly`); medias; funnels (`funnels/redirect`, `funnels/page.readonly`, `funnels/funnel.readonly`, `funnels/pagecount.readonly`); opportunities; payments (`payments/integration`, `payments/orders`, `payments/transactions.readonly`, `payments/subscriptions.readonly`); products (plus `products/prices`); oauth; **saas** (`saas/location.read`, `saas/location.write`, `saas/company.write`); snapshots (readonly); socialplanner (account, csv, category, oauth, post, tag); surveys (readonly); users; workflows (**readonly**); courses (write); emails (`emails/builder`, `emails/schedule.readonly`); blogs (post, post-update, check-slug, category, author, posts, list).
- **Note the asymmetry:** workflows are read-only via API. Funnels and sites are mostly read-only (pages count, funnel list, redirects). There is **no API to create or edit workflows, funnels, websites, email sequences or reputation settings.** The ideas board confirms: **"Become An API First Company" is the most-voted API idea at 1.0k votes** (anything the GUI can do should be doable by API; commenters say they build off-platform workarounds and report it going unreviewed for 2.5 years). Also "API to create workflows" (126), "create funnels and workflow automations through API" (89), "API for website builder" (60), "Workflow API enhancement" (35), "API endpoint for reputation management" (20), "API access for email sequences" (10). [Official, ideas board]
- Scope granularity is decent for CRUD resources but there is no resource-instance scoping (for example "this pipeline only") and no field-level scopes.

### 5.4 Rate limits

[Official, `docs/oauth/Faqs`, `Authorization`]

- **Burst: 100 requests per 10 seconds. Daily: 200,000 requests.** Per **Marketplace app, per resource (Location or Company)**. Usage reported in `X-RateLimit-*` response headers. Higher limits for Enterprise on request (pricing page).
- SaaS Configurator endpoints: **10 requests per second** global limit. [Official help]
- Implication: per-resource limits scale with installs, but bulk reads of a large contact base hit the 100/10s burst cap quickly (the MCP guide warns about this).

### 5.5 Webhooks

[Official, `docs/oauth/WebhookAuthentication`, Webhook Integration Guide, repo `docs/webhook events`]

- Two kinds: **app webhooks** configured on a Marketplace app (events for installed locations) and **workflow "Custom Webhook" actions / inbound webhook triggers** inside a sub-account. The workflow inbound webhook trigger has an open request for **native HMAC signature verification** (1 vote).
- **Signing:** `X-GHL-Signature` (**Ed25519**, current) and legacy `X-WH-Signature` (RSA-SHA256), the legacy header **scheduled for deprecation on Sept 1, 2026**. Replay protection advice: accept only timestamps within about 5 minutes and reject repeated webhook IDs. The public key is published in docs and rotated with announcement.
- **Retries:** any non-2xx or no response triggers retries with **exponential backoff and jitter, up to 12 retries**; retries stop on any 2xx. A Webhook Logs dashboard allows a manual resend of the latest undelivered attempt; a successful manual retry cancels scheduled ones.
- **Event types in the repo (about 70 documented):** AppInstall, AppUninstall, Appointment (Create/Update/Delete), Association (Create/Update/Delete), CampaignStatusUpdate, Contact (Create/Update/Delete/DndUpdate/TagUpdate), ConversationUnreadWebhook, InboundMessage, OutboundMessage, ProviderOutboundMessage, Invoice (Create/Update/Delete/Sent/Paid/PartiallyPaid/Void), LCEmailStats, Location (Create/Update), Note (Create/Update/Delete), ObjectSchema (Create/Update), Opportunity (Create/Update/Delete/AssignedToUpdate/MonetaryValueUpdate/StageUpdate/StatusUpdate), Order (Create/StatusUpdate), PlanChange, Price (Create/Update/Delete), Product (Create/Update/Delete), Record (Create/Update/Delete), Relation (Create/Delete), Task (Create/Complete/Delete), UserCreate. Categories cover contacts, opportunities, tasks, appointments, invoices, products, associations, locations, users. [Official-indirect]
- **Gaps:** no events listed for forms submitted, workflow executed, pipeline changed, calendar changed, funnel/page published, payment failed (outside invoices/orders), review received, call completed (events like these exist only as workflow triggers). The practical advice in the ecosystem is "use a workflow with a custom webhook action" for the missing ones. [Official-indirect + inference]

### 5.6 Marketplace

[Official, `docs/oauth/AgencyVsSubAccount`, `AppReviewGuidelines`, `Billing`, `ConversationProviders`, `CustomJs`]

- **App types:** **Standard** (listed in the Marketplace, may mention HighLevel factually) and **Whitelabel** (must remove all HighLevel/GHL branding from every user-facing surface and use terms like CRM, LeadConnector, business account). Install types must support **account (location) install, bulk install, and SaaS automated install**. Apps default to Private while developing.
- **Module types:** OAuth apps with scopes and webhooks; **Custom JS** (inject scripts into the HighLevel app via an `AppUtils` wrapper: `Storage` with 5KB caps and `custom_` key prefix, `RouteHelper`, `Utilities.getCurrentUser/Location/Company`, `routeLoaded` and `routeChangeEvent` events); **Custom Pages** (embedded iframe pages in the sidebar with a shared-secret handshake for identity); **Conversation Providers** (custom SMS/Email/Call providers, can replace the default Twilio/LC Phone and Mailgun/LC Email); workflow custom actions/triggers; external authentication; app billing.
- **Review requirements:** Loom demo mandatory; HTTPS and verified domain redirect URLs; minimum scopes with justification; no secrets client-side; first-response support within **24 hours** by email/phone; clear uninstall/disconnect and call the Uninstall API; prohibited: sub-marketplaces, data harvesting, duplicates, impersonation, hidden costs. Embedded apps must be responsive, validate the parent frame, avoid horizontal scrolling and not override parent navigation. HighLevel may delist for complaints or security issues.
- **Distribution/billing:** agencies buy third-party apps **per sub-account** or **usage-based**. HighLevel invoices the agency, collects, and remits revenue share per agreed terms; the developer's contract is with HighLevel, not the agency. Revenue share percentages are not public. Alternative: **external billing** (developer processes payment, then reports each payment per location/company via a billing webhook with `authType`, `amount`, `status` COMPLETED/FAILED, `paymentType` one_time/recurring; no batch, one call per location). Apps can be resold as part of SaaS plans.
- Listing counts: an aggregator showed 1,273 listings and 352 ISV partners (Oct 2025). [3rd-party, dated]
- Marketplace has an "App Marketplace" board on ideas for new app requests.

### 5.7 Custom JS, SDKs, and other developer surfaces

- **Custom JS / CSS in agency settings** (white-label section) and **in funnels/sites** (header/footer code, custom code blocks). Unsupported and brittle, as HighLevel itself warns.
- **Custom Menu Links** (iframe) plus **Custom Pages** and the **Custom Menus API** group.
- **Official SDK:** I found **no official first-party SDK** mentioned in the repo README or docs index (an `npm` `package.json` exists in the docs repo for tooling). Community SDKs and Postman/OpenAPI usage exist. [Official absence + Unverified]
- **Webhook logs dashboard** and **Loom-based review process** are the main developer tooling. There is no first-class CLI, local tunnel, sandbox environment, or test harness advertised. The docs repo has 79 open issues, which signals the docs backlog.

### 5.8 MCP server (official)

[Official, `marketplace.gohighlevel.com/docs/other/mcp` fetched; confirmed by two third-party guides]

- Hosted remote MCP at `services.leadconnectorhq.com`, with client-specific endpoints: `/mcp/anthropic/v2` (Claude.ai custom connector, Claude Code, Cowork), `/mcp/openai/v2/` (ChatGPT developer mode and plugin, Codex CLI/IDE, Streamable HTTP clients), `/mcp/muse/v2/` (official **Muse** app; there is also a "Connect HighLevel MCP to Muse" help article). Legacy `/mcp/` bare endpoint uses a **PIT bearer token plus a `locationId` header** (for Cursor, Windsurf and other HTTP clients). [Official]
- **Auth:** OAuth sign-in, you choose the sub-account(s) to expose, approve scopes, revocable from your LeadConnector account.
- **Four unified tools only:** `list_locations`, `search_operations`, `describe_operation` (inputs, example payloads, required scopes, safety info), `execute_operation`. This is a "search then execute" meta-tool design over **550+ active operations across 38 domains**, avoiding the context blowup of 550 individual tools. Sensitive/irreversible operations require extra confirmation and safety checks. [Official]
- **Limits:** each request targets **one sub-account**; agency connections spanning multiple sub-accounts are "rolling out" and require the multi-sub-account bulk install option; same API rate limits apply (100/10s, 200k/day); no MCP fee, but messages/calls sent through it bill at normal wallet rates. Prompt-injection caveat: inbound contact messages are untrusted content that could steer an assistant with edit scopes. [Official + 3rd-party]
- HighLevel is also an **MCP client**: Agent Studio and Super Agents can call external MCP servers; workflows and Voice AI agents can use MCP tools. [Official]
- Community MCP servers (for example "mastanley13-gohighlevel" with 250+ tools) exist and predate the official one. [3rd-party]

### 5.9 Other 2026 developer-relevant product changes

- **AI Studio** (help article "AI Studio in HighLevel"): conversational builder (prompt to websites, landing pages, dashboards, storefronts, forms, booking pages), visual edits, a built-in code editor, version history with revert, SEO support, preview domain then custom domain, cloning within or across sub-accounts, sharing via snapshots, usage measured in 5-hour windows, permissions "View AI Studio" and "View & Manage AI Studio". Oct 2026 changelog adds **Git Sync with GitHub**, native live chat widgets, and checkout/payments upgrades. [Official]
- **Agent Studio** (flow agents with nodes: LLM, MCP, API, Knowledge Base, Web Search, Router, AI Agent node; staging then production versions; test tab) now being superseded for new builds by **Super Agents** (natural-language, conversational agent builder, same engine, scheduling via cron, MCP connectors, CRM event triggers). Official pages disagree about whether new flow agents can still be created (one FAQ says no). [Official, with inconsistency]
- Global Search V2 (Cmd/Ctrl+K), Ask AI multi-threading and scheduled prompts, "Standard vs Advanced" workflow builder default switch, spreadsheet view for bulk product editing, accessibility enhancements for topbar and help drawer (the last is notable: accessibility work is a 2025-2026 theme).

---

## 6. UI/UX, design language, and reviews

### 6.1 Navigation structure

**Sub-account (location) left sidebar.** The default order I could corroborate (an old HighLevel idea-board post plus the modern permission-module list) is:

1. Launchpad
2. Dashboard
3. Conversations
4. Calendars
5. Contacts
6. Opportunities
7. Payments
8. AI Agents (newer, 2025-2026; grouped around Agent Studio / Conversation AI / Voice AI)
9. Marketing (social planner, emails, ads, affiliate manager, brand boards, snippets)
10. Automation (workflows)
11. Sites (funnels, websites, blogs, forms, surveys, quizzes, stores, WordPress, AI Studio)
12. Memberships (courses, communities, certificates, client portal; the product formerly marketed as ClientClub and now sold as Memberships/Courses/Communities)
13. Media Storage
14. Reputation
15. Reporting
16. App Marketplace (and then **custom menu links**)
17. Settings (gear icon, bottom-left)

Confidence: the order of the first 11 items is Official-indirect and consistent; AI Agents, Memberships, Media, Marketplace positions are [Background] and should be verified in a trial account. The idea-board shows built-in items **cannot be reordered natively** (reordering is requested; CSS hack exists), only custom links can be dragged.

**Agency view left sidebar** (from help articles, permission modules and third-party guides, [Background + 3rd-party]; exact order to verify): Launchpad, Dashboard, **Sub-Accounts**, **Account Snapshots**, Marketplace/Template Library, Partners/Affiliate Portal, Prospecting, Mobile App (white-label app customizer), Reporting, then agency **Settings** (Company, Team/Users, Billing, Stripe, Labs, Audit Logs, Private Integrations, Custom Menu Links, Phone/Email integrations, SaaS Configurator in the sidebar when SaaS is enabled).

**Settings** (sub-account): Business Profile, My Profile, Company Billing, My Staff, Opportunities & Pipelines, Calendars, Phone Numbers (incl. Trust Center/A2P), Phone Integration, Email Services, Domains, Custom Fields, Custom Values, Tags, Integrations, Private Integrations, Labs, Audit Logs, Compliance, Conversation AI, Voice AI, Reputation, Brand Boards. [Background]

**Top bar and utilities:** global search (V2 with Cmd/Ctrl+K), Ask AI assistant, help drawer, notification bell, location switcher, "quick actions" (+). Workflow builder has a toggle to show or hide the standard sidebar (Cmd/Ctrl+\\ in a June 2026 changelog). [Official-indirect]

### 6.2 Design language and theming

- Two layout themes in the web app: **Standard** (legacy navigation) and **Pro** ("modern SaaS-style", streamlined sidebar/header, saves screen space). Display modes Light, Dark, System/Auto. Branding can apply at user-profile or account level; agency admins can apply one brand across sub-accounts. [3rd-party, one source]
- Official white-label docs, however, say the agency-level **Light/Dark theme toggle affects the agency dashboard only**, not sub-accounts; colors and fonts beyond the logo require **custom CSS**. So dark mode is partial and theming is a hack layer, not a token system. [Official]
- Dashboard: unlimited custom dashboards per sub-account; widgets as counters, donut, line, bar, table; "date property" (created, updated, status change), widgets for Meta, Google Ads, GA4, reputation; hover **widget-level AI summaries**; quick filters panel; edit mode with drag and drop; clone and set default dashboard. Weak spots on the idea board: no math operations (399 votes), custom fields not usable in dashboards (86), not all GHL data available as widgets (279), reviews widget missing (83). [Official + 3rd-party]
- Builders: funnel/website builder has a **revamped right sidebar** (General, Styles, Animations tabs, Sept 2025), auto-hierarchical drag/drop layout; email builder with new block types; workflow builder offers **Standard vs Advanced** builders plus Workflow AI (describe a workflow in English); node-based visual canvas for Agent Studio.
- Accessibility work appears in 2025-2026 (topbar and help drawer enhancements). [Official]
- Observed style (from screenshots in YouTube/blog ecosystem, [Background]): blue-purple primary, dense cards, many modals, dropdown-heavy forms, inconsistent component styles between modules (older Vue modules vs newer ones), React pop-ups mixed with Vue pages (the official docs themselves refer to Vue instance lifecycle and "React pop-ups such as payment modals"), which is why custom CSS breaks.

### 6.3 Mobile apps

- **LeadConnector app** (the white-labelable engine) and the **HighLevel app** (branded). iOS and Android. Features: unified inbox (SMS, email, social DMs, WhatsApp), calls via LC Phone, contacts, opportunities (Kanban), calendar, push notifications, payments (mobile terminal on iOS), Mobile v4.0.0 redesign (app drawer, dark mode, universal search). [Official]
- **White-label mobile app** per agency ($497/month) and **branded Client Portal app** ($49/month/location) for end customers. Requires org-level Apple and Google developer accounts (D-U-N-S).
- Sentiment: reliability is the main complaint. iOS reviews summarized by aggregators cite crashes at startup and in use (including after updates), failed loads and notification glitches; a customer on the ideas board reports missed lead calls because the app stops ringing until reinstalled (9 votes); a reviewer says desktop-completed tasks do not sync until logout/login; navigation feels slow. One affiliate agency also lists "white-label mobile app has documented issues including call crashes". Idea board top mobile asks: **direct SIM card integration** (418 votes), **custom menu links in mobile app** (148), **custom objects in mobile app** (99), retain filters on opportunities (71). [Official ideas + 3rd-party]
- "ClientClub" was the name of the community/memberships product line before consolidation under Memberships (courses, communities, certificates, client portal). I found no current "ClientClub" documentation, so assume it is legacy naming. [Unverified]

### 6.4 Performance and reliability

- Load speed is mentioned in competitor-authored pieces. G2 reviewers mention occasional lag and freezes. There is no systematic measurement available publicly. [3rd-party, low]
- Status and outages: third-party monitoring counts about 121 outages since June 2025 (Pingoru) or "50 incidents in 90 days with median duration 4 minutes" (agency blog). Examples in June 2026: June 3 Smart Lists not loading; June 17 failed page loads and 520 errors for about 25 minutes. An agency field note describes an April 2026 partial **outbound SMS outage** where the status page took about 22 minutes to update. Warning from sources: automations queued during an outage may not retroactively fire; status page may itself fail to load during incidents. [3rd-party, moderate]
- Change velocity: about 20+ changelog entries per week. Reviewers note product updates require regression checks of workflows (an editorial caution) and Labs-flagged betas mean feature drift between accounts. [3rd-party]

### 6.5 Review sentiment: scores and where they come from

| Source | Score | Notes |
|---|---|---|
| G2 | 4.6 / 5 from about 600 reviews | G2 AI summary: about 139 mentions praise support as responsive vs about 53 calling it poor; about 56 mentions say UI is not intuitive. Ease-of-setup score 7.8 vs Close 9.1 in G2 comparison. |
| Capterra | around 4.5 | Reviewers: "a lot of features but complicated". |
| Software Advice | 4.2 from 89 reviews | Ease of use 3.7, support 3.7. |
| Trustpilot | **4.9 / 5, 15,252 reviews, 97% five-star** | Highly suspicious distribution (almost no 2 to 4 star reviews; HighLevel replies to 100% of negative reviews). Likely heavy invitation/incentive effect. Do not treat as unbiased. The few 1-star reviews are about **billing**: repeated charges during the trial, no virtual cards or PayPal. |
| Agency blogs (GHL Scale Up) | 4.4 / 5 overall; ease of use 3.5, support 3.5, deliverability 3.0 | Seller of setup services, discloses no affiliate relationship. |
| Scheduling-tool blog | ease of use 3 / 5, support 3.4 / 5 | Editorial. |

### 6.6 Most frequent praise (with concrete examples)

1. **All-in-one consolidation and cost.** "Replaced my whole toolstack" (Reddit paraphrase via blog). Estimated replacement of $400 to $1,200/month of tools (CRM, email, SMS, funnels, scheduling, reputation, memberships). Unlimited contacts and users on every plan.
2. **White-label reselling economics.** "The SaaS reselling is a game-changer" (Reddit paraphrase). Rebilling Twilio-style usage with markup turns cost into margin. Snapshots reportedly cut client onboarding from about 40 hours to about 2.
3. **Automation depth.** 30+ triggers and 100+ actions, plus Workflow AI builder that scaffolds flows from a text prompt; "Missed-call text-back" often cited as the highest-ROI feature.
4. **Unified inbox** across SMS, email, WhatsApp, social DMs.
5. **Velocity and AI.** Voice AI, Conversation AI, Agent Studio/Super Agents, AI Employee bundle, MCP server show the vendor shipping fast and early.
6. **Community and training.** Active Facebook groups, certification program, large YouTube ecosystem.

### 6.7 Most frequent complaints (with concrete examples)

1. **Learning curve and clutter.** 2 to 4 weeks to feel comfortable, months to master; many users "bounce before reaching value"; "does not hand-hold through setup"; interface "overwhelming", "hundreds of features", "several screens for simple tasks". G2: about 56 mentions of "not intuitive". Churn quote: "I churned in a month" (Reddit paraphrase).
2. **Support inconsistency.** Responsive for some (24/7 chat, 139 G2 mentions) and slow or unhelpful for others (53 G2 mentions: long waits, unanswered tickets, different answers from different agents). "It's buggy and support is slow" (Reddit paraphrase). Premium support is a $500/month add-on.
3. **Bugs and regression risk.** Fast shipping causes feature drift and broken workflows after updates; mobile app crashes; Smart Lists failing to load (June 2026); desktop app "launched buggy" (an agency review). Social planner, e-commerce, courses called "unfinished" by one agency review.
4. **Email deliverability.** The most consistent technical complaint: shared sending infrastructure by default, spam placement, must configure SPF/DKIM/DMARC, dedicated IP is a $59 add-on, 2 to 4 weeks of warm-up. "Not an ESP", per a pricing-analysis site.
5. **SMS compliance friction.** US SMS does not work until A2P 10DLC registration clears (per sub-account, about a week, brand and campaign fees). Carrier fee increases in 2026.
6. **Surprise costs.** Usage on top of subscription, add-ons ($497 white-label app, $297 HIPAA non-refundable, $500 premium support, $59 IP), re-priced AI (Voice engine fee from May 20, 2026). Trustpilot 1-star reviews about unauthorized-seeming charges during trial.
7. **Agency-layer pain.** No snapshot revert; no per-brand pricing in SaaS mode; no agency-level granular permissions (1.2k-vote top idea); limited bulk actions across sub-accounts; Starter sub-account cap; custom CSS unsupported and fragile; no agency-wide favicon.
8. **API gaps.** No API for workflows, funnels, sites, email sequences; "become API-first" is the 1.0k-vote ask. API v1 deprecated, forcing migration. Webhook event coverage is uneven.
9. **Security/compliance gaps.** 60-day audit log retention, no enterprise SSO documented, 2FA policy enforcement missing (294-vote request "Planned" since 2023), HIPAA irreversible and priced as a flat fee.
10. **Reporting.** Dashboards lack math, custom-field widgets, and complete data coverage.
11. **Naming and plan confusion.** HighLevel vs GoHighLevel vs LeadConnector; SaaS Pro vs Agency Pro; SaaS V1 vs V2 architectures; Standard vs Advanced workflow builders; Agent Studio vs Super Agents; Labs vs GA.
12. **Reliability concerns.** Multiple incidents per quarter, status page lag, queued automations not retroactively firing.

### 6.8 Idea-board "Top 10" snapshot (global, by votes, Oct 2026) [Official]

1. Leaderboard, points, gamification for Memberships (669, In Progress)
2. Revert snapshot update (492, Planned)
3. Assign multiple companies to a single contact (383, In Progress)
4. View attendees in event calendars (380, Complete)
5. Video chat bubble (372, Planned)
6. Enhanced rewards system with admin controls (251, In Progress)
7. Internal forms (246, Planned)
8. 2-way Gmail/Outlook sync with exclusions (230, Planned)
9. Full public API support for Courses (210, Complete)
10. Quiz-score based redirects (206, Planned)

Per-board highs worth remembering: Users and Permissions "granular permissions at agency level" 1.2k; APIs "API first" 1.0k; SaaS Mode "different brands, different price/features" 944; Mobile "direct SIM card integration" 418; Dashboard "basic math operation" 399. These five (permissions, API, brands, mobile, reporting math) are the clearest market signal about unmet enterprise-grade needs.

---

## 7. Competitive landscape (brief) and what they do better in UX

Caveat: most comparison content is vendor-authored. UX judgments below combine the sources I fetched with background knowledge. Verify with trials before relying on them.

| Competitor | Core positioning | Where they beat GHL on UX | Where GHL beats them |
|---|---|---|---|
| **HubSpot** | Full CRM and marketing suite, free tier, 2,000+ integrations | Guided onboarding tour, polished and consistent UI, in-app AI assistant (Breeze), enterprise RBAC, fast reporting, huge app ecosystem and docs; free plan up to 1,000 contacts | Price at mid/high tiers (HubSpot Pro about $1,300/month for 6 seats and 2,000 contacts; Enterprise about $4,700/month plus $7k to $24k onboarding), native white label and reselling, unlimited contacts, SMS/voice built in |
| **Keap** | SMB CRM, invoicing, scheduling, automation | Simpler, opinionated "small business owner" flows; cleaner contact timeline. Reported pricing $249 to $299/month for 2 users and about 1,500 contacts (expensive) | Breadth, price, white label |
| **ClickFunnels 2.0** | Funnels, courses, commerce for creators | Funnel creation speed and templates; opinionated "funnel workflow" mental model, easier for non-technical creators | CRM/automation depth, agency and reseller layer |
| **Kajabi** | Creator platform: courses, community, coaching, email | Learner/member experience polish, product-first mental model, simple site builder | CRM, SMS/voice, pipelines, agency mode (Kajabi has none) |
| **Vendasta** | White-label marketplace for resellers (products and fulfillment services) | Reseller storefront, ordering and fulfillment flow; partner marketplace of third-party products; account/partner hierarchy well designed for resale. Pricing reported about $79 starter, about $399 to $499 professional plus seat fees. | Build-your-own automation, price, single-platform depth |
| **Systeme.io** | Budget all-in-one (funnels, email, courses, affiliates) | Very simple UI and cheap entry; fewer decisions | Depth, SMS/voice, white label (Systeme is dated in design with limited integrations and support that can take days) |
| **Close** | Sales CRM with native calling/SMS/email sequences | **Ease of use and speed**: G2 ease-of-setup 9.1 vs GHL 7.8; keyboard-driven inbox, Smart Views, call/SMS inside the CRM, clean UI, about 4.7/5 | Marketing suite, funnels, white label, price |
| **Kommo** | Messenger-first CRM (WhatsApp, IG, FB, Telegram), sales pipeline | Messaging-first pipeline UX, chat-to-deal conversion, salesbots; lower learning curve for chat sellers (G2 setup/admin scores lower than Close though) | Breadth, white label, voice AI |
| **Attio / modern CRMs** (G2 compare pages exist) | Modern flexible data-model CRM | Clean data model UX, spreadsheet-like views, collaborative notes, custom objects done well | Agency layer, marketing/funnels |

### What these competitors consistently do better (UX principles)

1. **Opinionated, guided onboarding** (HubSpot tours, Close default views, Kommo salesbot templates). GHL drops users in an empty sub-account with 17 sidebar items.
2. **One coherent design system.** HubSpot and Close feel like one product. GHL mixes legacy Vue modules, React pop-ups and newer builders.
3. **Speed and keyboard-first interaction** (Close). GHL added Cmd/Ctrl+K only in a Labs flag in 2026.
4. **Progressive disclosure.** HubSpot hides Pro/Enterprise features behind clear upsells; GHL shows everything and relies on Labs and permission toggles.
5. **Opinionated data model** with clean associations (HubSpot, Attio). GHL has contacts plus a thin Company object plus capped custom objects (10 per location).
6. **Vertical-first starter kits.** Vendasta and Kommo ship more role/vertical-specific starting points; GHL relies on third-party snapshots of wildly varying quality.
7. **Enterprise controls** (HubSpot RBAC, SSO, audit trails, sandboxes). GHL has none of the sandboxed environments, SSO or long audit retention.

---

## 8. Cross-cutting observations (architecture and product-strategy inferences)

1. **Two-level tenancy (company > location) is the whole product.** Everything (roles, API tokens, billing, rebilling, snapshots, SaaS, MCP) is built on that one axis. A new product should treat "organization > workspace > environment" as a first-class concept from day 1 (HighLevel has no concept of environment or staging).
2. **Config-as-assets, not config-as-code.** Snapshots copy assets rather than describe desired state; there is no diff, revert, drift detection or lineage. This is the root of snapshot pain.
3. **Usage billing is bolted onto a subscription product**, so there are four billing surfaces (platform plan, wallet usage, add-ons, SaaS rebilling) with different rules by tier, and a wallet that is destroyed when SaaS is disabled.
4. **API is an afterthought for builders.** Read-only workflows/funnels, incomplete webhooks, per-app rate limits, and a docs site that is client-rendered and versioned by date strings. The official MCP server partially compensates by exposing 550+ operations through a 4-tool search/describe/execute interface, which is a good design to emulate.
5. **Extensibility is DOM injection.** Custom JS/CSS and iframes in a Vue app, with the vendor stating it is unsupported. There is no stable extension API (slots, design tokens, UI SDK). Marketplace apps use OAuth plus iframe custom pages and Custom JS.
6. **Feature flags as product surface** (Labs, per-sub-account Labs assignment, plan-gated Labs controls). This enables fast shipping, but fragments documentation and support.
7. **AI is now the product narrative** (AI Employee, Voice AI, Agent Studio to Super Agents, AI Studio, Ask AI, Workflow AI, MCP). They meter it by tokens and minutes with agency markup. Any competitor must have a coherent AI cost model for resellers (predictable per-seat or per-location tiers plus transparent pay-per-use).
8. **Vendor-driven content ecosystem.** The affiliate engine means public information is skewed positive and often outdated (plan names, rates). A competitor with truly accurate, current docs and honest pricing calculators has an easy trust advantage.

---

## 9. Opportunities to do better

Prioritized. P0 = decide before first line of code (architectural), P1 = launch differentiators, P2 = fast follow, P3 = later. Each item says what pain it answers and the evidence.

### P0: Foundations that cannot be bolted on later

1. **API-first, parity guarantee.** Rule: every UI action is an API call; workflows, funnels/sites, pipelines, forms, calendars, templates and settings are fully readable and writable via API, OpenAPI 3.1 generated from the same schema the UI uses. *Evidence:* "Become an API-first company" is the #1 API idea (1.0k votes), workflows are read-only in API v2, commenters build off-platform workarounds. *Deliver:* one OpenAPI spec, generated TypeScript/Python/Go SDKs, a real CLI, Postman/Bruno collection, and API changelog with deprecations announced 12 months ahead (HighLevel's v1 deprecation shows the cost of the opposite).
2. **Config as declarative, versioned state ("templates 2.0", replacing snapshots).** Treat a workspace config as a typed document: diffable, reviewable, revertible, with per-workspace overrides and a drift report. *Evidence:* revert snapshot update (492 votes), snapshot history/audit (151), see which snapshots tie to which sub-accounts (75), unlink sub-account from snapshot, backup of individual account (118). *Deliver:* "plan, apply, rollback" for pushing template updates to N workspaces, per-asset lock/unlock to control overrides, dry-run diffs, automatic pre-push backups, and Git-style history. Add an import/export in YAML/JSON so agencies can keep their templates in Git (HighLevel just added Git sync to AI Studio, not to snapshots).
3. **Tenancy model with environments.** Organization > Brand > Workspace, plus Draft/Staging/Production environments for workflows and sites. *Evidence:* SaaS mode "multiple brands with different price/features" (944 votes), no staging for workflows (only agent staging exists), snapshot pushes go straight to prod. *Deliver:* multi-brand white label from day one (domain, logo, theme, plan catalog per brand).
4. **Permission engine, not a checkbox matrix.** Resource, record and field-level policies; named reusable roles; teams and groups; agency-level granular admin roles; temporary and approval-based access; "only assigned + unassigned" visibility modes. *Evidence:* #1 Users & Permissions idea (1.2k votes), enterprise-grade field/record-level control, teams and sub-teams requests, locking custom fields (106 votes). Provide a policy simulator ("what can user X see?") and export for auditors.
5. **Unified billing and wallet model.** One metered-usage ledger (events with units, price, markup) that powers platform plan, usage, add-ons and reseller rebilling; per-brand price books; fixed-rate bundles and caps for resold AI; invoice-style statements instead of a mystery wallet; prepaid and postpaid modes; never delete a balance silently on downgrade. *Evidence:* wallet deleted on SaaS disable, 3DS recharge failures, price churn (Voice engine fee May 2026), surprise-bill complaints and Trustpilot billing reviews, fixed-rate AI rebilling requests.

### P1: Differentiators on UI and developer experience

6. **A single coherent design system with real theming tokens.** Design tokens (color, type, spacing, radius), true dark mode everywhere (HighLevel's dark mode is agency-dashboard only), light/dark/system, per-brand theme editor with live preview that covers favicon, fonts, login screen, emails, PDFs, client portal and mobile app from one place. Ship component library and extension slots so white-label agencies never need unsupported CSS hacks. *Evidence:* agency-wide favicon missing, CSS/JS declared unsupported by the vendor, fonts and colors only via CSS, mobile customizer limited.
7. **Navigation that matches how people work, not module sprawl.** Collapsible sidebar with pinned and reorderable items per user and per role, command palette (Cmd/Ctrl+K) as the primary navigation and action surface, "views" that change the product by persona (sales rep, marketer, operator, agency owner, client). Default to a small core (Inbox, Contacts, Pipeline, Calendar, Automations, Reports) and let power features be turned on. *Evidence:* "overwhelming" clutter, 17-item sidebar not reorderable, Global Search V2 stuck in Labs, built-in item reordering requested, G2 "not intuitive" mentions.
8. **Time-to-value onboarding: a guided setup that produces a working outcome in under 15 minutes** (import contacts, connect email/phone, create first pipeline, first automation, send first message) with vertical starter kits (home services, dental, real estate, coaching, agency). Include sandbox data and an interactive checklist. Handle A2P and domain authentication as wizards with status, estimated approval times and automatic retries. *Evidence:* 2 to 4 week learning curve, A2P friction, deliverability warm-up pain.
9. **Deliverability and compliance as first-class product.** Default dedicated sending domain per workspace with automatic SPF/DKIM/DMARC, warm-up schedules, reputation dashboard, spam-trap and complaint monitoring, block-sending guardrails, per-workspace health scores, bounce/complaint webhooks. Same for SMS (automated 10DLC and toll-free verification flows, templates that pass review, delivery diagnostics in plain language). *Evidence:* deliverability is the top technical complaint; A2P registration per sub-account; "LC Email is not an ESP".
10. **Developer experience as a product.** Self-serve sandbox workspaces, API explorer with live auth, request logs and replay, webhook delivery dashboard with search and bulk replay (HighLevel only allows resending the latest undelivered attempt), event catalog with JSON schemas, signed webhooks with HMAC or Ed25519 from day one, idempotency keys, cursor pagination everywhere, consistent errors with traceId, dynamic rate limits with `Retry-After`, and versioning with dated releases plus a compatibility proxy. Publish a status page and API changelog feed. Provide a real **local dev loop**: CLI, tunnel for webhooks, test fixtures, a "mock tenant" generator.
11. **Complete event and webhook coverage.** Emit events for every state change (forms submitted, workflow runs, calendar bookings, pipeline changes, page publishes, review received, call completed, payment failed, user and role changes) with filtering at subscription time, and an event stream (SSE or WebSocket) for real-time apps. *Evidence:* repo lists about 70 events, ecosystem advice is "use a workflow webhook for the rest"; native HMAC for inbound workflow webhooks was requested.
12. **First-party MCP server done even better, plus agent-safe APIs.** HighLevel's 4-tool search/describe/execute pattern is a good template. Improve it: agency-wide multi-workspace support from the start, dry-run and "propose changes" mode, approval queues for sensitive actions, scoped session tokens, per-tool audit trail, prompt-injection quarantine for inbound message content, and an "agent action budget" (spend and message caps). Expose workflow/page/pipeline authoring through MCP because the API will be complete.
13. **Reseller (SaaS) mode that a non-expert can run.** One-screen SaaS configurator with plan catalog preview, trials, coupons, usage bundles, proration, dunning, tax, multi-currency, per-brand storefront, customer self-service portal, and **webhook plus API for plan CRUD** (HighLevel's plans are read-only via API). Free-form "feature entitlements" and usage meters are first-class entities. Ship a hosted checkout and a plan-comparison embed.
14. **Marketplace and extension platform with stable UI extension points.** Replace iframe/CSS hacks with a proper app SDK: UI slots (sidebar item, contact panel, record action, settings page), a message bus for host context (workspace, user, theme), design-system components so third-party apps match, OAuth with granular scopes plus resource-level scoping, app billing handled natively (per seat, per workspace, usage) with transparent public revenue share. *Evidence:* review rules require responsive iframes that avoid overriding parent navigation, which shows how fragile the model is; revenue share is not public.

### P2: Close the trust and enterprise gaps early (cheap to do on day one)

15. **Enterprise security baseline included on every paid plan:** SAML/OIDC SSO and SCIM, passkeys and security keys, org-enforced 2FA policy, session management, IP allowlists, audit logs with 12+ months retention and streaming export (S3, webhook, SIEM), data residency options (US, EU), DPA and GDPR tooling (consent logs, DSAR export/delete workflows, double opt-in), and HIPAA readiness that can be toggled per workspace without a non-refundable agency-wide fee. *Evidence:* 60-day audit retention, 294-vote 2FA request open since 2022, no documented SSO, HIPAA priced at $297 flat and irreversible.
16. **Transparent pricing and a live cost calculator.** Show real total cost (plan + usage + add-ons) in-app before purchase; spend alerts; hard caps; plain-English invoices; no trial surprises (no card for the free tier, or a clear "this will bill you on <date>" with a one-click cancel). *Evidence:* Trustpilot 1-star reviews about unexpected charges during trial, "hidden costs" narrative across reviews.
17. **Real support model.** Public SLAs by tier, in-app ticketing with replayable session context, human first response on paid plans, status page with component-level incident updates inside minutes (HighLevel's status page reportedly lags and fails during incidents), automation replay after outages (queued runs are retried or at least listed, not silently dropped).
18. **Reporting that works at agency scale.** Cross-workspace dashboards with formulas (the 399-vote "basic math" request), custom fields as dimensions, scheduled client reports with white-label PDFs, SQL-ish query builder for power users, and warehouse export (BigQuery/Snowflake/S3). Make "client-facing reports" a first-class white-label feature.
19. **Bulk and fleet operations for agencies.** Any action available on one workspace is available on a selection of workspaces with preview, progress, partial-failure handling and undo (HighLevel bulk rebilling disable requires one-by-one, push update cannot be reverted). Fleet health view: A2P status, domain auth, deliverability, wallet balance, failed workflows, API errors across all clients on one page.

### P3: Later bets

20. **Modern data model.** Flexible objects (no 10-object cap) with associations, lookups, rollups and field-level validation, spreadsheet-like views, merge/dedupe tooling (merge contacts has 166 votes), multiple-companies-per-contact (383 votes).
21. **Real teams and routing.** Teams, skills-based routing, SLAs, business hours, queue views in the inbox, Gmail/Outlook sync with domain/contact exclusions (230 votes).
22. **Offline-capable, fast mobile apps** with a push-first reliability promise, direct SIM/VoIP handoff (418 votes), custom modules and objects, and a self-serve white-label build pipeline that does not require the agency to own a D-U-N-S-backed developer org (offer a managed publisher option).
23. **AI cost transparency and control for resellers:** model choices, per-agent budgets, guardrails, evals and simulation (HighLevel offers a prompt optimizer and test runs; add conversation replay and A/B testing), and a plain unit economics view for the agency ("this agent costs $X per resolved conversation").
24. **Quality bar for templates:** a vetted, versioned template marketplace with automated compatibility checks against the current platform version, instead of unvetted snapshot sellers.
25. **Migration kit:** a "Import from GoHighLevel" tool that reads sub-accounts via API v2 (contacts, pipelines, custom fields, tags, calendars, forms, funnels metadata, workflows read-only) and maps them to the new platform, plus a side-by-side parity checklist. Because GHL workflows are read-only in API, plan on a "recreate with AI from the workflow JSON export" path. This is the highest-leverage acquisition feature for a challenger because the agency switching cost is the real moat.

### What not to copy (anti-patterns observed)

- Unsupported CSS/JS injection as the main customization method.
- Naming sprawl (HighLevel/GoHighLevel/LeadConnector, V1/V2 SaaS, Agent Studio/Super Agents, Standard/Advanced builders).
- Features visible but unfinished in production (Labs plus half-built modules). Keep a hard "preview" label and an opt-in channel with rollback.
- Destroying state on a toggle (wallet deleted on SaaS disable; HIPAA cannot be disabled once enabled).
- Per-sub-account manual setup of the same compliance artifacts (A2P, Stripe customers, domains). Offer inheritance from a parent brand profile with per-workspace overrides.
- Pricing gates scattered by feature (API depth, rebilling markup, dedicated IP, Labs control).
- A giant default navigation with no personalization.

### Suggested positioning statement

"The agency and SMB growth platform with a real API, real templates (versioned, diffable, revertible), real permissions, and a UI that a new hire understands on day one." Back it with three proofs: a published OpenAPI + SDK + CLI + MCP server on launch day, a one-click "migrate from GoHighLevel" importer, and a public status/pricing/changelog page that is always current.

### Items to verify in a live trial before design lock

1. Exact current sidebar order for agency and sub-account views and what is behind the "Pro" layout theme.
2. Whether custom (named, reusable) roles exist.
3. SSO availability (any plan) and GDPR/data-residency stance.
4. Workflow export format (to scope a migration importer).
5. Real LC Email infrastructure and shared-pool reputation behavior.
6. Reddit r/gohighlevel recurring complaint list and recent outage threads (blocked in this research).
7. Marketplace revenue-share percentage and app counts.
8. Current accuracy of third-party voice/SMS rates (they differ by up to 30% between guides).

---

## 10. Source index

Official (HighLevel-owned):

- Pricing: https://www.gohighlevel.com/pricing
- Agency company settings: https://help.gohighlevel.com/support/solutions/articles/48000982604-agency-settings
- Custom menu links: https://help.gohighlevel.com/support/solutions/articles/48001185767-how-to-add-a-custom-domain (article titled "Customizing HighLevel Menus: A Guide to Custom Menu Links")
- SaaS Configurator getting started: https://help.gohighlevel.com/support/solutions/articles/155000008015-getting-started-with-the-saas-configurator
- SaaS Mode FAQ: https://help.gohighlevel.com/support/solutions/articles/155000002129-highlevel-saas-mode-faqs
- SaaS permissions levels: https://help.gohighlevel.com/support/solutions/articles/48001184431-saas-user-level-permissions-vs-sub-account-level-permissions
- SaaS bulk rebilling: https://help.gohighlevel.com/support/solutions/articles/155000005766-saas-bulk-rebilling-setup-for-multiple-sub-accounts
- SaaS configurator public API: https://help.gohighlevel.com/support/solutions/articles/155000005768-public-api-endpoints-for-saas-configurator
- AI product pricing: https://help.gohighlevel.com/support/solutions/articles/155000006652-ai-product-pricing
- AI Studio: https://help.gohighlevel.com/support/solutions/articles/155000007587-ai-studio-in-highlevel
- Super Agents: https://help.gohighlevel.com/support/solutions/articles/155000007931-how-to-setup-and-use-super-agents-in-agent-studio
- Labs overview: https://help.gohighlevel.com/support/solutions/articles/155000003588
- Agency user roles: https://help.gohighlevel.com/support/solutions/articles/155000002543-manage-agency-user-roles-and-permissions-in-highlevel
- Admin vs User roles and scopes: https://help.gohighlevel.com/support/solutions/articles/48001078296-admin-vs-user-roles-and-permission-scopes
- Audit logs: https://help.gohighlevel.com/support/solutions/articles/155000006667-audit-logs
- Authenticator 2FA: https://help.gohighlevel.com/support/solutions/articles/155000005534
- White-label mobile app: https://help.gohighlevel.com/support/solutions/articles/155000000089-how-to-promote-and-customize-your-whitelabel-mobile-app
- Mobile v4: https://help.gohighlevel.com/support/solutions/articles/155000006707
- Global Search V2: https://help.gohighlevel.com/support/solutions/articles/155000008323-global-search-v2
- API v1 deprecation post: https://www.gohighlevel.com/post/deprecating-the-highlevel-api-v1-and-migrating-to-v2
- API docs repo: https://github.com/GoHighLevel/highlevel-api-docs (raw files under `docs/oauth`, `docs/webhook events`, `docs/marketplace modules`)
- Private Integration Tokens: https://marketplace.gohighlevel.com/docs/Authorization/PrivateIntegrationsToken
- Webhook guide: https://marketplace.gohighlevel.com/docs/webhook/WebhookIntegrationGuide
- MCP docs: https://marketplace.gohighlevel.com/docs/other/mcp
- Marketplace GTM and review guidelines: https://marketplace.gohighlevel.com/docs/oauth/AgencyVsSubAccount.md and https://marketplace.gohighlevel.com/docs/oauth/AppReviewGuidelines.md
- Ideas board and changelog: https://ideas.gohighlevel.com/ (boards: apis, snapshots, users-permissions, saas-mode, dashboard, mobile-app, automations; changelog)

Third-party (directional):

- GHL Scale Up review: https://www.ghlscaleup.com/blog/gohighlevel-review
- SchedulingKit pros/cons: https://schedulingkit.com/pros-and-cons/gohighlevel-pros-and-cons
- Ciela Reddit synthesis: https://ciela.ai/blogs/is-gohighlevel-worth-it-2026-reddit
- BrandBlast snapshot guide: https://www.brandblast.com/blog/ghl-snapshot
- NetPartners cost, AI pricing, release study, reliability: netpartners.marketing (affiliate-authored)
- GHL Experts HIPAA and dashboard guides: https://www.ghlexperts.com/guides/gohighlevel-hipaa-compliance, https://ghlexperts.com/features/ghl-dashboard
- RevenueGeeks MCP guide: https://revenuegeeks.com/guides/gohighlevel-mcp
- OneExpand sub-accounts guide: https://oneexpand.com/gohighlevel-sub-accounts/
- Softr GHL vs HubSpot: https://softr.io/blog/gohighlevel-vs-hubspot
- Latka revenue estimates: https://getlatka.com/companies/gohighlevel
- General Atlantic press release (April 2024 investment)
- Trustpilot, G2, Capterra, Software Advice listings (scores via search summaries)
- Pingoru outage history for HighLevel
