"""Safely repair generated projects from static validation results."""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .BuildPlan import BuildFile, BuildPlan
from .BuildValidator import BuildValidationResult, BuildValidator, ValidationIssue
from .FileGenerator import FileGenerator, GeneratedFile
from .FileWriter import FileWriter


@dataclass
class RepairAction:
    """One file-level action derived from one or more validation errors."""

    action: str
    file_path: Optional[str] = None
    reason: str = ""
    related_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "file_path": self.file_path,
            "reason": self.reason,
            "related_errors": list(self.related_errors),
        }


@dataclass
class RepairIteration:
    """Result of one repair-and-revalidate pass."""

    iteration: int
    actions: List[RepairAction] = field(default_factory=list)
    repaired_files: List[str] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)
    validation_before: Optional[Dict[str, Any]] = None
    validation_after: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "actions": [action.to_dict() for action in self.actions],
            "repaired_files": list(self.repaired_files),
            "failed_files": list(self.failed_files),
            "validation_before": self.validation_before,
            "validation_after": self.validation_after,
        }


@dataclass
class RepairResult:
    """Backward-compatible aggregate returned to ProjectBuildService."""

    success: bool
    iterations: List[RepairIteration] = field(default_factory=list)
    final_validation: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def total_iterations(self) -> int:
        return len(self.iterations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "total_iterations": self.total_iterations,
            "iterations": [iteration.to_dict() for iteration in self.iterations],
            "final_validation": self.final_validation,
            "error": self.error,
        }


