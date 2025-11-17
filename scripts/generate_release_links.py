#!/usr/bin/env python3
"""
Generate download links for GitHub Release.
Run this script and copy the output to your release notes.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from watchdock import __version__

VERSION = __version__
REPO = "Z-MarkUs/WatchDock"
TAG = f"v{VERSION}"

BASE_URL = f"https://github.com/{REPO}/releases/download/{TAG}"

print("# WatchDock v" + VERSION)
print()
print("## Download Addresses")
print()
print("### Windows 10/11")
print()
print("**CLI (Command Line):**")
print(f"- [64-bit]({BASE_URL}/watchdock-{VERSION}-windows.exe)")
print()
print("**GUI (Graphical Interface):**")
print(f"- [64-bit]({BASE_URL}/WatchDock-{VERSION}-windows.exe)")
print()
print("### macOS 11+")
print()
print("**Apple Silicon (M1/M2/M3):**")
print(f"- CLI: [watchdock-{VERSION}-arm64]({BASE_URL}/watchdock-{VERSION}-arm64)")
print(f"- GUI: [WatchDock-{VERSION}-arm64.app]({BASE_URL}/WatchDock-{VERSION}-arm64.app)")
print()
print("**Intel:**")
print(f"- CLI: [watchdock-{VERSION}-intel]({BASE_URL}/watchdock-{VERSION}-intel)")
print(f"- GUI: [WatchDock-{VERSION}-intel.app]({BASE_URL}/WatchDock-{VERSION}-intel.app)")
print()
print("### Linux")
print()
print("**64-bit:**")
print(f"- CLI: [watchdock-{VERSION}-linux]({BASE_URL}/watchdock-{VERSION}-linux)")
print(f"- GUI: [WatchDock-{VERSION}-linux]({BASE_URL}/WatchDock-{VERSION}-linux)")
print()
print("**Make executable after download:**")
print("```bash")
print(f"chmod +x watchdock-{VERSION}-linux")
print(f"chmod +x WatchDock-{VERSION}-linux")
print("```")
print()
print("### Via pip (All Platforms)")
print()
print("```bash")
print("pip install watchdock")
print("```")
print()
print("Then run:")
print("```bash")
print("watchdock          # CLI")
print("watchdock-gui      # GUI")
print("```")

