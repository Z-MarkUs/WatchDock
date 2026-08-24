"""Safe file organization based on analysis results."""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import shutil
import stat as stat_module
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
        tags = self._safe_tags(analysis.get("tags", []))
        if self.config.move_files:
            destination = self._get_destination_path(source_path, analysis)
            destination = self._handle_name_conflict(
                destination,
                source_path=source_path,
                sidecar_required=True,
            )
            action_type = "move"
        else:
            destination = source_path.parent / self._safe_filename(
                analysis.get("suggested_name"), source_path.name
            )
            destination = self._handle_name_conflict(
                destination,
                source_path=source_path,
                sidecar_required=True,
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
            "tags": tags,
        }

    def execute_proposed_action(
        self, proposed_action: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute the exact normalized action that a user reviewed.

        Unlike :meth:`organize_file`, this method never selects a new conflict
        name. If the reviewed destination has become occupied, execution fails
        and leaves the source untouched so the proposal can be reviewed again.
        """

        source_value = proposed_action.get("from")
        destination_value = proposed_action.get("to")
        action_type = proposed_action.get("action_type")
        tags = self._safe_tags(proposed_action.get("tags", []))
        source = Path(str(source_value or "")).expanduser()
        destination = Path(str(destination_value or "")).expanduser()
        results = self._empty_result(source)

        try:
            if action_type not in {"move", "rename"}:
                raise ValueError("proposed action_type must be move or rename")
            if not source_value or not destination_value:
                raise ValueError("proposed action requires from and to paths")
            source_stat = self._require_regular_source(source)

            safe_name = self._safe_filename(destination.name, source.name)
            if destination.name != safe_name:
                raise ValueError("proposed destination filename is unsafe")

            if action_type == "move":
                self._ensure_within_archive(destination)
            elif not self._same_path(destination.parent, source.parent):
                raise ValueError("rename destination must remain in the source folder")

            if self._path_entry_exists(destination) and not self._same_path(
                destination, source
            ):
                raise FileExistsError(
                    f"reviewed destination already exists: {destination}"
                )
            if self._path_entry_exists(self._metadata_path(destination)):
                raise FileExistsError(
                    f"reviewed metadata destination already exists: "
                    f"{self._metadata_path(destination)}"
                )

            destination.parent.mkdir(parents=True, exist_ok=True)
            if self._same_path(destination, source):
                final_path = source
            else:
                if action_type == "move":
                    self._ensure_within_archive(destination)
                self._move_without_overwrite(
                    source,
                    destination,
                    source_stat,
                    require_archive=action_type == "move",
                )
                final_path = destination
                results["moved" if action_type == "move" else "renamed"] = True

            results["new_path"] = str(final_path)
            self._write_tags_result(results, final_path, tags)
        except (OSError, ValueError) as exc:
            results["error"] = str(exc)
            logger.error("Could not execute reviewed action for %s: %s", source, exc)
        return results

    def organize_file(self, file_path: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Organize one file and return a structured operation result."""

        source_path = Path(file_path).expanduser()
        results = self._empty_result(source_path)

        try:
            source_stat = self._require_regular_source(source_path)
            tags = self._safe_tags(analysis.get("tags", []))

            if self.config.move_files:
                destination = self._get_destination_path(source_path, analysis)
                if self._same_path(destination, source_path):
                    final_path = source_path
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination = self._handle_name_conflict(
                        destination,
                        source_path=source_path,
                        sidecar_required=True,
                    )
                    self._ensure_within_archive(destination)
                    self._move_without_overwrite(
                        source_path,
                        destination,
                        source_stat,
                        require_archive=True,
                    )
                    final_path = destination
                    results["moved"] = True
                    logger.info("Moved %s -> %s", source_path, destination)
            else:
                new_name = self._safe_filename(
                    analysis.get("suggested_name"), source_path.name
                )
                destination = source_path.parent / new_name
                destination = self._handle_name_conflict(
                    destination,
                    source_path=source_path,
                    sidecar_required=True,
                )
                if self._same_path(destination, source_path):
                    final_path = source_path
                else:
                    self._move_without_overwrite(
                        source_path,
                        destination,
                        source_stat,
                        require_archive=False,
                    )
                    final_path = destination
                    results["renamed"] = True
                    logger.info("Renamed %s -> %s", source_path, destination)

            results["new_path"] = str(final_path)
            self._write_tags_result(results, final_path, tags)
        except (OSError, ValueError) as exc:
            logger.error("Error organizing file %s: %s", file_path, exc)
            results["error"] = str(exc)

        return results

    @staticmethod
    def _empty_result(source_path: Path) -> Dict[str, Any]:
        return {
            "original_path": str(source_path),
            "moved": False,
            "renamed": False,
            "new_path": None,
            "tags_applied": False,
            "error": None,
            "warnings": [],
        }

    def _write_tags_result(
        self, results: Dict[str, Any], final_path: Path, tags: list[str]
    ) -> None:
        if not tags:
            return
        try:
            self._apply_tags(final_path, tags)
            results["tags_applied"] = True
        except OSError as exc:
            warning = f"could not write tag metadata: {exc}"
            results["warnings"].append(warning)
            logger.warning("%s", warning)

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

    @staticmethod
    def _require_regular_source(source: Path) -> os.stat_result:
        """Return an lstat result, rejecting symlinks and special files."""

        try:
            source_stat = source.lstat()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"file does not exist: {source}") from exc
        if not stat_module.S_ISREG(source_stat.st_mode):
            raise ValueError(f"path is not a regular file: {source}")
        return source_stat

    @staticmethod
    def _file_identity(file_stat: os.stat_result) -> tuple[int, int, int, int]:
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            file_stat.st_size,
            file_stat.st_mtime_ns,
        )

    @staticmethod
    def _path_entry_exists(path: Path) -> bool:
        """Return true for every directory entry, including broken symlinks."""

        return os.path.lexists(path)

    def _move_without_overwrite(
        self,
        source: Path,
        destination: Path,
        expected_source_stat: os.stat_result,
        *,
        require_archive: bool,
    ) -> None:
        """Move one regular file without ever replacing an existing entry.

        A hard link provides an atomic no-replace move on normal local file
        systems.  Cross-device and hard-link-limited file systems fall back to
        exclusive destination creation followed by a verified copy and source
        unlink.  Both paths verify source identity before removing it.
        """

        if self._path_entry_exists(destination):
            raise FileExistsError(f"destination already exists: {destination}")

        try:
            os.link(source, destination, follow_symlinks=False)
        except FileExistsError:
            raise FileExistsError(f"destination already exists: {destination}")
        except (NotImplementedError, OSError) as link_error:
            if isinstance(link_error, OSError) and link_error.errno == errno.EEXIST:
                raise FileExistsError(f"destination already exists: {destination}")
            self._copy_without_overwrite(
                source,
                destination,
                expected_source_stat,
                require_archive=require_archive,
            )
            return

        # Roll back only the hard link to the source identity we intended to
        # move.  Capturing the destination path after linking would let a
        # concurrent remove-and-replace race trick cleanup into deleting the
        # replacement instead.
        destination_stat = expected_source_stat
        try:
            current_source_stat = self._require_regular_source(source)
            if self._file_identity(current_source_stat) != self._file_identity(
                expected_source_stat
            ):
                raise OSError(f"source changed before it could be moved: {source}")
            current_destination_stat = destination.lstat()
            if (
                current_destination_stat.st_dev,
                current_destination_stat.st_ino,
            ) != (current_source_stat.st_dev, current_source_stat.st_ino):
                raise OSError(f"destination identity changed during move: {destination}")
            if require_archive:
                self._ensure_within_archive(destination)
            source.unlink()
        except Exception:
            self._unlink_if_identity_matches(destination, destination_stat)
            raise

    def _copy_without_overwrite(
        self,
        source: Path,
        destination: Path,
        expected_source_stat: os.stat_result,
        *,
        require_archive: bool,
    ) -> None:
        """Cross-device no-overwrite fallback with rollback on partial copies."""

        destination_stat = None
        try:
            current_source_stat = self._require_regular_source(source)
            if self._file_identity(current_source_stat) != self._file_identity(
                expected_source_stat
            ):
                raise OSError(f"source changed before it could be copied: {source}")

            with source.open("rb") as source_file:
                opened_source_stat = os.fstat(source_file.fileno())
                if self._file_identity(opened_source_stat) != self._file_identity(
                    expected_source_stat
                ):
                    raise OSError(f"source changed while it was opened: {source}")
                with destination.open("xb") as destination_file:
                    destination_stat = os.fstat(destination_file.fileno())
                    shutil.copyfileobj(source_file, destination_file, 1024 * 1024)
                    after_copy_stat = os.fstat(source_file.fileno())
                    if self._file_identity(after_copy_stat) != self._file_identity(
                        expected_source_stat
                    ):
                        raise OSError(f"source changed while it was copied: {source}")
                    destination_file.flush()
                    os.fsync(destination_file.fileno())

            current_destination_stat = destination.lstat()
            if (current_destination_stat.st_dev, current_destination_stat.st_ino) != (
                destination_stat.st_dev,
                destination_stat.st_ino,
            ):
                raise OSError(f"destination identity changed during copy: {destination}")
            shutil.copystat(source, destination, follow_symlinks=False)
            current_source_stat = self._require_regular_source(source)
            if self._file_identity(current_source_stat) != self._file_identity(
                expected_source_stat
            ):
                raise OSError(f"source changed before copy completion: {source}")
            current_destination_stat = destination.lstat()
            if (current_destination_stat.st_dev, current_destination_stat.st_ino) != (
                destination_stat.st_dev,
                destination_stat.st_ino,
            ):
                raise OSError(f"destination identity changed during copy: {destination}")
            if require_archive:
                self._ensure_within_archive(destination)
            source.unlink()
        except Exception:
            if destination_stat is not None:
                self._unlink_if_identity_matches(destination, destination_stat)
            raise

    @classmethod
    def _unlink_if_identity_matches(
        cls, path: Path, expected_stat: os.stat_result
    ) -> None:
        """Best-effort rollback that will not unlink a replaced destination."""

        try:
            current = path.lstat()
            # POSIX file systems can immediately recycle an inode after an
            # unlink.  Device/inode alone can therefore describe a different
            # file that appeared at the same path.  Fail closed unless the
            # complete captured identity still matches.
            if (
                stat_module.S_ISREG(current.st_mode)
                and cls._file_identity(current) == cls._file_identity(expected_stat)
            ):
                path.unlink()
            else:
                logger.warning(
                    "Skipped rollback because destination identity changed: %s",
                    path,
                )
        except OSError:
            logger.error("Could not roll back incomplete destination: %s", path)

    @classmethod
    def _safe_filename(cls, suggested_name: Any, original_name: str) -> str:
        original = cls._safe_component(original_name, fallback="file")
        candidate = cls._safe_component(suggested_name, fallback=original)

        original_suffix = "".join(Path(original).suffixes)
        if original_suffix and not candidate.lower().endswith(original_suffix.lower()):
            candidate_stem = Path(candidate).stem or Path(original).stem or "file"
            candidate = f"{candidate_stem}{original_suffix}"
        if original_suffix:
            candidate_stem = candidate[: -len(original_suffix)]
            available_stem_length = max(1, 240 - len(original_suffix))
            candidate_stem = candidate_stem[:available_stem_length].rstrip(" ._")
            return f"{candidate_stem or 'file'}{original_suffix}"
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

    @classmethod
    def _handle_name_conflict(
        cls,
        path: Path,
        *,
        source_path: Path | None = None,
        sidecar_required: bool = False,
    ) -> Path:
        def candidate_is_available(candidate: Path) -> bool:
            destination_available = not cls._path_entry_exists(candidate) or (
                source_path is not None and cls._same_path(candidate, source_path)
            )
            sidecar_available = not sidecar_required or not cls._path_entry_exists(
                cls._metadata_path(candidate)
            )
            return destination_available and sidecar_available

        if candidate_is_available(path):
            return path

        suffix = "".join(path.suffixes)
        stem = path.name[: -len(suffix)] if suffix else path.name
        for counter in range(1, 100_000):
            candidate = path.with_name(f"{stem}_{counter}{suffix}")
            if candidate_is_available(candidate):
                return candidate
        raise FileExistsError(f"could not find an available name for {path.name}")

    @staticmethod
    def _metadata_path(file_path: Path) -> Path:
        return file_path.with_name(f"{file_path.name}.watchdock.json")

    def _apply_tags(self, file_path: Path, tags: Iterable[str]) -> None:
        metadata_path = self._metadata_path(file_path)
        metadata = {
            "tags": list(tags),
            "tagged_at": self._now().isoformat(timespec="seconds"),
            "file": file_path.name,
        }

        descriptor = os.open(
            metadata_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        created_stat = os.fstat(descriptor)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(metadata, output, indent=2, ensure_ascii=False)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            self._unlink_if_identity_matches(metadata_path, created_stat)
            raise
