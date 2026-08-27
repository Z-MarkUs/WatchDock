# Agent integration

WatchDock's agent gateway lets coding agents analyze files and stage exact
organization proposals without giving the gateway an approval or source-file
execution tool. The transport is a local MCP server over standard input/output,
and the durable queue is the same SQLite queue used by the WatchDock desktop app
and CLI.

The repository includes three workflows:

- `watchdock-organize` analyzes an exact user-scoped file and can queue it.
- `watchdock-review` lists, inspects, explains, rejects, or retries actions.
- `watchdock-doctor` diagnoses configuration and readiness problems.

## Security boundary

The MCP server exposes no tool that approves, moves, renames, copies, deletes,
or overwrites a source file. Agent-queued actions remain pending until a human
uses the WatchDock desktop app or runs `watchdock approve ACTION_ID`.

This is an interface boundary, not an operating-system sandbox. A connected
agent may independently have shell, Python, editor, or filesystem tools outside
WatchDock. Those capabilities are governed by the agent host, not by the
absence of an MCP approval tool. The bundled skills explicitly instruct agents
not to bypass WatchDock's review boundary, but instructions are not containment.

The gateway also has non-source-file side effects:

- `queue_file`, `reject_action`, and `retry_action` can change SQLite queue
  state.
- `doctor` creates the archive directory if necessary and performs a temporary
  create/write/fsync/delete probe there.
- `analyze_file` and `queue_file` can contact the configured OpenAI, Anthropic,
  or Ollama-compatible provider.
- status, action, and error results can reveal absolute paths and file-derived
  information to the connected agent client.

