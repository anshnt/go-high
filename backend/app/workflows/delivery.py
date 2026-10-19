"""Sends the rows of the webhook action's outbox (ADR 0006): one `workflow.deliver` job per row, retried on the webhook
backoff (12 attempts over about a day), signed like any webhook delivery with the workflow's secret and carrying the
row's idempotency key (`run:node`) as `GoHigh-Idempotency-Key`, so a receiver can drop a repeat. The SSRF guard checks
the address again here, after DNS, as the step did when it queued the row. Runs in the worker, as the owner role."""
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import jobs, ssrf, webhooks
from .models import Delivery, Workflow


@jobs.handler("workflow.deliver", backoff=webhooks.retry_delay)
def deliver(db: Session, payload: dict) -> None:
    d = db.get(Delivery, uuid.UUID(payload["delivery_id"]))
    if d is None or d.status in ("succeeded", "failed"):
        return
    wf = db.get(Workflow, d.workflow_id)
    d.attempts += 1
    d.next_attempt_at = d.response_status = d.response_body_excerpt = d.error = None
    headers = {"Content-Type": "application/json", "User-Agent": "go-high-workflows/1", "GoHigh-Delivery-Id": str(d.id),
               "GoHigh-Run-Id": str(d.run_id), "GoHigh-Idempotency-Key": d.idempotency_key,
               "GoHigh-Signature": webhooks.signature(wf.signing_secret, int(time.time()), d.body)}
    started = time.monotonic()
    try:
        d.response_status, excerpt = ssrf.post(d.url, d.body.encode(), headers, webhooks.TIMEOUT)
        d.response_body_excerpt = excerpt.decode(errors="replace").replace("\x00", "")
    except Exception as e:
        d.error = webhooks.describe(e)
    d.response_ms = round((time.monotonic() - started) * 1000)
    if d.error is None and 200 <= d.response_status < 300:
        d.status = "succeeded"
        db.commit()
        return
    if d.attempts >= webhooks.MAX_ATTEMPTS:
        d.status = "failed"
        db.commit()
        return
    d.status, d.next_attempt_at = "retrying", db.scalar(select(func.now())) + webhooks.retry_delay(d.attempts)
    db.commit()  # the queue rolls back what a failed job did, so the attempt is committed before raising
    raise webhooks.DeliveryFailed(d.error or f"HTTP {d.response_status}")
