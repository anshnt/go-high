"""Where email marketing meets the usage ledger (module 06, built separately). Every accepted send calls `record` in
the send's own transaction, and the pre-send check shows `estimate`. Until the ledger exists, `record` only logs and
`estimate` multiplies by EMAIL_PRICE_PER_1000.

HOOK: when the ledger lands, `record` writes one ledger entry (event `email.send`, unit `email`, quantity 1, the send
id as its idempotency reference, so a retried job cannot bill twice) and `estimate` asks the ledger for the price, and
a workspace over its monthly cap should make `allowed` answer False so the batch pauses the campaign."""
import logging
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from .. import config

log = logging.getLogger("marketing")


def record(db: Session, workspace_id: uuid.UUID, send_id: uuid.UUID) -> None:
    log.debug("usage: email.send workspace=%s send=%s", workspace_id, send_id)


def allowed(db: Session, workspace_id: uuid.UUID, quantity: int) -> bool:
    return True


def estimate(recipients: int) -> dict:
    per_1000 = Decimal(config.EMAIL_PRICE_PER_1000 or "0")
    return {"recipients": recipients, "unit": "email", "per_1000": str(per_1000),
            "estimated_cost": str((per_1000 * recipients / 1000).quantize(Decimal("0.0001")))}
