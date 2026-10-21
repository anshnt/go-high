# ADR 0006: Workflow engine

Status: accepted (2026-10-17). Module: 18 workflow automation; used by 16 (reminders), 17 (form follow-ups), 20 (email sequences), 31 (AI agents as steps). Builds on ADR 0002 (filter language), ADR 0003 (events, consumers), ADR 0004 (actors and roles) and ADR 0005 (sending).

## Context

The incumbent's workflows are its stickiest feature and its biggest source of pain. It keeps 10 versions or 30 days of history and has no staging or test run. Live edits can strand enrolled contacts. "Why didn't this contact enter?" has no answer, and double sends after retries are a known failure. Its API cannot write workflows.

## Decision

### Definitions are versioned graphs

```
workflows          id, workspace_id, name, folder, status (draft, published, paused, archived),
                   published_version_id, settings jsonb (re-entry, quiet hours, time zone source), owner_id
workflow_versions  id, workflow_id, number, graph jsonb, created_by, created_at, published_at, note
```

- `graph` is `{trigger, nodes: {id: {type, config, next | branches}}}`. Versions are immutable. Editing writes a new draft version, and publishing points `published_version_id` at it. History is every version, forever, with a diff view between any two.
- Node types:
  - **trigger**: an event type (ADR 0003) plus a filter AST.
  - **action**: send SMS or email, update a field, add or remove a tag, create a task, assign the owner, move the stage, create a record, webhook, notify a user, AI step.
  - **wait**: a duration, until a date field, or until an event with a timeout.
  - **condition**: if/else over the filter AST.
  - **split**: percentages for A/B.
  - **goal**: jump here when the condition becomes true.
  - **subflow**: run another workflow with inputs.
  - **end**.
- Every action type is a registered handler with a JSON schema for its config. The builder, the API, the validator and the AI generator use the same schemas, so a workflow saved through the API is valid in the UI.

### Runs and steps

```
workflow_runs   id, workspace_id, workflow_id, version_id, record_id, status (running, waiting,
                completed, failed, exited), node_id, context jsonb, test bool, started_at, ended_at
workflow_steps  id, run_id, node_id, status, input jsonb, output jsonb, error, started_at, finished_at
```

- **Enrollment** is an events consumer. For each event it finds published workflows whose trigger type and filter match, then creates runs. When re-entry is off, a partial unique index `(workflow_id, record_id) WHERE status IN ('running', 'waiting')` makes double enrollment impossible. **Trigger evaluation is logged**, including the misses, as `workflow_trigger_checks` rows kept for 7 days. That table is what answers "why didn't this contact enter": it shows the filter clause that failed.
- **Execution**: a run advances through `workflow.step` jobs on the queue. A step runs in its own transaction and writes its `workflow_steps` row with input and output, which is the per-contact trace in the UI.
- **Waits** park the run as `waiting` and enqueue the next step with `run_at` set to the wake time, so the queue is the scheduler. An event wait registers a waiter row that the consumer resolves.
- **Exactly-once side effects**: actions that leave the system (send, webhook) do not perform the side effect in the step. They create the outbound row (message, delivery) with the idempotency key `run_id:node_id:attempt_group`, and the existing send machinery (ADR 0005, ADR 0003) delivers it. A retried step finds the row and moves on, so it never sends twice.
- **Guards**: at most 500 steps per run (loop guard), per-workspace concurrency limits, and quiet hours that defer sends to the next allowed window in the contact's time zone.
- **Actor**: runs act as the workflow's actor with the Automation role (ADR 0004). Field changes they make show "by workflow X" in timelines and the audit log.

### Testing and safe edits

- **Test run**: pick a record (or a sample) and run the draft version with `test = true` on a virtual clock. Waits resolve immediately, with the skipped time shown, and outbound actions are recorded but not sent. The trace looks exactly like a live run.
- **Publishing over in-flight runs**: by default a run finishes on the version it started on. The publisher can migrate runs instead. Runs at nodes that exist in both versions (same id) move over, and the dialog shows each removed node with its run count and lets you pick a target node or exit them.
- **Dependency index**: tags, fields, calendars, templates and other workflows used by each version are extracted on save into `workflow_refs`, so "what uses this tag" and safe-delete checks are one query.

### API and AI

- `/api/v1/workflows` exposes CRUD for workflows and versions, plus publish, pause, test runs, runs and steps. It is the same API the builder uses.
- The AI builder produces a graph validated against the same schemas, generates test cases (records and expected paths) and runs them before offering to publish.

### Code steps

There is no arbitrary code execution in v1. Webhook actions and inbound-webhook triggers cover integrations. A sandboxed code step (an isolated runtime with CPU, memory and network limits) gets its own ADR when there is demand.

## Consequences

- The jobs table carries all scheduling, so its `run_at` index is the hot path and must stay lean (finished jobs are pruned).
- Immutable versions grow storage linearly with edits. Graphs are small JSON, so that is acceptable.
- Exactly-once depends on every outbound action going through an idempotent outbox row. Action handlers that call third parties directly are rejected in review.

## As built in the backend slice (2026-10-19)

Where the code differs from the sketch above, or decides what it left open:

