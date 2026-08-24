"""Console and rotating-file logging setup without import-time side effects."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from watchdock.paths import default_log_path

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def prepare_console() -> None:
    """Prevent legacy Windows encodings from crashing on Unicode paths."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def configure_logging(level: str, log_path: Optional[Path] = None) -> Path:
    """Configure WatchDock loggers and return the log file path."""

    destination = (log_path or default_log_path()).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    package_logger = logging.getLogger("watchdock")
    package_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    package_logger.propagate = False

    for handler in list(package_logger.handlers):
        if getattr(handler, "_watchdock_handler", False):
            package_logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = RotatingFileHandler(
        destination,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._watchdock_handler = True

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler._watchdock_handler = True

    package_logger.addHandler(file_handler)
    package_logger.addHandler(console_handler)
    return destination
