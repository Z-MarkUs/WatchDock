# PyPI Publishing Setup Guide

## The Error You Saw

The error occurred because the workflow was trying to use **PyPI Trusted Publishing** (OIDC), which requires additional setup on PyPI. 

**Error:** `invalid-publisher: valid token, but no corresponding publisher`

## Solution: Use API Token (Simpler)

I've updated the workflow to use API token authentication instead, which is simpler and doesn't require PyPI configuration.

## Setup Steps

### 1. Get PyPI API Token

1. Go to https://pypi.org/manage/account/token/
2. Click "Add API token"
3. Token name: `watchdock-github-actions` (or any name)
4. Scope: **Entire account** (or just the project if you prefer)
5. Click "Add token"
6. **Copy the token immediately** (you won't see it again!)

The token looks like: `pypi-AgEIcHlwaS5vcmcCJ...` (long string)

### 2. Add Token to GitHub Secrets

1. Go to your GitHub repo: `https://github.com/Z-MarkUs/WatchDock`
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `PYPI_API_TOKEN`
5. Value: Paste your PyPI API token
6. Click **Add secret**

### 3. Create a Release

Now when you create a GitHub Release, it will automatically publish to PyPI!

```bash
# Tag the release
git tag v0.1.0
git push origin main --tags

# Then create release on GitHub web interface
```

Or create the release directly on GitHub:
- Go to Releases → Create a new release
- Tag: `v0.1.0`
- Title: `WatchDock v0.1.0`
- Publish release

## Alternative: Use Trusted Publishing (More Secure)

If you want to use trusted publishing instead (more secure, no token needed):

### On PyPI:
1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a new pending publisher"
3. PyPI project name: `watchdock`
4. Owner: `Z-MarkUs`
5. Workflow filename: `.github/workflows/publish.yml`
6. Environment name: (leave empty)
7. Click "Add"

### Update workflow to use trusted publishing:
```yaml
- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@release/v1
```

But the API token method is simpler and works fine!

## Testing

### Test on TestPyPI First (Recommended)

1. Get TestPyPI token: https://test.pypi.org/manage/account/token/
2. Add as secret: `TEST_PYPI_API_TOKEN`
3. Update workflow to test first (optional)

Or test manually:
```bash
python -m build
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ watchdock
```

## Current Workflow (API Token Method)

The workflow now uses:
- `TWINE_USERNAME: __token__`
- `TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}`
- `twine upload dist/*`

This is simpler and doesn't require PyPI configuration!

## Troubleshooting

### "Invalid API token"
- Make sure the token is correct
- Check that the secret name is exactly `PYPI_API_TOKEN`
- Verify token hasn't expired (they don't expire, but check anyway)

### "Package already exists"
- Version already published - bump version number
- Or delete the version on PyPI (if you have permissions)

### "Authentication failed"
- Double-check the token in GitHub secrets
- Make sure token scope includes the project

## Summary

✅ **Fixed:** Updated workflow to use API token (simpler)  
✅ **Next:** Add `PYPI_API_TOKEN` secret to GitHub  
✅ **Then:** Create release → auto-publishes to PyPI!

