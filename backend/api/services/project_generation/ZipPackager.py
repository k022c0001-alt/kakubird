"""Create safe, deterministic ZIP archives from validated projects."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass
class ZipPackageResult:
    """Backward-compatible packaging result consumed by ProjectBuildService."""

    success: bool
    project_name: str
    zip_path: Optional[str] = None
    files_added: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "project_name": self.project_name,
            "zip_path": self.zip_path,
            "files_added": self.files_added,
            "error": self.error,
        }


class ZipPackager:
    """Package one project without following links or executing its contents.

    The public ``package`` method and constructor's ``zip_output_dir`` argument
    remain compatible with the original implementation. Alias methods support
    every name currently probed by ``ProjectBuildService``.
    """

    DEFAULT_IGNORES = {
        ".DS_Store",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "coverage",
        "dist",
        "generated_zips",
        "node_modules",
    }
    _CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
    _UNSAFE_NAME_CHARACTER = re.compile(r"[<>:\"/\\|?*]")
    _WINDOWS_RESERVED_NAMES = {
        "aux",
        "com1",
        "com2",
        "com3",
        "com4",
        "com5",
        "com6",
        "com7",
        "com8",
        "com9",
        "con",
        "lpt1",
        "lpt2",
        "lpt3",
        "lpt4",
        "lpt5",
        "lpt6",
        "lpt7",
        "lpt8",
        "lpt9",
        "nul",
        "prn",
    }
    _ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

    def __init__(
        self,
        zip_output_dir: str = "generated_zips",
        *,
        output_root: Optional[str] = None,
        zip_output_root: Optional[str] = None,
        enable_debug: bool = False,
        max_files: int = 10_000,
        max_file_bytes: int = 100 * 1024 * 1024,
        max_total_bytes: int = 500 * 1024 * 1024,
        compression_level: int = 6,
    ) -> None:
        # ProjectBuildService historically used three names for the same path.
        selected_output = zip_output_root or output_root or zip_output_dir
        self.zip_output_dir = Path(selected_output).expanduser().resolve()
        self.enable_debug = bool(enable_debug)
        self.max_files = max(1, int(max_files))
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_total_bytes = max(1, int(max_total_bytes))
        self.compression_level = min(9, max(0, int(compression_level)))
        self.last_diagnostics: List[str] = []
        self.zip_output_dir.mkdir(parents=True, exist_ok=True)
        if not self.zip_output_dir.is_dir() or self.zip_output_dir.is_symlink():
            raise ValueError("ZIP出力先が安全なディレクトリではありません。")

    def package(
        self,
        project_root: str,
        project_name: Optional[str] = None,
        ignore_names: Optional[List[str]] = None,
    ) -> ZipPackageResult:
        """Create ``<safe-name>.zip`` and return a structured result."""
        self.last_diagnostics = []
        source = Path(project_root).expanduser()
        display_name = self._safe_name(project_name or source.name or "project")

        if source.is_symlink():
            return self._failure(display_name, "project_rootにシンボリックリンクは使用できません。")
        root = source.resolve()
        if not root.exists():
            return self._failure(display_name, "プロジェクトフォルダが存在しません。")
        if not root.is_dir():
            return self._failure(display_name, "project_rootがディレクトリではありません。")
        if self._is_inside(self.zip_output_dir, root):
            return self._failure(display_name, "ZIP出力先をプロジェクト内には配置できません。")

        try:
            ignores = self._normalize_ignores(ignore_names)
            files, total_bytes = self._collect_files(root, ignores)
        except ValueError as exc:
            return self._failure(display_name, str(exc))
        except OSError:
            return self._failure(display_name, "プロジェクトファイルを確認できませんでした。")

        if not files:
            return self._failure(display_name, "ZIPへ追加できるファイルがありません。")
        self._debug(f"files={len(files)}, source_bytes={total_bytes}")

        zip_path = self.zip_output_dir / f"{display_name}.zip"
        temporary_path: Optional[Path] = None
        files_added = 0
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{display_name}.", suffix=".zip.tmp", dir=str(self.zip_output_dir)
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            with zipfile.ZipFile(
                temporary_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=self.compression_level,
                allowZip64=True,
            ) as archive:
                for path, relative in files:
                    self._write_member(archive, root, path, relative, display_name)
                    files_added += 1
            self._verify_archive(temporary_path, display_name, files_added)
            os.replace(temporary_path, zip_path)
            temporary_path = None
            self._debug(f"created={zip_path}")
            return ZipPackageResult(
                success=True,
                project_name=display_name,
                zip_path=str(zip_path),
                files_added=files_added,
            )
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
            return ZipPackageResult(
                success=False,
                project_name=display_name,
                zip_path=None,
                files_added=files_added,
                error="ZIPファイルの作成に失敗しました。",
            )
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def package_project(
        self,
        project_root: str,
        project_name: Optional[str] = None,
        ignore_names: Optional[List[str]] = None,
    ) -> ZipPackageResult:
        return self.package(project_root, project_name, ignore_names)

    def create_zip(
        self,
        project_root: str,
        project_name: Optional[str] = None,
        ignore_names: Optional[List[str]] = None,
    ) -> ZipPackageResult:
        return self.package(project_root, project_name, ignore_names)

    def pack(
        self,
        project_root: str,
        project_name: Optional[str] = None,
        ignore_names: Optional[List[str]] = None,
    ) -> ZipPackageResult:
        return self.package(project_root, project_name, ignore_names)

    def _collect_files(
        self, root: Path, ignores: set[str]
    ) -> tuple[List[tuple[Path, PurePosixPath]], int]:
        files: List[tuple[Path, PurePosixPath]] = []
        total_bytes = 0
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if self._should_ignore(relative, ignores):
                continue
            if path.is_symlink():
                self._debug(f"ignored symlink: {relative.as_posix()}")
                continue
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not self._is_inside(resolved, root):
                self._debug(f"ignored outside file: {relative.as_posix()}")
                continue
            size = path.stat().st_size
            if size > self.max_file_bytes:
                raise ValueError(f"ファイルサイズが上限を超えています: {relative.as_posix()}")
            total_bytes += size
            if total_bytes > self.max_total_bytes:
                raise ValueError("ZIP対象ファイルの合計サイズが上限を超えています。")
            files.append((path, PurePosixPath(*relative.parts)))
            if len(files) > self.max_files:
                raise ValueError("ZIP対象のファイル数が上限を超えています。")
        return files, total_bytes

    def _write_member(
        self,
        archive: zipfile.ZipFile,
        root: Path,
        path: Path,
        relative: PurePosixPath,
        project_name: str,
    ) -> None:
        resolved = path.resolve()
        if path.is_symlink() or not path.is_file() or not self._is_inside(resolved, root):
            raise ValueError("ZIP作成中に不正なファイルを検出しました。")
        archive_name = (PurePosixPath(project_name) / relative).as_posix()
        self._validate_archive_name(archive_name, project_name)
        info = zipfile.ZipInfo(archive_name, date_time=self._ZIP_TIMESTAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        info.create_system = 3
        with path.open("rb") as source, archive.open(
            info, mode="w", force_zip64=path.stat().st_size >= 2 * 1024**3
        ) as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)

    @classmethod
    def _verify_archive(cls, path: Path, project_name: str, expected_files: int) -> None:
        with zipfile.ZipFile(path, mode="r") as archive:
            names = archive.namelist()
            if len(names) != expected_files or archive.testzip() is not None:
                raise zipfile.BadZipFile("archive verification failed")
            for name in names:
                cls._validate_archive_name(name, project_name)

    @classmethod
    def _validate_archive_name(cls, name: str, project_name: str) -> None:
        member = PurePosixPath(name)
        if (
            member.is_absolute()
            or not member.parts
            or member.parts[0] != project_name
            or any(part in {"", ".", ".."} for part in member.parts)
            or "\\" in name
            or cls._CONTROL_CHARACTER.search(name)
        ):
            raise ValueError("不正なZIP内パスです。")

    @classmethod
    def _normalize_ignores(cls, ignore_names: Optional[Sequence[str]]) -> set[str]:
        ignores = set(cls.DEFAULT_IGNORES)
        for value in ignore_names or []:
            name = str(value or "").strip()
            if name and name not in {".", ".."} and "/" not in name and "\\" not in name:
                ignores.add(name)
        return ignores

    @staticmethod
    def _should_ignore(relative: Path, ignores: Iterable[str]) -> bool:
        ignored = set(ignores)
        return any(part in ignored for part in relative.parts)

    @classmethod
    def _safe_name(cls, name: str) -> str:
        value = unicodedata.normalize("NFKC", str(name or "")).strip()
        value = cls._CONTROL_CHARACTER.sub("-", value)
        value = cls._UNSAFE_NAME_CHARACTER.sub("-", value)
        while ".." in value:
            value = value.replace("..", "-")
        value = re.sub(r"\s+", "-", value).strip(" .-")
        value = re.sub(r"-+", "-", value)[:80].rstrip(" .-")
        if not value or value.casefold() in cls._WINDOWS_RESERVED_NAMES:
            return "generated-project"
        return value

    @staticmethod
    def _is_inside(candidate: Path, root: Path) -> bool:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _failure(project_name: str, message: str) -> ZipPackageResult:
        return ZipPackageResult(success=False, project_name=project_name, error=message)

    def _debug(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self.last_diagnostics.append(text)
        if self.enable_debug and text:
            print(f"📦 [ZipPackager] {text}", flush=True)


__all__ = ["ZipPackageResult", "ZipPackager"]
