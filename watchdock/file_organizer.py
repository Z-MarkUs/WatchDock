"""Safe file organization based on analysis results."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

from watchdock.config import ArchiveConfig

logger = logging.getLogger(__name__)

_INVALID_COMPONENTS = re.compile(r"[<>:\"/\\|?*\x00-\x1f]")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FileOrganizer:
    """Move or rename files according to an :class:`ArchiveConfig`."""

    def __init__(
        self,
        config: ArchiveConfig,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        if not isinstance(config, ArchiveConfig):
            raise TypeError("FileOrganizer requires an ArchiveConfig")
        errors = config.validate()
        if errors:
            raise ValueError("; ".join(errors))

        self.config = config
        self.archive_base = Path(config.base_path).expanduser()
        self.archive_base.mkdir(parents=True, exist_ok=True)
        self._now = now

    def get_proposed_action(
        self, file_path: str, analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Describe an organization action without changing the file system."""

        source_path = Path(file_path).expanduser()
        if self.config.move_files:
            destination = self._get_destination_path(source_path, analysis)
            action_type = "move"
        else:
            destination = source_path.parent / self._safe_filename(
                analysis.get("suggested_name"), source_path.name
            )
            action_type = "rename"

        return {
            "action_type": action_type,
            "from": str(source_path),
            "to": str(destination),
            "new_name": destination.name,
            "category": self._safe_component(
                analysis.get("category"), fallback="Other"
            ),
            "tags": self._safe_tags(analysis.get("tags", [])),
        }

    def organize_file(self, file_path: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Organize one file and return a structured operation result."""

        source_path = Path(file_path).expanduser()
        results: Dict[str, Any] = {
            "original_path": str(source_path),
            "moved": False,
            "renamed": False,
            "new_path": None,
            "tags_applied": False,
            "error": None,
            "warnings": [],
        }

        try:
            if not source_path.exists():
                raise FileNotFoundError(f"file does not exist: {source_path}")
            if not source_path.is_file():
                raise ValueError(f"path is not a regular file: {source_path}")

            if self.config.move_files:
                destination = self._get_destination_path(source_path, analysis)
                if self._same_path(destination, source_path):
                    final_path = source_path
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination = self._handle_name_conflict(destination)
                    shutil.move(str(source_path), str(destination))
                    final_path = destination
                    results["moved"] = True
                    logger.info("Moved %s -> %s", source_path, destination)
            else:
                new_name = self._safe_filename(
                    analysis.get("suggested_name"), source_path.name
                )
                destination = source_path.parent / new_name
                if self._same_path(destination, source_path):
                    final_path = source_path
                else:
                    destination = self._handle_name_conflict(destination)
                    source_path.rename(destination)
                    final_path = destination
                    results["renamed"] = True
                    logger.info("Renamed %s -> %s", source_path, destination)

            results["new_path"] = str(final_path)
            tags = self._safe_tags(analysis.get("tags", []))
            if tags:
                try:
                    self._apply_tags(final_path, tags)
                    results["tags_applied"] = True
                except OSError as exc:
                    warning = f"could not write tag metadata: {exc}"
                    results["warnings"].append(warning)
                    logger.warning("%s", warning)
        except (OSError, ValueError) as exc:
            logger.error("Error organizing file %s: %s", file_path, exc)
            results["error"] = str(exc)

        return results

    def is_managed_path(self, file_path: str) -> bool:
        """Return whether a path is already under the configured archive."""

        try:
            Path(file_path).expanduser().resolve(strict=False).relative_to(
                self.archive_base.resolve(strict=False)
            )
            return True
        except ValueError:
            return False

    def _get_destination_path(
        self, source_path: Path, analysis: Dict[str, Any]
    ) -> Path:
        destination = self.archive_base
        if self.config.create_date_folders:
            destination /= self._now().strftime("%Y-%m")
        if self.config.create_category_folders:
            destination /= self._safe_component(
                analysis.get("category"), fallback="Other"
            )

        destination /= self._safe_filename(
            analysis.get("suggested_name"), source_path.name
        )
        self._ensure_within_archive(destination)
        return destination

    def _ensure_within_archive(self, destination: Path) -> None:
        try:
            destination.resolve(strict=False).relative_to(
                self.archive_base.resolve(strict=False)
            )
        except ValueError as exc:
            raise ValueError("destination escapes the configured archive") from exc

    @classmethod
    def _safe_filename(cls, suggested_name: Any, original_name: str) -> str:
        original = cls._safe_component(original_name, fallback="file")
        candidate = cls._safe_component(suggested_name, fallback=original)

        original_suffix = "".join(Path(original).suffixes)
        if original_suffix and not candidate.lower().endswith(original_suffix.lower()):
            candidate_stem = Path(candidate).stem or Path(original).stem or "file"
            candidate = f"{candidate_stem}{original_suffix}"
        return candidate[:240] or original

    @staticmethod
    def _safe_component(value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        text = _INVALID_COMPONENTS.sub("_", text)
        text = re.sub(r"\s+", "_", text)
        text = re.sub(r"_+", "_", text).strip(" ._")
        if not text or text in {".", ".."}:
            text = fallback

        stem = text.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            text = f"_{text}"
        return text[:240]

    @staticmethod
    def _safe_tags(tags: Any) -> list[str]:
        if not isinstance(tags, (list, tuple, set)):
            return []
        cleaned = []
        for tag in tags:
            value = str(tag).strip()
            if value and value not in cleaned:
                cleaned.append(value[:64])
        return cleaned[:50]

    @staticmethod
    def _same_path(first: Path, second: Path) -> bool:
        return os.path.normcase(str(first.resolve(strict=False))) == os.path.normcase(
            str(second.resolve(strict=False))
        )

    @staticmethod
    def _handle_name_conflict(path: Path) -> Path:
        if not path.exists():
            return path

        suffix = "".join(path.suffixes)
        stem = path.name[: -len(suffix)] if suffix else path.name
        for counter in range(1, 100_000):
            candidate = path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
        raise FileExistsError(f"could not find an available name for {path.name}")

    def _apply_tags(self, file_path: Path, tags: Iterable[str]) -> None:
        metadata_path = file_path.with_name(f"{file_path.name}.watchdock.json")
        metadata = {
            "tags": list(tags),
            "tagged_at": self._now().isoformat(timespec="seconds"),
            "file": file_path.name,
        }

        descriptor, temporary_name = tempfile.mkstemp(
            dir=str(metadata_path.parent),
            prefix=f".{metadata_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(metadata, output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, metadata_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
