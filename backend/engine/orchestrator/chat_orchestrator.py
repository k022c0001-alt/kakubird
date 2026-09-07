
# backend/engine/orchestrator/chat_orchestrator.py

from __future__ import annotations

import asyncio
import inspect
import json
import os
import traceback
from pathlib import Path
from typing import Any, Dict, List


from engine.context.ContextManager import ContextManager
from engine.prompt.PromptBuilder import PromptBuilder
from engine.KnowledgeContextSelector import KnowledgeContextSelector
from engine.KnowledgeLoader import KnowledgeLoader
from engine.KnowledgeRouter import KnowledgeRouter
from engine.KnowledgeStartupAudit import KnowledgeStartupAudit
from engine.ProjectProgressAnalyzer import ProjectProgressAnalyzer
from engine.knowledge_health import KnowledgeHealthMonitor
from engine.orchestrator.base_orchestrator import BaseOrchestrator

from api.services.inspectors.IntentInSpector import IntentInspector
from api.services.manager.KnowledgeManager import KnowledgeManager


# ============================================================
# Handlers
# ============================================================

from api.services.handlers.project.repomix_Handler import RepomixHandler
from api.services.handlers.analysis.ocr_recruit_handler import OcrRecruitHandler
from api.services.handlers.github_handler import GithubHandler
from api.services.handlers.recruit_handler import RecruitHandler
from api.services.handlers.weather_handler import WeatherHandler
from api.services.handlers.database_handler import DatabaseHandler
from api.services.handlers.ollama_handler import OllamaHandler
from api.services.handlers.offline_handler import OfflineFallbackHandler
from api.services.handlers.Scraping_Handler import ScrapingHandler
from api.services.handlers.DesignHandler import DesignHandler
from api.services.handlers.code.HtmlHandler import HTMLHandler
from api.services.handlers.project.DeploymentHandler import DeploymentHandler
from api.services.handlers.ChatHandler import ChatHandler
from api.services.handlers.KnowledgeHealthHandler import KnowledgeHealthHandler
from api.services.handlers.KnowledgeReloadHandler import KnowledgeReloadHandler
from api.services.handlers.code.ConversionJsonHandler import ConversionJsonHandler
from api.services.handlers.code.PHPHandler import PhpHandler
from api.services.handlers.Ckan_API_Collect_handler import APICollectHandler
from api.services.handlers.code.Decompositionhandler import DecompositionHandler
from api.services.handlers.Github_guide_handler import GithubGuideHandler
from api.services.handlers.LineFormatHandler import LineFormatHandler
from api.services.handlers.perserhandler import ParserHandler
from api.services.handlers.Math_Handler import MathHandler

# ============================================================
# ProjectBuilderHandlerだけは安全にimportする
#
# ProjectBuilderHandler内部の
# line_formatter等が壊れていても
# routes_chat.py全体を404にしないため。
# ============================================================

PROJECT_BUILDER_AVAILABLE = False
PROJECT_BUILDER_IMPORT_ERROR = None
ProjectBuilderHandler = None

try:
    from api.services.handlers.project.ProjectBuilderHandler import (
        ProjectBuilderHandler,
    )

    PROJECT_BUILDER_AVAILABLE = True

except Exception as e:
    PROJECT_BUILDER_IMPORT_ERROR = e

    print(
        "⚠️ [ChatOrchestrator] "
        "ProjectBuilderHandlerのimportに失敗しました。"
    )

    print(
        "⚠️ [ChatOrchestrator] "
        f"理由: {type(e).__name__}: {e}"
    )

    print(
        "⚠️ [ChatOrchestrator] "
        "Chat API自体は起動を続行します。"
    )


