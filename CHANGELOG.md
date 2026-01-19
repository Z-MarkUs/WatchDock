# Changelog

All notable changes to WatchDock will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

