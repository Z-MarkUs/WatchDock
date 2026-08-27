# Doctor MCP operations

Use only the arguments documented here; configuration remains server-side.

- `status()` returns the current WatchDock readiness and queue context.
- `doctor()` returns diagnostic findings without changing configuration or watched source files. It creates and removes a temporary write probe in the configured archive.
- `analyze_file(file_path)` helps isolate a problem for one exact, user-scoped file without queuing or moving it. It may call the configured AI provider and incur network use or cost.
- `list_actions(statuses?, limit=50)` can provide bounded queue context. Omit `statuses` unless a specific lifecycle state matters.
- `get_action(action_id)` can inspect one known action involved in the failure.

Do not use `reject_action` or `retry_action` as diagnostic probes. Those operations change action state and belong to an explicitly authorized review workflow.
