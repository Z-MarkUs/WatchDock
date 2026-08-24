from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from watchdock import gui as gui_module
from watchdock.config import AIConfig, ArchiveConfig, WatchedFolder, WatchDockConfig
from watchdock.file_organizer import FileOrganizer
from watchdock.gui import (
    PROVIDER_DEFAULT_MODELS,
    WatchDockGUI,
    build_config_from_gui,
    execute_review_action,
    gui_paths,
    parse_file_extensions,
    run_gui,
)
from watchdock.pending_actions import PendingActionsQueue


def _valid_config(tmp_path: Path) -> WatchDockConfig:
    watched = tmp_path / "incoming"
    watched.mkdir()
    return WatchDockConfig(
        watched_folders=[
            WatchedFolder(
                str(watched),
                enabled=True,
                recursive=False,
                file_extensions=[".pdf", ".txt"],
            )
        ],
        ai_config=AIConfig(
            provider="openai",
            api_key="saved-secret",
            model=PROVIDER_DEFAULT_MODELS["openai"],
            temperature=0.4,
        ),
        archive_config=ArchiveConfig(
            str(tmp_path / "archive"),
            create_date_folders=False,
            create_category_folders=True,
            move_files=True,
        ),
        log_level="DEBUG",
        check_interval=2.5,
        mode="hitl",
    )


def test_gui_paths_colocate_state_with_custom_config(tmp_path):
    paths = gui_paths(str(tmp_path / "portable" / "settings.json"))

    assert paths.config_path == (tmp_path / "portable" / "settings.json").resolve()
    assert paths.state_dir == paths.config_path.parent
    assert paths.examples_path == paths.state_dir / "few_shot_examples.json"
    assert paths.database_path == paths.state_dir / "pending_actions.sqlite3"
    assert paths.log_path == paths.state_dir / "logs" / "watchdock.log"


def test_gui_default_path_honors_watchdock_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHDOCK_HOME", str(tmp_path / "portable"))

    assert gui_paths().config_path == (tmp_path / "portable" / "config.json").resolve()


def test_build_config_preserves_every_runtime_field(tmp_path):
    incoming = tmp_path / "incoming"
    archive = tmp_path / "archive"
    config = build_config_from_gui(
        [
            {
                "path": str(incoming),
                "enabled": True,
                "recursive": False,
                "file_extensions": "PDF; .txt, pdf",
            }
        ],
        provider="anthropic",
        api_key="anthropic-secret",
        model="claude-test",
        base_url="http://ignored.example",
        temperature=0.7,
        archive_base_path=str(archive),
        create_date_folders=False,
        create_category_folders=False,
        move_files=False,
        log_level="warning",
        check_interval="3.25",
        mode="auto",
    )

    assert config.watched_folders[0].file_extensions == [".pdf", ".txt"]
    assert config.watched_folders[0].recursive is False
    assert config.ai_config.provider == "anthropic"
    assert config.ai_config.api_key == "anthropic-secret"
    assert config.ai_config.model == "claude-test"
    assert config.ai_config.base_url is None
    assert config.ai_config.temperature == 0.7
    assert config.archive_config.create_date_folders is False
    assert config.archive_config.create_category_folders is False
    assert config.archive_config.move_files is False
    assert config.log_level == "WARNING"
    assert config.check_interval == 3.25
    assert config.mode == "auto"


@pytest.mark.parametrize("provider", ["openai", "anthropic", "ollama"])
def test_blank_model_uses_current_provider_default(tmp_path, provider):
    config = build_config_from_gui(
        [{"path": str(tmp_path / "incoming")}],
        provider=provider,
        api_key=None,
        model="",
        base_url="http://localhost:11434/v1",
        temperature=0.3,
        archive_base_path=str(tmp_path / "archive"),
        create_date_folders=True,
        create_category_folders=True,
        move_files=True,
        log_level="INFO",
        check_interval=1,
        mode="hitl",
    )

    assert config.ai_config.model == PROVIDER_DEFAULT_MODELS[provider]


def test_blank_extensions_mean_all_files():
    assert parse_file_extensions("  ; , ") is None


@pytest.mark.parametrize(
    ("archive_suffix", "interval", "message"),
    [
        ("incoming/archive", 1, "overlaps"),
        ("archive", 0, "greater than 0"),
    ],
)
def test_build_config_rejects_unsafe_values(
    tmp_path, archive_suffix, interval, message
):
    with pytest.raises(ValueError, match=message):
        build_config_from_gui(
            [{"path": str(tmp_path / "incoming"), "enabled": True}],
            provider="openai",
            api_key=None,
            model="",
            base_url=None,
            temperature=0.3,
            archive_base_path=str(tmp_path / archive_suffix),
            create_date_folders=True,
            create_category_folders=True,
            move_files=True,
            log_level="INFO",
            check_interval=interval,
            mode="hitl",
        )


