"""The actions a workflow step can take (ADR 0006): each is a registered config model (its JSON schema) and a handler,
and each acts as the workspace's Automation role through the same write paths as the API, so its reach is what the
role allows and every change shows "by workflow X" through the actor. A handler writes inside the step's transaction.
Actions that leave the system (a message, a webhook) only write an outbox row whose idempotency key is
`run:node`, and a job delivers it: a step that runs twice still sends once. A handler raises `StepError` (or lets the
record engine's own `ApiError` through) to fail the step with a reason in words.

ponytail: values to merge into text are `{{field_key}}` (and `{{display_name}}`) only, no fallbacks or formatting.
ponytail: round robin counts the steps this node has completed (O(runs of the workflow)) and two steps at the same
moment can pick the same person; keep a counter row on the workflow if that matters."""
import json
import uuid
from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select

from .. import compliance, jobs, permissions, ssrf, webhooks
from ..db import elevated
from ..inbox import consent, outbound, threads
from ..inbox.models import Channel, Conversation, Message
from ..notifications.consumer import Draft, deliver, record_link
from ..records import stages, store, tags, types
from ..records.models import Stage, Tag
from ..records.schema import FieldKey
from ..tasks import store as tasks
from . import registry
from .models import Delivery, Run, Step
from .registry import Offset, Out, StepError, action, seconds

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Scalar = str | int | float | bool | None


def person(value: str) -> str:
    if value != "owner":
        try:
            uuid.UUID(value)
        except ValueError:
            raise ValueError('must be the id of a user, or "owner"') from None
    return value


Person = Annotated[str, AfterValidator(person)]  # a user id, or "owner": whoever owns the record
CHANNEL_KINDS = ("sms", "email", "whatsapp")
ADDRESS = {"sms": "phone_e164", "whatsapp": "phone_e164", "email": "email_norm"}  # where a contact is reached


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- helpers ----------------------------------------------------------------------------------------------------

def find_tag(db, key: str) -> Tag | None:
    """A tag by id or by name (case insensitive)."""
    try:
        return db.get(Tag, uuid.UUID(key))
    except ValueError:
        return db.scalar(select(Tag).where(func.lower(Tag.name) == key.strip().lower()))


def people_errors(cat, **named: uuid.UUID | str | None) -> dict[str, str]:
    """Errors for the people (user ids, by config key) that are not members of the workspace."""
    wanted = {k: str(v) for k, v in named.items() if v and v != "owner"}
    found = store.member_ids(cat.c, set(wanted.values())) if wanted else set()
    return {k: "is not a member of this workspace" for k, v in wanted.items() if v not in found}


def merge_errors(cat, obj, cfg: BaseModel) -> dict[str, str]:
    """Errors for `{{key}}` in any text of the config that is not a field of the object: it would send "Hi ,"."""
    known = {*cat.fields(obj), "display_name"}
    errors: dict[str, str] = {}

    def walk(value, path: str) -> None:
        if isinstance(value, str):
            if missing := [k for k in registry.merge_keys(value) if k not in known]:
                errors[path] = f"uses {{{{{missing[0]}}}}}, which is not a field of {obj.key}"
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}.{i}")

    walk(cfg.model_dump(mode="json"), "")
    return errors


# --- update record fields ---------------------------------------------------------------------------------------

class UpdateFields(Config):
    values: Annotated[dict[FieldKey, Scalar | list | dict], Field(min_length=1, max_length=50)]


def check_update_fields(cat, obj, cfg: UpdateFields) -> dict[str, str]:
    fields, errors = cat.fields(obj), {}
    for key, raw in cfg.values.items():
        field = fields.get(key)
        if field is None or key in permissions.hidden(cat.c, obj):
            errors[f"values.{key}"] = f"is not a field of {obj.key}"
        elif not (isinstance(raw, str) and registry.merge_keys(raw)):  # a text with merge fields is judged when it runs
            try:
                types.validate(field, raw)
            except ValueError as e:
                errors[f"values.{key}"] = f"{field.label} {e}"
    return errors | merge_errors(cat, obj, cfg)


@action("record.update", "Update fields", UpdateFields, check=check_update_fields,
        description="Sets fields of the record; a null value clears one. Text may hold {{field_key}}.",
        refs=lambda cfg: [("field", k) for k in cfg.values])
def update_fields(env, cfg: UpdateFields) -> Out:
    rec = env.record(lock=True)
    patch = {k: env.render_value(v) for k, v in cfg.values.items()}
    return Out({"values": patch}, {"changed": store.update(env.cat, env.obj, rec, patch)})


# --- tags -------------------------------------------------------------------------------------------------------

