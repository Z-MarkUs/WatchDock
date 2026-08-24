import threading
import time
from pathlib import Path

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent

from watchdock.config import WatchedFolder
from watchdock.watcher import FileWatcher, WatchDockHandler


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FakeObserver:
    def __init__(self):
        self.scheduled = []
        self.start_calls = 0
        self.stop_calls = 0
        self.join_calls = 0
        self._alive = False

    def schedule(self, handler, path, recursive):
        self.scheduled.append((handler, path, recursive))
        return object()

    def start(self):
        self.start_calls += 1
        self._alive = True

    def stop(self):
        self.stop_calls += 1
        self._alive = False

    def join(self):
        self.join_calls += 1

    def is_alive(self):
        return self._alive


def make_fake_watcher(tmp_path: Path, callback, **overrides):
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    observer = FakeObserver()
    options = {
        "check_interval": 0.01,
        "debounce_interval": 0.005,
        "retry_backoff": 0.005,
        "max_retry_backoff": 0.02,
        "observer_factory": lambda: observer,
    }
    options.update(overrides)
    watcher = FileWatcher(
        [WatchedFolder(str(inbox), recursive=True)],
        callback,
        **options,
    )
    return watcher, observer, inbox


def test_handler_filters_extensions_temporaries_sidecars_and_excluded_roots(tmp_path):
    excluded = tmp_path / "archive"
    seen = []
    handler = WatchDockHandler(
        seen.append,
        file_extensions=["TXT", ".tar.gz"],
        excluded_roots=[excluded],
    )

    accepted = tmp_path / "Report.TXT"
    accepted_archive = tmp_path / "bundle.TAR.GZ"
    for path in (accepted, accepted_archive):
        handler.on_created(FileCreatedEvent(str(path)))

    rejected = [
        tmp_path / "report.pdf",
        tmp_path / "download.crdownload",
        tmp_path / "download.txt.part",
        tmp_path / "draft.tmp",
        tmp_path / "report.watchdock_meta.json",
        tmp_path / "report.watchdock.json",
        tmp_path / "~$report.txt",
        excluded / "inside.txt",
    ]
    for path in rejected:
        handler.on_modified(FileModifiedEvent(str(path)))

    assert seen == [str(accepted.resolve()), str(accepted_archive.resolve())]


def test_event_burst_is_debounced_and_changed_signature_reuses_path(tmp_path):
    calls = []
    watcher, observer, inbox = make_fake_watcher(tmp_path, calls.append)
    target = inbox / "note.txt"
    target.write_text("one", encoding="utf-8")

    assert watcher.start()
    try:
        handler = observer.scheduled[0][0]
        handler.on_created(FileCreatedEvent(str(target)))
        handler.on_modified(FileModifiedEvent(str(target)))
        handler.on_moved(FileMovedEvent(str(inbox / "note.part"), str(target)))

        assert wait_until(lambda: len(calls) == 1)
        assert calls == [str(target.resolve())]

        for _ in range(5):
            handler.on_modified(FileModifiedEvent(str(target)))
        time.sleep(0.08)
        assert len(calls) == 1

        target.write_text("a different size", encoding="utf-8")
        handler.on_modified(FileModifiedEvent(str(target)))
        assert wait_until(lambda: len(calls) == 2)
    finally:
        watcher.stop()


def test_callback_runs_off_event_thread_and_new_events_can_queue(tmp_path):
    callback_started = threading.Event()
    release_callback = threading.Event()
    calls = []

    def callback(path):
        calls.append(path)
        callback_started.set()
        assert release_callback.wait(2)

    watcher, observer, inbox = make_fake_watcher(tmp_path, callback)
    first = inbox / "first.txt"
    second = inbox / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    assert watcher.start()
    try:
        handler = observer.scheduled[0][0]
        handler.on_created(FileCreatedEvent(str(first)))
        assert callback_started.wait(1)

        started = time.monotonic()
        first.write_text("first changed during callback", encoding="utf-8")
        handler.on_modified(FileModifiedEvent(str(first)))
        handler.on_created(FileCreatedEvent(str(second)))
        assert time.monotonic() - started < 0.1
        with watcher._condition:
            assert len(watcher._pending) == 2

        release_callback.set()
        assert wait_until(lambda: len(calls) == 3)
        assert calls.count(str(first.resolve())) == 2
        assert calls.count(str(second.resolve())) == 1
    finally:
        release_callback.set()
        watcher.stop()


