---
name: watchdock-organize
description: Analyze files and queue review-first organization proposals with WatchDock. Use when the user asks an agent to organize, classify, triage, or safely route generated artifacts or other files.
---

# WatchDock Organize

Use the WatchDock MCP server to turn a file-organization request into a proposal that remains under human control.

## Safety boundary

- Automatic or explicit use may analyze and queue proposals, but must never approve them or move, copy, rename, delete, or overwrite files.
- The WatchDock agent API intentionally exposes no approval or move tool. Never bypass that boundary with shell commands, filesystem tools, Python, direct database writes, or the WatchDock approval CLI.
- A queued action is not a completed organization. Tell the user that a human must review and approve it in the WatchDock GUI or CLI.

## Workflow

1. Identify the exact file or files the user placed in scope. Do not broaden the request into a directory-wide scan.
2. Check WatchDock status when readiness is uncertain. If the server reports a problem, use the doctor workflow instead of guessing.
3. Analyze each file when the user wants a preview or explanation.
4. Queue each file when the user asks WatchDock to organize or stage it for review. Queueing is permitted during implicit skill use because it does not move the file. Identical active requests are deduplicated by source path and fingerprint.
5. Report the proposed outcome and action identifier returned by WatchDock. Clearly label the action as awaiting human approval.

For exact v1 tool selection and argument boundaries, read [MCP operations](references/mcp-operations.md) before calling the server.
