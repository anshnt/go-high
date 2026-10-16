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
- `fields.type` is checked against the list of types; `file` is not built yet. `formula` and `rollup` fields are stored and refuse writes and filters until they can be computed, and a `stage` field is a `select` until pipelines exist. Conditional required and visibility rules are not enforced yet; `rules` hold `required`, lengths, `min` and `max`.
- Tags keep their group in `group_name`. A tag filter takes the tag's id or its name (case insensitive); a saved view should use the id, because a rename changes the name.
- `saved_views.shared` is a boolean: shared with the workspace, or private to the owner, which a row level security policy enforces. Sharing with a team waits for teams (module 03).
- A record's timeline reads events by subject, plus `event_records (event_id, record_id)` for events that touch several records. It has no foreign key to `events`, which will be partitioned.
- The filter language also has `{"not": ...}`, and `between` takes two values. An association path is one hop (`company.name`) and looks at links in both directions; a `record` field such as a contact's `company` is a plain value and not an association, and nothing keeps the two in step.
- Lists sort by up to three keys with empty values last, and page with a signed cursor that holds the sort values and the id.
- A phone number without a country code is read with the field's `options.region`, then `DEFAULT_PHONE_REGION` (`US`), until workspaces have settings.
