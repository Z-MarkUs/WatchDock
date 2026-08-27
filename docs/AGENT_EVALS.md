# Agent integration evaluations

This document defines what must be proven before WatchDock claims a coding-agent
integration is release-ready. It separates implementation tests, protocol tests,
packaging checks, and live-client acceptance so that a valid manifest is never
mistaken for an end-to-end result.

## Current evidence status

WatchDock 0.3.0 includes the agent service, eight-tool MCP server, three portable
skills, a Codex Git marketplace/plugin, and a Claude Code marketplace/plugin.
The release audit combines repository tests, public CI, clean package/protocol
smokes, and the client-specific evidence below. Client results are intentionally
reported at their actual depth rather than inferred from valid manifests.

| Evidence layer | Current status | Required release evidence |
| --- | --- | --- |
| Agent service behavior | Green locally and in public CI | Keep the release-commit workflow green |
| MCP tool inventory and structured results | Green source, clean-wheel, and real stdio smokes | Repeat in tagged platform builds |
| Codex marketplace and plugin | Windows live queue flow passed from installed skill through MCP | Repeat the marketplace install from the public tag |
| Claude marketplace and plugin | Native validation, isolated install, three-skill discovery, and MCP health passed | Model-driven queue requires an authenticated Claude session |
| Human handoff | Codex-queued source was approved separately; exact bytes, destination, sidecar, and completed state verified | Claude model-driven handoff not claimed |

## Invariants

Every release audit should prove all of these statements:

1. The MCP inventory is exactly `status`, `doctor`, `analyze_file`,
   `queue_file`, `list_actions`, `get_action`, `reject_action`, and
   `retry_action`.
2. No MCP tool approves or executes a proposed source-file move, rename, copy,
   deletion, or overwrite.
3. Analyze returns a proposal without persisting an action or changing the
   source.
4. Queue stores a pending action, captures SHA-256, and leaves the source and
   proposed destination unchanged.
5. Concurrent or repeated queue requests for the same canonical path and
   fingerprint reuse one active action.
6. Files outside enabled watched roots and symlink sources fail closed.
7. A source replaced during provider analysis is not queued.
8. Listing and lookup report whether the source is still current and contained.
9. Reject and retry change queue state only; neither mutates the source.
10. A changed source cannot be retried or approved against a stale review.
11. A newly occupied reviewed destination is not silently renamed.
12. Provider failure or invalid output falls back to a review-only result.
13. `doctor` reports its archive write probe rather than presenting itself as a
    side-effect-free read.
14. Standard output from `watchdock-mcp` remains reserved for the stdio
    protocol.
15. Approval rechecks that the source remains inside a currently enabled watched
    root before executing the reviewed proposal.
16. A hashed agent request never reuses a legacy active action whose digest is
    absent.

These are integration invariants, not proof that an agent with independent
shell or filesystem tools is sandboxed.

## Automated regression suite

Run the focused tests:

```console
python -m pytest tests/test_agent_service.py tests/test_mcp_server.py tests/test_pending_actions.py
```

Then run the full project gates:

```console
python -m ruff check watchdock scripts tests
python -m pytest
```

The primary evidence lives in:

