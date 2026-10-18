"""go-high HTTP API. Serves /api/* and, in production, the built web app."""
import asyncio
import contextlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import api, audit, auth, config, roles, simulator, teams, webhooks, workspaces
from .calendars import availability, bookings, public, reminders  # noqa: F401  (reminders registers its job)
from .calendars import routes as calendars
from .db import get_db
from .forms import admin as forms
from .forms import analytics as form_analytics
from .forms import public as form_public
from .forms import responses as form_responses
from .inbox import channels, chat, consent, conversations, inbound, outbound, stream
from .logs import setup_logging, trace_id
from .notifications import routes as notifications
from .records import associations, board, forecast, objects, pipelines, tags, timeline, views
from .records import routes as records
from .security import COOKIE, UNSAFE
from .tasks import day
from .tasks import routes as tasks

BACKEND = Path(__file__).resolve().parents[1]
log = logging.getLogger("api")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()
    if config.SECRET_KEY == config.DEV_SECRET_KEY:
        log.warning("SECRET_KEY is not set: pagination cursors are signed with a public development key")
    # ponytail: migrations on startup; run `alembic upgrade head` as a release step
    # once there is more than one API replica.
    migrate()
    listener = asyncio.create_task(stream.listen())  # the process's one LISTEN connection (realtime)
    try:
        yield
    finally:
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener


app = FastAPI(title="go-high API", version=config.VERSION, lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None)
api.install(app)


@app.middleware("http")
async def csrf(request: Request, call_next):
    """Cookie-authenticated writes from a browser page on another origin are refused. Requests without an
    Origin header (curl, server to server) carry no ambient browser credentials worth defending. The public chat
    endpoints take no cookie, so they are exempt (a widget on a sibling domain may still be sent one)."""
    origin = request.headers.get("origin")
    if (request.method in UNSAFE and COOKIE in request.cookies and origin is not None
            and origin.rstrip("/") not in config.ALLOWED_ORIGINS and not request.url.path.startswith("/api/public/")):
        if api.is_v1(request):
            return api.error_response(403, "forbidden", "Origin not allowed")
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    return await call_next(request)


app.middleware("http")(chat.cors)
app.middleware("http")(form_public.cors)
app.middleware("http")(public.cors)


@app.middleware("http")
async def trace(request: Request, call_next):
    tid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
    token = trace_id.set(tid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = tid
        log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000)
        return response
    finally:
        trace_id.reset(token)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        log.exception("health check: database unreachable")
        return JSONResponse({"status": "degraded", "database": False}, status_code=503)
    return {"status": "ok", "database": True, "version": app.version}


app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(webhooks.router)
for module in (objects, records, associations, tags, views, timeline, pipelines, board, forecast, roles, teams,
               simulator, audit, tasks, day, notifications, channels, conversations, outbound,
               consent, inbound, stream, chat,
               forms, form_responses, form_analytics, form_public, calendars, availability, bookings, public):
    app.include_router(module.router)
app.include_router(form_public.pages)  # /f/{key} and /embed.js, before the catch-all below
app.include_router(public.pages)


@app.get("/{path:path}", include_in_schema=False)
def web(path: str):
    """Static files from the built frontend; any other non-API path gets index.html (client routing)."""
    if path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    dist = config.FRONTEND_DIST.resolve()
    file = (dist / path).resolve()
    if path and file.is_file() and file.is_relative_to(dist):
        return FileResponse(file)
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"detail": "Web app not built; run `npm run build` in frontend/ or use the Vite dev server."},
                        status_code=404)