See the [tool effects](#exact-tool-effects) and
[security guide](SECURITY.md#coding-agent-and-mcp-boundary) before connecting a
cloud-hosted agent to sensitive folders.

## Prerequisites

1. Python 3.10 or newer.
2. WatchDock 0.3.0 or a current source checkout.
3. An explicit WatchDock configuration with at least one enabled watched root.
4. The `watchdock-mcp` command visible in the environment inherited by the
   coding-agent client.

Install and initialize the MCP-enabled package:

```console
python -m pip install "watchdock[mcp]"
watchdock config init
watchdock config validate
watchdock doctor
```

The `mcp` extra installs the MCP SDK. Provider SDKs remain separate:

```console
python -m pip install "watchdock[mcp,openai]"
python -m pip install "watchdock[mcp,anthropic]"
python -m pip install "watchdock[mcp,ai]"
```

If PyPI still serves WatchDock 0.2.x, install the 0.3.0 source checkout while
the release candidate is being validated:

```console
git clone https://github.com/Z-MarkUs/WatchDock.git
cd WatchDock
python -m pip install -e ".[mcp]"
```

The 0.3.0 release pipeline also builds a versioned, self-contained agent-plugin
ZIP. That archive contains the Claude marketplace, Codex/Claude manifests,
skills, references, and MCP launch configuration, but no executable. Install the
matching `watchdock[mcp]` package first, extract the ZIP, and use its top-level
directory as a local Claude marketplace. The platform application archives are
separate; the 0.3.0 candidate adds a frozen MCP executable to those archives,
subject to the final release build and smoke tests.

## Run the server directly

The default server reads `~/.watchdock/config.json` and reserves standard output
for MCP protocol messages:

```console
watchdock-mcp
```

Select a different configuration explicitly when the client integration permits
arguments:

```console
watchdock-mcp --config "/absolute/path/to/config.json"
```

Alternatively, set `WATCHDOCK_HOME` before starting the coding-agent client.
Environment variables are inherited when that client launches
`watchdock-mcp`; changing a variable in a different terminal does not update an
already-running client.

## Codex setup

### Preferred: version-pinned Git marketplace plugin

The repository publishes the `watchdock` Codex marketplace catalog at
`.agents/plugins/marketplace.json`. After `watchdock-mcp` is installed and
visible on `PATH`, install the tagged plugin bundle:

```console
codex plugin marketplace add Z-MarkUs/WatchDock --ref v0.3.0
codex plugin add watchdock-agent@watchdock
```

The `--ref` pin keeps the marketplace catalog, skills, and MCP launch
configuration on the same reviewed release. The command becomes the public
install path when the `v0.3.0` tag is published. For release-candidate testing
before that tag exists, use `--ref main` and record the exact commit; do not
describe that development install as a tagged release.

Start a new Codex task after installation so it discovers the plugin's skills
and MCP server. Example requests include:

```text
Use $watchdock-organize to analyze this report and queue it for review.
Use $watchdock-review to explain my pending WatchDock actions.
Use $watchdock-doctor to diagnose my WatchDock setup.
```

The catalog and plugin manifests are present, but a clean marketplace install
and real queue/review flow remain explicit final release gates. They are tracked
in [Agent evaluations](AGENT_EVALS.md); manifest discovery alone is not treated
as live end-to-end acceptance.

### Direct MCP and individual skills

Use this development fallback when testing a local checkout, a non-default MCP
configuration, or only one of the portable skills. Register the installed
command with the Codex CLI:

```console
codex mcp add watchdock -- watchdock-mcp
codex mcp get watchdock
```

For a non-default configuration:

```console
codex mcp add watchdock -- watchdock-mcp --config "/absolute/path/to/config.json"
```

Copy the three skill directories from a WatchDock checkout into Codex's
user-level Agent Skills directory. On Windows PowerShell:

```powershell
$WatchDockCodexSkills = Join-Path $env:USERPROFILE ".agents\skills"
New-Item -ItemType Directory -Force $WatchDockCodexSkills | Out-Null
Copy-Item -Recurse -Force `
    .\integrations\watchdock-agent\skills\* `
    $WatchDockCodexSkills
```

On macOS or Linux:

```bash
watchdock_codex_skills="$HOME/.agents/skills"
mkdir -p "${watchdock_codex_skills}"
cp -R integrations/watchdock-agent/skills/. "${watchdock_codex_skills}/"
```

For repository-scoped discovery instead, copy the same directories to
`<repository>/.agents/skills/`. Start a new Codex task after copying skills or
changing MCP registration. Avoid
installing the marketplace plugin and registering a second `watchdock` MCP
server in the same profile unless duplicate-server behavior is the subject of
the test.

## Claude Code marketplace setup

The repository publishes a Claude Code marketplace named `watchdock` at
`.claude-plugin/marketplace.json`. After `watchdock-mcp` is installed and visible
on `PATH`, add the Git repository and install the plugin:

```console
claude plugin marketplace add Z-MarkUs/WatchDock
claude plugin install watchdock-agent@watchdock
```

The equivalent interactive Claude Code commands are:

```text
/plugin marketplace add Z-MarkUs/WatchDock
/plugin install watchdock-agent@watchdock
```

Start a new Claude Code session or follow the client's reload instruction after
installation. For local development, validate the marketplace and plugin from
the repository root:

```console
claude plugin validate .
claude plugin validate ./integrations/watchdock-agent
```

Plugin skills are namespaced in Claude Code:

```text
/watchdock-agent:watchdock-organize
/watchdock-agent:watchdock-review
/watchdock-agent:watchdock-doctor
```

The marketplace and plugin manifests are present, but a clean Claude Code
install and real queue/review flow remain explicit final release gates. They are
tracked in [Agent evaluations](AGENT_EVALS.md); this documentation does not claim
that live acceptance from manifest structure alone.

## Exact tool effects

Every tool returns a structured envelope with `ok`, `operation`, `data`, and
`error`. “Provider/network” below means a WatchDock analysis request to the
configured provider; the connected agent client can separately transmit tool
arguments and results to its own model service.

| MCP tool | Local reads | Provider/network | Queue database | Temporary probe | Source-file mutation |
| --- | --- | --- | --- | --- | --- |
| `status` | Configuration, watched roots, archive existence, provider readiness, queue counts | No provider request | Read | None | **No** |
| `doctor` | Configuration, roots, provider package/credential presence, queue readiness | No provider request | Read | May create the archive directory; creates, writes, fsyncs, and removes one probe | **No** |
| `analyze_file` | Exact watched file metadata and an optional bounded text preview | **Possible**, according to provider configuration; otherwise rules fallback | None | None | **No** |
| `queue_file` | Same analysis input plus a full-file SHA-256 fingerprint | **Possible**, according to provider configuration; otherwise rules fallback | Atomic read/add or active-action deduplication | None | **No** |
| `list_actions` | Selected action rows and current source containment/fingerprint state | No provider request | Read | None | **No** |
| `get_action` | One action and current source containment/fingerprint state | No provider request | Read | None | **No** |
| `reject_action` | Current action and source safety state | No provider request | Read; write when transitioning pending/failed to rejected | None | **No** |
| `retry_action` | Failed action plus watched-root and SHA-256 source revalidation | No provider request | Read and write failed to pending | None | **No** |

`status.data.ai.ready` and `doctor.data.provider_ready` describe local client
readiness: the required SDK is installed, the client initialized, and any
required credential is configured. For Ollama, WatchDock checks the
OpenAI-compatible client and endpoint configuration but does not make a health
request, so these fields do not prove that the configured endpoint is online.

`analyze_file` and `queue_file` return `analysis_execution.source` and
`analysis_execution.provider_request_attempted`. Their `side_effects` list
includes `provider_analysis` only when a provider request was attempted; a
rules-only fallback caused by an unavailable client reports no provider effect.

The table describes tool-specific work after server initialization. Starting
`watchdock-mcp` opens and, when necessary, creates or migrates the SQLite state
database and its supporting files. Normal WatchDock logging can also append to
the configured rotating log during any operation.

`queue_file` computes a SHA-256 digest in addition to size and nanosecond mtime.
An active pending/processing action with the same canonical source and
fingerprint is reused instead of duplicated. The digest is an integrity check
for the reviewed source; it is not a malware scan, signature, or proof of
provenance.

`list_actions` defaults to `pending` and `failed` with a limit of 50, but callers
can request other lifecycle states and raise the limit to 500. `status`,
`list_actions`, and `get_action` can return absolute watched, state, source, and
destination paths. Action results can also include category, suggested name,
reasoning, tags, errors, and rows from requested lifecycle states. The MCP
interface does not expose the queue's lower-level event log. Do not connect an
agent that should not receive that information.

## Human approval

An agent can report the returned action ID, source, proposed destination, and
current fingerprint state. It must not describe a pending action as completed.
The human then reviews in the desktop app or CLI:

```console
watchdock list-pending
watchdock approve ACTION_ID
```

Approval atomically claims the action, rechecks watched-root containment and
the stored fingerprint, and attempts the exact reviewed destination without
replacing an existing entry. A changed source or occupied destination becomes a
failed action for reconciliation.

## Troubleshooting

- **`watchdock-mcp` is not found:** install `watchdock[mcp]` into an environment
  visible to the client, then restart the client so it inherits the updated
  `PATH`.
- **Configuration not found:** run `watchdock config init`, pass `--config` in a
  direct MCP registration, or set `WATCHDOCK_HOME` before launching the client.
- **A file is outside watched roots:** add the intended root to configuration;
  do not broaden scope merely to bypass the rejection.
- **Provider unavailable:** safe HITL operation can use the deterministic rules
  fallback. `doctor` reports whether the condition is a warning or error for the
  selected mode.
- **The same file was queued twice:** inspect the returned `created`,
  `deduplicated`, and `already_queued` fields. Active matching proposals are
  reused; a changed fingerprint or terminal prior action can produce new work.
- **A retry is rejected:** failed actions can return to pending only while the
  source remains inside a watched root and matches its reviewed fingerprint.
