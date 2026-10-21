"""Payment providers (module 21): `get(key)` for the provider of a key, `PROVIDERS` for all of them. See base.py for the
interface."""
from . import fake, stripe

PROVIDERS = {stripe.key: stripe, fake.key: fake}


def get(key: str):
    provider = PROVIDERS.get(key)
    if provider is None:
        raise KeyError(key)
    return provider
