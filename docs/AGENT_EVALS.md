# Agent integration evaluations

This document defines what must be proven before WatchDock claims a coding-agent
integration is release-ready. It separates implementation tests, protocol tests,
packaging checks, and live-client acceptance so that a valid manifest is never
mistaken for an end-to-end result.

## Current evidence status

The 0.3.0 release candidate includes the agent service, eight-tool MCP server,
three portable skills, a Codex Git marketplace and plugin manifest, and a Claude
Code marketplace. Repository tests cover the service and protocol invariants
below. Final clean package installation and live Codex and Claude Code acceptance
are still release gates and must be recorded before this document or the README
claims those flows passed.

| Evidence layer | Current status | Required release evidence |
| --- | --- | --- |
| Agent service behavior | Automated coverage present | Green public CI for the release commit |
| MCP tool inventory and structured results | Automated coverage present | Green public CI plus clean installed-wheel stdio session |
| Codex marketplace and plugin | Manifests present | Add the tagged Git marketplace in a clean profile; install the plugin; run a real queue flow |
| Claude marketplace and plugin | Manifests present | `claude plugin validate .`; clean marketplace install; run a real queue flow |
| Human handoff | Core GUI/CLI behavior covered separately | Queue from each live client, approve outside the agent, verify exact destination and sidecar |

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

Record the Codex version, operating system, model/client mode, installation
commands, sanitized transcript, and artifact hashes. Until this checklist is
complete, use “Codex marketplace and plugin candidate” or “Codex setup
available,” not
“end-to-end tested with Codex.”

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

Until this checklist is complete, describe the repository as containing a
Claude Code marketplace and plugin candidate, not as live Claude-validated.

## Results template

Add one row only after retaining the corresponding evidence:

| Client | Version | OS | Package source | Manifest/skill validation | Queue flow | External approval | Negative cases | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Codex | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| Claude Code | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

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
