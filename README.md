# WatchDock

A local, self-hosted, always-on "watchdog" tool that automatically organizes your files using AI.

## Features

- 🔍 **Monitors folders** - Watch one or more folders on your laptop for new or modified files
- 🤖 **AI-powered analysis** - Uses local or cloud AI to understand file content
- 📁 **Auto-organization** - Automatically renames, tags, and moves files to the correct archive location
- ⚙️ **Configurable** - Customize watched folders, AI providers, and organization rules
- 🔄 **Always-on** - Runs continuously in the background

## Installation

1. Clone or download this repository
2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Quick Start

1. **Initialize configuration:**

```bash
python main.py --init-config
```

This creates a default configuration file at `~/.watchdock/config.json`

2. **Edit the configuration file** to:
   - Add your AI API keys (if using cloud AI)
   - Configure watched folders
   - Set archive preferences

3. **Run WatchDock:**

```bash
python main.py
```

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

## Logging

WatchDock logs to both:
- Console output
- `watchdock.log` file in the current directory

## Requirements

- Python 3.8+
- Internet connection (for cloud AI providers) or local AI setup (Ollama)

## License

MIT License

