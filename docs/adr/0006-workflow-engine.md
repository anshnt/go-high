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
