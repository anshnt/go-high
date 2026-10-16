# 02 - Marketing, Sites, Content, Ads, Reporting and Reputation (HighLevel / GoHighLevel / LeadConnector)

Research date: 2026-10-16. Scope: Sites (funnels, websites, forms, surveys, quizzes, chat widget, QR codes, trigger links, blogs, client portal, WordPress hosting), Email marketing, Social Planner, Ads Manager and Reporting, Media library, Brand boards, Affiliate manager, Prospecting, Listings, Reputation.

## 0. How to read this document

Sources, in order of trust:
1. Official HighLevel help center (help.gohighlevel.com). Marked "(doc)". Many articles are dated; some are over 1,000 days old, so menu names may have shifted. Where two help articles disagree I say so.
2. Third-party agency and review blogs, G2/Capterra excerpts. Marked "(3rd party)". Many are affiliate content; treat claims as soft.
3. My own inference about data entities and fields. Marked "(inferred)". The public API and UI shape suggest these entities, but the vendor does not publish an official schema in the help center.

Not reachable in this session: ideas.gohighlevel.com changelog, highlevel.stoplight.io, marketplace.gohighlevel.com, direct Reddit threads, full G2 and Capterra pages (403). Those gaps are listed in section 17. Pain points are therefore weighted toward vendor-admitted limits ("Limitations" sections in the help center, which are very telling), plus the excerpts of G2/Capterra reviews and third-party tests I could read.

Pricing context used throughout (doc + 3rd party): agency plans are $97 Starter, $297 Unlimited, $497 SaaS Pro per month. Higher plans unlock API access, dedicated IP purchase, custom metrics, rebilling markup and the SaaS configurator. Usage (email, SMS, AI, ad management resale) is metered through a prepaid wallet.

Terminology: "location" and "sub-account" are the same thing. "Agency" is the parent account. "Snapshot" is a copy/paste package of a sub-account's assets. "Custom Value" is a per-location variable (a merge field). Most modules below hang off a location id.

---

## 1. Module map and mental model

```
Agency
 +-- Sub-account (location)
      +-- Sites
      |    +-- Funnels (ordered steps)        +-- Websites (free navigation pages)
      |    +-- Blogs                          +-- Forms / Surveys / Quizzes
      |    +-- Chat Widget                    +-- QR Codes
      |    +-- Client Portal                  +-- WordPress (hosting add-on)
      |    +-- Analytics (asset type switcher)
      +-- Marketing
      |    +-- Emails (Campaigns, Templates, Statistics)   +-- Social Planner
      |    +-- Trigger Links                               +-- Ad Manager
      |    +-- Affiliate Manager                           +-- Brand Boards
      |    +-- Prospecting (also agency level)             +-- Media Storage
      +-- Reputation (Overview, Requests, Reviews, Widgets, Listings, Settings)
      +-- Reporting (Dashboard, Custom Reports, Attribution, Call, Agent, Google Ads, Facebook Ads)
```

Cross-cutting plumbing that every module reuses (this is the real moat; a competitor must build it once and share it):
- Contact record with first and latest attribution session data.
- Custom values / merge fields and custom fields (contact, opportunity, custom objects, company objects).
- Media storage with a picker modal embedded in all builders.
- Brand boards (colors, fonts, logos) read by the email and page builders.
- Workflow triggers fired from every module (form submitted, quiz submitted, order submitted, trigger link clicked, review received, email events, call details, etc.).
- Usage metering and agency resale markup for paid add-ons.
- Whitelabel domains (API domain, sites domain, email sending domain, client portal domain).

---

## 2. SITES

### 2.1 Funnels vs Websites (doc)

| Aspect | Funnel | Website |
|---|---|---|
| Structure | Ordered steps (journey) | Multi-page, free navigation |
| Typical use | Lead capture, booking, sales, webinars | Business site, service pages, info pages |
| Split testing | Yes (step level) | No |
| Blog | Blog Post List element can be placed on a funnel step or site page | Same |
| E-commerce store | Not in funnels (3rd party claim) | Store is a separate module |
| Navigation menu element | Yes | Yes |

Both use the same underlying builder: Section > Row > Column > Element hierarchy. Same editor, same stats screen, same domain linking.

### 2.2 Creation paths (doc)

- Sites > Funnels (or Websites) > New. Choices: From Blank, From Template (template library with search, filter, sort, preview), Funnel AI / Website AI.
- Funnel and Website AI has two modes:
  - Assist: guided fields (page name, business niche, page goal, target audience, offer details). Option to generate immediately or customize first.
  - Build: free-form prompt with prompt starters.
  - Reference inputs: a public URL or an image for visual direction (inspiration, not an exact clone).
  - Conversational edits at section or page level, regenerate section or page, add sections (pricing, testimonials, FAQ) without regenerating the page, AI SEO suggestions for title and meta description.
  - Generation continues server side if the browser closes. Currently no extra AI charge but "subject to usage limits"; a separate rebill article exists for Funnel AI.
- Third-party benchmark of AI output: described as about 60 percent complete; stock images, brand colors, workflow triggers, pixels, and form actions still need manual work (3rd party).
- Import: a ClickFunnels import feature exists (convert funnels and websites by URL). A freelancer claims it often breaks fonts and layouts (3rd party, weak evidence).
- Ask AI also has a "Funnel Creation Agent" that can build a funnel from chat (doc title seen).
- Snapshots: funnels and websites are included in snapshots. Template library is also fed by snapshot imports.
- Funnel/website audit logs exist (doc title: "Audit Logs for Funnels, Websites, Webinars and Stores").

### 2.3 Funnel step model

A funnel is an ordered list of steps. Each step is a page with a URL path and a type-ish role. Typical step roles (doc + 3rd party):
- Landing / sales page
- Opt-in page with form
- Order form page (one-step or two-step)
- Upsell page (one click)
- Downsell page
- Thank-you / confirmation page
- Calendar booking page
- Webinar registration and confirmation pages
- Quote request / qualification form page

Funnel-level concepts:
- "Funnel Paths" doc exists (routing which step comes next; Funnel Paths allows branching, e.g. by upsell accepted or declined).
- Step order is drag and drop. Reordering changes sequence only, not URLs. Webinar-style funnels show a confirmation prompt first.
- Each step has: Page Name, URL path/slug (unique within funnel), optional products, SEO meta, tracking code, custom CSS, optional split-test variation.
- Funnel-level settings (inferred from docs): domain, favicon, default path, tracking code in head and body, payment mode (test/live), image optimization, Facebook pixel / event pixel, Conversion API settings.

Data entities (inferred):
```
Funnel { id, locationId, name, type, domainId, steps[], settings{trackingHead, trackingBody, favicon, imageOptimization, paymentMode}, createdAt, updatedAt }
FunnelStep { id, funnelId, name, pathSlug, sequence, type, pageId, products[], seo{title, description, ogImage}, splitTest{ variations[], trafficPct } }
FunnelPage { id, stepId, version, sections[ rows[ columns[ elements[] ] ] ], customCSS, trackingCode, mobileOverrides{} }
```

### 2.4 Order forms, checkout, upsells, downsells (doc)

One-step order form:
- Contact, optional shipping and payment fields on a single screen.
- Form options (fields like company name, shipping, price).
- Products tab per step: choose Product and Price (one-time or recurring). Overrides: Product Name Override, Price Display Override.
- Additional options: allow multiple quantity, max per order 1 to 999, product type Main or Bump.
- Cart Mode: customers buy multiple products from one form (V2 funnels only).
- Toggle product description and pricing display; recurring products can show price breakdown.
- Coupon codes toggle in element settings.
- Styling: button, text, background colors.

Two-step order form: step 1 captures contact details first (enables abandoned-checkout recovery), step 2 takes payment. Doc "two-step order form" exists. Shopping cart mode applies to both one and two step (V2 only).

Order bump (doc):
- Styles: Modern or Classic; Template 1, 2 or 3; highlight text and icon; show/hide price; colors (background, highlight text, headline, OTO headline, OTO text); layout 1, 2 or 3 columns; single or multiple selection; footer info toggle.
- Bump fields: headline, image on/off, upload or pull from product record.
- Rules: only one recurring product per form (main or one bump, not both). Bumps need a main product. Bump works only on forms that include the Sell Product element. Bumps can be toggled and reordered.

One-click upsell (doc):
- Primary form needs a Sell Products element (captures a payment token reused by upsell).
- Form button action: Go to Next Step.
- On the upsell page place a Button, set action "Upsell Product", pick product. One upsell product per step; chain multiple steps for sequences.
- "Order Upsell" does not work in V1 funnels or in Websites.
- Memberships have their own separate one-click upsell editor (title, subtitle, purchase button label, cancel button text, price styling, active toggle).
- Downsell: a decline path to a lower-priced step via Funnel Paths (3rd party description).
- Workflow trigger "Order Submitted" filters by submission type: Primary, Bump or Upsell. Doc recommends "Allow Multiple" in workflow settings and avoiding Wait steps for upsell flows.
- Payment triggers: Payment Received, Payment Failed (2026 roundups).

Payments provider layer (doc + 3rd party): Stripe is the primary native processor; products live under Payments > Products; funnel-level stats track orders, bump orders, quantity, revenue, average cart value.

Stats definitions (doc "Funnel and Website Stats Definitions"):
- Page views: All (includes repeats) and Unique.
- Opt-ins: any successful form submission, purchase, survey submit or calendar booking on a step. Rate = opt-ins / unique page views.
- Sales: orders (step level, product level, bump product), rate, quantity, amount, average cart value.
- Earnings per view (EPV): sales value / all page views, and also / unique views.
- GA numbers will not match (sessions vs views, bounce filtering, ad blockers).

### 2.5 Page builder (doc + 3rd party)

Layout of the editor (doc):
- Top bar: page selector popover (shows current page name), device toggle (desktop and mobile), undo/redo (session based), Versions, Preview, Save, Publish.
- Left: Pages drawer (search, add new page modal with name and URL path, drag reorder), Layers (nested tree), Elements panel (drag onto canvas), global/universal sections.
- Right: settings panel for selected section, row, column or element. Page-wide Typography and Background settings. Tracking Code and Custom CSS. Mobile and desktop controls including per-device visibility.
- Canvas: WYSIWYG.

Hierarchy: Section > Row > Column > Element. Elements can be moved, duplicated, deleted.

