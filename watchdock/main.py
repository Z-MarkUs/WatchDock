"""WatchDock application service and command-line interface."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from packaging import version as packaging_version

from watchdock import __version__
from watchdock.ai_processor import AIProcessor
from watchdock.config import WatchDockConfig
from watchdock.file_organizer import FileOrganizer
from watchdock.logging_utils import configure_logging, prepare_console
from watchdock.paths import default_config_path
from watchdock.pending_actions import (
    PendingAction,
    PendingActionsQueue,
    capture_source_fingerprint,
)
from watchdock.watcher import FileWatcher

logger = logging.getLogger(__name__)

DEFAULT_STALE_PROCESSING_SECONDS = 24 * 60 * 60


def _path_is_within(path: Path, root: Path) -> bool:
    """Return whether two absolute paths have a containment relationship."""

    try:
        return os.path.commonpath(
            (os.path.normcase(str(path)), os.path.normcase(str(root)))
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _validated_watched_source(config: WatchDockConfig, file_path: str) -> str:
    """Reject event paths that lexically or canonically escape watch roots."""

    source = Path(file_path).expanduser().absolute()
    resolved_source = source.resolve(strict=True)
    for folder in config.watched_folders:
        if not folder.enabled:
            continue
        lexical_root = Path(folder.path).expanduser().absolute()
        try:
            resolved_root = lexical_root.resolve(strict=True)
        except FileNotFoundError:
            continue
        if _path_is_within(source, lexical_root) and _path_is_within(
            resolved_source, resolved_root
        ):
            return str(source)
    raise ValueError(f"file resolves outside configured watched folders: {source}")


def _same_fingerprint(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    return (
        first.get("device"),
        first.get("inode"),
        first.get("size"),
        first.get("mtime_ns"),
    ) == (
        second.get("device"),
        second.get("inode"),
        second.get("size"),
        second.get("mtime_ns"),
    )


class WatchDock:
    """Coordinate analysis, review, organization, and folder monitoring."""

    def __init__(
        self,
        config: WatchDockConfig,
        *,
        state_dir: Optional[Path] = None,
        ai_processor: Optional[AIProcessor] = None,
        file_organizer: Optional[FileOrganizer] = None,
        pending_queue: Optional[PendingActionsQueue] = None,
        stale_processing_seconds: float = DEFAULT_STALE_PROCESSING_SECONDS,
    ) -> None:
        config.validate()
        self.config = config
        self.state_dir = (state_dir or default_config_path().parent).expanduser()
        self.ai_processor = ai_processor or AIProcessor(
            config.ai_config,
            examples_path=self.state_dir / "few_shot_examples.json",
        )
        self.file_organizer = file_organizer or FileOrganizer(config.archive_config)
        self.pending_queue = pending_queue or PendingActionsQueue(
            db_path=self.state_dir / "pending_actions.sqlite3"
        )
        if stale_processing_seconds < 0:
            raise ValueError("stale_processing_seconds cannot be negative")
        self.stale_processing_seconds = float(stale_processing_seconds)
        self.watcher: Optional[FileWatcher] = None
        self.running = False

    def process_file(self, file_path: str) -> None:
        """Analyze one file and either queue or safely execute its action."""

        source = _validated_watched_source(self.config, file_path)
        if self.file_organizer.is_managed_path(source):
            logger.debug("Ignoring file already managed by archive: %s", file_path)
            return

        logger.info("Analyzing file: %s", source)
        before_analysis = capture_source_fingerprint(source)
        analysis = self.ai_processor.analyze_file(source)
        source = _validated_watched_source(self.config, source)
        after_analysis = capture_source_fingerprint(source)
        if not _same_fingerprint(before_analysis, after_analysis):
            raise RuntimeError(f"file changed while it was being analyzed: {source}")
        proposal = self.file_organizer.get_proposed_action(source, analysis)
        needs_review = self.config.mode == "hitl" or bool(
            analysis.get("requires_review", False)
        )

        if needs_review:
            source = _validated_watched_source(self.config, source)
            action = self.pending_queue.add(
                source,
                analysis,
                proposal,
                source_fingerprint=after_analysis,
            )
            if self.config.mode == "auto":
                logger.warning(
                    "Provider result requires review; source was not moved: %s",
                    source,
                )
            self._notify_pending_action(action)
            return

        source = _validated_watched_source(self.config, source)
        before_organize = capture_source_fingerprint(source)
        if not _same_fingerprint(after_analysis, before_organize):
            raise RuntimeError(f"file changed after it was analyzed: {source}")
        result = self.file_organizer.organize_file(source, analysis)
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        logger.info("Organization result: %s", result)

    @staticmethod
    def _notify_pending_action(action: PendingAction) -> None:
        """Send a best-effort desktop notification without invoking a shell."""

        filename = Path(action.file_path).name
        try:
            system = platform.system()
            if system == "Darwin" and shutil.which("osascript"):
                script = (
                    "on run argv\n"
                    'display notification (item 1 of argv) with title "WatchDock"\n'
                    "end run"
                )
                subprocess.run(
                    ["osascript", "-e", script, "--", filename],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            elif system == "Linux" and shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", "WatchDock", f"Review action for: {filename}"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
        except OSError as exc:
            logger.debug("Could not send desktop notification: %s", exc)

        print(f"[REVIEW] {action.file_path}")
        print(f"  Category: {action.analysis.get('category', 'Unknown')}")
        print(f"  Destination: {action.proposed_action.get('to', 'N/A')}")
        print(f"  Action ID: {action.action_id}")
        print(f"  Approve: watchdock approve {action.action_id}")
        print(f"  Reject:  watchdock reject {action.action_id}")

    def start(self) -> None:
        """Start monitoring and block until stopped."""

        if self.running:
            return
        recovered = self.pending_queue.fail_stale_processing(
            self.stale_processing_seconds
        )
        if recovered:
            logger.warning(
                "Marked %s stale processing action(s) failed for reconciliation",
                len(recovered),
            )
        self.watcher = FileWatcher(
            self.config.watched_folders,
            self.process_file,
            check_interval=self.config.check_interval,
            excluded_roots=[self.config.archive_config.base_path],
        )
        if not self.watcher.start():
            raise RuntimeError("no enabled, existing watched folders are available")

        self.running = True
        logger.info("WatchDock is running. Press Ctrl+C to stop.")
        try:
            while self.running and self.watcher.is_alive():
                time.sleep(0.25)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop monitoring; repeated calls are safe."""

        self.running = False
        if self.watcher:
            self.watcher.stop()
        logger.info("WatchDock stopped")


