import errno
import json
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

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


def test_reviewed_action_executes_the_displayed_destination(tmp_path):
    source = tmp_path / "inbox" / "draft.txt"
    source.parent.mkdir()
    source.write_text("draft", encoding="utf-8")
    instance = organizer(tmp_path)
    action = instance.get_proposed_action(
        str(source), {"category": "Documents", "suggested_name": "final.txt"}
    )

    result = instance.execute_proposed_action(action)

    assert result["error"] is None
    assert result["new_path"] == action["to"]
    assert Path(action["to"]).read_text(encoding="utf-8") == "draft"


def test_reviewed_action_fails_closed_if_destination_becomes_occupied(tmp_path):
    source = tmp_path / "inbox" / "draft.txt"
    source.parent.mkdir()
    source.write_text("draft", encoding="utf-8")
    instance = organizer(tmp_path)
    action = instance.get_proposed_action(
        str(source), {"category": "Documents", "suggested_name": "final.txt"}
    )
    occupied = Path(action["to"])
    occupied.parent.mkdir(parents=True)
    occupied.write_text("other", encoding="utf-8")

    result = instance.execute_proposed_action(action)

    assert "already exists" in result["error"]
    assert source.read_text(encoding="utf-8") == "draft"
    assert occupied.read_text(encoding="utf-8") == "other"


def test_tampered_reviewed_destination_is_rejected(tmp_path):
    source = tmp_path / "draft.txt"
    source.write_text("draft", encoding="utf-8")
    instance = organizer(tmp_path)
    action = {
        "action_type": "move",
        "from": str(source),
        "to": str(tmp_path / "outside" / "stolen.txt"),
        "tags": [],
    }

    result = instance.execute_proposed_action(action)

    assert "escapes" in result["error"]
    assert source.exists()


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


def test_symlink_source_is_rejected_without_moving_target(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("keep me", encoding="utf-8")
    link = tmp_path / "inbox.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    result = organizer(tmp_path).organize_file(
        str(link), {"category": "Documents", "suggested_name": "moved.txt"}
    )

    assert "regular file" in result["error"]
    assert link.is_symlink()
    assert target.read_text(encoding="utf-8") == "keep me"


