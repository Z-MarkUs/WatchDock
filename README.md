# WatchDock

WatchDock is a review-first file organizer for Windows, macOS, and Linux. It can
watch folders, ask a cloud or local model for a proposed category and filename,
and keep the proposal in a durable approval queue. If no model is available, it
falls back to deterministic extension rules and still leaves the source file in
place until you approve the action.

WatchDock is alpha software that can rename or move files. Start with a test
folder, keep a backup, and stay in the default `hitl` mode until you have reviewed
its proposals.

## What it does

- Watches one or more folders for stable new or changed files.
- Creates a proposed category, filename, tags, and destination.
- Queues every proposal in the default human-in-the-loop (`hitl`) mode.
- Can automatically apply only a validated, high-confidence provider result in
  `auto` mode.
- Uses a durable SQLite queue shared by the CLI and GUI.
- Sanitizes path components and Windows reserved filenames, keeps the original
  extension, and avoids overwriting an existing file.
- Writes portable tag metadata in a JSON sidecar next to the organized file.
- Falls back to offline rules when a provider is unavailable or returns invalid
  output. A fallback result is always review-only, even in `auto` mode.

## Requirements and installation

WatchDock requires Python 3.10 or newer. A base install includes the CLI, folder
watching, GUI code, and offline rules, but not the optional model-provider SDKs.

In PowerShell or Command Prompt:

```powershell
python -m pip install --upgrade pip
python -m pip install watchdock
```

Choose an extra when you want an AI provider:

```powershell
# OpenAI, or an Ollama server with an OpenAI-compatible endpoint
python -m pip install "watchdock[openai]"

# Anthropic
python -m pip install "watchdock[anthropic]"

# Both provider SDKs
python -m pip install "watchdock[ai]"
```

PowerShell needs the quotes around a requirement containing brackets. On Windows,
`py -m pip` is also valid if the Python launcher is installed. Tkinter is supplied
by most standard Python installers; `watchdock gui` reports an error if it is not
available.

The base install can produce review-only rules proposals. Because the generated
configuration names OpenAI as its provider, `watchdock doctor` deliberately
reports a missing OpenAI SDK as an error until you install that extra. If you
change provider, install its required extra; Ollama also needs the `openai` extra,
even though its current doctor check only displays the configured endpoint.

### Install from source

```powershell
git clone https://github.com/Z-MarkUs/watchdock.git
cd watchdock
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, use `.venv\Scripts\activate.bat` from Command
Prompt, or run `.venv\Scripts\python.exe` directly. See [CONTRIBUTING.md](CONTRIBUTING.md)
for checks used by the project.

## Quick start

Initialization and monitoring are explicit; running `watchdock` with no command
shows help and does not start a watcher.

```powershell
watchdock config init
watchdock config validate
watchdock doctor
watchdock start
```

`watchdock config init` creates a review-first configuration. Inspect it before
starting. The default watches your `Downloads` folder non-recursively, archives
under `Documents\Archive`, and uses `hitl` mode. `watchdock start` runs in the
foreground until you press `Ctrl+C` or close the terminal.

For OpenAI or Anthropic, prefer an environment variable instead of putting a key
in JSON. These PowerShell assignments last for the current terminal only:

```powershell
$env:WATCHDOCK_OPENAI_API_KEY = "<your OpenAI API key>"
# Or, when ai_config.provider is "anthropic":
$env:WATCHDOCK_ANTHROPIC_API_KEY = "<your Anthropic API key>"
```

Standard `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` variables are also recognized.
The WatchDock-prefixed variable takes precedence. Open a new terminal or remove
the variable after testing if you do not want the key to remain in that process.

## A safe Windows sandbox walkthrough

This walkthrough isolates both the files and WatchDock state under a temporary
directory. Install `watchdock[openai]` but do not set an API key; this deliberately
exercises the offline, review-only fallback without making a cloud request.

```powershell
python -m pip install "watchdock[openai]"

$Sandbox = Join-Path $env:TEMP "watchdock-sandbox"
$Inbox = Join-Path $Sandbox "inbox"
$Archive = Join-Path $Sandbox "archive"
$env:WATCHDOCK_HOME = Join-Path $Sandbox "state"
New-Item -ItemType Directory -Force $Inbox, $Archive | Out-Null

watchdock config init

$ConfigPath = Join-Path $env:WATCHDOCK_HOME "config.json"
$Config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
$Config.watched_folders[0].path = $Inbox
$Config.archive_config.base_path = $Archive
$Config.mode = "hitl"
$Json = $Config | ConvertTo-Json -Depth 6
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($ConfigPath, $Json + [Environment]::NewLine, $Utf8NoBom)

