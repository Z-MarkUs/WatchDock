"""Durable pending-action storage for human-in-the-loop workflows.

The queue is intentionally a small SQLite state machine rather than an in-memory
list mirrored to JSON. Separate WatchDock CLI, GUI, and watcher processes can
therefore claim work without claiming the same action twice.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Union

from watchdock.paths import app_home, default_database_path

logger = logging.getLogger(__name__)

WATCHDOCK_STATE_DIR = app_home()
PENDING_ACTIONS_PATH = str(WATCHDOCK_STATE_DIR / "pending_actions.json")
PENDING_ACTIONS_DB_PATH = str(default_database_path())

ACTION_STATES = frozenset({"pending", "processing", "completed", "rejected", "failed"})
TERMINAL_STATES = frozenset({"completed", "rejected"})


class SourceChangedError(RuntimeError):
    """Raised when a source changes while its fingerprint is being captured."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json_dumps(value: Mapping[str, Any]) -> str:
    # Serialize before opening a transaction so malformed provider output cannot
    # cause a partial queue write.
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _legacy_status(status_value: Any) -> str:
    status_name = str(status_value or "pending").lower()
    if status_name in ACTION_STATES:
        return status_name
    # Legacy code wrote "approved" before attempting the filesystem operation.
    # Completion cannot be proven, so importing it as completed would be unsafe.
    if status_name == "approved":
        return "failed"
    return "failed"


