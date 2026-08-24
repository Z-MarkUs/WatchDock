# Security and privacy

WatchDock can move files and can send file-derived data to a configured AI
provider. Use a sandbox and the default human-in-the-loop mode first. Do not treat
the review queue as a backup.

## Data sent to providers

For OpenAI, Anthropic, or an Ollama-compatible endpoint, an analysis request can
contain:

- filename, extension, byte size, and guessed MIME type;
- up to 2,000 characters from the start of a supported text file; and
- up to five configured few-shot examples, reduced to bounded filename,
  category, suggested-name, and tag fields.

WatchDock may read up to 5,000 characters locally to form that bounded prompt.
It does not parse or extract content from PDF, Office, image, audio, video, or
archive files. Those receive metadata-only analysis.

The OpenAI adapter uses the Responses API with a strict JSON schema and sets
`store=false`. This is a request-level control, not a guarantee about transient
processing, abuse monitoring, application logs, or every retention rule. Consult
the provider's current terms and your account controls. The same caution applies
to Anthropic. An Ollama URL is only local if you configured and operate it that
way; inspect that endpoint's network path and logs.

When credentials or a provider client are unavailable, WatchDock uses its local
rules fallback and makes no provider request for that analysis. The fallback is
always marked low confidence and requires review.

## Credentials

Prefer environment variables:

| Provider | Preferred | Compatible fallback |
| --- | --- | --- |
| OpenAI | `WATCHDOCK_OPENAI_API_KEY` | `OPENAI_API_KEY` |
| Anthropic | `WATCHDOCK_ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` |

Do not commit credentials to `config.json`, examples, tests, shell history, or
issue reports. Inline `api_key` configuration is accepted for compatibility, but
environment variables are safer and `watchdock config show` only redacts the
display—it cannot remove a key already written to disk. Rotate a key if it was
exposed.

## Local data

The state directory stores configuration, analysis/proposal history, filenames,
destinations, errors, and logs. Tag sidecars store tags, a timestamp, and the final
filename next to each organized file. Protect these files with appropriate account
permissions, disk encryption, backup controls, and retention practices.

Stop both the watcher and GUI before copying the state directory for backup.
SQLite can have `-wal` and `-shm` companions during use, so copying only the main
database while it is live may produce an incomplete snapshot.

## Filesystem controls and residual risk

WatchDock validates configuration overlap, confines move proposals to the archive,
keeps renames in the source directory, sanitizes provider-proposed path
components, preserves extensions, and refuses to overwrite the exact destination
of a reviewed action. It also fingerprints queued sources and fails approval if a
source changed after review.

There is still no undo, rollback transaction, malware scanner, content-safety
classifier, access-control layer, or cryptographic verification of the source
contents by default. A sidecar failure can occur after a move succeeds. The
process inherits the permissions of the user who launched it, so run it with the
least filesystem access practical and never as an administrator merely for
convenience.

## Reporting a vulnerability

Do not include secrets, private file excerpts, or exploitable production details
in a public report. Check the repository's current GitHub security-reporting
options first; if no private reporting channel is enabled, open a minimal issue
asking the maintainers for a private contact path.