Element catalog (doc titles + 3rd party; incomplete):
- Content: headline, sub headline, paragraph, bullet list, image, video, audio, image slider, icon, divider, FAQ, countdown timer, progress bar, testimonials/reviews, pricing table, Google map, social icons.
- Interaction: button (actions: go to next step, URL, call, email, text, download file, popup, upsell product, scroll), form, survey, quiz, calendar, navigation menu, popup (including exit-intent), sticky bar, click-to-call/text/email links, QR code element, blog post list, custom HTML/JS/CSS.
- Commerce: Sell Product (order form), order bump, cart element, product list/featured product, store elements (websites).
- Misc: custom code, iframe, Chat Widget, color picker, border control, image optimization toggles, heading tags (h1 to h6 setting), height/width controls, Download File action for buttons, images, SVGs.
- Universal sections: header and footer shared across pages, updated once.

Mobile responsive editing (doc + 3rd party):
- Separate mobile view with independent spacing, font sizes, element hiding, section rearrangement.
- Third-party tests note no tablet breakpoint: widths around 768 to 1024 px use the mobile layout, which can break wide hero sections.
- Firefox preview spacing quirks reported.

Versions and publishing (doc):
- Save keeps a draft; Publish makes saved version live. Versions list allows restore. Undo/redo only per session.
- Website pages grid: reorder page cards by drag.

Global settings:
- Typography (headings, paragraph, links), background, tracking code, custom CSS, favicon, payment mode, image optimization, brand board linkage (Brand Boards are available as color and font pickers in funnels and websites).
- Global custom colors: updating one global color propagates everywhere (unlike brand boards which only affect future picks).

### 2.6 Custom code, tracking, SEO, page speed (doc + 3rd party)

- Custom code element accepts raw HTML, CSS, JS. Page-level and funnel-level "Tracking Code" in head and footer. Custom CSS at page level. Webhook and pixel support through tracking code.
- Facebook pixel and Conversion API event pixel for funnels (doc "How to set up a Funnel Event Pixel for Facebook Conversion API").
- SEO meta data per page: title, meta description, OG image, canonical link (blog), robots/indexing options, heading tag control. Funnel AI also produces SEO suggestions.
- Preview Custom Code is a doc section; code runs on the published page.
- Image optimization toggle at site level.
- Page speed (3rd party tests by one author; treat as directional):
  - Clean page with hero image under 150 KB and no third party scripts scored about 68 to 78 mobile PageSpeed in the key stat (a separate box says 89 mobile, 96 desktop; the source is internally inconsistent).
  - Adding a chat widget or heavy pixels dropped score to 55 to 65. A comparable Unbounce page scored 82 to 91.
  - LCP is the issue: hero images not lazy loaded by default, all section CSS loads before paint. TTFB reached 3.8 s from Southeast Asia (suggests CDN not edge-rendering everywhere).
  - Autoplay YouTube embed adds 400 to 600 ms.

### 2.7 Domains (doc)

- Settings > Domains and URL Redirects > Connect a domain > Funnel/Website. Root domain: A record @ to a fixed IP. Subdomain: CNAME to the platform sites host. Cloudflare must be set to DNS only (not proxied). Domain Connect supported for some registrars (one click).
- After DNS verify, link domain to a funnel or website, choose the default landing page. SSL is auto-provisioned in minutes.
- A domain must be added to the funnel before split tests work.
- Separate whitelabel domain types exist: whitelabel app domain, API domain (used for trigger links, preview URLs), email sending domain, sites domain, client portal domain.
- Known pain: "CNAME / A record not found" errors from conflicting records, old www records, DNS at wrong provider.
- Limit: one API domain per agency, cannot be set per sub-account (trigger links branding).

### 2.8 Split testing (doc + 3rd party)

Mechanics:
- Funnels only. Test lives at step level. All traffic goes to the step main URL; a slider routes visitors to dedicated Control and Variation URLs using a browser cookie so a returning visitor keeps their variant.
- Setup: open step, Create Variation (three creation options; clone control is the common one), set traffic slider, Start Split Test, Apply. Gear icon edits each variant's URL path.
- Stats tab: click the page under test to expand control vs variation stats (views, opt-ins, sales, EPV).
- Doc does not describe winner declaration, significance or sample size.
- Third party: choose goal (opt-in or purchase), declare winner manually; no multivariate; no significance indicator; no automatic winner deployment; no heatmaps or recordings. Max effectively two variants described in some sources; doc says "one or more variations".
- Pitfalls (doc): if visitors reach the page through another funnel, ad, or root domain the test is bypassed; edit control during test skews data; Google/Facebook ad policy can block path based redirect (workaround: test on step 2).
- Websites cannot split test; workaround is import into a funnel.
- Email has a separate A/B (section 5.6) and workflows have a separate Split action.

### 2.9 Analytics for Sites (doc)

Location: Sites > Analytics.
- Asset Type dropdown: Funnels, Websites, Blogs, Webinars, Forms, Surveys, QR Codes, External Tracking.
- Asset dropdown (all or one). Date range (default last 14 days, compared to prior equal period).
- KPI cards (act as tabs): Page Views (total and unique), Opt-ins, Sales, Time on Page, Opt-in Conversion Rate.
- Charts: timelines for views, opt-ins, sales, order conversion; Page Views by Step with drill-down; pie chart visualizations; top countries, states, cities; browsers and IPs; traffic sources; average time.
- QR codes: total scans and scans per code only.
- External Tracking: analytics for forms embedded on non HighLevel sites (a script captures submissions automatically; does not support iframe forms).
- Visitor Data Widgets for dashboards.
- Pain: not cohort based, no heatmaps/scroll maps/recordings, no funnel-visualization with drop-off between steps beyond per step table (3rd party: recommends Microsoft Clarity).

### 2.10 Websites specifics (doc)

- Sites > Websites > New Website > From Blank or From Templates; name; pages grid with drag reorder.
- Website Settings: site name, domain, default path, favicon, tracking code, payment mode, image optimization.
- Products can be attached to a page for order experiences; Payments area lists website orders.
- Stats: page views, opt-ins, sales, earnings.
- Navigation menus (doc "Navigation Menus in HighLevel Funnel Builder"): menu element linking to pages.
- Third party: not good for large e-commerce catalogs, blog-heavy or technically complex SEO-first sites.

### 2.11 Pain points (Sites)

- Template library smaller and lower quality than ClickFunnels or Leadpages; one Capterra reviewer called templates weak. Source says 400+ templates, "recommend using the 8 to 10 blank layouts" (3rd party).
- Editor is functional rather than design-rich; no real animation system; limited effects (3rd party).
- No tablet breakpoint; Firefox preview inconsistencies (3rd party).
- Basic A/B only: two variants, manual winner, no significance, no auto-deploy.
- Page speed behind dedicated landing page tools; chat widgets and pixels hit LCP; hero images not lazy-loaded by default.
- Split tests work through path redirects so ad platforms may block them; need domain first.
- Menus rename and move several times a week (G2 and Capterra mention shifting menu locations).
- Builders called out as needing improvement by G2 reviewers ("some elements like the builders need to be improved").
- Imported ClickFunnels designs reportedly break fonts and layouts.
- Websites missing split testing and several funnel-only commerce features; funnels missing blogs and stores; the split between V1 and V2 funnels means upsell and cart mode only work in V2.
- Forms embedded via iframe cannot be styled from the host page and break browser GTM triggers (agency report).

---

## 3. FORMS, SURVEYS, QUIZZES

### 3.1 Forms builder (doc)

Builder structure: left sidebar adds fields; canvas; right sidebar with tabs Styles, Themes, Advanced; top toggles for Settings, Notifications (bell), Submissions, Integrate. Pop-up Form Builder inside the funnel editor edits a form without leaving the page.

Layouts: Single Column, Two Column (formerly inline), Single Line (up to 5 fields). Field width as percentage. Per-field label alignment only in single column (Top, Left, Right, Form Default).

Field types (doc quiz list, matches forms):
- Personal info: full name, first name, last name, date of birth, phone, email.
- Address: address, city, state, country, postal code, organization, website.
- Question types: single choice, multiple choice, yes/no, short answer, long answer, number, single dropdown, multi dropdown, rating (5 star), file upload, monetary, signature, date.
- Display and special: text (display), HTML (third-party script), image, captcha, Source (lead source tracking), terms and conditions checkbox, Score (numeric), timezone field, sell-product/payment elements (order upsell and bumps work inside forms, doc "Order Upsell in Forms").
- Object fields: contact custom fields, opportunity custom fields, custom objects and company objects (custom objects are added from inside the builder with a primary field). Fields with "score" in the name are treated as numeric scoring elements.
- Each element has: question/label, placeholder, Query Key (pre-fills from URL parameter), Required, Hidden, short label, validation.
- Sticky Contact (remember the contact on repeat visit), Element and Slide cloning.

Right sidebar settings (doc):
- Styles: layout, widths, spacing, padding, top margin; footer (surveys): stick to card or page, background, height, typography, progress bar toggle, button type and position, button labels for Previous/Go Back/Next/Submit, button colors; colors and background; misc (agency branding on/off).
- Themes: preset themes (Use Theme overrides modifications); button styling gallery (Filled, Border, Text Only), colors, typography, alignment, padding, border radius, shadow.
- Advanced: form border, corners, shadow; input styling (text/focus color, border, corner, width, padding, shadow); label and short label typography; placeholder; Custom CSS (overrides Styles and Themes).
- Changes do not autosave; click Save.

Form settings:
- On Submit: confirmation message or redirect URL, with conditional logic overrides. Message editor.
- Facebook pixel ID and events, Google tag events, custom footer HTML.
- Open/close scheduling for quizzes (open and close dates, time zone, custom message or redirect outside window).
- Embedding options: iframe embed code (static; changes require re-copying code), link, "embed triggers, layouts and deactivation settings" (popup/inline/sticky triggers on scroll or time, and deactivate after submit).
- Source Field and Timezone in Forms and Surveys.
- Notifications: internal email on submit; Auto Responder to submitter; configurable subject, recipient, reply-to, sender name; attachments (quiz submission PDF and results PDF).
- Submissions tab with search and export. Contact auto-create/update with field mapping.
- Integration: workflow triggers "Form Submitted", "Survey Submitted", "Quiz Submitted", and 2026 "Form Partially Completed" (3rd party). Webhooks via workflow action. Typeform migration guide exists.

### 3.2 Conditional logic v2 (doc)

- Actions: redirect to URL, display custom message, disqualify lead (reject submission), show/hide fields dynamically.
- Rules: choose field, state, value; combine with AND or OR (one connector type per rule).
- Operators by type: text (exact, not, contains, starts/ends, empty/filled, case-insensitive), number (equal, greater, less, between, empty), date (equal, before, after, between), dropdowns and checkboxes (selected or not), terms (checked), file/signature (empty/filled).
- Evaluation: top-down; for redirect/message/disqualify the first match wins; for show/hide later match overrides.
- Limits: calendar fields unsupported in conditions; disqualify in a booking prevents appointment and payment; services v2 and rentals not covered.

