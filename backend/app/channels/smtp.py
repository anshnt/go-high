"""SMTP email. Amazon SES works through this adapter: use its SMTP endpoint (email-smtp.<region>.amazonaws.com, port 587
with starttls or 465 with tls) and the SMTP credentials SES issues. Delivery events from SES (SNS) are not read here.

The host is user configured, so it is resolved and checked with `app.ssrf` (public addresses only) and the socket is
opened to the address that was checked, while the name stays the TLS server name (SNI and certificate check), as in
`ssrf.post`. There is no plaintext mode: `security` is "starttls" (default, port 587) or "tls" (port 465), and a
server that does not offer STARTTLS is refused, so credentials and mail never cross the network in the clear.

channel.address: the From address. config: host, port, security, username, message_id_domain (default: the domain of
the From address). secrets: password. SMTP has no webhooks: `verify` is always False and `parse` finds nothing."""
import smtplib
import ssl
import time
from dataclasses import replace
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, parseaddr

from .. import ssrf
from . import dkim, mail
from .base import Channel, ChannelError, Inbound, Outbound, Request, SendResult

# ponytail: seconds per socket operation, not a total deadline; add a watchdog like ssrf.post if a tenant's slow server
# ever holds a worker too long
TIMEOUT = 10


class Pinned(smtplib.SMTP):
    """Connects to the validated address while `_host` stays the name, so STARTTLS checks the certificate for it
    (and `ssrf.connect` does for implicit TLS)."""

    def __init__(self, target: ssrf.Target, local_hostname: str):
        self.target = target
        super().__init__(target.host, target.port, local_hostname=local_hostname, timeout=TIMEOUT)

    def _get_socket(self, host, port, timeout):
        return ssrf.connect(self.target, time.monotonic() + timeout)


def verify(channel: Channel, request: Request) -> bool:
    return False


def parse(request: Request) -> list[Inbound]:
    return []


def pin(host: str, port: int, tls: bool) -> ssrf.Target:
    try:
        t = ssrf.target(f"https://{f'[{host}]' if ':' in host else host}:{port}/")
    except ssrf.Blocked as e:
        raise ChannelError(f"SMTP host {host}: {e}") from None
    if t.host != host.strip("[]").lower():
        raise ChannelError("the SMTP host must be a plain host name or address")
    return replace(t, https=tls)  # https here means TLS from the first byte


def build(channel: Channel, message: Outbound) -> tuple[EmailMessage, str]:
    """The MIME message and its bare Message-ID."""
    mid = mail.message_id(channel.config.get("message_id_domain") or mail.domain_of(message.from_ or channel.address),
                          message.idempotency_key)
    files = mail.fetch(message.attachments)
    msg = EmailMessage()
    try:
        msg["From"], msg["To"], msg["Subject"] = message.from_ or channel.address, message.to, message.subject or ""
        msg["Date"], msg["Message-ID"] = formatdate(usegmt=True), f"<{mid}>"
        if message.reply_to:
            msg["Reply-To"] = message.reply_to
        parent, refs = mail.thread(message)
        if parent:
            msg["In-Reply-To"] = f"<{parent}>"
        if refs:
            msg["References"] = " ".join(f"<{r}>" for r in refs)
        if message.unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{message.unsubscribe_url}>"
            if message.unsubscribe_url.startswith("https://"):
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"  # RFC 8058
        for name, value in message.headers.items():
            msg[name] = value
    except ValueError as e:  # the email policy refuses header values with line breaks
        raise ChannelError(f"invalid header: {e}") from None
    msg.set_content(message.body or (mail.plain_text(message.html) if message.html else ""))
    if message.html:
        msg.add_alternative(message.html, subtype="html")
    for name, ctype, data in files:
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    return msg, mid


def classify(e: Exception, sending: bool = False) -> ChannelError:
    """4xx replies and lost connections are worth retrying; 5xx replies, a refused login, a missing STARTTLS or a
    certificate that does not match the host are not. A connection lost while the message was being handed over
    (`sending`) is ambiguous: the server may have taken it."""
    error = _classify(e)
    if sending and not isinstance(e, smtplib.SMTPResponseException | smtplib.SMTPRecipientsRefused):
        error.ambiguous = True
    return error


def _classify(e: Exception) -> ChannelError:
    if isinstance(e, ssl.SSLCertVerificationError):
        return ChannelError(f"the SMTP server's certificate was refused: {e.verify_message}")
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        code, text = next(iter(e.recipients.values()))
        return ChannelError(f"SMTP {code}: {text.decode(errors='replace')}"[:300], retryable=400 <= code < 500,
                            code=str(code))
    if isinstance(e, smtplib.SMTPResponseException):
        return ChannelError(f"SMTP {e.smtp_code}: {e.smtp_error.decode(errors='replace')}"[:300],
                            retryable=400 <= e.smtp_code < 500, code=str(e.smtp_code))
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return ChannelError("the SMTP server closed the connection", retryable=True)
    if isinstance(e, smtplib.SMTPException):  # SMTPException is itself an OSError: it must be judged before one
        return ChannelError(f"SMTP: {e}"[:300])  # no STARTTLS, no usable AUTH method
    if isinstance(e, OSError):  # timeouts, refused or reset connections, TLS handshake failures
        return ChannelError(f"{type(e).__name__}: {e}"[:300], retryable=True)
    raise e


def server(channel: Channel) -> tuple[str, ssrf.Target]:
    """(security, the validated address to connect to) from the channel's settings."""
    security = channel.config.get("security", "starttls")
    if security not in ("starttls", "tls"):
        raise ChannelError('security must be "starttls" or "tls"')
    try:
        port = int(channel.config.get("port") or (465 if security == "tls" else 587))
    except (TypeError, ValueError):
        raise ChannelError("the SMTP port is not a number") from None
    if channel.config.get("username"):
        channel.secret("password")  # a missing password is a config error, found before any connection
    return security, pin(channel.conf("host"), port, security == "tls")


def login(smtp: smtplib.SMTP, channel: Channel, security: str) -> None:
    if security == "starttls":
        smtp.starttls(context=ssl.create_default_context())  # smtplib's own default does not verify
    user = channel.config.get("username")
    if user:
        smtp.login(user, channel.secret("password"))


def check(channel: Channel) -> str:
    """Connects, encrypts and logs in, without sending anything."""
    security, target = server(channel)
    try:
        with Pinned(target, mail.domain_of(channel.address) or "localhost") as smtp:
            login(smtp, channel, security)
            smtp.noop()
    except Exception as e:
        raise classify(e) from None
    return "the SMTP server accepted the connection and login"


def wire(msg: EmailMessage, message: Outbound) -> bytes:
    """The message as it goes over the wire (CRLF line ends), DKIM signed when the outbound asks for it."""
    raw = msg.as_bytes(policy=policy.SMTP)
    if message.dkim:
        domain, selector, key = message.dkim
        raw = dkim.sign(raw, domain, selector, key)
    return raw


def send(channel: Channel, message: Outbound) -> SendResult:
    security, target = server(channel)
    msg, mid = build(channel, message)
    raw, sending = wire(msg, message), False
    try:
        with Pinned(target, mail.domain_of(str(msg["From"]))) as smtp:
            login(smtp, channel, security)
            sending = True
            smtp.sendmail(parseaddr(str(msg["From"]))[1], [parseaddr(message.to)[1]], raw)
    except Exception as e:
        raise classify(e, sending) from None
    return SendResult(mid)
