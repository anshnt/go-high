"""Booking reminders (module 16). Making or moving a booking schedules one job per reminder offset
(booking.plan_reminders); when it runs, the reminder row goes from pending to sent in one UPDATE, so a retried or
duplicate job finds nothing to do and a reminder is recorded exactly once. A job queued for a time the booking has
since left, or for a cancelled booking, finds the row changed and stops. ponytail: a reminder is recorded as a
`booking.reminder_due` event and goes no further. Sending it (email, SMS) is for the inbox and the workflow engine
(ADR 0006), which will consume that event; nothing here knows how to send."""
import uuid
from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from .. import events, jobs
from ..records.timeline import link
from . import booking
from .models import Booking, BookingReminder, Calendar


@jobs.handler("calendars.reminder")
def remind(db: Session, payload: dict) -> None:
    row = db.execute(
        update(BookingReminder)
        .where(BookingReminder.id == uuid.UUID(payload["id"]), BookingReminder.status == "pending",
               BookingReminder.due_at == datetime.fromisoformat(payload["due"]), BookingReminder.due_at <= func.now())
        .values(status="sent", sent_at=func.now())
        .returning(BookingReminder.workspace_id, BookingReminder.booking_id, BookingReminder.offset_minutes)).first()
    if row is None:
        return
    b = db.get(Booking, row.booking_id)
    cal = db.get(Calendar, b.calendar_id)
    event = events.emit(db, "booking.reminder_due", "booking", b.id,
                        {**booking.event_data(b, cal), "offset_minutes": row.offset_minutes},
                        workspace_id=row.workspace_id)
    if b.contact_id:
        link(db, event, [b.contact_id])
