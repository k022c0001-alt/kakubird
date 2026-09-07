"""Deterministic action planning between intent analysis and ToolRouter.

The planner decides *what should happen next* but never executes a tool. It
preserves the current project rule: wanting an app starts requirements
conversation; only an explicit build command may create a project-build step.
"""
# backend/api/services/planning/ActionPlanner.py
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set
from api.services.handlers.Math_Handler import MathHandler


class PlanStatus(str, Enum):
    READY = "ready"
    NEEDS_INPUT = "needs_input"
    NO_ACTION = "no_action"


class ActionKind(str, Enum):
    TOOL = "tool"
    CLARIFY = "clarify"


@dataclass
class PlannedAction:
    action_id: str
    kind: ActionKind
    description: str
    tool_name: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionKind):
            self.kind = ActionKind(str(self.kind))
        self.action_id = str(self.action_id).strip()
        self.description = str(self.description).strip()
        self.tool_name = str(self.tool_name).strip().lower() if self.tool_name else None
        self.arguments = dict(self.arguments or {})
        self.depends_on = [str(item) for item in self.depends_on]
        self.metadata = dict(self.metadata or {})

        if not self.action_id:
            raise ValueError("action_id must not be empty")
        if self.kind is ActionKind.TOOL and not self.tool_name:
            raise ValueError("tool actions require tool_name")
        if self.kind is not ActionKind.TOOL and self.tool_name:
            raise ValueError("only tool actions may define tool_name")

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass
class ActionPlan:
    status: PlanStatus
    route: str
    message: str
    actions: List[PlannedAction] = field(default_factory=list)
    missing_requirements: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, PlanStatus):
            self.status = PlanStatus(str(self.status))
        self.route = str(self.route).strip().lower()
        self.message = str(self.message or "")
        self.missing_requirements = [str(item) for item in self.missing_requirements]
        self.reasons = [str(item) for item in self.reasons]
        self.context = dict(self.context or {})

        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action_id values must be unique")
        known_ids: Set[str] = set()
        for action in self.actions:
            unknown_dependencies = set(action.depends_on) - known_ids
            if unknown_dependencies:
                raise ValueError("actions may depend only on earlier actions")
            known_ids.add(action.action_id)

        if self.status is PlanStatus.READY and not self.actions:
            raise ValueError("ready plans require at least one action")

    @property
    def executable(self) -> bool:
        return self.status is PlanStatus.READY and any(
            action.kind is ActionKind.TOOL for action in self.actions
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "route": self.route,
            "message": self.message,
            "executable": self.executable,
            "actions": [action.to_dict() for action in self.actions],
            "missing_requirements": list(self.missing_requirements),
            "reasons": list(self.reasons),
            "context": deepcopy(self.context),
        }


