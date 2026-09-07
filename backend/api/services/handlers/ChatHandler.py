# api/services/handlers/ChatHandler.py

from __future__ import annotations

import inspect
import json
import logging

from pathlib import Path

from typing import (
    Any,
    Awaitable,
    Dict,
    List,
    Optional,
    Tuple,
    cast,
)


# ============================================================
# Base
# ============================================================

from api.services.handlers.base_handler import BaseHandler
# ============================================================
# Conversation
# ============================================================

from api.services.conversation.ConversationState import ConversationState
from api.services.conversation.TopicTracker import TopicTracker
from api.services.conversation.ContextResolver import ContextResolver
from api.services.conversation.ConversationSummary import ConversationSummary
from api.services.conversation.ResponseComposer import ResponseComposer
# ============================================================
# Knowledge
# ============================================================

from engine.KnowledgeRouter import KnowledgeRouter
from engine.KnowledgeLoader import KnowledgeLoader
# ============================================================
# Phase 3
# Requirement
# ============================================================

from api.services.project_generation.RequirementAnalyzer import (
    RequirementAnalyzer,
)


# ============================================================
# Optional Local LLM
# ============================================================

try:
    from api.services.llm.LocalLLMEngine import LocalLLMEngine
except ImportError:
    LocalLLMEngine = None


# ============================================================
# Optional PromptBuilder
#
# 新しい PromptBuilder.py が存在する場合に利用する。
# 無くてもChatHandler自体は動作する。
# ============================================================

try:
    from llm.ChatPromptBuilder import PromptBuilder
except ImportError:
    PromptBuilder = None



try:
    from api.services.project_generation.ProjectBuildService import (
        ProjectBuildService,
    )
except ImportError:
    ProjectBuildService = None


logger = logging.getLogger(
    __name__
)


# ============================================================
# ChatHandler
# ============================================================