watchdock config validate
watchdock doctor
"Quarterly planning notes" | Set-Content (Join-Path $Inbox "sample notes.txt")
watchdock process (Join-Path $Inbox "sample notes.txt")
```

The final command is a dry run and prints an analysis and proposal. With no API
key, the output has `"analysis_source": "rules"` and
`"requires_review": true`; the file remains in the inbox. Queue and review that
same proposal:

```powershell
watchdock process (Join-Path $Inbox "sample notes.txt") --queue
watchdock list-pending
watchdock approve ACTION_ID
```

Approval moves the file under the sandbox archive. To test continuous watching,
run `watchdock start` in that PowerShell window, create another file from a second
window using the same `WATCHDOCK_HOME`, then return to the first window and press
`Ctrl+C`. Environment variables are per-process, so set `WATCHDOCK_HOME` again in
each new terminal or pass the configuration explicitly:

```powershell
watchdock --config "$Sandbox\state\config.json" status
```

Remove the sandbox when you have finished and confirmed it contains nothing you
need.

## Review modes

### Human-in-the-loop (`hitl`, default)

Every watcher result is stored as `pending`. Nothing is moved or renamed until
you approve it with the CLI or GUI. Rejection records the decision without
touching the source.

### Automatic (`auto`)

A provider result is applied automatically only after it passes WatchDock's
structured validation and is marked high confidence. Missing credentials, a
missing SDK, a provider error, or invalid provider output produces a low-confidence
rules result with `requires_review=true`; WatchDock queues it and does not move the
source. Auto mode is not recommended until you have tested your exact folders,
provider, model, and archive rules.

## CLI reference

Both `watchdock` and `wd` invoke the same CLI.

```text
watchdock --help
watchdock --version
watchdock version
watchdock version --check
watchdock update

watchdock config init
watchdock config init --force
watchdock config validate
watchdock config show

watchdock status
watchdock status --json
watchdock doctor
watchdock gui
watchdock start

watchdock process FILE
watchdock process FILE --queue
watchdock process FILE --apply

watchdock list-pending
watchdock list-pending --all
watchdock approve ACTION_ID
watchdock reject ACTION_ID
watchdock retry ACTION_ID
```

- `config init --force` replaces an existing configuration; use it deliberately.
- `config show` redacts a non-empty inline API key.
- `doctor` checks configuration, watched folders, archive writability, provider
  package/credentials, and the SQLite queue. For Ollama it reports the configured
  endpoint but does not perform a network health check.
- `process FILE` is a dry run. `--queue` stores the proposal. `--apply` performs a
  fresh analysis and immediately applies it if it is high confidence; it refuses
  fallback results but is independent of the configured HITL mode. Dry-run first,
  then use the queue when you need approval of one frozen proposal.
- `list-pending` includes pending and failed actions; `--all` also includes
  processing, completed, and rejected history.
- `retry` changes a failed action back to pending; it does not execute it. Run
  `approve` after reviewing it again.
- `update` upgrades a pip installation after checking PyPI. A standalone build
  cannot self-update.
- `--config PATH` is accepted before or after a subcommand and uses the selected
  configuration's parent directory for its queue, examples, and logs.

## Configuration

The generated JSON is intentionally complete and can be edited directly. A
portable sample is in [config.example.json](config.example.json).

```json
{
  "watched_folders": [
    {
      "path": "~/Downloads",
      "enabled": true,
      "recursive": false,
      "file_extensions": null
    }
  ],
  "ai_config": {
    "provider": "openai",
    "api_key": null,
    "model": "gpt-5.6-luna",
    "base_url": null,
    "temperature": 0.3
  },
  "archive_config": {
    "base_path": "~/Documents/Archive",
    "create_date_folders": true,
    "create_category_folders": true,
    "move_files": true
  },
  "log_level": "INFO",
  "check_interval": 1.0,
  "mode": "hitl"
}
```

`~` expands to the current user's home directory on Windows, macOS, and Linux.
`file_extensions` may be `null` for all files or a list such as
`[".pdf", ".txt"]`. Validation rejects duplicate watched paths and any enabled
watched folder that contains, equals, or is contained by the archive path; this
prevents archive feedback loops.

When `move_files` is true, the default layout is
`Archive/YYYY-MM/Category/filename.ext`. When false, WatchDock only renames the
file in its source folder. If a new automatic proposal collides with an existing
name, WatchDock adds `_1`, `_2`, and so on. A reviewed action instead fails when
its exact destination has become occupied, because silently changing an approved
destination would invalidate the review.

For Ollama, install the `openai` or `ai` extra, set `provider` to `ollama`, choose
a model available on your server, and set an OpenAI-compatible URL such as
`http://localhost:11434/v1`. Provider/model availability is deployment-specific;
the default model shown above may need to be changed for your account or server.

