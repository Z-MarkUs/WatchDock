# Building WatchDock

## Creating Standalone Executables

WatchDock can be packaged as standalone executables for Windows, macOS, and Linux.

### Prerequisites

```bash
pip install pyinstaller
```

### Building GUI Application

```bash
# macOS/Linux
pyinstaller --name=WatchDock --windowed --onefile --icon=icon.icns watchdock/gui_main.py

# Windows
pyinstaller --name=WatchDock --windowed --onefile --icon=icon.ico watchdock/gui_main.py
```

### Building CLI Application

```bash
pyinstaller --name=watchdock --onefile watchdock/main.py
```

### Including Data Files

If you need to include additional files:

```bash
pyinstaller --name=WatchDock --windowed --onefile \
    --add-data "watchdock/templates:templates" \
    --add-data "watchdock/static:static" \
    watchdock/gui_main.py
```

### Distribution

After building, the executables will be in the `dist/` folder:
- **macOS**: `dist/WatchDock.app` (or `.dmg` if packaged)
- **Windows**: `dist/WatchDock.exe`
- **Linux**: `dist/WatchDock` (executable binary)

## Installation Packages

### macOS (.dmg)

```bash
# Create .dmg using create-dmg or hdiutil
create-dmg --volname "WatchDock" --window-pos 200 120 \
    --window-size 800 400 --icon-size 100 --app-drop-link 600 185 \
    WatchDock.dmg dist/WatchDock.app
```

### Windows (Installer)

Use tools like:
- Inno Setup
- NSIS
- WiX Toolset

### Linux (AppImage)

```bash
# Use appimagetool
appimagetool dist/WatchDock.AppDir WatchDock-x86_64.AppImage
```

