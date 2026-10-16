"""Pieces shared by the email adapters (smtp, mailgun)."""
import http.client
import mimetypes
import re
import time
import uuid
from email.utils import parseaddr
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from .. import ssrf
from .base import ChannelError, Outbound

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # all attachments of one message together (SES refuses messages over 10 MB)
FETCH_TIMEOUT = 10  # seconds for one attachment download


def bare_id(value: str) -> str:
    """A Message-ID without angle brackets, the form stored and compared everywhere."""
    return value.strip().strip("<>").strip()


def domain_of(address: str) -> str:
    _, at, domain = parseaddr(address)[1].rpartition("@")
    return domain.lower() if at else ""


def message_id(domain: str, key: str | None = None) -> str:
    """A new bare Message-ID on `domain`. With an idempotency key it is the same every time, so a retried send
    carries the id of the first attempt and mail clients and providers can tell it is a duplicate."""
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        domain = ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", domain):
        raise ChannelError("the sender address has no usable domain for a Message-ID")
    return f"{re.sub(r'[^A-Za-z0-9._-]', '-', key) if key else uuid.uuid4().hex}@{domain}"


def thread(message: Outbound) -> tuple[str, list[str]]:
    """(In-Reply-To, References) as bare ids; the message replied to always ends the references."""
    parent, refs = bare_id(message.in_reply_to or ""), [bare_id(r) for r in message.references]
    if parent and parent not in refs:
        refs.append(parent)
    return parent, refs


class _Text(HTMLParser):
    BREAKS = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skipping += 1
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skipping = max(self.skipping - 1, 0)
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def plain_text(html: str) -> str:
    """A text alternative for html-only mail. ponytail: links lose their URL; send a real text part when it matters."""
    parser = _Text()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def download(url: str, limit: int) -> tuple[str, bytes]:
    """GETs an attachment through the SSRF guard (public addresses only, connecting to the address that was checked)
    and returns (content type, bytes). The download gets FETCH_TIMEOUT seconds and `limit` bytes. ponytail: the
    deadline is checked between reads, so a server that drips bytes can overrun it by one read timeout."""
    try:
        t = ssrf.target(url)
    except ssrf.Blocked as e:
        raise ChannelError(f"attachment {url}: {e}") from None
    deadline = time.monotonic() + FETCH_TIMEOUT
    conn = http.client.HTTPConnection(t.host, t.port, timeout=FETCH_TIMEOUT)
    try:
        conn.sock = ssrf.connect(t, deadline)  # also used for https: the socket is already wrapped
        host = f"[{t.host}]" if ":" in t.host else t.host
        conn.request("GET", t.path, headers={"Host": host if t.port == (443 if t.https else 80) else f"{host}:{t.port}",
                                             "User-Agent": "go-high/1"})
        response = conn.getresponse()
        if response.status != 200:
            raise ChannelError(f"attachment {url}: HTTP {response.status}",
                               retryable=response.status in (408, 429) or response.status >= 500)
        chunks, size = [], 0
        while True:
            chunk = response.read1(65536)  # one read at a time, so the deadline is checked as bytes arrive
            if not chunk:
                return response.getheader("Content-Type", ""), b"".join(chunks)
            size += len(chunk)
            if size > limit:
                raise ChannelError(f"attachments are over the {MAX_ATTACHMENT_BYTES // 2**20} MB limit")
            if time.monotonic() > deadline:
                raise TimeoutError
            chunks.append(chunk)
    except (OSError, http.client.HTTPException) as e:  # TimeoutError is an OSError
        raise ChannelError(f"attachment {url}: {type(e).__name__}: {e}"[:300], retryable=True) from None
    finally:
        conn.close()


def fetch(urls: list[str]) -> list[tuple[str, str, bytes]]:
    """(file name, content type, bytes) for each attachment URL, at most MAX_ATTACHMENT_BYTES in all."""
    files, left = [], MAX_ATTACHMENT_BYTES
    for url in urls:
        ctype, data = download(url, left)
        left -= len(data)
        name = unquote(urlsplit(url).path.rsplit("/", 1)[-1]) or "attachment"
        ctype = ctype.split(";")[0].strip() or mimetypes.guess_type(name)[0] or "application/octet-stream"
        files.append((name, ctype, data))
    return files