def test_callback_failure_retries_and_is_only_cached_after_success(tmp_path):
    attempts = []
    succeeded = threading.Event()
    watcher = None

    def callback(path):
        attempts.append(path)
        assert path not in watcher.processed_files
        if len(attempts) < 3:
            raise RuntimeError("transient provider error")
        succeeded.set()

    watcher, observer, inbox = make_fake_watcher(tmp_path, callback, max_retries=2)
    target = inbox / "retry.txt"
    target.write_text("retry me", encoding="utf-8")

    assert watcher.start()
    try:
        observer.scheduled[0][0].on_created(FileCreatedEvent(str(target)))
        assert succeeded.wait(2)
        assert wait_until(lambda: str(target.resolve()) in watcher.processed_files)
        assert len(attempts) == 3

        observer.scheduled[0][0].on_modified(FileModifiedEvent(str(target)))
        time.sleep(0.08)
        assert len(attempts) == 3
    finally:
        watcher.stop()


def test_callback_errors_stop_after_bounded_retries(tmp_path):
    attempts = []

    def callback(path):
        attempts.append(path)
        raise RuntimeError("still broken")

    watcher, observer, inbox = make_fake_watcher(tmp_path, callback, max_retries=2)
    target = inbox / "bounded.txt"
    target.write_text("bounded", encoding="utf-8")

    assert watcher.start()
    try:
        observer.scheduled[0][0].on_created(FileCreatedEvent(str(target)))
        assert wait_until(lambda: len(attempts) == 3 and not watcher._pending)
        time.sleep(0.08)
        assert len(attempts) == 3
        assert not watcher.processed_files
    finally:
        watcher.stop()


def test_changed_during_stability_check_is_retried(tmp_path):
    calls = []
    signatures = iter(
        [
            (1, 10, 10, 1),
            (2, 20, 20, 1),
            (2, 20, 20, 1),
        ]
    )
    stat_calls = []
    watcher, observer, inbox = make_fake_watcher(tmp_path, calls.append)
    target = inbox / "changing.txt"

    def fake_signature(_path):
        stat_calls.append(True)
        try:
            return next(signatures)
        except StopIteration:
            return (2, 20, 20, 1)

    watcher._stat_signature = fake_signature

    assert watcher.start()
    try:
        observer.scheduled[0][0].on_created(FileCreatedEvent(str(target)))
        assert wait_until(lambda: len(calls) == 1)
        assert len(stat_calls) >= 3
    finally:
        watcher.stop()


def test_internal_pending_and_completed_state_are_bounded(tmp_path):
    calls = []
    watcher, observer, inbox = make_fake_watcher(
        tmp_path,
        calls.append,
        check_interval=0.2,
        debounce_interval=0.2,
        max_pending_paths=2,
        max_tracked_paths=2,
    )
    paths = [inbox / f"file-{index}.txt" for index in range(3)]
    for index, path in enumerate(paths):
        path.write_text(str(index), encoding="utf-8")

    assert watcher.start()
    try:
        handler = observer.scheduled[0][0]
        for path in paths:
            handler.on_created(FileCreatedEvent(str(path)))
        with watcher._condition:
            assert len(watcher._pending) == 2
            assert len(watcher._schedule_heap) <= 2
    finally:
        watcher.stop()

    # Exercise the completed LRU separately with short intervals.
    completed_watcher, completed_observer, _ = make_fake_watcher(
        tmp_path, calls.append, max_tracked_paths=2
    )
    assert completed_watcher.start()
    try:
        handler = completed_observer.scheduled[0][0]
        for path in paths:
            handler.on_created(FileCreatedEvent(str(path)))
        assert wait_until(lambda: len(calls) >= 3)
        with completed_watcher._condition:
            assert len(completed_watcher._completed) == 2
    finally:
        completed_watcher.stop()


