import ssl

import pytest
from fakes import FakeSMTP, Files, make_cert


@pytest.fixture(autouse=True)
def clean():
    """Overrides the suite's database cleanup: nothing in this directory touches the database."""
    yield


@pytest.fixture
def files():
    """A local server for attachment URLs (use with `receiver`, which allows 127.0.0.1 past the SSRF guard)."""
    server = Files()
    yield server
    server.close()


@pytest.fixture
def smtp_server():
    """Starts a FakeSMTP: smtp_server(context=None, implicit=False, login=("user", "secret"))."""
    servers = []

    def start(**kwargs):
        servers.append(FakeSMTP(**kwargs))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def tls(monkeypatch, tmp_path):
    """tls("smtp.test") makes a certificate for that name, makes the client trust it, returns the server context."""
    real = ssl.create_default_context
    trusted = []
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: _trusting(real(*a, **k), trusted))

    def make(name="smtp.test", trust=True):
        context, pem = make_cert(tmp_path, name)
        if trust:
            trusted.append(pem)
        return context

    return make


def _trusting(context, trusted):
    for pem in trusted:
        context.load_verify_locations(cadata=pem)
    return context
