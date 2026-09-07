"""Orchestrate project planning, generation, validation, repair and packaging."""

from __future__ import annotations

import inspect
import logging
import math
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .BuildPlan import BuildPlan
from .FileGenerator import FileGenerator, GeneratedFile
from .FileWriter import FileWriteResult, FileWriter
from .ProjectPlanner import ProjectPlanner


_AUTO = object()
logger = logging.getLogger(__name__)

_STEP_PROGRESS = {
    "ProjectPlanner": (2, 15),
    "FileGenerator": (15, 50),
    "FileWriter": (50, 60),
    "BuildValidator": (60, 80),
    "RepairEngine": (80, 90),
    "ZipPackager": (90, 100),
}

try:  # Components are added incrementally in the legacy application.
    from .BuildValidator import BuildValidationResult, BuildValidator
except ImportError:  # pragma: no cover - replaced once the component exists
    BuildValidationResult = Any  # type: ignore[misc,assignment]
    BuildValidator = None  # type: ignore[misc,assignment]

try:
    from .RepairEngine import RepairEngine, RepairResult
except ImportError:  # pragma: no cover - replaced once the component exists
    RepairEngine = None  # type: ignore[misc,assignment]
    RepairResult = Any  # type: ignore[misc,assignment]

try:
    from .ZipPackager import ZipPackager
except ImportError:  # pragma: no cover - standard-library fallback remains available
    ZipPackager = None  # type: ignore[misc,assignment]