def _check_pypi_version() -> Tuple[Optional[str], Optional[str]]:
    """Return the latest PyPI version and an optional error message."""

    try:
        request = urllib.request.Request(
            "https://pypi.org/pypi/watchdock/json",
            headers={"User-Agent": f"WatchDock/{__version__}"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read())
        return str(data["info"]["version"]), None
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return None, str(exc)


def cmd_version(args: argparse.Namespace) -> int:
    print(f"WatchDock {__version__}")
    if not getattr(args, "check", False):
        return 0

    latest_version, error = _check_pypi_version()
    if error:
        print(f"[WARN] Could not check PyPI: {error}")
        return 0
    if latest_version and packaging_version.parse(
        latest_version
    ) > packaging_version.parse(__version__):
        print(f"[UPDATE] {latest_version} is available")
    else:
        print("[OK] Installed version is current")
    return 0


def cmd_update(_args: argparse.Namespace) -> int:
    if getattr(sys, "frozen", False):
        print("[ERROR] Self-update is unavailable in a standalone executable.")
        print(
            "Download the latest release from https://github.com/Z-MarkUs/WatchDock/releases"
        )
        return 1

    latest_version, error = _check_pypi_version()
    if error or not latest_version:
        print(f"[ERROR] Could not check PyPI: {error or 'unknown response'}")
        return 1
    if packaging_version.parse(latest_version) <= packaging_version.parse(__version__):
        print(f"[OK] WatchDock {__version__} is current")
        return 0

    print(f"Updating WatchDock {__version__} -> {latest_version}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"watchdock=={latest_version}",
        ],
        check=False,
    )
    if result.returncode:
        print("[ERROR] Update failed. Run: python -m pip install -U watchdock")
        return 1
    print("[OK] Update installed")
    return 0


