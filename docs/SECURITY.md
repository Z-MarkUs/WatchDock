# Security and privacy

WatchDock can read, rename, and move files, and it can send file-derived data to
a configured AI provider. Its coding-agent integration adds another recipient
of paths, proposals, and queue history. Start with a sandbox, keep a backup, and
use the default human-in-the-loop mode. The review queue is not a backup.

## Data sent to analysis providers

An OpenAI, Anthropic, or Ollama-compatible analysis request can contain:

- filename, extension, byte size, and guessed MIME type;
- up to 2,000 characters from the start of a supported text file; and
- up to five configured few-shot examples, reduced to bounded filename,
  category, suggested-name, and tag fields.

WatchDock may read up to 5,000 characters locally to form the bounded prompt. It
does not extract content from PDF, Office, image, audio, video, or archive files;
those receive metadata-only analysis.

The OpenAI adapter uses the Responses API with a strict JSON schema and sets
`store=false`. This is a request-level control, not a guarantee about transient
processing, abuse monitoring, application logs, or every retention rule. Review
the provider's current terms and account controls. The same caution applies to
Anthropic. An Ollama URL is only local if the configured endpoint and its network
path are local and controlled by you. Status and doctor validate the local
OpenAI-compatible client and endpoint configuration; they do not send an
endpoint health request.

When credentials or a provider client are unavailable, WatchDock uses its local
rules fallback and makes no analysis-provider request. That result is low
confidence and always requires review.

## Coding-agent and MCP boundary

The optional `watchdock-mcp` process communicates with its client over local
stdio; it does not open a network listener. Its eight tools can analyze, queue,
list, inspect, reject, retry, report status, and diagnose. It exposes no approval,
move, rename, copy, delete, or overwrite tool.

That restricted inventory is not a sandbox. A Codex, Claude Code, or other agent
may separately have shell, editor, Python, or filesystem capabilities. WatchDock
cannot prevent the host from granting or the agent from using those independent
tools. Human-review guarantees apply to actions submitted through the WatchDock
agent gateway, not to every capability of the surrounding agent.

The MCP tools also are not globally side-effect free:

- `queue_file` analyzes the source, computes SHA-256, and writes or reuses a
  durable queue action.
- `reject_action` and `retry_action` can change queue state but not the source.
- `doctor` may create the configured archive directory and performs a temporary
  create/write/fsync/delete probe inside it.
- `analyze_file` and `queue_file` may call the configured analysis provider and
  therefore may incur network, privacy, latency, and billing effects.

The exact per-tool matrix is documented in
[Agent integration](AGENT_INTEGRATION.md#exact-tool-effects).

### Information visible to an agent

Depending on the tool and requested filters, responses can contain:

- absolute configuration, state, watched-root, archive, source, and destination
  paths;
- filenames, extensions, sizes, timestamps, and source SHA-256 digests;
- categories, suggested names, tags, reasoning, errors, and action states; and
- action rows in pending, failed, processing, completed, or rejected states
  requested by the caller. The lower-level queue event log is not exposed.

`list_actions` defaults to pending and failed actions, but other states are
queryable. Do not connect an agent that should not receive those paths or that
history. Even though WatchDock-to-client transport is local stdio, the client can
send prompts, arguments, and tool results to its own remote model provider. A
local MCP server does not make the overall workflow local.

## Source integrity for review

Agent-queued actions capture the canonical source path, size, nanosecond mtime,
and full-file SHA-256. Active pending or processing work with the same path and
fingerprint is reused atomically so ordinary client retries do not multiply the
same review. Later inspection, retry, and approval recompute the stored digest.

SHA-256 detects changed bytes for the reviewed action; it does not establish
authorship, trustworthiness, malware safety, or provenance. Older or non-agent
actions can use metadata-only fingerprints, and WatchDock follows the fields
actually stored with each action.

## Credentials

Prefer environment variables:

| Provider | Preferred | Compatible fallback |
| --- | --- | --- |
| OpenAI | `WATCHDOCK_OPENAI_API_KEY` | `OPENAI_API_KEY` |
| Anthropic | `WATCHDOCK_ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` |

Do not commit credentials to `config.json`, examples, tests, shell history, MCP
configuration, transcripts, screenshots, or issue reports. Inline `api_key`
configuration is accepted for compatibility, but environment variables are
safer. `watchdock config show` redacts a displayed key; it cannot remove a key
already written to disk. Rotate a key if it was exposed.

The agent status and doctor responses report whether a credential is configured;
they do not intentionally return the credential value.

## Local data

The state directory stores configuration, analysis and proposal payloads,
absolute paths, source fingerprints, lifecycle history, errors, and logs. Tag
sidecars store tags, a timestamp, and the final filename next to each organized
file. Treat these files as sensitive operational data and protect them with
appropriate account permissions, disk encryption, backup controls, and
retention practices.

Stop the watcher, GUI, and MCP clients before copying the state directory for
backup. SQLite can have `-wal` and `-shm` companions while live, so copying only
the main database can produce an incomplete snapshot.

## Filesystem controls

WatchDock validates configuration overlap, confines move proposals to the
archive, keeps renames in the source directory, sanitizes provider-proposed path
components, preserves extensions, and refuses to replace the exact reviewed
destination or an existing sidecar. It rejects symlink sources and resolved
watch-root escapes in watcher, agent, retry, and approval paths. The explicit
single-file `process` command accepts the exact path a human supplies.

Approval rechecks the current enabled watched roots and the fingerprint stored
at review time, then uses no-replace operations for destinations and sidecars.
Rollback cleanup verifies captured file identity before removing anything it
created. A changed or newly excluded source, or an occupied reviewed
destination, fails instead of silently changing the reviewed action.

Residual risks remain:

- There is no built-in undo, malware scanner, content-safety classifier,
  access-control layer, or source-authenticity proof.
- A move/rename and sidecar write are not one filesystem transaction; sidecar
  failure can occur after a successful file operation.
- Filesystem event delivery is best-effort and depends on the operating system,
  application write pattern, and filesystem.
- The process inherits the launching user's permissions. Do not run it as an
  administrator merely for convenience.
- The optional core `auto` mode intentionally permits validated high-confidence
  provider results to execute without a human decision. Test it in a sandbox;
  the agent gateway itself does not expose that execution route.

## Recovery

- If a queued source changed, re-analyze it instead of retrying a stale review.
- If an action failed, inspect the error, correct the cause, run
  `watchdock retry ACTION_ID`, review it again, and approve separately.
- If WatchDock exited during approval, inspect both source and destination before
  running `watchdock recover-stale`. A crash can happen after the move but before
  completion is recorded.
- To reverse a completed move, stop WatchDock, inspect the action history, and
  move the file and its `.watchdock.json` sidecar back manually. There is no undo
  command.

## Reporting a vulnerability

Do not include credentials, private file excerpts, absolute personal paths, or
working exploit details in a public issue. Check the repository's current GitHub
security-reporting options first. If no private reporting channel is available,
open a minimal issue asking maintainer Hehan Zhao for a private contact path.