def capture_source_fingerprint(
    file_path: Union[str, os.PathLike[str]], include_hash: bool = False
) -> Dict[str, Any]:
    """Capture source identity, size/mtime and, optionally, SHA-256.

    The pre/post stat check prevents recording a digest for a file that changed
    while it was read. New actions require a regular source file; legacy imports
    may retain a null fingerprint when the old source no longer exists.
    """

    source = Path(file_path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Pending actions require a regular source file")

    fingerprint: Dict[str, Any] = {
        "device": before.st_dev,
        "inode": before.st_ino,
        "size": before.st_size,
        "mtime_ns": before.st_mtime_ns,
        "sha256": None,
    }
    digest = hashlib.sha256() if include_hash else None
    with source.open("rb") as source_file:
        opened = os.fstat(source_file.fileno())
        if not stat.S_ISREG(opened.st_mode) or (
            before.st_dev,
            before.st_ino,
        ) != (opened.st_dev, opened.st_ino):
            raise SourceChangedError(
                "Source changed identity while its fingerprint was being captured"
            )
        if digest is not None:
            for block in iter(lambda: source_file.read(1024 * 1024), b""):
                digest.update(block)

    after = source.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise SourceChangedError(
            "Source changed while its fingerprint was being captured"
        )
    if digest is not None:
        fingerprint["sha256"] = digest.hexdigest()
    return fingerprint


def _normalize_proposed_action(
    source_path: Path, proposed_action: Mapping[str, Any]
) -> Dict[str, Any]:
    """Freeze proposal paths so later CLI processes cannot reinterpret them."""

    normalized = dict(proposed_action)
    action_type = normalized.get("action_type")
    if action_type not in {"move", "rename"}:
        raise ValueError("proposed action_type must be move or rename")
    proposed_source = normalized.get("from")
    proposed_destination = normalized.get("to")
    if not isinstance(proposed_source, str) or not proposed_source.strip():
        raise ValueError("proposed action requires a source path")
    if not isinstance(proposed_destination, str) or not proposed_destination.strip():
        raise ValueError("proposed action requires a destination path")

    resolved_source = Path(proposed_source).expanduser().resolve(strict=True)
    if resolved_source != source_path:
        raise ValueError("proposed action source does not match the reviewed file")
    resolved_destination = Path(proposed_destination).expanduser().resolve(strict=False)
    normalized["from"] = str(source_path)
    normalized["to"] = str(resolved_destination)
    return normalized


class PendingAction:
    """A persisted organization proposal and its lifecycle state."""

    def __init__(
        self,
        file_path: str,
        analysis: Mapping[str, Any],
        proposed_action: Mapping[str, Any],
        action_id: Optional[str] = None,
        source_size: Optional[int] = None,
        source_mtime_ns: Optional[int] = None,
        source_sha256: Optional[str] = None,
        status: str = "pending",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        processing_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        rejected_at: Optional[str] = None,
        failed_at: Optional[str] = None,
        error: Optional[str] = None,
        claimed_by: Optional[str] = None,
        attempt_count: int = 0,
    ) -> None:
        now = _utc_now()
        self.action_id = action_id or str(uuid.uuid4())
        self.file_path = str(file_path)
        self.analysis = dict(analysis)
        self.proposed_action = dict(proposed_action)
        self.source_size = source_size
        self.source_mtime_ns = source_mtime_ns
        self.source_sha256 = source_sha256
        self.status = _legacy_status(status)
        self.created_at = created_at or now
        self.updated_at = updated_at or self.created_at
        self.processing_at = processing_at
        self.completed_at = completed_at
        self.rejected_at = rejected_at
        self.failed_at = failed_at
        self.error = error
        self.claimed_by = claimed_by
        self.attempt_count = int(attempt_count)

    @property
    def source_fingerprint(self) -> Dict[str, Any]:
        return {
            "size": self.source_size,
            "mtime_ns": self.source_mtime_ns,
            "sha256": self.source_sha256,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-compatible representation for APIs and diagnostics."""

        return {
            "action_id": self.action_id,
            "file_path": self.file_path,
            "analysis": self.analysis,
            "proposed_action": self.proposed_action,
            "source_fingerprint": self.source_fingerprint,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "processing_at": self.processing_at,
            "completed_at": self.completed_at,
            "rejected_at": self.rejected_at,
            "failed_at": self.failed_at,
            "error": self.error,
            "claimed_by": self.claimed_by,
            "attempt_count": self.attempt_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PendingAction":
        """Construct an action from current or legacy serialized data."""

        fingerprint = data.get("source_fingerprint") or {}
        if not isinstance(fingerprint, Mapping):
            fingerprint = {}
        return cls(
            file_path=str(data["file_path"]),
            analysis=data.get("analysis") or {},
            proposed_action=data.get("proposed_action") or {},
            action_id=data.get("action_id"),
            source_size=fingerprint.get("size", data.get("source_size")),
            source_mtime_ns=fingerprint.get("mtime_ns", data.get("source_mtime_ns")),
            source_sha256=fingerprint.get("sha256", data.get("source_sha256")),
            status=str(data.get("status", "pending")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            processing_at=data.get("processing_at"),
            completed_at=data.get("completed_at"),
            rejected_at=data.get("rejected_at"),
            failed_at=data.get("failed_at"),
            error=data.get("error"),
            claimed_by=data.get("claimed_by"),
            attempt_count=int(data.get("attempt_count", 0)),
        )


class PendingActionsQueue:
    """Transactional SQLite repository for pending organization actions.

    Recommended execution flow::

        action = queue.claim(action_id, worker_id="cli")
        if action and queue.source_matches(action):
            try:
                execute_exactly(action.proposed_action)
            except Exception as exc:
                queue.fail(action.action_id, str(exc))
            else:
                queue.complete(action.action_id)

    ``approve`` and ``remove`` remain compatibility aliases for ``claim`` and
    ``complete``. ``remove`` never deletes a claimed action.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, os.PathLike[str]]] = None,
        *,
        legacy_json_path: Optional[Union[str, os.PathLike[str]]] = None,
        busy_timeout_ms: int = 5000,
        migrate_legacy: bool = True,
    ) -> None:
        using_default_database = db_path is None
        self.db_path = Path(db_path) if db_path is not None else default_database_path()
        if str(self.db_path) == ":memory:":
            raise ValueError("Use a temporary filesystem path, not ':memory:'")
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be positive")
        self.busy_timeout_ms = int(busy_timeout_ms)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

        if migrate_legacy:
            if legacy_json_path is not None:
                source = Path(legacy_json_path)
            elif using_default_database:
                source = app_home() / "pending_actions.json"
            else:
                # A custom state/config directory should migrate its colocated
                # legacy queue without requiring every caller to know migration
                # details.
                source = self.db_path.parent / "pending_actions.json"
            self._import_legacy_json(source)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=self.busy_timeout_ms / 1000.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        # SQLite's PRAGMA grammar does not accept bound parameters. The value is
        # normalized to a positive integer in ``__init__`` before interpolation.
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        connection = self._connect()
        try:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if str(journal_mode).lower() != "wal":
                journal_mode = connection.execute(
                    "PRAGMA journal_mode = WAL"
                ).fetchone()[0]
            if str(journal_mode).lower() != "wal":
                logger.warning(
                    "SQLite WAL mode is unavailable for %s; using %s",
                    self.db_path,
                    journal_mode,
                )
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    action_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    proposed_action_json TEXT NOT NULL,
                    source_size INTEGER,
                    source_mtime_ns INTEGER,
                    source_sha256 TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'pending', 'processing', 'completed',
                            'rejected', 'failed'
                        )
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    processing_at TEXT,
                    completed_at TEXT,
                    rejected_at TEXT,
                    failed_at TEXT,
                    error TEXT,
                    claimed_by TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_pending_actions_status_created
                    ON pending_actions(status, created_at, action_id);

                CREATE TABLE IF NOT EXISTS action_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    worker_id TEXT,
                    error TEXT,
                    FOREIGN KEY(action_id) REFERENCES pending_actions(action_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_action_events_action
                    ON action_events(action_id, event_id);

                CREATE TABLE IF NOT EXISTS queue_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                INSERT OR IGNORE INTO queue_metadata(key, value)
                    VALUES ('schema_version', '1');
                """)
        finally:
            connection.close()

        if os.name != "nt":
            try:
                os.chmod(self.db_path, 0o600)
            except OSError:
                logger.debug("Could not restrict queue database permissions")

    @staticmethod
    def _row_to_action(row: sqlite3.Row) -> PendingAction:
        analysis = json.loads(row["analysis_json"])
        proposed_action = json.loads(row["proposed_action_json"])
        if not isinstance(analysis, dict) or not isinstance(proposed_action, dict):
            raise ValueError("Persisted action payload is not a JSON object")
        return PendingAction(
            action_id=row["action_id"],
            file_path=row["file_path"],
            analysis=analysis,
            proposed_action=proposed_action,
            source_size=row["source_size"],
            source_mtime_ns=row["source_mtime_ns"],
            source_sha256=row["source_sha256"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            processing_at=row["processing_at"],
            completed_at=row["completed_at"],
            rejected_at=row["rejected_at"],
            failed_at=row["failed_at"],
            error=row["error"],
            claimed_by=row["claimed_by"],
            attempt_count=row["attempt_count"],
        )

    @staticmethod
    def _record_event(
        connection: sqlite3.Connection,
        action_id: str,
        from_status: Optional[str],
        to_status: str,
        occurred_at: str,
        worker_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO action_events (
                action_id, from_status, to_status, occurred_at, worker_id, error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (action_id, from_status, to_status, occurred_at, worker_id, error),
        )

    def _import_legacy_json(self, legacy_path: Path) -> None:
        if not legacy_path.exists():
            return
        marker = "legacy_json_imported_v1:" + str(legacy_path.resolve())
        connection = self._connect()
        try:
            already_imported = connection.execute(
                "SELECT 1 FROM queue_metadata WHERE key = ?", (marker,)
            ).fetchone()
        finally:
            connection.close()
        if already_imported:
            return

        try:
            with legacy_path.open("r", encoding="utf-8") as legacy_file:
                legacy_data = json.load(legacy_file)
            if not isinstance(legacy_data, dict):
                raise ValueError("legacy queue root must be an object")
            records = legacy_data.get("actions", [])
            if not isinstance(records, list):
                raise ValueError("legacy actions must be a list")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Could not import legacy pending actions: %s", exc)
            return

        imported = 0
        with self._transaction(immediate=True) as connection:
            if connection.execute(
                "SELECT 1 FROM queue_metadata WHERE key = ?", (marker,)
            ).fetchone():
                return

            for record in records:
                if not isinstance(record, Mapping):
                    logger.warning("Skipping malformed legacy pending action")
                    continue
                try:
                    action = PendingAction.from_dict(record)
                    if (
                        action.status == "failed"
                        and str(record.get("status", "")).lower() == "approved"
                    ):
                        action.error = (
                            "Imported legacy approved action; execution could not "
                            "be verified"
                        )
                        action.failed_at = action.updated_at
                    if action.source_size is None or action.source_mtime_ns is None:
                        try:
                            fingerprint = capture_source_fingerprint(action.file_path)
                        except (OSError, ValueError):
                            fingerprint = {}
                        action.source_size = fingerprint.get("size")
                        action.source_mtime_ns = fingerprint.get("mtime_ns")
                        action.source_sha256 = fingerprint.get("sha256")

                    cursor = connection.execute(
                        """
                        INSERT OR IGNORE INTO pending_actions (
                            action_id, file_path, analysis_json,
                            proposed_action_json, source_size, source_mtime_ns,
                            source_sha256, status, created_at, updated_at,
                            processing_at, completed_at, rejected_at, failed_at,
                            error, claimed_by, attempt_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            action.action_id,
                            action.file_path,
                            _json_dumps(action.analysis),
                            _json_dumps(action.proposed_action),
                            action.source_size,
                            action.source_mtime_ns,
                            action.source_sha256,
                            action.status,
                            action.created_at,
                            action.updated_at,
                            action.processing_at,
                            action.completed_at,
                            action.rejected_at,
                            action.failed_at,
                            action.error,
                            action.claimed_by,
                            action.attempt_count,
                        ),
                    )
                    if cursor.rowcount:
                        self._record_event(
                            connection,
                            action.action_id,
                            None,
                            action.status,
                            action.updated_at,
                            error=action.error,
                        )
                        imported += 1
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Skipping malformed legacy action: %s", exc)

            connection.execute(
                "INSERT INTO queue_metadata(key, value) VALUES (?, ?)",
                (
                    marker,
                    json.dumps(
                        {"imported": imported, "imported_at": _utc_now()},
                        separators=(",", ":"),
                    ),
                ),
            )
        logger.info("Imported %s legacy pending action(s)", imported)

    @property
    def actions(self) -> List[PendingAction]:
        """Compatibility view of currently pending actions."""

        return self.get_pending()

    def _prepare_new_action(
        self,
        file_path: str,
        analysis: Mapping[str, Any],
        proposed_action: Mapping[str, Any],
        *,
        source_fingerprint: Optional[Mapping[str, Any]] = None,
        include_source_hash: bool = False,
    ) -> tuple[PendingAction, str, str]:
        """Validate and serialize a new action before opening a transaction."""

        lexical_source_path = Path(file_path).expanduser().absolute()
        if source_fingerprint is None:
            fingerprint = capture_source_fingerprint(
                lexical_source_path, include_hash=include_source_hash
            )
        else:
            fingerprint = dict(source_fingerprint)

        # Resolve only after the lstat-based regular-file check above.  Resolving
        # first would silently turn a symlink proposal into an action against its
        # external target.
        source_path = lexical_source_path.resolve(strict=True)

        source_size = fingerprint.get("size")
        source_mtime_ns = fingerprint.get("mtime_ns")
        source_sha256 = fingerprint.get("sha256")
        if source_size is not None:
            source_size = int(source_size)
        if source_mtime_ns is not None:
            source_mtime_ns = int(source_mtime_ns)
        if source_size is None or source_mtime_ns is None:
            raise ValueError("source fingerprint requires size and mtime_ns")
        if source_size < 0 or source_mtime_ns < 0:
            raise ValueError("source fingerprint values cannot be negative")
        if source_sha256 is not None:
            source_sha256 = str(source_sha256).lower()
            if len(source_sha256) != 64 or any(
                char not in "0123456789abcdef" for char in source_sha256
            ):
                raise ValueError("source sha256 must contain 64 hexadecimal chars")
        if source_fingerprint is not None:
            current = capture_source_fingerprint(
                lexical_source_path, include_hash=source_sha256 is not None
            )
            if (
                current["size"] != source_size
                or current["mtime_ns"] != source_mtime_ns
                or (source_sha256 is not None and current["sha256"] != source_sha256)
            ):
                raise SourceChangedError(
                    "Provided source fingerprint does not match the current file"
                )

        normalized_proposal = _normalize_proposed_action(source_path, proposed_action)
        analysis_json = _json_dumps(analysis)
        proposed_action_json = _json_dumps(normalized_proposal)
        analysis_payload = json.loads(analysis_json)
        proposal_payload = json.loads(proposed_action_json)

        now = _utc_now()
        action = PendingAction(
            action_id=str(uuid.uuid4()),
            file_path=str(source_path),
            analysis=analysis_payload,
            proposed_action=proposal_payload,
            source_size=source_size,
            source_mtime_ns=source_mtime_ns,
            source_sha256=source_sha256,
            created_at=now,
            updated_at=now,
        )
        return action, analysis_json, proposed_action_json

    def _insert_prepared_action(
        self,
        connection: sqlite3.Connection,
        action: PendingAction,
        analysis_json: str,
        proposed_action_json: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO pending_actions (
                action_id, file_path, analysis_json, proposed_action_json,
                source_size, source_mtime_ns, source_sha256, status,
                created_at, updated_at, attempt_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, 0)
            """,
            (
                action.action_id,
                action.file_path,
                analysis_json,
                proposed_action_json,
                action.source_size,
                action.source_mtime_ns,
                action.source_sha256,
                action.created_at,
                action.updated_at,
            ),
        )
        self._record_event(
            connection,
            action.action_id,
            None,
            "pending",
            action.created_at,
        )

    def add(
        self,
        file_path: str,
        analysis: Mapping[str, Any],
        proposed_action: Mapping[str, Any],
        *,
        source_fingerprint: Optional[Mapping[str, Any]] = None,
        include_source_hash: bool = False,
    ) -> PendingAction:
        """Persist a proposal and a fingerprint of the source being reviewed."""

        action, analysis_json, proposed_action_json = self._prepare_new_action(
            file_path,
            analysis,
            proposed_action,
            source_fingerprint=source_fingerprint,
            include_source_hash=include_source_hash,
        )
        with self._transaction(immediate=True) as connection:
            self._insert_prepared_action(
                connection,
                action,
                analysis_json,
                proposed_action_json,
            )
        logger.info("Added pending action %s for %s", action.action_id, action.file_path)
        return action

    def add_or_get_active(
        self,
        file_path: str,
        analysis: Mapping[str, Any],
        proposed_action: Mapping[str, Any],
        *,
        source_fingerprint: Optional[Mapping[str, Any]] = None,
        include_source_hash: bool = False,
    ) -> tuple[PendingAction, bool]:
        """Atomically add a proposal or return matching active work.

        An action is considered the same active proposal when it has the same
        canonical source path and source fingerprint and is either pending or
        processing.  The immediate SQLite transaction makes this decision safe
        across simultaneous CLI, GUI, and agent processes.  ``add`` retains its
        historical always-insert behavior for backwards compatibility.

        The boolean return value is true only when this call inserted the row.
        """

        action, analysis_json, proposed_action_json = self._prepare_new_action(
            file_path,
            analysis,
            proposed_action,
            source_fingerprint=source_fingerprint,
            include_source_hash=include_source_hash,
        )
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                """
                SELECT *
                  FROM pending_actions
                 WHERE file_path = ?
                   AND status IN ('pending', 'processing')
                   AND source_size = ?
                   AND source_mtime_ns = ?
                   AND (
                        source_sha256 IS NULL
                        OR ? IS NULL
                        OR source_sha256 = ?
                   )
                 ORDER BY created_at, action_id
                 LIMIT 1
                """,
                (
                    action.file_path,
                    action.source_size,
                    action.source_mtime_ns,
                    action.source_sha256,
                    action.source_sha256,
                ),
            ).fetchone()
            if row is not None:
                existing = self._row_to_action(row)
                logger.info(
                    "Reused active action %s for %s",
                    existing.action_id,
                    existing.file_path,
                )
                return existing, False

            self._insert_prepared_action(
                connection,
                action,
                analysis_json,
                proposed_action_json,
            )

        logger.info("Added pending action %s for %s", action.action_id, action.file_path)
        return action, True

    def list_actions(
        self,
        statuses: Optional[Iterable[str]] = None,
        *,
        limit: Optional[int] = None,
    ) -> List[PendingAction]:
        """List actions ordered by creation time, optionally filtered by state."""

        parameters: List[Any] = []
        query = "SELECT * FROM pending_actions"
        if statuses is not None:
            normalized = list(dict.fromkeys(str(item) for item in statuses))
            invalid = set(normalized) - ACTION_STATES
            if invalid:
                raise ValueError(
                    "Unknown action state(s): " + ", ".join(sorted(invalid))
                )
            if not normalized:
                return []
            placeholders = ", ".join("?" for _ in normalized)
            query += " WHERE status IN (" + placeholders + ")"
            parameters.extend(normalized)
        query += " ORDER BY created_at, action_id"
        if limit is not None:
            if limit < 0:
                raise ValueError("limit cannot be negative")
            query += " LIMIT ?"
            parameters.append(int(limit))

        connection = self._connect()
        try:
            rows = connection.execute(query, parameters).fetchall()
            return [self._row_to_action(row) for row in rows]
        finally:
            connection.close()

    def get_pending(self) -> List[PendingAction]:
        return self.list_actions(["pending"])

    def get_by_id(self, action_id: str) -> Optional[PendingAction]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._row_to_action(row) if row else None
        finally:
            connection.close()

    def _claim_in_transaction(
        self,
        connection: sqlite3.Connection,
        action_id: str,
        worker_id: Optional[str],
    ) -> Optional[PendingAction]:
        now = _utc_now()
        cursor = connection.execute(
            """
            UPDATE pending_actions
               SET status = 'processing', updated_at = ?, processing_at = ?,
                   claimed_by = ?, error = NULL,
                   attempt_count = attempt_count + 1
             WHERE action_id = ? AND status = 'pending'
            """,
            (now, now, worker_id, action_id),
        )
        if cursor.rowcount != 1:
            return None
        self._record_event(
            connection,
            action_id,
            "pending",
            "processing",
            now,
            worker_id=worker_id,
        )
        row = connection.execute(
            "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
        ).fetchone()
        return self._row_to_action(row)

    def claim(
        self, action_id: str, *, worker_id: Optional[str] = None
    ) -> Optional[PendingAction]:
        """Atomically claim one pending action; competing claims return ``None``."""

        with self._transaction(immediate=True) as connection:
            return self._claim_in_transaction(connection, action_id, worker_id)

    def claim_next(self, *, worker_id: Optional[str] = None) -> Optional[PendingAction]:
        """Atomically claim the oldest pending action."""

        with self._transaction(immediate=True) as connection:
            row = connection.execute("""
                SELECT action_id FROM pending_actions
                 WHERE status = 'pending'
                 ORDER BY created_at, action_id
                 LIMIT 1
                """).fetchone()
            if row is None:
                return None
            return self._claim_in_transaction(connection, row["action_id"], worker_id)

    def approve(self, action_id: str) -> Optional[PendingAction]:
        """Compatibility alias: approval claims work but does not complete it."""

        return self.claim(action_id, worker_id="legacy-approve")

    def complete(self, action_id: str) -> Optional[PendingAction]:
        """Mark a processing action completed after verified execution."""

        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT status, claimed_by FROM pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] == "completed":
                completed = connection.execute(
                    "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                return self._row_to_action(completed)
            if row["status"] != "processing":
                return None
            connection.execute(
                """
                UPDATE pending_actions
                   SET status = 'completed', updated_at = ?, completed_at = ?,
                       error = NULL
                 WHERE action_id = ? AND status = 'processing'
                """,
                (now, now, action_id),
            )
            self._record_event(
                connection,
                action_id,
                "processing",
                "completed",
                now,
                worker_id=row["claimed_by"],
            )
            completed = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._row_to_action(completed)

    def fail(self, action_id: str, error: str) -> Optional[PendingAction]:
        """Retain a processing action as failed with a durable error message."""

        error_message = str(error).strip() or "Action execution failed"
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT status, claimed_by FROM pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            if row is None or row["status"] != "processing":
                return None
            connection.execute(
                """
                UPDATE pending_actions
                   SET status = 'failed', updated_at = ?, failed_at = ?, error = ?
                 WHERE action_id = ? AND status = 'processing'
                """,
                (now, now, error_message, action_id),
            )
            self._record_event(
                connection,
                action_id,
                "processing",
                "failed",
                now,
                worker_id=row["claimed_by"],
                error=error_message,
            )
            failed = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._row_to_action(failed)

    def retry(self, action_id: str) -> Optional[PendingAction]:
        """Return a failed action to pending for an explicit retry."""

        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                   SET status = 'pending', updated_at = ?, processing_at = NULL,
                       claimed_by = NULL, error = NULL
                 WHERE action_id = ? AND status = 'failed'
                """,
                (now, action_id),
            )
            if cursor.rowcount != 1:
                return None
            self._record_event(connection, action_id, "failed", "pending", now)
            retried = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._row_to_action(retried)

    def reject(self, action_id: str) -> Optional[PendingAction]:
        """Reject an unclaimed or failed action without deleting its audit row."""

        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT status FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                return None
            if row["status"] == "rejected":
                rejected = connection.execute(
                    "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
                ).fetchone()
                return self._row_to_action(rejected)
            if row["status"] not in {"pending", "failed"}:
                return None
            connection.execute(
                """
                UPDATE pending_actions
                   SET status = 'rejected', updated_at = ?, rejected_at = ?,
                       claimed_by = NULL
                 WHERE action_id = ? AND status = ?
                """,
                (now, now, action_id, row["status"]),
            )
            self._record_event(connection, action_id, row["status"], "rejected", now)
            rejected = connection.execute(
                "SELECT * FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._row_to_action(rejected)

    def remove(self, action_id: str) -> Optional[PendingAction]:
        """Compatibility alias for completion; it never physically deletes work."""

        return self.complete(action_id)

    def fail_stale_processing(
        self,
        older_than_seconds: float,
        *,
        error: str = "Processing claim expired; execution outcome requires review",
    ) -> List[PendingAction]:
        """Fail stale claims rather than blindly retrying a possibly executed move."""

        if older_than_seconds < 0:
            raise ValueError("older_than_seconds cannot be negative")
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
        ).isoformat(timespec="microseconds")
        now = _utc_now()
        failed: List[PendingAction] = []
        with self._transaction(immediate=True) as connection:
            rows = connection.execute(
                """
                SELECT action_id, claimed_by FROM pending_actions
                 WHERE status = 'processing' AND processing_at <= ?
                 ORDER BY processing_at, action_id
                """,
                (cutoff,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE pending_actions
                       SET status = 'failed', updated_at = ?, failed_at = ?,
                           error = ?
                     WHERE action_id = ? AND status = 'processing'
                    """,
                    (now, now, error, row["action_id"]),
                )
                self._record_event(
                    connection,
                    row["action_id"],
                    "processing",
                    "failed",
                    now,
                    worker_id=row["claimed_by"],
                    error=error,
                )
                action_row = connection.execute(
                    "SELECT * FROM pending_actions WHERE action_id = ?",
                    (row["action_id"],),
                ).fetchone()
                failed.append(self._row_to_action(action_row))
        return failed

    def source_matches(self, action_or_id: Union[PendingAction, str]) -> bool:
        """Return whether the current source matches the reviewed fingerprint."""

        if isinstance(action_or_id, PendingAction):
            action = action_or_id
        else:
            action = self.get_by_id(action_or_id)
            if action is None:
                return False
        if action.source_size is None or action.source_mtime_ns is None:
            return False
        try:
            current = capture_source_fingerprint(
                action.file_path, include_hash=bool(action.source_sha256)
            )
        except (OSError, ValueError, SourceChangedError):
            return False
        return (
            current["size"] == action.source_size
            and current["mtime_ns"] == action.source_mtime_ns
            and (
                action.source_sha256 is None
                or current["sha256"] == action.source_sha256
            )
        )

    def get_events(self, action_id: str) -> List[Dict[str, Any]]:
        """Return the append-only lifecycle event history for one action."""

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT event_id, action_id, from_status, to_status,
                       occurred_at, worker_id, error
                  FROM action_events
                 WHERE action_id = ?
                 ORDER BY event_id
                """,
                (action_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def clear_processed(self) -> int:
        """Physically purge completed/rejected history, leaving failures retryable."""

        with self._transaction(immediate=True) as connection:
            placeholders = ", ".join("?" for _ in TERMINAL_STATES)
            cursor = connection.execute(
                "DELETE FROM pending_actions WHERE status IN (" + placeholders + ")",
                tuple(sorted(TERMINAL_STATES)),
            )
            return cursor.rowcount

    # Kept for callers that invoked the old private load helper. Reads are live
    # in SQLite, so there is no in-memory cache to refresh.
    def _load(self) -> List[PendingAction]:
        return self.get_pending()