def test_review_approval_executes_exact_proposal_then_completes(tmp_path):
    source = tmp_path / "incoming.txt"
    source.write_text("reviewed", encoding="utf-8")
    organizer = FileOrganizer(
        ArchiveConfig(
            str(tmp_path / "archive"),
            create_date_folders=False,
            create_category_folders=False,
            move_files=True,
        )
    )
    analysis = {
        "category": "Documents",
        "suggested_name": "approved.txt",
        "tags": [],
    }
    proposal = organizer.get_proposed_action(str(source), analysis)
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(str(source), analysis, proposal, include_source_hash=True)

    result = execute_review_action(queue, organizer, action.action_id)

    assert result.success is True
    assert result.status == "completed"
    assert result.new_path == action.proposed_action["to"]
    assert Path(result.new_path).read_text(encoding="utf-8") == "reviewed"
    assert not source.exists()
    assert queue.get_by_id(action.action_id).status == "completed"


def test_review_approval_retains_source_change_as_failed_and_can_retry(tmp_path):
    source = tmp_path / "incoming.txt"
    source.write_text("reviewed", encoding="utf-8")
    organizer = FileOrganizer(
        ArchiveConfig(
            str(tmp_path / "archive"),
            create_date_folders=False,
            create_category_folders=False,
            move_files=True,
        )
    )
    analysis = {"category": "Documents", "suggested_name": "approved.txt"}
    proposal = organizer.get_proposed_action(str(source), analysis)
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(str(source), analysis, proposal, include_source_hash=True)
    source.write_text("changed after review", encoding="utf-8")

    first = execute_review_action(queue, organizer, action.action_id)
    second = execute_review_action(queue, organizer, action.action_id)

    assert first.success is False
    assert first.status == "failed"
    assert "changed or disappeared" in first.error
    assert second.success is False
    assert second.status == "failed"
    retained = queue.get_by_id(action.action_id)
    assert retained.status == "failed"
    assert retained.attempt_count == 2
    assert source.exists()


def test_review_approval_retains_organizer_error(tmp_path):
    source = tmp_path / "incoming.txt"
    source.write_text("reviewed", encoding="utf-8")
    queue = PendingActionsQueue(db_path=tmp_path / "pending_actions.sqlite3")
    action = queue.add(
        str(source),
        {"category": "Documents"},
        {
            "action_type": "rename",
            "from": str(source),
            "to": str(tmp_path / "renamed.txt"),
        },
    )

    class ErrorOrganizer:
        @staticmethod
        def execute_proposed_action(proposed_action):
            assert proposed_action == action.proposed_action
            return {"error": "destination is locked", "new_path": None}

    result = execute_review_action(queue, ErrorOrganizer(), action.action_id)

    assert result.success is False
    assert result.status == "failed"
    assert result.error == "destination is locked"
    assert queue.get_by_id(action.action_id).error == "destination is locked"


def test_run_gui_forwards_custom_config_path(monkeypatch, tmp_path):
    captured = {}

    class FakeRoot:
        def mainloop(self):
            captured["mainloop"] = True

    class FakeApp:
        def __init__(self, root, config_path=None):
            captured["root"] = root
            captured["config_path"] = config_path

    root = FakeRoot()
    monkeypatch.setattr(gui_module.tk, "Tk", lambda: root)
    monkeypatch.setattr(gui_module, "WatchDockGUI", FakeApp)
    config_path = tmp_path / "custom" / "config.json"

    app = run_gui(config_path=str(config_path))

    assert isinstance(app, FakeApp)
    assert captured == {
        "root": root,
        "config_path": str(config_path),
        "mainloop": True,
    }


def test_gui_main_forwards_config_option(monkeypatch, tmp_path):
    from watchdock import gui_main

    captured = {}
    monkeypatch.setattr(
        gui_main,
        "run_gui",
        lambda config_path=None: captured.setdefault("config_path", config_path),
    )
    config_path = tmp_path / "portable" / "config.json"

    assert gui_main.main(["--config", str(config_path)]) == 0
    assert captured["config_path"] == str(config_path)


def test_monitor_worker_starts_and_stops_without_touching_tk(tmp_path, monkeypatch):
    from watchdock import main as main_module

    started = threading.Event()
    instances = []

    class FakeService:
        def __init__(self, config, state_dir):
            self.config = config
            self.state_dir = state_dir
            self.running = False
            self.watcher = object()
            instances.append(self)

        def start(self):
            self.running = True
            started.set()
            while self.running:
                time.sleep(0.005)

        def stop(self):
            self.running = False
            self.watcher = None

    monkeypatch.setattr(main_module, "WatchDock", FakeService)
    app = object.__new__(WatchDockGUI)
    app.state_dir = tmp_path / "portable"
    app._service = None
    app._service_lock = threading.Lock()
    app._service_events = queue.Queue()
    app._monitor_stop_requested = threading.Event()
    config = _valid_config(tmp_path)
    monitor_thread = threading.Thread(target=app._monitor_worker, args=(config,))

    monitor_thread.start()
    assert started.wait(1)
    app._stop_service_until_finished(monitor_thread)

    assert not monitor_thread.is_alive()
    assert instances[0].state_dir == app.state_dir
    assert instances[0].config is config
    assert app._service is None
    assert app._service_events.get_nowait() == ("stopped", "Stopped")


