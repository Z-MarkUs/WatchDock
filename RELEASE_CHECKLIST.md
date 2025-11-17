# Release Checklist

Use this checklist before publishing a new version.

## Pre-Release

### Code Quality
- [ ] Code is tested (manually or with automated tests)
- [ ] No obvious bugs or crashes
- [ ] Error handling is robust
- [ ] Logging is comprehensive
- [ ] Code follows style guidelines

### Documentation
- [ ] README.md is up to date
- [ ] CHANGELOG.md is updated
- [ ] All features are documented
- [ ] Installation instructions are clear
- [ ] Examples are provided

### Configuration
- [ ] Version numbers are consistent:
  - [ ] `setup.py` (line 24)
  - [ ] `pyproject.toml` (line 7)
  - [ ] `watchdock/__init__.py` (line 5)
- [ ] Author information is correct:
  - [ ] `setup.py` - author, email, URLs
  - [ ] `pyproject.toml` - URLs
- [ ] License file exists and is correct

### Dependencies
- [ ] All dependencies are listed in `requirements.txt`
- [ ] Version constraints are appropriate
- [ ] No unnecessary dependencies
- [ ] Optional dependencies are documented

### Build & Test
- [ ] Package builds successfully: `python -m build`
- [ ] Package installs: `pip install dist/watchdock-*.whl`
- [ ] CLI works: `watchdock --help`
- [ ] GUI launches: `watchdock-gui`
- [ ] Configuration system works
- [ ] File watching works
- [ ] AI processing works (with test API key)
- [ ] HITL mode works

### Publishing Setup
- [ ] PyPI account created
- [ ] GitHub repository exists
- [ ] GitHub Actions secrets configured (PYPI_API_TOKEN)
- [ ] `.pypirc.example` is documented (don't commit `.pypirc`)

## Release Process

### 1. Final Checks
- [ ] All checklist items above are complete
- [ ] Git is clean: `git status`
- [ ] All changes committed

### 2. Version Bump
```bash
# Update version in:
# - setup.py
# - pyproject.toml  
# - watchdock/__init__.py
# - CHANGELOG.md
```

### 3. Commit & Tag
```bash
git add .
git commit -m "Bump version to X.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

### 4. Create GitHub Release
- Go to GitHub → Releases → Draft a new release
- Tag: `vX.Y.Z`
- Title: `Version X.Y.Z`
- Description: Copy from CHANGELOG.md
- Publish release

### 5. Verify
- [ ] GitHub Actions workflow completed successfully
- [ ] Package appears on PyPI: https://pypi.org/project/watchdock/
- [ ] Can install: `pip install watchdock`
- [ ] Can run: `watchdock --help`

### 6. Post-Release
- [ ] Announce release (if applicable)
- [ ] Update any external documentation
- [ ] Monitor for issues

## Current Status: v0.1.0

### ✅ Ready
- Core functionality implemented
- GUI and CLI working
- Documentation complete
- Publishing infrastructure set up
- Error handling in place

### ⚠️ Before Release
- [ ] Update placeholder values in setup.py and pyproject.toml
- [ ] Test on multiple platforms (if possible)
- [ ] Add basic tests (optional but recommended)
- [ ] Test installation from PyPI (use TestPyPI first)

### 📝 Notes
- This is an alpha release (0.1.0)
- Some features may need refinement based on user feedback
- Consider adding tests before 1.0.0 release