- [`tests/test_agent_service.py`](https://github.com/Z-MarkUs/WatchDock/blob/main/tests/test_agent_service.py)
- [`tests/test_mcp_server.py`](https://github.com/Z-MarkUs/WatchDock/blob/main/tests/test_mcp_server.py)
- [`tests/test_pending_actions.py`](https://github.com/Z-MarkUs/WatchDock/blob/main/tests/test_pending_actions.py)
- [`tests/test_cli.py`](https://github.com/Z-MarkUs/WatchDock/blob/main/tests/test_cli.py)
- [`tests/test_file_organizer.py`](https://github.com/Z-MarkUs/WatchDock/blob/main/tests/test_file_organizer.py)

Do not put a fixed test count in the README: parametrization, platform-specific
cases, and future additions make a green workflow link better evidence.

## Clean package and protocol acceptance

Use a temporary virtual environment outside the repository, install the built
wheel with its MCP extra, and verify that imports and entry points resolve from
that environment rather than the checkout.

The acceptance record must include:

- wheel filename and SHA-256;
- Python and operating-system versions;
- `pip check` output;
- installed `watchdock` version;
- `watchdock --help` and `watchdock-mcp --help`;
- an MCP initialize/list-tools/call-tool session over stdio;
- proof that queueing leaves the source unchanged and destination absent; and
- proof that a separate human approval produces the exact destination and tag
  sidecar.

Run this on Windows, Linux, and macOS for the final release candidate. The 0.3.0
candidate workflow builds a separate frozen MCP executable and runs the same
stdio smoke client against it; the claim becomes public only after those
platform jobs and downloaded release-asset checks pass.

## Codex live acceptance

Use a clean Codex profile or record all pre-existing configuration that might
affect discovery.

1. Install `watchdock[mcp]` from the candidate wheel.
2. Create an isolated WatchDock configuration and watched folder.
3. Add the tagged marketplace and install the plugin:

   ```console
   codex plugin marketplace add Z-MarkUs/WatchDock --ref v0.3.0
   codex plugin add watchdock-agent@watchdock
   ```

4. Confirm the plugin exposes all three skills and exactly the eight documented
   MCP tools.
5. Start a new task and request `watchdock-organize` for one exact file.
6. Capture the returned action ID, proposal, SHA-256, and source state.
7. Confirm the source is unchanged and the destination absent.
8. Inspect the action with `watchdock-review`.
9. Approve it outside the agent using the GUI or CLI.
10. Confirm the exact destination, sidecar, completed state, and lifecycle
    history.
11. Repeat with an outside-root file, changed queued source, occupied
    destination, and repeated queue request.

The 2026-08-28 Windows acceptance used Codex CLI `0.150.0-alpha.8` in an
ephemeral task. It loaded `watchdock-organize`, called `status`, queued one exact
test file through MCP, returned a pending SHA-256-backed action, and reported
`source_file_mutated=false`. Before approval the source digest was unchanged and
the destination was absent. A separate CLI approval then produced the exact
destination, byte-identical digest, `.watchdock.json` sidecar, and completed
state. The no-approval policy path was also exercised and correctly created no
action. The broader negative matrix remains covered by automated regressions,
not claimed as repeated model-driven calls.

## Claude Code live acceptance

Use a clean Claude Code profile and the repository marketplace:

```console
claude plugin validate .
claude plugin validate ./integrations/watchdock-agent
claude plugin marketplace add Z-MarkUs/WatchDock
claude plugin install watchdock-agent@watchdock
```

Then repeat the same queue, inspect, external approval, stale-source,
outside-root, destination-collision, and deduplication cases used for Codex.
Record the Claude Code version, plugin scope, marketplace revision, operating
system, sanitized transcript, and final artifact hashes.

The 2026-08-28 Windows acceptance used Claude Code `2.1.240` with an isolated
configuration. Native validation passed for the marketplace and plugin; local
marketplace installation reported version `0.3.0`; component discovery found
all three skills and one MCP server; and `claude mcp list` connected successfully.
A model-driven queue was not run because the isolated client was not logged in.
The project therefore claims Claude-native packaging and MCP connectivity, not
a Claude model-driven queue/handoff.

## Results template

Add one row only after retaining the corresponding evidence:

| Client | Version | OS | Package source | Manifest/skill validation | Queue flow | External approval | Negative cases | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Codex | 0.150.0-alpha.8 | Windows | 0.3.0 source candidate + installed local catalog | Passed: skill loaded and MCP tools called | Passed | Passed: exact bytes, destination, sidecar, completed state | Automated suite; live no-approval path | 2026-08-28 acceptance + public CI |
| Claude Code | 2.1.240 | Windows | 0.3.0 source candidate + isolated local marketplace | Passed: native validation, 3 skills, connected MCP | Not run: login required | Not claimed | Automated protocol suite | 2026-08-28 structural/connectivity acceptance |

Evidence may be a public CI run, a committed sanitized transcript, screenshots,
and checksums. Do not link private filenames, credentials, prompts, or home
directories.

## Non-goals

- The evaluation does not claim that skill instructions confine an agent that
  also has independent shell access.
- Active-action deduplication is not a universal exactly-once guarantee across
  every possible external client failure.
- SHA-256 proves content equality with the reviewed bytes; it does not prove
  authorship, safety, or provenance.
- A local stdio MCP transport does not prove that the agent client or configured
  analysis provider keeps data on the local machine.
- The 100-file watcher burst regression is a correctness scenario, not a
  throughput benchmark.
