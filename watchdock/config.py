"""Configuration models, validation, and persistence for WatchDock."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SUPPORTED_AI_PROVIDERS = {"openai", "anthropic", "ollama"}
SUPPORTED_MODES = {"auto", "hitl"}
SUPPORTED_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}


@dataclass
class WatchedFolder:
    """A folder monitored for new or changed files."""

    path: str
    enabled: bool = True
    recursive: bool = True
    file_extensions: Optional[List[str]] = None

    def __post_init__(self) -> None:
        self.path = str(Path(self.path).expanduser()) if self.path else ""
        if self.file_extensions is not None:
            normalized = []
            for extension in self.file_extensions:
                value = str(extension).strip().lower()
                if not value:
                    continue
                normalized.append(value if value.startswith(".") else f".{value}")
            self.file_extensions = sorted(set(normalized))

    def validate(self) -> List[str]:
        errors = []
        if not self.path.strip():
            errors.append("watched folder path cannot be empty")
        return errors


@dataclass
class AIConfig:
    """AI provider settings.

    API keys may be supplied directly for backwards compatibility, but the
    provider-specific environment variables are preferred.
    """

    provider: str = "openai"
    api_key: Optional[str] = None
    model: str = "gpt-5.6-luna"
    base_url: Optional[str] = None
    temperature: float = 0.3

    def __post_init__(self) -> None:
        self.provider = self.provider.strip().lower()
        self.model = self.model.strip()
        if self.base_url:
            self.base_url = self.base_url.strip().rstrip("/")

    def resolved_api_key(self) -> Optional[str]:
        """Return an explicit or environment-provided API key."""

        value = (self.api_key or "").strip()
        placeholders = {"your-api-key-here", "changeme", "none", "null"}
        if value and value.lower() not in placeholders:
            return value

        environment_names = {
            "openai": ("WATCHDOCK_OPENAI_API_KEY", "OPENAI_API_KEY"),
            "anthropic": ("WATCHDOCK_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        }
        for name in environment_names.get(self.provider, ()):
            environment_value = os.environ.get(name, "").strip()
            if environment_value:
                return environment_value
        return None

    def validate(self) -> List[str]:
        errors = []
        if self.provider not in SUPPORTED_AI_PROVIDERS:
            errors.append(
                "ai_config.provider must be one of: "
                + ", ".join(sorted(SUPPORTED_AI_PROVIDERS))
            )
        if not self.model:
            errors.append("ai_config.model cannot be empty")
        if not isinstance(self.temperature, (int, float)) or not (
            0 <= self.temperature <= 2
        ):
            errors.append("ai_config.temperature must be between 0 and 2")
        if self.provider == "ollama" and self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append("ai_config.base_url must be a valid HTTP(S) URL")
        return errors


@dataclass
class ArchiveConfig:
    """File organization destination and layout settings."""

    base_path: str
    create_date_folders: bool = True
    create_category_folders: bool = True
    move_files: bool = True

    def __post_init__(self) -> None:
        self.base_path = (
            str(Path(self.base_path).expanduser()) if self.base_path else ""
        )

    def validate(self) -> List[str]:
        if not self.base_path.strip():
            return ["archive_config.base_path cannot be empty"]
        return []


@dataclass
class WatchDockConfig:
    """Complete WatchDock configuration."""

    watched_folders: List[WatchedFolder]
    ai_config: AIConfig
    archive_config: ArchiveConfig
    log_level: str = "INFO"
    check_interval: float = 1.0
    mode: str = "auto"

    def __post_init__(self) -> None:
        self.log_level = self.log_level.strip().upper()
        self.mode = self.mode.strip().lower()

    @classmethod
    def load(cls, config_path: str) -> "WatchDockConfig":
        """Load and validate a JSON configuration file.

        Missing sections and fields inherit safe defaults so older WatchDock
        configuration files continue to work as the schema evolves.
        """

        path = Path(config_path).expanduser()
        if not path.exists():
            return cls.default()

        try:
            with path.open("r", encoding="utf-8") as config_file:
                data = json.load(config_file)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSON in {path} at line {exc.lineno}, column {exc.colno}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError("configuration root must be a JSON object")

        defaults = cls.default()
        watched_data = data.get("watched_folders")
        if watched_data is None:
            watched_folders = defaults.watched_folders
        elif not isinstance(watched_data, list):
            raise ValueError("watched_folders must be a JSON array")
        else:
            try:
                watched_folders = [WatchedFolder(**item) for item in watched_data]
            except (TypeError, AttributeError) as exc:
                raise ValueError(f"invalid watched_folders entry: {exc}") from exc

        ai_data = _merged_section(asdict(defaults.ai_config), data, "ai_config")
        archive_data = _merged_section(
            asdict(defaults.archive_config), data, "archive_config"
        )
        try:
            config = cls(
                watched_folders=watched_folders,
                ai_config=AIConfig(**ai_data),
                archive_config=ArchiveConfig(**archive_data),
                log_level=data.get("log_level", defaults.log_level),
                check_interval=data.get("check_interval", defaults.check_interval),
                mode=data.get("mode", defaults.mode),
            )
        except (TypeError, AttributeError, ValueError) as exc:
            raise ValueError(f"invalid configuration value: {exc}") from exc

        config.validate()
        return config

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""

        return {
            "watched_folders": [asdict(folder) for folder in self.watched_folders],
            "ai_config": asdict(self.ai_config),
            "archive_config": asdict(self.archive_config),
            "log_level": self.log_level,
            "check_interval": self.check_interval,
            "mode": self.mode,
        }

    def save(self, config_path: str) -> None:
        """Validate and atomically save configuration as UTF-8 JSON."""

        self.validate()
        path = Path(config_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(self.to_dict(), output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def validate(self) -> None:
        """Raise ``ValueError`` when configuration is unsafe or malformed."""

        errors = []
        if not isinstance(self.watched_folders, list):
            errors.append("watched_folders must be a list")
        else:
            for index, folder in enumerate(self.watched_folders):
                if not isinstance(folder, WatchedFolder):
                    errors.append(f"watched_folders[{index}] is invalid")
                    continue
                errors.extend(
                    f"watched_folders[{index}]: {error}" for error in folder.validate()
                )

        errors.extend(self.ai_config.validate())
        errors.extend(self.archive_config.validate())
        if self.mode not in SUPPORTED_MODES:
            errors.append("mode must be one of: auto, hitl")
        if self.log_level not in SUPPORTED_LOG_LEVELS:
            errors.append(
                "log_level must be one of: " + ", ".join(sorted(SUPPORTED_LOG_LEVELS))
            )
        if (
            not isinstance(self.check_interval, (int, float))
            or self.check_interval <= 0
        ):
            errors.append("check_interval must be greater than 0")

        archive_path = Path(self.archive_config.base_path).resolve(strict=False)
        seen_paths = set()
        for index, folder in enumerate(self.watched_folders):
            if not isinstance(folder, WatchedFolder) or not folder.path:
                continue
            watched_path = Path(folder.path).resolve(strict=False)
            normalized = os.path.normcase(str(watched_path))
            if normalized in seen_paths:
                errors.append(f"watched_folders[{index}] duplicates another folder")
            seen_paths.add(normalized)
            if folder.enabled and _paths_overlap(watched_path, archive_path):
                errors.append(
                    f"watched_folders[{index}] overlaps archive_config.base_path"
                )

        if errors:
            raise ValueError("; ".join(errors))

    @classmethod
    def default(cls) -> "WatchDockConfig":
        """Create a working default configuration for the current user."""

        home = Path.home()
        return cls(
            watched_folders=[
                WatchedFolder(
                    path=str(home / "Downloads"),
                    enabled=True,
                    recursive=False,
                    file_extensions=None,
                )
            ],
            ai_config=AIConfig(
                provider="openai",
                model="gpt-5.6-luna",
                temperature=0.3,
            ),
            archive_config=ArchiveConfig(
                base_path=str(home / "Documents" / "Archive"),
                create_date_folders=True,
                create_category_folders=True,
                move_files=True,
            ),
            mode="hitl",
        )


def _merged_section(
    default_values: Dict[str, Any], data: Dict[str, Any], section_name: str
) -> Dict[str, Any]:
    section = data.get(section_name, {})
    if section is None:
        section = {}
    if not isinstance(section, dict):
        raise ValueError(f"{section_name} must be a JSON object")
    merged = default_values.copy()
    merged.update(section)
    return merged


def _paths_overlap(first: Path, second: Path) -> bool:
    try:
        first.relative_to(second)
        return True
    except ValueError:
        try:
            second.relative_to(first)
            return True
        except ValueError:
            return False
