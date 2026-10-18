#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# IntentInspector.py
from __future__ import annotations

import importlib
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .detectors import (
    ForcedHandlerDetector,
    ActionDetector,
    TargetDetector,
    ThemeSurfaceDetector,
    DeploymentMetricDetector,
    load_json,
)
from .MessageTypeDetector import MessageTypeDetector
from .mode_rule import PYTHON_MODE_RULES, build_mode_rules

# ============================================================
# Path / Cache
# ============================================================

_DIR = os.path.dirname(os.path.abspath(__file__))
_KNOWLEDGE_DIR = os.path.join(_DIR, "Intentknowledge")

_INSPECTOR_CACHE: Dict[str, Any] = {}

_REQUIRED_KNOWLEDGE_KEYS = (
    "actions",
    "targets",
    "scoring",
    "mode_rules",
    "deployment_keywords",
    "deployment_themes",
    "parser_keywords",
    "feature_aliases",
    "crud_features",
    "tools",  # ← tools.json を自動キャッシュ対象に追加
)


def _ensure_loaded() -> None:
    """キャッシュが空の場合のみ、JSONを読み込んで初期化する"""
    global _INSPECTOR_CACHE
    if _INSPECTOR_CACHE:
        return

    loaded_files = 0
    if os.path.isdir(_KNOWLEDGE_DIR):
        for root, _, files in os.walk(_KNOWLEDGE_DIR):
            for file_name in files:
                if not file_name.lower().endswith(".json"):
                    continue

                file_path = os.path.join(root, file_name)
                cache_key = os.path.splitext(file_name)[0]

                try:
                    data = load_json(file_path)
                    _INSPECTOR_CACHE[cache_key] = data
                    loaded_files += 1
                except Exception as exc:
                    print(f"⚠️ [IntentInspector] Load Error {file_name}: {exc}", flush=True)

    for key in _REQUIRED_KNOWLEDGE_KEYS:
        _INSPECTOR_CACHE.setdefault(key, {})

    print(f"🧠 [IntentInspector] Knowledge Loaded: {loaded_files} files", flush=True)


def get_knowledge_cache() -> Dict[str, Any]:
    """他モジュールから安全に呼べる公開API。未ロードなら強制ロードする。"""
    _ensure_loaded()
    return _INSPECTOR_CACHE


# ============================================================
# IntentInspector
# ============================================================

