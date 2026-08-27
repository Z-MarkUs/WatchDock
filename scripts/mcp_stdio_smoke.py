"""Exercise an installed/frozen WatchDock MCP server over real stdio."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_TOOLS = {
    "status",
    "doctor",
    "analyze_file",
    "queue_file",
    "list_actions",
    "get_action",
    "reject_action",
    "retry_action",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server-command",
        default=os.environ.get("WATCHDOCK_MCP_COMMAND", "watchdock-mcp"),
        help="installed watchdock-mcp entry point or frozen executable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="MCP handshake and operation timeout in seconds",
    )
    return parser


def _resolve_command(value: str) -> str:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(value)
    if resolved:
        return resolved
    raise FileNotFoundError(f"MCP server command not found: {value}")


def _write_config(root: Path) -> tuple[Path, Path, Path]:
    inbox = root / "inbox"
    archive = root / "archive"
    inbox.mkdir()
    archive.mkdir()
    config_path = root / "config.json"
    config = {
        "watched_folders": [
            {
                "path": str(inbox.resolve()),
                "enabled": True,
                "recursive": False,
                "file_extensions": [".txt"],
            }
        ],
        "ai_config": {
            "provider": "openai",
            "api_key": None,
            "model": "watchdock-mcp-smoke",
            "base_url": None,
            "temperature": 0,
        },
        "archive_config": {
            "base_path": str(archive.resolve()),
            "create_date_folders": True,
            "create_category_folders": True,
            "move_files": True,
        },
        "log_level": "WARNING",
        "check_interval": 1,
        "mode": "hitl",
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config_path, inbox, archive


def _structured(result: Any, operation: str) -> Mapping[str, Any]:
    if getattr(result, "is_error", True):
        raise AssertionError(f"{operation} returned an MCP error: {result}")
    payload = getattr(result, "structured_content", None)
    if not isinstance(payload, Mapping):
        raise AssertionError(f"{operation} did not return structured content")
    if payload.get("ok") is not True or payload.get("operation") != operation:
        raise AssertionError(f"{operation} returned an unexpected envelope: {payload}")
    return payload


async def _exercise(command: str, timeout_seconds: float, root: Path) -> None:
    try:
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError("the smoke client requires WatchDock's 'mcp' extra") from exc

    config_path, inbox, archive = _write_config(root)
    source = inbox / "agent-smoke.txt"
    source_payload = b"WatchDock MCP smoke source: this file must stay in place.\n"
    source.write_bytes(source_payload)
    source_path = source.resolve()
    source_digest = hashlib.sha256(source_payload).hexdigest()

    server_environment = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "OPENAI_API_KEY",
        "WATCHDOCK_OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "WATCHDOCK_ANTHROPIC_API_KEY",
    ):
        server_environment.pop(name, None)

    parameters = StdioServerParameters(
        command=command,
        args=["--config", str(config_path)],
        cwd=root,
        env=server_environment,
    )
    async with Client(
        parameters,
        raise_exceptions=True,
        read_timeout_seconds=timeout_seconds,
    ) as client:
        server_info = client.server_info
        if server_info is None or getattr(server_info, "name", None) != "watchdock":
            raise AssertionError(f"MCP initialization handshake failed: {server_info}")
        listing = await asyncio.wait_for(client.list_tools(), timeout=timeout_seconds)
        tool_names = {tool.name for tool in listing.tools}
        if tool_names != EXPECTED_TOOLS:
            raise AssertionError(
                f"unexpected MCP tool inventory: expected {sorted(EXPECTED_TOOLS)}, "
                f"found {sorted(tool_names)}"
            )

        status_result = await asyncio.wait_for(
            client.call_tool("status", {}), timeout=timeout_seconds
        )
        status = _structured(status_result, "status")
        status_data = status.get("data")
        if not isinstance(status_data, Mapping):
            raise AssertionError("status data is missing")
        if Path(str(status_data.get("config_path"))).resolve() != config_path.resolve():
            raise AssertionError("server did not load the isolated smoke configuration")

        queue_result = await asyncio.wait_for(
            client.call_tool("queue_file", {"file_path": str(source_path)}),
            timeout=timeout_seconds,
        )
        queued = _structured(queue_result, "queue_file")

    queue_data = queued.get("data")
    if not isinstance(queue_data, Mapping) or queue_data.get("queued") is not True:
        raise AssertionError(f"queue_file did not create a review proposal: {queued}")
    if queue_data.get("source_file_mutated") is not False:
        raise AssertionError("queue_file did not affirm the source was left untouched")
    if not source.is_file() or source.resolve() != source_path:
        raise AssertionError("queue_file moved or removed the source")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_digest:
        raise AssertionError("queue_file changed the source bytes")

    action = queue_data.get("action")
    if not isinstance(action, Mapping):
        raise AssertionError("queue_file response omitted the action")
    proposal = action.get("proposed_action")
    if not isinstance(proposal, Mapping) or not proposal.get("to"):
        raise AssertionError("queue_file response omitted the proposed destination")
    proposed_destination = Path(str(proposal["to"]))
    if proposed_destination.exists():
        raise AssertionError("queue_file created the proposed destination")
    if any(path.is_file() for path in archive.rglob("*")):
        raise AssertionError("queue_file wrote an archive file before human approval")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = _resolve_command(args.server_command)
    with tempfile.TemporaryDirectory(prefix="watchdock-mcp-stdio-") as temporary:
        root = Path(temporary).resolve()
        asyncio.run(_exercise(command, args.timeout, root))
    print(f"MCP stdio smoke passed: {command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
