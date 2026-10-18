"""Whether a form is taking responses: its status, then the close date and the response limit of its settings."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .definition import Settings
from .models import Form, Submission


def completed(db: Session, form_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(Submission.form_id == form_id, Submission.status == "complete")) or 0


def closed_reason(db: Session, form: Form, s: Settings, count: int | None = None) -> str | None:
    """Why a published form takes no more responses (`manual`, `date` or `limit`), or None when it does. `count` is
    the number of completed responses when the caller already has it."""
    if form.status == "closed":
        return "manual"
    if form.status != "published":
        return None
    if s.close_at is not None and datetime.now(UTC) >= s.close_at:
        return "date"
    if s.max_responses is not None and (completed(db, form.id) if count is None else count) >= s.max_responses:
        return "limit"
    return None
