"""Reliable, non-blocking file-system monitoring for WatchDock."""

from __future__ import annotations

import heapq
import logging
import os
import stat as stat_module
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Set, Tuple

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


FileSignature = Tuple[int, int, int, int]

_TEMPORARY_SUFFIXES = (
    ".tmp",
    ".temp",
    ".crdownload",
    ".part",
    ".partial",
    ".download",
)
_METADATA_SUFFIXES = (".watchdock_meta.json", ".watchdock.json")


def _normalise_path(path: os.PathLike) -> str:
    """Return a stable absolute path without requiring the target to exist."""

    return os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _path_key(path: os.PathLike) -> str:
    """Return the platform-appropriate identity key for a path."""

    return os.path.normcase(_normalise_path(path))


def _is_within(path: str, root: str) -> bool:
    """Return whether *path* is *root* or one of its descendants."""

    try:
        root_key = _path_key(root)
        return os.path.commonpath((_path_key(path), root_key)) == root_key
    except ValueError:
        # Paths on different Windows drives have no common path.
        return False


def _normalise_extensions(
    file_extensions: Optional[Iterable[str]],
) -> Optional[Set[str]]:
    if file_extensions is None:
        return None

    result = set()
    for extension in file_extensions:
        value = str(extension).strip().lower()
        if value:
            result.add(value if value.startswith(".") else f".{value}")
    return result


def _is_ignored_filename(path: os.PathLike) -> bool:
    """Recognise partial downloads, editor temporaries, and our sidecars."""

    name = Path(os.fspath(path)).name.lower()
    if name.startswith("~$"):
        return True
    return name.endswith(_TEMPORARY_SUFFIXES + _METADATA_SUFFIXES)


def _matches_extensions(path: os.PathLike, extensions: Optional[Set[str]]) -> bool:
    if extensions is None:
        return True
    name = Path(os.fspath(path)).name.lower()
    return any(name.endswith(extension) for extension in extensions)


def _is_excluded(path: os.PathLike, excluded_roots: Sequence[str]) -> bool:
    normalised = _normalise_path(path)
    return any(_is_within(normalised, root) for root in excluded_roots)


