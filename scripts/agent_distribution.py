"""Validate and package WatchDock's portable agent integration.

This module intentionally uses only the Python standard library so release
validation can run before project or provider dependencies are installed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


PLUGIN_PATH = Path("integrations/watchdock-agent")
MARKETPLACE_PATH = Path(".claude-plugin/marketplace.json")
CODEX_MARKETPLACE_PATH = Path(".agents/plugins/marketplace.json")
PACKAGE_VERSION_PATH = Path("watchdock/__init__.py")
MCP_SERVER_PATH = Path("watchdock/mcp_server.py")

MCP_ENTRY_POINT = "watchdock.mcp_server:main"
MCP_REQUIREMENT = "mcp>=2.0,<3"
MCP_TOOLS = (
    "status",
    "doctor",
    "analyze_file",
    "queue_file",
    "list_actions",
    "get_action",
    "reject_action",
    "retry_action",
)
SKILL_TOOLS = {
    "watchdock-doctor": {
        "status",
        "doctor",
        "analyze_file",
        "list_actions",
        "get_action",
    },
    "watchdock-organize": {
        "status",
        "doctor",
        "analyze_file",
        "queue_file",
    },
    "watchdock-review": {
        "status",
        "list_actions",
        "get_action",
        "reject_action",
        "retry_action",
    },
}

_PLUGIN_COMMON_FILES = {
    Path(".mcp.json"),
    Path(".claude-plugin/plugin.json"),
    Path(".codex-plugin/plugin.json"),
    Path("assets/watchdock-hero.png"),
    Path("assets/watchdock-icon.png"),
}
EXPECTED_PLUGIN_FILES = frozenset(
    _PLUGIN_COMMON_FILES
    | {
        Path(f"skills/{skill}/SKILL.md")
        for skill in SKILL_TOOLS
    }
    | {
        Path(f"skills/{skill}/agents/openai.yaml")
        for skill in SKILL_TOOLS
    }
    | {
        Path(f"skills/{skill}/references/mcp-operations.md")
        for skill in SKILL_TOOLS
    }
)

_FORBIDDEN_PLUGIN_COMPONENTS = {
    "agents",
    "bin",
    "commands",
    "hooks",
    "lspServers",
    "monitors",
    "scripts",
}
_FORBIDDEN_PLUGIN_ROOTS = {
    "agents",
    "bin",
    "commands",
    "hooks",
    "monitors",
    "scripts",
}
_TOOL_CALL_PATTERN = re.compile(r"`([a-z][a-z0-9_]*)\([^`]*\)`")
_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class DistributionValidationError(ValueError):
    """Raised when the checked-in agent distribution is not release-safe."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("agent distribution validation failed:\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class DistributionInfo:
    """Validated release metadata used by the packager and workflows."""

    version: str
    plugin_files: tuple[Path, ...]


class _Validator:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def read_text(self, relative_path: Path) -> str:
        path = self.repo_root / relative_path
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.errors.append(f"cannot read {relative_path.as_posix()}: {exc}")
            return ""

    def read_json(self, relative_path: Path) -> Any:
        text = self.read_text(relative_path)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self.errors.append(
                f"invalid JSON in {relative_path.as_posix()} at "
                f"line {exc.lineno}, column {exc.colno}"
            )
            return None


def repository_root(script_path: Path | None = None) -> Path:
    """Return the repository root for an installed checkout script."""

    anchor = (script_path or Path(__file__)).resolve()
    return anchor.parent.parent


def _toml_section(text: str, section_name: str) -> str:
    match = re.search(
        rf"(?ms)^\[{re.escape(section_name)}\][ \t]*\r?\n(.*?)(?=^\[|\Z)",
        text,
    )
    return match.group(1) if match else ""


def _toml_string(section: str, key: str) -> str | None:
    match = re.search(
        rf'(?m)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*"([^"\r\n]+)"[ \t]*$',
        section,
    )
    return match.group(1) if match else None


def _toml_string_array(section: str, key: str) -> list[str] | None:
    match = re.search(
        rf"(?ms)^[ \t]*{re.escape(key)}[ \t]*=[ \t]*\[(.*?)\]",
        section,
    )
    if not match:
        return None
    return re.findall(r'"([^"\r\n]+)"', match.group(1))


