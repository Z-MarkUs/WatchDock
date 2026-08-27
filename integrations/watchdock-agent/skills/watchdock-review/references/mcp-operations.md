# Review MCP operations

Use only the arguments documented here; action identifiers are opaque.

- `list_actions(statuses?, limit=50)` lists actions. Omit `statuses` unless the user names a lifecycle state; choose the smallest useful limit.
- `get_action(action_id)` returns one action's current details. Call it immediately before any state-changing request.
- `reject_action(action_id)` rejects one action. Use only after explicit user authorization.
- `retry_action(action_id)` returns one eligible failed action to pending review; it does not execute the action. Use only after explicit user authorization, and report the response instead of assuming success.
- `status()` provides service and queue readiness context when needed.

No WatchDock agent API tool approves or executes an action. If the user wants approval, direct them to WatchDock's human-facing GUI or CLI.
