import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from watchdock.ai_processor import AIProcessor
from watchdock.config import AIConfig, ArchiveConfig, WatchedFolder, WatchDockConfig
from watchdock.main import WatchDock, main
from watchdock.main import _execute_claimed_action, _same_fingerprint
from watchdock.pending_actions import PendingActionsQueue


def write_config(tmp_path: Path, *, mode: str = "hitl") -> Path:
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(inbox), recursive=False)],
        ai_config=AIConfig(
            provider="openai", api_key=None, model="test-model", temperature=0.3
        ),
        archive_config=ArchiveConfig(str(tmp_path / "archive")),
        mode=mode,
    )
    path = tmp_path / "config.json"
    config.save(str(path))
    return path


def test_no_command_and_bare_config_show_help(capsys):
    assert main([]) == 0
    assert "commands:" in capsys.readouterr().out

    assert main(["config"]) == 0
    assert "create safe defaults" in capsys.readouterr().out


def test_version_is_offline_by_default(monkeypatch, capsys):
    monkeypatch.setattr(
        "watchdock.main._check_pypi_version",
        lambda: pytest.fail("version should not access the network"),
    )

    assert main(["version"]) == 0
    assert capsys.readouterr().out.startswith("WatchDock ")


def test_analysis_fingerprint_detects_identity_replacement():
    original = {"device": 1, "inode": 10, "size": 20, "mtime_ns": 30}
    replacement = {"device": 1, "inode": 11, "size": 20, "mtime_ns": 30}

    assert _same_fingerprint(original, dict(original)) is True
    assert _same_fingerprint(original, replacement) is False


def test_update_installs_the_exact_checked_version(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        "watchdock.main._check_pypi_version", lambda: ("9.9.9", None)
    )
    monkeypatch.setattr(
        "watchdock.main.subprocess.run",
        lambda command, **kwargs: captured.update(
            command=command, kwargs=kwargs
        )
        or type("Result", (), {"returncode": 0})(),
    )

    assert main(["update"]) == 0
    assert captured["command"][-1] == "watchdock==9.9.9"
    assert captured["kwargs"] == {"check": False}
    assert "Update installed" in capsys.readouterr().out


def test_config_option_works_after_subcommand_and_init_refuses_overwrite(
    tmp_path, capsys
):
    path = tmp_path / "state" / "config.json"

    assert main(["config", "init", "--config", str(path)]) == 0
    original = path.read_bytes()
    assert main(["config", "init", "--config", str(path)]) == 1
    assert path.read_bytes() == original
    assert "already exists" in capsys.readouterr().out
    assert main(["config", "init", "--force", "--config", str(path)]) == 0


