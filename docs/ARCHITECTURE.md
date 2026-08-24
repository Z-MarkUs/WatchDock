# Architecture

WatchDock has one processing path shared by explicit CLI requests, the foreground
watcher, and the desktop GUI:

```text
filesystem event or `watchdock process`
                 |
                 v
       stable regular-file check
                 |
                 v
 metadata + optional short text preview
                 |
                 v
 provider adapter ---- unavailable/invalid ----> rules fallback
                 |                                  |
                 v                                  v
 validated high-confidence result         requires_review=true
                 |                                  |
                 +---------------+------------------+
                                 |
                  HITL/review required?
                       /               \
                     yes               no
                      |                 |
                SQLite queue       safe organizer
                      |                 |
              explicit approval         |
                      +--------+---------+
                               v
                  move/rename + tag sidecar
```

## Components

- `config.py` owns typed configuration, defaults, validation, and atomic JSON
  writes. It rejects watched-folder/archive overlap before the service starts.
- `watcher.py` wraps `watchdog`, filters temporary and managed files, debounces
  repeated events, waits for stability, and runs file work outside the observer
  callback.
- `ai_processor.py` gathers bounded metadata/preview input, talks to the selected
  provider, validates the result, and produces the review-only rules fallback.
- `file_organizer.py` creates a sanitized proposal and applies either an archive
  move or an in-place rename. It writes portable tag metadata beside the result.
- `pending_actions.py` persists review state in SQLite and atomically claims an
  action for one worker. Approval verifies that the source still matches the
  reviewed fingerprint and executes the exact reviewed destination.
- `main.py` exposes CLI workflows and owns foreground service lifetime.
- `gui.py` provides an in-process desktop configuration, monitor, and review UI.
  It uses the same configuration and queue as the CLI.

## State and concurrency

The default state root is `~/.watchdock`, overridden by `WATCHDOCK_HOME`. Passing
`--config PATH` uses `PATH`'s parent as the state directory for that CLI command.
The config and sidecar writers use temporary files plus atomic replacement.
SQLite uses transactions, a busy timeout, full synchronous writes, and WAL mode
when the filesystem supports it.

The queue records `pending`, `processing`, `completed`, `rejected`, and `failed`
states. A claim is an atomic state transition, so concurrent CLI, GUI, and watcher
processes cannot normally execute the same pending action. A failed action remains
auditable and must be returned to pending explicitly before another approval.

## Safety invariants

- The default mode queues every proposed filesystem mutation.
- Rules fallback results always require review, regardless of configured mode.
- A move destination must remain inside the configured archive.
- A rename destination must remain inside the source directory.
- Windows-reserved names, separators, control characters, and traversal-like
  components are sanitized.
- Approval checks the source fingerprint and refuses a newly occupied reviewed
  destination.
- The archive and tag sidecars are excluded from watching to prevent loops.

These controls reduce accidental moves; they do not replace backups or provide a
filesystem transaction/undo mechanism.

## Trust boundaries

File previews and few-shot examples are untrusted input. They are bounded and
delimited before being included in provider prompts. Provider output is also
untrusted: required fields and types are validated, output lengths are bounded,
and filesystem components are sanitized again by the organizer.

Cloud-provider requests cross the local machine boundary. The local state
directory contains filenames, proposed destinations, analysis descriptions, tags,
history, and logs and should be protected like other user data. See
[SECURITY.md](SECURITY.md) for the exact data flow and operational guidance.
