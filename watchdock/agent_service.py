"""Structured, fail-closed operations for local coding agents.

This module deliberately stops at the human-review boundary.  It can inspect
files, create exact organization proposals, and update review-queue state, but
it never claims, approves, or executes a filesystem action.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, TypedDict

from watchdock import __version__
from watchdock.ai_processor import AIProcessor
from watchdock.config import WatchDockConfig
from watchdock.file_organizer import FileOrganizer
from watchdock.main import _same_fingerprint, _validated_watched_source
from watchdock.paths import default_config_path
from watchdock.pending_actions import (
    ACTION_STATES,
    PendingAction,
    PendingActionsQueue,
    SourceChangedError,
    capture_source_fingerprint,
)


class AgentError(TypedDict):
    """Machine-readable error returned by every agent operation."""

    code: str
    message: str


class AgentResponse(TypedDict):
    """Stable response envelope used by the service and MCP tools."""

    ok: bool
    operation: str
    data: Dict[str, Any]
    error: Optional[AgentError]


class AgentServiceError(RuntimeError):
    """Expected service rejection with a stable public error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _success(operation: str, data: Mapping[str, Any]) -> AgentResponse:
    return AgentResponse(
        ok=True,
        operation=operation,
        data=dict(data),
        error=None,
    )


def _failure(operation: str, code: str, message: str) -> AgentResponse:
    return AgentResponse(
        ok=False,
        operation=operation,
        data={},
        error=AgentError(code=code, message=message),
    )


def _json_object(value: Mapping[str, Any], *, name: str) -> Dict[str, Any]:
    """Return a detached, strictly JSON-compatible mapping."""

    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise AgentServiceError(
            "invalid_payload", f"{name} is not JSON-compatible: {exc}"
        ) from exc
    if not isinstance(decoded, dict):  # pragma: no cover - guarded by dict(value)
        raise AgentServiceError("invalid_payload", f"{name} must be an object")
    return decoded