def test_sidecar_collision_selects_a_new_auto_destination(tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("new report", encoding="utf-8")
    instance = organizer(tmp_path)
    first_destination = (
        tmp_path / "archive" / "2026-08" / "Documents" / "report.txt"
    )
    occupied_sidecar = first_destination.with_name("report.txt.watchdock.json")
    occupied_sidecar.parent.mkdir(parents=True)
    occupied_sidecar.write_text("user-owned", encoding="utf-8")

    result = instance.organize_file(
        str(source),
        {
            "category": "Documents",
            "suggested_name": "report.txt",
            "tags": ["report"],
        },
    )

    assert result["error"] is None
    assert Path(result["new_path"]).name == "report_1.txt"
    assert occupied_sidecar.read_text(encoding="utf-8") == "user-owned"
    assert Path(f"{result['new_path']}.watchdock.json").exists()


def test_reviewed_action_fails_before_move_when_sidecar_is_occupied(tmp_path):
    source = tmp_path / "inbox" / "draft.txt"
    source.parent.mkdir()
    source.write_text("draft", encoding="utf-8")
    instance = organizer(tmp_path)
    action = instance.get_proposed_action(
        str(source),
        {
            "category": "Documents",
            "suggested_name": "final.txt",
            "tags": [],
        },
    )
    sidecar = Path(f"{action['to']}.watchdock.json")
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("do not replace", encoding="utf-8")

    result = instance.execute_proposed_action(action)

    assert "metadata destination already exists" in result["error"]
    assert source.read_text(encoding="utf-8") == "draft"
    assert sidecar.read_text(encoding="utf-8") == "do not replace"
    assert not Path(action["to"]).exists()


def test_sidecar_creation_is_exclusive(tmp_path):
    source = tmp_path / "file.txt"
    source.write_text("file", encoding="utf-8")
    sidecar = Path(f"{source}.watchdock.json")
    sidecar.write_text("pre-existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        organizer(tmp_path)._apply_tags(source, ["new"])

    assert sidecar.read_text(encoding="utf-8") == "pre-existing"


def test_rollback_never_unlinks_a_replaced_destination(tmp_path):
    destination = tmp_path / "destination.txt"
    destination.write_text("created by WatchDock", encoding="utf-8")
    created_stat = destination.lstat()
    destination.unlink()
    destination.write_text("concurrent replacement", encoding="utf-8")

    FileOrganizer._unlink_if_identity_matches(destination, created_stat)

    assert destination.read_text(encoding="utf-8") == "concurrent replacement"


def test_rollback_identity_includes_size_and_mtime():
    class FakePath:
        def __init__(self):
            self.was_unlinked = False

        def lstat(self):
            return SimpleNamespace(
                st_dev=10,
                st_ino=20,
                st_size=99,
                st_mtime_ns=40,
                st_mode=stat.S_IFREG | 0o600,
            )

        def unlink(self):
            self.was_unlinked = True

    expected = SimpleNamespace(
        st_dev=10,
        st_ino=20,
        st_size=30,
        st_mtime_ns=40,
    )
    path = FakePath()

    FileOrganizer._unlink_if_identity_matches(path, expected)

    assert not path.was_unlinked


def test_rollback_removes_unchanged_regular_destination(tmp_path):
    destination = tmp_path / "unchanged.txt"
    destination.write_text("WatchDock output", encoding="utf-8")
    created_stat = destination.lstat()

    FileOrganizer._unlink_if_identity_matches(destination, created_stat)

    assert not destination.exists()


def test_long_generated_name_is_truncated_without_losing_original_suffix(tmp_path):
    instance = organizer(tmp_path)

    safe_name = instance._safe_filename("x" * 400, "report.final.pdf")

    assert len(safe_name) <= 240
    assert safe_name.endswith(".final.pdf")


def test_cross_device_move_uses_exclusive_verified_copy(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("cross-device content", encoding="utf-8")
    destination = tmp_path / "archive" / "destination.txt"
    destination.parent.mkdir()
    instance = organizer(tmp_path)

    def cross_device_link(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr("watchdock.file_organizer.os.link", cross_device_link)
    result = instance.execute_proposed_action(
        {
            "action_type": "move",
            "from": str(source),
            "to": str(destination),
            "tags": [],
        }
    )

    assert result["error"] is None
    assert result["moved"] is True
    assert not source.exists()
    assert destination.read_text(encoding="utf-8") == "cross-device content"


def test_concurrent_reviewed_moves_never_overwrite_same_destination(
    tmp_path, monkeypatch
):
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("first", encoding="utf-8")
    second_source.write_text("second", encoding="utf-8")
    destination = tmp_path / "archive" / "same.txt"
    destination.parent.mkdir(parents=True)
    first = organizer(tmp_path)
    second = organizer(tmp_path)
    barrier = threading.Barrier(2)

    first_move = first._move_without_overwrite
    second_move = second._move_without_overwrite

    def synchronized(move):
        def run(*args, **kwargs):
            barrier.wait(timeout=2)
            return move(*args, **kwargs)

        return run

    monkeypatch.setattr(first, "_move_without_overwrite", synchronized(first_move))
    monkeypatch.setattr(second, "_move_without_overwrite", synchronized(second_move))
    actions = [
        {
            "action_type": "move",
            "from": str(first_source),
            "to": str(destination),
            "tags": [],
        },
        {
            "action_type": "move",
            "from": str(second_source),
            "to": str(destination),
            "tags": [],
        },
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda pair: pair[0].execute_proposed_action(pair[1]),
                [(first, actions[0]), (second, actions[1])],
            )
        )

    assert sum(result["error"] is None for result in results) == 1
    assert sum(result["error"] is not None for result in results) == 1
    remaining_contents = [
        path.read_text(encoding="utf-8")
        for path in (first_source, second_source)
        if path.exists()
    ]
    assert {destination.read_text(encoding="utf-8"), *remaining_contents} == {
        "first",
        "second",
    }