class TagChange(Config):
    tag: Short  # the tag's id or its name


def check_tag(cat, obj, cfg: TagChange) -> dict[str, str]:
    return {} if find_tag(cat.db, cfg.tag) else {"tag": f"there is no tag {cfg.tag!r}"}


def change_tag(env, cfg: TagChange, *, add: bool) -> Out:
    permissions.require(env.ctx, "tags.write")
    tag = find_tag(env.db, cfg.tag)
    if tag is None:
        raise StepError(f"There is no tag {cfg.tag!r}: it was deleted or renamed")
    env.record(lock=True)
    done = tags.apply(env.cat, [env.run.record_id], [tag.id] if add else [], [] if add else [tag.id])
    return Out({"tag": tag.name, "tag_id": tag.id}, {"changed": bool(done["added" if add else "removed"])})


@action("tag.add", "Add a tag", TagChange, check=check_tag, refs=lambda cfg: [("tag", cfg.tag)])
def add_tag(env, cfg: TagChange) -> Out:
    return change_tag(env, cfg, add=True)


@action("tag.remove", "Remove a tag", TagChange, check=check_tag, refs=lambda cfg: [("tag", cfg.tag)])
def remove_tag(env, cfg: TagChange) -> Out:
    return change_tag(env, cfg, add=False)


# --- owner ------------------------------------------------------------------------------------------------------

class AssignOwner(Config):
    user_id: uuid.UUID | None = None  # this person, or
    round_robin: Annotated[list[uuid.UUID], Field(min_length=1, max_length=50)] | None = None  # each in turn

    @model_validator(mode="after")
    def one_way(self):
        if (self.user_id is None) == (self.round_robin is None):
            raise ValueError("give a user_id or a round_robin list, not both and not neither")
        return self


def check_owner(cat, obj, cfg: AssignOwner) -> dict[str, str]:
    errors = people_errors(cat, user_id=cfg.user_id)
    if cfg.round_robin:
        found = store.member_ids(cat.c, {str(u) for u in cfg.round_robin})
        errors |= {f"round_robin.{i}": "is not a member of this workspace" for i, u in enumerate(cfg.round_robin)
                   if str(u) not in found}
    return errors


@action("owner.assign", "Assign the owner", AssignOwner, check=check_owner,
        description="Makes one person the owner, or hands the owner role round a list of people in turn.",
        refs=lambda cfg: [("user", str(u)) for u in [cfg.user_id, *(cfg.round_robin or [])] if u])
def assign_owner(env, cfg: AssignOwner) -> Out:
    rec = env.record(lock=True)
    if cfg.round_robin:
        taken = env.db.scalar(select(func.count()).select_from(Step).join(Run, Run.id == Step.run_id).where(
            Run.workflow_id == env.wf.id, Step.node_id == env.node_id, Step.status == "completed",
            Run.test.is_(False)))
        who = cfg.round_robin[taken % len(cfg.round_robin)]
    else:
        who = cfg.user_id
    before = rec.owner_id
    changed = store.update(env.cat, env.obj, rec, {}, owner_id=who)
    return Out({"owner_id": who, "round_robin": bool(cfg.round_robin)}, {"changed": changed, "previous": before})


# --- deal stage -------------------------------------------------------------------------------------------------

class MoveStage(Config):
    stage_id: uuid.UUID
    lost_reason: Short | None = None  # a lost stage needs one
    lost_note: Annotated[str, StringConstraints(max_length=2000)] | None = None


def check_stage(cat, obj, cfg: MoveStage) -> dict[str, str]:
    stage = cat.db.get(Stage, cfg.stage_id)
    if obj.key != stages.DEAL:
        return {"stage_id": f"moving a stage works on deals; this workflow's records are {obj.plural.lower()}"}
    return {} if stage else {"stage_id": "is not a stage of this workspace"}


@action("deal.move_stage", "Move the deal to a stage", MoveStage, check=check_stage,
        description="Moves a deal. The stage it leaves may refuse (its exit rules), which fails the step with the "
                    "reason.", refs=lambda cfg: [("stage", str(cfg.stage_id))])
def move_stage(env, cfg: MoveStage) -> Out:
    if env.obj.key != stages.DEAL:
        raise StepError(f"Moving a stage works on deals, and this record is a {env.obj.key}")
    stage = env.db.get(Stage, cfg.stage_id)
    if stage is None:
        raise StepError("The stage no longer exists")
    rec = env.record(lock=True)
    before = stages.stage_of(env.cat, rec.values.get(stages.STAGE))
    stages.lock(env.cat, stage.id)
    patch = {stages.STAGE: str(stage.id), **{k: v for k, v in (("lost_reason", cfg.lost_reason),
                                                                  ("lost_note", cfg.lost_note)) if v is not None}}
    changed = store.update(env.cat, env.obj, rec, patch)
    return Out({"stage": stage.name, "stage_id": stage.id}, {"changed": changed, "from": before and before.name})


