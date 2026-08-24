import json
from pathlib import Path

import pytest

from watchdock.config import (
    AIConfig,
    ArchiveConfig,
    WatchedFolder,
    WatchDockConfig,
)


def make_config(tmp_path: Path, **overrides) -> WatchDockConfig:
    values = {
        "watched_folders": [WatchedFolder(str(tmp_path / "inbox"))],
        "ai_config": AIConfig(provider="openai", model="test-model"),
        "archive_config": ArchiveConfig(str(tmp_path / "archive")),
        "mode": "hitl",
    }
    values.update(overrides)
    return WatchDockConfig(**values)


def test_default_is_review_first_and_needs_no_inline_key():
    config = WatchDockConfig.default()

    assert config.mode == "hitl"
    assert config.ai_config.api_key is None
    assert config.ai_config.model == "gpt-5.6-luna"


def test_watched_extensions_are_normalized_and_deduplicated():
    folder = WatchedFolder(".", file_extensions=["PDF", ".txt", "pdf", ""])

    assert folder.file_extensions == [".pdf", ".txt"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("enabled", "false", "enabled must be a boolean"),
        ("recursive", 0, "recursive must be a boolean"),
        ("file_extensions", ".pdf", "file_extensions must be a JSON array"),
        ("file_extensions", [".pdf", 7], "file_extensions entries must be strings"),
    ],
)
def test_watched_folder_json_types_are_strict(tmp_path, field, value, message):
    path = tmp_path / "config.json"
    folder = {"path": str(tmp_path / "inbox"), field: value}
    path.write_text(json.dumps({"watched_folders": [folder]}), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        WatchDockConfig.load(str(path))


@pytest.mark.parametrize(
    "field",
    ["create_date_folders", "create_category_folders", "move_files"],
)
def test_archive_boolean_json_types_are_strict(tmp_path, field):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "watched_folders": [],
                "archive_config": {
                    "base_path": str(tmp_path / "archive"),
                    field: "false",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=rf"archive_config\.{field} must be a boolean"):
        WatchDockConfig.load(str(path))


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("ai_config", "temperature", True, "temperature must be between"),
        (None, "check_interval", True, "check_interval must be greater"),
    ],
)
def test_boolean_values_are_not_accepted_as_numbers(tmp_path, section, field, value, message):
    path = tmp_path / "config.json"
    payload = {"watched_folders": []}
    if section:
        payload[section] = {field: value}
    else:
        payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        WatchDockConfig.load(str(path))


def test_round_trip_is_utf8_and_atomic(tmp_path):
    config = make_config(
        tmp_path,
        watched_folders=[
            WatchedFolder(
                str(tmp_path / "收件箱"),
                recursive=False,
                file_extensions=["txt"],
            )
        ],
    )
    config_path = tmp_path / "settings" / "config.json"

    config.save(str(config_path))
    loaded = WatchDockConfig.load(str(config_path))

    assert loaded == config
    assert "收件箱" in config_path.read_text(encoding="utf-8")
    assert not list(config_path.parent.glob("*.tmp"))


def test_partial_configuration_inherits_defaults(tmp_path):
    path = tmp_path / "partial.json"
    path.write_text(
        json.dumps(
            {
                "watched_folders": [],
                "ai_config": {"provider": "ollama", "model": "qwen3"},
                "archive_config": {"base_path": str(tmp_path / "archive")},
            }
        ),
        encoding="utf-8",
    )

    loaded = WatchDockConfig.load(str(path))

    assert loaded.ai_config.provider == "ollama"
    assert loaded.ai_config.model == "qwen3"
    assert loaded.ai_config.temperature == 0.3
    assert loaded.mode == "hitl"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("mode", "surprise", "mode must be one of"),
        ("log_level", "verbose", "log_level must be one of"),
        ("check_interval", 0, "check_interval must be greater"),
    ],
)
def test_invalid_top_level_values_are_rejected(tmp_path, field, value, message):
    config = make_config(tmp_path)
    setattr(config, field, value)

    with pytest.raises(ValueError, match=message):
        config.validate()


def test_invalid_provider_and_temperature_are_rejected(tmp_path):
    config = make_config(
        tmp_path,
        ai_config=AIConfig(provider="unknown", model="x", temperature=3),
    )

    with pytest.raises(ValueError) as error:
        config.validate()

    assert "provider" in str(error.value)
    assert "temperature" in str(error.value)


def test_archive_and_enabled_watch_folder_must_not_overlap(tmp_path):
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(tmp_path))],
        ai_config=AIConfig(),
        archive_config=ArchiveConfig(str(tmp_path / "archive")),
    )

    with pytest.raises(ValueError, match="overlaps"):
        config.validate()


def test_invalid_json_has_actionable_location(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"mode":', encoding="utf-8")

    with pytest.raises(ValueError, match="line 1, column"):
        WatchDockConfig.load(str(path))


def test_api_key_prefers_explicit_then_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")

    assert AIConfig(api_key="explicit-secret").resolved_api_key() == "explicit-secret"
    assert AIConfig(api_key="your-api-key-here").resolved_api_key() == "environment-secret"


def test_missing_file_loads_safe_default(tmp_path):
    loaded = WatchDockConfig.load(str(tmp_path / "missing.json"))

    assert loaded.mode == "hitl"
