"""go-high HTTP API. Serves /api/* and, in production, the built web app."""
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .logs import setup_logging, trace_id

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
    # ponytail: migrations on startup; run `alembic upgrade head` as a release step
    # once there is more than one API replica.
    migrate()
    yield


app = FastAPI(title="go-high API", version="0.1.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None)


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


@app.get("/{path:path}", include_in_schema=False)
def web(path: str):
    """Static files from the built frontend; any other non-API path gets index.html (client routing)."""
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    dist = config.FRONTEND_DIST.resolve()
    file = (dist / path).resolve()
    if path and file.is_file() and file.is_relative_to(dist):
        return FileResponse(file)
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"detail": "Web app not built; run `npm run build` in frontend/ or use the Vite dev server."},
                        status_code=404)