def _ast_string_assignment(source: str, variable: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == variable for target in targets):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def _mcp_server_tools(source: str) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, ()

    declared: tuple[str, ...] | None = None
    registered: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MCP_TOOL_NAMES"
            for target in node.targets
        ):
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                value = None
            if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
                declared = value
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name)
            and decorator.func.value.id == "server"
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        ):
            registered.append(node.name)
    return declared, tuple(registered)


def _parse_skill_frontmatter(text: str, relative_path: Path) -> tuple[dict[str, str], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ValueError(f"{relative_path.as_posix()} must start with YAML frontmatter")
    delimiter = normalized.find("\n---\n", 4)
    if delimiter < 0:
        raise ValueError(f"{relative_path.as_posix()} has unterminated YAML frontmatter")
    raw_frontmatter = normalized[4:delimiter]
    values: dict[str, str] = {}
    for line_number, line in enumerate(raw_frontmatter.splitlines(), start=2):
        if not line.strip():
            continue
        if line.startswith((" ", "\t", "-")) or ":" not in line:
            raise ValueError(
                f"{relative_path.as_posix()}:{line_number} uses unsupported frontmatter syntax"
            )
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if not key or not value or key in values:
            raise ValueError(
                f"{relative_path.as_posix()}:{line_number} has an invalid frontmatter field"
            )
        values[key] = value
    return values, normalized[delimiter + 5 :]


def _validate_png(validator: _Validator, relative_path: Path) -> None:
    path = validator.repo_root / relative_path
    try:
        header = path.read_bytes()[:24]
    except OSError as exc:
        validator.errors.append(f"cannot read {relative_path.as_posix()}: {exc}")
        return
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        validator.errors.append(f"{relative_path.as_posix()} is not a valid PNG asset")
        return
    width, height = struct.unpack(">II", header[16:24])
    validator.require(width > 0 and height > 0, f"{relative_path.as_posix()} has invalid dimensions")


def _validate_openai_skill_metadata(
    validator: _Validator, relative_path: Path, text: str
) -> None:
    mcp_types = re.findall(r'(?m)^\s*-\s*type:\s*["\']?([^"\'\s]+)', text)
    tool_values = re.findall(r'(?m)^\s*value:\s*["\']?([^"\'\s]+)', text)
    transports = re.findall(r'(?m)^\s*transport:\s*["\']?([^"\'\s]+)', text)
    validator.require(
        mcp_types == ["mcp"],
        f"{relative_path.as_posix()} must declare exactly one MCP dependency",
    )
    validator.require(
        tool_values == ["watchdock"],
        f"{relative_path.as_posix()} must depend only on the watchdock server",
    )
    validator.require(
        transports == ["stdio"],
        f"{relative_path.as_posix()} must use stdio transport",
    )
    validator.require(
        not re.search(r"(?mi)^\s*(command|args|hooks?|permissions?|allowed_tools)\s*:", text),
        f"{relative_path.as_posix()} must not declare command, hook, or permission surfaces",
    )


def _validate_plugin_tree(validator: _Validator) -> tuple[Path, ...]:
    plugin_root = validator.repo_root / PLUGIN_PATH
    validator.require(plugin_root.is_dir(), f"missing plugin directory: {PLUGIN_PATH.as_posix()}")
    if not plugin_root.is_dir():
        return ()

    for path in plugin_root.rglob("*"):
        if path.is_symlink():
            validator.errors.append(
                f"plugin distribution must not contain symlinks: {path.relative_to(plugin_root).as_posix()}"
            )

    actual_files = {
        path.relative_to(plugin_root)
        for path in plugin_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    missing = sorted(EXPECTED_PLUGIN_FILES - actual_files, key=lambda item: item.as_posix())
    unexpected = sorted(actual_files - EXPECTED_PLUGIN_FILES, key=lambda item: item.as_posix())
    for path in missing:
        validator.errors.append(f"missing required plugin file: {(PLUGIN_PATH / path).as_posix()}")
    for path in unexpected:
        validator.errors.append(f"unexpected plugin execution/package surface: {(PLUGIN_PATH / path).as_posix()}")
    for root_name in _FORBIDDEN_PLUGIN_ROOTS:
        validator.require(
            not (plugin_root / root_name).exists(),
            f"forbidden executable plugin component: {(PLUGIN_PATH / root_name).as_posix()}",
        )

    for asset in (Path("assets/watchdock-icon.png"), Path("assets/watchdock-hero.png")):
        if asset in actual_files:
            _validate_png(validator, PLUGIN_PATH / asset)

    return tuple(sorted(actual_files, key=lambda item: item.as_posix()))


def _validate_manifests(
    validator: _Validator, version: str | None, plugin_files: tuple[Path, ...]
) -> None:
    marketplace = validator.read_json(MARKETPLACE_PATH)
    codex_marketplace = validator.read_json(CODEX_MARKETPLACE_PATH)
    claude_manifest_path = PLUGIN_PATH / ".claude-plugin/plugin.json"
    codex_manifest_path = PLUGIN_PATH / ".codex-plugin/plugin.json"
    mcp_path = PLUGIN_PATH / ".mcp.json"
    claude_manifest = validator.read_json(claude_manifest_path)
    codex_manifest = validator.read_json(codex_manifest_path)
    mcp_config = validator.read_json(mcp_path)

    if isinstance(marketplace, Mapping):
        plugins = marketplace.get("plugins")
        validator.require(
            isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], Mapping),
            f"{MARKETPLACE_PATH.as_posix()} must publish exactly one plugin",
        )
        if isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], Mapping):
            entry = plugins[0]
            validator.require(entry.get("name") == "watchdock-agent", "marketplace plugin name mismatch")
            validator.require(
                entry.get("source") == "./integrations/watchdock-agent",
                "marketplace source must be ./integrations/watchdock-agent",
            )
            validator.require(entry.get("version") == version, "marketplace version mismatch")
            forbidden = sorted(_FORBIDDEN_PLUGIN_COMPONENTS.intersection(entry))
            validator.require(
                not forbidden,
                "marketplace must not add executable/approval components: " + ", ".join(forbidden),
            )
    else:
        validator.require(False, f"{MARKETPLACE_PATH.as_posix()} must contain a JSON object")

    if isinstance(codex_marketplace, Mapping):
        plugins = codex_marketplace.get("plugins")
        validator.require(
            codex_marketplace.get("name") == "watchdock",
            f"{CODEX_MARKETPLACE_PATH.as_posix()} catalog name mismatch",
        )
        validator.require(
            isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], Mapping),
            f"{CODEX_MARKETPLACE_PATH.as_posix()} must publish exactly one plugin",
        )
        if isinstance(plugins, list) and len(plugins) == 1 and isinstance(plugins[0], Mapping):
            entry = plugins[0]
            validator.require(entry.get("name") == "watchdock-agent", "Codex catalog plugin name mismatch")
            validator.require(
                entry.get("source")
                == {"source": "local", "path": "./integrations/watchdock-agent"},
                "Codex catalog source must be the local WatchDock integration",
            )
            validator.require(
                entry.get("policy")
                == {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "Codex catalog must require explicit install authentication",
            )
            forbidden = sorted(_FORBIDDEN_PLUGIN_COMPONENTS.intersection(entry))
            validator.require(
                not forbidden,
                "Codex catalog must not add executable/approval components: "
                + ", ".join(forbidden),
            )
    else:
        validator.require(
            False, f"{CODEX_MARKETPLACE_PATH.as_posix()} must contain a JSON object"
        )

    for label, manifest in (
        (claude_manifest_path.as_posix(), claude_manifest),
        (codex_manifest_path.as_posix(), codex_manifest),
    ):
        if not isinstance(manifest, Mapping):
            validator.require(False, f"{label} must contain a JSON object")
            continue
        validator.require(manifest.get("name") == "watchdock-agent", f"{label} name mismatch")
        validator.require(manifest.get("version") == version, f"{label} version mismatch")
        forbidden = sorted(_FORBIDDEN_PLUGIN_COMPONENTS.intersection(manifest))
        if label == codex_manifest_path.as_posix():
            forbidden = [item for item in forbidden if item != "mcpServers"]
            validator.require(
                manifest.get("mcpServers") == "./.mcp.json",
                f"{label} must reference ./.mcp.json",
            )
            validator.require(
                manifest.get("skills") == "./skills/",
                f"{label} must reference ./skills/",
            )
            interface = manifest.get("interface")
            validator.require(
                isinstance(interface, Mapping)
                and interface.get("capabilities") == ["Interactive", "Write"],
                f"{label} capabilities must be exactly Interactive and Write",
            )
        validator.require(
            not forbidden,
            f"{label} must not declare executable/approval components: " + ", ".join(forbidden),
        )

    expected_mcp = {
        "mcpServers": {
            "watchdock": {
                "command": "watchdock-mcp",
                "args": [],
            }
        }
    }
    validator.require(
        mcp_config == expected_mcp,
        f"{mcp_path.as_posix()} must declare only `watchdock-mcp` over stdio",
    )

    if plugin_files:
        validator.require(
            PurePosixPath(".claude-plugin/plugin.json")
            in {PurePosixPath(path.as_posix()) for path in plugin_files},
            "Claude plugin manifest is not packaged",
        )


def _validate_skills(validator: _Validator) -> None:
    for skill_name, expected_tools in SKILL_TOOLS.items():
        skill_root = PLUGIN_PATH / "skills" / skill_name
        skill_path = skill_root / "SKILL.md"
        reference_path = skill_root / "references/mcp-operations.md"
        metadata_path = skill_root / "agents/openai.yaml"

        skill_text = validator.read_text(skill_path)
        if skill_text:
            try:
                frontmatter, body = _parse_skill_frontmatter(skill_text, skill_path)
            except ValueError as exc:
                validator.errors.append(str(exc))
            else:
                validator.require(
                    set(frontmatter) == {"name", "description"},
                    f"{skill_path.as_posix()} frontmatter must contain exactly name and description",
                )
                validator.require(
                    frontmatter.get("name") == skill_name,
                    f"{skill_path.as_posix()} frontmatter name must match its directory",
                )
                validator.require(
                    len(frontmatter.get("description", "")) >= 40,
                    f"{skill_path.as_posix()} needs a meaningful description",
                )
                validator.require(bool(body.strip()), f"{skill_path.as_posix()} body is empty")

        reference_text = validator.read_text(reference_path)
        if reference_text:
            documented_tools = set(_TOOL_CALL_PATTERN.findall(reference_text))
            validator.require(
                documented_tools == expected_tools,
                f"{reference_path.as_posix()} tool set mismatch: "
                f"expected {sorted(expected_tools)}, found {sorted(documented_tools)}",
            )
            validator.require(
                documented_tools <= set(MCP_TOOLS),
                f"{reference_path.as_posix()} documents a forbidden MCP tool",
            )

        metadata_text = validator.read_text(metadata_path)
        if metadata_text:
            _validate_openai_skill_metadata(validator, metadata_path, metadata_text)


def validate_agent_distribution(repo_root: Path) -> DistributionInfo:
    """Validate source metadata and return immutable packaging information."""

    root = repo_root.resolve()
    validator = _Validator(root)
    validator.require((root / "pyproject.toml").is_file(), "missing pyproject.toml")
    validator.require((root / "LICENSE").is_file(), "missing LICENSE")
    validator.require(
        (root / "scripts/agent_plugin_README.md").is_file(),
        "missing scripts/agent_plugin_README.md",
    )
    validator.require((root / MARKETPLACE_PATH).is_file(), f"missing {MARKETPLACE_PATH.as_posix()}")
    validator.require(
        (root / CODEX_MARKETPLACE_PATH).is_file(),
        f"missing {CODEX_MARKETPLACE_PATH.as_posix()}",
    )

    pyproject = validator.read_text(Path("pyproject.toml"))
    project_section = _toml_section(pyproject, "project")
    scripts_section = _toml_section(pyproject, "project.scripts")
    extras_section = _toml_section(pyproject, "project.optional-dependencies")
    project_version = _toml_string(project_section, "version")
    validator.require(
        bool(project_version and _VERSION_PATTERN.fullmatch(project_version)),
        "pyproject.toml must declare a valid project version",
    )
    validator.require(
        _toml_string(scripts_section, "watchdock-mcp") == MCP_ENTRY_POINT,
        f"watchdock-mcp entry point must be {MCP_ENTRY_POINT}",
    )
    validator.require(
        _toml_string_array(extras_section, "mcp") == [MCP_REQUIREMENT],
        f"the mcp extra must contain exactly {MCP_REQUIREMENT}",
    )

    package_source = validator.read_text(PACKAGE_VERSION_PATH)
    package_version = _ast_string_assignment(package_source, "__version__")
    validator.require(package_version == project_version, "package __version__ mismatch")

    mcp_source = validator.read_text(MCP_SERVER_PATH)
    declared_tools, registered_tools = _mcp_server_tools(mcp_source)
    validator.require(declared_tools == MCP_TOOLS, "MCP_TOOL_NAMES must match the release inventory exactly")
    validator.require(registered_tools == MCP_TOOLS, "registered MCP tools must match the release inventory exactly")
    validator.require(
        not any(token in name for name in MCP_TOOLS for token in ("approve", "execute", "move", "rename", "delete", "copy")),
        "MCP inventory contains a filesystem execution or approval surface",
    )

    plugin_files = _validate_plugin_tree(validator)
    _validate_manifests(validator, project_version, plugin_files)
    _validate_skills(validator)

    if validator.errors:
        raise DistributionValidationError(validator.errors)
    assert project_version is not None
    return DistributionInfo(version=project_version, plugin_files=plugin_files)


def _archive_entries(repo_root: Path, info: DistributionInfo) -> list[tuple[PurePosixPath, bytes]]:
    prefix = PurePosixPath(f"watchdock-agent-{info.version}")
    entries = [
        (prefix / MARKETPLACE_PATH.as_posix(), (repo_root / MARKETPLACE_PATH).read_bytes()),
        (
            prefix / CODEX_MARKETPLACE_PATH.as_posix(),
            (repo_root / CODEX_MARKETPLACE_PATH).read_bytes(),
        ),
        (prefix / "LICENSE", (repo_root / "LICENSE").read_bytes()),
        (
            prefix / "README.md",
            (repo_root / "scripts/agent_plugin_README.md")
            .read_text(encoding="utf-8")
            .replace("{version}", info.version)
            .encode("utf-8"),
        ),
    ]
    entries.extend(
        (
            prefix / PLUGIN_PATH.as_posix() / relative_path.as_posix(),
            (repo_root / PLUGIN_PATH / relative_path).read_bytes(),
        )
        for relative_path in info.plugin_files
    )
    return sorted(entries, key=lambda item: item[0].as_posix())


def _write_zip_member(archive: zipfile.ZipFile, name: PurePosixPath, payload: bytes) -> None:
    info = zipfile.ZipInfo(name.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def validate_agent_archive(
    archive_path: Path, repo_root: Path, distribution: DistributionInfo | None = None
) -> None:
    """Verify that an archive is an exact, safe copy of the validated sources."""

    root = repo_root.resolve()
    info = distribution or validate_agent_distribution(root)
    expected = {
        name.as_posix(): payload
        for name, payload in _archive_entries(root, info)
    }
    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                errors.append("archive contains duplicate member names")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    errors.append(f"unsafe archive member: {name}")
            if set(names) != set(expected):
                missing = sorted(set(expected) - set(names))
                unexpected = sorted(set(names) - set(expected))
                if missing:
                    errors.append("archive is missing: " + ", ".join(missing))
                if unexpected:
                    errors.append("archive contains unexpected files: " + ", ".join(unexpected))
            for name, payload in expected.items():
                if name in names and archive.read(name) != payload:
                    errors.append(f"archive payload differs from source: {name}")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"cannot read archive {archive_path}: {exc}")
    if errors:
        raise DistributionValidationError(errors)


def package_agent_distribution(repo_root: Path, output_directory: Path) -> Path:
    """Build and revalidate a deterministic, versioned marketplace ZIP."""

    root = repo_root.resolve()
    info = validate_agent_distribution(root)
    destination = output_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / f"watchdock-agent-{info.version}.zip"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        for name, payload in _archive_entries(root, info):
            _write_zip_member(archive, name, payload)
    validate_agent_archive(archive_path, root, info)
    return archive_path


def sha256_file(path: Path) -> str:
    """Return a lowercase SHA-256 digest without loading the whole file."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_validation_success(info: DistributionInfo) -> str:
    """Return a stable one-line validator summary for CI logs."""

    return (
        f"validated watchdock-agent {info.version}: {len(info.plugin_files)} files, "
        f"{len(SKILL_TOOLS)} skills, {len(MCP_TOOLS)} MCP tools"
    )


def expected_archive_members(repo_root: Path) -> Iterable[str]:
    """Expose expected names for focused tests and downstream release checks."""

    root = repo_root.resolve()
    info = validate_agent_distribution(root)
    return tuple(name.as_posix() for name, _payload in _archive_entries(root, info))