# --- task -------------------------------------------------------------------------------------------------------

class CreateTask(Config):
    title: Text
    notes: Annotated[str, StringConstraints(max_length=5000)] = ""
    due: Offset | None = None  # from the moment the step runs
    assignee: Person | None = "owner"
    priority: Literal["none", "low", "medium", "high"] = "none"


@action("task.create", "Create a task", CreateTask, refs=lambda cfg: [("user", cfg.assignee)]
        if cfg.assignee not in (None, "owner") else [],
        check=lambda cat, obj, cfg: people_errors(cat, assignee=cfg.assignee) | merge_errors(cat, obj, cfg))
def create_task(env, cfg: CreateTask) -> Out:
    permissions.require(env.ctx, "tasks.write")
    rec = env.record()
    assignee = rec.owner_id if cfg.assignee == "owner" else cfg.assignee and uuid.UUID(cfg.assignee)
    due = env.now + timedelta(seconds=seconds(cfg.due)) if cfg.due else None
    values = {"title": env.render(cfg.title), "notes": env.render(cfg.notes), "assignee_id": assignee,
              "priority": cfg.priority, "record_id": rec.id, "due_at": due, "all_day": False}
    task = tasks.create(env.ctx, values)
    return Out({k: v for k, v in values.items() if k != "record_id"}, {"task_id": task.id})


# --- message ----------------------------------------------------------------------------------------------------

class SendMessage(Config):
    channel_id: uuid.UUID  # an SMS, email or WhatsApp channel
    body: Annotated[str, StringConstraints(min_length=1, max_length=5000)]
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None  # email
    if_refused: Literal["fail", "skip"] = "fail"  # when consent says no (not for quiet hours, which wait)


def check_message(cat, obj, cfg: SendMessage) -> dict[str, str]:
    channel, errors = cat.db.get(Channel, cfg.channel_id), merge_errors(cat, obj, cfg)
    if obj.key != "contact":
        errors["channel_id"] = f"messages go to contacts; this workflow's records are {obj.plural.lower()}"
    elif channel is None:
        errors["channel_id"] = "is not a channel of this workspace"
    elif channel.kind not in CHANNEL_KINDS:
        errors["channel_id"] = f"workflows send on sms, email and whatsapp channels, not {channel.kind}"
    elif channel.kind == "email" and not cfg.subject:
        errors["subject"] = "is required to send an email"
    return errors


def conversation_of(env, contact) -> Conversation | None:
    """The contact's conversation: made (and locked) when a message is going out, only looked up when it is not."""
    if not env.test:
        return threads.conversation_for(env.db, env.run.workspace_id, contact.id)[0]
    return env.db.scalar(select(Conversation).where(Conversation.contact_id == contact.id)
                         .order_by(Conversation.last_message_at.desc()).limit(1))


@action("message.send", "Send a message", SendMessage, check=check_message, outbound=True,
        description="Sends an SMS, email or WhatsApp message through the inbox, with the consent checks of any "
                    "reply. In quiet hours the step waits for the next allowed time. Text may hold {{field_key}}.",
        refs=lambda cfg: [("channel", str(cfg.channel_id))])
def send_message(env, cfg: SendMessage) -> Out:
    permissions.require(env.ctx, "messages.send")
    contact, channel = env.record(), env.db.get(Channel, cfg.channel_id)
    if env.obj.key != "contact":
        raise StepError(f"Messages go to contacts, and this record is a {env.obj.key}")
    if channel is None or channel.kind not in CHANNEL_KINDS:
        raise StepError("The channel no longer exists, or is not an SMS, email or WhatsApp channel")
    body, subject = env.render(cfg.body), env.render(cfg.subject) if cfg.subject else None
    if channel.kind == "email" and not subject:
        raise StepError("An email needs a subject")
    conv, where = conversation_of(env, contact), getattr(contact, ADDRESS[channel.kind])
    shown = {"channel": channel.name, "to": where, "subject": subject, "body": body}
    if channel.status == "disabled":
        raise StepError(f"The channel {channel.name} is disabled")
    verdict = (compliance.Refusal("no_address", f"The contact has no way to be reached on {channel.name}")
               if where is None else consent.verdict(env.db, channel, contact, conv, env.now if env.test else None))
    if verdict and verdict.retry_at:
        return Out(shown, {"deferred_until": verdict.retry_at.isoformat(), "reason": verdict.reason},
                   until=verdict.retry_at)
    if verdict:
        if cfg.if_refused == "skip":
            return Out(shown, {"skipped": verdict.reason, "code": verdict.code})
        raise StepError(verdict.reason)
    if env.test:
        return Out(shown, {"would_send": True, "sent": False})
    key = env.key()
    msg = env.db.scalar(select(Message).where(Message.workspace_id == env.run.workspace_id,
                                              Message.idempotency_key == key))
    if msg is not None:  # a step that runs again finds the message it queued before, and moves on
        return Out(shown, {"message_id": msg.id, "already_queued": True})
    msg, _ = outbound.queue_reply(env.db, conv, contact, channel, body=body, subject=subject,
                                  actor=env.ctx.author(), idempotency_key=key)
    return Out(shown, {"message_id": msg.id})


