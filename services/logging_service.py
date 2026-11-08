"""Rotating local log file with automatic password/secret redaction. Logs never leave the computer."""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import threading
from pathlib import Path

from database.database import app_data_dir

_SECRET = re.compile(r"(?i)(password|passwd|pwd|secret|token)(['\"]?\s*[:=]\s*['\"]?)([^\s,'\"})]+)")


class _Redact(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET.sub(r"\1\2***", str(record.getMessage()))
        record.args = ()
        return True


def log_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("docucraft")
    logger.setLevel(level)
    for h in list(logger.handlers):
        logger.removeHandler(h); h.close()
    h = logging.handlers.RotatingFileHandler(log_dir() / "docucraft.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    h.addFilter(_Redact())
    logger.addHandler(h)
    logger.propagate = False
    _install_excepthooks(logger)
    return logger


def _install_excepthooks(logger: logging.Logger) -> None:
    def hook(t, e, tb):
        logger.critical("Unhandled exception", exc_info=(t, e, tb))
        sys.__excepthook__(t, e, tb)

    def thread_hook(args):
        logger.critical("Unhandled thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    sys.excepthook = hook
    threading.excepthook = thread_hook


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger("docucraft" + (f".{name}" if name else ""))


def clear_logs() -> None:
    for h in logging.getLogger("docucraft").handlers:
        h.flush()
    for f in log_dir().glob("docucraft.log*"):
        try:
            f.write_text("") if f.name == "docucraft.log" else f.unlink()
        except OSError:
            pass