def test_save_and_reload_refuse_while_monitor_thread_is_alive(monkeypatch):
    warnings = []

    class AliveThread:
        @staticmethod
        def is_alive():
            return True

    app = object.__new__(WatchDockGUI)
    app._service_thread = AliveThread()
    monkeypatch.setattr(
        gui_module.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )

    assert app._save_config() is False
    assert app._reload_config() is False
    assert len(warnings) == 2
    assert all(title == "Stop Monitor first" for title, _message in warnings)
    assert "Stop Monitor before saving configuration" in warnings[0][1]
    assert "Stop Monitor before reloading configuration" in warnings[1][1]


@pytest.mark.parametrize("failed_stage", ["examples", "logging"])
def test_partial_save_keeps_current_config_and_reports_truthfully(
    tmp_path, monkeypatch, failed_stage
):
    config = _valid_config(tmp_path)
    config_path = tmp_path / "portable" / "config.json"
    warnings = []
    app = object.__new__(WatchDockGUI)
    app._service_thread = None
    app.config_path = config_path
    app.log_path = config_path.parent / "logs" / "watchdock.log"
    app.config = WatchDockConfig.default()
    app._config_load_error = "old error"
    app._config_from_controls = lambda: config
    app._refresh_pending_actions = lambda: None
    app._update_overview = lambda: None
    app._update_status = lambda: None
    app._save_examples = lambda: None
    if failed_stage == "examples":
        app._save_examples = lambda: (_ for _ in ()).throw(OSError("examples locked"))
        monkeypatch.setattr(
            gui_module, "configure_logging", lambda level, path: path
        )
    else:
        monkeypatch.setattr(
            gui_module,
            "configure_logging",
            lambda level, path: (_ for _ in ()).throw(OSError("log locked")),
        )
    monkeypatch.setattr(
        gui_module.messagebox,
        "showwarning",
        lambda title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        gui_module.messagebox,
        "showerror",
        lambda *args, **kwargs: pytest.fail("a successful config save is not an error"),
    )

    assert app._save_config() is False

    assert app.config is config
    assert app._config_load_error is None
    assert WatchDockConfig.load(str(config_path)).to_dict() == config.to_dict()
    assert warnings[0][0] == "Configuration saved with follow-up errors"
    assert f"Configuration was saved to {config_path}" in warnings[0][1]
    assert "Configuration was not saved" not in warnings[0][1]


def test_malformed_examples_are_reported_and_never_overwritten(tmp_path):
    examples_path = tmp_path / "few_shot_examples.json"
    malformed = b'{"not": "finished"'
    examples_path.write_bytes(malformed)
    app = object.__new__(WatchDockGUI)
    app.examples_path = examples_path
    app.few_shot_examples = [{"file_name": "replacement.txt"}]

    assert app._load_few_shot_examples() == []
    assert app._examples_load_error
    with pytest.raises(RuntimeError, match="left untouched"):
        app._save_examples()
    assert examples_path.read_bytes() == malformed


def test_gui_round_trip_when_tk_display_is_available(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display is unavailable: {exc}")

    config_path = tmp_path / "portable" / "config.json"
    config = _valid_config(tmp_path)
    config.save(str(config_path))
    monkeypatch.setattr(gui_module.messagebox, "showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr(gui_module.messagebox, "showerror", lambda *args, **kwargs: None)
    monkeypatch.setattr(gui_module.messagebox, "showwarning", lambda *args, **kwargs: None)
    root.withdraw()
    try:
        app = WatchDockGUI(root, config_path=str(config_path))
        assert app.config_path == config_path.resolve()
        assert app.database_path == config_path.parent / "pending_actions.sqlite3"
        assert app._save_config(show_success=False) is True

        saved = WatchDockConfig.load(str(config_path))
        assert saved.watched_folders[0].file_extensions == [".pdf", ".txt"]
        assert saved.ai_config.api_key == "saved-secret"
        assert saved.log_level == "DEBUG"
        assert saved.check_interval == 2.5

        ai_cards = app.views["ai"].pack_slaves()
        assert ai_cards.index(app.api_key_card) < ai_cards.index(app.model_card)
        app.ai_provider_var.set("ollama")
        app._on_provider_change()
        ai_cards = app.views["ai"].pack_slaves()
        assert ai_cards.index(app.base_url_card) < ai_cards.index(app.model_card)
        app.ai_provider_var.set("openai")
        app._on_provider_change()
        ai_cards = app.views["ai"].pack_slaves()
        assert ai_cards.index(app.api_key_card) < ai_cards.index(app.model_card)

        app._set_monitor_status("Running")
        assert app.save_button.cget("state") == tk.DISABLED
        assert app.reload_button.cget("state") == tk.DISABLED
        app._set_monitor_status("Stopped")
        assert app.save_button.cget("state") == tk.NORMAL
        assert app.reload_button.cget("state") == tk.NORMAL
    finally:
        root.destroy()
