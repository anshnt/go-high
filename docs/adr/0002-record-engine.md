# ADR 0002: One record engine for contacts, companies, deals and custom objects

Status: accepted (2026-10-16). Modules: 07 records, 08 search and views, 09 import and dedupe, 10 pipelines.

## Context

The incumbent grew from a contact table. Companies, opportunities and custom objects arrived later with their own screens, filters, import paths and API shapes, a cap of 10 custom objects, and opportunities that cannot exist without a contact. Our plan promises one engine with the same list, filters, views, associations, timeline, permissions and API for every object, and no object cap.

## Decision

### Objects and fields are data

```
objects      id, workspace_id, key, singular, plural, icon, is_system, primary_field, archived_at
fields       id, workspace_id, object_id, key, label, type, options jsonb, rules jsonb,
             is_system, position, archived_at            unique (object_id, key)
```

- Each workspace starts with system objects `contact`, `company` and `deal`, seeded by the workspace template. A custom object is a row in `objects`, so there is no cap.
- Field types: `text`, `long_text`, `number`, `money`, `date`, `datetime`, `boolean`, `select`, `multi_select`, `email`, `phone`, `url`, `user`, `record` (link), `file`, `formula`, `rollup`, `stage`.
- `options` holds type settings (select choices with colors, currency, number format, the linked object for `record`). `rules` holds validation, conditional required and conditional visibility, written in the filter language described below.
- Archiving a field hides it everywhere and keeps its values. A purge job deletes the values after 30 days.

### Records live in one table

```
records      id, workspace_id, object_id, display_name, values jsonb,
             email_norm, phone_e164,                    -- contact identity keys
             owner_id, created_by, created_at, updated_at, deleted_at,
             search tsvector GENERATED ALWAYS AS (
               setweight(to_tsvector('simple', coalesce(display_name, '')), 'A') ||
               setweight(to_tsvector('simple', values), 'B')) STORED
```

- `values` maps field key to value, validated against `fields` on every write by one function (`records.validate`), so the API, imports, forms and workflows cannot disagree.
- Value encoding: money is `{"amount": <integer minor units>, "currency": "USD"}`; dates are ISO strings; `select` stores the choice id (so renaming a choice is free); `user` and `record` store ids.
- `display_name` is derived from the object's primary field on write, which keeps lists and search fast without reading `values`.
- `email_norm` (lower-cased) and `phone_e164` are typed columns because inbound email, SMS and calls must find the contact in one indexed lookup. They are indexed but **not** unique; duplicates go to the dedupe queue (module 09) instead of failing a form submit.
- Soft delete via `deleted_at`. Trash restores for 30 days, then a purge job deletes.
- Indexes: `(workspace_id, object_id, updated_at desc)`, GIN on `search`, `jsonb_path_ops` GIN on `values`, btree on `(workspace_id, email_norm)` and `(workspace_id, phone_e164)`. Hot filters get expression indexes when measured, not up front.
- RLS on `workspace_id`, like every workspace table (ADR 0001, module 02).

Tags get their own tables (`tags` with group, color and description, plus `record_tags`) because they need usage counts, rename and merge across thousands of records, which a jsonb array makes slow and racy.

### Associations

```
association_types  id, workspace_id, from_object_id, to_object_id, label, inverse_label,
                   cardinality (one_to_one, one_to_many, many_to_many)
associations       id, workspace_id, type_id, from_record_id, to_record_id, created_at
                   unique (type_id, from_record_id, to_record_id)
```

There is one row per link, with indexes on both ends; the inverse label reads it from the other side. Examples include contact to company ("works at" / "employs"), deal to contact with a role ("decision maker"), and property to contact.

### Timeline

The timeline is a query over the event log (ADR 0003), filtered to events whose subject is the record or one of its associated records. Notes, calls, emails and messages are their own tables. Their events carry the record ids, so the timeline is one indexed query: `events (workspace_id, subject_id, occurred_at desc)` plus an `event_records` link table for events that touch several records.

### Filter language

There is one JSON filter AST for lists, saved views, dynamic segments, workflow conditions, field rules, permissions (module 03) and the API:

