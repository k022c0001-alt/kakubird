"""Deterministic static validation for generated web projects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .BuildPlan import BuildPlan


@dataclass
class ValidationIssue:
    """One machine-readable problem consumed by RepairEngine and the UI."""

    level: str
    code: str
    message: str
    file_path: Optional[str] = None

    def __post_init__(self) -> None:
        self.level = str(self.level or "error").strip().lower()
        self.code = str(self.code or "VALIDATION_ERROR").strip().upper()
        self.message = str(self.message or "検証エラーです。").strip()
        self.file_path = str(self.file_path).replace("\\", "/") if self.file_path else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "file_path": self.file_path,
        }


@dataclass
class BuildValidationResult:
    """Backward-compatible result returned to ProjectBuildService."""

    success: bool = True
    status: str = "success"
    message: str = "静的検証に成功しました。"
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    checked_files: int = 0
    feature_checks: List[Dict[str, Any]] = field(default_factory=list)

    def add_error(
        self, code: str, message: str, file_path: Optional[str] = None
    ) -> None:
        issue = ValidationIssue("error", code, message, file_path)
        if not self._contains(self.errors, issue):
            self.errors.append(issue)
            self.logs.append(self._log_line("❌", issue))
        self.success = False
        self.status = "error"
        self.message = "静的検証でエラーが見つかりました。"

    def add_warning(
        self, code: str, message: str, file_path: Optional[str] = None
    ) -> None:
        issue = ValidationIssue("warning", code, message, file_path)
        if not self._contains(self.warnings, issue):
            self.warnings.append(issue)
            self.logs.append(self._log_line("⚠️", issue))

    def add_log(self, message: Any) -> None:
        text = str(message or "").strip()
        if text:
            self.logs.append(text)

    def finalize(self) -> None:
        if self.errors:
            self.success = False
            self.status = "error"
            self.message = f"{len(self.errors)}件の検証エラーが見つかりました。"
        elif self.warnings:
            self.success = True
            self.status = "warning"
            self.message = f"静的検証には成功しましたが、{len(self.warnings)}件の警告があります。"
        else:
            self.success = True
            self.status = "success"
            self.message = "静的検証に成功しました。"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "checked_files": self.checked_files,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "logs": list(self.logs),
            "feature_checks": list(self.feature_checks),
        }

    @staticmethod
    def _contains(items: Sequence[ValidationIssue], candidate: ValidationIssue) -> bool:
        return any(
            (item.code, item.message, item.file_path)
            == (candidate.code, candidate.message, candidate.file_path)
            for item in items
        )

    @staticmethod
    def _log_line(prefix: str, issue: ValidationIssue) -> str:
        location = f"{issue.file_path}: " if issue.file_path else ""
        return f"{prefix} {location}{issue.message}"


class BuildValidator:
    """Validate generated files using Python only.

    Package installation and actual ``npm run build`` execution intentionally
    belong to a future RuntimeBuildValidator. This class stays deterministic
    and safe to run in an offline request path.
    """

    IMPORT_PATTERN = re.compile(
        r"(?:\b(?:import|export)\s+(?:[^'\";]*?\s+from\s+)?|"
        r"\brequire\s*\(|\bimport\s*\()"
        r"['\"]([^'\"]+)['\"]\s*\)?",
        re.MULTILINE,
    )
    HTML_REFERENCE_PATTERN = re.compile(
        r"\b(?:src|href)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
    )
    SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    IMPORT_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".css", ".json")
    EXCLUDED_SCAN_DIRS = {
        ".git",
        ".next",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }

    def __init__(
        self,
        enable_debug: bool = False,
        max_file_bytes: int = 5 * 1024 * 1024,
    ) -> None:
        self.enable_debug = bool(enable_debug)
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.last_diagnostics: List[str] = []

    def validate(self, plan: BuildPlan, project_root: str) -> BuildValidationResult:
        """Return a complete validation report without executing project code."""
        result = BuildValidationResult()
        self.last_diagnostics = []
        result.add_log("🔍 Static Validationを開始しました。")

        if not isinstance(plan, BuildPlan):
            result.add_error("INVALID_BUILD_PLAN", "BuildPlan型ではありません。")
            result.finalize()
            return result
        for message in plan.validate():
            result.add_error("INVALID_BUILD_PLAN", message)
        if result.errors:
            result.finalize()
            return result
        result.add_log("✅ BuildPlanの整合性を確認しました。")

        root = Path(project_root).expanduser().resolve()
        if not root.exists():
            result.add_error("PROJECT_NOT_FOUND", "プロジェクトフォルダが存在しません。")
            result.finalize()
            return result
        if not root.is_dir():
            result.add_error("PROJECT_NOT_DIRECTORY", "project_rootがディレクトリではありません。")
            result.finalize()
            return result
        result.add_log("✅ Project directoryを確認しました。")

        self._validate_plan_files(plan, root, result)
        framework = str(plan.framework or "").lower().strip()
        result.add_log(f"🔧 Framework: {framework}")
        if framework == "react":
            self._validate_react(plan, root, result)
        elif framework == "nextjs":
            self._validate_nextjs(plan, root, result)
        elif framework == "html":
            self._validate_html_project(plan, root, result)
        else:
            result.add_warning(
                "UNSUPPORTED_FRAMEWORK_VALIDATION",
                f"このFramework専用の静的Validatorはありません: {framework}",
            )

        self._validate_requested_features(plan, root, result)

        result.finalize()
        result.add_log("✅ Static Validation完了" if result.success else "❌ Static Validation失敗")
        return result

    def _validate_requested_features(
        self, plan: BuildPlan, root: Path, result: BuildValidationResult
    ) -> None:
        """Report implementation evidence separately from runtime/visual checks."""
        features = {str(item).casefold() for item in plan.features}
        constraints = {str(item).casefold() for item in plan.constraints}
        source_text = self._combined_source_text(root)

        # Explicit negative requirements always win over inferred features.
        # RequirementAnalyzer/ProjectPlanner should normally remove the feature,
        # but Validator must not report an auth warning for a no-auth project.
        authentication_requested = (
            "authentication" in features
            and "no_auth" not in constraints
            and "no-auth" not in constraints
        )

        if authentication_requested:
            password_input = bool(
                re.search(
                    r"type\s*=\s*(?:['\"]password['\"]|\{\s*['\"]password['\"]\s*\})",
                    source_text,
                    re.IGNORECASE,
                )
            )
            plaintext_storage = bool(
                re.search(
                    r"(?:localStorage|sessionStorage)\.setItem\s*\([^\n;]*(?:password|パスワード)",
                    source_text,
                    re.IGNORECASE,
                )
            )
            failure_message = bool(
                re.search(
                    r"(?:login|sign.?in|ログイン|認証).{0,100}(?:error|invalid|failed|失敗|間違)",
                    source_text,
                    re.IGNORECASE | re.DOTALL,
                )
            )
            if not password_input:
                result.add_warning(
                    "PASSWORD_INPUT_NOT_CONFIRMED",
                    "認証機能がありますが、password型の入力欄を静的確認できませんでした。",
                )
            if plaintext_storage:
                result.add_error(
                    "PLAINTEXT_PASSWORD_STORAGE",
                    "パスワードをWeb Storageへ保存する可能性があるコードを検出しました。",
                )
            result.feature_checks.append(
                {
                    "key": "password_authentication",
                    "title": "パスワード認証",
                    "status": "warning" if (not password_input or plaintext_storage) else "success",
                    "summary": "コード上の認証要素を確認しました。実際のログイン成功は未確認です。",
                    "checks": [
                        {
                            "name": "パスワード入力欄",
                            "status": "success" if password_input else "warning",
                            "message": "password型を確認しました。" if password_input else "password型を確認できませんでした。",
                        },
                        {
                            "name": "平文保存の防止",
                            "status": "error" if plaintext_storage else "success",
                            "message": "危険なWeb Storage保存を検出しました。" if plaintext_storage else "Web Storageへの平文保存は検出されませんでした。",
                        },
                        {
                            "name": "ログイン失敗表示",
                            "status": "success" if failure_message else "not_verified",
                            "message": "失敗表示らしいコードを確認しました。" if failure_message else "静的には確認できませんでした。",
                        },
                        {
                            "name": "実際のログイン動作",
                            "status": "not_verified",
                            "message": "Backend接続後の実行テストが必要です。",
                        },
                    ],
                }
            )
            result.add_log("🔐 パスワード認証の静的確認を記録しました。")

        if "animation" in features:
            animation_found = bool(
                re.search(
                    r"@keyframes|\banimation(?:-name)?\s*:|\btransition\s*:",
                    source_text,
                    re.IGNORECASE,
                )
            )
            if not animation_found:
                result.add_warning(
                    "ANIMATION_NOT_CONFIRMED",
                    "演出が要求されていますが、CSSアニメーションを静的確認できませんでした。",
                )
            result.feature_checks.append(
                {
                    "key": "visual_effects",
                    "title": "画面演出・アニメーション",
                    "status": "success" if animation_found else "warning",
                    "summary": "コードの有無とブラウザでの目視確認を分けて表示します。",
                    "checks": [
                        {
                            "name": "演出コード",
                            "status": "success" if animation_found else "warning",
                            "message": "animation/transition定義を確認しました。" if animation_found else "演出コードを確認できませんでした。",
                        },
                        {
                            "name": "ブラウザでの見た目",
                            "status": "not_verified",
                            "message": "プレビューまたは目視確認が必要です。",
                        },
                    ],
                }
            )
            result.add_log("🎬 画面演出の静的確認を記録しました。")

    def _combined_source_text(self, root: Path) -> str:
        chunks: List[str] = []
        total = 0
        limit = min(self.max_file_bytes * 4, 20 * 1024 * 1024)
        suffixes = self.SOURCE_SUFFIXES | {".css", ".html"}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in suffixes:
                continue
            try:
                relative_parts = path.relative_to(root).parts
            except ValueError:
                continue
            if any(part.casefold() in self.EXCLUDED_SCAN_DIRS for part in relative_parts):
                continue
            try:
                resolved = path.resolve()
                if not self._is_inside(resolved, root):
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            total += len(text)
            if total > limit:
                break
            chunks.append(text)
        return "\n".join(chunks)

    def _validate_plan_files(
        self, plan: BuildPlan, root: Path, result: BuildValidationResult
    ) -> None:
        result.add_log("📁 BuildPlanのファイルを確認します。")
        for file_spec in plan.files:
            result.checked_files += 1
            try:
                path = self._resolve_inside(root, file_spec.path)
            except ValueError:
                result.add_error(
                    "UNSAFE_FILE_PATH", "project_root外を参照するファイルです。", file_spec.path
                )
                continue
            if not path.exists():
                method = result.add_error if file_spec.required else result.add_warning
                method(
                    "REQUIRED_FILE_MISSING" if file_spec.required else "OPTIONAL_FILE_MISSING",
                    "必須ファイルが存在しません。" if file_spec.required else "任意ファイルが存在しません。",
                    file_spec.path,
                )
                continue
            if not path.is_file():
                result.add_error(
                    "NOT_A_FILE", "ファイルとして定義されていますが、実体がファイルではありません。", file_spec.path
                )
                continue
            try:
                size = path.stat().st_size
            except OSError:
                result.add_error("FILE_READ_ERROR", "ファイル情報を取得できません。", file_spec.path)
                continue
            if size == 0:
                result.add_error("EMPTY_FILE", "ファイルが空です。", file_spec.path)
                continue
            if size > self.max_file_bytes:
                result.add_error("FILE_TOO_LARGE", "静的検証のファイルサイズ上限を超えています。", file_spec.path)
                continue
            if path.suffix.casefold() == ".json":
                self._validate_json(path, root, result)
        result.add_log(f"📁 {result.checked_files}個のBuildPlanファイルを確認しました。")

    def _validate_json(self, path: Path, root: Path, result: BuildValidationResult) -> None:
        relative = self._relative(path, root)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if path.name.casefold() == "package.json" and not isinstance(value, Mapping):
                result.add_error("INVALID_PACKAGE_JSON", "package.jsonのルートはobjectである必要があります。", relative)
        except json.JSONDecodeError as exc:
            result.add_error(
                "INVALID_JSON",
                f"JSON構文エラーがあります（{exc.lineno}行{exc.colno}列）。",
                relative,
            )
        except (OSError, UnicodeError):
            result.add_error("JSON_READ_ERROR", "JSONファイルを読み込めません。", relative)

    def _validate_react(
        self, plan: BuildPlan, root: Path, result: BuildValidationResult
    ) -> None:
        result.add_log("⚛️ React構成を確認します。")
        self._validate_framework_file_groups(
            plan,
            root,
            result,
            {
                "package manifest": ("package.json",),
                "HTML entry": ("index.html",),
                "React entry": (
                    "src/main.tsx",
                    "src/main.jsx",
                    "src/main.ts",
                    "src/main.js",
                ),
                "React root component": (
                    "src/App.tsx",
                    "src/App.jsx",
                    "src/app.tsx",
                    "src/app.jsx",
                ),
            },
            "REACT_REQUIRED_FILE_MISSING",
            "Reactアプリに必要なファイルがありません。",
        )
        package = self._read_package(root / "package.json", result)
        if package is not None:
            dependencies = self._mapping(package.get("dependencies"))
            dev_dependencies = self._mapping(package.get("devDependencies"))
            scripts = self._mapping(package.get("scripts"))
            if "react" not in dependencies:
                result.add_error("REACT_DEPENDENCY_MISSING", "package.jsonにreactがありません。", "package.json")
            if "react-dom" not in dependencies:
                result.add_error("REACT_DOM_DEPENDENCY_MISSING", "package.jsonにreact-domがありません。", "package.json")
            all_dependencies = {**dependencies, **dev_dependencies}
            if "vite" not in all_dependencies:
                result.add_error("VITE_NOT_FOUND", "Vite React構成ですがviteがありません。", "package.json")
            if not ({"@vitejs/plugin-react", "@vitejs/plugin-react-swc"} & set(all_dependencies)):
                result.add_warning(
                    "VITE_REACT_PLUGIN_MISSING",
                    "@vitejs/plugin-reactまたは@vitejs/plugin-react-swcが見つかりません。",
                    "package.json",
                )
            if "dev" not in scripts:
                result.add_warning("DEV_SCRIPT_MISSING", "npm run dev用のscriptがありません。", "package.json")
            if "build" not in scripts:
                result.add_error("BUILD_SCRIPT_MISSING", "npm run build用のscriptがありません。", "package.json")
        self._validate_source_tree_imports(root / "src", root, result)

    def _validate_nextjs(
        self, plan: BuildPlan, root: Path, result: BuildValidationResult
    ) -> None:
        result.add_log("▲ Next.js構成を確認します。")
        self._validate_framework_file_groups(
            plan,
            root,
            result,
            {
                "package manifest": ("package.json",),
                "Next.js page": (
                    "app/page.tsx",
                    "app/page.jsx",
                    "app/page.ts",
                    "app/page.js",
                    "pages/index.tsx",
                    "pages/index.jsx",
                    "pages/index.ts",
                    "pages/index.js",
                    "src/app/page.tsx",
                    "src/app/page.jsx",
                    "src/pages/index.tsx",
                    "src/pages/index.jsx",
                ),
            },
            "NEXTJS_REQUIRED_FILE_MISSING",
            "Next.jsアプリに必要なファイルがありません。",
        )
        package = self._read_package(root / "package.json", result)
        if package is not None:
            dependencies = self._mapping(package.get("dependencies"))
            scripts = self._mapping(package.get("scripts"))
            for dependency in ("next", "react", "react-dom"):
                if dependency not in dependencies:
                    result.add_error(
                        "NEXTJS_DEPENDENCY_MISSING",
                        f"package.jsonに{dependency}がありません。",
                        "package.json",
                    )
            for script in ("dev", "build", "start"):
                if script not in scripts:
                    result.add_warning(
                        "NEXTJS_SCRIPT_MISSING", f"{script} scriptがありません。", "package.json"
                    )
        self._validate_source_tree_imports(root / "app", root, result)

    def _validate_html_project(
        self, plan: BuildPlan, root: Path, result: BuildValidationResult
    ) -> None:
        result.add_log("🌐 HTML構成を確認します。")
        self._validate_framework_files(
            plan,
            root,
            result,
            ("index.html", "style.css", "script.js"),
            "HTML_REQUIRED_FILE_MISSING",
            "HTMLアプリに必要なファイルがありません。",
        )
        index = root / "index.html"
        if index.is_file():
            self._validate_html_references(index, root, result)

    def _validate_framework_files(
        self,
        plan: BuildPlan,
        root: Path,
        result: BuildValidationResult,
        required: Iterable[str],
        code: str,
        message: str,
    ) -> None:
        for relative in required:
            try:
                exists = self._resolve_inside(root, relative).is_file()
            except ValueError:
                exists = False
            # Planned missing files already have the generic repairable code.
            if not exists and not plan.has_file(relative):
                result.add_error(code, message, relative)

    def _validate_framework_file_groups(
        self,
        plan: BuildPlan,
        root: Path,
        result: BuildValidationResult,
        required_groups: Mapping[str, Sequence[str]],
        code: str,
        message: str,
    ) -> None:
        """Require one existing file from each semantic candidate group.

        BuildPlan file validation already reports a missing planned file with
        ``REQUIRED_FILE_MISSING``.  This framework-level check is therefore
        added only when no candidate was planned, preventing duplicate errors.
        """
        for role, candidates in required_groups.items():
            existing = False
            for relative in candidates:
                try:
                    if self._resolve_inside(root, relative).is_file():
                        existing = True
                        break
                except ValueError:
                    continue
            if existing:
                continue

            planned = any(plan.has_file(relative) for relative in candidates)
            if planned:
                continue

            preferred = self._preferred_candidate(plan, candidates)
            result.add_error(code, f"{message}（{role}）", preferred)

    @staticmethod
    def _preferred_candidate(plan: BuildPlan, candidates: Sequence[str]) -> str:
        """Choose the most useful repair target for the plan language."""
        metadata = plan.metadata if isinstance(plan.metadata, Mapping) else {}
        language = str(metadata.get("language", "")).casefold()
        use_typescript = bool(metadata.get("use_typescript")) or language in {
            "ts",
            "typescript",
        }
        preferred_suffixes = (".tsx", ".ts") if use_typescript else (".jsx", ".js")
        for suffix in preferred_suffixes:
            for candidate in candidates:
                if candidate.casefold().endswith(suffix):
                    return candidate
        return candidates[0] if candidates else ""

    def _read_package(
        self, path: Path, result: BuildValidationResult
    ) -> Optional[Mapping[str, Any]]:
        if not path.is_file():
            return None
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(package, Mapping):
                result.add_error("INVALID_PACKAGE_JSON", "package.jsonのルートはobjectである必要があります。", "package.json")
                return None
            return package
        except json.JSONDecodeError:
            # _validate_json already reports the precise syntax location.
            return None
        except (OSError, UnicodeError):
            result.add_error("PACKAGE_JSON_READ_ERROR", "package.jsonを読み込めません。", "package.json")
            return None

    def _validate_source_tree_imports(
        self, source_root: Path, project_root: Path, result: BuildValidationResult
    ) -> None:
        if not source_root.is_dir():
            return
        for path in source_root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in self.SOURCE_SUFFIXES:
                try:
                    resolved = path.resolve()
                    if not self._is_inside(resolved, project_root):
                        result.add_error("UNSAFE_SOURCE_PATH", "project_root外のソースファイルです。", self._relative(path, project_root))
                        continue
                except OSError:
                    continue
                self._validate_imports(path, project_root, result)

    def _validate_imports(
        self, file_path: Path, root: Path, result: BuildValidationResult
    ) -> None:
        relative_file = self._relative(file_path, root)
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            result.add_error("SOURCE_READ_ERROR", "ソースファイルを読み込めません。", relative_file)
            return
        for match in self.IMPORT_PATTERN.finditer(content):
            import_path = match.group(1).strip()
            if not import_path.startswith("."):
                continue
            import_path = import_path.split("?", 1)[0].split("#", 1)[0]
            candidate = (file_path.parent / import_path).resolve()
            if not self._is_inside(candidate, root):
                result.add_error(
                    "IMPORT_OUTSIDE_PROJECT",
                    f"project_root外のimportは禁止されています: {import_path}",
                    relative_file,
                )
            elif not self._import_exists(candidate):
                result.add_error(
                    "IMPORT_NOT_FOUND", f"import先が見つかりません: {import_path}", relative_file
                )

    def _validate_html_references(
        self, index: Path, root: Path, result: BuildValidationResult
    ) -> None:
        try:
            content = index.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return
        for match in self.HTML_REFERENCE_PATTERN.finditer(content):
            reference = match.group(1).strip().split("?", 1)[0].split("#", 1)[0]
            if not reference or reference.startswith(("http://", "https://", "//", "data:", "#")):
                continue
            try:
                target = self._resolve_inside(root, reference.lstrip("/"))
            except ValueError:
                result.add_error("HTML_REFERENCE_OUTSIDE_PROJECT", "project_root外の参照は禁止されています。", "index.html")
                continue
            if not target.is_file():
                result.add_error("HTML_ASSET_NOT_FOUND", f"参照ファイルが見つかりません: {reference}", "index.html")

    def _import_exists(self, candidate: Path) -> bool:
        candidates = [candidate]
        if not candidate.suffix:
            candidates.extend(candidate.with_suffix(suffix) for suffix in self.IMPORT_SUFFIXES)
        candidates.extend(candidate / f"index{suffix}" for suffix in self.IMPORT_SUFFIXES)
        return any(path.is_file() for path in candidates)

    def _resolve_inside(self, root: Path, relative: str) -> Path:
        normalized = str(relative or "").replace("\\", "/").strip()
        candidate = (root / normalized).resolve()
        if candidate == root or not self._is_inside(candidate, root):
            raise ValueError("path escapes project root")
        return candidate

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _is_inside(target: Path, root: Path) -> bool:
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _relative(path: Path, root: Path) -> str:
        try:
            return str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            return path.name

    def _debug(self, message: str) -> None:
        self.last_diagnostics.append(message)
        if self.enable_debug:
            print(f"[BuildValidator] {message}", flush=True)


__all__ = ["BuildValidator", "BuildValidationResult", "ValidationIssue"]
