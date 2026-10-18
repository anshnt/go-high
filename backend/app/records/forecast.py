"""The forecast of a pipeline (ADR 0002, module 10): what the deals expected to close in each month or quarter are
worth, by currency and by owner. Money is never added across currencies, and amounts are integer minor units."""
import uuid
from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import BigInteger, Date, DateTime, String, cast, func, select

from ..security import Ctx, in_workspace
from . import stages, store
from .models import Record, Stage
from .pipelines import pipeline_or_404
from .schema import Catalog

router = APIRouter(prefix="/api/v1")
BEST_CASE, COMMIT = 50, 80  # the lowest stage probability of an open deal that counts as best case, and as commit
METRICS = ("pipeline", "best_case", "commit", "weighted", "won")


def end_of(start: date, period: str) -> date:
    month = start.month - 1 + (1 if period == "month" else 3)
    return date(start.year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def label(start: date, period: str) -> str:
    return start.strftime("%Y-%m") if period == "month" else f"{start.year}-Q{(start.month - 1) // 3 + 1}"


def tally(buckets: list[dict], currency: str, kind: str, probability: int, total: int) -> None:
    """Adds one group of deals to each bucket: the won ones to `won`, the open ones to `pipeline` and, by the
    probability of their stage, to `best_case` and `commit`; `weighted` holds amount times probability until it is
    divided by 100 at the end, so rounding happens once per sum."""
    for bucket in buckets:
        if kind == "won":
            bucket["won"][currency] += total
            continue
        bucket["pipeline"][currency] += total
        bucket["weighted"][currency] += total * probability
        if probability >= BEST_CASE:
            bucket["best_case"][currency] += total
        if probability >= COMMIT:
            bucket["commit"][currency] += total


def blank() -> dict:
    return {m: defaultdict(int) for m in METRICS}


def done(bucket: dict) -> dict:
    out = {m: dict(sorted(bucket[m].items())) for m in METRICS}
    out["weighted"] = {cur: (n + 50) // 100 for cur, n in out["weighted"].items()}
    return out


@router.get("/pipelines/{pipeline_id}/forecast")
def forecast(pipeline_id: uuid.UUID, period: Literal["month", "quarter"] = "month",
             start: date | None = Query(None, alias="from"), end: date | None = Query(None, alias="to"),
             c: Ctx = Depends(in_workspace)):
    """Per month or quarter of the deals' `close_date` (`from` and `to` limit the dates), with `pipeline` (open deals),
    `best_case` (open deals in stages of probability 50 or more), `commit` (80 or more), `weighted` (open deals,
    amount times probability) and `won`, each as an amount per currency, and the same per owner. Lost deals, deals
    with no close date and deals with no amount are left out.
    ponytail: like the board, it reads `amount` whatever `permissions.redact` hides."""
    cat = Catalog(c)
    obj, pipeline = cat.need(stages.DEAL), pipeline_or_404(c, pipeline_id)
    close = cast(Record.values["close_date"].astext, Date)
    currency = Record.values["amount"]["currency"].astext
    amount = cast(Record.values["amount"]["amount"].astext, BigInteger)
    opens = cast(func.date_trunc(period, cast(close, DateTime)), Date)
    where = [*store.live(cat, obj), Stage.pipeline_id == pipeline.id, Stage.kind != "lost", close.is_not(None),
             currency.is_not(None)]
    where += [close >= start] if start else []
    where += [close <= end] if end else []
    rows = c.db.execute(
        select(opens.label("opens"), Record.owner_id, currency.label("cur"), Stage.kind, Stage.probability,
               func.sum(amount)).select_from(Record)
        .join(Stage, cast(Stage.id, String) == Record.values[stages.STAGE].astext).where(*where)
        .group_by("opens", Record.owner_id, "cur", Stage.kind, Stage.probability))
    periods: dict[date, dict] = {}
    for first, owner, cur, kind, probability, total in rows:
        found = periods.setdefault(first, {"all": blank(), "owners": defaultdict(blank)})
        tally([found["all"], found["owners"][owner]], cur, kind, probability, int(total))
    return {"pipeline_id": pipeline.id, "period": period, "periods": [
        {"label": label(first, period), "start": first, "end": end_of(first, period), **done(found["all"]),
         "owners": [{"owner_id": owner, **done(bucket)}
                    for owner, bucket in sorted(found["owners"].items(), key=lambda o: (o[0] is None, str(o[0])))]}
        for first, found in sorted(periods.items())]}
