import asyncio
import builtins
import importlib
import sys
from pathlib import Path

import pytest

from watchdock.agent_service import AgentService
from watchdock.config import AIConfig, ArchiveConfig, WatchedFolder, WatchDockConfig


class StaticProcessor:
    def analyze_file(self, _file_path):
        return {
            "category": "Documents",
            "suggested_name": "agent-output.txt",
            "tags": ["agent"],
            "confidence": 0.9,
            "reasoning": "test fixture",
            "requires_review": True,
        }


def make_service(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    config = WatchDockConfig(
        watched_folders=[WatchedFolder(str(inbox))],
        ai_config=AIConfig(provider="ollama", model="test-model"),
        archive_config=ArchiveConfig(str(tmp_path / "archive")),
        mode="hitl",
    )
    config_path = tmp_path / "config.json"
    config.save(str(config_path))
    return AgentService(
        config,
        config_path=config_path,
        state_dir=tmp_path,
        ai_processor=StaticProcessor(),
    )


def test_module_import_is_mcp_optional_and_dependency_error_is_actionable(monkeypatch):
    real_import = builtins.__import__

    def deny_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("mcp intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_mcp)
    sys.modules.pop("watchdock.mcp_server", None)
    module = importlib.import_module("watchdock.mcp_server")

    # Base WatchDock imports succeed; MCP is requested only when a server is built.
    assert "MCPServer" not in vars(module)
    assert "ToolAnnotations" not in vars(module)
    with pytest.raises(RuntimeError, match="optional MCP dependency"):
        module._load_mcp_api()


def test_mcp_v2_inventory_is_exact_and_has_no_approval_tool(tmp_path):
    pytest.importorskip("mcp")
    from watchdock.mcp_server import MCP_TOOL_NAMES, create_server

    server = create_server(service=make_service(tmp_path))
    tools = asyncio.run(server.list_tools())
    by_name = {tool.name: tool for tool in tools}

    assert tuple(by_name) == MCP_TOOL_NAMES
    assert "approve" not in by_name
    assert "approve_action" not in by_name
    assert by_name["status"].annotations.read_only_hint is True
    assert by_name["doctor"].annotations.read_only_hint is False
    assert by_name["doctor"].annotations.destructive_hint is False
    assert by_name["doctor"].annotations.idempotent_hint is True
    assert by_name["analyze_file"].annotations.read_only_hint is False
    assert by_name["analyze_file"].annotations.destructive_hint is False
    assert by_name["analyze_file"].annotations.idempotent_hint is False
    assert by_name["analyze_file"].annotations.open_world_hint is True
    assert by_name["queue_file"].annotations.read_only_hint is False
    assert by_name["queue_file"].annotations.destructive_hint is False
    assert by_name["reject_action"].annotations.destructive_hint is True
    for tool in tools:
        assert tool.output_schema["type"] == "object"
        assert set(tool.output_schema["required"]) == {
            "ok",
            "operation",
            "data",
            "error",
        }


def test_mcp_tools_return_structured_content_and_queue_never_moves(tmp_path):
    pytest.importorskip("mcp")
    from watchdock.mcp_server import create_server

    service = make_service(tmp_path)
    server = create_server(service=service)
    status_result = asyncio.run(server.call_tool("status", {}))

    assert status_result.is_error is False
    assert status_result.structured_content["ok"] is True
    assert status_result.structured_content["operation"] == "status"
    assert status_result.structured_content["data"]["guardrails"][
        "filesystem_execution_available"
    ] is False

    source = tmp_path / "inbox" / "agent notes.txt"
    source.write_text("keep this in place", encoding="utf-8")
    queue_result = asyncio.run(
        server.call_tool("queue_file", {"file_path": str(source)})
    )

    assert queue_result.is_error is False
    payload = queue_result.structured_content
    assert payload["ok"] is True
    assert payload["data"]["queued"] is True
    assert payload["data"]["source_file_mutated"] is False
    assert payload["data"]["side_effects"] == [
        "provider_analysis",
        "queue_database_write",
    ]
    assert source.read_text(encoding="utf-8") == "keep this in place"
    destination = Path(payload["data"]["action"]["proposed_action"]["to"])
    assert not destination.exists()
    assert len(service.pending_queue.get_pending()) == 1


def test_mcp_outside_root_failure_stays_structured_and_non_mutating(tmp_path):
    pytest.importorskip("mcp")
    from watchdock.mcp_server import create_server

    server = create_server(service=make_service(tmp_path))
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    result = asyncio.run(
        server.call_tool("queue_file", {"file_path": str(outside)})
    )

    assert result.is_error is False
    assert result.structured_content["ok"] is False
    assert result.structured_content["error"]["code"] == "outside_watched_roots"
    assert outside.read_text(encoding="utf-8") == "outside"


def test_stdio_module_entry_round_trips_with_official_v2_client(tmp_path):
    pytest.importorskip("mcp")
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    service = make_service(tmp_path)

    async def exercise_server():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "watchdock.mcp_server",
                "--config",
                str(service.config_path),
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        async with Client(parameters) as client:
            listing = await client.list_tools()
            status = await client.call_tool("status", {})
            return listing, status

    listing, status = asyncio.run(exercise_server())

    assert {tool.name for tool in listing.tools} == {
        "status",
        "doctor",
        "analyze_file",
        "queue_file",
        "list_actions",
        "get_action",
        "reject_action",
        "retry_action",
    }
    assert status.is_error is False
    assert status.structured_content["data"]["config_path"] == str(
        service.config_path
    )


def test_main_forwards_config_and_uses_stdio_without_protocol_output(
    tmp_path, monkeypatch, capsys
):
    from watchdock import mcp_server

    config_path = tmp_path / "chosen.json"
    captured = {}

    class FakeServer:
        def run(self, *, transport):
            captured["transport"] = transport

    def fake_create_server(*, config_path):
        captured["config_path"] = config_path
        return FakeServer()

    monkeypatch.setattr(mcp_server, "create_server", fake_create_server)

    assert mcp_server.main(["--config", str(config_path)]) == 0
    assert captured == {"config_path": config_path, "transport": "stdio"}
    assert capsys.readouterr().out == ""
