"""Optional local MCP v2 server for WatchDock's review-first agent API."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, List, Optional, Sequence

from watchdock import __version__
from watchdock.agent_service import AgentResponse, AgentService
from watchdock.paths import default_config_path


MCP_TOOL_NAMES = (
    "status",
    "doctor",
    "analyze_file",
    "queue_file",
    "list_actions",
    "get_action",
    "reject_action",
    "retry_action",
)


def _load_mcp_api() -> tuple[Any, Any]:
    """Import MCP only when the optional server is actually requested."""

    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "WatchDock's MCP server requires the optional MCP dependency; "
            "install WatchDock with its 'mcp' extra. "
            f"Import failed with {type(exc).__name__}: {exc}"
        ) from exc
    return MCPServer, ToolAnnotations


def create_server(
    *,
    service: Optional[AgentService] = None,
    config_path: Optional[Path] = None,
) -> Any:
    """Build an MCP v2 server with no approval or filesystem-execution tool."""

    MCPServer, ToolAnnotations = _load_mcp_api()
    agent = service or AgentService.from_config_path(config_path)
    server = MCPServer(
        "watchdock",
        title="WatchDock Agent Gateway",
        description="Review-first file analysis and organization queue",
        instructions=(
            "Analyze or queue files only inside configured watched roots. "
            "Queued actions require a human to approve them in WatchDock. "
            "This server cannot approve, move, rename, or delete files."
        ),
        version=__version__,
    )

    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    doctor_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
    # A dry-run does not mutate local files, but it can make a billable network
    # request to an open-world provider and may return nondeterministic output.
    analysis_only = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    queue_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
    reject_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )
    retry_write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(
        title="WatchDock status",
        annotations=read_only,
        structured_output=True,
    )
    def status() -> AgentResponse:
        """Inspect WatchDock configuration, watched roots, provider, and queue counts."""

        return agent.status()

    @server.tool(
        title="Check WatchDock readiness",
        annotations=doctor_write,
        structured_output=True,
    )
    def doctor() -> AgentResponse:
        """Run readiness checks for watched roots, archive, provider, and queue."""

        return agent.doctor()

    @server.tool(
        title="Analyze a watched file",
        annotations=analysis_only,
        structured_output=True,
    )
    def analyze_file(file_path: str) -> AgentResponse:
        """Dry-run analysis for one watched file; do not persist or change the file."""

        return agent.analyze_file(file_path)

    @server.tool(
        title="Queue a file for human review",
        annotations=queue_write,
        structured_output=True,
    )
    def queue_file(file_path: str) -> AgentResponse:
        """Analyze and queue one watched file; never move or rename it."""

        return agent.queue_file(file_path)

    @server.tool(
        title="List WatchDock actions",
        annotations=read_only,
        structured_output=True,
    )
    def list_actions(
        statuses: Optional[List[str]] = None,
        limit: int = 50,
    ) -> AgentResponse:
        """List reviewable pending/failed actions, or filter by lifecycle status."""

        return agent.list_actions(statuses=statuses, limit=limit)

    @server.tool(
        title="Get a WatchDock action",
        annotations=read_only,
        structured_output=True,
    )
    def get_action(action_id: str) -> AgentResponse:
        """Get one action with its current source and watched-root safety state."""

        return agent.get_action(action_id)

    @server.tool(
        title="Reject a WatchDock action",
        annotations=reject_write,
        structured_output=True,
    )
    def reject_action(action_id: str) -> AgentResponse:
        """Reject a pending or failed proposal without changing its source file."""

        return agent.reject_action(action_id)

    @server.tool(
        title="Retry a failed WatchDock action",
        annotations=retry_write,
        structured_output=True,
    )
    def retry_action(action_id: str) -> AgentResponse:
        """Return a failed, unchanged proposal to pending human review."""

        return agent.retry_action(action_id)

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="watchdock-mcp",
        description="Run WatchDock's local, review-first MCP server over stdio.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        help="path to an existing WatchDock JSON configuration",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the local MCP server; stdout is reserved for the stdio protocol."""

    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        server = create_server(config_path=args.config)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"watchdock-mcp: error: {exc}\n")
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the entry point
    raise SystemExit(main())
