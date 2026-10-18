#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/html/html_decompose_tool.py
HTML内の <script> / <style> / JSON設定ブロックを検出・抽出・分解するツール。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple
from tools.base_tool import BaseTool


class HtmlDecomposeTool(BaseTool):
    name = "script_decomposition"
    aliases = ["decomposition", "extract_script", "extract_style"]
    category = "html"
    description = "HTML内の<script>タグや<style>タグ、埋め込み設定JSONを検出・抽出・分解します。"

    fast_route_enabled = True
    priority = 10
    mode = "script_extraction"
    forced_handler = "DecompositionHandler"
    fast_route_score = 100

    _SCRIPT_RE = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
    _STYLE_RE = re.compile(r"<style\b[^>]*>", re.IGNORECASE)

    @classmethod
    def can_fast_route(
        cls,
        message: str,
        msg_lower: str,
        cache: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        has_script_tag = bool(cls._SCRIPT_RE.search(message))
        has_style_tag = bool(cls._STYLE_RE.search(message))
        if not (has_script_tag or has_style_tag):
            return False, ""

        pk = cache.get("parser_keywords", {})
        decomp_kws = pk.get(
            "DECOMPOSITION_KEYWORDS",
            ["分解", "抽出", "切り出し", "スクリプト", "extract", "decompose"],
        )
        if any(kw in msg_lower for kw in decomp_kws):
            return True, "script_tag_extraction"

        if has_script_tag:
            return True, "script_tag_detected"

        return False, ""

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "html_content": {
                    "type": "string",
                    "description": "抽出対象のHTMLまたはスクリプトを含むテキスト",
                }
            },
            "required": ["html_content"],
        }

    async def execute(self, html_content: str = "", **kwargs: Any) -> Dict[str, Any]:
        from api.services.handlers.code.Decompositionhandler import DecompositionHandler

        handler = DecompositionHandler()
        return await handler.handle(html_content or kwargs.get("message", ""))