def test_status_reports_real_folder_and_archive_fields(tmp_path, capsys):
    config_path = write_config(tmp_path)

    assert main(["status", "--json", "--config", str(config_path)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "hitl"
    assert payload["watched_folders"][0]["exists"] is True
    assert payload["archive_path"] == str(tmp_path / "archive")
    assert payload["queue"]["pending"] == 0


def test_doctor_passes_for_sandboxed_ollama_configuration(tmp_path, capsys):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(inbox))],
        ai_config=AIConfig(provider="ollama", model="qwen3"),
        archive_config=ArchiveConfig(str(tmp_path / "archive")),
        mode="hitl",
    )
    path = tmp_path / "config.json"
    config.save(str(path))

    assert main(["doctor", "--config", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Doctor result: 0 error(s)" in output
    assert not (tmp_path / "archive" / ".watchdock-write-test").exists()


def test_review_queue_survives_restart_and_approval_executes_exact_action(
    tmp_path, capsys
):
    config_path = write_config(tmp_path)
    source = tmp_path / "inbox" / "Meeting Notes.txt"
    source.write_text("agenda", encoding="utf-8")

    assert (
        main(
            [
                "process",
                str(source),
                "--queue",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    pending = queue.get_pending()
    assert len(pending) == 1
    reviewed_destination = Path(pending[0].proposed_action["to"])

    assert main(["approve", pending[0].action_id, "--config", str(config_path)]) == 0

    completed = queue.get_by_id(pending[0].action_id)
    assert completed.status == "completed"
    assert reviewed_destination.read_text(encoding="utf-8") == "agenda"
    assert not source.exists()
    assert "Completed action" in capsys.readouterr().out


def test_approval_fails_if_source_changed_after_review(tmp_path, capsys):
    config_path = write_config(tmp_path)
    source = tmp_path / "inbox" / "draft.txt"
    source.write_text("v1", encoding="utf-8")
    config = WatchDockConfig.load(str(config_path))
    processor = AIProcessor(config.ai_config, client=None, examples_path=tmp_path / "x")
    analysis = processor.analyze_file(str(source))
    service = WatchDock(config, state_dir=tmp_path, ai_processor=processor)
    proposal = service.file_organizer.get_proposed_action(str(source), analysis)
    action = service.pending_queue.add(str(source), analysis, proposal)
    source.write_text("version two is different", encoding="utf-8")

    assert main(["approve", action.action_id, "--config", str(config_path)]) == 1
    assert service.pending_queue.get_by_id(action.action_id).status == "failed"
    assert source.exists()
    assert "source changed" in capsys.readouterr().out


def test_approval_fails_if_source_is_no_longer_in_an_enabled_watched_root(
    tmp_path, capsys
):
    config_path = write_config(tmp_path)
    config = WatchDockConfig.load(str(config_path))
    source = tmp_path / "inbox" / "removed-root.txt"
    source.write_text("reviewed", encoding="utf-8")
    destination = tmp_path / "archive" / "removed-root.txt"
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {
            "action_type": "move",
            "from": str(source),
            "to": str(destination),
        },
        include_source_hash=True,
    )

    replacement_root = tmp_path / "different-inbox"
    replacement_root.mkdir()
    config.watched_folders = [WatchedFolder(str(replacement_root), enabled=True)]
    config.save(str(config_path))

    assert main(["approve", action.action_id, "--config", str(config_path)]) == 1
    retained = queue.get_by_id(action.action_id)
    assert retained.status == "failed"
    assert "currently enabled watched folder" in retained.error
    assert source.read_text(encoding="utf-8") == "reviewed"
    assert not destination.exists()
    assert "currently enabled watched folder" in capsys.readouterr().out


def test_unexpected_approval_exception_is_durably_failed(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    config = WatchDockConfig.load(str(config_path))
    source = tmp_path / "inbox" / "draft.txt"
    source.write_text("v1", encoding="utf-8")
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {
            "action_type": "move",
            "from": str(source),
            "to": str(tmp_path / "archive" / "draft.txt"),
        },
    )
    claimed = queue.claim(action.action_id, worker_id="test")

    class BrokenOrganizer:
        def __init__(self, _config):
            raise RuntimeError("boom")

    monkeypatch.setattr("watchdock.main.FileOrganizer", BrokenOrganizer)
    success, result = _execute_claimed_action(config, queue, claimed)

    assert success is False
    assert result["error"] == "boom"
    assert queue.get_by_id(action.action_id).status == "failed"


def test_auto_mode_never_moves_review_required_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config_path = write_config(tmp_path, mode="auto")
    config = WatchDockConfig.load(str(config_path))
    source = tmp_path / "inbox" / "photo.jpg"
    source.write_bytes(b"image")
    service = WatchDock(config, state_dir=tmp_path)

    service.process_file(str(source))

    assert source.exists()
    assert len(service.pending_queue.get_pending()) == 1


def test_notification_uses_argv_not_a_shell(tmp_path, monkeypatch):
    source = tmp_path / "$(touch owned).txt"
    source.write_text("x", encoding="utf-8")
    queue = PendingActionsQueue(db_path=tmp_path / "queue.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {"action_type": "move", "from": str(source), "to": str(tmp_path / "x")},
    )
    calls = []
    monkeypatch.setattr("watchdock.main.platform.system", lambda: "Linux")
    monkeypatch.setattr("watchdock.main.shutil.which", lambda _name: "notify-send")
    monkeypatch.setattr(
        "watchdock.main.subprocess.run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    WatchDock._notify_pending_action(action)

    assert isinstance(calls[0][0], list)
    assert calls[0][1]["check"] is False
    assert "$(touch owned).txt" in calls[0][0][-1]
    assert not (tmp_path / "owned").exists()


def test_cli_output_survives_legacy_windows_encoding(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [sys.executable, "-m", "watchdock", "--version"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="cp1252",
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("WatchDock ")
    assert "UnicodeEncodeError" not in result.stderr
    assert not (tmp_path / "watchdock.log").exists()


def test_missing_config_is_a_clean_error(tmp_path, capsys):
    missing = tmp_path / "missing.json"

    assert main(["status", "--config", str(missing)]) == 1
    assert "configuration not found" in capsys.readouterr().out


def test_doctor_missing_cloud_sdk_is_warning_in_hitl_mode(
    tmp_path, monkeypatch, capsys
):
    config_path = write_config(tmp_path, mode="hitl")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WATCHDOCK_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("watchdock.main.importlib.util.find_spec", lambda _name: None)

    assert main(["doctor", "--config", str(config_path)]) == 0
    output = capsys.readouterr().out
    assert "[WARN] provider package" in output
    assert "Doctor result: 0 error(s)" in output


def test_recover_stale_cli_marks_claim_failed_for_reconciliation(tmp_path, capsys):
    config_path = write_config(tmp_path)
    source = tmp_path / "inbox" / "claimed.txt"
    source.write_text("claimed", encoding="utf-8")
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {
            "action_type": "move",
            "from": str(source),
            "to": str(tmp_path / "archive" / "claimed.txt"),
        },
    )
    queue.claim(action.action_id, worker_id="crashed-cli")

    assert (
        main(
            [
                "recover-stale",
                "--older-than",
                "0",
                "--config",
                str(config_path),
            ]
        )
        == 0
    )
    recovered = queue.get_by_id(action.action_id)
    assert recovered.status == "failed"
    assert "outcome requires review" in recovered.error
    assert action.action_id in capsys.readouterr().out


def test_service_start_recovers_stale_claims(tmp_path, monkeypatch):
    config_path = write_config(tmp_path)
    config = WatchDockConfig.load(str(config_path))
    source = tmp_path / "inbox" / "startup-claim.txt"
    source.write_text("claimed", encoding="utf-8")
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {
            "action_type": "move",
            "from": str(source),
            "to": str(tmp_path / "archive" / "startup-claim.txt"),
        },
    )
    queue.claim(action.action_id, worker_id="crashed-service")

    class OneCycleWatcher:
        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            return True

        def is_alive(self):
            return False

        def stop(self):
            pass

    monkeypatch.setattr("watchdock.main.FileWatcher", OneCycleWatcher)
    service = WatchDock(
        config,
        state_dir=tmp_path,
        pending_queue=queue,
        stale_processing_seconds=0,
    )

    service.start()

    assert queue.get_by_id(action.action_id).status == "failed"


def test_watched_symlink_escape_is_rejected_before_analysis(tmp_path):
    config_path = write_config(tmp_path)
    config = WatchDockConfig.load(str(config_path))
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    link = tmp_path / "inbox" / "inside.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    class NeverAnalyze:
        def analyze_file(self, _path):
            pytest.fail("external target reached analysis")

    service = WatchDock(config, state_dir=tmp_path, ai_processor=NeverAnalyze())

    with pytest.raises(ValueError, match="outside configured watched folders"):
        service.process_file(str(link))
    assert target.read_text(encoding="utf-8") == "outside"
