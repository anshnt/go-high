"""The worker loop (`python -m app.worker`), with the queue and the clock faked: it keeps going through errors, waits
only when there is nothing to do, beats its heartbeat, and stops cleanly on SIGTERM or SIGINT."""
import logging
import signal

import pytest

from app import jobs, worker


@pytest.fixture(autouse=True)
def clean():
    """Overrides the suite's database cleanup: nothing here touches the database."""
    yield


@pytest.fixture
def loop(monkeypatch, tmp_path):
    """Runs worker.main with `run_one` answering from a script: True (did a job), False (queue empty), an exception
    (the database went away), or "TERM"/"INT" (that signal arrives). Returns what happened."""
    handlers, sleeps = {}, []
    monkeypatch.setattr(worker, "setup_logging", lambda: None)
    monkeypatch.setattr(worker, "HEARTBEAT", tmp_path / "heartbeat")
    monkeypatch.setattr(signal, "signal", lambda sig, fn: handlers.__setitem__(sig, fn))
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    def run(*script):
        steps = iter(script)

        def run_one(sessions):
            step = next(steps)
            if isinstance(step, Exception):
                raise step
            if step in ("TERM", "INT"):
                handlers[getattr(signal, f"SIG{step}")](getattr(signal, f"SIG{step}"), None)
                return False
            return step

        monkeypatch.setattr(jobs, "run_one", run_one)
        worker.main()
        return {"sleeps": sleeps, "steps_left": list(steps), "beat": (tmp_path / "heartbeat").exists()}

    return run


def test_the_worker_runs_jobs_back_to_back_and_sleeps_only_when_the_queue_is_empty(loop, monkeypatch):
    monkeypatch.setattr(worker.config, "WORKER_POLL_SECONDS", 0.25)
    seen = loop(True, True, False, True, "TERM", True)
    assert seen["sleeps"] == [0.25, 0.25]  # once after the empty queue, once after the signal's turn
    assert seen["steps_left"] == [True]  # stopped before taking another job
    assert seen["beat"]


def test_an_error_in_the_loop_is_logged_and_the_worker_keeps_going(loop, caplog):
    with caplog.at_level(logging.ERROR, logger="worker"):
        seen = loop(RuntimeError("the database restarted"), True, "INT")
    assert [r.message for r in caplog.records] == ["worker loop error"]
    assert len(seen["sleeps"]) == 2 and seen["steps_left"] == []