## State, logs, and tags

By default WatchDock stores its local state in `%USERPROFILE%\.watchdock` on
Windows and `~/.watchdock` elsewhere:

| Purpose | Default path |
| --- | --- |
| Configuration | `~/.watchdock/config.json` |
| Review queue and history | `~/.watchdock/pending_actions.sqlite3` |
| Few-shot examples | `~/.watchdock/few_shot_examples.json` |
| Active log | `~/.watchdock/logs/watchdock.log` |

Logs rotate at about 2 MiB and retain three backups. SQLite may create temporary
`-wal` and `-shm` companion files while WatchDock is running.

Set `WATCHDOCK_HOME` before running a command to relocate all default state:

```powershell
$env:WATCHDOCK_HOME = "D:\WatchDockState"
watchdock config init
```

Each non-empty tag list is stored next to the final file as
`filename.ext.watchdock.json`. This is a portable JSON sidecar, not an NTFS,
Finder, or Linux extended-attribute tag. The watcher ignores these sidecars.

## Content analysis and privacy

For supported text files, WatchDock reads at most 5,000 UTF-8 characters locally
and includes at most the first 2,000 characters in a provider prompt. Supported
preview extensions are `.txt`, `.md`, `.rst`, `.py`, `.js`, `.ts`, `.json`,
`.xml`, `.csv`, `.log`, `.yaml`, `.yml`, and `.toml`; files identified by the
operating system as `text/*` may also be previewed. Invalid UTF-8 bytes are
replaced for the preview.

PDF, Office, image, audio, video, archive, and other binary contents are not
parsed, OCR'd, or transcribed. Those files are classified from filename,
extension, size, and MIME type only.

When OpenAI or Anthropic is configured and available, WatchDock sends that
metadata, the optional text excerpt, and up to five sanitized few-shot examples
to the selected provider. The OpenAI integration uses the Responses API with a
strict structured-output schema and sends `store=false`. That request setting is
not a promise of zero retention or zero transient processing; review the
provider's current terms, account controls, and logging policy before sending
sensitive material. Anthropic data handling likewise depends on your provider
agreement. Avoid sensitive watched folders unless you have assessed those terms.

Ollama requests go to the configured endpoint. Whether that endpoint is local and
what it records depends on your Ollama deployment. With no usable client,
WatchDock's deterministic rules fallback does not make a provider request.

More detail is in [docs/SECURITY.md](docs/SECURITY.md).

## GUI and foreground monitoring

`watchdock gui` opens the Tk desktop UI for configuration, examples, monitoring,
and review actions. Monitoring started by the GUI runs only while that GUI process
is open. **Start Monitor** first validates and saves the current settings, then
runs the monitor on a background thread within that process. Settings saved while
it is already running take effect after the monitor is restarted. `watchdock
start` likewise runs in the current terminal. WatchDock does not currently install
a Windows service, a macOS LaunchAgent, a Linux systemd unit, a tray process, or
an automatic-start task.

The GUI needs a working graphical display and Tk. The CLI is the supported option
for headless sessions. Standalone application archives may be produced for tagged
releases, but they are unsigned and cannot self-update; verify release checksums
and expect operating-system warnings where applicable.

## Recovery and current limitations

- There is no undo command. To reverse an approved move, stop WatchDock, inspect
  the completed action with `watchdock list-pending --all`, and move the file back
  manually. Move or remove its `.watchdock.json` sidecar with it.
- Before backing up state, stop the CLI watcher and GUI, then copy the entire
  WatchDock state directory so the SQLite database and any companion files remain
  consistent.
- If a queued source changes after review, approval fails and retains the action
  as `failed`; re-analyze the file rather than trusting the stale proposal.
- If an action fails, inspect its error with `watchdock list-pending`, correct the
  cause, run `watchdock retry ACTION_ID`, review again, and then approve it.
- A file move/rename and sidecar write are not one transaction. A sidecar failure
  is logged as a warning after the file operation may already have succeeded.
- File arrival detection is best-effort and depends on the operating system and
  filesystem. WatchDock debounces events, waits for a file to stabilize, ignores
  common partial-download suffixes, and retries transient failures, but you should
  still test applications that write files in unusual ways.
- There is no built-in archive browser, duplicate-content detection, rollback,
  encryption, provider billing control, or binary-document understanding.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the processing flow and trust
boundaries.

## License

[MIT](LICENSE)
