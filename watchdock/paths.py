"""Centralized paths for WatchDock configuration and state."""

from __future__ import annotations

import os
from pathlib import Path


def app_home() -> Path:
    """Return the WatchDock state directory, honoring test/portable overrides."""

    override = os.environ.get("WATCHDOCK_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".watchdock"


def default_config_path() -> Path:
    return app_home() / "config.json"


def default_database_path() -> Path:
    return app_home() / "pending_actions.sqlite3"


def default_examples_path() -> Path:
    return app_home() / "few_shot_examples.json"


def default_log_path() -> Path:
    return app_home() / "logs" / "watchdock.log"