def test_start_stop_are_idempotent_and_missing_disabled_folders_are_safe(tmp_path):
    created_observers = []

    def observer_factory():
        observer = FakeObserver()
        created_observers.append(observer)
        return observer

    unavailable = FileWatcher(
        [
            WatchedFolder(str(tmp_path / "disabled"), enabled=False),
            WatchedFolder(str(tmp_path / "missing"), enabled=True),
        ],
        lambda _path: None,
        observer_factory=observer_factory,
    )
    assert unavailable.start() is False
    assert unavailable.start() is False
    unavailable.stop()
    unavailable.stop()
    assert all(observer.start_calls == 0 for observer in created_observers)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    watcher = FileWatcher(
        [WatchedFolder(str(inbox), enabled=True)],
        lambda _path: None,
        check_interval=0.01,
        observer_factory=observer_factory,
    )
    assert watcher.start() is True
    running_observer = watcher.observer
    assert watcher.start() is True
    assert running_observer.start_calls == 1
    assert watcher.is_alive()

    watcher.stop()
    watcher.stop()
    assert running_observer.stop_calls == 1
    assert running_observer.join_calls == 1
    assert not watcher.is_alive()

    assert watcher.start() is True
    assert watcher.observer is not running_observer
    watcher.stop()


def test_real_observer_processes_one_stable_allowed_file(tmp_path):
    inbox = tmp_path / "real-inbox"
    archive = inbox / "archive"
    inbox.mkdir()
    archive.mkdir()
    calls = []
    processed = threading.Event()

    def callback(path):
        calls.append(path)
        processed.set()

    watcher = FileWatcher(
        [
            WatchedFolder(
                str(inbox),
                recursive=True,
                file_extensions=[".txt"],
            )
        ],
        callback,
        check_interval=0.03,
        debounce_interval=0.03,
        retry_backoff=0.03,
        max_retry_backoff=0.06,
        excluded_roots=[archive],
    )

    assert watcher.start()
    try:
        (inbox / "ignored.pdf").write_text("ignored", encoding="utf-8")
        (inbox / "partial.txt.part").write_text("ignored", encoding="utf-8")
        (inbox / "note.watchdock_meta.json").write_text("{}", encoding="utf-8")
        (archive / "feedback.txt").write_text("ignored", encoding="utf-8")
        target = inbox / "accepted.txt"
        target.write_text("accepted", encoding="utf-8")

        assert processed.wait(5), "real watchdog observer did not deliver the event"
        time.sleep(0.2)
        assert calls == [str(target.resolve())]
    finally:
        watcher.stop()


def test_symlink_event_never_processes_external_target(tmp_path):
    calls = []
    watcher, observer, inbox = make_fake_watcher(
        tmp_path,
        calls.append,
        max_retries=0,
    )
    target = tmp_path / "outside-secret.txt"
    target.write_text("keep outside", encoding="utf-8")
    link = inbox / "download.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        import pytest

        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert watcher.start()
    try:
        observer.scheduled[0][0].on_created(FileCreatedEvent(str(link)))
        with watcher._condition:
            assert watcher._pending
            queued_path = next(iter(watcher._pending.values())).path
        assert queued_path == str(link.absolute())
        assert wait_until(lambda: not watcher._pending)
        assert calls == []
        assert link.is_symlink()
        assert target.read_text(encoding="utf-8") == "keep outside"
    finally:
        watcher.stop()
