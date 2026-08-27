"""Regression checks for the installed distribution metadata."""

from importlib.metadata import distribution

from packaging.requirements import Requirement

import watchdock


def _requirements_for_extra(extra: str | None = None) -> set[str]:
    requirements = distribution("watchdock").requires or []
    selected = set()
    for raw_requirement in requirements:
        requirement = Requirement(raw_requirement)
        if extra is None and requirement.marker is None:
            selected.add(requirement.name.lower())
        elif requirement.marker and requirement.marker.evaluate({"extra": extra or ""}):
            selected.add(requirement.name.lower())
    return selected


def test_runtime_metadata_has_only_eager_dependencies() -> None:
    assert _requirements_for_extra() == {"packaging", "watchdog"}


def test_ai_provider_sdks_are_optional() -> None:
    assert "openai" in _requirements_for_extra("openai")
    assert "anthropic" not in _requirements_for_extra("openai")
    assert "anthropic" in _requirements_for_extra("anthropic")
    assert "openai" not in _requirements_for_extra("anthropic")
    assert {"openai", "anthropic"} <= _requirements_for_extra("ai")


def test_mcp_sdk_is_optional() -> None:
    assert "mcp" not in _requirements_for_extra()
    assert "mcp" in _requirements_for_extra("mcp")


def test_console_entry_points_are_declared() -> None:
    scripts = {
        entry_point.name: entry_point.value
        for entry_point in distribution("watchdock").entry_points
        if entry_point.group == "console_scripts"
    }
    assert scripts["watchdock"] == "watchdock.main:main"
    assert scripts["wd"] == "watchdock.main:main"
    assert scripts["watchdock-mcp"] == "watchdock.mcp_server:main"


def test_runtime_and_distribution_versions_match() -> None:
    package = distribution("watchdock")
    assert package.version == watchdock.__version__
    assert package.metadata["Requires-Python"] == ">=3.10"
