# Attach Executables to Release - Step by Step

## Step 1: Download Artifacts from GitHub Actions

1. **Go to completed workflow:**
   - https://github.com/Z-MarkUs/WatchDock/actions
   - Click on the successful "Build Executables" run

2. **Scroll down to "Artifacts" section**

3. **Download all three artifacts:**
   - `watchdock-linux` (Linux executables)
   - `watchdock-windows` (Windows executables)
   - `watchdock-macos` (macOS executables - you already have this!)

4. **Extract the zip files** to see the executables inside

## Step 2: Edit Existing Release

1. **Go to Releases:**
   - https://github.com/Z-MarkUs/WatchDock/releases

2. **Find the v0.1.0 release** (the one you created earlier)

3. **Click "Edit release"** (top right)

4. **Scroll down to "Attach binaries by dropping them here"**

5. **Drag and drop the executables:**
   - From `watchdock-windows.zip`: `watchdock.exe` and `WatchDock.exe`
   - From `watchdock-linux.zip`: `watchdock` and `WatchDock`
   - From `watchdock-macos.zip`: `watchdock` and `WatchDock.app`

   **Or** click "Attach binaries" and select files

6. **Click "Update release"**

## What Users Will See

After attaching, users can:

### Windows:
- Download `watchdock.exe` (CLI)
- Download `WatchDock.exe` (GUI)
- Double-click to run (no Python needed!)

### macOS:
- Download `watchdock` (CLI binary)
- Download `WatchDock.app` (GUI app)
- Double-click `.app` to run

### Linux:
- Download `watchdock` (CLI binary)
- Download `WatchDock` (GUI binary)
- Make executable: `chmod +x watchdock`
- Run: `./watchdock`

## Alternative: Create New Release (Optional)

If you prefer a fresh release:

1. **Create new tag:**
   ```bash
   git tag v0.1.1
   git push origin v0.1.1
   ```

2. **Create new release** with tag v0.1.1

3. **Attach executables**

But editing the existing release is simpler! ✅