class RepairEngine:
    """Repair validator errors with templates first and an optional LLM second.

    The engine never executes generated code or package-manager commands. Every
    write goes through :class:`FileWriter`, and every pass ends with a fresh
    :class:`BuildValidator` result.
    """

    REPAIRABLE_CODES = {
        "BUILD_SCRIPT_MISSING",
        "EMPTY_FILE",
        "HTML_ASSET_NOT_FOUND",
        "HTML_REQUIRED_FILE_MISSING",
        "IMPORT_NOT_FOUND",
        "INVALID_JSON",
        "INVALID_PACKAGE_JSON",
        "NEXTJS_DEPENDENCY_MISSING",
        "NEXTJS_REQUIRED_FILE_MISSING",
        "REACT_DEPENDENCY_MISSING",
        "REACT_DOM_DEPENDENCY_MISSING",
        "REACT_REQUIRED_FILE_MISSING",
        "REQUIRED_FILE_MISSING",
        "VITE_NOT_FOUND",
    }
    MISSING_FILE_CODES = {
        "HTML_REQUIRED_FILE_MISSING",
        "NEXTJS_REQUIRED_FILE_MISSING",
        "REACT_REQUIRED_FILE_MISSING",
        "REQUIRED_FILE_MISSING",
    }
    PACKAGE_CODES = {
        "BUILD_SCRIPT_MISSING",
        "INVALID_JSON",
        "INVALID_PACKAGE_JSON",
        "NEXTJS_DEPENDENCY_MISSING",
        "REACT_DEPENDENCY_MISSING",
        "REACT_DOM_DEPENDENCY_MISSING",
        "VITE_NOT_FOUND",
    }
    RELATED_SUFFIXES = {".css", ".html", ".js", ".jsx", ".json", ".ts", ".tsx"}
    FENCE_START = re.compile(r"^\s*```[^\n]*\n?")
    FENCE_END = re.compile(r"\n?```\s*$")

    def __init__(
        self,
        llm_engine: Optional[Any] = None,
        validator: Optional[BuildValidator] = None,
        writer: Optional[FileWriter] = None,
        max_iterations: int = 3,
        max_file_chars: int = 12000,
        enable_debug: bool = False,
    ) -> None:
        self.llm_engine = llm_engine
        self.validator = validator or BuildValidator(enable_debug=enable_debug)
        self.writer = writer or FileWriter(enable_debug=enable_debug)
        self.max_iterations = max(1, int(max_iterations))
        self.max_file_chars = max(1000, int(max_file_chars))
        self.enable_debug = bool(enable_debug)
        self.last_diagnostics: List[str] = []
        self.template_generator = FileGenerator(llm_engine=None, enable_debug=enable_debug)

    def repair_project(
        self,
        plan: BuildPlan,
        project_root: str,
        project_context: Optional[Dict[str, Any]] = None,
    ) -> RepairResult:
        """Repair a project up to ``max_iterations`` times."""
        self.last_diagnostics = []
        if not isinstance(plan, BuildPlan):
            return RepairResult(success=False, error="BuildPlan型ではありません。")
        try:
            plan.validate_or_raise()
        except Exception:
            return RepairResult(success=False, error="BuildPlanが不正です。")

        root = Path(project_root).expanduser().resolve()
        if not root.exists():
            return RepairResult(success=False, error="project_root が存在しません。")
        if not root.is_dir():
            return RepairResult(success=False, error="project_root がディレクトリではありません。")

        context = dict(project_context or {})
        validation = self.validator.validate(plan=plan, project_root=str(root))
        if validation.success:
            return RepairResult(success=True, final_validation=validation.to_dict())

        iterations: List[RepairIteration] = []
        stop_reason = "最大修正回数に達しました。"
        for number in range(1, self.max_iterations + 1):
            before_fingerprint = self._validation_fingerprint(validation)
            actions = self._build_repair_actions(validation)
            current = RepairIteration(
                iteration=number,
                actions=actions,
                validation_before=validation.to_dict(),
            )
            if not actions:
                iterations.append(current)
                stop_reason = "自動修復できる検証エラーがありません。"
                break

            for action in actions:
                if not action.file_path or action.action == "skip":
                    continue
                repaired = self._repair_file(
                    plan=plan,
                    project_root=root,
                    file_path=action.file_path,
                    action=action,
                    project_context=context,
                    validation=validation,
                )
                target = current.repaired_files if repaired else current.failed_files
                if action.file_path not in target:
                    target.append(action.file_path)

            validation = self.validator.validate(plan=plan, project_root=str(root))
            current.validation_after = validation.to_dict()
            iterations.append(current)
            if validation.success:
                return RepairResult(
                    success=True,
                    iterations=iterations,
                    final_validation=validation.to_dict(),
                )
            if (
                not current.repaired_files
                or self._validation_fingerprint(validation) == before_fingerprint
            ):
                stop_reason = "修復後も同じ検証エラーが残ったため停止しました。"
                break

        return RepairResult(
            success=False,
            iterations=iterations,
            final_validation=validation.to_dict(),
            error=stop_reason,
        )

    def _build_repair_actions(
        self, validation: BuildValidationResult
    ) -> List[RepairAction]:
        grouped: Dict[str, List[ValidationIssue]] = {}
        for issue in validation.errors:
            if issue.code not in self.REPAIRABLE_CODES:
                continue
            file_path = issue.file_path
            if not file_path and issue.code in self.PACKAGE_CODES:
                file_path = "package.json"
            if file_path:
                grouped.setdefault(BuildFile.normalize_path(file_path), []).append(issue)

        actions: List[RepairAction] = []
        for file_path, issues in grouped.items():
            codes = list(dict.fromkeys(issue.code for issue in issues))
            action_name = (
                "create_missing_file"
                if any(code in self.MISSING_FILE_CODES for code in codes)
                else "repair_file"
            )
            actions.append(
                RepairAction(
                    action=action_name,
                    file_path=file_path,
                    reason=" / ".join(dict.fromkeys(issue.message for issue in issues)),
                    related_errors=codes,
                )
            )
        return actions

    def _repair_file(
        self,
        plan: BuildPlan,
        project_root: Path,
        file_path: str,
        action: RepairAction,
        project_context: Dict[str, Any],
        validation: BuildValidationResult,
    ) -> bool:
        try:
            target_path = self._resolve_inside(project_root, file_path)
        except ValueError as exc:
            self._debug(str(exc))
            return False

        file_spec = plan.get_file(file_path)
        if file_spec is None:
            candidate = BuildFile(
                path=file_path,
                type=self._guess_file_type(file_path),
                language=self._guess_language(file_path),
                description="Validatorが必要と判断した修復対象ファイル",
            )
            if not candidate.is_valid() or not plan.add_file(candidate):
                self._debug(f"BuildPlanへ修復対象を追加できません: {file_path}")
                return False
            file_spec = candidate

        if file_path.casefold() == "package.json" and any(
            code in self.PACKAGE_CODES for code in action.related_errors
        ):
            content = self._repair_package_json(plan, file_spec, target_path, project_context)
            if content and self._write(project_root, file_path, content):
                return True

        if action.action == "create_missing_file" or "EMPTY_FILE" in action.related_errors:
            generated = self.template_generator.generate_file(
                plan=plan,
                file_spec=file_spec,
                project_context=project_context,
                generated_files={},
                use_ai=False,
            )
            if generated.success and self._write(project_root, file_path, generated.content):
                return True

        if self.llm_engine is None or not self._llm_available():
            self._debug(f"LLMを利用できないため修復できません: {file_path}")
            return False

        existing = self._read_limited_text(target_path)
        related = self._collect_related_files(project_root, file_path)
        errors = [
            issue.to_dict()
            for issue in validation.errors
            if issue.file_path == file_path
            or (file_path == "package.json" and issue.code in self.PACKAGE_CODES)
        ]
        messages = self._build_repair_messages(
            plan,
            file_spec,
            action,
            existing,
            related,
            errors,
            project_context,
        )
        try:
            response = self._call_llm(messages)
            if inspect.isawaitable(response):
                self._close_awaitable(response)
                self._debug("同期RepairEngineに非同期LLMが接続されています。")
                return False
            text, error = self._extract_llm_result(response)
            if error:
                self._debug(error)
                return False
            content = self._clean_content(text)
            if not self._content_is_safe(file_path, content):
                return False
            return self._write(project_root, file_path, content)
        except Exception as exc:
            self._debug(f"LLM修復に失敗しました: {exc}")
            return False

    def _repair_package_json(
        self,
        plan: BuildPlan,
        file_spec: BuildFile,
        target_path: Path,
        project_context: Dict[str, Any],
    ) -> str:
        existing: Dict[str, Any] = {}
        try:
            parsed = json.loads(target_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                existing = parsed
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass

        baseline: Dict[str, Any] = {}
        generated = self.template_generator.generate_file(
            plan=plan,
            file_spec=file_spec,
            project_context=project_context,
            generated_files={},
            use_ai=False,
        )
        if generated.success:
            try:
                parsed = json.loads(generated.content)
                if isinstance(parsed, dict):
                    baseline = parsed
            except json.JSONDecodeError:
                pass
        if not baseline and not existing:
            return ""

        merged = dict(existing)
        for key, value in baseline.items():
            if isinstance(value, Mapping):
                current = merged.get(key)
                current_mapping = dict(current) if isinstance(current, Mapping) else {}
                for child_key, child_value in value.items():
                    current_mapping.setdefault(child_key, child_value)
                merged[key] = current_mapping
            else:
                merged.setdefault(key, value)
        return json.dumps(merged, ensure_ascii=False, indent=2) + "\n"

    def _write(self, project_root: Path, file_path: str, content: str) -> bool:
        generated = GeneratedFile(
            path=file_path,
            content=content,
            status="success",
            source="repair_engine",
        )
        written = self.writer._write_file(project_root=project_root, generated=generated)
        if not written.success:
            self._debug(written.error or f"書き込みに失敗しました: {file_path}")
        return written.success

    def _build_repair_messages(
        self,
        plan: BuildPlan,
        file_spec: BuildFile,
        action: RepairAction,
        existing_content: str,
        related_files: Dict[str, str],
        errors: List[Dict[str, Any]],
        project_context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        system = """あなたは生成アプリの自動修復を担当するシニアエンジニアです。
指定された1ファイルだけを修正してください。

【厳守事項】
- 回答には完成したファイル内容だけを出力する。
- Markdownコードブロック、挨拶、説明、修正理由を出力しない。
- Validatorが報告していない箇所を不必要に変更しない。
- 既存機能を可能な限り維持する。
- BuildPlanに存在しない相対importを追加しない。
- TODOや空の仮実装だけで終わらせない。
- JSONは必ず有効なJSONにする。
- 指定ファイル以外を変更しようとしない。"""
        payload = {
            "project": {
                "project_name": plan.project_name,
                "framework": plan.framework,
                "description": plan.description,
                "features": plan.features,
                "target_user": plan.target_user,
                "purpose": plan.purpose,
            },
            "project_context": project_context,
            "target": file_spec.to_dict(),
            "action": action.to_dict(),
            "validator_errors": errors,
            "current_content": existing_content or "(ファイルなし)",
            "related_files": related_files,
        }
        user = (
            json.dumps(payload, ensure_ascii=False, indent=2, default=str)
            + f"\n\n{file_spec.path} の完成した修正版内容だけを出力してください。"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _collect_related_files(
        self,
        project_root: Path,
        target_file: str,
        max_files: int = 6,
        max_chars_per_file: int = 2500,
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        candidates = [
            "package.json",
            "src/main.jsx",
            "src/App.jsx",
            "src/App.tsx",
            "app/layout.jsx",
            "app/page.jsx",
            "index.html",
        ]
        try:
            target = self._resolve_inside(project_root, target_file)
            if target.parent.is_dir():
                candidates.extend(
                    str(path.relative_to(project_root)).replace("\\", "/")
                    for path in sorted(target.parent.iterdir())
                    if path.is_file() and path.suffix.casefold() in self.RELATED_SUFFIXES
                )
        except (OSError, ValueError):
            return result

        for relative in dict.fromkeys(candidates):
            if relative == target_file or len(result) >= max_files:
                continue
            try:
                path = self._resolve_inside(project_root, relative)
            except ValueError:
                continue
            content = self._read_limited_text(path, max_chars_per_file)
            if content:
                result[relative] = content
        return result

    def _read_limited_text(self, path: Path, limit: Optional[int] = None) -> str:
        if not path.is_file() or path.is_symlink():
            return ""
        maximum = min(self.max_file_chars, limit or self.max_file_chars)
        try:
            with path.open("r", encoding="utf-8") as handle:
                return handle.read(maximum + 1)[:maximum]
        except (OSError, UnicodeError):
            return ""

    def _llm_available(self) -> bool:
        value = getattr(self.llm_engine, "is_available", True)
        try:
            checked = value() if callable(value) else value
            if inspect.isawaitable(checked):
                self._close_awaitable(checked)
                return False
            return bool(checked)
        except Exception:
            return False

    def _call_llm(self, messages: List[Dict[str, str]]) -> Any:
        chat = getattr(self.llm_engine, "chat", None)
        if callable(chat):
            return chat(messages, temperature=0.1, max_tokens=3000)
        generate = getattr(self.llm_engine, "generate", None)
        if callable(generate):
            return generate(messages)
        raise TypeError("LLM engine must provide chat() or generate()")

    @staticmethod
    def _extract_llm_result(result: Any) -> tuple[str, Optional[str]]:
        if isinstance(result, str):
            return result, None
        if isinstance(result, Mapping):
            if result.get("success") is False:
                return "", str(result.get("error") or "LocalLLMの修復に失敗しました。")
            return str(result.get("text") or result.get("content") or ""), None
        if getattr(result, "success", True) is False:
            return "", str(getattr(result, "error", None) or "LocalLLMの修復に失敗しました。")
        return str(getattr(result, "text", None) or getattr(result, "content", None) or ""), None

    def _content_is_safe(self, file_path: str, content: str) -> bool:
        if not content.strip() or len(content) > self.max_file_chars * 20:
            self._debug(f"修復内容が空、または大きすぎます: {file_path}")
            return False
        if Path(file_path).suffix.casefold() == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError:
                self._debug(f"LLMが不正なJSONを返しました: {file_path}")
                return False
        return True

    @classmethod
    def _clean_content(cls, content: Any) -> str:
        value = str(content or "").strip()
        value = cls.FENCE_START.sub("", value, count=1)
        value = cls.FENCE_END.sub("", value, count=1).strip()
        return value + "\n" if value else ""

    @staticmethod
    def _resolve_inside(root: Path, relative_path: str) -> Path:
        candidate_spec = BuildFile(path=relative_path)
        if not candidate_spec.is_valid():
            raise ValueError("修復対象のファイルパスが不正です。")
        candidate = root.joinpath(*Path(candidate_spec.path).parts)
        if candidate.is_symlink():
            raise ValueError("シンボリックリンクは修復対象にできません。")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("project_root外のファイルは修復できません。") from exc
        return resolved

    @staticmethod
    def _validation_fingerprint(validation: BuildValidationResult) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((issue.code, issue.file_path or "") for issue in validation.errors))

    @staticmethod
    def _guess_language(file_path: str) -> Optional[str]:
        return {
            ".css": "css",
            ".html": "html",
            ".js": "javascript",
            ".jsx": "javascript",
            ".json": "json",
            ".md": "markdown",
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
        }.get(Path(file_path).suffix.casefold())

    @staticmethod
    def _guess_file_type(file_path: str) -> str:
        name = Path(file_path).name.casefold()
        suffix = Path(file_path).suffix.casefold()
        if name == "package.json":
            return "config"
        if suffix in {".jsx", ".tsx"}:
            return "component"
        if suffix == ".json":
            return "data"
        if suffix == ".css":
            return "style"
        if suffix == ".html":
            return "html"
        if suffix == ".md":
            return "documentation"
        return "file"

    @staticmethod
    def _close_awaitable(value: Any) -> None:
        close = getattr(value, "close", None)
        if callable(close):
            close()

    def _debug(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self.last_diagnostics.append(text)
        if self.enable_debug and text:
            print(f"🔧 [RepairEngine] {text}", flush=True)


__all__ = ["RepairAction", "RepairIteration", "RepairResult", "RepairEngine"]