class WatchDockHandler(FileSystemEventHandler):
    """Translate watchdog events into cheap queue submissions.

    This handler deliberately performs no sleeps, file reads, AI work, or user
    callbacks. Those operations belong to :class:`FileWatcher`'s worker thread.
    """

    def __init__(
        self,
        enqueue: Callable[[str], None],
        *,
        file_extensions: Optional[Iterable[str]] = None,
        excluded_roots: Optional[Iterable[os.PathLike]] = None,
    ) -> None:
        super().__init__()
        self._enqueue = enqueue
        self.file_extensions = _normalise_extensions(file_extensions)
        self.excluded_roots = tuple(
            _normalise_path(root) for root in (excluded_roots or ())
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_file(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle_file(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory and getattr(event, "dest_path", None):
            self._handle_file(event.dest_path)

    def _handle_file(self, file_path: os.PathLike) -> None:
        path = os.fspath(file_path)
        if _is_ignored_filename(path):
            return
        if not _matches_extensions(path, self.file_extensions):
            return
        if _is_excluded(path, self.excluded_roots):
            return
        self._enqueue(_normalise_path(path))


@dataclass
class _PendingPath:
    path: str
    token: int
    due_at: float
    revision: int = 1
    retry_count: int = 0
    last_signature: Optional[FileSignature] = None
    stable_observations: int = 0
    queued: bool = False
    heap_due_at: float = 0.0
    schedule_version: int = 0


class FileWatcher:
    """Watch configured folders and process stable files on a worker thread.

    ``check_interval`` can be wired directly to
    ``WatchDockConfig.check_interval``. Pass archive or other output locations
    through ``excluded_roots`` so generated files are never fed back into the
    watcher::

        FileWatcher(
            config.watched_folders,
            callback,
            check_interval=config.check_interval,
            excluded_roots=[config.archive_config.base_path],
        )

    A callback signals failure by raising an exception. A signature is entered
    in the bounded successful-signature cache only after the callback returns.
    """

    def __init__(
        self,
        watched_folders: list,
        callback: Callable[[str], object],
        *,
        check_interval: float = 0.5,
        debounce_interval: Optional[float] = None,
        excluded_roots: Optional[Iterable[os.PathLike]] = None,
        max_retries: int = 4,
        retry_backoff: Optional[float] = None,
        max_retry_backoff: float = 5.0,
        stable_observations: int = 2,
        max_tracked_paths: int = 4096,
        max_pending_paths: int = 4096,
        observer_factory: Callable[[], object] = Observer,
    ) -> None:
        if check_interval <= 0:
            raise ValueError("check_interval must be greater than zero")
        if debounce_interval is not None and debounce_interval < 0:
            raise ValueError("debounce_interval cannot be negative")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if retry_backoff is not None and retry_backoff <= 0:
            raise ValueError("retry_backoff must be greater than zero")
        if max_retry_backoff <= 0:
            raise ValueError("max_retry_backoff must be greater than zero")
        if stable_observations < 2:
            raise ValueError("stable_observations must be at least two")
        if max_tracked_paths <= 0 or max_pending_paths <= 0:
            raise ValueError("watcher state bounds must be greater than zero")

        self.watched_folders = list(watched_folders)
        self.callback = callback
        self.check_interval = float(check_interval)
        self.debounce_interval = (
            min(0.2, self.check_interval)
            if debounce_interval is None
            else float(debounce_interval)
        )
        self.excluded_roots = tuple(
            _normalise_path(root) for root in (excluded_roots or ())
        )
        self.max_retries = max_retries
        self.retry_backoff = float(retry_backoff or self.check_interval)
        self.max_retry_backoff = float(max_retry_backoff)
        self.required_stable_observations = stable_observations
        self.max_tracked_paths = max_tracked_paths
        self.max_pending_paths = max_pending_paths
        self._observer_factory = observer_factory

        self.observer = None
        self.handlers: List[WatchDockHandler] = []
        self._worker: Optional[threading.Thread] = None
        self._stop_event: Optional[threading.Event] = None
        self._running = False
        self._stopping = False
        self._lifecycle_lock = threading.RLock()

        self._condition = threading.Condition(threading.RLock())
        self._pending: "OrderedDict[str, _PendingPath]" = OrderedDict()
        self._completed: "OrderedDict[str, Tuple[FileSignature, str]]" = OrderedDict()
        self._schedule_heap: List[Tuple[float, int, str, int, int]] = []
        self._sequence = 0
        self._token_sequence = 0

    @property
    def processed_files(self) -> Set[str]:
        """A compatibility snapshot of successfully processed paths."""

        with self._condition:
            return {path for _signature, path in self._completed.values()}

    def start(self) -> bool:
        """Start monitoring; repeated calls while running are harmless.

        Returns ``False`` when there are no enabled, existing directories to
        schedule. Missing or excluded folders are logged and skipped.
        """

        with self._lifecycle_lock:
            if self._running:
                return True
            if self._stopping:
                return False

            observer = self._observer_factory()
            handlers: List[WatchDockHandler] = []

            for folder_config in self.watched_folders:
                if not getattr(folder_config, "enabled", True):
                    continue

                raw_path = getattr(folder_config, "path", "")
                if not raw_path:
                    logger.warning("Skipping watched folder with an empty path")
                    continue

                folder_path = Path(_normalise_path(raw_path))
                if not folder_path.is_dir():
                    logger.warning("Watched folder does not exist: %s", folder_path)
                    continue
                if _is_excluded(str(folder_path), self.excluded_roots):
                    logger.warning("Watched folder is excluded: %s", folder_path)
                    continue

                handler = WatchDockHandler(
                    self._enqueue_candidate,
                    file_extensions=getattr(folder_config, "file_extensions", None),
                    excluded_roots=self.excluded_roots,
                )
                try:
                    observer.schedule(
                        handler,
                        str(folder_path),
                        recursive=bool(getattr(folder_config, "recursive", True)),
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    logger.warning("Could not watch folder %s: %s", folder_path, exc)
                    continue

                handlers.append(handler)
                logger.info(
                    "Watching folder: %s (recursive: %s)",
                    folder_path,
                    bool(getattr(folder_config, "recursive", True)),
                )

            if not handlers:
                logger.warning("File watcher has no enabled, available folders")
                return False

            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._worker_loop,
                args=(stop_event,),
                name="watchdock-file-worker",
                daemon=True,
            )

            self.observer = observer
            self.handlers = handlers
            self._stop_event = stop_event
            self._worker = worker
            self._running = True
            worker.start()

            try:
                observer.start()
            except Exception:
                self._running = False
                stop_event.set()
                with self._condition:
                    self._condition.notify_all()
                worker.join()
                self.observer = None
                self.handlers = []
                self._worker = None
                self._stop_event = None
                raise

            logger.info("File watcher started")
            return True

    def stop(self) -> None:
        """Stop monitoring; repeated calls are harmless."""

        with self._lifecycle_lock:
            if self._stopping:
                return
            if not self._running and self.observer is None:
                return

            self._stopping = True
            self._running = False
            observer = self.observer
            worker = self._worker
            stop_event = self._stop_event

        if observer is not None:
            try:
                if observer.is_alive():
                    observer.stop()
                    observer.join()
            except RuntimeError:
                logger.debug("Observer was already stopped", exc_info=True)

        if stop_event is not None:
            stop_event.set()
        with self._condition:
            self._condition.notify_all()
        if worker is not None and worker is not threading.current_thread():
            worker.join()

        with self._condition:
            self._pending.clear()
            self._schedule_heap.clear()

        with self._lifecycle_lock:
            self.observer = None
            self.handlers = []
            self._worker = None
            self._stop_event = None
            self._stopping = False
        logger.info("File watcher stopped")

    def is_alive(self) -> bool:
        """Return whether both the observer and processing worker are alive."""

        with self._lifecycle_lock:
            observer = self.observer
            worker = self._worker
            return bool(
                self._running
                and observer is not None
                and observer.is_alive()
                and worker is not None
                and worker.is_alive()
            )

    def _enqueue_candidate(self, file_path: str) -> None:
        """Debounce a candidate path without touching the file system."""

        if _is_ignored_filename(file_path) or _is_excluded(
            file_path, self.excluded_roots
        ):
            return

        path = _normalise_path(file_path)
        key = _path_key(path)
        now = time.monotonic()

        with self._condition:
            if not self._running:
                return

            state = self._pending.get(key)
            if state is None:
                if len(self._pending) >= self.max_pending_paths:
                    dropped_key, dropped = self._pending.popitem(last=False)
                    logger.warning(
                        "Dropping pending file because watcher queue is full: %s",
                        dropped.path,
                    )
                    self._compact_heap_locked(discard_key=dropped_key)

                self._token_sequence += 1
                state = _PendingPath(
                    path=path,
                    token=self._token_sequence,
                    due_at=now + self.debounce_interval,
                )
                self._pending[key] = state
            else:
                # A create/modify/move burst becomes one candidate. A later
                # event restarts the stability window, but not its retry budget.
                state.path = path
                state.revision += 1
                state.due_at = now + self.debounce_interval
                state.last_signature = None
                state.stable_observations = 0
                self._pending.move_to_end(key)

            self._ensure_scheduled_locked(key, state)
            self._condition.notify()

    def _ensure_scheduled_locked(self, key: str, state: _PendingPath) -> None:
        """Keep at most one current heap entry per pending state."""

        if state.queued and state.due_at >= state.heap_due_at:
            return

        self._sequence += 1
        state.schedule_version += 1
        state.queued = True
        state.heap_due_at = state.due_at
        heapq.heappush(
            self._schedule_heap,
            (
                state.heap_due_at,
                self._sequence,
                key,
                state.token,
                state.schedule_version,
            ),
        )
        self._compact_heap_locked()

    def _compact_heap_locked(self, discard_key: Optional[str] = None) -> None:
        """Prevent stale debounce entries from growing without bound."""

        limit = max(64, self.max_pending_paths * 2)
        if discard_key is None and len(self._schedule_heap) <= limit:
            return

        rebuilt = []
        for key, state in self._pending.items():
            if key == discard_key or not state.queued:
                continue
            self._sequence += 1
            state.schedule_version += 1
            rebuilt.append(
                (
                    state.heap_due_at,
                    self._sequence,
                    key,
                    state.token,
                    state.schedule_version,
                )
            )
        heapq.heapify(rebuilt)
        self._schedule_heap = rebuilt

    def _worker_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            task = None
            with self._condition:
                while not stop_event.is_set():
                    if not self._schedule_heap:
                        self._condition.wait()
                        continue

                    due_at, _sequence, key, token, version = self._schedule_heap[0]
                    remaining = due_at - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(remaining)
                        continue

                    heapq.heappop(self._schedule_heap)
                    state = self._pending.get(key)
                    if (
                        state is None
                        or state.token != token
                        or state.schedule_version != version
                        or not state.queued
                    ):
                        continue

                    state.queued = False
                    if state.due_at > time.monotonic():
                        self._ensure_scheduled_locked(key, state)
                        continue

                    task = (key, token, state.revision, state.path)
                    break

            if task is None:
                continue

            key, token, revision, path = task
            try:
                self._process_candidate(key, token, revision, path)
            except Exception as exc:  # keep the worker alive on internal errors
                logger.exception("Unexpected watcher error for %s", path)
                self._retry_candidate(key, token, revision, exc, reset_stability=True)

    def _process_candidate(
        self, key: str, token: int, revision: int, path: str
    ) -> None:
        try:
            signature = self._stat_signature(path)
        except (OSError, ValueError) as exc:
            self._retry_candidate(key, token, revision, exc, reset_stability=True)
            return

        with self._condition:
            state = self._current_state_locked(key, token, revision)
            if state is None:
                return

            completed = self._completed.get(key)
            if completed is not None and completed[0] == signature:
                self._completed.move_to_end(key)
                self._pending.pop(key, None)
                return

            if state.last_signature is None:
                state.last_signature = signature
                state.stable_observations = 1
                state.due_at = time.monotonic() + self.check_interval
                self._ensure_scheduled_locked(key, state)
                self._condition.notify()
                return

            if state.last_signature != signature:
                state.last_signature = signature
                state.stable_observations = 1
                if not self._schedule_retry_locked(
                    key, state, "file changed while waiting for stability"
                ):
                    return
                self._condition.notify()
                return

            state.stable_observations += 1
            if state.stable_observations < self.required_stable_observations:
                state.due_at = time.monotonic() + self.check_interval
                self._ensure_scheduled_locked(key, state)
                self._condition.notify()
                return

        try:
            self.callback(path)
        except Exception as exc:
            logger.warning("File callback failed for %s: %s", path, exc)
            self._retry_candidate(key, token, revision, exc, reset_stability=False)
            return

        with self._condition:
            # Remember the processed signature even if a new event arrived
            # during the callback. That newer event remains pending and will be
            # compared against this signature on its own pass.
            self._completed[key] = (signature, path)
            self._completed.move_to_end(key)
            while len(self._completed) > self.max_tracked_paths:
                self._completed.popitem(last=False)

            state = self._current_state_locked(key, token, revision)
            if state is not None:
                self._pending.pop(key, None)
            logger.info("Processed stable file: %s", path)

    def _stat_signature(self, path: str) -> FileSignature:
        """Return a change signature after confirming the file is readable."""

        path_obj = Path(path)
        file_stat = path_obj.stat()
        if not stat_module.S_ISREG(file_stat.st_mode):
            raise OSError(f"Not a regular file: {path}")

        # Opening catches common Windows sharing/permission failures without
        # reading file content or holding the file open across a callback.
        with path_obj.open("rb"):
            pass

        return (
            file_stat.st_size,
            file_stat.st_mtime_ns,
            getattr(file_stat, "st_ctime_ns", 0),
            getattr(file_stat, "st_ino", 0),
        )

    def _retry_candidate(
        self,
        key: str,
        token: int,
        revision: int,
        reason: Exception,
        *,
        reset_stability: bool,
    ) -> None:
        with self._condition:
            state = self._current_state_locked(key, token, revision)
            if state is None:
                return
            if reset_stability:
                state.last_signature = None
                state.stable_observations = 0
            if self._schedule_retry_locked(key, state, str(reason)):
                self._condition.notify()

    def _schedule_retry_locked(
        self, key: str, state: _PendingPath, reason: str
    ) -> bool:
        state.retry_count += 1
        if state.retry_count > self.max_retries:
            self._pending.pop(key, None)
            logger.error(
                "Giving up on file after %s retries (%s): %s",
                self.max_retries,
                reason,
                state.path,
            )
            return False

        delay = min(
            self.retry_backoff * (2 ** (state.retry_count - 1)),
            self.max_retry_backoff,
        )
        state.due_at = time.monotonic() + delay
        self._ensure_scheduled_locked(key, state)
        logger.debug(
            "Retrying file in %.3fs (%s/%s, %s): %s",
            delay,
            state.retry_count,
            self.max_retries,
            reason,
            state.path,
        )
        return True

    def _current_state_locked(
        self, key: str, token: int, revision: Optional[int] = None
    ) -> Optional[_PendingPath]:
        state = self._pending.get(key)
        if (
            state is None
            or state.token != token
            or (revision is not None and state.revision != revision)
        ):
            return None
        return state
