---
name: watchdock-review
description: Inspect and explain WatchDock action proposals and explicitly requested rejection or retry operations. Use when the user asks what WatchDock plans to do, wants pending actions summarized, or needs a queued action rejected or retried.
---

# WatchDock Review

Inspect WatchDock's durable action queue and make every proposed filesystem change understandable before the human decides what to do.

## Safety boundary

- Implicit use is read-oriented: list, inspect, and explain actions only.
- Reject or retry an action only after an explicit user request identifying the action or an unambiguous set of actions. Inspect each action immediately before changing its state.
- Never approve an action or move, copy, rename, delete, or overwrite a file. The WatchDock agent API intentionally exposes no approval or move tool.
- Never bypass the missing tools with shell commands, filesystem tools, Python, direct database writes, or the WatchDock approval CLI. Approval belongs to the human in the WatchDock GUI or CLI.

## Workflow

1. List only the action states and quantity needed for the request.
2. Fetch full details for an action before explaining, rejecting, or retrying it.
3. Explain the proposed source, destination, rationale, and current state using the fields WatchDock actually returns. Surface missing or surprising data rather than filling gaps.
4. For an explicitly requested rejection or retry, repeat the affected action identifiers and report the server's resulting state.
5. End with the next human decision. Do not describe a pending proposal as executed.

For exact v1 tool selection and mutation boundaries, read [MCP operations](references/mcp-operations.md) before calling the server.
