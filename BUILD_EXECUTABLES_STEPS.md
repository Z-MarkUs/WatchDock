# Building Standalone Executables - Step by Step

## Step 1: Run the Build Executables Workflow

1. **Go to GitHub Actions:**
   - https://github.com/Z-MarkUs/WatchDock/actions

2. **Click "Build Executables"** in the left sidebar

3. **Click "Run workflow"** (top right button)

4. **Select:**
   - Branch: `main`
   - Click "Run workflow"

5. **Wait for builds to complete** (~5-10 minutes)
   - You'll see 3 jobs running (Linux, Windows, macOS)
   - Each will build executables for that platform

## Step 2: Download Artifacts

After all jobs complete:

1. **Click on the completed workflow run**

2. **Scroll down to "Artifacts"** section

3. **Download each artifact:**
   - `watchdock-linux` - Linux executables
   - `watchdock-windows` - Windows executables (.exe files)
   - `watchdock-macos` - macOS executables (.app files)

## Step 3: Create GitHub Release with Executables

### Option A: Create New Release

1. **Go to Releases:**
   - https://github.com/Z-MarkUs/WatchDock/releases

2. **Click "Draft a new release"**

3. **Fill in:**
   - Tag: `v0.1.0` (or create new tag)
   - Title: `WatchDock v0.1.0`
   - Description: Copy from CHANGELOG.md

4. **Attach executables:**
   - Drag and drop the downloaded executables
   - Or click "Attach binaries" and select files

5. **Click "Publish release"**

### Option B: Edit Existing Release

1. **Go to existing v0.1.0 release**

2. **Click "Edit release"**

3. **Attach executables** (drag & drop)

4. **Click "Update release"**

## What Users Will Get

### Windows Users:
- Download `watchdock.exe` (CLI)
- Download `WatchDock.exe` (GUI)
- Double-click to run (no Python needed!)

### macOS Users:
- Download `watchdock` (CLI binary)
- Download `WatchDock.app` (GUI app)
- Double-click `.app` to run

### Linux Users:
- Download `watchdock` (CLI binary)
- Download `WatchDock` (GUI binary)
- Make executable: `chmod +x watchdock`
- Run: `./watchdock`

## Troubleshooting

### If workflow fails:
- Check the error message in Actions
- Common issues:
  - Missing dependencies
  - PyInstaller errors
  - Platform-specific issues

### If executables are large:
- This is normal (PyInstaller bundles Python)
- Typical size: 50-100MB per executable
- Consider using `--onedir` instead of `--onefile` for smaller size

## Next Steps After Building

1. ✅ Test executables locally (if possible)
2. ✅ Upload to GitHub Release
3. ✅ Update README with download links
4. ✅ Announce to users