# --- notify -----------------------------------------------------------------------------------------------------

class NotifyUser(Config):
    user_id: Person
    title: Text
    body: Annotated[str, StringConstraints(max_length=2000)] = ""


@action("notify.user", "Notify a user", NotifyUser, refs=lambda cfg: [("user", cfg.user_id)]
        if cfg.user_id != "owner" else [],
        check=lambda cat, obj, cfg: people_errors(cat, user_id=cfg.user_id) | merge_errors(cat, obj, cfg),
        description="An in-app notification that links to the record. Text may hold {{field_key}}.")
def notify_user(env, cfg: NotifyUser) -> Out:
    rec = env.record()
    who = rec.owner_id if cfg.user_id == "owner" else uuid.UUID(cfg.user_id)
    if who is None:
        raise StepError("The record has no owner to notify")
    if not store.member_ids(env.ctx, {str(who)}):
        raise StepError("The person to notify is not a member of this workspace")
    title, body, link = env.render(cfg.title), env.render(cfg.body), record_link(env.obj.key, str(rec.id))
    shown = {"user_id": who, "title": title, "body": body, "link": link}
    if not env.test:
        draft = Draft("workflow", env.run.workspace_id, who, None, title, title, body, link, ("record", rec.id),
                      f"workflow:{env.key()}")
        with elevated(env.db):  # the app role cannot write a notification; the key makes it one per step
            deliver(env.db, {}, draft)
    return Out(shown, {"notified": not env.test})


# --- webhook ----------------------------------------------------------------------------------------------------

class SendWebhook(Config):
    url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    payload: Annotated[dict[Short, Scalar], Field(max_length=30)] = {}  # sent as `data`; text may hold {{field_key}}


def check_webhook(cat, obj, cfg: SendWebhook) -> dict[str, str]:
    try:
        ssrf.target(cfg.url)
    except ssrf.Blocked as e:
        return {"url": str(e)} | merge_errors(cat, obj, cfg)
    return merge_errors(cat, obj, cfg)


@action("webhook.send", "Send a webhook", SendWebhook, check=check_webhook, outbound=True,
        description="POSTs JSON to a public https URL, signed with the workflow's secret like a webhook delivery "
                    "(GoHigh-Signature), and retried. The receiver can dedupe on GoHigh-Idempotency-Key.")
def send_webhook(env, cfg: SendWebhook) -> Out:
    rec = env.record()
    try:
        ssrf.target(cfg.url)
    except ssrf.Blocked as e:
        raise StepError(f"The URL is not allowed: {e}") from None
    body = {"workflow": {"id": env.wf.id, "name": env.wf.name}, "run": {"id": env.run.id, "node_id": env.node_id},
            "record": {"id": rec.id, "object": env.obj.key, "display_name": rec.display_name},
            "data": {k: env.render_value(v) for k, v in cfg.payload.items()}}
    shown = {"url": cfg.url, "body": json.loads(json.dumps(body, default=str))}
    if env.test:
        return Out(shown, {"would_post": True, "sent": False})
    key = env.key()
    sent = env.db.scalar(select(Delivery).where(Delivery.workspace_id == env.run.workspace_id,
                                                Delivery.idempotency_key == key))
    if sent is None:
        sent = Delivery(workspace_id=env.run.workspace_id, workflow_id=env.wf.id, run_id=env.run.id,
                        node_id=env.node_id, idempotency_key=key, url=cfg.url,
                        body=json.dumps(body, default=str, separators=(",", ":")))
        env.db.add(sent)
        env.db.flush()
        jobs.enqueue(env.db, "workflow.deliver", {"delivery_id": str(sent.id)}, max_attempts=webhooks.MAX_ATTEMPTS)
        return Out(shown, {"delivery_id": sent.id})
    return Out(shown, {"delivery_id": sent.id, "already_queued": True})

