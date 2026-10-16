"""Outbound webhook requests: the SSRF guard, and a POST that connects to the address it validated.

The URL's host is resolved once and every resolved address must be public. The socket is then opened to one of
those addresses, not to the name, so an answer that changes between the check and the connection (DNS rebinding)
cannot redirect the request. The original host still goes into the Host header and the TLS handshake (SNI and
certificate check)."""
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config

EXCERPT = 2048  # bytes of the response body kept


class Blocked(ValueError):
    """The URL, or an address it resolves to, may not be called."""


@dataclass
class Target:
    https: bool
    host: str
    port: int
    path: str
    ips: list[str]


def public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Routable unicast only: no private, loopback, link-local, CGNAT (100.64/10), multicast, reserved or
    unspecified space. IPv4-mapped IPv6 is judged as the IPv4 address inside it; NAT64 and 6to4 fall in the
    reserved or private IPv6 ranges and are refused."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved)


def check_address(address: str) -> None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        raise Blocked(f"{address!r} is not an IP address") from None
    if public(ip) or (config.ALLOW_HTTP_WEBHOOKS and str(ip) in config.WEBHOOK_ALLOW_IPS):
        return
    raise Blocked("not a public address")  # the address itself stays out of messages: it may be an internal answer


def resolve(host: str, port: int) -> list[str]:
    """What the system resolver says, which also normalizes forms like 2130706433 or 0177.0.0.1 where the
    resolver accepts them. Whatever it answers is what gets checked and connected to."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError, ValueError):
        raise Blocked(f"{host} does not resolve") from None
    return list(dict.fromkeys(info[4][0] for info in infos))


def target(url: str) -> Target:
    """Parses and resolves `url`; raises Blocked unless every address it resolves to may be called."""
    if not url.isascii() or any(c <= " " or c == "\x7f" for c in url):
        raise Blocked("must be a plain ASCII URL without spaces")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise Blocked("is not a valid URL") from None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise Blocked("must be an absolute https URL")
    if parts.scheme == "http" and not config.ALLOW_HTTP_WEBHOOKS:
        raise Blocked("must use https")
    if parts.username is not None or parts.password is not None:
        raise Blocked("must not contain credentials")
    https = parts.scheme == "https"
    port = port or (443 if https else 80)
    ips = resolve(parts.hostname, port)
    try:
        for ip in ips:
            check_address(ip)
    except Blocked:
        raise Blocked(f"{parts.hostname} resolves to a non-public address") from None
    return Target(https, parts.hostname, port, (parts.path or "/") + (f"?{parts.query}" if parts.query else ""), ips)


def connect(t: Target, deadline: float) -> socket.socket:
    error: OSError | None = None
    for ip in t.ips:
        try:
            sock = socket.create_connection((ip, t.port), timeout=max(deadline - time.monotonic(), 0.01))
            break
        except OSError as e:
            error = e
    else:
        raise error or OSError("no address to connect to")
    if t.https:
        try:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=t.host)
        except BaseException:
            sock.close()
            raise
    return sock


def post(url: str, body: bytes, headers: dict[str, str], timeout: float = 10) -> tuple[int, bytes]:
    """POSTs and returns (status, first 2 KB of the response body). Redirects are returned, never followed.
    The address check runs here as well as at save time. The whole exchange gets `timeout` seconds."""
    t = target(url)
    sock = connect(t, time.monotonic() + timeout)
    host = f"[{t.host}]" if ":" in t.host else t.host
    default_port = 443 if t.https else 80
    conn = http.client.HTTPConnection(t.host, t.port, timeout=timeout)  # also used for https: the socket is wrapped
    conn.sock = sock
    expired = threading.Event()

    def abort() -> None:  # a receiver that trickles bytes must not hold a worker past the deadline
        expired.set()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    watchdog = threading.Timer(timeout, abort)
    watchdog.start()
    try:
        conn.request("POST", t.path, body, {"Host": host if t.port == default_port else f"{host}:{t.port}", **headers})
        response = conn.getresponse()
        return response.status, response.read(EXCERPT)
    except Exception as e:
        if expired.is_set() or isinstance(e, TimeoutError):
            raise TimeoutError(f"timed out after {timeout:g} s") from None
        raise
    finally:
        watchdog.cancel()
        conn.close()
