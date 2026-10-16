"""One JSON object per log line, with the request's trace id when there is one."""
import json
import logging
from contextvars import ContextVar

from . import config

trace_id: ContextVar[str] = ContextVar("trace_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {"time": self.formatTime(record), "level": record.levelname, "logger": record.name,
                "message": record.getMessage()}
        if tid := trace_id.get():
            line["trace_id"] = tid
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=config.LOG_LEVEL, handlers=[handler], force=True)