@dataclass
class BuildStep:
    """One UI-visible build stage."""

    name: str
    status: str = "pending"
    message: Optional[str] = None
    progress_percent: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    _started_monotonic: Optional[float] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ProjectBuildResult:
    """Backward-compatible payload passed to ProjectBuildBlock.tsx."""

    project_name: str
    status: str = "building"
    message: str = ""
    files_generated: int = 0
    project_root: Optional[str] = None
    zip_path: Optional[str] = None
    zip_download_url: Optional[str] = None
    zip_files_added: int = 0
    plan: Optional[Dict[str, Any]] = None
    generation: List[Dict[str, Any]] = field(default_factory=list)
    write_result: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None
    repair: Optional[Dict[str, Any]] = None
    steps: List[BuildStep] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    progress_percent: int = 0
    current_stage: str = "準備中"
    elapsed_seconds: float = 0.0
    estimated_total_minutes: Optional[int] = None
    estimated_remaining_minutes: Optional[int] = None
    estimate_confidence: str = "low"
    feature_checks: List[Dict[str, Any]] = field(default_factory=list)
    _started_monotonic: float = field(default_factory=time.monotonic, repr=False)

    @property
    def success(self) -> bool:
        return self.status == "success"

    def add_log(self, message: Any) -> None:
        text = str(message or "").strip()
        if text:
            self.logs.append(text)
            logger.info("[ProjectBuild][%s] %s", self.project_name, text)

    def add_error(self, message: Any) -> None:
        text = str(message or "").strip()
        if text and text not in self.errors:
            self.errors.append(text)
            self.add_log(f"❌ {text}")

    def add_warning(self, message: Any) -> None:
        text = str(message or "").strip()
        if text and text not in self.warnings:
            self.warnings.append(text)
            self.add_log(f"⚠️ {text}")

    def add_step(self, name: str, status: str, message: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        start_progress, end_progress = _STEP_PROGRESS.get(
            name, (self.progress_percent, self.progress_percent)
        )
        for step in self.steps:
            if step.name == name:
                step.status = status
                step.message = message
                if status == "building" and not step.started_at:
                    step.started_at = now
                    step._started_monotonic = time.monotonic()
                if status in {"success", "warning", "error"}:
                    step.finished_at = now
                    if step._started_monotonic is not None:
                        step.duration_ms = max(
                            0, int((time.monotonic() - step._started_monotonic) * 1000)
                        )
                step.progress_percent = (
                    start_progress if status == "building" else end_progress
                )
                self._update_progress(name, status, start_progress, end_progress)
                self.add_log(f"{self._status_icon(status)} {message or name}")
                return
        self.steps.append(
            BuildStep(
                name=name,
                status=status,
                message=message,
                progress_percent=start_progress if status == "building" else end_progress,
                started_at=now if status == "building" else None,
                finished_at=now if status in {"success", "warning", "error"} else None,
                _started_monotonic=time.monotonic(),
            )
        )
        self._update_progress(name, status, start_progress, end_progress)
        self.add_log(f"{self._status_icon(status)} {message or name}")

    def configure_estimate(
        self, context: Mapping[str, Any], planned_files: int = 0
    ) -> None:
        features = list(context.get("features") or []) + list(
            context.get("raw_features") or []
        )
        design = list(context.get("design_preferences") or [])
        total = 8 + max(0, planned_files) * 2 + len(features) * 3 + len(design)
        if "authentication" in features:
            total += 5
        combined = " ".join(str(item).lower() for item in [*features, *design])
        if any(word in combined for word in ("animation", "アニメ", "演出", "transition")):
            total += 4
        self.estimated_total_minutes = max(5, min(120, total))
        self.estimate_confidence = "medium" if planned_files else "low"
        self._refresh_timing()

    def set_feature_checks(self, values: Any) -> None:
        if isinstance(values, list):
            self.feature_checks = [
                dict(item) for item in values if isinstance(item, Mapping)
            ]

    def finish(self, *, success: bool) -> None:
        self.elapsed_seconds = round(time.monotonic() - self._started_monotonic, 3)
        if success:
            self.progress_percent = 100
            self.current_stage = "完成"
            self.estimated_remaining_minutes = 0

    def _update_progress(
        self, name: str, status: str, start_progress: int, end_progress: int
    ) -> None:
        self.current_stage = name
        self.progress_percent = max(
            self.progress_percent,
            start_progress if status == "building" else end_progress,
        )
        self._refresh_timing()

    def _refresh_timing(self) -> None:
        self.elapsed_seconds = round(time.monotonic() - self._started_monotonic, 3)
        if self.progress_percent >= 100:
            self.estimated_remaining_minutes = 0
        elif self.estimated_total_minutes is not None:
            remaining = self.estimated_total_minutes * (100 - self.progress_percent) / 100
            self.estimated_remaining_minutes = max(1, math.ceil(remaining))

    @staticmethod
    def _status_icon(status: str) -> str:
        return {
            "building": "🔄",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
        }.get(status, "○")

    def to_dict(self) -> Dict[str, Any]:
        # Keep the legacy keys stable: ChatHandler and ProjectBuildBlock use them.
        return {
            "project_name": self.project_name,
            "status": self.status,
            "message": self.message,
            "files_generated": self.files_generated,
            "project_root": self.project_root,
            "zip_path": self.zip_path,
            "zip_download_url": self.zip_download_url,
            "zip_files_added": self.zip_files_added,
            "plan": self.plan,
            "generation": list(self.generation),
            "write_result": self.write_result,
            "validation": self.validation,
            "repair": self.repair,
            "steps": [step.to_dict() for step in self.steps],
            "logs": list(self.logs),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "progress_percent": self.progress_percent,
            "current_stage": self.current_stage,
            "elapsed_seconds": self.elapsed_seconds,
            "estimated_total_minutes": self.estimated_total_minutes,
            "estimated_remaining_minutes": self.estimated_remaining_minutes,
            "estimate_confidence": self.estimate_confidence,
            "feature_checks": list(self.feature_checks),
        }


class ProjectBuildService:
    """Coordinate specialists without embedding generation logic.

    Existing constructor arguments and ``build`` remain valid. Optional
    dependency injection makes it possible to replace legacy components one at
    a time while the application stays operational.
    """

    def __init__(
        self,
        llm_engine: Optional[Any] = None,
        output_root: str = "generated_projects",
        zip_output_root: str = "generated_zips",
        enable_repair: bool = True,
        max_repair_iterations: int = 3,
        enable_debug: bool = True,
        *,
        project_planner: Optional[Any] = None,
        file_generator: Optional[Any] = None,
        file_writer: Optional[Any] = None,
        build_validator: Any = _AUTO,
        repair_engine: Optional[Any] = None,
        zip_packager: Optional[Any] = None,
        download_url_prefix: str = "/api/projects/download",
    ) -> None:
        self.llm_engine = llm_engine
        self.output_root = Path(output_root).resolve()
        self.zip_output_root = Path(zip_output_root).resolve()
        self.enable_repair = bool(enable_repair)
        self.max_repair_iterations = max(1, int(max_repair_iterations))
        self.enable_debug = bool(enable_debug)
        self.download_url_prefix = "/" + str(download_url_prefix).strip("/")
        self.last_diagnostics: List[str] = []
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.zip_output_root.mkdir(parents=True, exist_ok=True)

        self.project_planner = project_planner or ProjectPlanner(
            llm_engine=llm_engine, enable_debug=enable_debug
        )
        self.file_generator = file_generator or FileGenerator(
            llm_engine=llm_engine, enable_debug=enable_debug
        )
        self.file_writer = file_writer or FileWriter(
            output_root=str(self.output_root), overwrite=True, enable_debug=enable_debug
        )
        self.build_validator = (
            self._create_validator() if build_validator is _AUTO else build_validator
        )
        self.repair_engine = repair_engine or self._create_repair_engine()
        self.zip_packager = zip_packager or self._create_zip_packager()

    def build(
        self,
        project_context: Dict[str, Any],
        use_ai: bool = True,
        clean_existing: bool = True,
    ) -> ProjectBuildResult:
        """Build one project and always return a UI-safe structured result."""
        if not isinstance(project_context, dict):
            raise TypeError("project_context は dict である必要があります。")
        self.last_diagnostics = []
        result = ProjectBuildResult(
            project_name=str(project_context.get("project_name") or "generated-app"),
            message="プロジェクト生成を開始しました。",
        )
        result.configure_estimate(project_context)
        result.add_log("🚀 Project Buildを開始しました。")

        plan = self._plan(result, project_context, use_ai)
        if plan is None:
            return result
        generated_files = self._generate(result, plan, project_context, use_ai)
        if generated_files is None:
            return result
        write_result = self._write(result, plan, generated_files, clean_existing)
        if write_result is None:
            return result
        validation = self._validate(result, plan, write_result.project_root)
        if validation is None:
            return result

        if not self._result_success(validation):
            validation = self._repair_and_revalidate(
                result, plan, write_result.project_root, project_context, validation
            )
            if validation is None or not self._result_success(validation):
                result.status = "error"
                result.message = "生成プロジェクトの検証に失敗しました。"
                if not result.errors:
                    result.add_error("自動修復後も検証エラーが残っています。")
                result.finish(success=False)
                return result

        packaged = self._package(result, write_result.project_root, plan.project_name)
        if packaged is None:
            return result
        result.zip_path = packaged["zip_path"]
        result.zip_download_url = packaged["zip_download_url"]
        result.zip_files_added = int(packaged.get("files_added", 0) or 0)
        result.add_step("ZipPackager", "success", "ZIPファイルを作成しました。")
        result.add_log(
            f"📦 ZIPを作成・検証しました: {result.zip_path} "
            f"(files={result.zip_files_added or 'unknown'})"
        )
        result.status = "success"
        result.message = f"{plan.project_name} のプロジェクト生成が完了しました。"
        result.add_log("🎉 Project Buildが完了しました。")
        result.finish(success=True)
        return result

    def _plan(
        self, result: ProjectBuildResult, context: Dict[str, Any], use_ai: bool
    ) -> Optional[BuildPlan]:
        result.add_step("ProjectPlanner", "building", "アプリ構成を設計しています。")
        try:
            plan = self.project_planner.plan(project_context=context, use_ai=use_ai)
            if not isinstance(plan, BuildPlan):
                if isinstance(plan, Mapping):
                    plan = BuildPlan.from_dict(plan)
                else:
                    raise TypeError("ProjectPlanner returned an unsupported plan")
            plan.validate_or_raise()
        except Exception as exc:
            self._record_internal("ProjectPlanner", exc)
            self._fail_step(result, "ProjectPlanner", "アプリ構成の設計に失敗しました。")
            return None
        result.project_name = plan.project_name
        result.plan = plan.to_dict()
        result.configure_estimate(context, planned_files=len(plan.files))
        result.set_feature_checks(self._planned_feature_checks(context, plan))
        result.add_step(
            "ProjectPlanner", "success", f"{len(plan.files)}個のファイル構成を設計しました。"
        )
        result.add_log("✅ BuildPlanを生成しました。")
        return plan

    def _generate(
        self,
        result: ProjectBuildResult,
        plan: BuildPlan,
        context: Dict[str, Any],
        use_ai: bool,
    ) -> Optional[List[GeneratedFile]]:
        result.add_step("FileGenerator", "building", "各ファイルを生成しています。")
        try:
            generated = self.file_generator.generate_project(
                plan=plan, project_context=context, use_ai=use_ai
            )
            generated = list(generated or [])
        except Exception as exc:
            self._record_internal("FileGenerator", exc)
            self._fail_step(result, "FileGenerator", "ファイル生成に失敗しました。")
            return None

        result.generation = self._summarize_generated_files(generated)
        successful = [item for item in generated if getattr(item, "status", None) == "success"]
        failed = [item for item in generated if getattr(item, "status", None) != "success"]
        result.files_generated = len(successful)
        for item in successful:
            result.add_log(f"📝 Generated: {item.path}")
        for item in failed:
            result.add_warning(
                f"FileGenerator: {getattr(item, 'path', '<unknown>')}: "
                f"{getattr(item, 'error', None) or 'generation failed'}"
            )
        if not successful:
            self._fail_step(result, "FileGenerator", "ファイルを生成できませんでした。")
            return None
        result.add_step(
            "FileGenerator",
            "warning" if failed else "success",
            f"{len(successful)}個成功 / {len(failed)}個失敗",
        )
        return generated

    def _write(
        self,
        result: ProjectBuildResult,
        plan: BuildPlan,
        generated: List[GeneratedFile],
        clean_existing: bool,
    ) -> Optional[FileWriteResult]:
        result.add_step("FileWriter", "building", "生成ファイルを書き込んでいます。")
        try:
            write_result = self.file_writer.write_project(
                plan=plan, generated_files=generated, clean_existing=clean_existing
            )
        except Exception as exc:
            self._record_internal("FileWriter", exc)
            self._fail_step(result, "FileWriter", "ファイルの書き込みに失敗しました。")
            return None
        result.project_root = str(write_result.project_root)
        result.write_result = self._to_dict(write_result)
        if self._result_success(write_result):
            result.add_step(
                "FileWriter", "success", f"{write_result.files_written}個のファイルを書き込みました。"
            )
        else:
            result.add_step("FileWriter", "warning", "一部ファイルの書き込みに失敗しました。")
            for error in getattr(write_result, "errors", []):
                result.add_warning(error)
        return write_result

    def _validate(
        self, result: ProjectBuildResult, plan: BuildPlan, project_root: str
    ) -> Optional[Any]:
        result.add_step("BuildValidator", "building", "生成Projectを検証しています。")
        if self.build_validator is None:
            self._fail_step(result, "BuildValidator", "BuildValidatorがまだ接続されていません。")
            return None
        try:
            validation = self.build_validator.validate(plan=plan, project_root=project_root)
        except Exception as exc:
            self._record_internal("BuildValidator", exc)
            self._fail_step(result, "BuildValidator", "生成Projectの検証に失敗しました。")
            return None
        result.validation = self._to_dict(validation)
        result.set_feature_checks(
            result.validation.get("feature_checks", result.feature_checks)
        )
        self._append_validation_logs(result, validation)
        if self._result_success(validation):
            result.add_step("BuildValidator", "success", "静的検証に成功しました。")
        else:
            count = len(self._result_items(validation, "errors"))
            result.add_step("BuildValidator", "error", f"{count}件の検証エラーがあります。")
        return validation

    def _repair_and_revalidate(
        self,
        result: ProjectBuildResult,
        plan: BuildPlan,
        project_root: str,
        context: Dict[str, Any],
        validation: Any,
    ) -> Optional[Any]:
        del validation
        if not self.enable_repair or self.repair_engine is None:
            result.add_error("BuildValidatorの検証エラーを修復できませんでした。")
            return None
        result.add_step("RepairEngine", "building", "エラーを自動修復しています。")
        try:
            repaired = self.repair_engine.repair_project(
                plan=plan, project_root=project_root, project_context=context
            )
        except Exception as exc:
            self._record_internal("RepairEngine", exc)
            self._fail_step(result, "RepairEngine", "自動修復中にエラーが発生しました。")
            return None
        result.repair = self._to_dict(repaired)
        if not self._result_success(repaired):
            result.add_step("RepairEngine", "error", "自動修復に失敗しました。")
            result.add_error("RepairEngineによる自動修復に失敗しました。")
            return None
        result.add_step("RepairEngine", "success", "自動修復に成功しました。")
        result.add_log("🔧 RepairEngineによる自動修復に成功しました。")
        # Trust but verify. Legacy RepairResult.success alone is not sufficient.
        return self._validate(result, plan, project_root)

    def _package(
        self, result: ProjectBuildResult, project_root: str, project_name: str
    ) -> Optional[Dict[str, Any]]:
        result.add_step("ZipPackager", "building", "ProjectをZIP化しています。")
        try:
            packaged = self._package_project(project_root, project_name)
        except Exception as exc:
            self._record_internal("ZipPackager", exc)
            self._fail_step(result, "ZipPackager", "ZIPファイルの作成に失敗しました。")
            return None
        if not packaged:
            self._fail_step(result, "ZipPackager", "ZIPファイルを作成できませんでした。")
            return None
        return packaged

    def _create_validator(self) -> Optional[Any]:
        if BuildValidator is None:
            return None
        try:
            return BuildValidator(enable_debug=self.enable_debug)
        except TypeError:
            return BuildValidator()

    def _create_repair_engine(self) -> Optional[Any]:
        if (
            not self.enable_repair
            or RepairEngine is None
            or self.llm_engine is None
            or self.build_validator is None
        ):
            return None
        kwargs = {
            "llm_engine": self.llm_engine,
            "validator": self.build_validator,
            "writer": self.file_writer,
            "max_iterations": self.max_repair_iterations,
            "enable_debug": self.enable_debug,
        }
        try:
            return self._call_with_supported_kwargs(RepairEngine, kwargs)
        except Exception as exc:
            self._record_internal("RepairEngine initialization", exc)
            return None

    def _create_zip_packager(self) -> Optional[Any]:
        if ZipPackager is None:
            return None
        kwargs = {
            "output_root": str(self.zip_output_root),
            "zip_output_root": str(self.zip_output_root),
            "zip_output_dir": str(self.zip_output_root),
            "enable_debug": self.enable_debug,
        }
        try:
            return self._call_with_supported_kwargs(ZipPackager, kwargs)
        except Exception as exc:
            self._record_internal("ZipPackager initialization", exc)
            return None

    def _package_project(self, project_root: str, project_name: str) -> Dict[str, Any]:
        root = Path(project_root).resolve()
        if not root.is_dir() or not self._is_inside(root, self.output_root):
            raise ValueError("ZIP化対象Projectが不正です。")
        if self.zip_packager is not None:
            normalized = self._call_zip_packager(root, project_name)
            if normalized:
                return normalized
        return self._fallback_zip(root, project_name)

    def _call_zip_packager(
        self, project_root: Path, project_name: str
    ) -> Optional[Dict[str, Any]]:
        for name in ("package_project", "create_zip", "package", "pack"):
            method = getattr(self.zip_packager, name, None)
            if not callable(method):
                continue
            try:
                value = self._invoke_packager_method(method, project_root, project_name)
                normalized = self._normalize_zip_result(value, project_name)
                if normalized:
                    return normalized
            except Exception as exc:
                self._record_internal(f"ZipPackager.{name}", exc)
        return None

    def _invoke_packager_method(self, method: Any, root: Path, name: str) -> Any:
        kwargs = {
            "project_root": str(root),
            "project_name": name,
            "output_root": str(self.zip_output_root),
            "zip_output_root": str(self.zip_output_root),
            "zip_output_dir": str(self.zip_output_root),
        }
        try:
            return self._call_with_supported_kwargs(method, kwargs)
        except TypeError:
            try:
                return method(str(root), name)
            except TypeError:
                return method(str(root))

    def _normalize_zip_result(
        self, value: Any, project_name: str
    ) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if isinstance(value, Mapping):
            if value.get("success") is False:
                return None
            path = value.get("zip_path") or value.get("path") or value.get("file_path")
            url = value.get("zip_download_url") or value.get("download_url")
            files_added = int(value.get("files_added", 0) or 0)
        elif isinstance(value, (str, Path)):
            path, url, files_added = value, None, 0
        else:
            path = getattr(value, "zip_path", None) or getattr(value, "path", None)
            url = getattr(value, "zip_download_url", None) or getattr(value, "download_url", None)
            files_added = int(getattr(value, "files_added", 0) or 0)
        if not path:
            return None
        return {
            "zip_path": str(path),
            "zip_download_url": str(url or self._download_url(project_name)),
            "files_added": files_added,
        }

    def _fallback_zip(self, project_root: Path, project_name: str) -> Dict[str, Any]:
        safe_name = self._safe_project_name(project_name)
        archive_base = self.zip_output_root / safe_name
        archive_path = Path(str(archive_base) + ".zip")
        if archive_path.exists():
            archive_path.unlink()
        created = shutil.make_archive(
            base_name=str(archive_base),
            format="zip",
            root_dir=str(project_root.parent),
            base_dir=project_root.name,
        )
        return {
            "zip_path": str(Path(created).resolve()),
            "zip_download_url": self._download_url(safe_name),
            "files_added": sum(1 for path in project_root.rglob("*") if path.is_file()),
        }

    @staticmethod
    def _summarize_generated_files(files: List[Any]) -> List[Dict[str, Any]]:
        return [
            {
                "path": str(getattr(item, "path", "")),
                "status": str(getattr(item, "status", "error")),
                "source": str(getattr(item, "source", "unknown")),
                "error": getattr(item, "error", None),
                "characters": len(str(getattr(item, "content", "") or "")),
            }
            for item in files
        ]

    @staticmethod
    def _planned_feature_checks(
        context: Mapping[str, Any], plan: BuildPlan
    ) -> List[Dict[str, Any]]:
        """Create honest, UI-visible checks without claiming runtime verification."""
        features = [str(item) for item in plan.features]
        raw_features = [str(item) for item in context.get("raw_features", []) or []]
        design = [str(item) for item in plan.design_preferences]
        combined = " ".join([*features, *raw_features, *design]).lower()
        checks: List[Dict[str, Any]] = []

        if "authentication" in {item.casefold() for item in features}:
            checks.append(
                {
                    "key": "password_authentication",
                    "title": "パスワード認証",
                    "status": "checking",
                    "summary": "認証UIと安全性を静的検証します。",
                    "checks": [
                        {"name": "パスワード入力欄", "status": "pending", "message": "生成後に確認します。"},
                        {"name": "平文保存の防止", "status": "pending", "message": "生成後に確認します。"},
                        {"name": "ログイン失敗表示", "status": "pending", "message": "生成後に確認します。"},
                        {"name": "実際のログイン動作", "status": "not_verified", "message": "実行環境での確認が必要です。"},
                    ],
                }
            )

        if any(word in combined for word in ("animation", "アニメ", "演出", "transition", "fade")):
            checks.append(
                {
                    "key": "visual_effects",
                    "title": "画面演出・アニメーション",
                    "status": "checking",
                    "summary": "CSS定義を静的検証し、目視確認は未確認として区別します。",
                    "checks": [
                        {"name": "演出コード", "status": "pending", "message": "生成後に確認します。"},
                        {"name": "ブラウザでの見た目", "status": "not_verified", "message": "プレビューまたは目視確認が必要です。"},
                    ],
                }
            )

        for feature in features:
            key = feature.casefold()
            if key == "authentication":
                continue
            checks.append(
                {
                    "key": key,
                    "title": feature,
                    "status": "planned",
                    "summary": "BuildPlanへ登録済みです。",
                    "checks": [],
                }
            )
        return checks

    def _append_validation_logs(self, result: ProjectBuildResult, validation: Any) -> None:
        for log in self._result_items(validation, "logs"):
            result.add_log(log)
        for issue in self._result_items(validation, "errors"):
            result.add_log("❌ " + self._issue_text(issue))
        for issue in self._result_items(validation, "warnings"):
            result.add_warning(self._issue_text(issue))

    @staticmethod
    def _issue_text(issue: Any) -> str:
        if isinstance(issue, Mapping):
            code = issue.get("code", "VALIDATION")
            message = issue.get("message", issue)
            path = issue.get("file_path")
        else:
            code = getattr(issue, "code", "VALIDATION")
            message = getattr(issue, "message", issue)
            path = getattr(issue, "file_path", None)
        return f"{code}: {message}" + (f" [{path}]" if path else "")

    @staticmethod
    def _result_items(value: Any, key: str) -> List[Any]:
        raw = value.get(key, []) if isinstance(value, Mapping) else getattr(value, key, [])
        return list(raw or [])

    @staticmethod
    def _result_success(value: Any) -> bool:
        if isinstance(value, Mapping):
            return bool(value.get("success", False))
        return bool(getattr(value, "success", False))

    @staticmethod
    def _to_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        method = getattr(value, "to_dict", None)
        if callable(method):
            converted = method()
            return dict(converted) if isinstance(converted, Mapping) else {"value": converted}
        return {"success": bool(getattr(value, "success", False))}

    @staticmethod
    def _call_with_supported_kwargs(callable_value: Any, kwargs: Dict[str, Any]) -> Any:
        try:
            signature = inspect.signature(callable_value)
        except (TypeError, ValueError):
            return callable_value(**kwargs)
        accepts_extra = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        selected = kwargs if accepts_extra else {
            name: value for name, value in kwargs.items() if name in signature.parameters
        }
        return callable_value(**selected)

    def _fail_step(self, result: ProjectBuildResult, step: str, message: str) -> None:
        result.add_step(step, "error", message)
        result.status = "error"
        result.message = f"{step}でエラーが発生しました。"
        result.add_error(f"{step}: {message}")
        result.finish(success=False)

    def _download_url(self, project_name: str) -> str:
        return f"{self.download_url_prefix}/{self._safe_project_name(project_name)}.zip"

    @staticmethod
    def _safe_project_name(project_name: str) -> str:
        value = str(project_name or "generated-app").lower().strip().replace("_", "-")
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[^a-z0-9-]", "-", value)
        value = re.sub(r"-+", "-", value).strip("-")
        return value[:80].rstrip("-") or "generated-app"

    @staticmethod
    def _is_inside(target: Path, root: Path) -> bool:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    def _record_internal(self, stage: str, exc: Exception) -> None:
        self._debug(f"{stage}: {type(exc).__name__}: {exc}")

    def _debug(self, message: str) -> None:
        self.last_diagnostics.append(message)
        if self.enable_debug:
            print(f"[ProjectBuildService] {message}", flush=True)


__all__ = ["BuildStep", "ProjectBuildResult", "ProjectBuildService"]
