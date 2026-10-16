"""Messaging provider adapters (ADR 0005): `verify`, `parse` and `send` per provider, shared types in `base`.
`ADAPTERS` maps a `channels.provider` value to its module; Amazon SES sends through the SMTP adapter."""
from . import mailgun, meta_whatsapp, smtp, telnyx, twilio

ADAPTERS = {"twilio": twilio, "telnyx": telnyx, "smtp": smtp, "ses": smtp, "mailgun": mailgun, "meta": meta_whatsapp}
