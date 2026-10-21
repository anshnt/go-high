"""What is metered: one entry per kind of paid action. A ledger row names its meter and a whole number of its units. The
platform's own cost of a unit (what a carrier or a model provider charges) is `USAGE_COSTS`, a JSON map of meter to
micros in the environment (all zero when unset: a self-hosted install pays its carriers directly), and a channel's
`segment_cost` overrides it for the messages sent on that channel. What a workspace is charged is decided by rate cards
(pricing.py)."""
import json
import logging
import os

log = logging.getLogger("usage")

# meter: (label, unit, unit plural)
METERS = {
    "sms.segment": ("SMS", "segment", "segments"),
    "email.message": ("Email", "email", "emails"),
    "whatsapp.message": ("WhatsApp", "message", "messages"),
    "call.minute": ("Calls", "minute", "minutes"),
    "ai.credit": ("AI", "credit", "credits"),
    "workflow.premium_action": ("Premium workflow actions", "action", "actions"),
}
BY_CHANNEL = {"sms": "sms.segment", "email": "email.message", "whatsapp": "whatsapp.message"}  # webchat is free


def _costs(raw: str) -> dict[str, int]:
    try:
        given = json.loads(raw or "{}")
        costs = {k: int(v) for k, v in given.items() if k in METERS and int(v) >= 0}
    except (ValueError, TypeError, AttributeError):
        log.warning("USAGE_COSTS is not a JSON object of meter to whole micros; every platform cost is 0")
        return {}
    if unknown := set(given) - set(METERS):
        log.warning("USAGE_COSTS names meters that do not exist: %s", ", ".join(sorted(unknown)))
    return costs


COSTS = _costs(os.getenv("USAGE_COSTS", ""))


def platform_cost(meter: str) -> int:
    return COSTS.get(meter, 0)


def describe(meter: str, quantity: int) -> str:
    label, one, many = METERS[meter]
    return f"{label}: {quantity} {one if quantity == 1 else many}"