class ChatOrchestrator(BaseOrchestrator):

    def __init__(
        self,
        project_root=None,
        config=None,
        services=None,
    ):
        super().__init__(
            project_root=project_root,
            config=config,
            services=services,
        )

        # ====================================================
        # Core
        # ====================================================

        self.context_manager = ContextManager()
        self.intent_inspector = None
        self.prompt_builder = PromptBuilder()

        self.last_used_handler = "Unknown"
        self.active_context = None

        # ====================================================
        # Path
        #
        # このファイル:
        # backend/engine/orchestrator/chat_orchestrator.py
        #
        # base_dir:
        # backend/engine/orchestrator
        # ====================================================

        base_dir = Path(__file__).resolve().parent

        project_root = (
            base_dir
            / ".."
            / ".."
            / ".."
        ).resolve()

        self.project_root = project_root

        self.knowledge_dir = (
            project_root
            / "plugins"
            / "project_builder"
            / "knowledge"
        ).resolve()

        print(
            "📚 [ChatOrchestrator] "
            f"Knowledge検索先={self.knowledge_dir}"
        )

        self.knowledge_router = None
        self.knowledge_loader = KnowledgeLoader(
            knowledge_dirs=[self.knowledge_dir],
            cache_enabled=True,
        )
        self.knowledge_selector = KnowledgeContextSelector(
            max_items=4,
            max_chars=8_000,
            min_score=1.0,
            fallback_items=1,
        )
        self.project_progress_analyzer = ProjectProgressAnalyzer(
            max_tasks=100,
            max_barriers=30,
            max_next_actions=5,
            in_progress_credit=0.5,
        )
        self.knowledge_health_monitor = KnowledgeHealthMonitor(
            strict=False,
            max_issues=50,
            inspect_empty_content=True,
        )
        self.knowledge_startup_auditor = KnowledgeStartupAudit(
            knowledge_roots=[self.knowledge_dir],
            max_files=1_000,
            max_file_bytes=32 * 1024 * 1024,
            require_markdown_frontmatter=True,
            strict=False,
            cache_path=(
                project_root
                / "backend"
                / ".ai_memory"
                / "knowledge_audit_cache.json"
            ),
            use_cache=True,
        )
        self.knowledge_reload_lock = asyncio.Lock()
        self.knowledge_startup_report: Dict[str, Any] = {
            "status": "not_checked",
            "summary": "Knowledgeの起動時監査はまだ実行されていません",
            "should_warn_user": False,
            "counts": {},
            "valid_paths": [],
            "issues": [],
        }
        self.last_knowledge_health: Dict[str, Any] = {
            "status": "not_checked",
            "summary": "Knowledgeの読込処理はまだ実行されていません",
            "should_warn_user": False,
            "can_use_knowledge": False,
            "expected": False,
            "counts": {},
            "loaded_paths": [],
            "selected_domains": [],
            "dropped_domains": [],
            "issues": [],
        }
        self.last_project_progress: Dict[str, Any] = {
            "goal": None,
            "overall_status": "not_analyzed",
            "progress_percent": None,
            "confidence": "low",
            "current_phase": None,
            "counts": {},
            "tasks": [],
            "barriers": [],
            "next_actions": [],
            "evidence_sources": [],
            "warnings": [],
            "calculation": {},
        }
        self.last_knowledge_selection: Dict[str, Any] = {
            "selected_domains": [],
            "dropped_domains": [],
            "estimated_chars": 0,
            "truncated": False,
            "decisions": [],
            "load_errors": [],
        }
        self.last_knowledge_load_status: Dict[str, Any] = {
            "status": "not_run",
            "requested_count": 0,
            "loaded_count": 0,
            "loaded_paths": [],
            "errors": [],
        }

        try:
            if self.knowledge_dir.is_dir():

                self.knowledge_router = KnowledgeRouter(
                    knowledge_dir=self.knowledge_dir,
                    threshold=1.0,
                    top_k=5,
                )

                print(
                    "📚 [ChatOrchestrator] "
                    f"登録Knowledge数="
                    f"{len(self.knowledge_router.domains)}"
                )

            else:
                print(
                    "⚠️ [ChatOrchestrator] "
                    "Knowledgeフォルダが見つかりません: "
                    f"{self.knowledge_dir}"
                )

        except Exception as e:
            print(
                "❌ [ChatOrchestrator] "
                f"KnowledgeRouter初期化失敗: {e}"
            )

            traceback.print_exc()

            self.knowledge_router = None

        self._run_knowledge_startup_audit()

        # ====================================================
        # Memory
        # ====================================================

        # 起動時のcwdがTo/でもTo/backendでも同じ保存先を使う。
        self.memory_dir = str(
            self.project_root
            / "backend"
            / ".ai_memory"
        )

        self.feedback_file = os.path.join(
            self.memory_dir,
            "feedback_scores.json",
        )

        self.signals_file = os.path.join(
            self.memory_dir,
            "user_signals.json",
        )

        os.makedirs(
            self.memory_dir,
            exist_ok=True,
        )

        # ====================================================
        # DeploymentHandler用Knowledge
        # ====================================================

        default_knowledge_dirs: list[str | Path] = [
            self.knowledge_dir / "domains"
        ]

        default_manager_base_dir = (
            self.knowledge_dir
        )

        # ====================================================
        # Plugin Knowledge
        # ====================================================

        self.plugin_knowledge_dir = str(
            self.knowledge_dir
        )

        self.occupations_dir = os.path.join(
            self.plugin_knowledge_dir,
            "Claude_occupations",
        )

        self.historical_figures_dir = os.path.join(
            self.plugin_knowledge_dir,
            "Claude_historical_figures",
        )

        occupation_titles: List[str] = []
        historical_figures_titles: List[str] = []

        # ====================================================
        # KnowledgeManager
        # ====================================================

        self.knowledge_manager = None

        try:
            self.knowledge_manager = KnowledgeManager(
                base_dir=(
                    self.project_root
                    / "backend"
                )
            )

            # --------------------------------------------
            # Occupations
            # --------------------------------------------

            try:
                occupation_items = (
                    self.knowledge_manager
                    .load_all_json_from_dir(
                        self.occupations_dir
                    )
                )

                occupation_titles = [
                    item["title"]
                    for item in occupation_items
                    if item.get("title")
                ]

            except Exception as e:
                print(
                    "⚠️ 職業タイトル一覧の"
                    f"読み込みに失敗: {e}"
                )

            # --------------------------------------------
            # Historical Figures
            # --------------------------------------------

            try:
                history_items = (
                    self.knowledge_manager
                    .load_all_json_from_dir(
                        self.historical_figures_dir
                    )
                )

                for item in history_items:

                    try:
                        data = item.data

                    except Exception as e:
                        print(
                            "⚠️ 歴史人物データ読み込み失敗 "
                            f"({item.rel_path}): {e}"
                        )

                        continue

                    if not isinstance(
                        data,
                        dict,
                    ):
                        continue

                    hf = data.get(
                        "history_figures",
                        {},
                    )

                    if not isinstance(
                        hf,
                        dict,
                    ):
                        continue

                    for group in (
                        "world_history",
                        "japan_history",
                    ):
                        people = hf.get(
                            group
                        )

                        if not isinstance(
                            people,
                            list,
                        ):
                            continue

                        for person in people:

                            if not isinstance(
                                person,
                                dict,
                            ):
                                continue

                            name = person.get(
                                "name"
                            )

                            if name:
                                historical_figures_titles.append(
                                    str(name)
                                )

            except Exception as e:
                print(
                    "⚠️ 歴史人物タイトル一覧の"
                    f"読み込みに失敗: {e}"
                )

        except Exception as e:
            print(
                "❌ [ChatOrchestrator] "
                f"KnowledgeManager初期化失敗: {e}"
            )

            traceback.print_exc()

            self.knowledge_manager = None

        # ====================================================
        # Handlers
        # ====================================================

        self.handlers = [
            MathHandler(),
            KnowledgeReloadHandler(
                reload_callback=self._reload_knowledge_system,
            ),
            KnowledgeHealthHandler(),
            DecompositionHandler(),
            GithubGuideHandler(),
            APICollectHandler(),
            RepomixHandler(),
        ]

        # ----------------------------------------------------
        # ProjectBuilderHandler
        #
        # importできた場合だけ追加。
        # ----------------------------------------------------

        if (
            PROJECT_BUILDER_AVAILABLE
            and
            ProjectBuilderHandler is not None
        ):
            try:
                self.handlers.append(
                    ProjectBuilderHandler(
                        project_root=str(
                            self.project_root
                        )
                    )
                )

                print(
                    "✅ [ChatOrchestrator] "
                    "ProjectBuilderHandler登録成功"
                )

            except Exception as e:
                print(
                    "❌ [ChatOrchestrator] "
                    "ProjectBuilderHandler初期化失敗: "
                    f"{e}"
                )

                traceback.print_exc()

        else:
            print(
                "⚠️ [ChatOrchestrator] "
                "ProjectBuilderHandlerは無効です。"
            )

            if PROJECT_BUILDER_IMPORT_ERROR:
                print(
                    "⚠️ [ChatOrchestrator] "
                    "import error="
                    f"{PROJECT_BUILDER_IMPORT_ERROR}"
                )

        # ----------------------------------------------------
        # その他Handler
        # ----------------------------------------------------

        self.handlers.extend(
            [
                PhpHandler(),
                ConversionJsonHandler(),

                DeploymentHandler(
                    knowledge_dirs=default_knowledge_dirs,
                    manager_base_dir=default_manager_base_dir,
                    cache_enabled=True,
                ),

                ChatHandler(),

                LineFormatHandler(),
                HTMLHandler(),
                GithubHandler(),
                RecruitHandler(),
                ScrapingHandler(),
                DesignHandler(),
                WeatherHandler(),
                DatabaseHandler(),
                OllamaHandler(),
                OfflineFallbackHandler(),
                ParserHandler(),
            ]
        )
    # ========================================================
    # Save Assistant State
    # ========================================================

    def _save_assistant_response_and_state(
        self,
        res_content: Any,
    ):
        try:
            assistant_text = ""

            if isinstance(
                res_content,
                dict,
            ):
                assistant_text = res_content.get(
                    "message",
                    "",
                )

                if "update_signals" in res_content:
                    self._save_signals(
                        res_content[
                            "update_signals"
                        ]
                    )

            else:
                assistant_text = str(
                    res_content
                )

            if assistant_text:
                self.context_manager.add_chat_history(
                    "assistant",
                    assistant_text,
                )

            self._update_signals_with_created_files(
                assistant_text
            )

            self.context_manager.save_state()

            print(
                "💾 AIの記憶とステートを"
                "正常に更新しました。"
            )

        except Exception as e:
            print(
                "⚠️ 記憶の保存中に"
                f"エラーが発生しました: {e}"
            )

    # ========================================================
    # Signals
    # ========================================================

    def _save_signals(
        self,
        signals_data: Dict[str, Any],
    ):
        try:
            with open(
                self.signals_file,
                "w",
                encoding="utf-8",
            ) as f_out:

                json.dump(
                    signals_data,
                    f_out,
                    ensure_ascii=False,
                    indent=4,
                )

            print(
                "📡 会話状態(Context)を更新しました。"
            )

        except Exception as e:
            print(
                f"⚠️ 信号の保存に失敗: {e}"
            )

    def _get_current_signals(
        self,
    ) -> Dict[str, Any]:

        try:
            if os.path.exists(
                self.signals_file
            ):
                with open(
                    self.signals_file,
                    "r",
                    encoding="utf-8",
                ) as f:

                    data = json.load(f)

                    if isinstance(
                        data,
                        dict,
                    ):
                        return data

        except Exception as e:
            print(
                f"⚠️ シグナル読み込み失敗: {e}"
            )

        return {}

    # ========================================================
    # Created Files
    # ========================================================

    def _update_signals_with_created_files(
        self,
        assistant_text: str,
    ):
        import re

        pattern = (
            r"(?:FILE|File|Path|path):\s*"
            r"([a-zA-Z0-9_\-\.\/]+)"
        )

        files = re.findall(
            pattern,
            assistant_text,
        )

        if not files:
            return

        current_signals = (
            self._get_current_signals()
        )

        recent_files = (
            current_signals.setdefault(
                "recent_files",
                [],
            )
        )

        for file_path in files:

            clean_file = (
                file_path.strip()
            )

            if clean_file not in recent_files:
                recent_files.append(
                    clean_file
                )

        current_signals["recent_files"] = (
            recent_files[-5:]
        )

        try:
            with open(
                self.signals_file,
                "w",
                encoding="utf-8",
            ) as f_out:

                json.dump(
                    current_signals,
                    f_out,
                    ensure_ascii=False,
                    indent=4,
                )

            print(
                "📡 Signals更新: "
                f"{current_signals['recent_files']}"
            )

        except Exception as e:
            print(
                f"⚠️ Signals保存失敗: {e}"
            )

    # ========================================================
    # Knowledge Normalizer
    # ========================================================

    def _normalize_loaded_knowledge(
        self,
        value: Any,
    ) -> list[dict[str, Any]]:

        if value is None:
            return []

        # ----------------------------------------------------
        # list
        # ----------------------------------------------------

        if isinstance(
            value,
            list,
        ):
            return [
                item
                for item in value
                if isinstance(
                    item,
                    dict,
                )
            ]

        # ----------------------------------------------------
        # dict
        # ----------------------------------------------------

        if isinstance(
            value,
            dict,
        ):
            values = list(
                value.values()
            )

            # KnowledgeManager:
            # {
            #   "something.json": {...}
            # }
            if (
                values
                and
                all(
                    isinstance(
                        item,
                        dict,
                    )
                    for item in values
                )
            ):
                return values

            return [value]

        return []

    # ========================================================
    # Knowledge Merge
    # ========================================================

    def _merge_knowledge_lists(
        self,
        existing: list[dict[str, Any]],
        additional: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        merged: list[
            dict[str, Any]
        ] = []

        seen: set[str] = set()

        for item in (
            existing
            +
            additional
        ):

            if not isinstance(
                item,
                dict,
            ):
                continue

            identity = (
                item.get("id")
                or
                item.get("name")
                or
                item.get("title")
            )

            if identity:
                identity_key = str(
                    identity
                ).strip()

            else:
                try:
                    identity_key = json.dumps(
                        item,
                        ensure_ascii=False,
                        sort_keys=True,
                    )

                except Exception:
                    identity_key = str(
                        id(item)
                    )

            if identity_key in seen:
                continue

            seen.add(
                identity_key
            )

            merged.append(
                item
            )

        return merged

    # ========================================================
    # Router Knowledge Loader
    # ========================================================

    def _load_router_knowledge(
        self,
        matched_paths: list[Any],
        user_message: str = "",
        signals: Dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        requested_paths = [
            str(path).strip()
            for path in matched_paths
            if str(path).strip()
        ]

        loaded: list[dict[str, Any]] = []

        if not requested_paths:
            self.last_knowledge_load_status = {
                "status": "empty",
                "requested_count": 0,
                "loaded_count": 0,
                "loaded_paths": [],
                "errors": [],
            }
            self.last_knowledge_selection = {
                "selected_domains": [],
                "dropped_domains": [],
                "estimated_chars": 0,
                "truncated": False,
                "decisions": [],
                "load_errors": [],
            }
            return loaded

        try:
            load_result = self.knowledge_loader.load(
                requested_paths
            )

        except Exception as exc:
            self.last_knowledge_load_status = {
                "status": "failed",
                "requested_count": len(requested_paths),
                "loaded_count": 0,
                "loaded_paths": [],
                "errors": [
                    {
                        "path": "*",
                        "reason": "loader_exception",
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }

            print(
                "❌ [ChatOrchestrator] "
                "KnowledgeLoader実行失敗: "
                f"{exc}"
            )
            traceback.print_exc()
            return loaded

        candidate_count = len(load_result.items)

        try:
            selection_result = self.knowledge_selector.select(
                user_message=user_message,
                load_result=load_result,
                signals=signals,
            )
            self.last_knowledge_selection = selection_result.to_dict()
            load_result = selection_result.as_load_result()

        except Exception as exc:
            # Selectorの障害だけで会話全体を停止させない。
            self.last_knowledge_selection = {
                "selected_domains": [
                    str(getattr(item, "domain_label", ""))
                    for item in load_result.items
                ],
                "dropped_domains": [],
                "estimated_chars": 0,
                "truncated": False,
                "decisions": [],
                "load_errors": [],
                "status": "fallback",
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(
                "⚠️ [ChatOrchestrator] "
                f"Knowledge選別失敗。未選別で継続します: {exc}"
            )

        loaded_paths: list[str] = []

        for item in load_result.items:
            item_path = str(
                getattr(item, "path", "")
            )
            domain_label = str(
                getattr(item, "domain_label", "")
                or item_path
                or "knowledge"
            )

            loaded.append(
                {
                    "id": domain_label,
                    "title": domain_label,
                    "source_path": item_path,
                    "content_type": str(
                        getattr(item, "content_type", "unknown")
                    ),
                    "description": str(
                        getattr(item, "description", "")
                    ),
                    "content": getattr(item, "content", None),
                }
            )
            loaded_paths.append(item_path)

        errors = [
            {
                "path": str(
                    getattr(error, "path", "")
                ),
                "reason": str(
                    getattr(error, "reason", "unknown")
                ),
                "detail": str(
                    getattr(error, "detail", "")
                ),
            }
            for error in load_result.errors
        ]

        if errors and loaded:
            status = "partial"
        elif errors:
            status = "failed"
        else:
            status = "ready"

        self.last_knowledge_load_status = {
            "status": status,
            "requested_count": len(requested_paths),
            "candidate_count": candidate_count,
            "loaded_count": len(loaded),
            "loaded_paths": loaded_paths,
            "selection": dict(self.last_knowledge_selection),
            "errors": errors,
        }

        print(
            "📚 [ChatOrchestrator] "
            f"KnowledgeLoader status={status} "
            f"requested={len(requested_paths)} "
            f"candidates={candidate_count} "
            f"loaded={len(loaded)} "
            f"errors={len(errors)}"
        )

        return loaded

    # ========================================================
    # Knowledge Startup Audit
    # ========================================================

    async def _reload_knowledge_system(self) -> Dict[str, Any]:
        """Router/Loaderを候補状態で再構築し、監査後に安全に切り替える。"""

        async with self.knowledge_reload_lock:
            domains_before = len(
                getattr(self.knowledge_router, "domains", []) or []
            )

            try:
                def rebuild():
                    candidate_router = KnowledgeRouter(
                        knowledge_dir=self.knowledge_dir,
                        threshold=1.0,
                        top_k=5,
                    )
                    candidate_loader = KnowledgeLoader(
                        knowledge_dirs=[self.knowledge_dir],
                        cache_enabled=True,
                    )
                    audit_report = self.knowledge_startup_auditor.run(
                        router=candidate_router,
                    )
                    return (
                        candidate_router,
                        candidate_loader,
                        audit_report,
                    )

                (
                    candidate_router,
                    candidate_loader,
                    audit_report,
                ) = await asyncio.to_thread(rebuild)

            except Exception as exc:
                failed_audit = {
                    "status": "failed",
                    "summary": "Knowledge再読込の準備中に例外が発生しました",
                    "should_warn_user": True,
                    "counts": {},
                    "valid_paths": [],
                    "issues": [
                        {
                            "code": "knowledge_reload_exception",
                            "severity": "critical",
                            "message": "Knowledgeを再構築できませんでした",
                            "path": None,
                            "detail": f"{type(exc).__name__}: {exc}",
                        }
                    ],
                }
                self.knowledge_startup_report = failed_audit
                if hasattr(self, "request"):
                    setattr(
                        self.request,
                        "knowledge_startup_audit",
                        dict(failed_audit),
                    )
                return {
                    "status": "failed",
                    "applied": False,
                    "summary": failed_audit["summary"],
                    "domains_before": domains_before,
                    "domains_after": domains_before,
                    "audit": failed_audit,
                }

            audit_data = audit_report.to_dict()
            self.knowledge_startup_report = audit_data
            domains_after = len(
                getattr(candidate_router, "domains", []) or []
            )
            applied = audit_report.status != "failed"

            if applied:
                # 監査を通過した候補だけを一度に本番状態へ切り替える。
                self.knowledge_router = candidate_router
                self.knowledge_loader = candidate_loader
                self.last_knowledge_load_status = {
                    "status": "not_run_after_reload",
                    "requested_count": 0,
                    "candidate_count": 0,
                    "loaded_count": 0,
                    "loaded_paths": [],
                    "errors": [],
                }
                self.last_knowledge_selection = {
                    "selected_domains": [],
                    "dropped_domains": [],
                    "estimated_chars": 0,
                    "truncated": False,
                    "decisions": [],
                    "load_errors": [],
                }
                self.last_knowledge_health = {
                    "status": "not_checked",
                    "summary": "再読込後の最初の質問で診断します",
                    "should_warn_user": False,
                    "can_use_knowledge": False,
                    "expected": False,
                    "counts": {},
                    "loaded_paths": [],
                    "selected_domains": [],
                    "dropped_domains": [],
                    "issues": [],
                }
                if hasattr(self.prompt_builder, "set_active_knowledge"):
                    self.prompt_builder.set_active_knowledge([])
                else:
                    self.prompt_builder.active_knowledge = []

            if hasattr(self, "request"):
                setattr(
                    self.request,
                    "knowledge_startup_audit",
                    dict(audit_data),
                )
                if applied:
                    setattr(self.request, "loaded_knowledge", [])
                    setattr(
                        self.request,
                        "knowledge_load_status",
                        dict(self.last_knowledge_load_status),
                    )
                    setattr(
                        self.request,
                        "knowledge_selection",
                        dict(self.last_knowledge_selection),
                    )
                    setattr(
                        self.request,
                        "knowledge_health",
                        dict(self.last_knowledge_health),
                    )

            result_status = (
                "success"
                if audit_report.status == "healthy"
                else audit_report.status
            )
            return {
                "status": result_status,
                "applied": applied,
                "summary": audit_report.summary,
                "domains_before": domains_before,
                "domains_after": (
                    domains_after if applied else domains_before
                ),
                "audit": audit_data,
            }

    def _run_knowledge_startup_audit(self) -> None:
        """登録Knowledgeを起動時に一度検証し、結果を保持する。"""

        if self.knowledge_router is None:
            self.knowledge_startup_report = {
                "status": "failed",
                "summary": (
                    "KnowledgeRouterが利用できないため起動時監査を実行できません"
                ),
                "should_warn_user": True,
                "counts": {},
                "valid_paths": [],
                "issues": [
                    {
                        "code": "router_unavailable",
                        "severity": "critical",
                        "message": "KnowledgeRouterが利用できません",
                        "path": None,
                        "detail": "起動時監査を開始できませんでした",
                    }
                ],
            }
            print(
                "❌ [ChatOrchestrator] "
                "Knowledge Startup Audit: router unavailable"
            )
            return

        try:
            report = self.knowledge_startup_auditor.run(
                router=self.knowledge_router
            )
            self.knowledge_startup_report = report.to_dict()

        except Exception as exc:
            self.knowledge_startup_report = {
                "status": "failed",
                "summary": "Knowledge起動時監査で例外が発生しました",
                "should_warn_user": True,
                "counts": {},
                "valid_paths": [],
                "issues": [
                    {
                        "code": "startup_audit_exception",
                        "severity": "critical",
                        "message": "Knowledge起動時監査で例外が発生しました",
                        "path": None,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }
            print(
                "❌ [ChatOrchestrator] "
                f"Knowledge Startup Audit失敗: {exc}"
            )
            traceback.print_exc()

        print(
            "🔎 [ChatOrchestrator] "
            "KnowledgeStartupAudit status="
            f"{self.knowledge_startup_report.get('status')} "
            "summary="
            f"{self.knowledge_startup_report.get('summary')}"
        )

    # ========================================================
    # Knowledge Health
    # ========================================================

    def _analyze_knowledge_health(
        self,
        knowledge: list[dict[str, Any]],
    ) -> str:
        """Loaderの申告とPrompt直前の実データを照合する。"""

        signals = getattr(
            self.request,
            "current_signals",
            {},
        )
        if not isinstance(signals, dict):
            signals = {}

        try:
            report = self.knowledge_health_monitor.evaluate(
                load_status=self.last_knowledge_load_status,
                selection=self.last_knowledge_selection,
                loaded_knowledge=knowledge,
                startup_audit=self.knowledge_startup_report,
            )
            health_data = report.to_dict()
            health_context = report.to_prompt_context()

        except Exception as exc:
            # Health監視自体の失敗もサイレントにしない。
            health_data = {
                "status": "failed",
                "summary": "Knowledge Health監視処理が失敗しました",
                "should_warn_user": True,
                "can_use_knowledge": False,
                "expected": True,
                "counts": {},
                "loaded_paths": [],
                "selected_domains": [],
                "dropped_domains": [],
                "issues": [
                    {
                        "code": "health_monitor_exception",
                        "severity": "critical",
                        "message": "Knowledge Health監視処理が失敗しました",
                        "stage": "health",
                        "path": None,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                ],
            }
            health_context = (
                "# Knowledge Health\n"
                "- 状態: failed\n"
                "- 監視処理自体が失敗しました。"
                "Knowledgeを正常に読めたと主張しないこと。"
            )
            print(
                "❌ [ChatOrchestrator] "
                f"Knowledge Health監視失敗: {exc}"
            )
            traceback.print_exc()

        self.last_knowledge_health = health_data
        setattr(
            self.request,
            "knowledge_health",
            dict(health_data),
        )
        setattr(
            self.request,
            "knowledge_health_context",
            health_context,
        )
        setattr(
            self.request,
            "knowledge_startup_audit",
            dict(self.knowledge_startup_report),
        )
        signals["knowledge_health"] = dict(health_data)
        signals["knowledge_health_context"] = health_context
        setattr(
            self.request,
            "current_signals",
            signals,
        )
        self.current_signals = signals

        print(
            "🩺 [ChatOrchestrator] "
            "KnowledgeHealth status="
            f"{health_data.get('status')} "
            "warn="
            f"{health_data.get('should_warn_user')}"
        )
        return health_context

    # ========================================================
    # Project Progress
    # ========================================================

    def _analyze_project_progress(
        self,
        knowledge: list[dict[str, Any]],
    ) -> str:
        """選択済みKnowledgeから進捗を計算し、HandlerとPromptへ共有する。"""

        signals = getattr(
            self.request,
            "current_signals",
            {},
        )
        if not isinstance(signals, dict):
            signals = {}

        try:
            report = self.project_progress_analyzer.analyze(
                user_message=self.message,
                knowledge=knowledge,
                signals=signals,
            )
            progress_data = report.to_dict()
            progress_context = report.to_prompt_context()

        except Exception as exc:
            progress_data = {
                "goal": None,
                "overall_status": "analysis_failed",
                "progress_percent": None,
                "confidence": "low",
                "current_phase": None,
                "counts": {},
                "tasks": [],
                "barriers": [],
                "next_actions": [],
                "evidence_sources": [],
                "warnings": [
                    f"{type(exc).__name__}: {exc}"
                ],
                "calculation": {},
            }
            progress_context = (
                "# プロジェクト進捗\n"
                "進捗解析に失敗したため、進捗率を推測しないこと。"
            )
            print(
                "⚠️ [ChatOrchestrator] "
                f"ProjectProgress解析失敗: {exc}"
            )
            traceback.print_exc()

        self.last_project_progress = progress_data
        setattr(
            self.request,
            "project_progress",
            dict(progress_data),
        )
        setattr(
            self.request,
            "project_progress_context",
            progress_context,
        )

        # ChatHandlerやPromptBuilderがcurrent_signals経由でも参照できる。
        signals["project_progress"] = dict(progress_data)
        signals["project_progress_context"] = progress_context
        setattr(
            self.request,
            "current_signals",
            signals,
        )
        self.current_signals = signals

        print(
            "📊 [ChatOrchestrator] "
            "ProjectProgress status="
            f"{progress_data.get('overall_status')} "
            "progress="
            f"{progress_data.get('progress_percent')}"
        )
        return progress_context

    # ========================================================
    # Handler Invocation
    # ========================================================

    async def _invoke_handler(
        self,
        handler,
    ):
        handler_name = (
            handler.__class__.__name__
        )

        # ----------------------------------------------------
        # Routerからすでに入っているKnowledgeを維持
        # ----------------------------------------------------

        existing_knowledge = (
            self._normalize_loaded_knowledge(
                getattr(
                    self.request,
                    "loaded_knowledge",
                    [],
                )
            )
        )

        additional_knowledge: list[
            dict[str, Any]
        ] = []

        # ----------------------------------------------------
        # Handler固有Knowledge検索
        # ----------------------------------------------------

        if (
            hasattr(
                handler,
                "get_search_keywords",
            )
            and
            self.knowledge_manager is not None
        ):
            try:
                keywords = (
                    handler.get_search_keywords(
                        self.message
                    )
                )

            except Exception:
                keywords = []

                print(
                    f"❌ {handler_name}."
                    "get_search_keywordsで例外"
                )

                traceback.print_exc()

            if keywords:

                search_dirs = [
                    self.plugin_knowledge_dir,
                    self.occupations_dir,
                    self.historical_figures_dir,
                ]

                for search_dir in search_dirs:

                    try:
                        result = (
                            self.knowledge_manager
                            .search_by_keywords(
                                search_dir,
                                keywords,
                            )
                        )

                        normalized = (
                            self._normalize_loaded_knowledge(
                                result
                            )
                        )

                        additional_knowledge.extend(
                            normalized
                        )

                    except Exception as e:
                        print(
                            "⚠️ Knowledge追加検索エラー "
                            f"({search_dir}): {e}"
                        )

                        traceback.print_exc()

        combined_knowledge = (
            self._merge_knowledge_lists(
                existing_knowledge,
                additional_knowledge,
            )
        )

        health_context = self._analyze_knowledge_health(
            combined_knowledge
        )

        progress_context = self._analyze_project_progress(
            combined_knowledge
        )

        # 既存PromptBuilderが改修前でも進捗説明を利用できるよう、
        # 巨大な全タスクではなく短い集計結果だけをKnowledgeへ追加する。
        combined_knowledge = self._merge_knowledge_lists(
            combined_knowledge,
            [
                {
                    "id": "system/knowledge_health",
                    "title": "Knowledge読込監視結果",
                    "source_path": "system/knowledge_health",
                    "content_type": "generated_context",
                    "description": (
                        "Knowledgeの読込失敗・件数不一致・空データの監視結果"
                    ),
                    "content": health_context,
                },
                {
                    "id": "system/project_progress",
                    "title": "プロジェクト進捗",
                    "source_path": "system/project_progress",
                    "content_type": "generated_context",
                    "description": (
                        "選択済みJSONから決定的に計算した現在地・壁・次の行動"
                    ),
                    "content": progress_context,
                }
            ],
        )

        setattr(
            self.request,
            "loaded_knowledge",
            combined_knowledge,
        )

        if hasattr(
            self.prompt_builder,
            "set_active_knowledge",
        ):
            self.prompt_builder.set_active_knowledge(
                combined_knowledge
            )
        else:
            self.prompt_builder.active_knowledge = (
                combined_knowledge
            )

        knowledge_ids = []

        for item in combined_knowledge:

            knowledge_id = (
                item.get("id")
                or
                item.get("name")
                or
                item.get("title")
            )

            if knowledge_id:
                knowledge_ids.append(
                    knowledge_id
                )

        print(
            "🧠 [ChatOrchestrator] "
            f"{handler_name}へ渡すKnowledge件数="
            f"{len(combined_knowledge)}"
        )

        print(
            "🧠 [ChatOrchestrator] "
            f"knowledge_ids={knowledge_ids}"
        )

        return await handler.handle(
            self.request
        )

    # ========================================================
    # Main
    # ========================================================

    async def route_and_execute(
        self,
        request,
        **kwargs,
    ):
        self.request = request

        self.message = getattr(
            request,
            "message",
            "",
        )

        if not isinstance(
            self.message,
            str,
        ):
            self.message = str(
                self.message
            )

        # ----------------------------------------------------
        # History
        # ----------------------------------------------------

        self.context_manager.add_chat_history(
            "user",
            self.message,
        )

        available_keys: list[str] = []

        if (
            self.knowledge_router is not None
            and hasattr(
                self.knowledge_router,
                "domains",
            )
        ):
            available_keys = [
                domain.name
                for domain
                in self.knowledge_router.domains
            ]

        # 前回リクエストのKnowledgeを残さない。
        loaded_knowledges: list[
            dict[str, Any]
        ] = []

        setattr(
            self.request,
            "loaded_knowledge",
            loaded_knowledges,
        )

        self.last_knowledge_load_status = {
            "status": "not_run",
            "requested_count": 0,
            "loaded_count": 0,
            "loaded_paths": [],
            "errors": [],
        }

        self.last_knowledge_selection = {
            "selected_domains": [],
            "dropped_domains": [],
            "estimated_chars": 0,
            "truncated": False,
            "decisions": [],
            "load_errors": [],
        }

        self.last_knowledge_health = {
            "status": "not_checked",
            "summary": "Knowledgeの読込処理はまだ実行されていません",
            "should_warn_user": False,
            "can_use_knowledge": False,
            "expected": False,
            "counts": {},
            "loaded_paths": [],
            "selected_domains": [],
            "dropped_domains": [],
            "issues": [],
        }

        self.last_project_progress = {
            "goal": None,
            "overall_status": "not_analyzed",
            "progress_percent": None,
            "confidence": "low",
            "current_phase": None,
            "counts": {},
            "tasks": [],
            "barriers": [],
            "next_actions": [],
            "evidence_sources": [],
            "warnings": [],
            "calculation": {},
        }

        setattr(
            self.request,
            "knowledge_load_status",
            dict(self.last_knowledge_load_status),
        )

        setattr(
            self.request,
            "knowledge_selection",
            dict(self.last_knowledge_selection),
        )

        setattr(
            self.request,
            "knowledge_health",
            dict(self.last_knowledge_health),
        )

        setattr(
            self.request,
            "knowledge_startup_audit",
            dict(self.knowledge_startup_report),
        )

        setattr(
            self.request,
            "project_progress",
            dict(self.last_project_progress),
        )

        if hasattr(
            self.prompt_builder,
            "set_active_knowledge",
        ):
            self.prompt_builder.set_active_knowledge(
                loaded_knowledges
            )
        else:
            self.prompt_builder.active_knowledge = (
                loaded_knowledges
            )

        # ====================================================
        # 1. IntentInspector
        #
        # 現在の入力を最初に一度だけ解析し、その結果を
        # KnowledgeRouterと全Handlerで共有する。
        # ====================================================

        try:
            inspector = IntentInspector(
                self.message,
                available_knowledge_keys=
                    available_keys,
            )

        except TypeError:

            inspector = IntentInspector(
                self.message
            )

            print(
                "⚠️ 古いIntentInspectorを検出。"
                "フォールバック初期化しました。"
            )

        inspect_result = (
            inspector.inspect()
        )

        self.context_manager.apply_inspector_result(
            inspect_result
        )

        # ====================================================
        # 2. Signals
        # ====================================================

        current_signals = (
            self._get_current_signals()
        )

        current_signals[
            "intent_analysis"
        ] = inspect_result

        # ChatHandler.calculate_scoreとhandleの両方から読めるようにする
        self.request.current_signals = (
            current_signals
        )

        self.request.intent_analysis = (
            inspect_result
        )

        setattr(
            self.request,
            "current_signals",
            current_signals,
        )

        self.current_signals = (
            current_signals
        )

        self.active_context = (
            current_signals.get(
                "active_context"
            )
        )
        if current_signals:
            # intent_analysisにはavailable_knowledgeが数百件入る場合がある。
            # Signals全体を出力せず、運用確認に必要な項目だけを記録する。
            intent_summary = (
                inspect_result
                if isinstance(inspect_result, dict)
                else {}
            )
            print(
                "📡 [ChatOrchestrator] "
                f"mode={intent_summary.get('mode', 'unknown')} "
                f"intent={intent_summary.get('intent', 'unknown')} "
                f"handler={intent_summary.get('handler')} "
                f"knowledge_count={len(available_keys)} "
                f"active_context={self.active_context!r}"
            )

        # ====================================================
        # 3. KnowledgeRouter
        #
        # IntentInspectorの今回の解析結果を含むSignalsで
        # 関連Knowledgeを選択・ロードする。
        # ====================================================

        if self.knowledge_router:

            try:
                route_result = (
                    self.knowledge_router.route(
                        self.message,
                        current_signals,
                    )
                )

                matched_paths: list[Any] = []

                # --------------------------------------------
                # RouteResult互換
                # --------------------------------------------

                if route_result is not None:

                    if hasattr(
                        route_result,
                        "file_paths",
                    ):
                        matched_paths = list(
                            route_result.file_paths
                        )

                    elif hasattr(
                        route_result,
                        "matched_files",
                    ):
                        matched_paths = list(
                            route_result.matched_files
                        )

                    elif isinstance(
                        route_result,
                        list,
                    ):
                        matched_paths = (
                            route_result
                        )

                    elif (
                        hasattr(
                            route_result,
                            "__iter__",
                        )
                        and
                        not isinstance(
                            route_result,
                            str,
                        )
                    ):
                        matched_paths = list(
                            route_result
                        )

                print(
                    "🧠 [ChatOrchestrator] "
                    f"matched_paths={matched_paths}"
                )

                if hasattr(
                    route_result,
                    "matched_domains",
                ):
                    print(
                        "🧠 [ChatOrchestrator] "
                        "matched_domains="
                        f"{route_result.matched_domains}"
                    )

                if hasattr(
                    route_result,
                    "scores",
                ):
                    route_scores = getattr(
                        route_result,
                        "scores",
                    )
                    print(
                        "🧠 [ChatOrchestrator] "
                        "knowledge_scores="
                        f"{route_scores}"
                    )

                    if isinstance(route_scores, dict):
                        current_signals[
                            "knowledge_scores"
                        ] = route_scores

                loaded_knowledges = (
                    self._load_router_knowledge(
                        matched_paths,
                        user_message=self.message,
                        signals=current_signals,
                    )
                )

                setattr(
                    self.request,
                    "knowledge_load_status",
                    dict(self.last_knowledge_load_status),
                )

                setattr(
                    self.request,
                    "knowledge_selection",
                    dict(self.last_knowledge_selection),
                )

                loaded_knowledge_ids = []

                for item in loaded_knowledges:

                    knowledge_id = (
                        item.get("id")
                        or
                        item.get("name")
                        or
                        item.get("title")
                    )

                    if knowledge_id:
                        loaded_knowledge_ids.append(
                            knowledge_id
                        )

                print(
                    "🧠 [ChatOrchestrator] "
                    "loaded_knowledge_count="
                    f"{len(loaded_knowledges)}"
                )

                print(
                    "🧠 [ChatOrchestrator] "
                    "loaded_knowledge_ids="
                    f"{loaded_knowledge_ids}"
                )

                setattr(
                    self.request,
                    "loaded_knowledge",
                    loaded_knowledges,
                )

                if hasattr(
                    self.prompt_builder,
                    "set_active_knowledge",
                ):
                    self.prompt_builder.set_active_knowledge(
                        loaded_knowledges
                    )
                else:
                    self.prompt_builder.active_knowledge = (
                        loaded_knowledges
                    )

            except Exception as e:

                print(
                    "❌ [ChatOrchestrator] "
                    "Knowledgeルーティング中に"
                    f"エラー: {e}"
                )

                traceback.print_exc()

                setattr(
                    self.request,
                    "loaded_knowledge",
                    [],
                )

                self.last_knowledge_load_status = {
                    "status": "failed",
                    "requested_count": 0,
                    "loaded_count": 0,
                    "loaded_paths": [],
                    "errors": [
                        {
                            "path": "*",
                            "reason": "routing_exception",
                            "detail": f"{type(e).__name__}: {e}",
                        }
                    ],
                }

                self.last_knowledge_selection = {
                    "selected_domains": [],
                    "dropped_domains": [],
                    "estimated_chars": 0,
                    "truncated": False,
                    "decisions": [],
                    "load_errors": [],
                    "status": "routing_failed",
                }

                setattr(
                    self.request,
                    "knowledge_load_status",
                    dict(self.last_knowledge_load_status),
                )

                setattr(
                    self.request,
                    "knowledge_selection",
                    dict(self.last_knowledge_selection),
                )

                if hasattr(
                    self.prompt_builder,
                    "set_active_knowledge",
                ):
                    self.prompt_builder.set_active_knowledge(
                        []
                    )
                else:
                    self.prompt_builder.active_knowledge = []

        else:
            self.last_knowledge_load_status = {
                "status": "router_unavailable",
                "requested_count": 0,
                "loaded_count": 0,
                "loaded_paths": [],
                "errors": [
                    {
                        "path": "*",
                        "reason": "router_unavailable",
                        "detail": "KnowledgeRouterが初期化されていません",
                    }
                ],
            }

            self.last_knowledge_selection = {
                "selected_domains": [],
                "dropped_domains": [],
                "estimated_chars": 0,
                "truncated": False,
                "decisions": [],
                "load_errors": [],
                "status": "router_unavailable",
            }

            setattr(
                self.request,
                "knowledge_load_status",
                dict(self.last_knowledge_load_status),
            )

            setattr(
                self.request,
                "knowledge_selection",
                dict(self.last_knowledge_selection),
            )

        # ====================================================
        # 4. Image fast path
        # ====================================================

        image_data = getattr(
            self.request,
            "image_base64",
            None,
        )

        if image_data:

            print(
                "📸 画像データ受信！ "
                "OcrRecruitHandlerへ直接ルーティング"
            )

            ocr_handler = (
                OcrRecruitHandler()
            )

            self.last_used_handler = (
                "OcrRecruitHandler"
            )

            self.active_context = None

            result = await ocr_handler.handle(
                self.message,
                image_data,
            )

            if result:
                _, res_content = result

                self._save_assistant_response_and_state(
                    res_content
                )

            return result

        # ====================================================
        # 5. Handler Scoring
        # ====================================================

        scored_handlers = []

        for handler in self.handlers:

            handler_name = (
                handler.__class__.__name__
            )

            try:
                if hasattr(
                    handler,
                    "calculate_score",
                ):
                    sig = inspect.signature(
                        handler.calculate_score
                    )

                    if len(
                        sig.parameters
                    ) >= 2:

                        base_score = await (
                            handler.calculate_score(
                                self.message,
                                current_signals,
                            )
                        )

                    else:

                        base_score = await (
                            handler.calculate_score(
                                self.message
                            )
                        )

                elif hasattr(
                    handler,
                    "can_handle",
                ):

                    can_handle = await (
                        handler.can_handle(
                            self.message
                        )
                    )

                    base_score = (
                        100
                        if can_handle
                        else 0
                    )

                else:
                    base_score = 0

            except Exception:

                print(
                    f"❌ {handler_name} "
                    "のscore計算で例外"
                )

                traceback.print_exc()

                base_score = 0

            # --------------------------------------------
            # Feedback
            # --------------------------------------------

            bonus = (
                self._get_feedback_bonus(
                    self.message,
                    handler_name,
                )
            )

            final_score = (
                base_score
                +
                bonus
            )

            # --------------------------------------------
            # Size
            # --------------------------------------------

            try:
                estimated_size = getattr(
                    handler,
                    "estimate_size",
                    lambda msg: 1000,
                )(
                    self.message
                )

            except Exception:
                estimated_size = 1000

            print(
                f"🔎 {handler_name}"
                f" -> ベース:{base_score}"
                f" 補正:{bonus}"
                f" 最終:{final_score}"
            )

            scored_handlers.append(
                {
                    "handler": handler,
                    "score": final_score,
                    "size": estimated_size,
                }
            )

        # ====================================================
        # 6. Sort
        # ====================================================

        scored_handlers.sort(
            key=lambda item:
                item["score"],
            reverse=True,
        )

        if not scored_handlers:

            return (
                "text",
                {
                    "message":
                        "利用可能なHandlerがありません。",
                    "blocks": [],
                },
            )

        top = scored_handlers[0]

        second = (
            scored_handlers[1]

            if len(
                scored_handlers
            ) >= 2

            else {
                "handler": None,
                "score": 0,
                "size": 0,
            }
        )

        # ====================================================
        # Debug Block
        # ====================================================

        debug_block = {
            "type": "RoutingDebugBlock",

            "props": {
                "selected":
                    top["handler"]
                    .__class__
                    .__name__,

                "handlers": [
                    {
                        "name":
                            item["handler"]
                            .__class__
                            .__name__,

                        "score":
                            item["score"],
                    }

                    for item
                    in scored_handlers

                    if item["score"] > 0
                ],
            },
        }

        def attach_debug_block(
            content: Any,
        ) -> dict:

            if not isinstance(
                content,
                dict,
            ):
                return {
                    "message":
                        str(content),
                    "blocks": [],
                }

            if "blocks" not in content:
                content["blocks"] = []

            return content

        # ====================================================
        # 7. 100点
        # ====================================================

        if top["score"] == 100:

            handler_name = (
                top["handler"]
                .__class__
                .__name__
            )

            print(
                f"🎯 {handler_name} "
                "が100点を獲得"
            )

            self.last_used_handler = (
                handler_name
            )

            result = await self._invoke_handler(
                top["handler"]
            )

            if result is None:

                return (
                    "text",
                    {
                        "message":
                            "処理に失敗しました。",
                        "blocks": [
                            debug_block
                        ],
                    },
                )

            res_type, res_content = (
                result
            )

            print(
                "📦 [ChatOrchestrator] "
                f"res_type={res_type}"
            )

            self._save_assistant_response_and_state(
                res_content
            )

            return (
                res_type,
                attach_debug_block(
                    res_content
                ),
            )

        # ====================================================
        # 8. 低スコア
        # ====================================================

        if top["score"] < 40:

            return (
                "text",
                {
                    "message":
                        "どのエージェントも"
                        "処理できませんでした。",

                    "blocks": [
                        debug_block
                    ],
                },
            )

        # ====================================================
        # 9. 競合
        # ====================================================

        if (
            second["handler"]
            is not None
            and
            (
                top["score"]
                -
                second["score"]
            )
            <= 10
        ):
            top_name = (
                top["handler"]
                .__class__
                .__name__
            )

            second_name = (
                second["handler"]
                .__class__
                .__name__
            )

            print(
                "🤔 競合:"
                f"{top_name}"
                " vs "
                f"{second_name}"
            )

            total_size = (
                top["size"]
                +
                second["size"]
            )

            if total_size >= 20000:

                return (
                    "text",
                    {
                        "message":
                            f"{top_name} と "
                            f"{second_name} が"
                            "競合しています。\n"
                            "どちらを優先しますか？",

                        "blocks": [
                            debug_block
                        ],
                    },
                )

            print(
                "🚀 2つのHandlerを実行して"
                "マージします。"
            )

            result1 = await (
                self._invoke_handler(
                    top["handler"]
                )
            )

            result2 = await (
                self._invoke_handler(
                    second["handler"]
                )
            )

            if (
                result1 is None
                and
                result2 is None
            ):
                return (
                    "text",
                    {
                        "message":
                            "両方のHandlerで"
                            "エラーが発生しました。",

                        "blocks": [
                            debug_block
                        ],
                    },
                )

            if result1 is None:

                res_type, res_content = (
                    result2
                )

                self.last_used_handler = (
                    second_name
                )

                self._save_assistant_response_and_state(
                    res_content
                )

                return (
                    res_type,
                    attach_debug_block(
                        res_content
                    ),
                )

            if result2 is None:

                res_type, res_content = (
                    result1
                )

                self.last_used_handler = (
                    top_name
                )

                self._save_assistant_response_and_state(
                    res_content
                )

                return (
                    res_type,
                    attach_debug_block(
                        res_content
                    ),
                )

            _, res_content1 = result1
            _, res_content2 = result2

            merged = (
                self._merge_responses(
                    res_content1,
                    res_content2,
                )
            )

            self.last_used_handler = (
                top_name
            )

            final_type = (
                "ui_code"

                if merged.get(
                    "blocks"
                )

                else "text"
            )

            self._save_assistant_response_and_state(
                merged
            )

            return (
                final_type,
                attach_debug_block(
                    merged
                ),
            )

        # ====================================================
        # 10. 通常実行
        # ====================================================

        result = await self._invoke_handler(
            top["handler"]
        )

        if result is None:

            return (
                "text",
                {
                    "message":
                        "処理中に"
                        "エラーが発生しました。",

                    "blocks": [
                        debug_block
                    ],
                },
            )

        self.last_used_handler = (
            top["handler"]
            .__class__
            .__name__
        )

        res_type, res_content = (
            result
        )

        print(
            "📦 [ChatOrchestrator] "
            f"res_type={res_type}"
        )

        self._save_assistant_response_and_state(
            res_content
        )

        return (
            res_type,
            attach_debug_block(
                res_content
            ),
        )

    # ========================================================
    # Feedback Bonus
    # ========================================================

    def _get_feedback_bonus(
        self,
        message,
        handler_name,
    ) -> int:

        try:
            if not os.path.exists(
                self.feedback_file
            ):
                return 0

            with open(
                self.feedback_file,
                "r",
                encoding="utf-8",
            ) as f:

                data = json.load(f)

            bonus = data.get(
                handler_name,
                0,
            )

            try:
                return int(
                    bonus
                )

            except Exception:
                return 0

        except Exception:
            return 0

    # ========================================================
    # Merge
    # ========================================================

    def _merge_responses(
        self,
        c1: Any,
        c2: Any,
    ) -> dict:

        if not isinstance(
            c1,
            dict,
        ):
            c1 = {
                "message":
                    str(c1),

                "blocks": [],
            }

        if not isinstance(
            c2,
            dict,
        ):
            c2 = {
                "message":
                    str(c2),

                "blocks": [],
            }

        return {
            "message":
                c1.get(
                    "message",
                    "",
                )
                +
                "\n\n---\n\n"
                +
                c2.get(
                    "message",
                    "",
                ),

            "blocks":
                c1.get(
                    "blocks",
                    [],
                )
                +
                c2.get(
                    "blocks",
                    [],
                ),
        }
