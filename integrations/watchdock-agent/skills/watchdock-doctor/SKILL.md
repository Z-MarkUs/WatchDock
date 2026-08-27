---
name: watchdock-doctor
description: Diagnose WatchDock configuration, readiness, and file-analysis problems without changing watched source files. Use when WatchDock is unavailable, a proposal fails, queue state looks wrong, or the user asks for a health check.
---

# WatchDock Doctor

Use WatchDock's own diagnostics as the source of truth, then turn the findings into a concise, evidence-based recovery path.

## Safety boundary

- Diagnostic use may check status, run doctor, inspect queue state, and analyze a user-scoped file. It must not edit configuration, start or stop monitoring, approve actions, or mutate watched source files. The doctor tool creates and removes a temporary write probe in the configured archive.
- The WatchDock agent API intentionally exposes no approval or move tool. Never bypass that boundary with shell commands, filesystem tools, Python, direct database writes, or the WatchDock approval CLI.
- Recommendations are not authorization to apply changes. Tell the user which fix or human-facing WatchDock step is needed.

## Workflow

1. Call status to establish the current service and queue state.
2. Call doctor for concrete diagnostic findings; quote or paraphrase only what the server returns.
3. If the problem concerns one exact file, analyze that file after the user places it in scope. Do not turn troubleshooting into a broad scan.
4. Inspect action state only when it helps explain a queue or retry problem.
5. Separate confirmed findings from suggested next checks, ordered by the smallest safe intervention.

For exact v1 diagnostic tools and argument boundaries, read [MCP operations](references/mcp-operations.md) before calling the server.