class ChatHandler(BaseHandler):
    """
    雑談・Knowledge応答・Conversation管理・
    アプリ開発要件収集を担当するHandler。


    ============================================================
    Phase 1
    ============================================================

    IntentInspector
        ↓
    KnowledgeRouter
        ↓
    KnowledgeLoader
        ↓
    ConversationState
        ↓
    JSON / Rule Response


    ============================================================
    Phase 2
    ============================================================

    ContextResolver
        ↓
    IntentInspector
        ↓
    KnowledgeRouter
        ↓
    TopicTracker
        ↓
    ConversationSummary
        ↓
    ResponseComposer


    ============================================================
    Phase 3
    ============================================================

    User
        ↓
    ChatHandler
        ↓
    RequirementAnalyzer
        ↓
    ConversationState.project_context
        ↓
    会話を継続
        ↓
    「じゃあ作って」
        ↓
    ProjectBuildService
        ↓
    ProjectPlanner
        ↓
    FileGenerator
        ↓
    FileWriter
        ↓
    BuildValidator
        ↓
    RepairEngine
        ↓
    ZipPackager
        ↓
    ProjectBuildBlock


    ============================================================
    重要
    ============================================================

    「アプリを作りたい」

    だけではビルド開始しない。

    この段階では要件相談として扱う。


    「じゃあ作って」
    「実際に生成して」
    「ビルドして」

    のような明示的な命令で初めて
    ProjectBuildServiceへ移行する。
    """

    HANDLER_NAME = (
        "ChatHandler"
    )

    CHATBOT_MODE = (
        "chatbot"
    )

    AI_MODE = (
        "ai"
    )

    DEFAULT_SCORE = 60

    # ========================================================
    # Casual
    # ========================================================

    CASUAL_WORDS = (
        "こんにちは",
        "こんばんは",
        "おはよう",
        "ありがとう",
        "ありがと",
        "なるほど",
        "そうだね",
        "だよね",
        "確かに",
        "面白い",
        "すごい",
        "どう思う",
        "どうかな",
        "相談",
        "話したい",
    )

    # ========================================================
    # AI mode
    # ========================================================

    AI_ENABLE_WORDS = (
        "aiモード",
        "aiモードにして",
        "aiを有効",
        "aiをオン",
        "生成aiを使う",
        "local llmを使う",
    )

    CHATBOT_ENABLE_WORDS = (
        "チャットボットモード",
        "chatbotモード",
        "jsonモード",
        "ルールベースモード",
        "aiを無効",
        "aiをオフ",
        "生成aiを使わない",
    )

    # ========================================================
    # Project conversation
    #
    # 「アプリ相談中か」を判断するための語。
    # Build開始判定とは別。
    # ========================================================

    PROJECT_WORDS = (
        "アプリ",
        "webアプリ",
        "ウェブアプリ",
        "プロジェクト",
        "react",
        "next.js",
        "nextjs",
        "html",
        "画面",
        "機能",
        "ページ",
        "データベース",
        "バックエンド",
        "フロントエンド",
    )

    # ========================================================
    # Build Intent
    #
    # 「作りたい」は入れない。
    #
    # 作りたい
    # =
    # Requirements conversation
    #
    # 作って
    # =
    # Build command
    # ========================================================

    PROJECT_BUILD_INTENTS = {
        "build_app",
        "build_project",
        "create_project",
        "generate_app",
        "generate_project",
        "start_build",
        "project_build",
        "implement_project",
    }

    PROJECT_BUILD_PHRASES = (
        "じゃあ作って",
        "では作って",
        "それで作って",
        "これで作って",
        "この内容で作って",
        "この要件で作って",
        "この仕様で作って",
        "実際に作って",
        "実装して",
        "実装を始めて",
        "実装を開始して",
        "生成して",
        "アプリを生成して",
        "プロジェクトを生成して",
        "プロジェクトを作って",
        "アプリを作って",
        "ビルドして",
        "buildして",
        "buildしてほしい",
        "コードを生成して",
    )

    # ========================================================
    # Init
    # ========================================================

    def __init__(
        self,
        knowledge_dir: str = "knowledge",
        default_mode: str = AI_MODE,
        knowledge_threshold: int = 1,
        knowledge_top_k: Optional[int] = 5,
        enable_debug: bool = True,
    ) -> None:

        super().__init__()

        self.enable_debug = (
            enable_debug
        )

        # ----------------------------------------------------
        # Mode
        # ----------------------------------------------------

        if default_mode not in (
            self.CHATBOT_MODE,
            self.AI_MODE,
        ):
            default_mode = self.AI_MODE
            default_mode = (
                self.AI_MODE
            )

        self.default_mode = (
            default_mode
        )

        # ----------------------------------------------------
        # Knowledge
        # ----------------------------------------------------

        self.knowledge_dir = Path(
            knowledge_dir
        )

        self.knowledge_router = (
            KnowledgeRouter(
                knowledge_dir=str(
                    self.knowledge_dir
                ),
                threshold=
                    knowledge_threshold,
                top_k=
                    knowledge_top_k,
            )
        )

        self.knowledge_loader = (
            KnowledgeLoader(
                knowledge_dirs=[
                    self.knowledge_dir
                ],
                cache_enabled=True,
            )
        )

        # ----------------------------------------------------
        # Conversation
        # ----------------------------------------------------

        self.topic_tracker = (
            TopicTracker()
        )

        self.context_resolver = (
            ContextResolver()
        )

        self.conversation_summary = (
            ConversationSummary()
        )

        self.response_composer = (
            ResponseComposer()
        )

        # ----------------------------------------------------
        # Requirement Analyzer
        # ----------------------------------------------------

        self.requirement_analyzer = (
            RequirementAnalyzer()
        )

        # ----------------------------------------------------
        # PromptBuilder
        # ----------------------------------------------------

        self.prompt_builder = None

        if PromptBuilder is not None:

            try:

                self.prompt_builder = (
                    PromptBuilder()
                )

            except Exception as exc:

                logger.warning(
                    "PromptBuilder initialization failed: %s",
                    exc,
                )

        # ----------------------------------------------------
        # Local LLM
        # ----------------------------------------------------

        self.local_llm = None

        if LocalLLMEngine is not None:

            try:

                self.local_llm = (
                    LocalLLMEngine()
                )

            except Exception as exc:

                logger.warning(
                    "LocalLLMEngine initialization failed: %s",
                    exc,
                )

        # ----------------------------------------------------
        # Project Build Service
        # ----------------------------------------------------

        self.project_build_service = None

        if ProjectBuildService is not None:

            try:

                # --------------------------------------------
                # 可能であれば同じLLM Engineを共有
                # --------------------------------------------

                try:

                    self.project_build_service = (
                        ProjectBuildService(
                            llm_engine=
                                self.local_llm
                        )
                    )

                except TypeError:

                    # 古いconstructor互換
                    self.project_build_service = (
                        ProjectBuildService()
                    )

            except Exception as exc:

                logger.warning(
                    "ProjectBuildService initialization failed: %s",
                    exc,
                )

        self._debug(
            "initialized "
            f"default_mode={self.default_mode}, "
            f"project_build="
            f"{self.project_build_service is not None}"
        )

    # ========================================================
    # Debug
    # ========================================================

    def _debug(
        self,
        message: str,
    ) -> None:

        if not self.enable_debug:
            return

        print(
            "💬 "
            f"[{self.HANDLER_NAME}] "
            f"{message}",
            flush=True,
        )

    # ========================================================
    # Handler Score
    # ========================================================

    async def calculate_score(
        self,
        message: str,
        current_signals: Optional[
            dict
        ] = None,
    ) -> int:

        text = (
            message
            if isinstance(
                message,
                str,
            )
            else str(
                message
            )
        )

        if not text.strip():

            return 0

        current_signals = (
            current_signals
            if isinstance(
                current_signals,
                dict,
            )
            else {}
        )

        # ----------------------------------------------------
        # Orchestratorが既にIntent解析済みなら再利用
        # ----------------------------------------------------

        analysis = self._extract_existing_analysis(
            current_signals
        )

        if not analysis:

            # IntentInspectorはChatOrchestrator側で1回だけ実行する。
            # ChatHandler単体で採点された場合もクラッシュさせず、
            # unknownとしてHandler固有ルールへフォールバックする。
            analysis = {
                "mode": "unknown",
                "intent": "unknown",
                "score": 0,
            }

            self._debug(
                "intent_analysis was not supplied; "
                "using safe score fallback"
            )

        mode = (
            analysis.get(
                "mode"
            )
            or "unknown"
        )

        intent = (
            analysis.get(
                "intent"
            )
            or mode
            or "unknown"
        )

        # ----------------------------------------------------
        # Build Intent
        #
        # アプリ相談がChatHandlerに入っている状態なら、
        # 「じゃあ作って」を確実に拾う。
        # ----------------------------------------------------

        if self._is_build_intent(
            message=text,
            analysis=analysis,
        ):

            return 95

        # ----------------------------------------------------
        # Project conversation continuation
        # ----------------------------------------------------

        conversation_state = (
            current_signals.get(
                "conversation_state",
                {}
            )
        )

        project_context = {}

        if isinstance(
            conversation_state,
            dict,
        ):

            raw_project_context = (
                conversation_state.get(
                    "project_context"
                )
            )

            if isinstance(
                raw_project_context,
                dict,
            ):

                project_context = (
                    raw_project_context
                )

        if (
            self._has_project_context(
                project_context
            )
            and self._looks_like_project_message(
                text
            )
        ):

            return 90

        # ----------------------------------------------------
        # IntentInspector Chat系
        # ----------------------------------------------------

        if (
            mode in (
                "casual_chat",
                "general_chat",
                "knowledge_question",
                "follow_up",
                "agreement",
                "disagreement",
                "greeting",
                "thanks",
            )
            or intent in (
                "casual_chat",
                "general_chat",
                "knowledge_question",
                "follow_up",
                "agreement",
                "disagreement",
                "greeting",
                "thanks",
            )
        ):

            return 85

        # ----------------------------------------------------
        # Casual
        # ----------------------------------------------------

        lowered = (
            text.lower()
        )

        if any(
            word in lowered
            for word
            in self.CASUAL_WORDS
        ):

            return 80

        # ----------------------------------------------------
        # Project相談
        # ----------------------------------------------------

        if self._looks_like_project_message(
            text
        ):

            # ProjectBuilderHandlerなどとの競合を避けるため
            # 明示Buildではない相談段階はChatHandlerを強める
            return 82

        # ----------------------------------------------------
        # Unknown
        # ----------------------------------------------------

        if mode == "unknown":

            if len(
                text.strip()
            ) <= 20:

                return 70

            return (
                self.DEFAULT_SCORE
            )

        # ----------------------------------------------------
        # Other
        # ----------------------------------------------------

        try:

            raw_score = int(
                analysis.get(
                    "score",
                    20,
                )
                or 20
            )

        except Exception:

            raw_score = 20

        return min(
            raw_score,
            45,
        )

    # ========================================================
    # Estimate
    # ========================================================

    def estimate_size(
        self,
        message: str,
    ) -> int:

        return 1600

    # ========================================================
    # Main
    # ========================================================

    async def handle(
        self,
        request,
    ) -> Tuple[str, Any]:

        # ====================================================
        # STEP 1
        # Message
        # ====================================================

        message = (
            self._extract_message(
                request
            )
        )

        if not message.strip():

            state = (
                ConversationState(
                    mode=
                        self.default_mode
                )
            )

            return self._simple_result(
                message=
                    "メッセージが空です。",

                source=
                    "system",

                state=
                    state,
            )

        self._debug(
            f"input={message!r}"
        )

        # ====================================================
        # STEP 2
        # Signals
        # ====================================================

        current_signals = (
            self._extract_signals(
                request
            )
        )

        # ====================================================
        # STEP 3
        # Restore State
        # ====================================================

        state = (
            self._restore_state(
                current_signals
            )
        )

        self._debug(
            "restored "
            f"mode={state.mode}, "
            f"topic={state.current_topic}"
        )

        # ====================================================
        # STEP 4
        # Mode
        # ====================================================

        requested_mode = (
            self._extract_requested_mode(
                request=
                    request,

                message=
                    message,
            )
        )

        if requested_mode:

            state.set_mode(
                requested_mode
            )
        self._debug(
    "requested "
    f"chat_mode="
    f"{getattr(request, 'chat_mode', None)!r}, "
    f"ai_mode="
    f"{getattr(request, 'ai_mode', None)!r}, "
    f"resolved="
    f"{requested_mode!r}"
)
        # ====================================================
        # STEP 5
        # Mode Switch only
        # ====================================================

        mode_response = (
            self._mode_switch_response(
                message,
                state,
            )
        )

        if mode_response:

            state.next_turn()

            state.update_intent(
                "mode_change"
            )

            state.add_user_message(
                content=
                    message,

                intent=
                    "mode_change",

                topic=
                    state.current_topic,
            )

            state.add_assistant_message(
                content=
                    mode_response,

                source=
                    "system",

                intent=
                    "mode_change",

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    mode_response,

                source=
                    "system",

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        "mode_change"
                },
            )

        # ====================================================
        # STEP 6
        # Context Resolver
        # ====================================================

        context_result = (
            self._resolve_context(
                message,
                state,
            )
        )

        resolved_message = str(
            context_result.get(
                "resolved",
                message,
            )
            or message
        )

        self._debug(
            "context "
            f"changed={context_result.get('changed')}, "
            f"resolved={resolved_message!r}"
        )

        # ====================================================
        # STEP 7
        # Intent
        #
        # ChatOrchestratorですでにIntentInspectorを
        # 実行している場合はその結果を優先する。
        # ====================================================

        analysis = (
            self._analysis_from_request_or_signals(
                request=
                    request,

                current_signals=
                    current_signals,

                fallback_message=
                    resolved_message,
            )
        )

        intent = (
            analysis.get(
                "intent"
            )
            or analysis.get(
                "mode"
            )
            or "unknown"
        )

        state.update_intent(
            intent
        )

        self._debug(
            f"intent={intent}"
        )

        # ====================================================
        # STEP 8
        # Phase 3 Requirement Analyzer
        #
        # 重要:
        # Build判定より先に実行する。
        #
        # 「Reactで作って」
        #
        # のような入力では、
        # React要件をStateへ保存してからBuildする。
        # ====================================================

        requirement_result = (
            self._update_project_context(
                message=
                    resolved_message,

                state=
                    state,
            )
        )

        project_context = (
            self._get_project_context(
                state
            )
        )

        self._debug(
            "project_context="
            + self._compact_json(
                project_context
            )
        )

        # OrchestratorがすでにロードしたKnowledgeを優先する。
        preloaded_knowledge = (
            self._extract_preloaded_knowledge(
                request
            )
        )

        if preloaded_knowledge:
            self._debug(
                "reusing preloaded knowledge count="
                f"{len(preloaded_knowledge)}"
            )

        # ====================================================
        # STEP 9
        # Knowledge Router
        # ====================================================

        if preloaded_knowledge:
            route_result = None
            knowledge_paths: List[str] = []
        else:
            route_result = (
                self._route_knowledge(
                    message=
                        resolved_message,

                    state=
                        state,

                    analysis=
                        analysis,
                )
            )

            knowledge_paths = (
                self._extract_route_paths(
                    route_result
                )
            )

        self._debug(
            f"knowledge_paths={knowledge_paths}"
        )

        # ====================================================
        # STEP 10
        # Topic
        # ====================================================

        topic_result = (
            self._track_topic(
                message=
                    resolved_message,

                state=
                    state,

                analysis=
                    analysis,

                knowledge_paths=
                    knowledge_paths,
            )
        )

        detected_topic = (
            topic_result.get(
                "topic"
            )
        )

        if detected_topic:

            state.update_topic(
                detected_topic
            )

            state.add_entity(
                detected_topic
            )

        # ----------------------------------------------------
        # Project中なのにTopicが取れない場合の補完
        # ----------------------------------------------------

        if (
            not state.current_topic
            and self._has_project_context(
                project_context
            )
        ):

            state.update_topic(
                "アプリ開発"
            )

        self._debug(
            "topic="
            f"{state.current_topic}, "
            "previous="
            f"{state.previous_topic}"
        )

        # ====================================================
        # STEP 11
        # Active Knowledge
        # ====================================================

        state.update_active_knowledge(
            knowledge_paths
        )

        # ====================================================
        # STEP 12
        # User History
        # ====================================================

        state.next_turn()

        state.add_user_message(
            content=
                message,

            intent=
                intent,

            topic=
                state.current_topic,
        )

        # ====================================================
        # STEP 13
        # BUILD INTENT
        #
        # User History/Requirement保存後にBuildへ移行。
        # ====================================================

        if self._is_build_intent(
            message=
                resolved_message,

            analysis=
                analysis,
        ):

            self._debug(
                "project build intent detected"
            )

            return await self._handle_project_build(
                message=
                    resolved_message,

                state=
                    state,

                current_signals=
                    current_signals,

                analysis=
                    analysis,

                requirement_result=
                    requirement_result,

                context_result=
                    context_result,

                topic_result=
                    topic_result,
            )

        # ====================================================
        # STEP 14
        # KnowledgeLoader
        # ====================================================

        loaded_knowledge = (
            preloaded_knowledge
            if preloaded_knowledge
            else self._load_knowledge(
                knowledge_paths
            )
        )

        self._debug(
            "loaded knowledge count="
            f"{len(loaded_knowledge)}"
        )

        # ====================================================
        # STEP 15
        # Summary
        # ====================================================

        summary = (
            self._build_summary(
                state
            )
        )

        state.update_summary(
            summary
        )

        # ====================================================
        # STEP 16
        # Project Conversation Response
        #
        # アプリ相談中なら、
        # Knowledgeが無くても普通の
        # 「Knowledgeありません」で終わらせない。
        # ====================================================

        if (
            self._has_project_context(
                project_context
            )
            and self._looks_like_project_message(
                resolved_message
            )
            and not loaded_knowledge
        ):

            project_response = (
                self._compose_project_conversation_response(
                    message=
                        resolved_message,

                    project_context=
                        project_context,

                    state=
                        state,
                )
            )

            # ------------------------------------------------
            # AI modeならLocalLLMで自然に会話させてもよい
            # ------------------------------------------------

            if (
                state.ai_enabled
                and self.local_llm
                is not None
            ):

                llm_response = (
                    self._generate_with_local_llm(
                        user_message=
                            resolved_message,

                        analysis=
                            analysis,

                        state=
                            state,

                        summary=
                            summary,
                    )
                )

                if llm_response:

                    project_response = (
                        llm_response
                    )

            state.add_assistant_message(
                content=
                    project_response,

                source=
                    (
                        "local_llm"
                        if state.ai_enabled
                        and self.local_llm
                        is not None
                        else "project_rule"
                    ),

                intent=
                    intent,

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    project_response,

                source=
                    (
                        "local_llm"
                        if state.ai_enabled
                        and self.local_llm
                        is not None
                        else "project_rule"
                    ),

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        intent,

                    "analysis":
                        analysis,

                    "project_context":
                        project_context,

                    "requirements":
                        requirement_result,

                    "context_resolution":
                        context_result,

                    "topic_tracking":
                        topic_result,

                    "summary":
                        summary,
                },
            )

        # ====================================================
        # STEP 17
        # Knowledge first
        # ====================================================

        if loaded_knowledge:

            response = None
            response_source = "json"

            # AIモードではKnowledgeを根拠としてLocalLLMに渡す。
            # LLMが使えない/失敗した場合だけルールベースへ戻る。
            if (
                state.ai_enabled
                and self.local_llm is not None
            ):
                response = (
                    self._generate_with_local_llm(
                        user_message=
                            resolved_message,

                        analysis=
                            analysis,

                        state=
                            state,

                        summary=
                            summary,

                        knowledge_data=
                            loaded_knowledge,
                    )
                )

                if response:
                    response_source = "local_llm+knowledge"

            if not response:
                response = (
                    self._compose_response(
                        user_message=
                            resolved_message,

                        intent=
                            intent,

                        knowledge=
                            loaded_knowledge,

                        state=
                            state,
                    )
                )

            state.add_assistant_message(
                content=
                    response,

                source=
                    response_source,

                intent=
                    intent,

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    response,

                source=
                    response_source,

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        intent,

                    "analysis":
                        analysis,

                    "project_context":
                        project_context,

                    "requirements":
                        requirement_result,

                    "context_resolution":
                        context_result,

                    "topic_tracking":
                        topic_result,

                    "knowledge_paths":
                        knowledge_paths,

                    "summary":
                        summary,
                },
            )

        # ====================================================
        # STEP 18
        # chatbot mode
        # ====================================================

        if state.chatbot_enabled:

            response = (
                self._compose_chatbot_fallback(
                    message=
                        resolved_message,

                    intent=
                        intent,

                    state=
                        state,
                )
            )

            state.add_assistant_message(
                content=
                    response,

                source=
                    "rule",

                intent=
                    intent,

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    response,

                source=
                    "rule",

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        intent,

                    "analysis":
                        analysis,

                    "project_context":
                        project_context,

                    "requirements":
                        requirement_result,

                    "context_resolution":
                        context_result,

                    "topic_tracking":
                        topic_result,

                    "summary":
                        summary,
                },
            )

        # ====================================================
        # STEP 19
        # AI mode
        # ====================================================

        if state.ai_enabled:

            response = (
                self._generate_with_local_llm(
                    user_message=
                        resolved_message,

                    analysis=
                        analysis,

                    state=
                        state,

                    summary=
                        summary,
                )
            )

            if response:

                state.add_assistant_message(
                    content=
                        response,

                    source=
                        "local_llm",

                    intent=
                        intent,

                    topic=
                        state.current_topic,
                )

                return self._finalize(
                    message=
                        response,

                    source=
                        "local_llm",

                    state=
                        state,

                    current_signals=
                        current_signals,

                    extra={
                        "intent":
                            intent,

                        "analysis":
                            analysis,

                        "project_context":
                            project_context,

                        "requirements":
                            requirement_result,

                        "context_resolution":
                            context_result,

                        "topic_tracking":
                            topic_result,

                        "summary":
                            summary,
                    },
                )

        # ====================================================
        # STEP 20
        # LLM unavailable
        # ====================================================

        response = (
            "AIモードは有効ですが、"
            "LocalLLMEngineを現在利用できません。"
            "登録済みのJSON Knowledgeで回答できる"
            "内容を入力してください。"
        )

        state.set_error(
            "local_llm_unavailable"
        )

        state.add_assistant_message(
            content=
                response,

            source=
                "system",

            intent=
                intent,

            topic=
                state.current_topic,
        )

        return self._finalize(
            message=
                response,

            source=
                "system",

            state=
                state,

            current_signals=
                current_signals,

            extra={
                "intent":
                    intent,

                "analysis":
                    analysis,

                "project_context":
                    project_context,
            },
        )

    # ========================================================
    # Project Context
    # ========================================================

    def _update_project_context(
        self,
        message: str,
        state: ConversationState,
    ) -> Dict[str, Any]:
        """
        RequirementAnalyzerで現在の発言から
        Project Contextを更新する。

        Project関連でない会話の場合もAnalyzerは安全に
        空/既存Contextを返す想定。
        """

        current_context = (
            self._get_project_context(
                state
            )
        )

        # ----------------------------------------------------
        # Projectに全く関係がなく、
        # 既存Project Contextも無ければ解析しない。
        # ----------------------------------------------------

        if (
            not self._looks_like_project_message(
                message
            )
            and not self._has_project_context(
                current_context
            )
        ):

            return current_context

        try:

            result = (
                self.requirement_analyzer
                .analyze(
                    message=
                        message,

                    current_context=
                        current_context,
                )
            )

        except Exception as exc:

            logger.exception(
                "RequirementAnalyzer failed"
            )

            self._debug(
                "RequirementAnalyzer failed: "
                f"{exc}"
            )

            return current_context

        if not isinstance(
            result,
            dict,
        ):

            return current_context

        # ----------------------------------------------------
        # ConversationState側のmerge APIを優先
        # ----------------------------------------------------

        updater = getattr(
            state,
            "update_project_context",
            None,
        )

        if callable(
            updater
        ):

            try:

                updater(
                    result
                )

            except Exception as exc:

                self._debug(
                    "state.update_project_context failed: "
                    f"{exc}"
                )

        else:

            # 古いConversationState互換
            try:

                state.project_context = (
                    dict(
                        result
                    )
                )

            except Exception:

                pass

        return result

    # ========================================================
    # Project Context Getter
    # ========================================================

    def _get_project_context(
        self,
        state: ConversationState,
    ) -> Dict[str, Any]:

        getter = getattr(
            state,
            "get_project_context",
            None,
        )

        if callable(
            getter
        ):

            try:

                result = getter()

                if isinstance(
                    result,
                    dict,
                ):

                    return result

            except Exception:

                pass

        raw = getattr(
            state,
            "project_context",
            {},
        )

        if isinstance(
            raw,
            dict,
        ):

            return dict(
                raw
            )

        return {}

    # ========================================================
    # Has Project Context
    # ========================================================

    @staticmethod
    def _has_project_context(
        context: Dict[str, Any],
    ) -> bool:

        if not isinstance(
            context,
            dict,
        ):

            return False

        meaningful_fields = (
            "project_name",
            "framework",
            "purpose",
            "description",
            "target_user",
            "features",
            "pages",
            "database",
            "backend",
            "design_preferences",
            "constraints",
            "raw_requirements",
        )

        for key in meaningful_fields:

            value = context.get(
                key
            )

            if value not in (
                None,
                "",
                [],
                {},
                False,
            ):

                return True

        return False

    # ========================================================
    # Looks Like Project
    # ========================================================

    def _looks_like_project_message(
        self,
        message: str,
    ) -> bool:

        lowered = str(
            message or ""
        ).lower()

        return any(
            word in lowered
            for word
            in self.PROJECT_WORDS
        )

    # ========================================================
    # Build Intent
    # ========================================================

    def _is_build_intent(
        self,
        message: str,
        analysis: Optional[
            Dict[str, Any]
        ] = None,
    ) -> bool:
        """
        IntentInspectorの明示Intentを優先し、
        未整備の場合のみキーワードfallback。
        """

        analysis = (
            analysis
            if isinstance(
                analysis,
                dict,
            )
            else {}
        )

        intent_candidates = (
            analysis.get(
                "intent"
            ),
            analysis.get(
                "mode"
            ),
            analysis.get(
                "action"
            ),
        )

        for value in intent_candidates:

            if (
                value
                and str(
                    value
                ).lower()
                in self.PROJECT_BUILD_INTENTS
            ):

                return True

        # ----------------------------------------------------
        # actions配列
        # ----------------------------------------------------

        actions = analysis.get(
            "actions",
            []
        )

        if isinstance(
            actions,
            list,
        ):

            for action in actions:

                if isinstance(
                    action,
                    str,
                ):

                    value = (
                        action.lower()
                    )

                elif isinstance(
                    action,
                    dict,
                ):

                    value = str(
                        action.get(
                            "name"
                        )
                        or action.get(
                            "action"
                        )
                        or action.get(
                            "intent"
                        )
                        or ""
                    ).lower()

                else:

                    continue

                if value in (
                    self.PROJECT_BUILD_INTENTS
                ):

                    return True

        # ----------------------------------------------------
        # Text fallback
        # ----------------------------------------------------

        lowered = str(
            message or ""
        ).lower().strip()

        return any(
            phrase in lowered
            for phrase
            in self.PROJECT_BUILD_PHRASES
        )

    # ========================================================
    # Handle Project Build
    # ========================================================

    async def _handle_project_build(
        self,
        message: str,
        state: ConversationState,
        current_signals: Dict[str, Any],
        analysis: Dict[str, Any],
        requirement_result: Dict[str, Any],
        context_result: Dict[str, Any],
        topic_result: Dict[str, Any],
    ) -> Tuple[str, Any]:
        """
        ChatHandlerからProjectBuildServiceへ移行する唯一の入口。
        """

        project_context = (
            self._get_project_context(
                state
            )
        )

        # ----------------------------------------------------
        # Project context無し
        # ----------------------------------------------------

        if not self._has_project_context(
            project_context
        ):

            response = (
                "アプリを生成するための要件が"
                "まだありません。"
                "まず、どのようなアプリを作るか"
                "教えてください。"
            )

            state.add_assistant_message(
                content=
                    response,

                source=
                    "project_system",

                intent=
                    "project_build",

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    response,

                source=
                    "project_system",

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        "project_build",

                    "project_context":
                        project_context,
                },
            )

        # ----------------------------------------------------
        # Build Service未実装
        # ----------------------------------------------------

        if self.project_build_service is None:

            response = (
                "アプリの要件は保持できています。"
                "ただしProjectBuildServiceが"
                "まだ接続されていないため、"
                "現時点では実ファイル生成を開始できません。"
            )

            state.set_error(
                "project_build_service_unavailable"
            )

            state.add_assistant_message(
                content=
                    response,

                source=
                    "project_system",

                intent=
                    "project_build",

                topic=
                    state.current_topic,
            )

            return self._finalize(
                message=
                    response,

                source=
                    "project_system",

                state=
                    state,

                current_signals=
                    current_signals,

                extra={
                    "intent":
                        "project_build",

                    "project_context":
                        project_context,

                    "project_build": {
                        "status":
                            "unavailable",

                        "project_name":
                            project_context.get(
                                "project_name"
                            ),

                        "message":
                            response,
                    },

                    "blocks": [
                        {
                            "type":
                                "project_build",

                            "data": {
                                "status":
                                    "error",

                                "project_name":
                                    project_context.get(
                                        "project_name"
                                    ),

                                "message":
                                    response,

                                "files_generated":
                                    0,
                            },
                        }
                    ],
                },
            )

        # ----------------------------------------------------
        # Build
        # ----------------------------------------------------

        try:

            self._debug(
                "ProjectBuildService started"
            )

            build_method = getattr(
                self.project_build_service,
                "build",
                None,
            )

            if not callable(
                build_method
            ):

                raise AttributeError(
                    "ProjectBuildService.build() "
                    "がありません。"
                )

            result: Any = build_method(
                project_context=
                    project_context
            )

            # ----------------------------------------------------
            # Sync / Async 両対応
            # ----------------------------------------------------

            if inspect.isawaitable(
                result
            ):

                result = await cast(
                    Awaitable[Any],
                    result,
                )

        except Exception as exc:

            logger.exception(
                "Project build failed"
            )

            state.set_error(
                "project_build_error: "
                f"{exc}"
            )

            response = (
                "プロジェクト生成中に"
                "エラーが発生しました。"
            )

            state.add_assistant_message(
                content=
                    response,

                source=
                    "project_build",

                intent=
                    "project_build",

                topic=
                    state.current_topic,
            )

            build_data = {
                "project_name":
                    project_context.get(
                        "project_name"
                    )
                    or "generated-app",

                "status":
                    "error",

                "files_generated":
                    0,

                "message":
                    str(
                        exc
                    ),
            }

            return self._finalize_project_build(
                message=
                    response,

                build_data=
                    build_data,

                state=
                    state,

                current_signals=
                    current_signals,

                analysis=
                    analysis,

                requirement_result=
                    requirement_result,

                context_result=
                    context_result,

                topic_result=
                    topic_result,
            )

        # ----------------------------------------------------
        # Normalize Build Result
        # ----------------------------------------------------

        build_data = (
            self._normalize_build_result(
                result=
                    result,

                project_context=
                    project_context,
            )
        )

        status = str(
            build_data.get(
                "status",
                "success",
            )
        ).lower()

        if status in (
            "success",
            "completed",
            "complete",
        ):

            response = (
                build_data.get(
                    "message"
                )
                or (
                    f"{build_data.get('project_name', 'アプリ')} "
                    "の生成が完了しました。"
                )
            )

            state.clear_error()

        else:

            project_name = str(
                build_data.get(
                    "project_name"
                )
                or "プロジェクト"
            )

            build_message = str(
                build_data.get(
                    "message"
                )
                or ""
            ).strip()

            errors = build_data.get(
                "errors"
            )

            error_messages = []

            if isinstance(
                errors,
                list,
            ):

                error_messages = [
                    str(error)
                    for error in errors
                    if error
                ]

            response = (
                f"{project_name} の生成を試みましたが、"
                "正常に完了できませんでした。"
            )

            if build_message:

                response += (
                    f"\n\n{build_message}"
                )

            if error_messages:

                response += (
                    "\n\n確認されたエラー:\n- "
                    + "\n- ".join(
                        error_messages[:3]
                    )
                )

            response += (
                "\n\nアプリの要件は保持されています。"
            )

            state.set_error(
                "project_build_failed"
            )

        state.add_assistant_message(
            content=
                str(
                    response
                ),

            source=
                "project_build",

            intent=
                "project_build",

            topic=
                state.current_topic,
        )

        return self._finalize_project_build(
            message=
                str(
                    response
                ),

            build_data=
                build_data,

            state=
                state,

            current_signals=
                current_signals,

            analysis=
                analysis,

            requirement_result=
                requirement_result,

            context_result=
                context_result,

            topic_result=
                topic_result,
        )

    # ========================================================
    # Normalize Build Result
    # ========================================================

    def _normalize_build_result(
        self,
        result: Any,
        project_context: Dict[str, Any],
    ) -> Dict[str, Any]:

        # ----------------------------------------------------
        # to_dict()
        # ----------------------------------------------------

        if hasattr(
            result,
            "to_dict",
        ):

            try:
                result = result.to_dict()

            except Exception:
                pass

        # ----------------------------------------------------
        # 型を明示
        # ----------------------------------------------------

        build_data: Dict[str, Any]

        # ----------------------------------------------------
        # Dict
        # ----------------------------------------------------

        if isinstance(
            result,
            dict,
        ):

            data = result.get(
                "data"
            )

            if isinstance(
                data,
                dict,
            ):

                build_data = dict(
                    data
                )

            else:

                build_data = dict(
                    result
                )

        else:

            build_data = {
                "status":
                    "success",

                "message":
                    str(
                        result
                    ),
            }

        # ----------------------------------------------------
        # Defaults
        # ----------------------------------------------------

        project_name = (
            project_context.get(
                "project_name"
            )
            or "generated-app"
        )

        build_data.setdefault(
            "project_name",
            str(
                project_name
            ),
        )

        build_data.setdefault(
            "status",
            "success",
        )

        files_written = (
            build_data.get(
                "files_written"
            )
        )

        build_data.setdefault(
            "files_generated",
            files_written
            if isinstance(files_written, int)
            else 0,
        )

        build_data.setdefault(
            "logs",
            [],
        )

        return build_data

    # ========================================================
    # Final Project Build
    # ========================================================

    def _finalize_project_build(
        self,
        message: str,
        build_data: Dict[str, Any],
        state: ConversationState,
        current_signals: Dict[str, Any],
        analysis: Dict[str, Any],
        requirement_result: Dict[str, Any],
        context_result: Dict[str, Any],
        topic_result: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:

        updated_signals = dict(
            current_signals
        )

        updated_signals[
            "conversation_state"
        ] = state.to_dict()

        updated_signals[
            "active_context"
        ] = state.current_topic

        updated_signals[
            "chat_mode"
        ] = state.mode

        updated_signals[
            "project_context"
        ] = self._get_project_context(
            state
        )

        updated_signals[
            "last_project_build"
        ] = {
            "project_name":
                build_data.get(
                    "project_name"
                ),

            "status":
                build_data.get(
                    "status"
                ),

            "zip_download_url":
                build_data.get(
                    "zip_download_url"
                ),
        }

        result = {
            "message":
                message,

            "source":
                "project_build",

            "mode":
                state.mode,

            "ai_enabled":
                state.ai_enabled,

            "intent":
                "project_build",

            "analysis":
                analysis,

            "project_context":
                self._get_project_context(
                    state
                ),

            "requirements":
                requirement_result,

            "context_resolution":
                context_result,

            "topic_tracking":
                topic_result,

            "conversation_state":
                state.to_dict(),

            "project_build":
                build_data,

            "update_signals":
                updated_signals,

            # --------------------------------------------
            # Frontend Blocks
            # --------------------------------------------

            "blocks": [
                {
                    "type":
                        "project_build",

                    "data":
                        build_data,
                }
            ],
        }

        self._debug(
            "project build response "
            f"status={build_data.get('status')}"
        )

        return (
            "project_build",
            result,
        )

    # ========================================================
    # Project Conversation
    # ========================================================

    def _compose_project_conversation_response(
        self,
        message: str,
        project_context: Dict[str, Any],
        state: ConversationState,
    ) -> str:

        missing = (
            project_context.get(
                "missing_requirements",
                [],
            )
            or []
        )

        features = (
            project_context.get(
                "features",
                [],
            )
            or []
        )

        pages = (
            project_context.get(
                "pages",
                [],
            )
            or []
        )

        # ----------------------------------------------------
        # 要件を自然に続ける
        # ----------------------------------------------------

        if missing:

            readable = {
                "project_name":
                    "アプリ名",

                "framework":
                    "使用するフレームワーク",

                "purpose":
                    "アプリの目的",

                "target_user":
                    "主な利用者",
            }

            next_field = (
                missing[0]
            )

            field_name = (
                readable.get(
                    next_field,
                    next_field,
                )
            )

            return (
                "アプリの要件として記録しました。"
                f"現在は「{field_name}」がまだ未確定です。"
                "決まっていれば教えてください。"
                "まだ決めたくなければ、"
                "機能や画面について先に話しても大丈夫です。"
            )

        if features or pages:

            return (
                "ここまでのアプリ要件を保持しました。"
                "さらに機能・画面・デザイン・"
                "データベースなどを追加できます。"
                "内容が固まったら「じゃあ作って」と"
                "言えば生成段階へ進めます。"
            )

        return (
            "アプリ開発の相談として内容を保持しています。"
            "対象ユーザー、目的、欲しい機能、画面構成などを"
            "順番に追加できます。"
        )

    # ========================================================
    # Request
    # ========================================================

    def _extract_message(
        self,
        request,
    ) -> str:

        if isinstance(
            request,
            str,
        ):

            return request

        value = getattr(
            request,
            "message",
            "",
        )

        if isinstance(
            value,
            str,
        ):

            return value

        return str(
            getattr(
                value,
                "text",
                getattr(
                    value,
                    "content",
                    value,
                ),
            )
        )

    # ========================================================
    # Signals
    # ========================================================

    def _extract_signals(
        self,
        request,
    ) -> Dict[str, Any]:

        signals = getattr(
            request,
            "current_signals",
            None,
        )

        if isinstance(
            signals,
            dict,
        ):

            return dict(
                signals
            )

        return {}

    # ========================================================
    # Preloaded Knowledge
    # ========================================================

    def _extract_preloaded_knowledge(
        self,
        request,
    ) -> List[Any]:
        """
        ChatOrchestratorがすでに選択・ロードしたKnowledgeを再利用する。

        ChatHandler側で同じKnowledgeを再検索・再ロードすると、
        knowledge_dirの基準差や重複処理が発生しやすいため、
        request.loaded_knowledgeが存在する場合はこちらを優先する。
        """

        raw = getattr(
            request,
            "loaded_knowledge",
            None,
        )

        if raw is None:
            return []

        if isinstance(raw, list):
            return list(raw)

        if isinstance(raw, dict):
            values = list(raw.values())

            if values and all(
                isinstance(item, dict)
                for item in values
            ):
                return values

            return [raw]

        return []

    # ========================================================
    # State Restore
    # ========================================================

    def _restore_state(
        self,
        current_signals: Dict[str, Any],
    ) -> ConversationState:

        raw = current_signals.get(
            "conversation_state"
        )

        if not raw:

            return (
                ConversationState(
                    mode=
                        self.default_mode
                )
            )

        try:

            return (
                ConversationState.from_dict(
                    raw
                )
            )

        except Exception as exc:

            logger.exception(
                "ConversationState restore failed"
            )

            self._debug(
                "state restore failed: "
                f"{exc}"
            )

            return (
                ConversationState(
                    mode=
                        self.default_mode
                )
            )

    # ========================================================
    # Mode
    # ========================================================

    def _extract_requested_mode(
        self,
        request,
        message: str,
    ) -> Optional[str]:

        # ----------------------------------------------------
        # chat_mode
        # ----------------------------------------------------

        chat_mode = getattr(
            request,
            "chat_mode",
            None,
        )

        if chat_mode in (
            self.CHATBOT_MODE,
            self.AI_MODE,
        ):

            return chat_mode

        # ----------------------------------------------------
        # ai_mode
        # ----------------------------------------------------

        ai_mode = getattr(
            request,
            "ai_mode",
            None,
        )

        if isinstance(
            ai_mode,
            bool,
        ):

            return (
                self.AI_MODE
                if ai_mode
                else self.CHATBOT_MODE
            )

        # ----------------------------------------------------
        # Natural text
        # ----------------------------------------------------

        lowered = (
            message.lower()
        )

        if any(
            word in lowered
            for word
            in self.CHATBOT_ENABLE_WORDS
        ):

            return (
                self.CHATBOT_MODE
            )

        if any(
            word in lowered
            for word
            in self.AI_ENABLE_WORDS
        ):

            return (
                self.AI_MODE
            )

        return None

    # ========================================================
    # Mode Response
    # ========================================================

    def _mode_switch_response(
        self,
        message: str,
        state: ConversationState,
    ) -> Optional[str]:

        lowered = (
            message.lower()
        )

        if any(
            word in lowered
            for word
            in self.CHATBOT_ENABLE_WORDS
        ):

            return (
                "チャットボットモードに切り替えました。"
                "このモードでは生成AIを使用せず、"
                "JSON Knowledgeとルールだけを使います。"
            )

        if any(
            word in lowered
            for word
            in self.AI_ENABLE_WORDS
        ):

            return (
                "AIモードに切り替えました。"
                "JSON Knowledgeを優先し、"
                "必要な場合にLocalLLMを使用します。"
            )

        return None

    # ========================================================
    # Context Resolver
    # ========================================================

    def _resolve_context(
        self,
        message: str,
        state: ConversationState,
    ) -> Dict[str, Any]:

        try:

            result = (
                self.context_resolver.resolve(
                    user_input=
                        message,

                    topic=
                        state.current_topic,

                    state=
                        state,
                )
            )

            if isinstance(
                result,
                dict,
            ):

                return result

            if isinstance(
                result,
                str,
            ):

                return {
                    "original":
                        message,

                    "resolved":
                        result,

                    "changed":
                        result != message,

                    "reference":
                        None,

                    "source":
                        None,
                }

        except Exception as exc:

            self._debug(
                "ContextResolver failed: "
                f"{exc}"
            )

        return {
            "original":
                message,

            "resolved":
                message,

            "changed":
                False,

            "reference":
                None,

            "source":
                None,
        }

    # ========================================================
    # Existing Intent Analysis
    # ========================================================

    @staticmethod
    def _extract_existing_analysis(
        current_signals: Dict[str, Any],
    ) -> Dict[str, Any]:

        if not isinstance(
            current_signals,
            dict,
        ):

            return {}

        raw = (
            current_signals.get(
                "intent_analysis"
            )
        )

        if isinstance(
            raw,
            dict,
        ):

            return raw

        return {}

    # ========================================================
    # Analysis
    # ========================================================

    def _analysis_from_request_or_signals(
        self,
        request,
        current_signals: Dict[str, Any],
        fallback_message: str,
    ) -> Dict[str, Any]:

        # ----------------------------------------------------
        # 1. Orchestrator Signal
        # ----------------------------------------------------

        analysis = (
            self._extract_existing_analysis(
                current_signals
            )
        )

        if analysis:

            self._debug(
                "reusing orchestrator intent_analysis"
            )

            return analysis

        # ----------------------------------------------------
        # 2. request.intent_analysis
        # ----------------------------------------------------

        request_analysis = getattr(
            request,
            "intent_analysis",
            None,
        )

        if isinstance(
            request_analysis,
            dict,
        ):

            return request_analysis

        # ----------------------------------------------------
        # 3. Fallback
        # ----------------------------------------------------
        # IntentInspectorはChatOrchestratorで1回だけ実行する。
        # ChatHandler単体で呼ばれた場合は、ここで再解析せず
        # unknownとして安全に継続する。
        self._debug(
            "intent_analysis was not supplied by orchestrator; "
            "using safe fallback"
        )

        return {
            "mode": "unknown",
            "intent": "unknown",
            "score": 0,
            "routing_reason": "missing_orchestrator_intent_analysis",
            "fallback_message": fallback_message,
        }

    # ========================================================
    # Knowledge Router
    # ========================================================

    def _route_knowledge(
        self,
        message: str,
        state: ConversationState,
        analysis: Optional[Dict[str, Any]] = None,
    ):

        signals = {
            "active_context":
                state.current_topic,

            "current_topic":
                state.current_topic,

            "previous_topic":
                state.previous_topic,

            "active_knowledge":
                list(
                    state.active_knowledge
                ),

            "current_intent":
                state.current_intent,

            "project_context":
                self._get_project_context(
                    state
                ),

            # ChatOrchestratorで解析済みのIntentを
            # KnowledgeRouterへそのまま渡す。
            "intent_analysis":
                dict(analysis or {}),

            "mode":
                (analysis or {}).get("mode"),

            "intent":
                (analysis or {}).get("intent"),

            "actions":
                (analysis or {}).get("actions", []),

            "targets":
                (analysis or {}).get("targets", []),

            "target_categories":
                (analysis or {}).get("target_categories", []),
        }

        try:

            return (
                self.knowledge_router.route(
                    message,
                    signals=
                        signals,
                )
            )

        except TypeError:

            # 古いKnowledgeRouter互換
            try:

                return (
                    self.knowledge_router.route(
                        message
                    )
                )

            except Exception as exc:

                self._debug(
                    "KnowledgeRouter failed: "
                    f"{exc}"
                )

                return None

        except Exception as exc:

            logger.exception(
                "KnowledgeRouter failed"
            )

            self._debug(
                "KnowledgeRouter failed: "
                f"{exc}"
            )

            return None

    # ========================================================
    # Route Paths
    # ========================================================

    def _extract_route_paths(
        self,
        route_result,
    ) -> List[str]:

        if route_result is None:

            return []

        # ----------------------------------------------------
        # RouteResult.file_paths
        # ----------------------------------------------------

        file_paths = getattr(
            route_result,
            "file_paths",
            None,
        )

        if isinstance(
            file_paths,
            list,
        ):

            return [
                str(
                    path
                )
                for path
                in file_paths
            ]

        # ----------------------------------------------------
        # RouteResult.matched_files
        # ----------------------------------------------------

        matched_files = getattr(
            route_result,
            "matched_files",
            None,
        )

        if isinstance(
            matched_files,
            list,
        ):

            return [
                str(
                    path
                )
                for path
                in matched_files
            ]

        # ----------------------------------------------------
        # Dict
        # ----------------------------------------------------

        if isinstance(
            route_result,
            dict,
        ):

            values = (
                route_result.get(
                    "file_paths"
                )
                or route_result.get(
                    "matched_files"
                )
                or []
            )

            if isinstance(
                values,
                list,
            ):

                return [
                    str(
                        path
                    )
                    for path
                    in values
                ]

        # ----------------------------------------------------
        # List
        # ----------------------------------------------------

        if isinstance(
            route_result,
            list,
        ):

            return [
                str(
                    path
                )
                for path
                in route_result
            ]

        return []

    # ========================================================
    # Topic Tracker
    # ========================================================

    def _track_topic(
        self,
        message: str,
        state: ConversationState,
        analysis: Dict[str, Any],
        knowledge_paths: List[str],
    ) -> Dict[str, Any]:

        try:

            result = (
                self.topic_tracker.track(
                    user_input=
                        message,

                    state=
                        state,

                    analysis=
                        analysis,

                    knowledge_paths=
                        knowledge_paths,
                )
            )

            if isinstance(
                result,
                dict,
            ):

                return result

            if isinstance(
                result,
                str,
            ):

                return {
                    "topic":
                        result,

                    "previous_topic":
                        state.current_topic,

                    "changed":
                        result
                        != state.current_topic,

                    "source":
                        "tracker",
                }

        except Exception as exc:

            self._debug(
                "TopicTracker failed: "
                f"{exc}"
            )

        return {
            "topic":
                state.current_topic,

            "previous_topic":
                state.previous_topic,

            "changed":
                False,

            "source":
                "previous",
        }

    # ========================================================
    # Knowledge Loader
    # ========================================================

    def _load_knowledge(
        self,
        paths: List[str],
    ) -> List[Any]:

        if not paths:

            return []

        try:

            result = (
                self.knowledge_loader.load(
                    paths
                )
            )

        except Exception as exc:

            logger.exception(
                "KnowledgeLoader failed"
            )

            self._debug(
                "KnowledgeLoader failed: "
                f"{exc}"
            )

            return []

        # ----------------------------------------------------
        # LoadResult.items
        # ----------------------------------------------------

        items = getattr(
            result,
            "items",
            None,
        )

        if isinstance(
            items,
            list,
        ):

            return items

        # ----------------------------------------------------
        # Dict
        # ----------------------------------------------------

        if isinstance(
            result,
            dict,
        ):

            return list(
                result.values()
            )

        # ----------------------------------------------------
        # List
        # ----------------------------------------------------

        if isinstance(
            result,
            list,
        ):

            return result

        return []

    # ========================================================
    # Summary
    # ========================================================

    def _build_summary(
        self,
        state: ConversationState,
    ) -> Dict[str, Any]:

        try:

            result = (
                self.conversation_summary.summarize(
                    history=
                        state.history,

                    state=
                        state,
                )
            )

            if isinstance(
                result,
                dict,
            ):

                return result

            return {
                "text":
                    str(
                        result
                    )
            }

        except Exception as exc:

            self._debug(
                "ConversationSummary failed: "
                f"{exc}"
            )

        return {
            "current_topic":
                state.current_topic,

            "previous_topic":
                state.previous_topic,

            "current_intent":
                state.current_intent,

            "active_knowledge":
                list(
                    state.active_knowledge
                ),

            "turn_count":
                state.turn_count,

            "project_context":
                self._get_project_context(
                    state
                ),
        }

    # ========================================================
    # Response Composer
    # ========================================================

    def _compose_response(
        self,
        user_message: str,
        intent: str,
        knowledge: List[Any],
        state: ConversationState,
    ) -> str:

        try:

            response = (
                self.response_composer.compose(
                    user_message=
                        user_message,

                    intent=
                        intent,

                    knowledge=
                        knowledge,

                    state=
                        state,

                    is_ai_enabled=
                        False,
                )
            )

            if response:

                return str(
                    response
                )

        except TypeError:

            # ------------------------------------------------
            # 古いResponseComposer
            # ------------------------------------------------

            try:

                response = (
                    self.response_composer.compose(
                        raw_data=
                            knowledge,

                        is_ai_enabled=
                            False,
                    )
                )

                if response:

                    return str(
                        response
                    )

            except Exception:

                pass

        except Exception as exc:

            self._debug(
                "ResponseComposer failed: "
                f"{exc}"
            )

        return self._safe_json_response(
            knowledge
        )

    # ========================================================
    # Chatbot fallback
    # ========================================================

    def _compose_chatbot_fallback(
        self,
        message: str,
        intent: str,
        state: ConversationState,
    ) -> str:

        lowered = (
            message.lower()
        )

        # ----------------------------------------------------
        # Greeting
        # ----------------------------------------------------

        if any(
            word in lowered
            for word in (
                "こんにちは",
                "こんばんは",
                "おはよう",
            )
        ):

            return (
                "こんにちは。"
                "現在はチャットボットモードです。"
                "登録されているJSON Knowledgeと"
                "会話ルールを使って回答します。"
            )

        # ----------------------------------------------------
        # Thanks
        # ----------------------------------------------------

        if any(
            word in lowered
            for word in (
                "ありがとう",
                "ありがと",
                "助かった",
            )
        ):

            return (
                "どういたしまして。"
                "必要なら今の話題を続けられます。"
            )

        # ----------------------------------------------------
        # Agreement
        # ----------------------------------------------------

        if intent == "agreement":

            if state.current_topic:

                return (
                    "そうですね。"
                    f"今は「{state.current_topic}」の話として"
                    "文脈を保持しています。"
                )

            return (
                "そうですね。"
                "今の会話内容は保持しています。"
            )

        # ----------------------------------------------------
        # Follow-up
        # ----------------------------------------------------

        if intent == "follow_up":

            if state.current_topic:

                return (
                    f"「{state.current_topic}」についての"
                    "続きですね。"
                    "今回の入力に直接対応する"
                    "JSON Knowledgeが見つからなかったため、"
                    "確認できない情報の追加は行いません。"
                )

        return (
            "【チャットボットモード】\n"
            "この内容に対応するJSON Knowledgeを"
            "見つけられませんでした。\n"
            "確認できない情報を事実として生成しないよう、"
            "回答を控えています。"
        )

    # ========================================================
    # Safe JSON
    # ========================================================

    def _safe_json_response(
        self,
        knowledge: List[Any],
    ) -> str:

        converted = []

        for item in knowledge:

            converted.append(
                self._knowledge_to_data(
                    item
                )
            )

        if not converted:

            return (
                "関連Knowledgeは"
                "見つかりませんでした。"
            )

        payload: Any

        if len(
            converted
        ) == 1:

            payload = (
                converted[0]
            )

        else:

            payload = (
                converted
            )

        return (
            "【JSON Knowledgeからの回答】\n"
            + json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    # ========================================================
    # Knowledge to Data
    # ========================================================

    def _knowledge_to_data(
        self,
        item: Any,
    ) -> Any:

        if isinstance(
            item,
            (
                dict,
                list,
                str,
                int,
                float,
                bool,
                type(None),
            ),
        ):

            return item

        content = getattr(
            item,
            "content",
            None,
        )

        if content is not None:

            return content

        data = getattr(
            item,
            "data",
            None,
        )

        if data is not None:

            return data

        if hasattr(
            item,
            "__dict__",
        ):

            try:

                return dict(
                    item.__dict__
                )

            except Exception:

                pass

        return str(
            item
        )

    # ========================================================
    # Local LLM
    # ========================================================

    def _generate_with_local_llm(
        self,
        user_message: str,
        analysis: Dict[str, Any],
        state: ConversationState,
        summary: Dict[str, Any],
        knowledge_data: Optional[List[Any]] = None,
    ) -> Optional[str]:

        if not state.ai_enabled:

            return None

        if self.local_llm is None:

            return None

        # ----------------------------------------------------
        # 新PromptBuilderが使える場合
        # ----------------------------------------------------

        if (
            self.prompt_builder
            is not None
            and hasattr(
                self.prompt_builder,
                "build_chat_messages",
            )
            and hasattr(
                self.local_llm,
                "chat",
            )
        ):

            try:

                messages = (
                    self.prompt_builder
                    .build_chat_messages(
                        user_message=
                            user_message,

                        state=
                            state,

                        analysis=
                            analysis,

                        summary=
                            summary,

                        knowledge_data=
                            list(knowledge_data or []),
                    )
                )

                result = (
                    self.local_llm.chat(
                        messages,
                        temperature=0.3,
                        max_tokens=1200,
                    )
                )

                if isinstance(
                    result,
                    str,
                ):

                    return result.strip()

                if hasattr(
                    result,
                    "success",
                ):

                    if not result.success:

                        return None

                    text = getattr(
                        result,
                        "text",
                        None,
                    )

                    if text:

                        return str(
                            text
                        ).strip()

            except Exception as exc:

                self._debug(
                    "PromptBuilder/chat failed; "
                    "legacy generate fallback: "
                    f"{exc}"
                )

        # ----------------------------------------------------
        # Legacy LocalLLMEngine.generate
        # ----------------------------------------------------

        prompt = (
            self._build_local_llm_prompt(
                user_message=
                    user_message,

                analysis=
                    analysis,

                state=
                    state,

                summary=
                    summary,

                knowledge_data=
                    knowledge_data,
            )
        )

        generate = getattr(
            self.local_llm,
            "generate",
            None,
        )

        if not callable(
            generate
        ):

            return None

        try:

            result = generate(
                prompt
            )

            if not result:

                return None

            if isinstance(
                result,
                str,
            ):

                return result

            text = getattr(
                result,
                "text",
                None,
            )

            if text:

                return str(
                    text
                )

            return str(
                result
            )

        except Exception as exc:

            logger.exception(
                "LocalLLM generation failed"
            )

            state.set_error(
                "local_llm_error: "
                f"{exc}"
            )

            self._debug(
                "LocalLLM failed: "
                f"{exc}"
            )

            return None

    # ========================================================
    # Legacy Local LLM Prompt
    # ========================================================

    def _build_local_llm_prompt(
        self,
        user_message: str,
        analysis: Dict[str, Any],
        state: ConversationState,
        summary: Dict[str, Any],
        knowledge_data: Optional[List[Any]] = None,
    ) -> str:

        recent_messages = (
            state.get_recent_messages(
                limit=6
            )
        )

        context_snapshot = (
            state.get_context_snapshot()
        )

        return f"""
あなたはローカルで動作している会話AIです。

# 最重要ルール

- 確認できない事実を断定しない。
- JSON Knowledgeに無い情報を事実として捏造しない。
- ユーザーが発言していないことを事実として扱わない。
- facts と user_opinions を混同しない。
- ConversationStateを優先して会話文脈を維持する。
- Project Contextに保存された要件を維持する。
- Project Contextの未確定項目を勝手に確定しない。
- 不明な場合は不明と答えてよい。
- 架空のKnowledgeを作らない。
- 存在しない過去会話を作らない。

# Conversation State

{json.dumps(
    context_snapshot,
    ensure_ascii=False,
    indent=2,
    default=str,
)}

# Conversation Summary

{json.dumps(
    summary,
    ensure_ascii=False,
    indent=2,
    default=str,
)}

# Intent Analysis

{json.dumps(
    analysis,
    ensure_ascii=False,
    indent=2,
    default=str,
)}

# Active Knowledge

{json.dumps(
    list(knowledge_data or []),
    ensure_ascii=False,
    indent=2,
    default=str,
)}

# Recent Conversation

{json.dumps(
    recent_messages,
    ensure_ascii=False,
    indent=2,
    default=str,
)}

# User

{user_message}

# Assistant

会話の流れとProject Contextを維持しながら、
自然な日本語で返答してください。
""".strip()

    # ========================================================
    # Finalize
    # ========================================================

    def _finalize(
        self,
        message: str,
        source: str,
        state: ConversationState,
        current_signals: Dict[str, Any],
        extra: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Tuple[str, Dict[str, Any]]:

        # ----------------------------------------------------
        # Clear Error
        # ----------------------------------------------------

        if source in (
            "json",
            "rule",
            "project_rule",
            "local_llm",
        ):

            state.clear_error()

        # ----------------------------------------------------
        # Signals
        # ----------------------------------------------------

        updated_signals = dict(
            current_signals
        )

        updated_signals[
            "conversation_state"
        ] = state.to_dict()

        updated_signals[
            "active_context"
        ] = state.current_topic

        updated_signals[
            "chat_mode"
        ] = state.mode

        updated_signals[
            "project_context"
        ] = self._get_project_context(
            state
        )

        # ----------------------------------------------------
        # Result
        # ----------------------------------------------------

        result: Dict[str, Any] = {
            "message":
                message,

            "source":
                source,

            "mode":
                state.mode,

            "ai_enabled":
                state.ai_enabled,

            "conversation_state":
                state.to_dict(),

            "project_context":
                self._get_project_context(
                    state
                ),

            "update_signals":
                updated_signals,

            "blocks":
                [],
        }

        if extra:

            result.update(
                extra
            )

        self._debug(
            "response "
            f"source={source}, "
            f"mode={state.mode}, "
            f"topic={state.current_topic}, "
            f"turn={state.turn_count}"
        )

        if self.enable_debug:

            try:

                state.debug_print()

            except Exception:

                pass

        return (
            "text",
            result,
        )

    # ========================================================
    # Simple Result
    # ========================================================

    def _simple_result(
        self,
        message: str,
        source: str,
        state: ConversationState,
    ) -> Tuple[str, Dict[str, Any]]:

        return (
            "text",
            {
                "message":
                    message,

                "source":
                    source,

                "mode":
                    state.mode,

                "ai_enabled":
                    state.ai_enabled,

                "conversation_state":
                    state.to_dict(),

                "project_context":
                    self._get_project_context(
                        state
                    ),

                "blocks":
                    [],
            },
        )

    # ========================================================
    # Utility JSON
    # ========================================================

    @staticmethod
    def _compact_json(
        data: Any,
    ) -> str:

        try:

            return json.dumps(
                data,
                ensure_ascii=False,
                default=str,
            )

        except Exception:

            return str(
                data
            )
