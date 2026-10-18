import base64
import re
import socket
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


class Files:
    """A local HTTP server that serves attachments: `files` maps a path to (content type, bytes); a path in `fail`
    answers with that status instead; `delay` holds every answer back."""

    def __init__(self):
        self.files: dict[str, tuple[str, bytes]] = {}
        self.fail: dict[str, int] = {}
        self.delay = 0.0
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                ctype, data = outer.files.get(self.path, (None, None))
                time.sleep(outer.delay)
                try:
                    if data is None or self.path in outer.fail:
                        self.send_response(outer.fail.get(self.path, 404))
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}{path}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def make_cert(tmp_path, name: str = "smtp.test"):
    """A self-signed certificate for `name`: (server TLS context, certificate PEM to trust)."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, True, False, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    pem = cert.public_bytes(serialization.Encoding.PEM)
    certfile, keyfile = tmp_path / f"{name}.crt", tmp_path / f"{name}.key"
    certfile.write_bytes(pem)
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    return context, pem.decode()


class FakeSMTP:
    """A tiny SMTP server. With a TLS `context` it offers STARTTLS, or speaks TLS from the first byte when
    `implicit`. It offers AUTH PLAIN once the connection is encrypted, checks it against `login`, and records every
    accepted message in `messages` as {"from", "to", "data", "secure", "user", "helo"}. `replies` overrides what the
    server answers to a command: {"RCPT": "550 no such user"}, "GREETING" ("HANG": say nothing) and "END" (after the
    message data) too."""

    def __init__(self, context=None, implicit=False, login=("user", "secret")):
        self.context, self.implicit, self.login = context, implicit and context is not None, login
        self.messages: list[dict] = []
        self.commands: list[str] = []  # the verb of every command received
        self.replies: dict[str, str] = {}
        self.connections = 0
        self.closed = False
        self.server = socket.create_server(("127.0.0.1", 0))
        threading.Thread(target=self.accept, daemon=True).start()

    @property
    def port(self) -> int:
        return self.server.getsockname()[1]

    def accept(self) -> None:
        while not self.closed:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn: socket.socket) -> None:
        try:
            self.talk(conn)
        except (OSError, ssl.SSLError):
            pass  # the client hung up, or refused our certificate
        finally:
            conn.close()

    def talk(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        secure = False
        if self.implicit:
            conn, secure = self.context.wrap_socket(conn, server_side=True), True
        reader = conn.makefile("rb")

        def say(line: str) -> None:
            conn.sendall(line.encode() + b"\r\n")

        greeting = self.replies.get("GREETING", "220 fake.test ESMTP")
        if greeting == "HANG":  # never greets: the client must time out
            time.sleep(3)
            return
        say(greeting)
        if not greeting.startswith("2"):
            return
        sender, recipients, user, helo = "", [], None, ""
        while line := reader.readline():
            command = line.decode().rstrip("\r\n")
            verb = command.split(" ")[0].upper()
            self.commands.append(verb)
            if verb in self.replies:
                say(self.replies[verb])
                continue
            if verb == "EHLO":
                helo = command.split(" ", 1)[1]
                say("250-fake.test")
                if self.context and not self.implicit and not secure:
                    say("250-STARTTLS")
                if self.login and (secure or not self.context):
                    say("250-AUTH PLAIN")
                say("250 8BITMIME")
            elif verb == "STARTTLS":
                say("220 ready")
                conn, secure = self.context.wrap_socket(conn, server_side=True), True
                reader = conn.makefile("rb")
            elif verb == "AUTH":
                _, user_name, password = base64.b64decode(command.split()[2]).split(b"\0")
                if (user_name.decode(), password.decode()) == self.login:
                    user = user_name.decode()
                    say("235 2.7.0 ok")
                else:
                    say("535 5.7.8 credentials invalid")
            elif verb == "MAIL":
                sender, recipients = re.search(r"<([^>]*)>", command).group(1), []
                say("250 ok")
            elif verb == "RCPT":
                recipients.append(re.search(r"<([^>]*)>", command).group(1))
                say("250 ok")
            elif verb == "DATA":
                say("354 go ahead")
                data = b""
                while (row := reader.readline()) != b".\r\n":
                    data += row[1:] if row.startswith(b"..") else row
                say(self.replies.get("END", "250 queued"))
                if self.replies.get("END", "2")[0] == "2":
                    self.messages.append({"from": sender, "to": recipients, "data": data, "secure": secure,
                                          "user": user, "helo": helo})
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("250 ok")

    def close(self) -> None:
        self.closed = True
        self.server.close()
