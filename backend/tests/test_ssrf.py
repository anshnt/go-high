import ipaddress
import socket
import ssl
import time

import pytest

from app import config, ssrf
from app.ssrf import Blocked, Target

BLOCKED = [
    "0.0.0.0", "0.1.2.3", "127.0.0.1", "127.255.255.254", "10.0.0.1", "10.255.255.255", "172.16.5.4",
    "172.31.255.255", "192.168.0.1", "169.254.169.254", "169.254.0.1", "100.64.0.1", "100.100.100.200",
    "100.127.255.255", "192.0.0.1", "192.0.2.1", "198.18.0.1", "198.51.100.1", "203.0.113.1", "224.0.0.1",
    "239.255.255.255", "240.0.0.1", "255.255.255.255",
    "::", "::1", "::ffff:127.0.0.1", "::ffff:7f00:1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "::ffff:0.0.0.0",
    "::ffff:100.64.0.1", "fe80::1", "fe80::1%eth0", "fc00::1", "fd00:ec2::254", "ff02::1", "64:ff9b::7f00:1",
    "64:ff9b::808:808", "2002:7f00:1::", "2002:a00:1::", "::7f00:1", "2001::1", "2001:db8::1",
]
ALLOWED = ["93.184.216.34", "8.8.8.8", "1.1.1.1", "172.32.0.1", "172.15.255.255", "100.63.255.255", "100.128.0.1",
           "2606:4700:4700::1111", "2a00:1450:4001::1", "::ffff:8.8.8.8"]


@pytest.mark.parametrize("address", BLOCKED)
def test_non_public_addresses_are_refused(address):
    with pytest.raises(Blocked):
        ssrf.check_address(address)


@pytest.mark.parametrize("address", ALLOWED)
def test_public_addresses_pass(address):
    ssrf.check_address(address)
    assert ssrf.public(ipaddress.ip_address(address))


def test_unparseable_addresses_are_refused():
    for address in ("2130706433", "0177.0.0.1", "127.1", "not-an-ip", ""):
        with pytest.raises(Blocked):
            ssrf.check_address(address)  # only what the resolver answers is ever checked, and it answers canonically


def test_the_test_allowance_needs_both_switches(monkeypatch):
    monkeypatch.setattr(config, "WEBHOOK_ALLOW_IPS", {"127.0.0.1"})
    with pytest.raises(Blocked):
        ssrf.check_address("127.0.0.1")  # the address list alone does nothing
    monkeypatch.setattr(config, "ALLOW_HTTP_WEBHOOKS", True)
    ssrf.check_address("127.0.0.1")
    with pytest.raises(Blocked):
        ssrf.check_address("127.0.0.2")  # exact addresses only
    with pytest.raises(Blocked):
        ssrf.check_address("10.0.0.1")


def test_a_public_https_url_resolves_to_a_target():
    t = ssrf.target("https://Hooks.Example.com/in/coming?a=1")
    assert (t.https, t.host, t.port, t.path, t.ips) == (True, "hooks.example.com", 443, "/in/coming?a=1",
                                                        ["93.184.216.34"])
    assert ssrf.target("https://hooks.example.com:8443").port == 8443
    assert ssrf.target("https://hooks.example.com").path == "/"


@pytest.mark.parametrize("url", [
    "http://hooks.example.com/x",  # https only
    "ftp://hooks.example.com/x", "file:///etc/passwd", "gopher://hooks.example.com/", "javascript:alert(1)",
    "//hooks.example.com/x", "hooks.example.com/x", "https://", "https:///x", "",
    "https://user:pw@hooks.example.com/x", "https://user@hooks.example.com/x",
    "https://hooks.example.com:99999/x", "https://hooks.example.com:abc/x", "https://[::1/x",
    "https://hooks.example.com/a b", "https://hooks.example.com/\r\nHost: evil", "https://hooks.example.com/é",
    "https://unknown.example.org/x",  # does not resolve
])
def test_malformed_or_forbidden_urls_are_refused(url):
    with pytest.raises(Blocked):
        ssrf.target(url)


