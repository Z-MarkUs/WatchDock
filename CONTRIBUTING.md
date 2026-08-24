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

Install `.[dev,ai]` when testing both optional provider adapters. Tests must not
make live provider requests or depend on real API keys.

## Checks

Run the same core checks used by CI:

```powershell
python -m ruff check watchdock tests
python -m pytest
```

For packaging changes, also build and inspect both distributions:

```powershell
python -m pip install -e ".[release]"
python -m build
$Artifacts = Get-ChildItem dist\*
$Wheels = Get-ChildItem dist\*.whl
python -m twine check $Artifacts.FullName
check-wheel-contents $Wheels.FullName
```

Use a fresh virtual environment for a final wheel install and run both entry
points outside the repository directory. Adjust the executable path in this
example to the repository's absolute path:

```powershell
python -m venv .wheel-smoke
$Wheel = (Get-ChildItem dist\watchdock-*.whl | Select-Object -First 1).FullName
.\.wheel-smoke\Scripts\python.exe -m pip install $Wheel
$WatchDockCli = (Resolve-Path .\.wheel-smoke\Scripts\watchdock.exe).Path
Push-Location $env:TEMP
& $WatchDockCli --help
Pop-Location
```

Do not commit generated `dist`, `build`, virtual-environment, database, log, or
sidecar files.

## Change guidelines

- Preserve the default `hitl` behavior and the rule that fallback analysis cannot
  move a file automatically.
- Treat watched-file content and provider output as untrusted.
- Keep proposals free of filesystem side effects; apply an action only in the
  organizer after the relevant review decision.
- Add tests for Windows paths, name conflicts, path traversal, changed queued
  sources, concurrent claims, and failure/retry behavior when those areas change.
- Keep `pyproject.toml` authoritative for package metadata and dependencies.
- Add user-visible work under the `Unreleased` heading in `CHANGELOG.md`; release
  automation owns the eventual version/tag alignment.

Before opening a pull request, include a concise risk note for changes that touch
file movement, credentials, provider data, queue transitions, or release logic.
