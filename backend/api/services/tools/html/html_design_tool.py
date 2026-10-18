#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/html/html_design_tool.py
ポスター、ルール付きクリック案内、授業プリント/解答用紙、
および「無限課金・広告過多・単調作業ゲームシミュレーター」を高速ルーティングするツール。
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from tools.base_tool import BaseTool
from tools.html.preset_loader import HTMLPresetLoader


class HtmlDesignTool(BaseTool):
    name = "html_design_generator"
    aliases = [
        "poster_layout",
        "interactive_guide",
        "worksheet_print",
        "satire_game_sim",
    ]
    category = "html"
    description = (
        "ポスター骨格、ルール順クリック案内、授業プリント・解答用紙、"
        "無限課金/広告過多/単調ゲームのシミュレーターHTMLを生成します。"
    )

    fast_route_enabled = True
    priority = 15
    mode = "ui_design"
    forced_handler = "HTMLHandler"
    fast_route_score = 95

    @classmethod
    def detect_layout_and_surface(cls, message: str) -> Tuple[str, str, str]:
        """メッセージから最適な (layout, surface, theme_title) を推論する"""
        msg_lower = message.lower()
        kw_data = HTMLPresetLoader.get_keywords()

        # 1. named_themes の完全・部分一致チェック
        named_themes = kw_data.get("named_themes", {})
        for name, info in named_themes.items():
            if name.lower() in msg_lower or name in message:
                return (
                    info.get("layout", "poster"),
                    info.get("surface", "glass"),
                    name,
                )

        # 2. レイアウト別トリガー判定
        layout_triggers = kw_data.get("layout_triggers", {})
        best_layout = "poster"
        best_score = 0
        for layout_key, words in layout_triggers.items():
            score = sum(1 for w in words if w.lower() in msg_lower or w in message)
            if score > best_score:
                best_score = score
                best_layout = layout_key

        # 3. Surface（質感）の推論
        surface_kw = kw_data.get("surface_keywords", {})
        best_surface = layout_data_default_surface(best_layout)
        max_surface_hits = 0
        for s_name, lang_dict in surface_kw.items():
            if s_name.startswith("_"):
                continue
            words = lang_dict.get("ja", []) + lang_dict.get("en", [])
            hits = sum(1 for w in words if w.lower() in msg_lower or w in message)
            if hits > max_surface_hits:
                max_surface_hits = hits
                best_surface = s_name

        return best_layout, best_surface, best_layout.upper()

    @classmethod
    def can_fast_route(
        cls,
        message: str,
        msg_lower: str,
        cache: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        kw_data = HTMLPresetLoader.get_keywords()
        commands = kw_data.get("triggers", {}).get(
            "commands", ["/html", "/css", "/design", "/poster", "/print", "/gacha", "/guide"]
        )
        if any(msg_lower.strip().startswith(cmd) for cmd in commands):
            return True, "html_command_trigger"

        named_themes = kw_data.get("named_themes", {})
        for name in named_themes:
            if name.lower() in msg_lower or name in message:
                return True, f"named_theme:{name}"

        layout_triggers = kw_data.get("layout_triggers", {})
        for layout_key, words in layout_triggers.items():
            if sum(1 for w in words if w.lower() in msg_lower or w in message) >= 2:
                return True, f"layout_trigger:{layout_key}"

        return False, ""

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "生成したいHTMLの指示文"},
                "layout": {
                    "type": "string",
                    "enum": ["poster", "interactive_guide", "worksheet_print", "satire_game_sim"],
                },
                "surface": {
                    "type": "string",
                    "enum": ["glass", "frosted-dark", "elevated", "bordered", "flat", "glow", "neumorphism", "paper"],
                },
            },
            "required": ["message"],
        }

    async def execute(self, message: str = "", **kwargs: Any) -> Dict[str, Any]:
        from api.services.handlers.code.HtmlHandler import HTMLHandler

        handler = HTMLHandler()
        _, content = await handler.handle(message or kwargs.get("prompt", ""))
        return content


def layout_data_default_surface(layout_key: str) -> str:
    defaults = {
        "poster": "glow",
        "interactive_guide": "elevated",
        "worksheet_print": "paper",
        "satire_game_sim": "glow",
    }
    return defaults.get(layout_key, "glass")
