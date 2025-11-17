# Understanding GitHub Actions Artifacts

## What You're Seeing

GitHub Actions artifacts are **folders**, not zip files (they're zipped when downloaded, but appear as folders in the UI).

### Artifact Structure:

1. **watchdock-linux** (folder)
   - Contains: `watchdock` (CLI binary)
   - Contains: `WatchDock` (GUI binary)

2. **watchdock-windows** (folder)
   - Contains: `watchdock.exe` (CLI executable)
   - Contains: `WatchDock.exe` (GUI executable)

3. **watchdock-macos** (folder)
   - Contains: `watchdock` (CLI binary)
   - Contains: `WatchDock.app` (GUI application bundle)

## The macOS Issue

### Why WatchDock.app appears empty:
- `.app` files on macOS are actually **folders** (application bundles)
- GitHub's web UI might not show the contents properly
- The app is there, but it's built for **Apple Silicon (ARM64)**

### Why you can't open it:
- You're probably on an **Intel Mac**
- The build created an **ARM64** binary (for M1/M2/M3 Macs)
- We need to build **universal binaries** or **Intel-only** binaries

## Solution: Fix macOS Build

We need to specify the architecture. Let me update the workflow to build for Intel Macs (or universal).

## How to Upload to Release

### Option 1: Download and Extract First

1. **Download each artifact** (they download as .zip)
2. **Extract the zip files**
3. **Upload individual files** to the release:
   - From `watchdock-windows.zip`: Upload `watchdock.exe` and `WatchDock.exe`
   - From `watchdock-linux.zip`: Upload `watchdock` and `WatchDock`
   - From `watchdock-macos.zip`: Upload `watchdock` and `WatchDock.app` (the whole folder)

### Option 2: Upload the Zip Files Directly

You can upload the `.zip` files directly to the release - users can extract them.

## Fixing macOS Architecture

I'll update the workflow to build for Intel Macs (x86_64) which will work on both Intel and Apple Silicon (via Rosetta).

