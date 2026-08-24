import time
from pathlib import Path

from watchdock.ai_processor import AIProcessor
from watchdock.config import AIConfig, ArchiveConfig, WatchedFolder, WatchDockConfig
from watchdock.main import WatchDock
from watchdock.watcher import FileWatcher


def wait_until(predicate, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_real_observer_handles_100_file_burst_without_loss_or_duplicates(
    tmp_path, monkeypatch
):
    inbox = tmp_path / "inbox"
    archive = tmp_path / "archive"
    inbox.mkdir()
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(inbox), recursive=False)],
        ai_config=AIConfig(provider="openai", model="test-model"),
        archive_config=ArchiveConfig(str(archive)),
        mode="hitl",
        check_interval=0.02,
    )
    processor = AIProcessor(config.ai_config, client=None, examples_path=tmp_path / "x")
    service = WatchDock(config, state_dir=tmp_path, ai_processor=processor)
    monkeypatch.setattr(service, "_notify_pending_action", lambda _action: None)
    watcher = FileWatcher(
        config.watched_folders,
        service.process_file,
        check_interval=0.02,
        debounce_interval=0.02,
        retry_backoff=0.02,
        max_retry_backoff=0.1,
        excluded_roots=[archive],
    )

    assert watcher.start() is True
    try:
        for index in range(100):
            (inbox / f"document-{index:03d}.txt").write_text(
                f"document {index}", encoding="utf-8"
            )
        assert wait_until(lambda: len(service.pending_queue.get_pending()) == 100)
    finally:
        watcher.stop()

    actions = service.pending_queue.get_pending()
    assert len(actions) == 100
    assert len({action.file_path for action in actions}) == 100
    assert {Path(action.file_path).name for action in actions} == {
        f"document-{index:03d}.txt" for index in range(100)
    }
    assert len(list(inbox.glob("*.txt"))) == 100
    assert not list(archive.rglob("*.txt"))