```json
{"and": [
  {"field": "lifecycle", "op": "is", "value": "lead"},
  {"field": "created_at", "op": "within_last", "value": {"days": 30}},
  {"or": [{"tag": "vip"}, {"field": "deal.amount", "op": "gt", "value": {"amount": 500000, "currency": "USD"}}]}
]}
```

- `records.filters.compile(ast, object)` turns the AST into a SQLAlchemy expression and checks every field and operator against the field type, so an unknown field is a 400 error, never SQL.
- Association paths (`deal.amount`) compile to `EXISTS` subqueries.
- The AI natural-language filter (module 08) outputs this AST and the UI shows it as editable rules, so AI never writes SQL.

### Lists and views

- **Saved view**: object, filter AST, columns, sort, owner, shared with (team or workspace).
- **Dynamic list**: a saved filter whose membership is evaluated at query time. A nightly job snapshots membership counts for history.
- **Static list**: `list_members (list_id, record_id, added_at, added_by)`.

### Pipelines

`pipelines` and `stages` (position, probability, rotting days, exit rules as filter AST) are tables. A deal stores its stage in a `stage` field. Stage history is the event log, which forecasting and "time in stage" read.

## Consequences

- New objects, fields and views need no migrations, which is the point.
- jsonb filters on unindexed keys scan the workspace's rows for that object. That is fine into the low millions of records per workspace. The upgrade path is expression indexes per hot field, then partitioning `records` by workspace hash.
- Strong typing lives in one validator instead of the database. Tests must cover it per field type.
- Formula and rollup fields are computed on read in this first version. Materialize them on write when list performance needs it.

## As built in the first slice (2026-10-17)

Where the code differs from the sketch above:

- `objects.primary_fields` is a list, so a contact is named by `first_name` and `last_name`; when they are empty the name falls back to the first email, then the first phone. A record with no name at all is refused.
- Every reference between these tables carries `workspace_id` (foreign keys such as `(object_id, workspace_id)`), so a row cannot point into another workspace even if application code is wrong, and a request cannot move a row to another workspace (the policies check the new row too).
- `fields.type` is checked against the list of types; `file` is not built yet. `formula` and `rollup` fields are stored and refuse writes and filters until they can be computed, and a `stage` field was a `select` until pipelines existed (see the addendum below). Conditional required and visibility rules are not enforced yet; `rules` hold `required`, lengths, `min` and `max`.
- Tags keep their group in `group_name`. A tag filter takes the tag's id or its name (case insensitive); a saved view should use the id, because a rename changes the name.
- `saved_views.shared` is a boolean: shared with the workspace, or private to the owner, which a row level security policy enforces. Sharing with a team waits for teams (module 03).
- A record's timeline reads events by subject, plus `event_records (event_id, record_id)` for events that touch several records. It has no foreign key to `events`, which will be partitioned.
- The filter language also has `{"not": ...}`, and `between` takes two values. An association path is one hop (`company.name`) and looks at links in both directions; a `record` field such as a contact's `company` is a plain value, which the next section ties to the association.
- Lists sort by up to three keys with empty values last, and page with a signed cursor that holds the sort values and the id.
- A phone number without a country code is read with the field's `options.region`, then `DEFAULT_PHONE_REGION` (`US`), until workspaces have settings.

## As built for pipelines (2026-10-18)

