# Publishing WatchDock

This guide explains how to publish WatchDock for distribution via pip and as standalone installers.

## PyPI Publishing (pip install)

### Prerequisites

1. Create accounts:
   - [PyPI](https://pypi.org/account/register/) - for production releases
   - [TestPyPI](https://test.pypi.org/account/register/) - for testing

2. Install build tools:
```bash
pip install build twine
```

### Manual Publishing

1. **Update version** in `setup.py` and `pyproject.toml`

2. **Build the package:**
```bash
python -m build
```

This creates:
- `dist/watchdock-0.1.0.tar.gz` (source distribution)
- `dist/watchdock-0.1.0-py3-none-any.whl` (wheel)

3. **Test on TestPyPI:**
```bash
twine upload --repository testpypi dist/*
```

4. **Install from TestPyPI to test:**
```bash
pip install --index-url https://test.pypi.org/simple/ watchdock
```

5. **Publish to PyPI:**
```bash
twine upload dist/*
```

### Automated Publishing (GitHub Actions)

The `.github/workflows/publish.yml` workflow automatically publishes to PyPI when you create a GitHub release.

1. Create a PyPI API token:
   - Go to https://pypi.org/manage/account/token/
   - Create a new API token
   - Add it as a GitHub secret: `PYPI_API_TOKEN`

2. Create a release:
```bash
git tag v0.1.0
git push origin v0.1.0
```

Or create a release on GitHub - it will automatically publish to PyPI.

### After Publishing

Users can install via:
```bash
pip install watchdock
```

## Standalone Executables

### Using PyInstaller

1. **Install PyInstaller:**
```bash
pip install pyinstaller
```

2. **Build CLI executable:**
```bash
pyinstaller --name=watchdock --onefile watchdock/main.py
```

3. **Build GUI executable:**
```bash
# macOS
pyinstaller --name=WatchDock --windowed --onefile --icon=icon.icns watchdock/gui_main.py

# Windows
pyinstaller --name=WatchDock --windowed --onefile --icon=icon.ico watchdock/gui_main.py

# Linux
pyinstaller --name=WatchDock --windowed --onefile watchdock/gui_main.py
```

### macOS Distribution

#### Option 1: DMG (Recommended)

1. Create `.app` bundle:
```bash
pyinstaller --name=WatchDock --windowed --onedir watchdock/gui_main.py
# Manually create .app bundle from dist/WatchDock/
```

2. Create DMG:
```bash
# Install create-dmg
brew install create-dmg

# Create DMG
create-dmg --volname "WatchDock" \
  --window-pos 200 120 \
  --window-size 800 400 \
  --icon-size 100 \
  --app-drop-link 600 185 \
  WatchDock.dmg dist/WatchDock.app
```

#### Option 2: Homebrew Formula

Create `watchdock.rb`:
```ruby
class Watchdock < Formula
  desc "File monitoring and organization tool using AI"
  homepage "https://github.com/yourusername/watchdock"
  url "https://github.com/yourusername/watchdock/releases/download/v0.1.0/watchdock-0.1.0.tar.gz"
  sha256 "..."
  license "MIT"

  depends_on "python@3.11"

  def install
    system "pip3", "install", "--prefix=#{prefix}", "."
  end

  test do
    system "#{bin}/watchdock", "--version"
  end
end
```

### Windows Distribution

#### Option 1: Inno Setup Installer

1. Install [Inno Setup](https://jrsoftware.org/isinfo.php)

2. Create `installer.iss`:
```iss
[Setup]
AppName=WatchDock
AppVersion=0.1.0
DefaultDirName={pf}\WatchDock
DefaultGroupName=WatchDock
OutputDir=installer
OutputBaseFilename=WatchDock-Setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\WatchDock.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\watchdock.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\WatchDock"; Filename: "{app}\WatchDock.exe"
Name: "{commondesktop}\WatchDock"; Filename: "{app}\WatchDock.exe"
```

3. Build installer:
```bash
iscc installer.iss
```

#### Option 2: Chocolatey Package

Create `watchdock.nuspec`:
```xml
<?xml version="1.0"?>
<package>
  <metadata>
    <id>watchdock</id>
    <version>0.1.0</version>
    <title>WatchDock</title>
    <authors>WatchDock Team</authors>
    <description>File monitoring and organization tool using AI</description>
    <projectUrl>https://github.com/yourusername/watchdock</projectUrl>
    <tags>file-organization ai automation</tags>
  </metadata>
  <files>
    <file src="dist\WatchDock.exe" target="tools\" />
  </files>
</package>
```

### Linux Distribution

#### Option 1: AppImage

1. Build AppImage:
```bash
# Install appimagetool
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage

# Create AppDir structure
mkdir -p WatchDock.AppDir/usr/bin
cp dist/watchdock WatchDock.AppDir/usr/bin/
cp dist/WatchDock WatchDock.AppDir/usr/bin/

# Create AppImage
./appimagetool-x86_64.AppImage WatchDock.AppDir WatchDock-x86_64.AppImage
```

#### Option 2: DEB Package (Debian/Ubuntu)

1. Create directory structure:
```bash
mkdir -p watchdock_0.1.0/usr/bin
mkdir -p watchdock_0.1.0/usr/share/applications
mkdir -p watchdock_0.1.0/DEBIAN
```

2. Copy files:
```bash
cp dist/watchdock watchdock_0.1.0/usr/bin/
cp dist/WatchDock watchdock_0.1.0/usr/bin/
```

3. Create `control` file:
```
Package: watchdock
Version: 0.1.0
Section: utils
Priority: optional
Architecture: amd64
Depends: python3
Maintainer: WatchDock Team <your-email@example.com>
Description: File monitoring and organization tool using AI
```

4. Build DEB:
```bash
dpkg-deb --build watchdock_0.1.0
```

#### Option 3: RPM Package (Fedora/RHEL)

1. Install rpmbuild:
```bash
sudo dnf install rpm-build
```

2. Create spec file `watchdock.spec`:
```
Name:           watchdock
Version:        0.1.0
Release:        1%{?dist}
Summary:        File monitoring and organization tool using AI
License:        MIT
Source0:        watchdock-%{version}.tar.gz

%description
File monitoring and organization tool using AI

%install
mkdir -p %{buildroot}/usr/bin
cp dist/watchdock %{buildroot}/usr/bin/
cp dist/WatchDock %{buildroot}/usr/bin/

%files
/usr/bin/watchdock
/usr/bin/WatchDock
```

3. Build RPM:
```bash
rpmbuild -ba watchdock.spec
```

#### Option 4: Snap Package

Create `snap/snapcraft.yaml`:
```yaml
name: watchdock
version: '0.1.0'
summary: File monitoring and organization tool using AI
description: |
  WatchDock automatically organizes your files using AI.

grade: stable
confinement: strict

apps:
  watchdock:
    command: watchdock
  watchdock-gui:
    command: WatchDock

parts:
  watchdock:
    plugin: python
    source: .
    python-version: python3
```

Build:
```bash
snapcraft
```

## Release Checklist

- [ ] Update version in `setup.py` and `pyproject.toml`
- [ ] Update CHANGELOG.md
- [ ] Run tests
- [ ] Build and test locally
- [ ] Create git tag: `git tag v0.1.0`
- [ ] Push tag: `git push origin v0.1.0`
- [ ] Create GitHub release
- [ ] Verify PyPI upload
- [ ] Build platform-specific installers
- [ ] Upload installers to GitHub release
- [ ] Announce release

## Version Numbering

Follow [Semantic Versioning](https://semver.org/):
- MAJOR.MINOR.PATCH (e.g., 1.0.0)
- MAJOR: incompatible API changes
- MINOR: backwards-compatible functionality
- PATCH: backwards-compatible bug fixes

