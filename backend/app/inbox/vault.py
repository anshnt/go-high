"""Provider secrets at rest (ADR 0005): a channel's API keys and passwords are one JSON document, encrypted with
AES-256-GCM under a key derived (HKDF-SHA256) from SECRET_KEY, bound to its row and workspace so a ciphertext copied
to another row does not open. Request handlers can write the `secrets` table but cannot read the ciphertext (column
grants), so only code that sends, verifies or tests a channel decrypts, through `reveal` on the owner role. No API
response, event, job payload or log carries a secret.
ponytail: one key and no version column; rotating SECRET_KEY needs a re-encrypt job before it is changed."""
import json
import os
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from .models import Channel, Secret

INFO = b"go-high channel secrets v1"
VERSION = b"\x01"


def key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(config.SECRET_KEY.encode())


def aad(ref: uuid.UUID, workspace_id: uuid.UUID) -> bytes:
    return ref.bytes + workspace_id.bytes


def encrypt(values: dict, ref: uuid.UUID, workspace_id: uuid.UUID) -> bytes:
    nonce = os.urandom(12)
    return VERSION + nonce + AESGCM(key()).encrypt(nonce, json.dumps(values).encode(), aad(ref, workspace_id))


def decrypt(blob: bytes, ref: uuid.UUID, workspace_id: uuid.UUID) -> dict:
    if blob[:1] != VERSION:
        raise ValueError("unknown secret format")
    return json.loads(AESGCM(key()).decrypt(blob[1:13], blob[13:], aad(ref, workspace_id)))


def reveal(ref: uuid.UUID | None) -> dict:
    """The decrypted secrets of a `secret_ref`, read on the owner role (the request role cannot read them)."""
    if ref is None:
        return {}
    with SessionLocal() as db:
        row = db.execute(select(Secret.workspace_id, Secret.ciphertext).where(Secret.id == ref)).one_or_none()
    return decrypt(bytes(row.ciphertext), ref, row.workspace_id) if row else {}


def of(channel: Channel) -> dict:
    return reveal(channel.secret_ref)


def put(db: Session, workspace_id: uuid.UUID, values: dict, ref: uuid.UUID | None = None) -> uuid.UUID:
    """Stores `values` in the caller's transaction: a new secret, or merged into the existing `ref` (a null value
    removes its key). Returns the secret's id."""
    if ref is None:
        ref = uuid.uuid4()
        db.execute(insert(Secret).values(id=ref, workspace_id=workspace_id,
                                         ciphertext=encrypt({k: v for k, v in values.items() if v is not None},
                                                            ref, workspace_id)))
        return ref
    merged = {k: v for k, v in {**reveal(ref), **values}.items() if v is not None}
    db.execute(update(Secret).where(Secret.id == ref).values(ciphertext=encrypt(merged, ref, workspace_id),
                                                             updated_at=func.now()))
    return ref
