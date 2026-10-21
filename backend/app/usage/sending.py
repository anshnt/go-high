"""What a message costs, for the senders (the inbox composer, the `message.send` job, workflow steps) and the cost
preview: the meter of the channel's kind, how many units (an SMS counts its segments, email and WhatsApp count one
message per recipient), and the channel's own carrier rate (`segment_cost`, text in major units) as the unit cost when
it has one. Webchat costs nothing and has no meter."""
from .. import compliance
from . import meters, money


def unit_cost(channel) -> int | None:
    raw = (channel.config or {}).get("segment_cost")
    return None if raw in (None, "") else money.from_major(raw)


def units(channel, body: str) -> int:
    return compliance.sms_segments(body)[1] if channel.kind == "sms" else 1


def items(channel, body: str, recipients: int = 1) -> list[tuple[str, int, int | None]]:
    """(meter, quantity, unit cost) for sending `body` on `channel` to `recipients` people; empty when it is free."""
    meter = meters.BY_CHANNEL.get(channel.kind)
    return [(meter, units(channel, body) * recipients, unit_cost(channel))] if meter else []
