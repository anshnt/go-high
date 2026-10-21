"""DKIM (RFC 6376) for sending domains whose key we manage: a 2048 bit RSA key per domain, its DNS record, and the
signature (rsa-sha256, relaxed/relaxed) added to a message just before it leaves through SMTP or SES. Mailgun and SES
"easy DKIM" sign with their own keys, which is the domain's `provider` mode. The signature covers the headers mail
providers look at, List-Unsubscribe and List-Unsubscribe-Post included (RFC 8058 asks for that)."""
import base64
import hashlib
import re
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SIGNED = ("from", "to", "subject", "date", "message-id", "reply-to", "mime-version", "content-type",
          "list-unsubscribe", "list-unsubscribe-post", "list-id", "feedback-id", "in-reply-to", "references")


def generate() -> tuple[str, str]:
    """(private key PEM, public key as base64 DER for the p= tag)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return pem, base64.b64encode(der).decode()


def record(public_key: str) -> str:
    """The TXT value of <selector>._domainkey.<domain>."""
    return f"v=DKIM1; k=rsa; p={public_key}"


def split(message: bytes) -> tuple[list[tuple[str, str]], bytes]:
    """(headers as (name, raw value with folding), body) of a message with CRLF line ends."""
    head, sep, body = message.partition(b"\r\n\r\n")
    if not sep:
        head, body = message, b""
    headers: list[tuple[str, str]] = []
    for line in head.decode("utf-8", "surrogateescape").split("\r\n"):
        if line[:1] in (" ", "\t") and headers:
            name, value = headers[-1]
            headers[-1] = (name, value + "\r\n" + line)
        elif ":" in line:
            name, value = line.split(":", 1)
            headers.append((name, value))
    return headers, body


def relaxed_header(name: str, value: str) -> str:
    value = re.sub(r"[ \t]+", " ", value.replace("\r\n", "")).strip()
    return f"{name.strip().lower()}:{value}\r\n"


def relaxed_body(body: bytes) -> bytes:
    lines = body.split(b"\r\n")
    lines = [re.sub(rb"[ \t]+", b" ", line).rstrip(b" \t") for line in lines]
    while lines and lines[-1] == b"":
        lines.pop()
    return b"\r\n".join(lines) + b"\r\n" if lines else b""


def sign(message: bytes, domain: str, selector: str, private_pem: str, now: int | None = None) -> bytes:
    """The message with a DKIM-Signature header in front. `message` must use CRLF line ends (policy SMTP)."""
    headers, body = split(message)
    present = [n for n, _ in headers]
    names = [h for h in SIGNED if any(p.lower() == h for p in present)]
    # the last instance of each signed header is the one a verifier uses (RFC 6376 5.4.2)
    by_name = {n.lower(): (n, v) for n, v in headers}
    bh = base64.b64encode(hashlib.sha256(relaxed_body(body)).digest()).decode()
    tags = (f"v=1; a=rsa-sha256; c=relaxed/relaxed; d={domain}; s={selector}; t={now or int(time.time())}; "
            f"h={':'.join(names)}; bh={bh}; b=")
    signed = "".join(relaxed_header(*by_name[n]) for n in names) + relaxed_header("DKIM-Signature", tags).rstrip("\r\n")
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    signature = base64.b64encode(key.sign(signed.encode("utf-8", "surrogateescape"), padding.PKCS1v15(),
                                          hashes.SHA256())).decode()
    # folded only where relaxed canonicalization makes no difference: after a "; ", and inside the b= value, which a
    # verifier takes out before it hashes the header
    lines = fold(tags) + [signature[i:i + 76] for i in range(0, len(signature), 76)]
    return ("DKIM-Signature: " + "\r\n\t".join(lines) + "\r\n").encode() + message


def fold(tags: str, width: int = 76) -> list[str]:
    out, line = [], ""
    for part in tags.split("; "):
        piece = part if part == "b=" else part + ";"
        if line and len(line) + 1 + len(piece) > width:
            out.append(line)
            line = piece
        else:
            line = f"{line} {piece}" if line else piece
    return out + [line]
