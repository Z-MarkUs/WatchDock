# GitHub Release Guide

## Do You Need to Make the Repo Public?

### For PyPI Publishing: **No, but recommended**
- Your GitHub repo can be **private** and PyPI publishing will still work
- GitHub Actions can run on private repos (with free tier limits)
- However, **public repos are recommended** for open source projects because:
  - Users can see the source code
  - Better discoverability
  - Community contributions
  - Transparency builds trust

### For GitHub Releases: **Yes, recommended**
- If you want others to download releases from GitHub, make it public
- If it's private, only collaborators can access releases
- The GitHub Actions workflow will work either way

## Releases vs Packages - Which to Use?

### Use **GitHub Releases** ✅ (Recommended)

**GitHub Releases** is what you want for:
- Versioned releases (v0.1.0, v0.2.0, etc.)
- Release notes and changelog
- Downloadable assets (executables, installers)
- Triggering automated workflows (like PyPI publishing)
- Standard way to distribute software

**How it works:**
1. Create a release on GitHub → triggers GitHub Actions
2. GitHub Actions automatically publishes to PyPI
3. Users can download from GitHub Releases OR install via `pip install watchdock`

### GitHub Packages (Not Needed for PyPI)

**GitHub Packages** is a separate package registry (like npm, Maven, etc.)
- Different from PyPI
- Used for GitHub's own package management
- Not needed if you're publishing to PyPI
- More complex setup

**You don't need this** - PyPI is the standard Python package index.

## Step-by-Step Release Process

### Option 1: Using GitHub Web Interface (Easiest)

1. **Make repo public** (recommended):
   - Go to Settings → General → Danger Zone → Change visibility → Public

2. **Create a Release**:
   - Go to your repo on GitHub
   - Click "Releases" (right sidebar)
   - Click "Create a new release"
   - Tag: `v0.1.0` (must match your version)
   - Title: `WatchDock v0.1.0`
   - Description: Copy from `CHANGELOG.md`
   - Check "Set as the latest release"
   - Click "Publish release"

3. **GitHub Actions will automatically**:
   - Build the package
   - Publish to PyPI
   - You'll see the workflow run in Actions tab

### Option 2: Using Git Commands

1. **Tag and push**:
   ```bash
   git tag v0.1.0
   git push origin main --tags
   ```

2. **Create release on GitHub**:
   - Go to Releases → Draft a new release
   - Select tag `v0.1.0`
   - Add release notes
   - Publish

### Option 3: Manual PyPI Upload (Without GitHub)

If you don't want to use GitHub Actions:

```bash
# Build
python -m build

# Upload to TestPyPI first (recommended)
twine upload --repository testpypi dist/*

# Then upload to PyPI
twine upload dist/*
```

## What Happens When You Create a Release?

1. **GitHub Actions triggers** (if configured):
   - `.github/workflows/publish.yml` runs
   - Builds the package
   - Publishes to PyPI automatically

2. **Users can then**:
   - Install via: `pip install watchdock`
   - Download executables from GitHub Releases (if you upload them)

## Recommended Setup

### For Open Source Project:
- ✅ Make repo **public**
- ✅ Use **GitHub Releases**
- ✅ Let GitHub Actions publish to PyPI automatically
- ✅ Upload executables to Releases (optional)

### For Private Project:
- ✅ Keep repo **private**
- ✅ Use **GitHub Releases** (only collaborators see it)
- ✅ GitHub Actions still works
- ✅ PyPI package will be public (if you publish there)

## Summary

| Question | Answer |
|----------|--------|
| **Repo needs to be public?** | No, but recommended for open source |
| **Use Releases or Packages?** | **Use Releases** ✅ |
| **What triggers PyPI publish?** | Creating a GitHub Release |
| **Can I publish manually?** | Yes, use `twine upload dist/*` |

## Quick Checklist

- [ ] Repo is public (recommended) or private (works too)
- [ ] GitHub Actions secret `PYPI_API_TOKEN` is set
- [ ] Version is updated in `setup.py` and `pyproject.toml`
- [ ] CHANGELOG.md is updated
- [ ] Create GitHub Release with tag `v0.1.0`
- [ ] GitHub Actions publishes to PyPI automatically
- [ ] Users can `pip install watchdock`