### 3.3 Surveys (doc)

- Multi-slide forms with progress bar and per-slide Jump To rules on choice options. Footer controls for navigation. Themes and styling like forms. Math calculation v2: numeric scores on radio, checkbox and dropdown options (decimals and negatives allowed) summed into score fields.
- Conditional logic in surveys v2 (slide jump, show/hide).
- Same notification, submission, embed options.

### 3.4 Quizzes (doc)

- Builder tabs: Edit, Settings, Notifications, Submissions.
- Scoring: points per option; max score per question; categories (outcome groups) per option; overall-only vs category contribution.
- Result tiers: score ranges (percent) mapped to custom messages and colors (default example 0 to 39, 40 to 79, 80 to 100). Highest or lowest category result (personality quizzes).
- Results page customizable: header (logo, name, layout, background), tier text, CTA with button link, footer (logo, social links, sticky).
- CRM mapping: scores, tiers, categories into contact custom fields; workflow trigger Quiz Submitted with filters on overall or category scores.
- Quiz template library (browse, filter, search, preview, activate). Start from scratch or from template.
- Publish: Save > Integrate > Embed (iframe) or direct Link.
- Course quizzes (inside Memberships/Courses) are separate and have certificates.

### 3.5 Data entities (inferred)

```
Form { id, locationId, name, fields[], layout, theme, settings{onSubmit, notifications, pixel}, conditionalRules[], status }
FormField { id, type, label, placeholder, queryKey, required, hidden, options[], width, mapTo{customFieldId|objectKey} }
FormSubmission { id, formId, contactId, others{fieldKey: value}, source{page, utm, referrer}, createdAt }
Survey { id, slides[ elements[] ], jumpRules[], scoreFields[] }
Quiz { id, questions[], categories[], scoreTiers[], resultPage{}, schedule{open, close, tz} }
```

### 3.6 Pain points (Forms)

- Embed codes are static; any edit needs a new embed code (doc).
- Calendar fields not supported in conditional logic; legacy v1 logic vs v2 confusion; legacy forms keep old inline settings.
- Iframe embeds cannot be styled from host page or tracked by host GTM.
- Quizzes and forms only recently converged (still some "Quiz Builder" vs "Sites > Quizzes" vs course quiz split).
- Sidebar changes need explicit Save (easy to lose work).
- No native multi-form A/B test.

---

## 4. CHAT WIDGET, QR CODES, TRIGGER LINKS, LINK TRACKING

### 4.1 Chat widget (doc)

Seven chat types: All-In-One (live chat, email/SMS, WhatsApp, Facebook, Instagram, Voice AI selectable channels), Email and SMS, Live Chat (web chat, routes into Conversations), Facebook, Instagram, WhatsApp (needs approved number), Voice AI (browser-based voice agent).

Config tabs: Style (theme, icons, welcome messages, avatar, dimensions Auto or custom, Sticky or Embedded/Inline), Chat Window (title, intro, contact form, branding, compliance notice, consent checkbox required or pre-checked, "load on user interaction" with about 8 s fallback), Messaging (acknowledgments, language), Agent (voice agent for AI types).

Behavior: Conversation AI can greet and answer; multiple widgets per sub-account; install by script, GTM, WordPress or directly via Funnels/Websites/Blogs; changing chat type does not affect existing conversations; Client portal chat widget integration exists.

Limits: same message on every page (no per-page dynamic messaging; workaround = multiple widgets with prefilled text on specific pages). No stated caps.

Pain point: third-party tests say chat widget plus pixels cost 10 to 20 PageSpeed points.

### 4.2 QR codes (doc)

- Types (dynamic, destination changeable later): Website, Review Link, Call, SMS, Email, Payment, WhatsApp, Funnel, Form, Survey, Quiz, vCard, business card.
- Bulk QR creation exists.
- Styling: shape (square, rounded, circle), dot style, colors, corner markers, border/frame, CTA text above/below, center logo (predefined like Google or YouTube, or upload) with background removal, background alpha for transparent PNG.
- Export: PNG, SVG, PDF, copyable link.
- Analytics: total and unique scans (shown in Sites > Analytics > QR Codes; the creation article does not mention it).
- Media Picker integrates for images.

### 4.3 Trigger links and link tracking (doc)

- Marketing > Trigger Links > Add Link: name, destination URL. Short redirect URL on the agency API domain. Insert into SMS, email, GMB, FB/IG/WhatsApp DMs only.
- On click: logs to the contact activity timeline, can fire a workflow ("Trigger Link Clicked" trigger, filter by link), and Wait step in a workflow can branch on click with timeout.
- Custom Value URL: assign a custom value so the destination can change without editing messages (does not change links already sent).
- Unsubscribe trigger links per channel (SMS, email, GMB, FB/IG).
- SMS opt-out keywords handled separately (STOP etc.).
- Email click tracking (doc "click tracking in email campaigns"): link wrapping rewrites URLs through a tracking domain; a separate "email attribution settings" feature has a 5 day default window.
- Click-to-call, click-to-text, click-to-email link buttons for funnels.
- Limits: one API domain for all locations; article lists no aggregate analytics, only per contact timeline (an agency-level click report is absent in the doc I read; the Social Planner link shortener has its own URL Tracking stats).

Entities (inferred): `TriggerLink { id, locationId, name, redirectTo, shortKey, clicks[] }`, `LinkClick { linkId, contactId, ts, ua, ip }`.

---

## 5. EMAIL MARKETING

### 5.1 Structure

Marketing > Emails with tabs: Campaigns, Templates, Statistics (unified Email Statistics dashboard across sources), plus Smart Lists / bulk actions for sending from Contacts. Campaign statuses (doc): Draft, Sent, Failed, Archived (plus an "All" filter). A scheduled state exists in practice.

### 5.2 Builders

Three authoring modes:
1. Drag and drop builder (Add Elements menu, Manage Elements list, Appearance global styling).
2. Inline WYSIWYG text editor inside the canvas (headings, fonts 8 to 96 px, hex colors, bold/italic/underline/strike, links, alignment, line height, bullets, clear format).
3. Code editor / plain HTML. Import emails from other platforms (Mailchimp, Klaviyo, ConvertKit, ActiveCampaign, Constant Contact) using Email AI into the code editor.
4. Plain text editor (separate article).

Layouts: single column, two column, unequal splits (1/3 to 2/3, 2/3 to 1/3, 1/4 to 3/4, 3/4 to 1/4), four column.

Element list (doc, 19 entries): Text, Image, Button, Logo, Divider, Social, Footer, Code (HTML, inline CSS only; no JS or iframe), Video (YouTube/Vimeo preview), Shopping Cart (abandoned cart), RSS Header and RSS Items (`{{rss_feed.title}}`, `{{rss_item.title}}`), FAQ (collapsible), Products, Image Slider, Preview URL, Countdown Timer, Spacer, Review Link, Forms (embedded form, only works in some clients), plus custom-value-driven colors, conditional visibility by custom field (3rd party).

Mobile: per-element visibility toggle; separate font size, alignment and line height for H1 to H3, paragraph and buttons on mobile (media queries).

Personalization: merge fields for contact, location, custom values, service and rental values (booking), trigger links. Brand Board fonts and colors appear when the default board is set. Custom fonts support.

Templates: Marketing > Emails > Templates; folders; save any email as template; system templates (e.g. Social Planner post approval, review requests); template library with prebuilt templates; snapshot sharing. Email AI generates copy using Brand Voice.

### 5.3 Campaigns, scheduling, batch sending

Audience: tags, smart lists, segments (pre-built segments are fixed at creation; smart lists are re-evaluated at send time; one doc says contacts are captured at schedule time, a conflict), exclusions (e.g. unsubscribed), individual contacts, bulk action from Contacts, "send bulk email to associated contacts from companies and custom objects".

Sending options (doc): Send Now, Schedule, Batch Schedule (drip), RSS Schedule (recurring email from a feed, "RSS campaign").
- Batch fields: start date/time, batch quantity (emails per batch), repeat after (days/hours/minutes, minimum 1 minute), active weekdays, daily start and end time window, sender name, verified sender domain and email, subject, preview text, recipients.
- Drip rate limits: 1 min interval allows 1,000 per minute; 5 min 4,999 per minute; 6 to 10 min 5,000; over 10 min 10,000 per minute.
- Reschedule only at least 60 minutes before send. "Rate Limited Emails" doc covers throttling.
- AI Schedule (Conversations, one to one email): window of 12, 48 or 72 hours; sends at the recipient's engagement-high time; requires LC Email or Mailgun and 2-way sync off; email only; cannot be edited or deleted after confirm. Not available for campaigns (campaigns use Smart Send).
- Email Campaign Agent (Beta) in Ask AI: prompts a guided builder that checks sending domain, drafts on-brand copy, offers subject A/B test, audience selection, confirm summary card.

### 5.4 LC Email and deliverability (doc)

