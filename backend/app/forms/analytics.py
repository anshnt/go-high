"""How a form performs (`/api/v1/forms/{id}/analytics`): views, starts, completions and the rate between them, the
average time to complete, and where visitors leave, per step and per question. Everything is read from counters and
a few grouped queries, so it stays fast for a form with many responses."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from ..security import Ctx, in_workspace
from .admin import form_or_404
from .models import FormVersion
from .responses import bounds

router = APIRouter(prefix="/api/v1/forms/{form_id}/analytics")
# Time to complete ignores the days a visitor may leave a saved response before coming back.
TOTALS = """
    SELECT count(*), count(*) FILTER (WHERE status = 'complete'),
           avg(extract(epoch FROM completed_at - started_at))
               FILTER (WHERE status = 'complete' AND completed_at - started_at < interval '1 day')
    FROM form_submissions WHERE form_id = :form {when}"""
REACHED = "SELECT k, count(*) FROM form_submissions, unnest(steps_seen) AS k WHERE form_id = :form {when} GROUP BY k"
LEFT_AT = ("SELECT steps_seen[cardinality(steps_seen)], count(*) FROM form_submissions WHERE form_id = :form "
           "AND status = 'partial' AND cardinality(steps_seen) > 0 {when} GROUP BY 1")
ANSWERED = ("SELECT k, count(*) FROM form_submissions, jsonb_object_keys(answers) AS k WHERE form_id = :form {when} "
            "GROUP BY k")
LAST_FIELD = ("SELECT last_field, count(*) FROM form_submissions WHERE form_id = :form AND status = 'partial' "
              "AND last_field IS NOT NULL {when} GROUP BY 1")
VIEWS = "SELECT coalesce(sum(count), 0) FROM form_views WHERE form_id = :form {days}"


@router.get("")
def analytics(form_id: uuid.UUID, created: date | None = Query(None, alias="from"),
              until: date | None = Query(None, alias="to"), c: Ctx = Depends(in_workspace)):
    """`from` and `to` (UTC dates, inclusive) bound when responses were started and views counted. A step's `reached`
    counts the responses that visited it, `dropped` those that left the form there; a question's `answered` counts
    responses with an answer, `dropped_after` those whose last answer it was."""
    form = form_or_404(c, form_id)
    start, end = bounds(created, until)
    when = ("AND created_at >= :start " if start else "") + ("AND created_at < :end" if end else "")
    params = {"form": form.id, **({"start": start} if start else {}), **({"end": end} if end else {})}

    def run(sql: str) -> list:
        return c.db.execute(text(sql.format(when=when)), params).all()

    starts, completions, average = run(TOTALS)[0]
    views = c.db.scalar(text(VIEWS.format(days=("AND day >= :first " if created else "") + (
        "AND day <= :last" if until else ""))), {"form": form.id, "first": created, "last": until})
    reached, left, answered, last = (dict(run(sql)) for sql in (REACHED, LEFT_AT, ANSWERED, LAST_FIELD))
    steps: dict[str, dict] = {}
    fields: dict[str, dict] = {}
    for v in c.db.scalars(select(FormVersion).where(FormVersion.form_id == form.id)
                          .order_by(FormVersion.number.desc())):  # the newest version names and orders first
        for s in v.definition["steps"]:
            steps.setdefault(s["key"], {"key": s["key"], "title": s["title"], "reached": reached.get(s["key"], 0),
                                        "dropped": left.get(s["key"], 0)})
            for f in s["fields"]:
                if f["type"] not in ("heading", "paragraph", "hidden"):
                    fields.setdefault(f["key"], {"key": f["key"], "label": f["label"], "step": s["key"],
                                                 "type": f["type"], "answered": answered.get(f["key"], 0),
                                                 "dropped_after": last.get(f["key"], 0)})
    return {"from": created, "to": until, "views": int(views), "starts": starts, "completions": completions,
            "completion_rate": round(completions / starts, 4) if starts else None,
            "conversion_rate": round(completions / views, 4) if views else None,
            "avg_seconds": round(float(average), 1) if average is not None else None,
            "steps": list(steps.values()), "fields": list(fields.values())}