def _config_path(args: argparse.Namespace) -> Path:
    return Path(args.config).expanduser()


def _state_dir(args: argparse.Namespace) -> Path:
    return _config_path(args).parent


def _queue_for_args(args: argparse.Namespace) -> PendingActionsQueue:
    return PendingActionsQueue(db_path=_state_dir(args) / "pending_actions.sqlite3")


def _load_existing_config(args: argparse.Namespace) -> WatchDockConfig:
    path = _config_path(args)
    if not path.exists():
        raise FileNotFoundError(
            f"configuration not found: {path} (run 'watchdock config init')"
        )
    return WatchDockConfig.load(str(path))


def cmd_config_init(args: argparse.Namespace) -> int:
    path = _config_path(args)
    if path.exists() and not args.force:
        print(f"[ERROR] Configuration already exists: {path}")
        print("Use --force only if you intend to replace it.")
        return 1

    WatchDockConfig.default().save(str(path))
    print(f"[OK] Created review-first configuration: {path}")
    print("Set a provider API key through an environment variable or configure Ollama.")
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    config = _load_existing_config(args)
    config.validate()
    print(f"[OK] Configuration is valid: {_config_path(args)}")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    data = _load_existing_config(args).to_dict()
    if data["ai_config"].get("api_key"):
        data["ai_config"]["api_key"] = "***configured***"
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def _status_payload(args: argparse.Namespace) -> Dict[str, Any]:
    config = _load_existing_config(args)
    queue = _queue_for_args(args)
    folder_status = []
    for folder in config.watched_folders:
        path = Path(folder.path)
        folder_status.append(
            {
                "path": str(path),
                "enabled": folder.enabled,
                "exists": path.is_dir(),
                "recursive": folder.recursive,
                "file_extensions": folder.file_extensions,
            }
        )

    queue_counts = {
        status: len(queue.list_actions([status]))
        for status in ("pending", "processing", "failed", "completed", "rejected")
    }
    if config.ai_config.provider in {"openai", "anthropic"}:
        provider_ready = bool(config.ai_config.resolved_api_key())
    else:
        provider_ready = True

    return {
        "version": __version__,
        "config_path": str(_config_path(args)),
        "mode": config.mode,
        "watched_folders": folder_status,
        "ai": {
            "provider": config.ai_config.provider,
            "model": config.ai_config.model,
            "configured": provider_ready,
        },
        "archive_path": config.archive_config.base_path,
        "queue": queue_counts,
    }


