"""One small HTTP client for the providers' fixed public hosts. Hosts a user can configure never come through here:
they go through `app.ssrf`. Errors are classified once, for every provider."""
import base64
import http.client
import json as jsonlib
import uuid
from urllib.parse import urlencode, urlsplit

from .base import ChannelError

TIMEOUT = 10  # seconds per socket operation
EXCERPT = 300  # characters of an unreadable error body kept in the message
MAX_RESPONSE = 1_000_000


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def multipart(fields: list[tuple[str, str]], files: list[tuple[str, str, str, bytes]]) -> tuple[str, bytes]:
    """(content type, body) for form `fields` and `files` of (field, file name, content type, data)."""
    boundary = uuid.uuid4().hex

    def quoted(s: str) -> str:
        return s.replace("\r", "").replace("\n", "").replace('"', "%22")

    body = b""
    for name, value in fields:
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{quoted(name)}"\r\n\r\n{value}\r\n'.encode()
    for name, filename, ctype, data in files:
        disposition = f'form-data; name="{quoted(name)}"; filename="{quoted(filename)}"'
        body += f"--{boundary}\r\nContent-Disposition: {disposition}\r\nContent-Type: {ctype}\r\n\r\n".encode()
        body += data + b"\r\n"
    return f"multipart/form-data; boundary={boundary}", body + f"--{boundary}--\r\n".encode()


def explain(data: dict) -> tuple[str, str]:
    """(code, message) from the error shapes of Twilio and Mailgun (top level), Telnyx (errors list), Meta (error)."""
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code", "")), str(error.get("message", ""))
    errors = data.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return str(errors[0].get("code", "")), str(errors[0].get("detail") or errors[0].get("title") or "")
    return str(data.get("code", "")), str(data.get("message", ""))


def post(url: str, *, json: object = None, form: list[tuple[str, str]] | None = None,
         files: list[tuple[str, str, str, bytes]] | None = None, headers: dict[str, str] | None = None,
         retry_codes: frozenset[str] = frozenset(), timeout: float = TIMEOUT) -> dict:
    """POSTs JSON, a urlencoded form, or a multipart form (when `files` are given) and returns the JSON answer.
    Raises ChannelError: retryable for timeouts, connection errors, 408, 429, 5xx and the provider error codes in
    `retry_codes` (throttling that comes as a 4xx); permanent for any other failure. Redirects are not followed."""
    if json is not None:
        ctype, body = "application/json", jsonlib.dumps(json).encode()
    elif files:
        ctype, body = multipart(form or [], files)
    else:
        ctype, body = "application/x-www-form-urlencoded", urlencode(form or []).encode()
    return call("POST", url, body, {"Content-Type": ctype, **(headers or {})}, retry_codes, timeout)


def get(url: str, *, headers: dict[str, str] | None = None, timeout: float = TIMEOUT) -> dict:
    """GETs and returns the JSON answer, with the same errors as `post` (for connection checks)."""
    return call("GET", url, None, headers or {}, frozenset(), timeout)


def call(method: str, url: str, body: bytes | None, headers: dict[str, str], retry_codes: frozenset[str],
         timeout: float) -> dict:
    u = urlsplit(url)
    connection = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = connection(u.hostname, u.port, timeout=timeout)
    try:
        out = {"Accept": "application/json", "User-Agent": "go-high/1", **headers}
        conn.request(method, u.path + (f"?{u.query}" if u.query else ""), body, out)
        response = conn.getresponse()
        status, raw = response.status, response.read(MAX_RESPONSE)
    except (OSError, http.client.HTTPException) as e:  # TimeoutError and ConnectionError are OSErrors
        raise ChannelError(f"{type(e).__name__}: {e}"[:EXCERPT], retryable=True) from None
    finally:
        conn.close()
    try:
        data = jsonlib.loads(raw)
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if 200 <= status < 300:
        return data
    code, reason = explain(data)
    reason = reason or raw[:EXCERPT].decode("utf-8", "replace")
    retryable = status in (408, 429) or status >= 500 or code in retry_codes
    raise ChannelError(f"HTTP {status}: {reason}"[:EXCERPT], retryable=retryable, code=code)