@pytest.mark.parametrize("host", [
    "127.0.0.1", "[::1]", "[::ffff:127.0.0.1]", "[::ffff:7f00:1]", "[::]", "0.0.0.0", "169.254.169.254",
    "[fd00:ec2::254]", "[fe80::1]", "100.64.0.1", "10.1.2.3", "192.168.1.1", "localhost",
])
def test_urls_naming_non_public_hosts_are_refused_even_with_http_allowed(host, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_HTTP_WEBHOOKS", True)
    with pytest.raises(Blocked):
        ssrf.target(f"http://{host}/hook")


@pytest.mark.parametrize("host, canonical", [
    ("2130706433", "127.0.0.1"), ("0177.0.0.1", "127.0.0.1"), ("0x7f.0.0.1", "127.0.0.1"), ("127.1", "127.0.0.1"),
    ("0177.1", "127.0.0.1"), ("0x7f000001", "127.0.0.1"), ("0", "0.0.0.0"),
])
def test_odd_ipv4_spellings_are_judged_by_the_address_the_resolver_makes_of_them(host, canonical, monkeypatch):
    """inet_aton, which glibc's getaddrinfo uses, reads these as loopback or 0.0.0.0 (a resolver that rejects them
    never gets as far as an address). The guard looks at the answer, never at the spelling."""
    assert socket.inet_ntoa(socket.inet_aton(host)) == canonical
    monkeypatch.setattr(ssrf, "resolve", lambda name, port: [canonical])
    monkeypatch.setattr(config, "ALLOW_HTTP_WEBHOOKS", True)
    with pytest.raises(Blocked):
        ssrf.target(f"http://{host}/hook")


def test_every_resolved_address_must_be_public(dns):
    dns["mixed.test"] = ["93.184.216.34", "10.0.0.7"]  # one private answer poisons the name
    with pytest.raises(Blocked, match="mixed.test resolves to a non-public address"):
        ssrf.target("https://mixed.test/x")
    dns["v6.test"] = ["2606:4700:4700::1111", "::ffff:127.0.0.1"]
    with pytest.raises(Blocked):
        ssrf.target("https://v6.test/x")


def test_the_request_goes_to_the_validated_address_with_the_original_host(receiver, dns):
    dns["customer.test"] = ["127.0.0.1"]  # allowed here by the test switches
    status, body = ssrf.post(receiver.url("/in", host="customer.test"), b'{"a":1}', {"X-Test": "1"}, timeout=5)
    assert (status, body) == (200, b"ok")
    seen = receiver.requests[0]
    assert seen["headers"]["host"] == f"customer.test:{receiver.port}"
    assert seen["headers"]["x-test"] == "1" and seen["body"] == b'{"a":1}' and seen["path"] == "/in"


def test_the_name_is_resolved_once_so_rebinding_cannot_swap_the_address(receiver, monkeypatch):
    answers = iter([["127.0.0.1"], ["10.0.0.5"], ["10.0.0.5"]])
    calls = []
    monkeypatch.setattr(ssrf, "resolve", lambda host, port: calls.append(host) or next(answers))
    assert ssrf.post(receiver.url(host="rebind.test"), b"{}", {}, timeout=5)[0] == 200
    assert calls == ["rebind.test"]  # connected to the checked address, not to the name
    with pytest.raises(Blocked):  # a later send sees the new answer and is refused before any connection
        ssrf.post(receiver.url(host="rebind.test"), b"{}", {}, timeout=5)
    assert len(receiver.requests) == 1


def test_a_name_that_turns_private_after_saving_is_refused_at_send_time(dns):
    dns["flip.test"] = ["93.184.216.34"]
    ssrf.target("https://flip.test/x")  # fine when saved
    dns["flip.test"] = ["169.254.169.254"]
    with pytest.raises(Blocked):
        ssrf.post("https://flip.test/x", b"{}", {}, timeout=1)


def test_https_connects_to_the_ip_and_verifies_the_original_name(monkeypatch):
    seen = {}

    class Context:
        def wrap_socket(self, sock, server_hostname):
            seen["server_hostname"] = server_hostname
            return sock

    def create_connection(address, timeout):
        seen["address"] = address
        return object()

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(ssl, "create_default_context", lambda: Context())
    ssrf.connect(Target(True, "hooks.example.com", 443, "/", ["93.184.216.34"]), time.monotonic() + 5)
    assert seen == {"address": ("93.184.216.34", 443), "server_hostname": "hooks.example.com"}


def test_redirects_are_returned_not_followed(receiver):
    receiver.default = (302, b"", {"Location": receiver.url("/elsewhere")})
    assert ssrf.post(receiver.url(), b"{}", {}, timeout=5)[0] == 302
    assert [r["path"] for r in receiver.requests] == ["/hook"]


def test_the_response_body_is_capped(receiver):
    receiver.default = (200, b"x" * 10_000, {})
    assert len(ssrf.post(receiver.url(), b"{}", {}, timeout=5)[1]) == ssrf.EXCERPT


def test_the_timeout_covers_a_receiver_that_trickles_headers(receiver):
    receiver.trickle = True  # every read succeeds quickly, so a per-read timeout alone would wait 20 s
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        ssrf.post(receiver.url(), b"{}", {}, timeout=0.6)
    assert time.monotonic() - started < 3


def test_a_slow_receiver_times_out(receiver):
    receiver.delay = 2
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        ssrf.post(receiver.url(), b"{}", {}, timeout=0.5)
    assert time.monotonic() - started < 2
