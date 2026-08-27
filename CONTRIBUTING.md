# Contributing

Contributions are welcome. Keep safety-sensitive file operations small,
reviewable, and covered by tests.

## Development setup

WatchDock supports Python 3.10 and newer. On Windows PowerShell:

```powershell
git clone https://github.com/Z-MarkUs/watchdock.git
cd watchdock
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The `dev` extra includes the optional MCP SDK. Install `.[dev,ai]` when testing
both optional provider adapters. Automated tests must not make live provider
requests or depend on real API keys.

## Checks

Run the same core checks used by CI:

```powershell
python -m ruff check watchdock scripts tests
python -m pytest
```

For agent-boundary changes, run the focused service, protocol, and queue suite
before the full suite:

```powershell
python -m pytest `
  tests/test_agent_service.py `
  tests/test_mcp_server.py `
  tests/test_pending_actions.py
```

Keep the MCP tool-effects table in `docs/AGENT_INTEGRATION.md` synchronized with
tool annotations and returned `side_effects` fields. A new approval or
filesystem-execution MCP tool is an architecture change, not a routine tool
addition.

Validate and package the portable plugin bundle when its manifests, skills,
assets, or MCP inventory change:

```powershell
python scripts/validate_agent_distribution.py
python scripts/package_agent_plugin.py --output-dir agent-dist
```

The archive validator enforces the exact file inventory and rejects unexpected
hooks, commands, scripts, agents, binaries, or other execution surfaces inside
the plugin bundle.

For packaging changes, also build and inspect both distributions:

```powershell
python -m pip install -e ".[release]"
python -m build
$Artifacts = Get-ChildItem dist\*
$Wheels = Get-ChildItem dist\*.whl
python -m twine check $Artifacts.FullName
check-wheel-contents $Wheels.FullName
```

Use a fresh virtual environment for a final wheel install and run the CLI and
MCP entry points outside the repository directory. Adjust paths in this example
to the repository's absolute path:

```powershell
python -m venv .wheel-smoke
$Wheel = (Get-ChildItem dist\watchdock-*.whl | Select-Object -First 1).FullName
.\.wheel-smoke\Scripts\python.exe -m pip install "$Wheel`[mcp`]"
$WatchDockCli = (Resolve-Path .\.wheel-smoke\Scripts\watchdock.exe).Path
$WatchDockMcp = (Resolve-Path .\.wheel-smoke\Scripts\watchdock-mcp.exe).Path
Push-Location $env:TEMP
& $WatchDockCli --help
& $WatchDockMcp --help
Pop-Location
```

Before a public agent-integration claim, also complete the clean Codex and
Claude Code acceptance checklists in `docs/AGENT_EVALS.md`. Static manifest
validation is necessary but does not substitute for a real queue and external
approval flow.

Do not commit generated `dist`, `build`, virtual-environment, database, log, or
sidecar files.

## Change guidelines

- Preserve the default `hitl` behavior and the rule that fallback analysis cannot
  move a file automatically.
- Treat watched-file content and provider output as untrusted.
- Keep proposals free of filesystem side effects; apply an action only in the
  organizer after the relevant review decision.
- Keep the agent service free of approval and source-file execution methods.
  Queue/database state and the documented doctor probe are allowed only when
  accurately represented in MCP annotations and documentation.
- Treat tool arguments, absolute paths, action history, and responses returned
  to agent clients as potentially remote-visible data.
- Add tests for Windows paths, name conflicts, path traversal, changed queued
  sources, concurrent claims, and failure/retry behavior when those areas change.
- Keep `pyproject.toml` authoritative for package metadata and dependencies.
- Add user-visible work under the `Unreleased` heading in `CHANGELOG.md`; release
  automation owns the eventual version/tag alignment.

Before opening a pull request, include a concise risk note for changes that touch
file movement, credentials, provider data, queue transitions, or release logic.
