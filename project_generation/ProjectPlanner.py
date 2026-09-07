"""Create a validated, scalable BuildPlan from normalized requirements.

The planner accepts an optional LLM proposal, but Python owns normalization,
required files, architecture profiles, dependency edges, and safety limits.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .BuildPlan import BuildFile, BuildPlan


class ProjectPlanner:
    """Plan runnable HTML, React/Vite, or Next.js projects.

    Design principles:
    - Explicit user requirements override an LLM proposal.
    - TypeScript is planned end-to-end when requested.
    - Scale and architecture are separate from feature detection.
    - CRUD files are added only for actual CRUD requirements.
    - Every accepted plan is normalized and validated before returning.
    """

    SUPPORTED_FRAMEWORKS = ("react", "nextjs", "html")
    SUPPORTED_LANGUAGES = ("typescript", "javascript")
    SUPPORTED_SCALES = ("small", "medium", "large")

    MAX_LLM_OUTPUT_CHARS = 1_000_000
    MAX_CONTEXT_CHARS = 80_000
    MAX_PLANNED_FILES = 120

    FRAMEWORK_ALIASES = {
        "reactjs": "react",
        "react.js": "react",
        "react ts": "react",
        "react typescript": "react",
        "vite": "react",
        "vite react": "react",
        "next": "nextjs",
        "next.js": "nextjs",
        "next js": "nextjs",
        "vanilla": "html",
        "vanilla js": "html",
        "vanilla_js": "html",
        "vanilla javascript": "html",
        "static html": "html",
    }

    FEATURE_ALIASES: Dict[str, Tuple[str, ...]] = {
        "create": ("create", "作成", "追加", "新規登録", "新しく作る"),
        "edit": ("edit", "編集", "更新", "修正"),
        "delete": ("delete", "削除", "消去"),
        "list": ("list", "一覧", "リスト表示"),
        "detail": ("detail", "詳細", "詳細表示"),
        "history": ("history", "履歴", "操作履歴"),
        "search": ("search", "検索", "絞り込み"),
        "filter": ("filter", "フィルター", "条件指定"),
        "sort": ("sort", "並び替え", "ソート"),
        "favorite": ("favorite", "お気に入り", "ブックマーク"),
        "calendar": ("calendar", "カレンダー", "予定表"),
        "chat": ("chat", "チャット", "会話"),
        "dashboard": ("dashboard", "ダッシュボード", "集計画面"),
        "settings": ("settings", "設定画面", "環境設定"),
        "authentication": ("authentication", "login", "ログイン", "認証"),
        "validation": ("validation", "入力検証", "バリデーション"),
        "local_storage": ("localstorage", "local storage", "ローカル保存"),
        "import_export": ("import", "export", "インポート", "エクスポート"),
        "upload": ("upload", "アップロード", "ファイル選択"),
        "responsive": ("responsive", "レスポンシブ", "スマホ対応"),
        "accessibility": ("accessibility", "a11y", "アクセシビリティ"),
        "testing": ("test", "testing", "テスト", "vitest"),
    }

    CRUD_FEATURES = {"create", "edit", "delete", "list", "detail", "history"}

    PAGE_NAME_ALIASES = {
        "ホーム": "Home",
        "トップ": "Home",
        "一覧": "List",
        "詳細": "Detail",
        "設定": "Settings",
        "カレンダー": "Calendar",
        "チャット": "Chat",
        "ダッシュボード": "Dashboard",
        "履歴": "History",
    }

    def __init__(
        self,
        llm_engine: Optional[Any] = None,
        prompt_builder: Optional[Any] = None,
        enable_debug: bool = True,
        max_llm_attempts: int = 2,
        max_planned_files: int = MAX_PLANNED_FILES,
    ) -> None:
        self.llm_engine = llm_engine
        self.prompt_builder = prompt_builder
        self.enable_debug = bool(enable_debug)
        self.max_llm_attempts = max(1, min(int(max_llm_attempts), 3))
        self.max_planned_files = max(10, min(int(max_planned_files), 500))
        self.last_diagnostics: List[str] = []

    def plan(
        self,
        project_context: Dict[str, Any],
        use_ai: bool = True,
    ) -> BuildPlan:
        """Return a validated BuildPlan using LLM proposal or safe fallback."""

        self.last_diagnostics = []
        context = self._normalize_context(project_context)
        self._debug(
            "planning started "
            f"framework={context['framework']} "
            f"language={context['language']} "
            f"scale={context['scale']} "
            f"features={context['features']} "
            f"use_ai={use_ai}"
        )

        candidate: Optional[BuildPlan] = None
        source = "deterministic_fallback"
        if use_ai and self._llm_available():
            candidate = self._plan_with_llm(context)
            if candidate is not None:
                source = "llm"

        if candidate is None:
            candidate = self._build_fallback_plan(context)

        plan = self._normalize_plan(candidate, context, source=source)
        errors = plan.validate()

        if errors and source == "llm":
            self._debug("LLM plan rejected: " + " / ".join(errors))
            plan = self._normalize_plan(
                self._build_fallback_plan(context),
                context,
                source="deterministic_fallback_after_llm_rejection",
            )

        plan.validate_or_raise()
        self._debug(
            f"planning completed files={len(plan.files)} "
            f"source={plan.metadata.get('planning_source')}"
        )
        return plan

    # ------------------------------------------------------------------
    # LLM planning
    # ------------------------------------------------------------------

    def _llm_available(self) -> bool:
        if self.llm_engine is None:
            return False
        availability = getattr(self.llm_engine, "is_available", True)
        try:
            result = availability() if callable(availability) else availability
            if inspect.isawaitable(result):
                self._close_awaitable(result)
                self._debug("async LLM availability is unsupported; using fallback")
                return False
            return bool(result)
        except Exception as exc:
            self._debug(f"LLM availability check failed: {type(exc).__name__}: {exc}")
            return False

    def _plan_with_llm(self, context: Dict[str, Any]) -> Optional[BuildPlan]:
        last_error = "unknown error"
        for attempt in range(1, self.max_llm_attempts + 1):
            try:
                messages = self._build_planning_messages(context)
                result = self._call_llm(messages)
                if inspect.isawaitable(result):
                    self._close_awaitable(result)
                    self._debug("async LLM result is unsupported; using fallback")
                    return None
                text = self._result_text(result)
                if not text:
                    last_error = "LLM returned no usable planning text"
                    continue
                plan = BuildPlan.from_dict(self._parse_llm_json(text))
                self._debug(f"LLM plan parsed on attempt {attempt}")
                return plan
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._debug(
                    f"LLM planning attempt {attempt}/{self.max_llm_attempts} "
                    f"failed: {last_error}"
                )
        self._debug(f"LLM planning exhausted: {last_error}")
        return None

    def _build_planning_messages(self, context: Dict[str, Any]) -> Any:
        builder = self.prompt_builder
        if builder is not None:
            for method_name in (
                "build_planning_messages",
                "build_project_plan_messages",
                "build_project_plan_prompt",
            ):
                method = getattr(builder, method_name, None)
                if callable(method):
                    try:
                        return method(project_context=context)
                    except TypeError:
                        return method(context)

        file_target = {
            "small": "8-15",
            "medium": "18-35",
            "large": "35-80",
        }[context["scale"]]
        schema = {
            "project_name": "safe-kebab-case string",
            "description": "string",
            "framework": "react | nextjs | html",
            "language": "typescript | javascript",
            "features": ["canonical feature string"],
            "file_structure": [
                {
                    "path": "safe relative/path",
                    "type": "component | page | style | config | data | test | file",
                    "language": "typescript | javascript | html | css | json | markdown",
                    "description": "single responsibility",
                    "required": True,
                    "dependencies": ["another planned relative/path"],
                }
            ],
            "dependencies": ["npm package"],
            "dev_dependencies": ["npm package"],
            "scripts": {"command": "value"},
        }
        system = (
            "Return exactly one JSON object for a runnable project. No markdown. "
            "Use only safe relative paths. Do not create placeholder-only files. "
            "Each file must have one clear responsibility. All dependency paths "
            "must refer to files in file_structure. Respect frontend_only, no_db, "
            "no_auth, and no_external_api constraints. "
            f"Target approximately {file_target} files. Schema: "
            + json.dumps(schema, ensure_ascii=False)
        )
        safe_context = self._bounded_context(context)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(safe_context, ensure_ascii=False)},
        ]

    def _call_llm(self, messages: Any) -> Any:
        assert self.llm_engine is not None
        chat = getattr(self.llm_engine, "chat", None)
        if callable(chat):
            return chat(messages, temperature=0.15, max_tokens=8000)
        generate = getattr(self.llm_engine, "generate", None)
        if callable(generate):
            return generate(messages)
        raise TypeError("LLM engine must provide chat() or generate()")

    @staticmethod
    def _result_text(result: Any) -> str:
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, Mapping):
            if result.get("success") is False:
                return ""
            return str(result.get("text") or result.get("content") or "").strip()
        if getattr(result, "success", True) is False:
            return ""
        return str(
            getattr(result, "text", None)
            or getattr(result, "content", None)
            or ""
        ).strip()

    def _parse_llm_json(self, text: str) -> Dict[str, Any]:
        cleaned = str(text or "").strip().lstrip("\ufeff")
        if not cleaned:
            raise ValueError("LLM output is empty")
        if len(cleaned) > self.MAX_LLM_OUTPUT_CHARS:
            raise ValueError("LLM output is too large")
        cleaned = re.sub(r"^\s*```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            if not isinstance(parsed, dict):
                raise TypeError("planning output must be a JSON object")
            return parsed
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for start, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(cleaned[start:])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        raise ValueError("LLM output does not contain a JSON object")

    # ------------------------------------------------------------------
    # Context normalization
    # ------------------------------------------------------------------

    def _normalize_context(self, project_context: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(project_context, dict):
            raise TypeError("project_context は dict である必要があります。")

        context = dict(project_context)
        context["project_name"] = self._safe_project_name(
            str(context.get("project_name") or "generated-app")
        )
        context["raw_requirements"] = self._normalize_string_list(
            context.get("raw_requirements")
        )

        raw_text = self._context_text(context)
        framework = str(context.get("framework") or "").lower().strip()
        framework = self.FRAMEWORK_ALIASES.get(framework, framework)
        if not framework:
            framework = self._infer_framework(raw_text)
        if framework not in self.SUPPORTED_FRAMEWORKS:
            self._debug(f"unsupported framework {framework!r}; using react")
            framework = "react"
        context["framework"] = framework

        language = str(context.get("language") or "").lower().strip()
        if self._coerce_bool(context.get("use_typescript"), False):
            language = "typescript"
        if language in {"ts", "tsx", "react-ts", "react_typescript"}:
            language = "typescript"
        elif language in {"js", "jsx"}:
            language = "javascript"
        if language not in self.SUPPORTED_LANGUAGES:
            language = self._infer_language(raw_text, framework)
        if framework == "html":
            language = "javascript"
        context["language"] = language
        context["use_typescript"] = language == "typescript"

        raw_features = self._normalize_string_list(context.get("features"))
        context["raw_features"] = raw_features
        context["features"] = self._canonicalize_features(raw_features, raw_text)

        for key in (
            "pages",
            "design_preferences",
            "constraints",
            "dependencies",
            "dev_dependencies",
        ):
            context[key] = self._normalize_string_list(context.get(key))

        context["constraints"] = self._normalize_constraints(
            context["constraints"], raw_text
        )
        context["scale"] = self._infer_scale(context, raw_text)

        for key in ("description", "purpose", "target_user", "database", "backend"):
            value = context.get(key)
            context[key] = (str(value).strip() or None) if value is not None else None

        if "frontend_only" in context["constraints"]:
            context["backend"] = "none"
        if "no_db" in context["constraints"]:
            context["database"] = "none"
        return context

    def _context_text(self, context: Mapping[str, Any]) -> str:
        values: List[str] = []
        for key in (
            "description",
            "purpose",
            "framework",
            "language",
            "features",
            "pages",
            "constraints",
            "raw_requirements",
        ):
            value = context.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value)
            elif value is not None:
                values.append(str(value))
        return " ".join(values).lower()

    @staticmethod
    def _infer_framework(text: str) -> str:
        if any(word in text for word in ("next.js", "nextjs", "next js")):
            return "nextjs"
        if any(word in text for word in ("react", "tsx", "vite")):
            return "react"
        if any(word in text for word in ("htmlだけ", "htmlのみ", "vanilla", "静的html")):
            return "html"
        # Larger app requests default to React instead of the three-file HTML demo.
        return "react"

    @staticmethod
    def _infer_language(text: str, framework: str) -> str:
        if framework == "html":
            return "javascript"
        if any(word in text for word in ("typescript", "tsx", "型定義", "tsで")):
            return "typescript"
        return "javascript"

    def _canonicalize_features(
        self,
        raw_features: Sequence[str],
        raw_text: str,
    ) -> List[str]:
        search_texts = [str(item).lower() for item in raw_features]
        search_texts.append(raw_text)
        detected: List[str] = []
        for canonical, aliases in self.FEATURE_ALIASES.items():
            if any(
                self._alias_matches(text, alias)
                for text in search_texts
                for alias in aliases
            ):
                detected.append(canonical)

        if any("crud" in text for text in search_texts):
            detected.extend(["create", "edit", "delete", "list"])

        # Keep unknown explicit feature names as normalized extension points.
        for feature in raw_features:
            if any(
                self._alias_matches(feature.lower(), alias)
                for aliases in self.FEATURE_ALIASES.values()
                for alias in aliases
            ):
                continue
            normalized = re.sub(r"\s+", "_", feature.strip().lower())
            if normalized:
                detected.append(normalized)
        return self._merge_unique([], detected)

    def _normalize_constraints(self, constraints: Sequence[str], text: str) -> List[str]:
        normalized = [str(item).strip().lower() for item in constraints if str(item).strip()]
        rules = {
            "frontend_only": ("frontend only", "frontend-only", "フロントエンドのみ", "バックエンドなし"),
            "no_db": ("no db", "no database", "dbなし", "データベースなし"),
            "no_auth": ("no auth", "no login", "ログインなし", "認証なし"),
            "no_external_api": ("no external api", "外部apiなし", "外部apiを使わない"),
            "offline": ("offline", "オフライン"),
        }
        for canonical, aliases in rules.items():
            if any(alias in text for alias in aliases):
                normalized.append(canonical)
        return self._merge_unique([], normalized)

    def _infer_scale(self, context: Mapping[str, Any], text: str) -> str:
        explicit = str(context.get("scale") or "").strip().lower()
        aliases = {
            "small": "small", "mini": "small", "小規模": "small",
            "medium": "medium", "middle": "medium", "中規模": "medium",
            "large": "large", "enterprise": "large", "大規模": "large",
        }
        if explicit in aliases:
            return aliases[explicit]
        if any(word in text for word in ("大規模", "本格的", "enterprise", "50ファイル")):
            return "large"
        if any(word in text for word in ("中規模", "時間のかかる", "本格アプリ", "20ファイル", "30ファイル")):
            return "medium"
        feature_count = len(context.get("features", []) or [])
        if feature_count >= 10:
            return "large"
        if feature_count >= 4 or set(context.get("features", [])) & self.CRUD_FEATURES:
            return "medium"
        return "small"

    # ------------------------------------------------------------------
    # Plan normalization and architecture expansion
    # ------------------------------------------------------------------

    def _build_fallback_plan(self, context: Dict[str, Any]) -> BuildPlan:
        return BuildPlan(
            project_name=context["project_name"],
            description=str(
                context.get("description")
                or context.get("purpose")
                or "Generated application"
            ),
            framework=context["framework"],
            features=context["features"],
            pages=context["pages"],
            target_user=context.get("target_user"),
            purpose=context.get("purpose"),
            database=context.get("database"),
            backend=context.get("backend"),
            design_preferences=context["design_preferences"],
            constraints=context["constraints"],
            dependencies=context["dependencies"],
            dev_dependencies=context["dev_dependencies"],
            metadata={"planner": "deterministic_fallback"},
        )

    def _normalize_plan(
        self,
        plan: BuildPlan,
        context: Dict[str, Any],
        *,
        source: str,
    ) -> BuildPlan:
        context_name = context["project_name"]
        plan.project_name = self._safe_project_name(
            context_name if context_name != "generated-app" else plan.project_name
        )
        plan.framework = context["framework"]
        if not plan.description:
            plan.description = str(
                context.get("description")
                or context.get("purpose")
                or "Generated application"
            )

        for attribute in ("target_user", "purpose", "database", "backend"):
            value = context.get(attribute)
            if value is not None:
                setattr(plan, attribute, value)

        for attribute in (
            "features",
            "pages",
            "design_preferences",
            "constraints",
            "dependencies",
            "dev_dependencies",
        ):
            setattr(
                plan,
                attribute,
                self._merge_unique(
                    getattr(plan, attribute, []),
                    context.get(attribute, []),
                ),
            )

        if "frontend_only" in plan.constraints:
            plan.backend = "none"
        if "no_db" in plan.constraints:
            plan.database = "none"
        if "no_auth" in plan.constraints:
            plan.features = [item for item in plan.features if item != "authentication"]

        self._ensure_framework_dependencies(plan, context)
        self._ensure_required_files(plan, context)
        self._add_common_architecture(plan, context)
        self._add_feature_files(plan, context)
        self._add_page_files(plan, context)
        self._ensure_file_dependencies(plan, context)
        self._enforce_plan_limits(plan)

        plan.metadata.setdefault("planner_normalized", True)
        plan.metadata["planning_source"] = source
        plan.metadata["language"] = context["language"]
        plan.metadata["use_typescript"] = context["use_typescript"]
        plan.metadata["project_scale"] = context["scale"]
        plan.metadata["raw_features"] = context.get("raw_features", [])
        plan.metadata["raw_requirements"] = context.get("raw_requirements", [])
        plan.metadata["planned_file_count"] = len(plan.files)
        return plan.normalize()

    def _ensure_framework_dependencies(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        if plan.framework == "react":
            plan.dependencies = self._merge_unique(plan.dependencies, ["react", "react-dom"])
            dev = ["vite", "@vitejs/plugin-react", "vitest", "jsdom"]
            if context["use_typescript"]:
                dev.extend(["typescript", "@types/react", "@types/react-dom"])
            if "testing" in plan.features:
                dev.extend(["@testing-library/react", "@testing-library/jest-dom"])
            plan.dev_dependencies = self._merge_unique(plan.dev_dependencies, dev)
            defaults = {
                "dev": "vite",
                "build": (
                    "tsc --noEmit && vite build"
                    if context["use_typescript"]
                    else "vite build"
                ),
                "preview": "vite preview",
                "test": "vitest run",
                "test:watch": "vitest",
            }
        elif plan.framework == "nextjs":
            plan.dependencies = self._merge_unique(
                plan.dependencies, ["next", "react", "react-dom"]
            )
            if context["use_typescript"]:
                plan.dev_dependencies = self._merge_unique(
                    plan.dev_dependencies,
                    ["typescript", "@types/react", "@types/node"],
                )
            defaults = {
                "dev": "next dev",
                "build": "next build",
                "start": "next start",
            }
        else:
            defaults = {}
        for name, command in defaults.items():
            plan.scripts.setdefault(name, command)

    def _extensions(self, context: Mapping[str, Any]) -> Tuple[str, str]:
        return ("tsx", "ts") if context["use_typescript"] else ("jsx", "js")

    def _ensure_required_files(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        component_ext, module_ext = self._extensions(context)
        if plan.framework == "react":
            required = [
                ("package.json", "config", "json", "Vite package configuration."),
                (f"vite.config.{module_ext}", "config", context["language"], "Vite configuration."),
                ("index.html", "html", "html", "Vite HTML entry point."),
                (f"src/main.{component_ext}", "entry", context["language"], "Mounts React."),
                (f"src/App.{component_ext}", "component", context["language"], "Root component."),
                ("src/index.css", "style", "css", "Global styles."),
                (f"src/test/setup.{module_ext}", "test", context["language"], "Vitest setup."),
                ("README.md", "documentation", "markdown", "Setup and run instructions."),
            ]
            if context["use_typescript"]:
                required.extend(
                    [
                        ("tsconfig.json", "config", "json", "TypeScript configuration."),
                        ("src/vite-env.d.ts", "file", "typescript", "Vite environment types."),
                    ]
                )
        elif plan.framework == "nextjs":
            required = [
                ("package.json", "config", "json", "Next.js package configuration."),
                (f"app/layout.{component_ext}", "layout", context["language"], "Root layout."),
                (f"app/page.{component_ext}", "page", context["language"], "Home page."),
                ("app/globals.css", "style", "css", "Global styles."),
            ]
            if context["use_typescript"]:
                required.append(("tsconfig.json", "config", "json", "TypeScript configuration."))
        else:
            required = [
                ("index.html", "html", "html", "Application entry point."),
                ("style.css", "style", "css", "Application styles."),
                ("script.js", "script", "javascript", "Client-side behavior."),
            ]

        for path, file_type, language, description in required:
            self._add_file(
                plan,
                path,
                file_type,
                language,
                description,
                required=path != "README.md",
            )

    def _add_common_architecture(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        if plan.framework != "react" or context["scale"] == "small":
            return
        component_ext, module_ext = self._extensions(context)
        language = context["language"]
        common = [
            (f"src/components/AppHeader.{component_ext}", "component", language, "Application header."),
            (f"src/components/EmptyState.{component_ext}", "component", language, "Reusable empty state."),
            (f"src/components/ErrorMessage.{component_ext}", "component", language, "Accessible error display."),
            (f"src/hooks/useLocalStorage.{module_ext}", "file", language, "Safe localStorage hook."),
            (f"src/utils/createId.{module_ext}", "file", language, "Stable client-side ID helper."),
            (f"src/utils/formatDate.{module_ext}", "file", language, "Date formatting helper."),
            ("src/styles/components.css", "style", "css", "Shared component styles."),
            (f"tests/smoke.test.{module_ext}", "test", language, "Project smoke tests."),
        ]
        for spec in common:
            self._add_file(plan, *spec)

        if context["scale"] == "large":
            large = [
                (f"src/components/AppNavigation.{component_ext}", "component", language, "Primary navigation."),
                (f"src/components/LoadingState.{component_ext}", "component", language, "Loading feedback."),
                (f"src/hooks/useDebouncedValue.{module_ext}", "file", language, "Debounced state helper."),
                (f"src/services/storageService.{module_ext}", "file", language, "Storage boundary."),
                (f"src/utils/result.{module_ext}", "file", language, "Typed operation result."),
                (f"tests/accessibility.test.{module_ext}", "test", language, "Accessibility regression checks."),
            ]
            for spec in large:
                self._add_file(plan, *spec)

    def _add_feature_files(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        if plan.framework != "react":
            return
        component_ext, module_ext = self._extensions(context)
        language = context["language"]
        features = set(plan.features)

        if features & self.CRUD_FEATURES:
            crud = [
                (f"src/types/Item.{module_ext}", "file", language, "Item and history types."),
                (f"src/components/ItemForm.{component_ext}", "component", language, "Create and edit form."),
                (f"src/components/ItemList.{component_ext}", "component", language, "Item collection."),
                (f"src/components/ItemCard.{component_ext}", "component", language, "Item actions."),
                (f"src/components/HistoryPanel.{component_ext}", "component", language, "Operation history."),
                (f"src/components/ConfirmDialog.{component_ext}", "component", language, "Confirmation dialog."),
                (f"src/hooks/useItemManager.{module_ext}", "file", language, "CRUD state orchestration."),
                (f"src/services/itemRepository.{module_ext}", "file", language, "Persistence repository."),
                (f"src/utils/validation.{module_ext}", "file", language, "Input validation."),
                (f"src/data/initialItems.{module_ext}", "data", language, "Initial records."),
                ("src/styles/forms.css", "style", "css", "Form and action styles."),
                (f"tests/validation.test.{module_ext}", "test", language, "Validation unit tests."),
                (f"tests/itemRepository.test.{module_ext}", "test", language, "Repository unit tests."),
            ]
            for spec in crud:
                self._add_file(plan, *spec)

        feature_components = {
            "favorite": ("FavoriteButton", "Favorite toggle UI."),
            "search": ("SearchBar", "Search input UI."),
            "filter": ("FilterPanel", "Filter controls."),
            "sort": ("SortControl", "Sort controls."),
            "calendar": ("CalendarView", "Calendar UI."),
            "chat": ("ChatPanel", "Chat history and input UI."),
            "dashboard": ("DashboardView", "Summary dashboard."),
            "settings": ("SettingsPanel", "Application settings."),
            "authentication": ("LoginForm", "Authentication form."),
            "upload": ("FileUpload", "File selection UI."),
            "import_export": ("ImportExportPanel", "Import and export UI."),
        }
        for feature, (name, description) in feature_components.items():
            if feature in features:
                self._add_file(
                    plan,
                    f"src/components/{name}.{component_ext}",
                    "component",
                    language,
                    description,
                )

    def _add_page_files(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        if plan.framework != "react":
            return
        component_ext, _ = self._extensions(context)
        for index, page in enumerate(plan.pages, start=1):
            alias = next(
                (
                    english
                    for japanese, english in self.PAGE_NAME_ALIASES.items()
                    if japanese in str(page)
                ),
                "",
            )
            name = self._component_name(alias or page) or f"GeneratedPage{index}"
            if name:
                self._add_file(
                    plan,
                    f"src/pages/{name}.{component_ext}",
                    "page",
                    context["language"],
                    f"{name} page component.",
                )

    def _ensure_file_dependencies(
        self,
        plan: BuildPlan,
        context: Mapping[str, Any],
    ) -> None:
        if plan.framework != "react":
            return
        component_ext, module_ext = self._extensions(context)
        main_path = f"src/main.{component_ext}"
        app_path = f"src/App.{component_ext}"
        main = plan.get_file(main_path)
        if main:
            main.dependencies = self._merge_unique(
                main.dependencies, [app_path, "src/index.css"]
            )

        app = plan.get_file(app_path)
        if app:
            children = [
                item.path
                for item in plan.files
                if item.path.startswith(("src/pages/", "src/components/"))
                and item.path != app_path
                and ".test." not in item.path
            ]
            app.dependencies = self._merge_unique(app.dependencies, children)

        edges = {
            f"src/components/ItemForm.{component_ext}": [
                f"src/types/Item.{module_ext}",
                f"src/utils/validation.{module_ext}",
            ],
            f"src/components/ItemList.{component_ext}": [
                f"src/types/Item.{module_ext}",
                f"src/components/ItemCard.{component_ext}",
            ],
            f"src/hooks/useItemManager.{module_ext}": [
                f"src/types/Item.{module_ext}",
                f"src/hooks/useLocalStorage.{module_ext}",
                f"src/services/itemRepository.{module_ext}",
                f"src/data/initialItems.{module_ext}",
            ],
            f"src/services/itemRepository.{module_ext}": [
                f"src/types/Item.{module_ext}",
            ],
            f"tests/validation.test.{module_ext}": [
                f"src/utils/validation.{module_ext}",
            ],
            f"tests/itemRepository.test.{module_ext}": [
                f"src/services/itemRepository.{module_ext}",
            ],
        }
        for path, dependencies in edges.items():
            target = plan.get_file(path)
            if target:
                target.dependencies = self._merge_unique(
                    target.dependencies,
                    [dependency for dependency in dependencies if plan.has_file(dependency)],
                )

    def _add_file(
        self,
        plan: BuildPlan,
        path: str,
        file_type: str,
        language: str,
        description: str,
        required: bool = True,
    ) -> None:
        if plan.has_file(path):
            return
        plan.add_file(
            BuildFile(
                path=path,
                type=file_type,
                language=language,
                description=description,
                required=required,
            )
        )

    def _enforce_plan_limits(self, plan: BuildPlan) -> None:
        if len(plan.files) <= self.max_planned_files:
            return
        required = [item for item in plan.files if getattr(item, "required", True)]
        optional = [item for item in plan.files if not getattr(item, "required", True)]
        if len(required) > self.max_planned_files:
            raise ValueError(
                f"必須ファイル数が上限を超えました: {len(required)} > {self.max_planned_files}"
            )
        plan.files = (required + optional)[: self.max_planned_files]
        allowed = {item.path.casefold() for item in plan.files}
        for item in plan.files:
            item.dependencies = [
                dependency
                for dependency in item.dependencies
                if dependency.casefold() in allowed
            ]
        self._debug(f"plan truncated to {self.max_planned_files} files")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _bounded_context(self, context: Mapping[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        used = 0
        for key, value in context.items():
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            if used + len(serialized) > self.MAX_CONTEXT_CHARS:
                continue
            result[key] = value
            used += len(serialized)
        return result

    @staticmethod
    def _alias_matches(text: str, alias: str) -> bool:
        normalized_text = str(text).lower()
        normalized_alias = str(alias).lower().strip()
        if not normalized_alias:
            return False
        if re.fullmatch(r"[a-z0-9_ -]+", normalized_alias):
            pattern = (
                rf"(?<![a-z0-9_]){re.escape(normalized_alias)}(?![a-z0-9_])"
            )
            return bool(re.search(pattern, normalized_text))
        return normalized_alias in normalized_text

    @staticmethod
    def _merge_unique(
        first: Optional[Sequence[Any]],
        second: Optional[Sequence[Any]],
    ) -> List[str]:
        result: List[str] = []
        seen: set[str] = set()
        for collection in (first or [], second or []):
            for item in collection:
                value = str(item).strip()
                key = value.casefold()
                if value and key not in seen:
                    result.append(value)
                    seen.add(key)
        return result

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if value is None:
            return []
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return ProjectPlanner._merge_unique([], list(values))

    @staticmethod
    def _safe_project_name(name: str) -> str:
        value = str(name or "generated-app").lower().strip().replace("_", "-")
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[^a-z0-9-]", "-", value)
        value = re.sub(r"-+", "-", value).strip("-")
        return (value or "generated-app")[:80].rstrip("-") or "generated-app"

    @staticmethod
    def _component_name(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-\s]", "", str(value))
        return "".join(
            word[:1].upper() + word[1:]
            for word in re.split(r"[_\-\s]+", cleaned)
            if word
        )

    @staticmethod
    def _coerce_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return default if value is None else bool(value)

    @staticmethod
    def _close_awaitable(value: Any) -> None:
        close = getattr(value, "close", None)
        if callable(close):
            close()

    def _debug(self, message: str) -> None:
        self.last_diagnostics.append(message)
        if self.enable_debug:
            print(f"[ProjectPlanner] {message}", flush=True)


__all__ = ["ProjectPlanner"]