- LC Email is the native sending service (Mailgun-based infrastructure per brief; docs describe it as HighLevel's own service with a Mailgun alternative). Default for new sub-accounts. Alternatives: connect custom SMTP (Mailgun, SendGrid, Postmark) billed by the provider; SMTP stats show only opens/clicks; delivered/bounced need Mailgun or LC Email.
- Dedicated sending domain: Settings > Email Services > Dedicated Domain. Generates SPF, DKIM and optional DMARC DNS records (also CNAME for tracking/SSL). Verify button. Use subdomain. Multiple sending domains per account (marketing vs transactional).
- Pricing (3rd party): about $0.001 per email, usage billed; example $8/mo for weekly send to 2,000 contacts.
- Dedicated IP (doc): $59 per IP per month billed to agency (rebilling possible). Only agencies on $297 or $497 plans. Sub-account must have more than 10,000 contacts or 50,000 emails in the last 10 days (as the doc states). Recommended minimum 50,000 messages per week; about one IP per 1 million messages per month. Automated warmup alternating shared and dedicated IP. Dedicated IP links only to dedicated sending domain; multiple IPs rotate. Reverse DNS whitelabel exists.
- Warm-up and sending stage limits (doc): Stage 1 up to 100/hour and 1,000/day; Stage 2 300/hour and 2,500/day; warm-up up to about 4 weeks; domain warmup uses a fixed-stage model.
- Email validation: first-send verification toggle in Business Profile; re-validate every 90 days toggle; $2.50 per 1,000 validations.
- Diagnostics docs: low domain reputation, blacklisted domain/IP, mail loop, spam filter blocks, rate limited emails, email sending health. Risk tiers (low, medium, high) for accounts referenced in 3rd party content; the doc I read does not define them.
- Authentication: SPF, DKIM, DMARC (doc recommends `v=DMARC1; p=reject`), one-click unsubscribe headers (3rd party says some users find them missing).
- Unsubscribe link automatic; custom unsubscribe links via trigger links; DND per channel.
- Deliverability guidance numbers (3rd party): keep bounce under 2 percent, spam complaints under 0.1 percent.

### 5.5 Statistics

- Metrics (doc): delivered, opened (unique opens / delivered), clicked, conversion (default 5 day attribution window; most recent qualifying campaign wins), soft bounced, hard bounced, unsubscribed, skipped (DND or processing), spam, failed, replies, attributed revenue, revenue per recipient.
- Engagement analysis chart (delivered, opened, clicked lines), Summary and Details tabs (recipient-level export), Statistics side panel from campaign menu; unified Email Statistics dashboard; email dashboard widgets and custom report widgets.
- Opens are pixel based, affected by Apple Mail Privacy Protection. No inbox placement data (3rd party; need Google Postmaster Tools).
- SMTP stats limited to opens/clicks. Email events workflow trigger (delivered, opened, clicked, bounced, unsubscribed, spam, replied).
- Email Marketing V2 public APIs exist.

### 5.6 A/B testing for campaigns (doc)

- One variable at a time: subject or content. Up to six variations. Test audience slider (equal share per variation). Winner by unique open rate or unique click rate; duration 30 min to 24 hours; at least 40 contacts total and 10 per variation. Only Send Now or Schedule; not Batch or RSS. If metric yields no result the first variation wins.

### 5.7 Data entities (inferred)

```
EmailTemplate { id, locationId, name, folderId, builderType(drag|code|text), html, json, previewText, brandBoardId }
EmailCampaign { id, name, status, templateId, subject, previewText, sender{name,email,replyTo,domain}, audience{tags[],smartListIds[],excludeTags[]}, delivery{type(now|schedule|batch|rss), at, batch{qty, interval, days[], window}}, ab{variable, variants[], testPct, winnerMetric, duration}, stats{} }
EmailEvent { id, campaignId, contactId, type, ts, url?, bounceType? }
SendingDomain { id, domain, dkim, spf, dmarc, verifiedAt, dedicatedIpIds[] }
```

### 5.8 Pain points (Email)

- Deliverability is the number one complaint in third-party reviews: shared infrastructure, link tracking via shared tracking domains, lack of automatic warmup for some accounts (conflicts with doc claiming automated warmup for IPs). Recommended fixes always push users to self-manage DNS, subdomains, and warm-up.
- Builder described as functional rather than design-forward; Mailchimp seen as better in template experience.
- Sub-accounts can be suspended on provider blocks.
- Dedicated IP is expensive ($59), gated to higher plans and big volume thresholds.
- Validation is billed separately; email sends metered; no revenue attribution beyond a 5 day last-campaign window.
- Inconsistent docs on whether smart lists are evaluated at schedule or send time.
- A/B limited to subject or content, not both, and not available with batch send.
- Reschedule locked within 60 minutes.
- Menus and templates move constantly; Capterra reviewer cited having to pay for Twilio and Mailgun in earlier era (now LC Email/LC Phone, but cost transparency is still an issue).
- Email in the one to one inbox has separate rate limits, AI Schedule limited to Conversations.

---

## 6. SOCIAL PLANNER

### 6.1 Networks (doc)

Facebook, Instagram, Threads, Google Business Profile, LinkedIn (pages), TikTok (business), YouTube, Pinterest, HighLevel Community, Bluesky. X/Twitter is not supported for publishing (RSS doc states X is not supported; an older review article still mentions Twitter).

### 6.2 Layout and ways to create content (doc)

Marketing > Social Planner. Tabs include Planner (calendar, with Drafts, Scheduled, Published, Failed states), Approval (reviewer queue), Statistics, Settings (social accounts, notifications, watermarks, categories). Mobile app has a Social Planner (older list of 6 platforms in docs, probably outdated).

Content creation modes:
- Create New Post (select accounts, caption, links, hashtags, media, mentions/tags, customize per channel).
- Post types per platform: Post, Story, Reel, Shorts, carousel, video, GBP post (what is supported varies per platform).
- Publish now, schedule, draft, send for approval, recurring.
- Recurring posts (every day, week, month, year).
- Evergreen Category Queue: group posts under a category, publish on set days and time slots, loop at the end; prioritize new content to front or back; multiple variations rotate; edit; pause/resume; move whole queue to a new start date; public API for categories and queue.
- RSS Post: feed URL (RSS/Atom), channels, "End with" text, update interval 5 minutes to 1 day, max 1 to 5 posts per check, include description option, preview of 5 items, dedupe by GUID or link+title for 90 days, per-platform truncation.
- Bulk scheduling by CSV or XLSX: 90 posts per file; Basic CSV (content, date, media, OG link) and Advanced CSV (platform specific types, YouTube titles, tags, categories, first comment, thumbnailUrl, comma-separated image URLs, watermark); date formats flexible; errors flagged on review screens; Google Drive links no longer processed (use Media Library); no Pinterest board specification in CSV; upload at least about 10 min before earliest schedule (3rd party).
- Social Planner Templates through Template Library, Review & Schedule, import.
- Review posts: share reviews as social posts (Schedule your Review Post).
- Content AI (guided content questions) for captions.
- Media: optimization to platform requirements, watermarking (multiple watermarks), video thumbnail edit, link shortener with UTM, Best Time to Post.
- Mentions/tag profile, community posting.

### 6.3 Approvals (doc)

- Creator picks "Scheduled for Approval", sets date/time, approver, internal note; approver gets email (Settings > Notifications, template "Social Planner: Post Approval" in email templates).
- Reviewer sees Content > Approval tab: view, approve, reject, edit, change schedule. Rejected returns to the creator with comment. Approved goes to calendar.
- Bulk CSV: pick approver for the whole import.
- No formal multi-level approval or roles beyond a single approver per post.

### 6.4 Analytics (doc)

- Advanced analytics page: KPI overview (posts, likes, followers, impressions, comments), social post performance (weekly bars with daily engagement lines), link clicks by socials, link performance by campaign, number of posts/engagement/impressions/post reach week over week by platform, top performing posts (ranked by likes), engagement stats toggles, gender and age demographics (Instagram only, needs 100+ followers).
- Filters: accounts dropdown, platform selector (All or single).
- Per-platform data limits: TikTok business profiles only, 1 to 2 day lag; Pinterest n-2 lag and missing metrics; LinkedIn pages only, followers n-2; Threads and Bluesky limited; GBP post count not supported and "reach" counts actions; analytics weekly only; export not available.
- Dashboard widgets aggregated across platforms (no post level detail).

### 6.5 Comments (doc)

Unified comment inbox for posts published through Social Planner on Facebook, Instagram, LinkedIn, TikTok, Communities, Bluesky, Threads: reply, like (FB/IG/LinkedIn), threaded replies, sort Latest/Top, mark all read, search (3+ chars), mentions. Limits: no hide/delete; comments on natively published posts are not shown; Bluesky syncs last 15 posts every 6 hours; TikTok replies capped at 150 chars; Threads accounts need reconnect.

### 6.6 Account health

In-app and email alerts when token authorization is lost; scheduled posts cannot publish to disconnected accounts.

### 6.7 Data entities (inferred)

```
SocialAccount { id, locationId, platform, accountId, name, tokenStatus, connectedAt }
SocialPost { id, accounts[], type(post|story|reel|short|carousel), caption, perChannelOverrides{}, media[], link{short, utm}, status(draft|scheduled|published|failed|pending_approval|rejected), scheduledAt, approverId, approvalNote, categoryId, recurrence{}, error{code,message} }
CategoryQueue { id, categoryId, slots[{day,time}], items[], prioritizeNew, status }
RssSocialFeed { id, url, accounts[], suffix, intervalMin, maxPerCheck, includeDesc, seenGuids[] }
```

### 6.8 Pain points (Social)

- Failed posts are common and error text is often generic ("temporary error from Facebook", "Unexpected error"); causes cited: expired tokens (Facebook around 90 days), permission changes, reels failing on duration/aspect ratio, duplicate content within 12 hours, stuck posts; users must reconnect accounts repeatedly (3rd party guides).
- No hide/delete comments; native posts not synced; Bluesky sync only 15 posts every 6 hours.
- Analytics weekly only, no export, uneven per-platform support; no competitor benchmarking, hashtag analytics, or listening.
- CSV limited to 90 posts per file; Pinterest board not specifiable; Google Drive media removed; tags and categories do not survive snapshot import.
- Scheduled reels cannot edit the video after upload (3rd party).
- Queue posts cannot be individually rescheduled; calendar view cannot reschedule or rearrange queue items (doc).
- Single approver model only.

---

## 7. BLOGS

Doc "Blogs in HighLevel":
- Sites > Blogs. Blog site creation: title, optional domain (can connect later; remove then reconnect to switch), slug, meta description, start from scratch or template.
- Blog post fields: content editor (page width 736 px), URL slug (required), category (required, select or create), author (required, select or create), title and post description (required), canonical link, keywords (optional), SEO title, cover image with alt text, status Draft, Publish or Schedule.
- Edit: three-dot menu > Update Post (content) or Update Settings (author, category, slug, SEO) then Publish.
- Layout: Standard or Compact for list and post views; styling of blog cards (images, tags, headings, titles, descriptions, authors, publish dates); choose blog home and post pages.
- Placement: Blog Post List element on any website page or funnel step; URL structure follows host (e.g. abc.com/b/sample-slug). Author and category URL patterns like /blog/author/name.
- Import: from URL, from CSV (bulk). Ask AI can generate SEO friendly posts.
- Sites > Analytics supports Blogs asset type.
- Limitations (doc): no separate category pages ("planned"), custom values not supported in posts, forms and surveys cannot be added inside posts (custom code "coming soon"), no recommended image size, scheduled publishing only. Blog RSS output for the blog itself not documented.
- Pain: weak vs WordPress for content SEO (no category archives, no tags, no related posts documented, no comments, no scheduled republish); users who need serious content marketing use the WordPress add-on.

Entities (inferred): `Blog {id, title, domainId, slug}`, `BlogPost {id, blogId, title, slug, html, categoryId, authorId, seo{}, status, publishAt, cover{url, alt}}`, `BlogAuthor`, `BlogCategory`.

---

## 8. CLIENT PORTAL

Doc "Unified Client Portal Experience" (Labs):
- One login for customers: Dashboard, Courses, Communities, Billing items, Shared files, Account settings. Redesigned dashboard shows courses in progress, continue watching, community activity, pinned communities, billing items, shared files.
- Public Course and Community pages are crawlable with metadata; private content not indexed.
- Magic links (SSO magic links) per app: generate links for Courses, Communities, Affiliates, and "Custom Menu" magic links for sidebar items; one-click access without password.
- Custom Menu Links (agency level): title, icon, URL (http/https), open in iFrame, new tab or current tab; visibility in agency sidebar, sub-account sidebar or both; role limits (All, User, Admin); sub-account targeting; dynamic merge fields in URL (warning about leaking data via URLs). Used in SaaS plans too.
- Customer login for e-commerce stores exists as separate flow.
- Roadmap (stated): appointments inside portal, custom navigation links, deeper customization, expanded branding, richer community/event experience, more self-service.
- Client Portal domain (whitelabel domain type) and chat widget integration.

Pain points: customers' view is split by product (membership portal, store login, courses) historically; unified portal is still a Labs feature with limited branding, no appointments, no custom nav, no invoices/proposals consolidated documented. Portal for "client" (end customer of the sub-account) is not a project/deliverable portal like HoneyBook or Dubsado.

---

## 9. WORDPRESS HOSTING

Doc "WordPress Hosting Specs":
- Plans (add-on, no contract, activated in Agency > Reselling): Standard $10/mo (annual $9), 1 site, 12 GB per site; Utility $220/mo (annual $208), 25 sites, 60 GB pooled; Unlimited $497/mo (annual $414), unlimited sites, 500 GB pooled. Extra disk $12/mo per 25 GB.
- Shared: unmetered bandwidth (fair use), unlimited visitors, Cloudflare Enterprise CDN, free SSL, SFTP, daily backups with 30 day one-click restore (05:00 CST) and manual backups, staging included, full themes/plugins, 24/7 chat support, 99.99 percent uptime claim, site setup about 10 minutes, Linux VPS, migration by file upload.
- Tech: PHP 5.6, 7.4, 8.0 to 8.4, MySQL 8, unlimited workers and inodes, Imagick, standard extensions. No caching feature described.
- Features: Sites > WordPress; new site from template; multiple installs per sub-account; domain add in WordPress dashboard; LeadConnector plugin auto-installed (forms, chat widget, tracking); WordPress performance report; resell with agency-set price; client self-pay or agency pay.
- Pain: add-on cost; caching not described; doc has storage inconsistencies; WP plugin conflicts are users' burden; staging included but no documented git or CI.

---

## 10. ADS MANAGER (Marketing > Ad Manager)

### 10.1 Platforms and objects (doc)

- Meta (Facebook and Instagram): objectives Lead Generation, Website Traffic, Engagement, Sales. Formats: single image, video, carousel (up to 10 cards), lead forms, conversation forms. Structure campaign > ad set (up to 10) > ad (up to 10 per ad set). Facebook form (instant form) builder: greeting, questions, privacy policy URL, field mapping into HighLevel fields.
- Google Ads: Search campaigns supported; Demand Gen article exists (and "coming soon" in overview); additional assets (logos, images, call extensions, sitelinks), audience segments, multiple ad groups and ads (up to 10 ad groups, 3 ads per group), offline conversions.
- LinkedIn Ads: objectives Lead Generation and Website Visits; formats single image, video, carousel, lead forms.
- Creation flow: Marketing > Ad Manager > Connect Accounts (LeadConnector app permissions) > Create Campaign > platform > objective > Start from Scratch or template > audience, budget, schedule, creative > Publish (submits to platform for review; spend billed by the platform).
- Google Search fields: campaign name, bid strategy (Maximize Clicks default; optional max CPC), daily budget, start/end date, location or radius, EU political ad declaration, language, audience segments, gender and age. Ad group: base URL, keywords (positive/negative, broad/phrase/exact, bulk entry with dedupe). Ad: 3 to 15 headlines of 30 chars, 2 to 4 descriptions of 90 chars, final URL, display paths 15 chars x 2. Review screen then Publish.
- Templates: save campaigns to a template library; Ad Manager included in snapshots.
- Ask AI for Ad Manager: build campaigns from prompts, analyze performance.
- Billing: agency base cost $0; agencies resell with markup (Agency > Reselling, sub-account override, SaaS configurator). Ad spend paid by the sub-account to the platform.
- APIs for automation and reporting.

### 10.2 Statistics tab (doc)

- Home tabs: Campaigns and Statistics. Statistics shows Published and Paused campaigns, Performance Analytics and Conversion Summary charts, metrics table, drill into a campaign; Meta drill to ad set and ad; Google by campaign, ad group, ad, keyword.
- Filters: platform (Google/Facebook), Facebook page selector, date range. Column chooser. Export CSV (campaign table, leads, opportunities).
- Metrics: clicks, revenue, ROI%, CPC, CTR, sales, CPS, leads, results, CPL, impressions, spend, reach, frequency. ROAS mentioned in FAQ but not in table.
- Leads and sales icons open a modal listing leads and closed opportunities (this is the join from ad click to CRM revenue).

### 10.3 Ad reporting (legacy and attribution) (doc)

- Facebook Ad Reporting and Google Ad Reporting (Reporting > Ads Reports): require UTM templates added in the ad platform (Meta: tracking section; Google: tracking template, ideally account level). Names must be unique across campaign/ad set/ad; renaming mid flight breaks attribution (create new instead); campaign names over 250 chars cause discrepancies.
- Leads = contacts whose first attribution is paid and who came from that platform. Sales = opportunities marked WON that came from ad leads. Revenue = opportunity monetary value, not payment received. Client spend can be added manually (doc "add client spend"). Facebook sales require FB Lead Event workflow.
- Google call count is not linked to HighLevel call reporting; need number pool script.
- Troubleshooting docs exist for both.

### 10.4 Conversion APIs

- Meta Conversion API: workflow action "Facebook Conversion API" (events Funnel Events and Lead Events; custom mapping of FBCLID and lead id; access token and dataset id, or Ad Manager based connection that handles the token). Needs attribution data already on the contact (fbclid or paid social source). Funnel event pixel setup for CAPI. Conversion leads walkthrough.
- Google Ads offline conversions: workflow action "Add to Google Ads"; needs connected account and existing conversion action; match by GCLID, GBRAID, WBRAID; fixed or custom value per conversion. Create/manage offline conversions in Ad Manager.
- LinkedIn conversions are not documented in what I read.

### 10.5 Attribution (doc)

- Stored on the contact: First attribution (immutable first session) and Latest attribution (updates). Viewable in Contact > Activity.
- Source categories: Paid Search, Paid Social, Direct Traffic, Organic Search, Social Media, Referrals, Others, CRM UI, Third-Party. Rule order: gclid/wbraid/gbraid/msclkid or utm_source adwords => paid search; utm with google referrer => paid search; utm_source fb_ad/linkedin_ad/twitter_ad/reddit_ad or ctwa_clid => paid social; referrer social => social; referrer search engine => organic; other referrer => referral; none => direct; calls/SMS/email/WhatsApp/FB messages => Others; manual contact => CRM UI; integrations like Zapier => Third-Party.
- Fields: page URL, referrer, utm_source, utm_medium, utm_campaign, utm_content, utm_keyword, utm_matchtype, campaign_id, ad_group_id, ad_id, gclid, wbraid, gbraid, msclkid, ctwa_clid, session data for external tracking forms.
- Recorded only when a contact completes a form, survey, booking, chat (after submitting contact info) or order form in the same session. UTMs are case sensitive; do not add custom parameters to provided templates.
- Attribution and UTM can be used as filters on custom dashboard widgets. Email has its own attribution (5 day window, last eligible campaign).
- No true multi-touch model (first vs latest only).

### 10.6 Pain points (Ads)

- Search campaigns only for Google (no Performance Max, shopping, YouTube). Demand Gen added recently. No TikTok, Microsoft, Reddit or X native management.
- UTM template setup is manual in the ad platform and fragile: naming uniqueness, renames break attribution, 250-char limit, duplicates attribute one contact to several ads.
- Revenue is opportunity value, not collected payment; "sales" depend on users moving opportunities to WON.
- Metrics inconsistent between FAQ and table (ROAS). Only first vs latest touch; agencies export to Looker Studio or AgencyAnalytics for multi-touch (3rd party).
- Conversion API needs separate workflow setup and token handling.

---

## 11. REPORTING AND DASHBOARDS

### 11.1 Reports catalog (doc)

Reporting menu (names vary by version): Dashboard, Custom Reports, Attribution Report, Call Reporting, Agent Reporting, Appointment Report, Google Ads Report, Facebook Ads Report, Email Stats, Phone Call Report, Reputation overview, Funnel/Site analytics, Voice AI reports.

- Call Reporting: by assigned number (filter by phone number, custom name). Number pools: minimum 4 tracking numbers per pool; script on the site swaps number by source; Keyword column in Call Report. Call dispositions (custom dispositions marked coming soon in one article).
- Agent Reporting: by staff member; counts calls to contacts assigned to them plus made/received. Different from call reporting so totals differ.
- Google and Facebook ad reports as in section 10.3.
- Email stats (SMTP) track opens, clicks, replies, bounces; delivered inferred from opens.
- Dashboard widgets respect user permissions, "only assigned user" setting and selected date range. Location dashboard revenue = sum of WON opportunity values.

### 11.2 Dashboards and widgets (doc)

- Sub-account dashboard: edit dashboard > Add Widget > choose chart type (Numeric, Donut, Line, Bar, Table; custom objects also Horizontal Bar) > pick metric by category > filters > theme > save.
- Widget families: contacts, opportunities/pipeline, conversations, SMS, email, calls, appointments, funnel/website visitor data, custom objects (count, sum, average), Meta Ads (top campaigns table; ad spend, conversions, website purchases, clicks, impressions, reach, CPC, CPM, CTR, cost per conversion), Google Ads, Google Analytics, SLA (needs Conversations setting), Social Planner aggregates, reputation.
- Dashboard permissions: VIEW, EDIT, FULL, NO ACCESS. Multiple dashboards per sub-account available on all plans (doc claims all plans include multiple dashboards and custom reports; one article says custom metrics only $497).
- Custom metrics (doc): formula editor combining up to four metrics with operators and constants, multi-source KPIs (e.g. ROI, CPA), display as integer, float, currency or percentage, date property per metric, trend direction, clone, description, usable in dashboards, reports and snapshots. Plan gating ($497) is documented in one article and contradicted by another.
- Custom Report builder: from blank, template or an existing dashboard; cover page (logo, headers, background); pages (add, reorder, rename); elements menu (titles, sections); widget drag in; themes; send/schedule by email (frequency, delivery time, date range, widget-level date settings, compare-with, sender, subject, recipients, body, test email, save and schedule); PDF download; email preview link for non-login recipients.
- Limits: tables in PDF and email show first 100 records; no drill-down in PDF or email; PDF excludes images and iframes; embedded images should be JPEG or PNG; time zones differ across builder (browser), email (sub-account) and ad data (ad account).
- Snapshots can push dashboards and custom metrics to other sub-accounts.
- Revenue forecasting tab added April 2026 (3rd party).

### 11.3 Entities (inferred)

```
Dashboard { id, locationId, name, widgets[{id, type, metricKey, chartType, filters{dateRange, campaign, user}, theme, layout{x,y,w,h}}], permissions{} }
CustomMetric { id, name, formula[{metric, op}], format, dateProperty, trendPositive }
Report { id, name, pages[ {elements[], widgets[]} ], schedule{freq, time, dateRange, recipients[], compareWith}, theme, cover }
```

### 11.4 Pain points (Reporting)

- "Wide rather than deep": basic metrics; no cohort or custom SQL; limited to platform widgets (3rd party, competitor biased but repeated).
- Attribution is first or latest touch, no data-driven or position-based model; no cross-channel spend normalization; cost data only for connected ad platforms plus manual client spend.
- Reports emailed are snapshots; table caps at 100 rows; no interactive public share link without login except the email preview link.
- Dashboard share link requires authentication (doc), so agencies build scheduled PDFs.
- Discrepancy hazards: GA vs HighLevel sessions, revenue as opportunity value vs payments, time zone mismatches.
- Plan gating confusion for custom metrics/API access.
- Iframe-embedded forms break GTM triggers and external tracking (agency report).

---

## 12. MEDIA LIBRARY / MEDIA STORAGE

Doc "Media Storage and File Upload Limits":
- Limits table: Media Library images 100 MB, video 4 GB, audio 100 MB, documents 100 MB; Social Planner images 10 MB, video 1 GB; Sites and Funnels same as library; Courses images 50 MB, video 5 GB; form file upload 50 MB each.
- Types: images (PNG, JPEG, GIF, TIFF, WEBP, SVG, ICO, HEIC), video (AVI, MOV, MP4, MPEG, Ogg, WMV, WebM, M4V), audio (AIFF, MIDI, WAV, Ogg, M4A, MP3), documents (PDF, Office, Numbers, Google Docs types, RTF, TXT, CSV, ZIP), fonts (TTF, OTF, WOFF, WOFF2), vCard, JSON, CSS. Expanded support (60+ extra formats incl. RAW photos and CAD) with native previews missing for some.
- Features: folders, rename, move, search, sort; multi-select (move, download, delete up to 100 files within one folder); in-place edit of TXT, CSS, JSON, SQL, RTF keeping URL (previews over 5 MB lost); storage usage modal per module (Media Library, Conversations, Memberships, Contacts, Calendar) and by file type; Google Drive integration (view and organize owned files; rename and delete disabled; shared files not listed; disabled under Login As); media picker modal inside Funnels, Websites, Forms, Surveys, QR codes; drag and drop uploads; AI generated images, audio and video saved automatically (generated-audio-*.mp3, video thumbnails); email attachments over 20 MB become links; mobile app has a media library.
- Private files: created only via digital product setup, lock icon, private links expire after 10 minutes, cannot convert public to private or vice versa.
- Pain: no manual private toggle, no image editing or versioning documented, no CDN transformations/resizing presets documented, flat reporting of storage by module only, no tagging or AI search, no duplicate detection.

---

## 13. BRAND BOARDS (Design Kits)

Doc:
- Create blank, from preset template, or by importing from a website URL (auto brand extraction). Fields: primary and secondary logos (max 2, saved in a media folder named after the board), colors (min 2, max 10, renameable), fonts (min 1, max 5).
- Default board: first one created; only the default board's colors and fonts appear in email editor pickers; can change default. Used in emails, funnels, websites, Agent Studio (Brand Voice and Brand Kit), Social/AI content.
- Edits do not alter existing content, only future picks. Global Custom Colors are a separate mechanism that does propagate to existing items.
- Design Kits API v3 (create/read/update/delete colors and fonts per location).
- Delete is permanent.

Pain: low caps (10 colors, 5 fonts, 2 logos), no semantic tokens (primary, surface, text), no spacing/radius/button style tokens, no auto-propagation of changes, no per-brand guideline doc, one default per location.

---

## 14. AFFILIATE MANAGER

Doc:
- Marketing > Affiliate Manager. Objects: Campaigns, Affiliates, Referral links, Leads, Customers, Commissions, Payouts.
- Campaign setup: source (Funnels, Websites, Stores, Forms, Calendars, External Websites), tracking rules, commission model Pay Per Lead (form/survey/booking) or Pay Per Sale, flat or percentage, recurring, product-specific rates (override default), per-affiliate custom rates, multi-tier up to 7 tiers, assigned affiliates.
- Affiliate portal: affiliates see campaign data, referral links, commissions, payouts, leads, customers (accessed through client portal magic link).
- Leads attributed when a contact completes an eligible action via the affiliate link; admins can add leads manually.
- Payouts: generated from payout terms, Pending tab for review, pay through PayPal automatically or manually (Stripe, bank transfer, Wise, check). Bulk actions approve, deny, delete; bulk actions do not notify affiliates.
- Refund handling is manual (refunds for one-time products and subscriptions are not auto reflected). Cookie duration not documented in the article I read.
- Import from FirstPromoter exists (campaigns, affiliates, commissions). Affiliate automations (workflow triggers) exist.
- HighLevel's own agency affiliate program (40 percent level 1 recurring, 5 percent level 2, paid on the 15th) is separate (3rd party).

Entities (inferred): `AffiliateCampaign`, `Affiliate { id, contactId, status, customRates }`, `Referral { affiliateId, campaignId, contactId, ts }`, `Commission { id, affiliateId, orderId|leadId, amount, tier, status(pending|approved|denied|paid) }`, `Payout { id, affiliateId, method, amount, status }`.

Pain: manual refund clawback, bulk actions silent, no fraud tooling (self-referral, coupon leakage), cookie window undocumented, payout methods mostly manual outside PayPal.

---

## 15. PROSPECTING TOOL

Doc:
- Agency: Prospecting tab. Sub-account: Marketing > Prospecting. Search by keyword or brand plus location (city, postal code, address, map point, "near me" in Labs) with radius up to 31.1 miles; Labs: up to 60 leads per search, 15 per page, bulk save up to 15; manual business entry.
- Each prospect gets a Marketing Audit Report in seconds: Online Health score, listings (count, accuracy, missing across 70+ directories), reviews (Google Business Profile and Facebook), website hosting detection (WordPress, LeadConnector, AI Studio, Webflow, Wix, Squarespace, Framer; toggleable under Report Settings), point of contact (role, expertise, socials, phone, email).
- Prospect cards: Open, Won, Lost status. Share Report link. Prospect AI recommends 2 to 3 prospects weekly by niche and zip (premium). Prospect Score sort and duplicate check. Prospecting widgets embeddable on a website (lead capture of audits). Workflow action "Generate Marketing Audit Report".
- In sub-accounts: save leads as contacts, trigger workflows (welcome SMS with audit link), add to opportunities.
- Limits: basic plan 50 prospects per day, premium unlimited; free tier caps premium reports at 5 per month.
- Pain: Google Business Profile-centric data only (no email/phone enrichment at scale, no social/firmographic data), status not synced to opportunities (article unclear), many parts still in Labs, small result sets per search.

---

## 16. LOCAL SEO / LISTINGS AND REPUTATION MANAGEMENT

### 16.1 Listings (Yext and Uberall) (doc)

- Pushes NAP (name, address, phone), hours and other business data to 70+ directories and publishers; view live listings; approve or reject publisher suggestions (Google Business Profile, Facebook, Yelp edits); duplicate suppression tab (Yext only); listings analytics (impressions, calls, clicks, directions; Yext only).
- Resell: plans Monthly, Smart Saver (6 month term), Annual Advantage (12 month); price slider per plan with client price, cost and profit; per sub-account override; price changes affect future activations only. Minimum commitment 30 days for agencies.
- Cancel: info stops updating in directories; resolution guides for Yext canceled or duplicate states.
- Listings summary is on Reputation > Overview when enabled (the Manage listings button is agency only). Ask AI cannot manage listing sync.
- Pain: dependency on third parties (Yext and Uberall) so features differ by engine (analytics and duplicate suppression Yext only); opaque states (canceled/duplicate) needing step by step recovery; no own citation audit or schema/markup; no rank tracking or local pack/grid reports; no GBP posts/Q&A/photos manager beyond Social Planner GBP posting.

### 16.2 Reputation Management (doc)

Menu: Reputation > Overview, Requests, Reviews, Widgets, Listings (when enabled), Settings (Review Link, SMS Requests, Email Requests, WhatsApp Requests, Reviews AI, Integrations). Guided Review Setup Wizard appears once in new sub-accounts (connect Google/Facebook, review link, first request, Reviews AI, widget, more platforms) and cannot be reopened.

Overview tiles: Invite Goals (non-editable steps), Reviews Received, Online Listings, Avg Rating (doc formula description is inverted), Sentiment (LLM scores written reviews; stars for unwritten: 4 to 5 positive, 3 neutral, 1 to 2 negative), Invite Trends, Review Trends (monthly bars), Latest Review Requests, Latest Review. Each tile has a time filter menu.

Review sources: Google Business Profile and Facebook natively; others (Yelp, TripAdvisor) via integration/region; manual reviews (Labs) to add offline reviews; video testimonials collector (record or upload by email, SMS or WhatsApp; Responses tab; widget visibility toggle).

Review requests:
- Channels: SMS, email (each with toggle), WhatsApp (separate settings; "coming soon" in marketing page but a Settings tab exists).
- Send from Reputation > Requests (bulk or single), from contact record, or via workflow action "Review Request" (e.g. on appointment status change).
- Cadence: initial timing (SMS immediate, email delay e.g. 1 hour), repeat interval in days, maximum retries, stops once click detected; template per retry slot; request with image (MMS).
- Merge field `{{reputation.review_link}}`; email "Review Link" element as CTA; multiple review links in one email (Google, Facebook, others). Review link either Review Balancing across platforms or a single custom link. Default sender number and email.
- QR codes for review link (digital QR for maximizing reviews).
- Spam detection of reviews: flagged reviews excluded from AI replies.

Review replies and Reviews AI:
- Suggestive mode (staff generate up to 4 AI suggestions per review for free) and Auto-Pilot (auto reply rules by star rating, wait time, footers, source). Pricing 1 cent per sent AI response; heavily edited drafts count as manual. Drip Mode answers old unreplied reviews on a schedule with limits and agent settings. Custom Reviews AI agents with tone and sentiment rules and visibility of which agent wrote each reply. Sentiment categorization and AI suggested responses.
- Workflow triggers for Google and Facebook reviews (Review Received). Share review as social post via Social Planner.

Review widgets (doc): types List, Grid, Masonry, Carousel, Slider, Flash, Legacy, plus newer Floating Badge (position, rotation interval) and Slider (interval). Tabs: Layout (summary type short/detailed/action points, summary position, review source, widget type, max reviews, minimum rating, powered-by), Content (title, heading, description, header with average rating, total count, Write a Review button, position, slider interval), Appearance (theme Light/Dark/Custom, font, colors), Settings (display date, reviewer icon, exclude no-description reviews, embed code). Templates as a starting point; embed via HTML block or on external sites. AI summaries update when review edited.

Data entities (inferred): `Review { id, locationId, source, externalId, rating, text, reviewer{name,avatar}, createdAt, reply{text, by(ai|human), agentId}, sentiment, spamFlag }`, `ReviewRequest { id, contactId, channel, templateId, sentAt, clickedAt, attempt }`, `ReviewWidget { id, type, filters{}, theme{}, embedKey }`, `ReviewsAiConfig { mode, rules[{stars, waitMin, footer, tone}], agentId }`.

Pain points:
- Only Google and Facebook are first-class review sources; Yelp, Trustpilot, TripAdvisor and industry sites are region/limited. WhatsApp and some features still labelled coming soon or Labs.
- Overview tiles are not editable (goals fixed), doc formula error for average rating, no competitor benchmarking, no review velocity vs competitors, no review gating compliance guidance, no negative review dispute workflow.
- Wizard one-time only; AI auto-reply risk (platform policy, brand tone) with only footers and tone controls.
- Reviews are metered (1 cent per reply) in addition to base fees.

---

## 17. CROSS-MODULE PAIN POINTS AND PRODUCT-LEVEL THEMES

1. Learning curve and clutter: G2 summary says steep learning curve; Capterra reviewers call UI clunky/cluttered, 2 to 4 weeks to get comfortable. Menus rename and relocate (releases several times a week), breaking SOPs and training videos.
2. Support: G2 reviewers rate frontline support as weak; vendor admitted need to improve escalation. Premium support costs $500/month (3rd party).
3. Versioned products with inconsistent behavior: Funnels V1 vs V2, quizzes vs forms, legacy vs new widgets, Labs features with partial availability, docs that contradict each other (smart list timing, batch limits, custom metric gating, A/B max variants).
4. Cost opacity: wallet metering for email, SMS, AI, ad management resale, validation, dedicated IP, WordPress storage; users surprised by usage bills.
5. Builders: functional but not best-in-class; template quality, no tablet breakpoint, limited design features, performance (LCP) behind dedicated tools.
6. Deliverability and tracking infrastructure shared across tenants; tracking domains and IP reputation influence outcomes.
7. Reporting breadth over depth; first/last touch only; manual UTM hygiene.
8. Social API fragility (tokens, permissions, platform rules) with weak error explanations.
9. Gaps explicitly stated: blog categories, forms inside blog, hide/delete social comments, multivariate tests, Performance Max, true multi-touch, analytics export for social.

Items I could not verify this session (do before building): ideas.gohighlevel.com official changelog entries for 2026; Stoplight API schemas (for exact field names of funnels, forms, social posts, emails, trigger links, media, blogs endpoints); marketplace app listings; Reddit r/gohighlevel threads; full G2 and Capterra pages (403). Recommend a second pass to pull the OpenAPI spec from the public GitHub repo (GoHighLevel/highlevel-api-docs) to turn the "(inferred)" entities above into exact schemas.

---

## 18. OPPORTUNITIES TO DO BETTER

Grouped by module, concrete and buildable.

### 18.1 Platform and UX

1. One consistent navigation model with stable URLs and a changelog-aware "what moved" banner. Ship a global command palette (Cmd+K) that searches every asset (funnel, page, form, email, post, review) and every setting. HighLevel's menu churn is a repeated complaint, so make renames cheap and keep redirects.
2. Single "Assets" model: every builder artifact (page, form, email, social post, QR code) is a typed asset with folder, tags, owner, status, version history, audit log, usage graph ("where is this form used"). HighLevel has audit logs only for funnels and websites, and no usage graph for forms.
3. A unified, visible "Setup health" checklist per sub-account (domain DNS, email auth, social token expiry, review sources, tracking template, pixel) with one-click fixes. Replace the one-shot wizard that cannot be reopened.
4. Make Labs/beta features explicit with a stable flag registry; no silent v1/v2 splits (funnels V1/V2, form logic v1/v2). Migrate automatically, never strand customers.
5. Honest usage meter: show estimated cost before sending (email, SMS, AI, validation) and a monthly forecast with hard caps per sub-account.

### 18.2 Sites, funnels, websites

6. Single page builder for both funnels and websites with the same capabilities (A/B split, blog, store, upsell all work everywhere). Remove the "websites cannot split test, funnels cannot blog" asymmetry.
7. Real tablet breakpoint plus fluid typography and spacing tokens; container queries; per-breakpoint visibility. Show a side by side desktop/tablet/mobile preview.
8. Performance by default: edge rendered static output, automatic image resizing and WebP/AVIF, lazy loading below the fold, LCP image preload, critical CSS, deferred widgets (chat loads on interaction by default), per-page "performance budget" panel with Lighthouse-like score before publish. Target 90+ mobile with chat and pixels (HighLevel lands near 55 to 65 with them).
9. Experimentation done properly: A/B and multivariate, server-side assignment (no path redirects to avoid ad-policy blocks), significance (frequentist or Bayesian), minimum sample guardrails, auto-winner with approval, segment breakdowns, and the ability to test any block, not just whole pages. Support split testing across steps (journey tests), not only page vs page.
10. Funnel visualization: step graph with drop-off, revenue per step, and branch performance (accept/decline upsell), cohort of visitors and replay-lite (scroll map, click map, session recordings built in so users do not need Clarity).
11. Design system layer: brand tokens (colors, type scale, spacing, radius, shadows, button styles) that propagate live to pages, forms, emails and widgets. Brand boards in HighLevel do not retroactively update and cap at 10 colors and 5 fonts; make tokens semantic with a "propagate" toggle and diff preview.
12. Better templates: curated, industry-tagged, performance-tested, accessible (WCAG contrast checks), with AI personalization from the brand kit and a URL import that actually re-creates structure. Offer a quality score and ratings for templates (including marketplace-style community templates with revenue share).
13. AI builder that outputs editable, structured pages (not 60 percent complete): include real stock imagery from the brand library, form wiring, workflow trigger scaffolding, tracking, SEO and schema in one pass, with a checklist of what remains.
14. Import tools: ClickFunnels, Leadpages, Unbounce, WordPress, Webflow importers with a fidelity report (what mapped, what did not).
15. SEO suite for sites: sitemap and robots editor, schema.org JSON-LD blocks (LocalBusiness, FAQ, Product, Review), redirects manager with bulk CSV, hreflang, canonical controls, Core Web Vitals per page, broken link checker, internal link suggestions, OG preview.
16. Accessibility: automatic alt text suggestions, contrast checker, keyboard navigation test, skip links, ARIA on forms and widgets.
17. Custom code with safety: scoped code blocks, version history, CSP-aware loader, per-page script manager with consent-mode gating, test/live separation.

### 18.3 Forms, surveys, quizzes

18. One form engine for forms, surveys and quizzes with multi-step, scoring, logic and payments. Ship a visual logic map (branching diagram) rather than rule lists; allow calendar and payment fields in logic (HighLevel excludes calendar).
19. Embeds that update live (versioned embed script, not static code) and a no-iframe, shadow DOM embed so host CSS, GTM and attribution work. Offer server-side event forwarding.
20. Partial submissions, drop-off analytics per field, autosave and resume links, spam protection (honeypot, rate limit, invisible captcha) by default, file upload scanning, e-signatures, PDF generation of answers.
21. Quiz and survey result pages as full pages in the page builder (not a limited results template), with dynamic tokens, shareable result cards, and referral loops.

### 18.4 Email

22. Treat deliverability as the headline feature: per tenant isolated sending domains by default (no shared tracking domain), automatic SPF/DKIM/DMARC checker with registrar integrations (Domain Connect, Cloudflare API), automatic warmup schedule visible in UI, seed-list inbox placement testing, Google and Microsoft postmaster integration, blocklist monitoring with alerts, bounce and complaint auto-suppression, and a per-send "risk score" before sending. Offer dedicated IP pools by volume, not by plan tier.
23. Email builder: a modern block editor with real design system, reusable global blocks, dynamic content blocks (per segment), AMP-free interactive blocks that degrade gracefully, dark mode preview, Litmus-style client previews, accessibility lint, spam-word lint, image alt enforcement, link checker. Keep the HTML and plain text editors but sync all three modes.
24. Sending: segment evaluated at send time with a preview of exact count and sample contacts; throttle presets by domain reputation; send-time optimization for campaigns (not only one-to-one); holdout groups; multivariate (subject + content + from name) tests with auto-winner and a reschedule that works up to a minute before send.
25. Analytics: revenue attribution with configurable windows (not fixed 5 days), click maps, device and client breakdown, Apple MPP aware open estimates, domain-level engagement, list health score, and a deliverability dashboard (reputation by mailbox provider).
26. Transparent usage: price per email shown in the composer; auto validation on import at lower cost; included monthly allowance per plan.

### 18.5 Social planner

27. Resilient connectors: proactive token refresh, pre-flight validation of media and aspect ratio per platform, human readable error messages with a "fix it" action, automatic retry/backoff, and a failed-post inbox. Show platform policy hints (duplicate content rules, hashtag limits) inline.
28. Unified composer and calendar with drag to reschedule (including queue items), per-platform previews, internal comments on drafts, multi-step approval chains with roles, client-facing approval links (no login), version history and rejection reasons.
29. Real analytics: daily granularity, export (CSV/PDF), post-level reports, competitor and hashtag benchmarking, best-time-to-post per account with explainability, UTM auto-tagging with funnel revenue attribution (connect post to opportunity revenue).
30. Inbox: unified social inbox including native posts, hide/delete/moderation rules, saved replies, sentiment and AI suggestions.
31. Content ops: asset library with campaigns, evergreen queue with expiry and performance-based recycling, RSS with templates and filters, bulk import beyond 90 posts with validation preview, AI repurposing (blog to posts, review to branded image).
32. Add X, Reddit, Mastodon, Snapchat, WhatsApp channels and Telegram, plus GBP posts with offers, products and Q&A.

### 18.6 Ads and attribution

33. Server-side tracking built in: first-party collection script on customer domain, automatic capture of click IDs (gclid, fbclid, ttclid, msclkid, li_fat_id), stored on the contact and on every session; automatic CAPI/offline conversion upload for all major platforms without hand-built workflows; deduplication by event id.
34. Multi-touch attribution (first, last, linear, position-based, time decay, data-driven) with a journey view per contact and per opportunity, plus MMM-light for budget guidance. Let users pick models per report and compare.
35. Ads manager breadth: Meta, Google (Search, PMax, Demand Gen, YouTube), LinkedIn, TikTok, Microsoft, Reddit; creative library with AI variations, automated rules (pause when CPA > X), budget pacing alerts, and automatic UTM injection via platform APIs so users never paste tracking templates or worry about names.
36. Closed loop reporting that uses collected payments (not just opportunity value), with refunds and LTV, and ROAS/MER/CAC payback charts.
37. White-label client ad reports with live links (read-only, no login, expiring tokens), annotations, and plain-language summaries from AI.

### 18.7 Reporting and dashboards

38. Dashboard builder with free grid layout, drilldown on any widget, cross-filter, saved filters, dashboard-level date and segment controls, shareable public/read-only links with permission scopes, and embed in client portal.
39. Metric layer: governed definitions (like a semantic layer) that powers dashboards, reports, workflows and API; formulas with unlimited inputs; custom SQL widget for power users; export to BigQuery/Snowflake/Sheets/Looker Studio connector as a first-party feature (HighLevel agencies pay for third-party reporting tools).
40. Reports as web pages (interactive), PDFs without row caps, scheduled delivery, narrative AI commentary, and white-label cover pages. Time zone handling consistent and visible.

### 18.8 Media, brand, content

41. DAM-grade media library: tags, AI auto-tagging and search, duplicate detection, image editor (crop, resize presets, background removal), responsive derivatives via CDN, usage graph ("used in 5 pages"), versioning, expiring/private links with ACL, video transcoding with thumbnails and captions, shared libraries across sub-accounts.
42. Brand kit v2: semantic tokens, multiple brands per location, voice guidelines, approved templates lock, live propagate with preview/diff, export to Figma.
43. Blog: categories, tags, archives, related posts, author pages, RSS, comments, forms and custom code in posts, scheduled republish, internal linking suggestions, content scoring, bulk import with redirects, AI draft with SEO brief.
44. Client portal: appointments, invoices, proposals, files, tasks, project status, messaging, branded domain and mobile PWA; allow custom navigation links and widgets.
45. WordPress: if offered, include caching, image optimization, staging with promote, git deploy, plugin vulnerability monitoring, performance reports tied to Core Web Vitals; or skip WordPress and make the native site builder good enough.

### 18.9 Affiliate, prospecting, listings, reputation

46. Affiliates: coupon-based and link-based attribution with configurable cookie windows, fraud checks (self-referral, IP/device), refund and chargeback clawbacks, tiered rules builder with simulation, automated payouts (Stripe Connect, Wise, PayPal), affiliate recruiting pages, creative asset library, leaderboard and notifications on bulk actions.
47. Prospecting: enrich beyond Google Business Profile (email finder, tech stack, social, ad library, reviews from Yelp), AI scored fit, auto-personalized audit reports as shareable web pages, sequences that start from a prospect, and CRM sync that updates opportunity stages.
48. Listings and local SEO: own citation manager or multi-vendor abstraction, GBP posts, Q&A, photos and attributes management, local rank tracking grids, review velocity, call tracking attribution into GBP, schema generator.
49. Reputation: support Yelp, Trustpilot, TripAdvisor, industry sites, App stores; competitor benchmarking; review-gating-safe request flows (policy compliant); smart routing of negative sentiment to private channel and ticket; response SLA tracking and templates; AI reply with brand voice and human approval queue; widgets as SEO-friendly server-rendered markup with schema (HighLevel widgets embed via script), review-to-social image generator, editable goals on the overview, and video testimonials with auto captioning and clipping.

### 18.10 Developer and data

50. Publish a typed public schema (OpenAPI plus webhooks) for every asset type from day one and a versioned event bus; every UI action should be available as an API and event. Provide sandbox sub-accounts for agencies and a migration API that preserves ids when moving between sub-accounts (snapshots in HighLevel lose tags and categories).

### 18.11 Suggested MVP slicing for our build (marketing and sites scope)

Phase 1 (core loop, highest value): page builder (funnel and website unified) + forms engine (forms/surveys/quizzes) + domains/SSL + analytics + trigger links + media library + brand tokens + order form with bump and one-click upsell + email builder and campaign sending on a managed sending domain.
Phase 2: A/B and multivariate, blogs, QR codes, chat widget, Social Planner with 5 networks (Facebook, Instagram, LinkedIn, Google Business Profile, TikTok) + approvals + queue, reviews (Google and Facebook) with requests and widgets, attribution and dashboards.
Phase 3: Ads Manager (Meta and Google Search), affiliate manager, prospecting, listings partner, client portal, WordPress/hosting decisions, custom metrics, AI agents for campaign creation and review replies.

---

## 19. APPENDIX: Selected facts and numbers to preserve (quick lookup)

| Topic | Fact | Source type |
|---|---|---|
| Agency plans | $97 / $297 / $497 per month; API and dedicated IP need $297+; custom metrics noted at $497+ in one article | doc + 3rd party |
| Email unit cost | about $0.001 per email | 3rd party |
| Email validation | $2.50 per 1,000; first-send or 90 day re-validation | doc |
| Dedicated IP | $59 per month per IP; plan and volume gates | doc |
| Warm-up stages | Stage 1 100/hr 1,000/day; Stage 2 300/hr 2,500/day | doc |
| Batch drip rate limits | 1,000 per min at 1 min interval up to 10,000 per min above 10 min | doc |
| A/B email | up to 6 variants, min 40 contacts, 30 min to 24 h test duration, subject OR content | doc |
| AI Schedule windows | 12, 48, 72 hours | doc |
| Social bulk CSV | 90 posts per file, csv or xlsx | doc |
| RSS social | check every 5 min to 1 day, 1 to 5 items per check, dedupe 90 days | doc |
| Social analytics | weekly only, no export, demographics Instagram only with 100 followers | doc |
| Google Search ads | 10 ad groups, 3 ads per group, 15 headlines at 30 chars, 4 descriptions at 90 chars | doc |
| Meta ads | 10 ad sets per campaign, 10 ads per ad set, carousel up to 10 cards | doc |
| Attribution | first and latest only; email window 5 days | doc |
| Number pool | minimum 4 numbers | doc |
| Custom report tables | first 100 rows in PDF/email | doc |
| Custom metric | up to 4 metrics per formula | doc |
| Media | image 100 MB, video 4 GB (library); social image 10 MB, video 1 GB; private link expiry 10 min; multi-select 100 files | doc |
| Brand board | 2 logos, 2 to 10 colors, 1 to 5 fonts | doc |
| Affiliate | up to 7 tiers; PayPal automatic, others manual | doc |
| Prospecting | 31.1 mile radius; 50/day basic; 60 results per search in Labs | doc |
| Listings | 70+ directories; plans monthly, 6 month, 12 month | doc |
| Reviews AI | 1 cent per sent reply; 4 free suggestions per review | doc |
| WordPress hosting | $10, $220, $497 per month tiers (annual $9, $208, $414) | doc |
| Funnel split test | cookie assignment, funnels only, domain required, no winner logic documented | doc |
| Page speed (one author) | about 68 to 78 mobile clean, 55 to 65 with chat and pixels vs Unbounce 82 to 91 | 3rd party |

## 20. Source list (URLs consulted)

Official help center (help.gohighlevel.com/support/solutions/articles/...):
155000001633 (websites overview), 155000005057 (launch a funnel), 155000006713 (Funnel and Website AI), 155000008367 (create pages in page builder), 48001230918 (split testing in funnels), 155000003094 (site and funnel analytics), 155000005698 (stats definitions), 155000007238 (one-step order form), 155000005767 (order bumps), 155000006914 (order upsell in forms), 155000002951 (enhanced form builder), 155000004090 (right sidebar form and survey builder), 155000001314 (conditional logic v2), 155000004126 (quiz builder guide), 155000004750 and 155000006615 (quiz scoring and results), 155000004102 (chat widget), 155000004583 (QR codes), 48000981404 (trigger links), 48001220286 (blogs), 155000008402 (unified client portal), 48001185767 (custom menu links), 48001231366 (WordPress hosting specs), 48001216629 (media storage limits), 155000003136 (brand boards), 155000000087 (email builder), 155000006657 (email elements), 155000006659 (campaign statuses), 48001215379 (batch schedule), 48001230348 (email A/B), 155000007168 (AI schedule), 155000006670 (email campaign agent), 155000001021 (email sending guide), 155000001152 (dedicated IP), 155000006834 (email statistics), 155000005063 (Social Planner setup), 155000005542 (advanced CSV), 48001229834 (post approval), 155000001052 (RSS social posts), 155000005514 (category queue), 155000005654 (best time to post), 155000005008 (link shortener), 155000006433 (comments), 155000004101 (social analytics), 155000002433 (Ad Manager overview), 155000003631 (ad statistics), 155000004543 (Google search campaign), 155000002435 and 155000002439 (Meta campaigns and forms), 48001219997 (attribution source), 48001204042 and 48001219312 (Facebook and Google ad reporting), 155000002087 (reporting FAQs), 155000006608 (Meta ad widgets), 155000003965 (custom reports), 155000005903 (custom metrics), 48000981393 (call tracking number pool), 155000003637 (affiliate manager), 48001231875 (prospecting), 48001216623 and 155000001901 (listings), 48001222767 (reputation overview), 155000005201 (review setup wizard), 155000005684 and 155000000997 (review widgets), 48000980328 (review requests), 155000001074 (Reviews AI).

Third-party (soft evidence): automatethejourney.com (split testing, email marketing, landing page builder review 2026), ghlscaleup.com (funnel builder), netpartners.marketing (disadvantages, release radar), growthable.io, consultevo.com, suped.com and inboxally.com (deliverability), segmetrics.io and coupler.io (reporting), G2 and Capterra review excerpts as surfaced by search.
