# WatchDock Agent {version}

This archive is a self-contained local Claude Code marketplace for the
WatchDock agent plugin. It contains portable Agent Skills and a local stdio MCP
configuration; it contains no approval tool, hook, shell command, or bundled
executable.

Install the matching server first:

```text
python -m pip install "watchdock[mcp]=={version}"
```

Extract the ZIP, then add the extracted top-level directory as a local Claude
Code marketplace and install `watchdock-agent@watchdock`. The `watchdock-mcp`
command must be available on `PATH` when Claude Code starts the plugin.

The same directory also contains the native Codex catalog at
`.agents/plugins/marketplace.json`; its local source points to the identical
`integrations/watchdock-agent` plugin tree.

Queued proposals do not move source files. A human must separately review and
approve them through the WatchDock GUI or CLI.