def cmd_status(args: argparse.Namespace) -> int:
    payload = _status_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"WatchDock {payload['version']}")
    print(f"  Config:  {payload['config_path']}")
    print(f"  Mode:    {payload['mode'].upper()}")
    print(
        f"  AI:      {payload['ai']['provider']} / {payload['ai']['model']} "
        f"({'ready' if payload['ai']['configured'] else 'review-only fallback'})"
    )
    print(f"  Archive: {payload['archive_path']}")
    print("  Watched folders:")
    for folder in payload["watched_folders"]:
        marker = "OK" if folder["enabled"] and folder["exists"] else "MISSING"
        if not folder["enabled"]:
            marker = "DISABLED"
        print(f"    [{marker}] {folder['path']}")
    print(
        "  Queue:   "
        + ", ".join(f"{key}={value}" for key, value in payload["queue"].items())
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = _load_existing_config(args)
    checks: List[Tuple[str, str, str]] = []

    enabled_folders = [folder for folder in config.watched_folders if folder.enabled]
    if not enabled_folders:
        checks.append(("ERROR", "watch folders", "no folders are enabled"))
    for folder in enabled_folders:
        path = Path(folder.path)
        level = "OK" if path.is_dir() else "ERROR"
        message = str(path) if path.is_dir() else f"missing directory: {path}"
        checks.append((level, "watch folder", message))

    archive = Path(config.archive_config.base_path)
    try:
        archive.mkdir(parents=True, exist_ok=True)
        probe = archive / ".watchdock-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        checks.append(("OK", "archive", f"writable: {archive}"))
    except OSError as exc:
        checks.append(("ERROR", "archive", str(exc)))

    provider = config.ai_config.provider
    if provider in {"openai", "anthropic"}:
        module_name = provider
        if importlib.util.find_spec(module_name) is None:
            level = "ERROR" if config.mode == "auto" else "WARN"
            checks.append(
                (
                    level,
                    "provider package",
                    f"install WatchDock[{provider}] (review-only rules fallback)",
                )
            )
        else:
            checks.append(("OK", "provider package", module_name))
        if config.ai_config.resolved_api_key():
            checks.append(("OK", "provider credential", "environment/config key found"))
        else:
            level = "ERROR" if config.mode == "auto" else "WARN"
            checks.append((level, "provider credential", "review-only rules fallback"))
    else:
        checks.append(
            (
                "OK",
                "provider endpoint",
                config.ai_config.base_url or "http://localhost:11434/v1",
            )
        )

    try:
        queue = _queue_for_args(args)
        queue.list_actions(limit=1)
        checks.append(("OK", "approval queue", str(queue.db_path)))
    except (OSError, ValueError) as exc:
        checks.append(("ERROR", "approval queue", str(exc)))

    for level, name, message in checks:
        print(f"[{level}] {name}: {message}")
    errors = sum(1 for level, _name, _message in checks if level == "ERROR")
    warnings = sum(1 for level, _name, _message in checks if level == "WARN")
    print(f"Doctor result: {errors} error(s), {warnings} warning(s)")
    return 1 if errors else 0


def _print_action(action: PendingAction) -> None:
    print(f"  ID:          {action.action_id}")
    print(f"  Status:      {action.status}")
    print(f"  Source:      {action.file_path}")
    print(f"  Destination: {action.proposed_action.get('to', 'N/A')}")
    print(f"  Category:    {action.analysis.get('category', 'Unknown')}")
    if action.error:
        print(f"  Error:       {action.error}")


def cmd_list_pending(args: argparse.Namespace) -> int:
    queue = _queue_for_args(args)
    statuses = None if args.all else ["pending", "failed"]
    actions = queue.list_actions(statuses)
    if not actions:
        print("No reviewable actions.")
        return 0
    print(f"Reviewable actions ({len(actions)}):")
    for action in actions:
        _print_action(action)
        print()
    return 0


def _execute_claimed_action(
    config: WatchDockConfig,
    queue: PendingActionsQueue,
    action: PendingAction,
) -> Tuple[bool, Dict[str, Any]]:
    if not queue.source_matches(action):
        error = "source changed after review; re-analysis is required"
        queue.fail(action.action_id, error)
        return False, {"error": error}

    try:
        organizer = FileOrganizer(config.archive_config)
        result = organizer.execute_proposed_action(action.proposed_action)
    except Exception as exc:
        queue.fail(action.action_id, str(exc))
        return False, {"error": str(exc)}
    if result.get("error"):
        queue.fail(action.action_id, str(result["error"]))
        return False, result
    completed = queue.complete(action.action_id)
    if completed is None:
        error = (
            "filesystem action completed but the processing claim changed; "
            "manual queue reconciliation is required"
        )
        return False, {**result, "error": error}
    return True, result


def cmd_approve(args: argparse.Namespace) -> int:
    config = _load_existing_config(args)
    configure_logging(config.log_level, _state_dir(args) / "logs" / "watchdock.log")
    queue = _queue_for_args(args)
    action = queue.claim(args.action_id, worker_id="cli")
    if action is None:
        existing = queue.get_by_id(args.action_id)
        status = existing.status if existing else "not found"
        print(f"[ERROR] Action is not claimable ({status}): {args.action_id}")
        return 1

    success, result = _execute_claimed_action(config, queue, action)
    if not success:
        current = queue.get_by_id(action.action_id)
        status = current.status if current else "missing"
        print(f"[ERROR] Action was not completed cleanly ({status}): {result['error']}")
        return 1
    print(f"[OK] Completed action: {action.action_id}")
    print(f"  Destination: {result['new_path']}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    action = _queue_for_args(args).reject(args.action_id)
    if action is None:
        print(f"[ERROR] Action is not rejectable: {args.action_id}")
        return 1
    print(f"[OK] Rejected action: {action.action_id}")
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    action = _queue_for_args(args).retry(args.action_id)
    if action is None:
        print(f"[ERROR] Only failed actions can be retried: {args.action_id}")
        return 1
    print(f"[OK] Returned action to pending: {action.action_id}")
    return 0


def cmd_recover_stale(args: argparse.Namespace) -> int:
    """Fail expired claims so their uncertain outcome can be reconciled."""

    recovered = _queue_for_args(args).fail_stale_processing(args.older_than)
    if not recovered:
        print("No stale processing actions found.")
        return 0
    print(f"Recovered stale processing actions ({len(recovered)}):")
    for action in recovered:
        print(f"  {action.action_id}: {action.file_path}")
    print("Review each failed action before retrying; execution may have occurred.")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    config = _load_existing_config(args)
    state_dir = _state_dir(args)
    processor = AIProcessor(
        config.ai_config, examples_path=state_dir / "few_shot_examples.json"
    )
    organizer = FileOrganizer(config.archive_config)
    source = str(Path(args.file).expanduser().absolute())
    before_analysis = capture_source_fingerprint(source)
    analysis = processor.analyze_file(source)
    after_analysis = capture_source_fingerprint(source)
    if not _same_fingerprint(before_analysis, after_analysis):
        print(f"[ERROR] File changed while it was being analyzed: {source}")
        return 1
    proposal = organizer.get_proposed_action(source, analysis)

    print(
        json.dumps(
            {"analysis": analysis, "proposal": proposal}, indent=2, ensure_ascii=False
        )
    )
    if args.queue:
        action = _queue_for_args(args).add(source, analysis, proposal)
        print(f"[REVIEW] Queued as {action.action_id}")
        return 0
    if not args.apply:
        print(
            "Dry run only. Use --queue for review or --apply for a high-confidence result."
        )
        return 0
    if analysis.get("requires_review"):
        print(
            "[ERROR] Low-confidence/fallback analysis cannot be applied automatically."
        )
        return 1

    result = organizer.organize_file(source, analysis)
    if result.get("error"):
        print(f"[ERROR] {result['error']}")
        return 1
    print(f"[OK] Organized file at {result['new_path']}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    config = _load_existing_config(args)
    configure_logging(config.log_level, _state_dir(args) / "logs" / "watchdock.log")
    service = WatchDock(config, state_dir=_state_dir(args))

    def signal_handler(_signal_number: int, _frame: Any) -> None:
        service.stop()

    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    except ValueError:
        logger.debug("Signal handlers are only available in the main thread")

    service.start()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    config_path = _config_path(args)
    if config_path.exists():
        config = WatchDockConfig.load(str(config_path))
        configure_logging(
            config.log_level, config_path.parent / "logs" / "watchdock.log"
        )
    try:
        from watchdock.gui import run_gui

        run_gui(config_path=str(config_path))
    except ImportError as exc:
        print(f"[ERROR] GUI requires tkinter: {exc}")
        return 1
    return 0


def _cmd_help(args: argparse.Namespace) -> int:
    args.help_parser.print_help()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watchdock",
        description="Safely analyze and organize watched files",
    )
    parser.add_argument(
        "--config",
        default=str(default_config_path()),
        help="configuration path (accepted before or after a subcommand)",
    )
    parser.add_argument(
        "--version", action="version", version=f"WatchDock {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", title="commands")

    version_parser = subparsers.add_parser("version", help="show installed version")
    version_parser.add_argument("--check", action="store_true", help="check PyPI")
    version_parser.set_defaults(func=cmd_version)

    subparsers.add_parser("update", help="update a pip installation").set_defaults(
        func=cmd_update
    )

    status_parser = subparsers.add_parser("status", help="show configuration status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    doctor_parser = subparsers.add_parser("doctor", help="run readiness checks")
    doctor_parser.set_defaults(func=cmd_doctor)

    config_parser = subparsers.add_parser("config", help="manage configuration")
    config_parser.set_defaults(func=_cmd_help, help_parser=config_parser)
    config_subparsers = config_parser.add_subparsers(dest="config_command")
    init_parser = config_subparsers.add_parser("init", help="create safe defaults")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_config_init)
    config_subparsers.add_parser(
        "validate", help="validate JSON and values"
    ).set_defaults(func=cmd_config_validate)
    config_subparsers.add_parser(
        "show", help="show redacted configuration"
    ).set_defaults(func=cmd_config_show)

    subparsers.add_parser("gui", help="launch the desktop application").set_defaults(
        func=cmd_gui
    )
    subparsers.add_parser("start", help="start foreground monitoring").set_defaults(
        func=cmd_start
    )

    process_parser = subparsers.add_parser(
        "process", help="analyze one file (dry run by default)"
    )
    process_parser.add_argument("file")
    process_choice = process_parser.add_mutually_exclusive_group()
    process_choice.add_argument("--queue", action="store_true")
    process_choice.add_argument("--apply", action="store_true")
    process_parser.set_defaults(func=cmd_process)

    list_parser = subparsers.add_parser(
        "list-pending", help="list pending and failed review actions"
    )
    list_parser.add_argument("--all", action="store_true")
    list_parser.set_defaults(func=cmd_list_pending)

    approve_parser = subparsers.add_parser("approve", help="execute a reviewed action")
    approve_parser.add_argument("action_id")
    approve_parser.set_defaults(func=cmd_approve)

    reject_parser = subparsers.add_parser("reject", help="reject a review action")
    reject_parser.add_argument("action_id")
    reject_parser.set_defaults(func=cmd_reject)

    retry_parser = subparsers.add_parser("retry", help="retry a failed review action")
    retry_parser.add_argument("action_id")
    retry_parser.set_defaults(func=cmd_retry)

    recover_parser = subparsers.add_parser(
        "recover-stale",
        help="mark expired processing claims failed for manual reconciliation",
    )
    recover_parser.add_argument(
        "--older-than",
        type=float,
        default=DEFAULT_STALE_PROCESSING_SECONDS,
        metavar="SECONDS",
        help=f"claim age threshold (default: {DEFAULT_STALE_PROCESSING_SECONDS})",
    )
    recover_parser.set_defaults(func=cmd_recover_stale)

    parser.set_defaults(func=_cmd_help, help_parser=parser)
    return parser


def _normalize_global_config(argv: Sequence[str]) -> List[str]:
    """Allow ``--config`` before or after subcommands for normal CLI ergonomics."""

    values = list(argv)
    for index, value in enumerate(values):
        if value == "--config" and index + 1 < len(values):
            config_value = values[index + 1]
            return ["--config", config_value] + values[:index] + values[index + 2 :]
        if value.startswith("--config="):
            return [value] + values[:index] + values[index + 1 :]
    return values


def main(argv: Optional[Sequence[str]] = None) -> int:
    prepare_console()
    parser = build_parser()
    normalized = _normalize_global_config(
        list(argv) if argv is not None else sys.argv[1:]
    )
    args = parser.parse_args(normalized)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("[WARN] Interrupted")
        return 130
    except Exception as exc:
        logger.debug("Command failed", exc_info=True)
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
