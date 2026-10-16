"""API conventions (ADR 0003) for /api/v1: one error envelope, signed cursor pagination, idempotency keys.
/api/auth and the other older routes keep their `{"detail": ...}` errors."""
import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, delete, func, select, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config
from .db import Base
from .logs import trace_id
from .security import Ctx, in_workspace

log = logging.getLogger("api")
V1 = "/api/v1"
IDEMPOTENCY_TTL = timedelta(hours=24)
CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
         409: "conflict", 422: "validation_failed", 429: "rate_limited"}


def is_v1(request: Request) -> bool:
    return request.url.path == V1 or request.url.path.startswith(V1 + "/")


class ApiError(HTTPException):
    """An error with a machine readable `code`, and optionally per-field messages."""

    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(status, message, headers)
        self.code, self.fields = code, fields


def error_response(status: int, code: str, message: str, fields: dict[str, str] | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    error = {"code": code, "message": message, **({"fields": fields} if fields else {}), "trace_id": trace_id.get()}
    return JSONResponse({"error": error}, status_code=status, headers=headers)


class Replay(Exception):
    """Answers with the response stored under an Idempotency-Key instead of running the request again."""

    def __init__(self, status: int, content):
        self.status, self.content = status, content


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if not is_v1(request):
            return await http_exception_handler(request, exc)
        code = getattr(exc, "code", None) or CODES.get(exc.status_code, f"http_{exc.status_code}")
        return error_response(exc.status_code, code, str(exc.detail), getattr(exc, "fields", None), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if not is_v1(request):
            return await request_validation_exception_handler(request, exc)
        fields = {".".join(map(str, e["loc"][1:])) or str(e["loc"][0]): e["msg"].removeprefix("Value error, ")
                  for e in exc.errors()}
        return error_response(422, "validation_failed", "The request is not valid", fields)

    @app.exception_handler(DataError)
    async def unstorable(request: Request, exc: DataError):
        """A value Postgres refuses (a NUL character, a number out of range) that validation did not catch."""
        if not is_v1(request):
            raise exc
        log.warning("the database refused a value: %s", exc.orig)
        return error_response(422, "validation_failed", "The request holds a value that cannot be stored")

    @app.exception_handler(Replay)
    async def replay(request: Request, exc: Replay):
        return JSONResponse(exc.content, status_code=exc.status, headers={"Idempotent-Replayed": "true"})


# --- pagination -----------------------------------------------------------------------------------------------

def sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def seal(parts: list) -> str:
    """A signed, opaque token for a list of JSON values (a sort key and an id, or several sort keys)."""
    payload = base64.urlsafe_b64encode(json.dumps(parts).encode()).decode().rstrip("=")
    return f"{payload}.{sign(payload)}"


def unseal(cursor: str) -> list:
    try:
        payload, signature = cursor.rsplit(".", 1)
        if not hmac.compare_digest(signature, sign(payload)):
            raise ValueError("bad signature")
        parts = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(parts, list):
            raise ValueError("not a list")
        return parts
    except (ValueError, TypeError):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None


def encode_cursor(created_at: datetime, id_: uuid.UUID) -> str:
    return seal([created_at.isoformat(), str(id_)])


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, id_ = unseal(cursor)
        return datetime.fromisoformat(created_at), uuid.UUID(id_)
    except (ValueError, TypeError):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None


def paginate(db: Session, stmt, model, limit: int, cursor: str | None, by: str = "created_at"):
    """Newest first by (`by`, id), `by` being a timestamp column of `model` (default created_at). `stmt` selects
    `model` as its first column. Returns the rows and the cursor of the next page, or None on the last page. The
    cursor is signed, so it cannot be forged or edited.
    ponytail: ids are uuids and the sort key is a timestamp; other sort orders need their own cursor payload."""
    key = getattr(model, by)
    if cursor:
        stmt = stmt.where(tuple_(key, model.id) < tuple_(*decode_cursor(cursor)))
    rows = db.execute(stmt.order_by(key.desc(), model.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return page, encode_cursor(getattr(page[-1][0], by), page[-1][0].id) if len(rows) > limit else None


# --- idempotency keys -----------------------------------------------------------------------------------------

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (Index("ix_idempotency_keys_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def stored_for(db: Session, workspace_id: uuid.UUID, key: str) -> IdempotencyKey | None:
    return db.scalar(select(IdempotencyKey).where(
        IdempotencyKey.workspace_id == workspace_id, IdempotencyKey.key == key,
        IdempotencyKey.created_at > func.now() - IDEMPOTENCY_TTL))


def replay_or_conflict(stored: IdempotencyKey, digest: str):
    if stored.request_hash != digest:
        raise ApiError(409, "idempotency_key_reused", "This Idempotency-Key was already used with a different request")
    raise Replay(stored.status, stored.response)


class Idem:
    """Ends a POST handler: `return idem.commit(201, body)` commits the handler's work together with the response
    stored under the Idempotency-Key, so a retry can never repeat the work. Without a key it is a plain commit."""

    def __init__(self, db: Session, workspace_id: uuid.UUID, key: str | None, digest: str):
        self.db, self.workspace_id, self.key, self.digest = db, workspace_id, key, digest

    def commit(self, status: int, content) -> JSONResponse:
        content = jsonable_encoder(content)
        if self.key:
            # ponytail: expired keys are removed when the same workspace stores a new one, so a workspace that
            # stops posting keeps at most its last 24 hours of rows. A purge job can replace this.
            self.db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < func.now() - IDEMPOTENCY_TTL))
            self.db.add(IdempotencyKey(workspace_id=self.workspace_id, key=self.key, request_hash=self.digest,
                                       status=status, response=content))
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            stored = stored_for(self.db, self.workspace_id, self.key) if self.key else None
            if stored is None:
                raise
            replay_or_conflict(stored, self.digest)  # a concurrent request with this key committed first
        return JSONResponse(content, status_code=status)


async def raw_body(request: Request) -> bytes:
    return await request.body()  # cached by Starlette, so the route still parses it


def idempotency(request: Request, c: Ctx = Depends(in_workspace), body: bytes = Depends(raw_body),
                idempotency_key: str | None = Header(default=None, min_length=1, max_length=255)) -> Idem:
    """For POST routes in a workspace. List it after the role dependency of the route. A repeated key with the same
    request answers with the stored response (header `Idempotent-Replayed: true`); with a different request, 409.
    Keys live 24 hours; only successful responses are stored."""
    digest = hashlib.sha256(f"{request.method} {request.url.path}?{request.url.query}\n".encode() + body).hexdigest()
    if idempotency_key and (stored := stored_for(c.db, c.workspace.id, idempotency_key)):
        replay_or_conflict(stored, digest)
    return Idem(c.db, c.workspace.id, idempotency_key, digest)
