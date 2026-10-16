"""Background worker: `python -m app.worker`. Run as many copies as needed."""
import logging
import signal
import time

from . import config, jobs
from .db import SessionLocal
from .logs import setup_logging

log = logging.getLogger("worker")


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
