import json
from datetime import datetime
from pathlib import Path

import pytest

from watchdock.config import ArchiveConfig, WatchDockConfig
from watchdock.file_organizer import FileOrganizer

FIXED_NOW = datetime(2026, 8, 24, 12, 30, 45)


def organizer(tmp_path, **config_values):
    config = ArchiveConfig(base_path=str(tmp_path / "archive"), **config_values)
    return FileOrganizer(config, now=lambda: FIXED_NOW)


def test_move_uses_date_category_safe_name_and_metadata(tmp_path):
    source = tmp_path / "inbox" / "Draft report.txt"
    source.parent.mkdir()
    source.write_text("hello", encoding="utf-8")

    result = organizer(tmp_path).organize_file(
        str(source),
        {
            "category": "Documents",
            "suggested_name": "quarterly_report.txt",
            "tags": ["finance", "reviewed"],
        },
    )

    destination = (
        tmp_path / "archive" / "2026-08" / "Documents" / "quarterly_report.txt"
    )
    assert result["error"] is None
    assert result["moved"] is True
    assert result["new_path"] == str(destination)
    assert destination.read_text(encoding="utf-8") == "hello"
    metadata = json.loads(
        destination.with_name("quarterly_report.txt.watchdock.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["tags"] == ["finance", "reviewed"]


def test_untrusted_analysis_cannot_escape_archive_or_change_extension(tmp_path):
    source = tmp_path / "invoice.txt"
    source.write_text("pay me", encoding="utf-8")
    instance = organizer(tmp_path)

    proposed = instance.get_proposed_action(
        str(source),
        {
            "category": "../../outside",
            "suggested_name": "..\\..\\payload.exe",
        },
    )
    destination = instance.archive_base / "2026-08" / "outside" / "payload.txt"

    assert proposed["to"] == str(destination)
    assert destination.resolve().is_relative_to(instance.archive_base.resolve())
    result = instance.organize_file(
        str(source), proposed | {"suggested_name": "payload.txt"}
    )
    assert result["error"] is None
    assert Path(result["new_path"]).is_relative_to(instance.archive_base)


def test_conflict_never_overwrites_existing_file(tmp_path):
    instance = organizer(tmp_path)
    archive_file = tmp_path / "archive" / "2026-08" / "Documents" / "report.txt"
    archive_file.parent.mkdir(parents=True)
    archive_file.write_text("original", encoding="utf-8")
    source = tmp_path / "report.txt"
    source.write_text("new", encoding="utf-8")

    result = instance.organize_file(
        str(source), {"category": "Documents", "suggested_name": "report.txt"}
    )

    assert archive_file.read_text(encoding="utf-8") == "original"
    assert (archive_file.parent / "report_1.txt").read_text(encoding="utf-8") == "new"
    assert result["new_path"].endswith("report_1.txt")


def test_rename_in_place_handles_windows_reserved_name(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("notes", encoding="utf-8")
    instance = organizer(tmp_path, move_files=False)

    result = instance.organize_file(
        str(source), {"suggested_name": "CON", "tags": ["one", "one"]}
    )

    renamed = tmp_path / "_CON.txt"
    assert result["renamed"] is True
    assert renamed.exists()
    assert (tmp_path / "_CON.txt.watchdock.json").exists()


def test_missing_source_returns_truthful_error(tmp_path):
    result = organizer(tmp_path).organize_file(
        str(tmp_path / "missing.pdf"), {"category": "Documents"}
    )

    assert result["moved"] is False
    assert result["new_path"] is None
    assert "does not exist" in result["error"]


def test_metadata_failure_is_a_warning_not_false_success(tmp_path, monkeypatch):
    source = tmp_path / "notes.txt"
    source.write_text("notes", encoding="utf-8")
    instance = organizer(tmp_path)

    def fail_metadata(*_args):
        raise OSError("read only")

    monkeypatch.setattr(instance, "_apply_tags", fail_metadata)
    result = instance.organize_file(
        str(source),
        {"category": "Documents", "suggested_name": "notes.txt", "tags": ["x"]},
    )

    assert result["moved"] is True
    assert result["tags_applied"] is False
    assert "read only" in result["warnings"][0]


def test_requires_archive_config(tmp_path):
    with pytest.raises(TypeError, match="ArchiveConfig"):
        FileOrganizer(WatchDockConfig.default())
