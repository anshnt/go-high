"""Background worker: `python -m app.worker`. Run as many copies as needed."""
import logging
import signal
import tempfile
import time
from pathlib import Path

from . import config, jobs, webhooks  # noqa: F401  (webhooks registers the delivery handlers)
from .db import SessionLocal
from .logs import setup_logging
from .notifications import consumer  # noqa: F401  (the notifications consumer and the task.due job)

log = logging.getLogger("worker")
HEARTBEAT = Path(tempfile.gettempdir(), "worker-heartbeat")  # docker healthcheck: stale file = stuck worker


def main() -> None:
    setup_logging()
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker started, handlers: %s", ", ".join(sorted(jobs.HANDLERS)))
    while not stopping:
        HEARTBEAT.touch()
        try:
            if jobs.run_one(SessionLocal):
                continue
        except Exception:
            log.exception("worker loop error")  # e.g. database restart; keep going
        # ponytail: polling; switch to LISTEN/NOTIFY wake-ups if 1 s pickup latency matters.
        time.sleep(config.WORKER_POLL_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
