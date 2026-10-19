# UI and UX principles

The incumbent's most repeated complaints are clutter, a steep learning curve, menus that keep moving, slow screens and a patchwork of old and new modules. We win by being the calmer, faster product. Every screen is reviewed against this page.

## Principles

1. **Small core, progressive disclosure.** A new workspace shows six items: Inbox, Contacts, Pipeline, Calendar, Automations, Reports. Everything else (Sites, Email, Social, Payments, Courses, Reputation, Ads...) is switched on from **Apps** and then appears in the sidebar. Roles only see what they can use.
2. **Keyboard first, mouse friendly.** `Ctrl/Cmd+K` command palette searches every record, asset and setting and runs actions ("new contact", "assign to me", "go to pipeline settings"). `j/k` in lists, `e` archive, `a` assign, `s` snooze, `/` search, `?` shows every shortcut. Shortcuts are configurable.
3. **Fast is a feature.** Budgets: p95 route change under 300 ms, inbox interactions under 100 ms with optimistic updates, lists virtualized, published pages 90+ mobile Lighthouse with the chat widget installed. Budgets run in CI.
4. **One design system, everywhere.** Same components in the app, page builder, client portal, emails and the mobile PWA. No legacy islands.
5. **Stable navigation.** Built-in sidebar items can be pinned, hidden and reordered per user and per role. Renamed pages keep redirects; a "what moved" note shows once.
6. **One settings hub.** Searchable, deep-linkable, with every setting in exactly one place. Setup health (DNS, email auth, A2P, social tokens, payment account) is a live checklist with one-click fixes, never a one-shot wizard.
7. **Safe by default.** Every destructive or bulk action shows a preview with counts, runs as a job with progress, and can be undone (trash with 30-day restore, merge undo, import rollback, template push rollback).
8. **Show the cost before it happens.** Any send that costs money (SMS, email, AI, calls) shows the estimate inline before confirming.
9. **AI is a colleague, not a separate module.** Ask AI lives in the palette and on every record; every AI action is logged, explainable ("why"), and reversible. AI drafts, a human approves, unless the workspace turns on autonomy for that action.
10. **Empty states teach.** Every empty screen offers a one-click starter (template, sample data, import) and a 30 second explanation. Vertical starter kits (home services, dental, real estate, coaching, agency) produce a working setup in under 15 minutes.

## Layout

```
+---------+-----------------------------------------------+
| sidebar | top bar: workspace switcher, Ctrl+K, Ask AI,  |
| (pinned |          notifications, help, profile         |
|  items, +-----------------------------------------------+
|  Apps,  | page header: title, saved views, primary CTA  |
|  Settings) ---------------------------------------------+
|         | content (list / board / detail split view)    |
+---------+-----------------------------------------------+
```

- Records open in a split view (list stays visible) and have a stable URL. `Esc` closes.
- Detail page: header with key fields and actions, left column properties, centre timeline (messages, notes, calls, emails, events), right column associations, tasks and AI summary.
- Lists share one table component: column chooser, sort, filters, saved views (server side, shareable), inline edit, bulk bar.
- Phones get the same app as a PWA: bottom tab bar (Inbox, Contacts, Calendar, Tasks, More), sheets instead of dialogs.

## Visual language

- Fonts: Geist (UI, headings at 600) and Geist Mono (ids, code, numbers in tables), same as the other SROT AI products.
- Light theme is the default; dark theme is complete (app, builders, portal, emails preview). A saved choice wins.
- Tokens in CSS variables: color (neutral scale + one accent + success/warning/danger/info), radius, spacing (4 px grid), shadow, type scale. White label = a different token set plus logo, favicon, login screen and email footer, edited in one theme editor with live preview.
- Density toggle (comfortable, compact) per user.
- Accessibility: WCAG 2.2 AA contrast, full keyboard paths, visible focus, ARIA on every widget, reduced motion respected.

## Review checklist for every PR that touches UI

- [ ] Works at 1280 px and 375 px, light and dark.
- [ ] Keyboard only path works; focus is visible.
- [ ] Empty, loading, error and permission-denied states exist.
- [ ] What a role may not do is hidden or disabled with `can(capability)` from `lib/capabilities.ts` (the caller's capabilities from `GET /api/v1/me/capabilities`), never guessed from a role's name. The server still refuses it; `can` only avoids offering it. A screen that must not show anything before it knows reads `ready`.
- [ ] Destructive actions have preview and undo.
- [ ] No new one-off component when a design-system one exists.
- [ ] Route meets the performance budget.
