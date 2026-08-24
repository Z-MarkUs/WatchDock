import logging

from watchdock.logging_utils import configure_logging
from watchdock.paths import (
    app_home,
    default_config_path,
    default_database_path,
    default_log_path,
)


def test_watchdock_home_override_centralizes_state(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHDOCK_HOME", str(tmp_path / "portable"))

    assert app_home() == tmp_path / "portable"
    assert default_config_path() == tmp_path / "portable" / "config.json"
    assert default_database_path() == tmp_path / "portable" / "pending_actions.sqlite3"
    assert default_log_path() == tmp_path / "portable" / "logs" / "watchdock.log"


def test_logging_is_rotating_utf8_and_idempotent(tmp_path):
    destination = tmp_path / "logs" / "watchdock.log"

    assert configure_logging("DEBUG", destination) == destination
    assert configure_logging("INFO", destination) == destination
    logger = logging.getLogger("watchdock.runtime-test")
    logger.info("Unicode path: 收件箱")
    for handler in logging.getLogger("watchdock").handlers:
        handler.flush()

    assert "收件箱" in destination.read_text(encoding="utf-8")
    managed_handlers = [
        handler
        for handler in logging.getLogger("watchdock").handlers
        if getattr(handler, "_watchdock_handler", False)
    ]
    assert len(managed_handlers) == 2