- **Tables** are those of the sketch plus `workflow_deliveries`, the outbox of the webhook action, and the message
  gained `idempotency_key` (unique per workspace where set). `workflow_versions.published_at` is the one column a request
  may set on a version; the rest is immutable by grant. Steps are append only: a wait writes a `waiting` row when it
  parks and a `completed` row (`resumed_by` `timer`, `event` or `timeout`) when it ends, a failure a `failed` row, a
  publish that moves a run a `migrated` row, a cancel a `cancelled` row. `workflow_waiters` and `workflow_refs` are as
  sketched; refs are by id or by key (a field is `contact.email`, a tag may be named by id or by name).
- **The graph** is `{trigger, start, nodes}`. The trigger is `{event, object (default contact; deal for a stage change), filter, data}`: the event
  types that name a record (as subject, or in `contact_id` or `record_id`; 25 today; workflow events and `record.deleted` are excluded), the
  object whose records enter, a filter AST over the record and a containment test on the event's data. Nodes carry
  `next` or `branches` (`yes` and `no`; a split's path names; `event` and `timeout` for an event wait); `null` ends the
  run. Validation is `schema.py` (pure) plus `check.py` (against the workspace); both produce field pointers.
  Condition and goal configs are `{"filter": AST}`. Subflow nodes can be saved and not published.
- **Actions** are `record.update`, `tag.add`, `tag.remove`, `owner.assign` (one user or round robin), `deal.move_stage`,
  `task.create`, `message.send` (SMS, email, WhatsApp, with `if_refused` `fail` or `skip`), `notify.user` and
  `webhook.send`, in one registry (`registry.py`) of a pydantic config (the JSON schema), a handler and the references it
  uses. AI steps, record creation, calendars and email marketing are later. A note on the actor: the Automation role
  acts through `Ctx.actor = ("workflow", id)`, which `Ctx.author()` turns into the actor of every event of the record
  engine, tags and tasks.
- **Exactly once** is two things together. A job carries `n`, the run's step count when it was scheduled, and a step
  whose run has another `n` (or is no longer at that node) does nothing: that is what makes a job that runs twice
  harmless, and it also lets an event wait, a goal, a publish or a cancel move a run without chasing its pending jobs.
  And what leaves the system is an outbox row with the key `run:node` (`run:node:2` on the second loop round; a retry
  of a failed step is the same attempt, since its row rolled back with it). A step is one transaction, so the row and
  the trace commit together; the key is what protects a step that is run again over a row that did commit.
- **Enrollment** judges a record by its state when the event is read, not when it happened (a record changed in between
  is judged as it is now), and only for events after the workflow first went live. It logs every check with the failing
  clause. The unique index of the sketch covers live runs; the re-entry setting (off by default) is the check above it,
  taken under an advisory lock per workflow and record so the check and the insert are one step.
- **Waits**: duration, a date or datetime field with an offset (a date at `at`, 09:00, in the contact's `timezone`
  field, else UTC), and an event with a timeout. Event waits only see events after the wait began. A send put off by quiet
  hours is a `waiting` step and the same node runs again at the end of the window.
- **Goals** are checked on every event of the record against its runs, once per goal and run; a goal reached by walking
  goes on or ends as its `otherwise` says. "Wait until met" is not built.
- **Execution** runs in the worker's owner session inside `db.acting`, which sets `gohigh_app` and the workspace for the
  steps' own queries (the record engine looks objects up by key and relies on row level security), and `db.elevated` for
  the one write the app role cannot make (a notification, through the notifications consumer's own `deliver`, whose
  `dedupe_key` is the step's key). A failed node is rolled back to a savepoint. Per-workspace concurrency is
  `WORKFLOW_CONCURRENCY` advisory-lock slots (no table); a step with no free slot puts its job back five seconds on.
- **Pause** freezes: the jobs of a paused workflow end, and resume queues every live run again (a waiting one at its
  wake time). Archive cancels the runs. Events during a pause are not seen by that workflow's waiters and goals.
- **Test runs** do not simulate on a copy of the values: they run the real actions against the real record inside a
  savepoint that is always rolled back, with the outbound actions only describing what they would send. Everything a
  condition, an exit rule or a permission check needs is therefore real, and nothing is left behind (a test compares the
  whole of the tables a run could touch before and after). The virtual clock starts at `consent.clock()`. The trace is
  saved as a run with `test = true`.
- **Publishing**: `migrate` maps removed nodes to a node of the new version or `exit`; runs at a node both versions
  have stay there on the new version, keeping the wake-up they were scheduled with; a removed node with no answer is a
  422 that counts its runs; `dry_run` reports the counts. Migrating happens in the publish request.
- **Dependency index** kinds: `tag`, `field`, `stage`, `user`, `channel`, `form`, `calendar` (the last two from the
  trigger's data and an event wait's match). Templates and other workflows join it when they exist.
- **Permissions** are `workflows.read`, `workflows.write` and `workflows.publish`; a run is visible with its record's
  scope and its steps' input and output are withheld from a role that hides fields.
- **Not built**: subflows, AI steps, code steps, the inbound webhook trigger, loops over records,
  cost preview, bulk retry and enrollment, a time window per workflow, stop on response, "wait until met" goals, and
  migrating runs in a job (it is done in the request).