class ActionPlanner:
    """Build a small, auditable plan from already available context."""

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
    MEANINGFUL_PROJECT_FIELDS = (
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

    def __init__(
        self,
        *,
        math_handler: Optional[MathHandler] = None,
        known_tools: Optional[Iterable[str]] = None,
    ) -> None:
        self.math_handler = math_handler or MathHandler()
        selected_tools = (
            known_tools
            if known_tools is not None
            else {"math", "project_build"}
        )
        self.known_tools = {
            str(name).strip().lower()
            for name in selected_tools
            if str(name).strip()
        }

    def plan(
        self,
        message: str,
        *,
        intent_analysis: Optional[Mapping[str, Any]] = None,
        current_signals: Optional[Mapping[str, Any]] = None,
        project_context: Optional[Mapping[str, Any]] = None,
    ) -> ActionPlan:
        text = str(message or "").strip()
        analysis = self._resolve_analysis(intent_analysis, current_signals)
        context = self._resolve_project_context(project_context, current_signals)

        if not text:
            return self._clarification_plan(
                route="conversation",
                message="実行したい内容を入力してください。",
                missing=("message",),
                reason="empty_message",
            )

        if self._is_build_intent(text, analysis):
            return self._plan_project_build(context)

        explicit_tool = self._extract_explicit_tool(analysis)
        if explicit_tool:
            if explicit_tool not in self.known_tools:
                return self._clarification_plan(
                    route="tool",
                    message=f"ツール「{explicit_tool}」は現在の計画対象にありません。",
                    missing=("supported_tool",),
                    reason="unknown_explicit_tool",
                    context={"requested_tool": explicit_tool},
                )
            arguments = self._extract_explicit_arguments(analysis)
            if explicit_tool == "math" and "expression" not in arguments:
                arguments["expression"] = text
            return self._tool_plan(
                route="tool",
                tool_name=explicit_tool,
                arguments=arguments,
                description=f"{explicit_tool}ツールを実行する",
                reason="tool_selected_by_intent_analysis",
            )

        score_message = getattr(self.math_handler, "score_message", None)
        math_score = score_message(text) if callable(score_message) else 0
        if math_score > 0:
            return self._tool_plan(
                route="tool",
                tool_name="math",
                arguments={"expression": text},
                description="安全な計算エンジンで式を計算する",
                reason="math_expression_detected",
                context={"math_score": math_score},
            )

        if self._looks_like_project_message(text):
            return ActionPlan(
                status=PlanStatus.NO_ACTION,
                route="project_requirements",
                message="アプリ要件の相談を続けます。明示的な作成命令まではビルドしません。",
                reasons=["project_requirements_conversation"],
                context={"project_context": context},
            )

        return ActionPlan(
            status=PlanStatus.NO_ACTION,
            route="conversation",
            message="ツール実行は不要です。通常の会話処理を続けます。",
            reasons=["no_tool_action_detected"],
        )

    async def plan_async(self, message: str, **kwargs: Any) -> ActionPlan:
        """Async-compatible entry point for ChatOrchestrator."""

        return self.plan(message, **kwargs)

    def _plan_project_build(self, project_context: Dict[str, Any]) -> ActionPlan:
        if not self._has_project_context(project_context):
            return self._clarification_plan(
                route="project_build",
                message="アプリを生成するための要件がまだありません。",
                missing=("project_context",),
                reason="project_context_missing",
            )

        missing = self._normalize_string_list(
            project_context.get("missing_requirements", [])
        )
        if missing:
            return self._clarification_plan(
                route="project_build",
                message="不足している要件を確認してからビルドします。",
                missing=missing,
                reason="project_requirements_incomplete",
                context={"project_context": project_context},
            )

        return self._tool_plan(
            route="project_build",
            tool_name="project_build",
            arguments={"project_context": deepcopy(project_context)},
            description="確定した要件からプロジェクトを生成する",
            reason="explicit_build_command_with_project_context",
            context={"project_name": project_context.get("project_name")},
        )

    @staticmethod
    def _resolve_analysis(
        intent_analysis: Optional[Mapping[str, Any]],
        current_signals: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if isinstance(intent_analysis, Mapping):
            return dict(intent_analysis)
        if isinstance(current_signals, Mapping):
            for key in ("intent_analysis", "analysis"):
                candidate = current_signals.get(key)
                if isinstance(candidate, Mapping):
                    return dict(candidate)
        return {}

    @classmethod
    def _resolve_project_context(
        cls,
        project_context: Optional[Mapping[str, Any]],
        current_signals: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if isinstance(project_context, Mapping):
            return deepcopy(dict(project_context))
        if not isinstance(current_signals, Mapping):
            return {}

        direct = current_signals.get("project_context")
        if isinstance(direct, Mapping):
            return deepcopy(dict(direct))

        state = current_signals.get("conversation_state")
        if isinstance(state, Mapping):
            nested = state.get("project_context")
            if isinstance(nested, Mapping):
                return deepcopy(dict(nested))
        return {}

    @classmethod
    def _is_build_intent(cls, message: str, analysis: Mapping[str, Any]) -> bool:
        candidates: List[str] = []
        for key in ("intent", "mode", "action"):
            value = analysis.get(key)
            if value:
                candidates.append(str(value).lower())

        actions = analysis.get("actions", [])
        if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
            for action in actions:
                if isinstance(action, str):
                    candidates.append(action.lower())
                elif isinstance(action, Mapping):
                    value = action.get("name") or action.get("action") or action.get("intent")
                    if value:
                        candidates.append(str(value).lower())

        if any(value in cls.PROJECT_BUILD_INTENTS for value in candidates):
            return True
        lowered = message.lower().strip()
        return any(phrase in lowered for phrase in cls.PROJECT_BUILD_PHRASES)

    @staticmethod
    def _extract_explicit_tool(analysis: Mapping[str, Any]) -> Optional[str]:
        value = analysis.get("tool_name") or analysis.get("tool")
        if isinstance(value, Mapping):
            value = value.get("name")
        return str(value).strip().lower() if value else None

    @staticmethod
    def _extract_explicit_arguments(analysis: Mapping[str, Any]) -> Dict[str, Any]:
        value = analysis.get("arguments") or analysis.get("tool_arguments") or {}
        return deepcopy(dict(value)) if isinstance(value, Mapping) else {}

    @classmethod
    def _has_project_context(cls, context: Mapping[str, Any]) -> bool:
        return any(
            context.get(key) not in (None, "", [], {}, False)
            for key in cls.MEANINGFUL_PROJECT_FIELDS
        )

    @classmethod
    def _looks_like_project_message(cls, message: str) -> bool:
        lowered = message.lower()
        return any(word in lowered for word in cls.PROJECT_WORDS)

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if value in (None, "", [], (), {}):
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable) and not isinstance(value, Mapping):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)]

    @staticmethod
    def _tool_plan(
        *,
        route: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        description: str,
        reason: str,
        context: Optional[Mapping[str, Any]] = None,
    ) -> ActionPlan:
        return ActionPlan(
            status=PlanStatus.READY,
            route=route,
            message=description,
            actions=[
                PlannedAction(
                    action_id="step_1",
                    kind=ActionKind.TOOL,
                    description=description,
                    tool_name=tool_name,
                    arguments=deepcopy(dict(arguments)),
                )
            ],
            reasons=[reason],
            context=deepcopy(dict(context or {})),
        )

    @staticmethod
    def _clarification_plan(
        *,
        route: str,
        message: str,
        missing: Iterable[str],
        reason: str,
        context: Optional[Mapping[str, Any]] = None,
    ) -> ActionPlan:
        missing_list = [str(item) for item in missing]
        return ActionPlan(
            status=PlanStatus.NEEDS_INPUT,
            route=route,
            message=message,
            actions=[
                PlannedAction(
                    action_id="step_1",
                    kind=ActionKind.CLARIFY,
                    description=message,
                    metadata={"missing_requirements": missing_list},
                )
            ],
            missing_requirements=missing_list,
            reasons=[reason],
            context=deepcopy(dict(context or {})),
        )


__all__ = [
    "ActionKind",
    "ActionPlan",
    "ActionPlanner",
    "PlannedAction",
    "PlanStatus",
]
