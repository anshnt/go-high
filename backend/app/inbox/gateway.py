"""Where the inbox calls a provider adapter (app/channels): builds the adapter's Channel from a row and its decrypted
secrets, and sends or checks through it. Provider hosts are fixed; `BASE_URLS` lets a test point a provider at a local
server."""
from .. import config
from ..channels import ADAPTERS, base
from ..channels.base import ChannelError, Outbound, SendResult
from . import vault
from .models import Channel

BASE_URLS: dict[str, str] = {}


def hook_url(channel: Channel) -> str:
    """The URL to paste into the provider's console. Twilio signs it, so it is also the URL verification uses."""
    return f"{config.ALLOWED_ORIGINS[0]}/api/hooks/{channel.provider}/{channel.id}"


def account(channel: Channel, secrets: dict | None = None) -> base.Channel:
    return base.Channel(channel.address, channel.config, vault.of(channel) if secrets is None else secrets)


def options(channel: Channel) -> dict:
    return {"base_url": BASE_URLS[channel.provider]} if channel.provider in BASE_URLS else {}


def send(channel: Channel, message: Outbound) -> SendResult:
    if channel.provider not in ADAPTERS:
        raise ChannelError(f"{channel.provider} cannot send")
    return ADAPTERS[channel.provider].send(account(channel), message, **options(channel))


def check(channel: Channel) -> str | None:
    """Asks the provider to accept the channel's credentials. None when the adapter has no check; raises
    ChannelError when the provider refuses."""
    adapter = ADAPTERS.get(channel.provider)
    test = getattr(adapter, "check", None)
    if test is None:
        return None
    return test(account(channel), **options(channel))
