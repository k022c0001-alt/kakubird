"""Safely persist GeneratedFile objects beneath one project directory."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

from .BuildPlan import BuildPlan
from .FileGenerator import GeneratedFile


_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class WrittenFile:
    """Result of attempting to write one generated file."""

    path: str
    absolute_path: str
    status: str = "success"
    bytes_written: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "absolute_path": self.absolute_path,
            "status": self.status,
            "bytes_written": self.bytes_written,
            "error": self.error,
        }


@dataclass
class FileWriteResult:
    """Aggregate result consumed by ProjectBuildService and the UI block."""

    project_name: str
    project_root: str
    files: List[WrittenFile] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.files) and not self.errors and all(item.success for item in self.files)

    @property
    def files_written(self) -> int:
        return sum(1 for item in self.files if item.success)

    @property
    def files_failed(self) -> int:
        return sum(1 for item in self.files if not item.success)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_root": self.project_root,
            "success": self.success,
            "files_written": self.files_written,
            "files_failed": self.files_failed,
            "files": [item.to_dict() for item in self.files],
            "errors": list(self.errors),
        }


class FileWriter:
    """Write generated UTF-8 text files without escaping the project root.

    The public API remains compatible with the earlier implementation. Writes
    are atomic per file, and existing project deletion is limited to the exact
    validated child directory selected by ``plan.project_name``.
    """

    def __init__(
        self,
        output_root: str = "generated_projects",
        overwrite: bool = True,
        enable_debug: bool = False,
        max_file_bytes: int = 5 * 1024 * 1024,
        strict_plan: bool = True,
    ) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.overwrite = bool(overwrite)
        self.enable_debug = bool(enable_debug)
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.strict_plan = bool(strict_plan)
        self.last_diagnostics: List[str] = []
        self.output_root.mkdir(parents=True, exist_ok=True)
        if not self.output_root.is_dir():
            raise ValueError("output_rootがディレクトリではありません。")

    def write_project(
        self,
        plan: BuildPlan,
        generated_files: List[GeneratedFile],
        clean_existing: bool = False,
    ) -> FileWriteResult:
        """Write a generated project and return per-file outcomes."""
        if not isinstance(plan, BuildPlan):
            raise TypeError("plan must be a BuildPlan")
        plan.validate_or_raise()
        if not isinstance(generated_files, list):
            raise TypeError("generated_files must be a list")

        self.last_diagnostics = []
        project_name = self._safe_project_name(plan.project_name)
        project_root = self._resolve_project_root(project_name)
        result = FileWriteResult(project_name=project_name, project_root=str(project_root))

        if not generated_files:
            result.errors.append("書き込み対象の生成ファイルがありません。")
            return result
        if len(generated_files) > plan.MAX_FILES:
            result.errors.append(f"書き込み対象は{plan.MAX_FILES}件以内にしてください。")
            return result

        if clean_existing and project_root.exists():
            self._clean_project_root(project_root)
        project_root.mkdir(parents=True, exist_ok=True)

        declared = {item.path.casefold() for item in plan.files}
        seen: set[str] = set()
        for generated in generated_files:
            if not isinstance(generated, GeneratedFile):
                written = WrittenFile(
                    path="",
                    absolute_path="",
                    status="error",
                    error="GeneratedFile以外の値は書き込めません。",
                )
            else:
                normalized = str(generated.path or "").replace("\\", "/").strip()
                key = normalized.casefold()
                if key in seen:
                    written = WrittenFile(
                        path=normalized,
                        absolute_path="",
                        status="error",
                        error=f"生成ファイルが重複しています: {normalized}",
                    )
                elif self.strict_plan and key not in declared:
                    written = WrittenFile(
                        path=normalized,
                        absolute_path="",
                        status="error",
                        error=f"BuildPlanに存在しないファイルです: {normalized}",
                    )
                else:
                    written = self._write_file(project_root=project_root, generated=generated)
                seen.add(key)

            result.files.append(written)
            if not written.success:
                result.errors.append(
                    written.error or f"ファイル書き込みに失敗しました: {written.path}"
                )
        return result

    def _write_file(self, project_root: Path, generated: GeneratedFile) -> WrittenFile:
        """Write one file. RepairEngine intentionally uses this method directly."""
        relative_path = str(generated.path or "").replace("\\", "/").strip()
        if generated.status != "success":
            return WrittenFile(
                path=relative_path,
                absolute_path="",
                status="error",
                error=generated.error or "生成に失敗したファイルです。",
            )

        try:
            target = self._resolve_safe_path(project_root, relative_path)
        except ValueError as exc:
            return WrittenFile(
                path=relative_path,
                absolute_path="",
                status="error",
                error=str(exc),
            )

        if target.exists() and not self.overwrite:
            return WrittenFile(
                path=relative_path,
                absolute_path=str(target),
                status="error",
                error=f"既にファイルが存在します: {relative_path}",
            )
        if target.exists() and not target.is_file():
            return WrittenFile(
                path=relative_path,
                absolute_path=str(target),
                status="error",
                error=f"書き込み先がファイルではありません: {relative_path}",
            )

        content = str(generated.content or "")
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            return WrittenFile(
                path=relative_path,
                absolute_path=str(target),
                status="error",
                error=f"ファイルサイズが上限を超えています: {relative_path}",
            )

        temporary_path: Optional[Path] = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Re-resolve after mkdir so a pre-existing symlinked parent cannot
            # redirect the actual write outside the project directory.
            target = self._resolve_safe_path(project_root, relative_path)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
            self._debug(f"wrote {relative_path} ({len(encoded)} bytes)")
            return WrittenFile(
                path=relative_path,
                absolute_path=str(target),
                bytes_written=len(encoded),
            )
        except Exception as exc:
            self._debug(f"write failed for {relative_path}: {exc}")
            return WrittenFile(
                path=relative_path,
                absolute_path=str(target),
                status="error",
                error=f"ファイルの書き込みに失敗しました: {relative_path}",
            )
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _resolve_project_root(self, project_name: str) -> Path:
        candidate = self.output_root / project_name
        if candidate == self.output_root or candidate.is_symlink():
            raise ValueError("不正なproject pathです。")
        resolved = candidate.resolve()
        if not self._is_inside_root(resolved, self.output_root):
            raise ValueError("不正なproject pathです。")
        return resolved

    def _clean_project_root(self, project_root: Path) -> None:
        if (
            project_root == self.output_root
            or not self._is_inside_root(project_root, self.output_root)
            or project_root.is_symlink()
        ):
            raise ValueError("安全でないプロジェクト削除を拒否しました。")
        shutil.rmtree(project_root)
        self._debug(f"cleaned existing project: {project_root.name}")

    def _resolve_safe_path(self, project_root: Path, relative_path: str) -> Path:
        normalized = str(relative_path or "").replace("\\", "/").strip()
        if not normalized:
            raise ValueError("空のファイルパスです。")
        if (
            normalized.startswith(("/", "//", "~"))
            or _WINDOWS_ABSOLUTE.match(normalized)
            or _CONTROL_CHARACTER.search(normalized)
        ):
            raise ValueError(f"絶対パスまたは不正なパスは禁止されています: {normalized}")
        parts = PurePosixPath(normalized).parts
        if any(part in {"", ".", ".."} for part in parts) or normalized.endswith("/"):
            raise ValueError(f"相対移動またはディレクトリ形式のパスは禁止されています: {normalized}")

        root = project_root.resolve()
        if not self._is_inside_root(root, self.output_root):
            raise ValueError("project_rootがoutput_rootの外部です。")
        target = (root / Path(*parts)).resolve()
        if target == root or not self._is_inside_root(target, root):
            raise ValueError("project_root外への書き込みは禁止されています。")
        return target

    @staticmethod
    def _is_inside_root(target: Path, root: Path) -> bool:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _safe_project_name(project_name: str) -> str:
        value = str(project_name or "generated-app").strip().lower().replace("_", "-")
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[^a-z0-9.-]", "-", value)
        value = re.sub(r"-+", "-", value).strip("-.")
        if value in {"", ".", ".."}:
            return "generated-app"
        return value[:80].rstrip("-.") or "generated-app"

    def _debug(self, message: str) -> None:
        self.last_diagnostics.append(message)
        if self.enable_debug:
            print(f"[FileWriter] {message}", flush=True)


__all__ = ["FileWriter", "FileWriteResult", "WrittenFile"]
