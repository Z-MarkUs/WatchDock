# Quick Publishing Guide

## Quick Start: Publish to PyPI

### 1. First Time Setup

```bash
# Install build tools
pip install build twine

# Create PyPI account and API token
# Go to: https://pypi.org/manage/account/token/
# Create token and save it
```

### 2. Build and Test Locally

```bash
# Build the package
python -m build

# Check the package
twine check dist/*

# Test install locally
pip install dist/watchdock-*.whl
```

### 3. Test on TestPyPI

```bash
# Upload to TestPyPI
twine upload --repository testpypi dist/*

# Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ watchdock
```

### 4. Publish to PyPI

```bash
# Upload to PyPI
twine upload dist/*
```

Or use the Makefile:
```bash
make publish
```

## Automated Publishing (Recommended)

### Setup GitHub Actions

1. **Create PyPI API Token:**
   - Go to https://pypi.org/manage/account/token/
   - Create a new API token (scope: entire account)
   - Copy the token

2. **Add GitHub Secret:**
   - Go to your GitHub repo → Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `PYPI_API_TOKEN`
   - Value: Your PyPI API token
   - Click "Add secret"

3. **Create a Release:**
   ```bash
   # Update version in setup.py and pyproject.toml
   git add .
   git commit -m "Bump version to 0.1.0"
   git tag v0.1.0
   git push origin main --tags
   ```
   
   Or create a release on GitHub - it will automatically publish to PyPI!

## Building Executables

### Quick Build

```bash
# Install PyInstaller
pip install pyinstaller

# Build CLI
make build-exe-cli

# Build GUI
make build-exe-gui

# Build both
make build-exe-all
```

### Platform-Specific

See `PUBLISHING.md` for detailed instructions on creating:
- macOS: DMG, Homebrew formula
- Windows: Installer, Chocolatey package
- Linux: AppImage, DEB, RPM, Snap

## Version Bumping

Before publishing, update version in:
- `setup.py` (line 24)
- `pyproject.toml` (line 5)
- `watchdock/__init__.py` (if you add version there)

Then commit and tag:
```bash
git commit -am "Bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

