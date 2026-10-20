"""Provider webhooks (module 21): `POST /api/hooks/payments/{provider}`, public, no session. The signature is checked
on the raw body first (401 for anything unsigned, wrongly signed or older than five minutes, so a captured request
cannot be replayed later); only then is the body read. Each event names the provider account it is about, which finds
the workspace in the system scope; the request then moves into that workspace and applies the event once (see
ledger.py). An event about an account nobody connected is acknowledged and dropped, so the provider stops sending it;
one that names a payment we have not committed yet is answered 409, so the provider sends it again later."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from ..db import rescope, scoped
from ..models import Workspace
from . import ledger, providers
from .models import PaymentAccount
from .scope import system_ctx

log = logging.getLogger("payments")
router = APIRouter()


@router.post("/api/hooks/payments/{provider}")
async def hook(provider: str, request: Request):
    headers, body = dict(request.headers), await request.body()
    return await run_in_threadpool(process, provider, headers, body)


def process(provider_key: str, headers: dict[str, str], body: bytes) -> dict:
    try:
        provider = providers.get(provider_key)
    except KeyError:
        raise HTTPException(404, "Not found") from None
    if provider.available() is not None and provider_key == "fake":
        raise HTTPException(404, "Not found")  # the test provider does not exist where it is switched off
    if not provider.verify(headers, body):
        log.warning("payments webhook from %s refused: no valid signature", provider_key)
        raise HTTPException(401, "Invalid signature")
    try:
        updates = provider.parse(body)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, "The webhook body is not readable") from None
    applied = 0
    with scoped(system="on") as db:
        for u in updates:
            rescope(db, system="on")
            acct = db.scalar(select(PaymentAccount).where(PaymentAccount.provider == provider_key,
                                                          PaymentAccount.account_id == (u.account_id or "")))
            if acct is None:
                log.info("payments webhook %s for an account nobody connected: dropped", u.event_id)
                continue
            ws = db.get(Workspace, acct.workspace_id)
            db.commit()
            rescope(db, workspace_id=ws.id, org_id=ws.org_id)
            if not ledger.record_event(db, ws.id, provider_key, u):
                db.rollback()
                continue  # seen before: a replay changes nothing
            acct = db.get(PaymentAccount, acct.id, populate_existing=True)
            try:
                ledger.apply(system_ctx(db, ws), acct, u, datetime.now(UTC))
            except ledger.Retry as e:
                db.rollback()
                log.info("payments webhook %s: %s; asking for it again", u.event_id, e)
                raise HTTPException(409, "Not ready, send it again") from None
            db.commit()
            applied += 1
    return {"received": True, "applied": applied}
