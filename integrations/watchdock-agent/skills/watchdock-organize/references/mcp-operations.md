# Organize MCP operations

Use only the arguments documented here; configuration remains server-side.

- `status()` checks whether WatchDock is ready.
- `doctor()` returns diagnostic findings when readiness is unclear. It creates and removes a temporary archive write probe.
- `analyze_file(file_path)` analyzes one exact file without queuing or moving it. It may call the configured AI provider and incur network use or cost.
- `queue_file(file_path)` records one exact file as a proposal for later human review and computes a SHA-256 source fingerprint. It may call the configured AI provider and writes queue state, but it does not approve or move the source file. An identical active request returns the existing action.

Treat `file_path` as narrowly scoped user input. Preserve the server's returned action identifier and state exactly; do not infer that a proposal has been executed.
