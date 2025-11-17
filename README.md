# WatchDock

A local, self-hosted, always-on "watchdog" tool that automatically organizes your files using AI.

## Features

- 🔍 **Monitors folders** - Watch one or more folders on your laptop for new or modified files
- 🤖 **AI-powered analysis** - Uses local or cloud AI to understand file content
- 📁 **Auto-organization** - Automatically renames, tags, and moves files to the correct archive location
- ⚙️ **Configurable** - Customize watched folders, AI providers, and organization rules
- 🖥️ **Native GUI** - Cross-platform desktop application (Windows, macOS, Linux)
- 💻 **CLI Mode** - Command-line interface for developers
- 🤝 **HITL Mode** - Human-In-The-Loop mode for approval before organizing files
- 📚 **Few-Shot Learning** - Provide examples to train the AI on your preferences
- 🔄 **Always-on** - Runs continuously in the background

## Installation

### Via pip (Recommended)

```bash
pip install watchdock
```

### From Source

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
pip install -e .
```

## Quick Start

### Option 1: Native GUI (Recommended for non-developers)

1. **Install WatchDock:**

```bash
pip install -e .
# Or: pip install watchdock
```

2. **Launch the GUI:**

```bash
watchdock-gui
# Or: python -m watchdock.gui_main
# Or: watchdock --gui
```

3. **Configure WatchDock** through the GUI:
   - Set up watched folders
   - Configure AI provider and API keys
   - Set archive preferences
   - Add few-shot examples (optional)

4. **Run WatchDock** (from command line):

```bash
watchdock
# Or: python main.py
```

### Option 2: Command Line (For Developers)

1. **Install WatchDock:**

```bash
pip install -e .
```

2. **Initialize configuration:**

```bash
watchdock --init-config
# Or: python main.py --init-config
```

This creates a default configuration file at `~/.watchdock/config.json`

3. **Edit the configuration file** to:
   - Add your AI API keys (if using cloud AI)
   - Configure watched folders
   - Set archive preferences

4. **Run WatchDock:**

```bash
watchdock
# Or: python main.py
```

### Creating Standalone Executables

To create standalone executables (.app on macOS, .exe on Windows) for distribution:

1. **Install PyInstaller:**

```bash
pip install pyinstaller
```

2. **Create executable:**

```bash
# For GUI application
pyinstaller --name=WatchDock --windowed --onefile watchdock/gui_main.py

# For CLI application
pyinstaller --name=watchdock --onefile watchdock/main.py
```

The executables will be in the `dist/` folder.

## Operation Modes

WatchDock supports two operation modes:

### Auto Mode (Default)
Files are automatically analyzed and organized without user intervention. Perfect for fully automated workflows.

### HITL Mode (Human-In-The-Loop)
Files are analyzed and proposed actions are queued for your approval. You can:
- Review each proposed action in the GUI
- Approve or reject individual actions
- Approve all pending actions at once
- Use CLI commands to manage pending actions

**CLI Commands for HITL Mode:**
```bash
# List all pending actions
watchdock --list-pending

# Approve a specific action
watchdock --approve <action_id>

# Reject a specific action
watchdock --reject <action_id>
```

**GUI:** Use the "Pending Actions" tab to review and manage pending actions.

## Configuration

The configuration file (`~/.watchdock/config.json` by default) contains:

### Watched Folders

```json
{
  "watched_folders": [
    {
      "path": "/Users/yourname/Downloads",
      "enabled": true,
      "recursive": false,
      "file_extensions": null
    }
  ]
}
```

### AI Configuration

WatchDock supports multiple AI providers:

- **OpenAI** - Cloud-based (requires API key)
- **Anthropic** - Cloud-based (requires API key)
- **Ollama** - Local AI (no API key needed)

Example for OpenAI:
```json
{
  "ai_config": {
    "provider": "openai",
    "api_key": "your-api-key-here",
    "model": "gpt-4",
    "temperature": 0.3
  }
}
```

Example for Ollama (local):
```json
{
  "ai_config": {
    "provider": "ollama",
    "model": "llama2",
    "base_url": "http://localhost:11434/v1"
  }
}
```

### Archive Configuration

```json
{
  "archive_config": {
    "base_path": "/Users/yourname/Documents/Archive",
    "create_date_folders": true,
    "create_category_folders": true,
    "move_files": true
  }
}
```

## How It Works

1. **Monitoring**: WatchDock monitors specified folders using the `watchdog` library
2. **Detection**: When a new file appears or is modified, it's detected
3. **Analysis**: The file is analyzed using AI to understand its content
4. **Organization**: Based on the analysis, the file is:
   - Categorized (e.g., Documents, Images, Videos)
   - Renamed with a clean, descriptive name
   - Tagged with relevant keywords
   - Moved to an organized archive structure

## File Organization Structure

Files are organized in the archive like this:

```
Archive/
├── 2024-01/
│   ├── Documents/
│   │   ├── project_proposal.pdf
│   │   └── meeting_notes.txt
│   ├── Images/
│   │   └── screenshot_2024.png
│   └── Videos/
│       └── presentation_recording.mp4
```

## Few-Shot Examples

You can provide examples to help the AI understand your organization preferences. This is especially useful for:
- Custom category names
- Specific naming conventions
- Tag preferences
- Domain-specific file types

Examples can be added through the GUI or by editing `~/.watchdock/few_shot_examples.json`:

```json
[
  {
    "file_name": "IMG_20240101_123456.jpg",
    "category": "Photos",
    "suggested_name": "2024-01-01_family_photo.jpg",
    "tags": ["family", "photo", "2024"],
    "description": "Family photo from January 2024"
  }
]
```

## Logging

WatchDock logs to both:
- Console output
- `watchdock.log` file in the current directory

## Requirements

- Python 3.8+
- Internet connection (for cloud AI providers) or local AI setup (Ollama)

## License

MIT License