class IntentInspector:
    """
    Detector群・ModeRule・toolsフォルダーのプラグインを統合し、
    Handler選択用のIntentを生成するスリムな司令塔。
    """

    def __init__(
        self,
        message: Any,
        available_knowledge_keys: Optional[List[str]] = None,
    ) -> None:
        self.raw_message = message
        self.available_knowledge_keys = available_knowledge_keys or []

        self.message = self._normalize_message(message)
        self.msg_lower = self.message.lower().strip()

        _ensure_loaded()
        self._initialize_detectors()

    @staticmethod
    def _normalize_message(message: Any) -> str:
        """str / オブジェクト形式のmessageを文字列へ統一する。"""
        if isinstance(message, str):
            return message
        return str(
            getattr(
                message,
                "text",
                getattr(message, "content", getattr(message, "body", message)),
            )
        )

    def _initialize_detectors(self) -> None:
        self.forced_detector = ForcedHandlerDetector()
        self.action_detector = ActionDetector(_INSPECTOR_CACHE["actions"])
        self.target_detector = TargetDetector(_INSPECTOR_CACHE["targets"])
        self.theme_detector = ThemeSurfaceDetector()
        self.deployment_detector = DeploymentMetricDetector(
            _INSPECTOR_CACHE["deployment_keywords"],
            _INSPECTOR_CACHE["deployment_themes"],
        )
        self.message_detector = MessageTypeDetector(self.message)

        mode_rule_data = _INSPECTOR_CACHE["mode_rules"]
        # mode_rules.json が未設定でも PYTHON_MODE_RULES の7種が必ず動くように順序を構築
        rule_order = list(mode_rule_data.keys()) if mode_rule_data else list(PYTHON_MODE_RULES.keys())
        for py_mode in PYTHON_MODE_RULES:
            if py_mode not in rule_order:
                rule_order.append(py_mode)

        self.mode_rules = build_mode_rules(
            _INSPECTOR_CACHE["scoring"],
            mode_rule_data,
            rule_order,
        )

        self.conversation_actions: Dict[str, List[str]] = _INSPECTOR_CACHE.get(
            "conversation_actions", {}
        )

    def _build_context(
        self,
        message_type: Dict[str, Any],
        ui_context: Dict[str, Any],
        deployment: Dict[str, Any],
        target_categories: List[str],
    ) -> Dict[str, Any]:
        return {
            "message_type": message_type.get("type", "unknown"),
            "is_code": message_type.get("is_code", False),
            "has_html": message_type.get("has_html", False),
            "theme": ui_context.get("theme"),
            "surface": ui_context.get("surface"),
            "responsive": ui_context.get("responsive", False),
            "modify_existing": ui_context.get("modify_existing", False),
            "deployment_metrics": deployment.get("deployment_metrics", {}),
            "deployment_surface": deployment.get("deployment_surface"),
            "deployment_theme": deployment.get("deployment_theme"),
            "target_categories": target_categories,
            "_KW_named_themes": _INSPECTOR_CACHE.get("deployment_keywords", {}).get(
                "named_themes", {}
            ),
        }

    # ========================================================
    # Mode Rules
    # ========================================================

    def _calculate_mode(
        self,
        actions: Any,
        targets: Any,
        context: Dict[str, Any],
    ) -> Tuple[str, int]:
        best_mode = "unknown"
        highest_score = 0

        for rule in self.mode_rules:
            try:
                if not rule.match(self.msg_lower, actions, targets, context):
                    continue
                score = rule.calculate_score(self.msg_lower, actions, targets, context)
            except Exception as exc:
                print(f"⚠️ [IntentInspector] ModeRule失敗 ({rule.mode_name}): {exc}", flush=True)
                continue

            if score > highest_score:
                highest_score = score
                best_mode = rule.mode_name

        scoring = _INSPECTOR_CACHE.get("scoring", {})
        max_score = scoring.get("global", {}).get("max_score_cap", 85)
        return best_mode, min(highest_score, max_score)

    # ========================================================
    # Tool Fast-Routing (tools.json + tools/*_tool.py 連携)
    # ========================================================

    def _evaluate_tools(
        self,
        context: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, bool], Optional[str]]:
        """
        tools.json に登録されたツール群を優先度順にチェックする。
        個別ロジックは tools/*_tool.py 側の can_fast_route() に委譲する。
        """
        tools_list = _INSPECTOR_CACHE.get("tools", {}).get("tools", [])
        sorted_tools = sorted(
            tools_list,
            key=lambda item: item.get("inspector_routing", {}).get("priority", 999),
        )

        routing_flags: Dict[str, bool] = {}
        matched_routing: Optional[Dict[str, Any]] = None
        matched_reason = ""
        detected_language: Optional[str] = None

        for tool_cfg in sorted_tools:
            if not tool_cfg.get("enabled", True):
                continue

            routing_cfg = tool_cfg.get("inspector_routing", {})
            tool_key = routing_cfg.get("flag_key") or tool_cfg.get("name", "unknown")

            if not routing_cfg.get("enabled", False):
                routing_flags[tool_key] = False
                continue

            is_match, reason, lang = self._run_tool_detector(tool_cfg, routing_cfg, context)
            if lang and not detected_language:
                detected_language = lang

            routing_flags[tool_key] = is_match

            if is_match and matched_routing is None:
                matched_routing = routing_cfg
                matched_reason = reason

        return matched_routing, matched_reason, routing_flags, detected_language

    def _run_tool_detector(
        self,
        tool_cfg: Dict[str, Any],
        routing_cfg: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[str]]:
        """
        1. tool_module (例: tools.math.calculator_tool.CalculatorTool) が指定されていれば
           その can_fast_route() を呼ぶ。
        2. 指定がなければ JSON 内の triggers (regex / slash_commands / keywords) で判定する。
        """
        detector_Spec = routing_cfg.get("tool_detector") or {}
        module_path = detector_Spec.get("module")
        class_name = detector_Spec.get("class")

        if module_path and class_name:
            try:
                mod = importlib.import_module(module_path)
                tool_cls = getattr(mod, class_name)
                is_match, reason = tool_cls.can_fast_route(
                    self.message, self.msg_lower, _INSPECTOR_CACHE, context
                )
                lang = None
                if hasattr(tool_cls, "detect_language"):
                    lang = tool_cls.detect_language(self.message, self.msg_lower, _INSPECTOR_CACHE)
                return is_match, reason, lang
            except Exception as exc:
                print(f"⚠️ [IntentInspector] ToolDetector失敗 ({module_path}.{class_name}): {exc}", flush=True)

        # JSON宣言トリガーによるフォールバック判定
        triggers = routing_cfg.get("triggers", {})
        for cmd in triggers.get("slash_commands", []):
            if self.msg_lower.startswith(cmd.lower()):
                return True, f"{tool_cfg.get('name')}_command", None

        regex_pat = triggers.get("regex")
        if regex_pat and re.search(regex_pat, self.message, flags=re.IGNORECASE):
            return True, triggers.get("default_reason", "regex_matched"), None

        for kw in triggers.get("keywords", []):
            if kw.lower() in self.msg_lower:
                return True, f"{tool_cfg.get('name')}_keyword", None

        return False, "", None

    # ========================================================
    # Conversation Intent Detection (Phase 2)
    # ========================================================

    def _detect_conversation_intent(self) -> Tuple[Optional[str], int, List[str]]:
        if not isinstance(self.conversation_actions, dict):
            return None, 0, []

        best_intent: Optional[str] = None
        best_score = 0
        best_matches: List[str] = []
        normalized_message = self.msg_lower.strip()

        for intent_name, keywords in self.conversation_actions.items():
            if not isinstance(keywords, list):
                continue

            matched_keywords = [
                str(kw).lower().strip()
                for kw in keywords
                if str(kw).strip() and self._conversation_keyword_matches(str(kw).lower().strip())
            ]
            if not matched_keywords:
                continue

            score = sum(35 if len(k) >= 8 else 25 if len(k) >= 4 else 10 for k in matched_keywords)
            for k in matched_keywords:
                if normalized_message == k:
                    score += 40
                elif normalized_message.startswith(k):
                    score += 10

            if len(self.message.strip()) <= 20:
                score += 10
            if len(self.message.strip()) >= 40 and all(len(k) <= 2 for k in matched_keywords):
                score = min(score, 10)

            score = min(score, 100)
            if score > best_score:
                best_score = score
                best_intent = str(intent_name)
                best_matches = matched_keywords

        return best_intent, best_score, best_matches

    def _conversation_keyword_matches(self, keyword: str) -> bool:
        message = self.msg_lower.strip()
        if not keyword:
            return False
        if len(keyword) >= 3:
            return keyword in message
        if message == keyword:
            return True
        return bool(
            re.search(rf"(?:^|\n)\s*{re.escape(keyword)}(?:[、,。.!！?？\s]|$)", message)
        )

    # ========================================================
    # Frontend Export (フロントエンド連携用API)
    # ========================================================

    def get_available_commands(self) -> Dict[str, Any]:
        pk = _INSPECTOR_CACHE.get("parser_keywords", {})
        conversation_keys = (
            list(self.conversation_actions.keys())
            if isinstance(self.conversation_actions, dict)
            else []
        )
        action_keys = list(_INSPECTOR_CACHE.get("actions", {}).keys())
        registered_tools = [
            t.get("name") for t in _INSPECTOR_CACHE.get("tools", {}).get("tools", []) if t.get("name")
        ]

        return {
            "slash_commands": pk.get("PARSER_COMMANDS", []),
            "parser_keywords": pk.get("PARSER_STRONG_KEYWORDS", []),
            "decomposition_keywords": pk.get("DECOMPOSITION_KEYWORDS", []),
            "conversation_intents": conversation_keys,
            "action_intents": action_keys,
            "registered_tools": registered_tools,
        }

    # ========================================================
    # Inspect（エントリーポイント）
    # ========================================================

    def inspect(self) -> Dict[str, Any]:
        print("🚨 [IntentInspector ENTER]", repr(self.message), flush=True)

        forced_handler = self.forced_detector.detect(self.message)
        message_type = self.message_detector.detect()
        actions = self.action_detector.detect(self.msg_lower)
        targets = self.target_detector.detect_words(self.msg_lower)
        target_categories = self.target_detector.detect_categories(self.msg_lower)
        ui_context = self.theme_detector.detect(self.msg_lower)
        deployment = self.deployment_detector.detect(self.msg_lower)

        context = self._build_context(message_type, ui_context, deployment, target_categories)
        best_mode, highest_score = self._calculate_mode(actions, targets, context)

        conversation_intent, conversation_score, conversation_matches = (
            self._detect_conversation_intent()
        )

        result: Dict[str, Any] = {
            "mode": best_mode,
            "intent": conversation_intent or best_mode or "unknown",
            "score": highest_score,
            "intent_score": conversation_score,
            "intent_matches": conversation_matches,
            "forced_handler": forced_handler,
            "actions": actions,
            "targets": targets,
            "target_categories": target_categories,
            "message_type_info": message_type,
            "available_knowledge": self.available_knowledge_keys,
            **ui_context,
            **deployment,
        }

        # --- 例外ルール：「空箱を作らない」 ---
        if "空箱" in self.msg_lower and "作らない" in self.msg_lower:
            best_mode = "unknown"
            highest_score = 0
            result["forced_handler"] = None

        # --- Tool Fast-Routing（tools.json & tools/*_tool.py による一括判定） ---
        matched_routing, routing_reason, routing_flags, detected_language = (
            self._evaluate_tools(context)
        )

        if matched_routing:
            best_mode = matched_routing.get("mode", best_mode)
            highest_score = matched_routing.get("score", 100)
            if matched_routing.get("forced_handler"):
                result["forced_handler"] = matched_routing["forced_handler"]

        final_intent = conversation_intent or best_mode or "unknown"

        result.update(
            {
                "mode": best_mode,
                "intent": final_intent,
                "score": highest_score,
                "detected_language": detected_language,
                "routing_reason": routing_reason,
                "routing": routing_flags,
            }
        )

        print(
            "[IntentInspector]",
            {
                "mode": best_mode,
                "intent": final_intent,
                "score": highest_score,
                "handler": result.get("forced_handler"),
                "language": detected_language,
                "routing": routing_flags,
                "reason": routing_reason,
                "is_code": message_type.get("is_code", False),
            },
            flush=True,
        )

        return result