class AgentService:
    """Agent-safe facade over WatchDock's analysis and durable review queue."""

    def __init__(
        self,
        config: WatchDockConfig,
        *,
        config_path: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        ai_processor: Optional[AIProcessor] = None,
        file_organizer: Optional[FileOrganizer] = None,
        pending_queue: Optional[PendingActionsQueue] = None,
    ) -> None:
        config.validate()
        self.config = config
        configured_path = (config_path or default_config_path()).expanduser().absolute()
        self.config_path = configured_path
        self.state_dir = (state_dir or configured_path.parent).expanduser().absolute()
        self.ai_processor = ai_processor or AIProcessor(
            config.ai_config,
            examples_path=self.state_dir / "few_shot_examples.json",
        )
        self.file_organizer = file_organizer or FileOrganizer(config.archive_config)
        self.pending_queue = pending_queue or PendingActionsQueue(
            db_path=self.state_dir / "pending_actions.sqlite3"
        )

    @classmethod
    def from_config_path(cls, config_path: Optional[Path] = None) -> "AgentService":
        """Load an existing configuration; never silently invent one for an agent."""

        path = (config_path or default_config_path()).expanduser().absolute()
        if not path.is_file():
            raise FileNotFoundError(
                f"configuration not found: {path} (run 'watchdock config init')"
            )
        return cls(
            WatchDockConfig.load(str(path)),
            config_path=path,
            state_dir=path.parent,
        )

    @staticmethod
    def _error_response(operation: str, exc: Exception) -> AgentResponse:
        if isinstance(exc, AgentServiceError):
            return _failure(operation, exc.code, str(exc))
        if isinstance(exc, SourceChangedError):
            return _failure(operation, "source_changed", str(exc))
        if isinstance(exc, FileNotFoundError):
            return _failure(operation, "not_found", str(exc))
        if isinstance(exc, PermissionError):
            return _failure(operation, "permission_denied", str(exc))
        if isinstance(exc, ValueError):
            message = str(exc)
            if "outside configured watched folders" in message:
                return _failure(operation, "outside_watched_roots", message)
            if "regular file" in message:
                return _failure(operation, "unsafe_source", message)
            return _failure(operation, "invalid_request", message)
        if isinstance(exc, OSError):
            return _failure(operation, "filesystem_error", str(exc))
        return _failure(operation, "internal_error", str(exc) or type(exc).__name__)

    def _prepare_proposal(
        self,
        file_path: str,
        *,
        include_source_hash: bool = False,
    ) -> Dict[str, Any]:
        source = _validated_watched_source(self.config, file_path)
        if self.file_organizer.is_managed_path(source):
            raise AgentServiceError(
                "managed_path", "source is already inside WatchDock's managed archive"
            )

        before_analysis = capture_source_fingerprint(source)
        analysis_value = self.ai_processor.analyze_file(source)
        if not isinstance(analysis_value, Mapping):
            raise AgentServiceError("invalid_payload", "analysis must be an object")
        analysis = _json_object(analysis_value, name="analysis")

        # Re-run lexical and canonical containment after provider I/O, then
        # compare full identity.  A provider call can take long enough for a
        # file to be replaced underneath an otherwise valid path.
        source = _validated_watched_source(self.config, source)
        after_analysis = capture_source_fingerprint(
            source, include_hash=include_source_hash
        )
        if not _same_fingerprint(before_analysis, after_analysis):
            raise AgentServiceError(
                "source_changed", f"file changed while it was being analyzed: {source}"
            )

        proposal_value = self.file_organizer.get_proposed_action(source, analysis)
        if not isinstance(proposal_value, Mapping):
            raise AgentServiceError("invalid_payload", "proposed action must be an object")
        proposal = _json_object(proposal_value, name="proposed action")
        return {
            "file_path": source,
            "analysis": analysis,
            "proposed_action": proposal,
            "source_fingerprint": after_analysis,
        }

    def _action_payload(self, action: PendingAction) -> Dict[str, Any]:
        payload = action.to_dict()
        containment_error: Optional[str] = None
        try:
            _validated_watched_source(self.config, action.file_path)
            within_watched_roots = True
        except (OSError, ValueError) as exc:
            within_watched_roots = False
            containment_error = str(exc)

        source_current = within_watched_roots and self.pending_queue.source_matches(action)
        payload["safety"] = {
            "within_watched_roots": within_watched_roots,
            "source_current": source_current,
            "filesystem_execution_available": False,
            "reason": containment_error,
        }
        return payload

    @staticmethod
    def _action_id(action_id: str) -> str:
        if not isinstance(action_id, str) or not action_id.strip():
            raise AgentServiceError("invalid_request", "action_id cannot be empty")
        if len(action_id) > 128:
            raise AgentServiceError("invalid_request", "action_id is too long")
        return action_id.strip()

    def status(self) -> AgentResponse:
        """Return configuration, watched-root, provider, and queue status."""

        operation = "status"
        try:
            watched_folders = []
            for folder in self.config.watched_folders:
                path = Path(folder.path).expanduser()
                watched_folders.append(
                    {
                        "path": str(path),
                        "enabled": folder.enabled,
                        "exists": path.is_dir(),
                        "recursive": folder.recursive,
                        "file_extensions": folder.file_extensions,
                    }
                )

            queue_counts = {
                state: len(self.pending_queue.list_actions([state]))
                for state in sorted(ACTION_STATES)
            }
            provider = self.config.ai_config.provider
            package_installed = (
                True
                if provider == "ollama"
                else importlib.util.find_spec(provider) is not None
            )
            credential_configured = (
                True
                if provider == "ollama"
                else bool(self.config.ai_config.resolved_api_key())
            )
            archive = Path(self.config.archive_config.base_path).expanduser()
            return _success(
                operation,
                {
                    "version": __version__,
                    "config_path": str(self.config_path),
                    "state_dir": str(self.state_dir),
                    "mode": self.config.mode,
                    "watched_folders": watched_folders,
                    "ai": {
                        "provider": provider,
                        "model": self.config.ai_config.model,
                        "package_installed": package_installed,
                        "credential_configured": credential_configured,
                        "ready": package_installed and credential_configured,
                    },
                    "archive": {
                        "path": str(archive),
                        "exists": archive.is_dir(),
                    },
                    "queue": queue_counts,
                    "guardrails": {
                        "human_approval_required": True,
                        "filesystem_execution_available": False,
                    },
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def doctor(self) -> AgentResponse:
        """Run local readiness checks and return machine-readable findings."""

        operation = "doctor"
        checks: List[Dict[str, str]] = []
        try:
            enabled = [folder for folder in self.config.watched_folders if folder.enabled]
            if not enabled:
                checks.append(
                    {"level": "ERROR", "name": "watch folders", "message": "none enabled"}
                )
            for folder in enabled:
                path = Path(folder.path).expanduser()
                checks.append(
                    {
                        "level": "OK" if path.is_dir() else "ERROR",
                        "name": "watch folder",
                        "message": str(path) if path.is_dir() else f"missing directory: {path}",
                    }
                )

            archive = Path(self.config.archive_config.base_path).expanduser()
            probe_path: Optional[Path] = None
            descriptor: Optional[int] = None
            try:
                archive.mkdir(parents=True, exist_ok=True)
                descriptor, probe_name = tempfile.mkstemp(
                    dir=str(archive), prefix=".watchdock-agent-doctor-", suffix=".tmp"
                )
                probe_path = Path(probe_name)
                os.write(descriptor, b"ok")
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = None
                probe_path.unlink()
                probe_path = None
                checks.append(
                    {"level": "OK", "name": "archive", "message": f"writable: {archive}"}
                )
            except OSError as exc:
                checks.append(
                    {"level": "ERROR", "name": "archive", "message": str(exc)}
                )
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if probe_path is not None:
                    try:
                        probe_path.unlink()
                    except FileNotFoundError:
                        pass

            provider = self.config.ai_config.provider
            if provider in {"openai", "anthropic"}:
                package_present = importlib.util.find_spec(provider) is not None
                fallback_level = "ERROR" if self.config.mode == "auto" else "WARN"
                checks.append(
                    {
                        "level": "OK" if package_present else fallback_level,
                        "name": "provider package",
                        "message": provider if package_present else f"install WatchDock[{provider}]",
                    }
                )
                credential_present = bool(self.config.ai_config.resolved_api_key())
                checks.append(
                    {
                        "level": "OK" if credential_present else fallback_level,
                        "name": "provider credential",
                        "message": (
                            "environment/config key found"
                            if credential_present
                            else "review-only rules fallback"
                        ),
                    }
                )
            else:
                checks.append(
                    {
                        "level": "OK",
                        "name": "provider endpoint",
                        "message": self.config.ai_config.base_url
                        or "http://localhost:11434/v1",
                    }
                )

            try:
                self.pending_queue.list_actions(limit=1)
                checks.append(
                    {
                        "level": "OK",
                        "name": "approval queue",
                        "message": str(self.pending_queue.db_path),
                    }
                )
            except (OSError, ValueError) as exc:
                checks.append(
                    {"level": "ERROR", "name": "approval queue", "message": str(exc)}
                )

            errors = sum(check["level"] == "ERROR" for check in checks)
            warnings = sum(check["level"] == "WARN" for check in checks)
            return _success(
                operation,
                {
                    "ready": errors == 0,
                    "errors": errors,
                    "warnings": warnings,
                    "checks": checks,
                    "side_effects": ["archive_write_probe"],
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def analyze_file(self, file_path: str) -> AgentResponse:
        """Analyze one watched file and propose an action without persisting or moving it."""

        operation = "analyze_file"
        try:
            prepared = self._prepare_proposal(file_path)
            return _success(
                operation,
                {
                    "dry_run": True,
                    "queued": False,
                    "side_effects": ["provider_analysis"],
                    "file_path": prepared["file_path"],
                    "analysis": prepared["analysis"],
                    "proposed_action": prepared["proposed_action"],
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def queue_file(self, file_path: str) -> AgentResponse:
        """Analyze and queue one watched file for a human; never move or rename it."""

        operation = "queue_file"
        try:
            prepared = self._prepare_proposal(file_path, include_source_hash=True)
            action, created = self.pending_queue.add_or_get_active(
                prepared["file_path"],
                prepared["analysis"],
                prepared["proposed_action"],
                source_fingerprint=prepared["source_fingerprint"],
            )
            return _success(
                operation,
                {
                    "queued": True,
                    "created": created,
                    "deduplicated": not created,
                    "already_queued": not created,
                    "source_file_mutated": False,
                    "side_effects": [
                        "provider_analysis",
                        "queue_database_write" if created else "queue_database_read",
                    ],
                    "human_approval_required": True,
                    "action": self._action_payload(action),
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def list_actions(
        self,
        statuses: Optional[Iterable[str]] = None,
        limit: int = 50,
    ) -> AgentResponse:
        """List durable actions, optionally filtered by lifecycle status."""

        operation = "list_actions"
        try:
            if isinstance(statuses, (str, bytes)):
                raise AgentServiceError("invalid_request", "statuses must be an array")
            normalized_statuses = (
                ["pending", "failed"] if statuses is None else list(statuses)
            )
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise AgentServiceError("invalid_request", "limit must be an integer")
            if not 1 <= limit <= 500:
                raise AgentServiceError("invalid_request", "limit must be between 1 and 500")
            actions = self.pending_queue.list_actions(normalized_statuses, limit=limit)
            return _success(
                operation,
                {
                    "count": len(actions),
                    "statuses": normalized_statuses,
                    "limit": limit,
                    "actions": [self._action_payload(action) for action in actions],
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def get_action(self, action_id: str) -> AgentResponse:
        """Return one durable action and its current source-safety assessment."""

        operation = "get_action"
        try:
            normalized_id = self._action_id(action_id)
            action = self.pending_queue.get_by_id(normalized_id)
            if action is None:
                raise AgentServiceError("action_not_found", f"action not found: {normalized_id}")
            return _success(operation, {"action": self._action_payload(action)})
        except Exception as exc:
            return self._error_response(operation, exc)

    def reject_action(self, action_id: str) -> AgentResponse:
        """Reject a pending or failed proposal without touching its source file."""

        operation = "reject_action"
        try:
            normalized_id = self._action_id(action_id)
            existing = self.pending_queue.get_by_id(normalized_id)
            if existing is None:
                raise AgentServiceError("action_not_found", f"action not found: {normalized_id}")
            if existing.status not in {"pending", "failed", "rejected"}:
                raise AgentServiceError(
                    "transition_not_allowed",
                    f"action cannot be rejected from status {existing.status}",
                )
            action = self.pending_queue.reject(normalized_id)
            if action is None:
                raise AgentServiceError(
                    "transition_conflict", "action state changed before it could be rejected"
                )
            return _success(
                operation,
                {
                    "source_file_mutated": False,
                    "side_effects": [
                        "queue_database_read"
                        if existing.status == "rejected"
                        else "queue_database_write"
                    ],
                    "action": self._action_payload(action),
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)

    def retry_action(self, action_id: str) -> AgentResponse:
        """Return a failed, still-current proposal to pending human review."""

        operation = "retry_action"
        try:
            normalized_id = self._action_id(action_id)
            existing = self.pending_queue.get_by_id(normalized_id)
            if existing is None:
                raise AgentServiceError("action_not_found", f"action not found: {normalized_id}")
            if existing.status != "failed":
                raise AgentServiceError(
                    "transition_not_allowed",
                    f"only failed actions can be retried (current status: {existing.status})",
                )
            _validated_watched_source(self.config, existing.file_path)
            if not self.pending_queue.source_matches(existing):
                raise AgentServiceError(
                    "source_changed",
                    "source no longer matches the reviewed fingerprint; re-analysis is required",
                )
            action = self.pending_queue.retry(normalized_id)
            if action is None:
                raise AgentServiceError(
                    "transition_conflict", "action state changed before it could be retried"
                )
            return _success(
                operation,
                {
                    "source_file_mutated": False,
                    "side_effects": ["queue_database_write"],
                    "human_approval_required": True,
                    "action": self._action_payload(action),
                },
            )
        except Exception as exc:
            return self._error_response(operation, exc)
