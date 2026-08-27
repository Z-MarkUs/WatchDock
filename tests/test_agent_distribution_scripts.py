import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.agent_distribution import (
    DistributionValidationError,
    MCP_TOOLS,
    expected_archive_members,
    package_agent_distribution,
    sha256_file,
    validate_agent_archive,
    validate_agent_distribution,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _copy_distribution_source(destination):
    destination.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", destination / "pyproject.toml")
    shutil.copy2(REPO_ROOT / "LICENSE", destination / "LICENSE")
    for relative in (
        Path("watchdock/__init__.py"),
        Path("watchdock/mcp_server.py"),
        Path("scripts/agent_plugin_README.md"),
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    shutil.copytree(REPO_ROOT / ".claude-plugin", destination / ".claude-plugin")
    shutil.copytree(REPO_ROOT / ".agents", destination / ".agents")
    shutil.copytree(REPO_ROOT / "integrations", destination / "integrations")


def test_checked_in_agent_distribution_is_exact_and_release_safe():
    info = validate_agent_distribution(REPO_ROOT)

    assert info.version.count(".") == 2
    assert len(info.plugin_files) == 14
    assert len(MCP_TOOLS) == 8


def test_agent_archive_is_deterministic_self_contained_and_revalidated(tmp_path):
    version = validate_agent_distribution(REPO_ROOT).version
    first = package_agent_distribution(REPO_ROOT, tmp_path / "first")
    second = package_agent_distribution(REPO_ROOT, tmp_path / "second")

    assert first.name == f"watchdock-agent-{version}.zip"
    assert sha256_file(first) == sha256_file(second)
    validate_agent_archive(first, REPO_ROOT)

    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == set(expected_archive_members(REPO_ROOT))
        prefix = f"watchdock-agent-{version}/"
        assert prefix + ".claude-plugin/marketplace.json" in archive.namelist()
        assert prefix + ".agents/plugins/marketplace.json" in archive.namelist()
        assert prefix + "integrations/watchdock-agent/.mcp.json" in archive.namelist()
        install_note = archive.read(prefix + "README.md").decode("utf-8")
        assert f"watchdock[mcp]=={version}" in install_note


def test_validator_rejects_manifest_drift_and_new_execution_surface(tmp_path):
    checkout = tmp_path / "checkout"
    _copy_distribution_source(checkout)
    manifest_path = checkout / "integrations/watchdock-agent/.claude-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    hooks = checkout / "integrations/watchdock-agent/hooks/hooks.json"
    hooks.parent.mkdir()
    hooks.write_text("{}\n", encoding="utf-8")

    with pytest.raises(DistributionValidationError) as caught:
        validate_agent_distribution(checkout)

    message = str(caught.value)
    assert "version mismatch" in message
    assert "execution" in message or "executable" in message
