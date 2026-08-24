# Changelog

All notable changes to WatchDock will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Review-first single-file workflow with dry-run `process`, explicit `--queue`
  and `--apply` choices, durable action history, `retry`, `doctor`, redacted
  `config show`, and JSON status output.
- SQLite-backed pending-action storage with atomic claims, source fingerprints,
  failure retention, legacy JSON migration, and concurrent CLI/GUI access.
- Portable `.watchdock.json` tag sidecars and centralized config, queue, examples,
  and rotating-log paths under `WATCHDOCK_HOME` or `~/.watchdock`.
- Cross-platform CI for Python 3.10 through 3.14, provider-extra checks,
  wheel/source-distribution validation, clean-wheel CLI smoke tests, and gated
  executable builds.
- Architecture, security/privacy, recovery, and contributor documentation.

### Changed

- The supported Python floor is now 3.10.
- The default mode is now human-in-the-loop (`hitl`), and monitoring must be
  started explicitly with `watchdock start` or from the GUI.
- OpenAI and Anthropic SDKs are optional extras (`openai`, `anthropic`, or `ai`);
  the base installation retains offline, review-only rules.
- Provider imports are lazy. Unavailable providers, request failures, and invalid
  responses now fall back to deterministic low-confidence proposals that cannot
  be applied automatically.
- OpenAI analysis uses the Responses API with strict structured output and
  `store=false`.
- File monitoring now debounces duplicate events, waits for stable readable
  files, ignores common partial downloads and tag sidecars, retries transient
  errors, and excludes the archive from observation.
- `watchdock version` is local-only; use `watchdock version --check` for the
  networked PyPI check.

### Security

- Provider API keys are resolved from WatchDock-specific or standard environment
  variables; inline configuration remains supported only for compatibility and
  is redacted by `config show`.
- Configuration rejects watched-folder/archive overlap and duplicate watch paths.
- Generated destination components are sanitized, original extensions are
  retained, reviewed destinations are executed exactly, and a changed source or
  occupied destination fails safely instead of silently changing the action.
- File previews are limited to supported text types and treated as untrusted
  prompt data; binary content is not parsed or uploaded as a preview.

## [0.1.5] - 2026-01-19

### Fixed
- GUI: reduce/avoid native focus highlight “flash” (white/grey) when clicking in the window

### Changed
- CLI: `watchdock version` now also checks PyPI and reports whether an update is available
- CLI: `watchdock update` now installs the update directly (removed `update --install`)
- Docs: updated README to match the new CLI behavior

## [0.1.4] - 2026-01-16

### Fixed
- Fixed white/grey highlights appearing when clicking on widgets
- Configured global widget styles to prevent default focus highlights
- Set option database defaults for consistent dark theme across all widgets
- Added highlight settings to all frames to prevent unwanted focus borders

## [0.1.3] - 2026-01-16

### Added
- CLI subcommands: `watchdock update`, `watchdock version`, `watchdock status`, `watchdock config`
- `wd` alias as shorter alternative to `watchdock` command
- `watchdock update --install` command to automatically update from PyPI
- `watchdock config init` and `watchdock config validate` commands

### Changed
- Complete GUI redesign with OpenAI-style dark theme
- Improved text contrast and readability (fixed grey-on-white issues)
- Enhanced color palette with darker backgrounds and higher contrast
- Changed accent color to OpenAI green (#10A37F)
- Improved card styling with borders and dividers
- Better input field focus states and styling
- Enhanced navigation buttons with improved hover effects
- Replaced ttk buttons with custom styled buttons for consistency

## [0.1.2] - 2026-01-16

### Changed
- Complete GUI redesign with ChatGPT/Cursor-style dark theme
- Replaced tab navigation with modern sidebar navigation
- Implemented card-based layouts for better visual hierarchy
- Improved typography and spacing throughout the application
- Enhanced button and input field styling with modern aesthetics

## [0.1.1] - 2026-01-16

### Added
- Overview tab with quick actions (open config/logs)
- Status bar with current config summary

### Changed
- Modernized GUI styling (spacing, typography, and visual hierarchy)
- Improved layout clarity across tabs
- Added mode field to config example

## [0.1.0] - 2024-01-XX

### Added
- Initial release of WatchDock
- File system monitoring with watchdog library
- AI-powered file analysis (OpenAI, Anthropic, Ollama support)
- Automatic file organization (rename, tag, move to archive)
- Native GUI application (Tkinter-based, cross-platform)
- CLI interface for developers
- HITL (Human-In-The-Loop) mode for manual approval
- Auto mode for fully automated organization
- Few-shot learning support for custom organization preferences
- Configuration management system
- Pending actions queue for HITL mode
- Desktop notifications for pending actions (macOS/Linux)
- Comprehensive documentation and publishing infrastructure

### Features
- Monitor multiple folders for new/modified files
- AI analysis of file content and metadata
- Automatic categorization and organization
- Custom archive structure (date/category folders)
- Tagging system for files
- Cross-platform support (Windows, macOS, Linux)