- `pipelines` (workspace, `object_key` default `deal`, name, position, `archived_at`) and `stages` (pipeline, name, position, kind `open`/`won`/`lost`, probability, `rotting_days`, `exit_rules` jsonb, color) carry the workspace in every reference like the rest, and `board_layouts` (one row per pipeline and user, jsonb) is visible to its user only. Only deals use them: exit rules, lost reasons, events and the board are tied to the `deal` object, and a stage field on another object is checked for existence in a pipeline of that object and nothing more.
- A `stage` value is a stage id; whether the stage exists in a live pipeline of the object is checked by the write path, like `user` and `record` values. The value is mirrored in `records.stage_id`, a typed column with a composite foreign key to `stages` (so a stage that holds a deal, trashed ones too, cannot be deleted even by mistake), derived on every write like `email_norm`. The reason is row level security: Postgres refuses to use an index on a non-leakproof expression such as `values ->> 'stage'` for a table that has policies. Measured as the application role, the first page of a stage with 36 000 deals took 40 ms by scan and 0.1 ms through the typed column.
- Exit rules guard leaving a stage. They are a filter AST judged on the deal as it will be after the change, as a one-row subquery through the ordinary compiler (so association paths work), and each condition of a top level `and` is reported on its own. A won deal needing `close_date` and `amount` is therefore a rule on the stage before Won, which also applies to moving that deal to Lost. The `lost_reason` select and `lost_note` are system fields of `deal`; a lost stage requires the reason and leaving a lost stage clears both.
- Stage history is the event log: `deal.stage_changed` has the stages and `seconds_in_stage` (from the previous stage change, else from creation, so a deal's creation has no stage event). The board reads the last change for `days_in_stage` and the newest timeline entry for `last_activity_at`.
- `records.board_position` is numeric. A drop between two cards stores the midpoint, exact up to 1000 digits (about one digit per drop between the same two cards); a new or arriving deal takes the lowest position of the stage minus one. Positions travel as text, because JSON numbers are doubles. A reorder writes only the dropped record and emits no event.
- The forecast groups deals by the month or quarter of `close_date` and adds integer minor units per currency, never across currencies. `weighted` is the sum of amount times probability, divided by 100 and rounded half up once per sum.

## Wiring the screens (2026-10-18)

What the web app needed from the engine once it left its in-memory stand-in, and how the two were reconciled:

- **A contact's company is a field and a link.** A `record` field named like the object it links to, with an association type from this object to that one, keeps the association in step in the same transaction as the write (`associations.sync_field_links`, called by `store.create` and `store.update`, so the API, imports and the seed all get it). Setting `contact.company` adds the "works at" link if it is missing; changing the company removes the link to the old one and adds the new; clearing it removes the link. Links made with `POST /associations` stay while the field does not change. The step goes one way: a link made by hand leaves the field empty, so a company's page lists contacts linked either way, with one query that ORs `company is <id>` with `company.id is <id>` and so counts each contact once. A type whose cardinality forbids the link is skipped, not an error. A migration that links the contacts of workspaces that already hold companies is not written: nothing in production holds them yet.
- **Bulk changes** are `POST /objects/{key}/records/delete` and `/restore` with up to 1000 ids, all or none, one event per record (`events.emit_many`). Not found, trashed when it should be live, or outside the caller's scope: 404 for the whole call.
- **`id` is a filter column** of type record (`is`, `in`, `is_not`, `not_in`), so the names behind a page of links are one `in` query of at most 100 ids, and `company.id` reaches through an association.
- **People** come from `GET /api/v1/members` of the permissions module (`members.read`: `user_id`, name, email, role, teams), which the owner and user pickers read; the screen maps `user_id` to the id its pickers use. A workspace's members can read each other's `users` rows through that module's own policy, so this work adds no policy or migration.
- **Stages**: a stage field's options are empty on the API, because a stage is a row of a pipeline. The screens build the choices from `GET /api/v1/pipelines` (live pipelines first, archived ones last and labelled, the pipeline's name only where there is a choice of pipelines), take the color from the stage, start a new deal in the first open stage (the form fills it in, and the field is required so a picker cannot clear it), and do not offer to sort by stage (the engine does not). A move that an exit rule refuses is a 422 whose `fields` name what the deal lacks; the detail view shows all of those messages under the stage being changed.
- **Views and writes**: a saved view's `owner_id` is returned (it already was), and `tags` is a valid column since a list shows tags through `include=tags`; create and patch accept `include` like a read, so the screen gets the tags back with the saved row.
- **Shapes the screen changed to match the API**: an object has `primary_fields` (a list), and the name column of a list is the derived `display_name`, which sorts and filters; a field is archived when `archived_at` is set; the system columns `owner_id`, `created_at` and `updated_at` are field definitions the web client adds (read only except the owner) because the API lists only the object's own fields; `user` fields and `owner_id` do not sort (a sort would join users); a timeline event is the engine's event, which the client turns into created, changed, tagged, untagged, linked and unlinked lines.
- **Dates**: a `datetime` filter that names a day ("created on or after Oct 1") means that day in the browser's time zone, and the client sends the instants (`>= local midnight`); a `date` field is a calendar day with no zone. `within_last` is a rolling span from now on the server and needs no zone. The filter summary says "your time zone" next to such conditions.
