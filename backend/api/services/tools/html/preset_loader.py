#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/html/preset_loader.py
分割されたJSONプリセット（キーワード、Surface CSS、レイアウト骨格、データ駆動JSエンジン）を
一元管理・キャッシュしてHTMLHandlerや各Toolへ提供するローダー。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
LAYOUTS_DIR = PRESETS_DIR / "layouts"
SCRIPTS_DIR = PRESETS_DIR / "scripts"


class HTMLPresetLoader:
    _cache: Dict[str, Any] = {}

    @classmethod
    def _read_json(cls, path: Path) -> Dict[str, Any]:
        cache_key = str(path)
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cls._cache[cache_key] = data
            return data
        except Exception as exc:
            print(f"  [HTMLPresetLoader] JSONロード失敗: {path.name} - {exc}", flush=True)
            return {}

    @classmethod
    def _read_text(cls, path: Path) -> str:
        cache_key = str(path)
        if cache_key in cls._cache:
            return cls._cache[cache_key]
        if not path.is_file():
            return ""
        try:
            text = path.read_text(encoding="utf-8")
            cls._cache[cache_key] = text
            return text
        except Exception as exc:
            print(f"  [HTMLPresetLoader] テキストロード失敗: {path.name} - {exc}", flush=True)
            return ""

    @classmethod
    def reload_all(cls) -> None:
        """キャッシュをクリアして再読み込みを可能にする"""
        cls._cache.clear()

    @classmethod
    def get_keywords(cls) -> Dict[str, Any]:
        return cls._read_json(PRESETS_DIR / "keywords.json")

    @classmethod
    def get_surfaces(cls) -> Dict[str, Any]:
        return cls._read_json(PRESETS_DIR / "surfaces.json")

    @classmethod
    def get_layout(cls, layout_name: str) -> Dict[str, Any]:
        return cls._read_json(LAYOUTS_DIR / f"{layout_name}.json")

    @classmethod
    def get_script_engine(cls, engine_name: str) -> str:
        return cls._read_text(SCRIPTS_DIR / f"{engine_name}.js")

    @classmethod
    def build_complete_bundle(
        cls,
        layout_name: str,
        surface_name: str,
        title: str,
        custom_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """
        レイアウト骨格(HTML) + 表面テーマ(CSS) + メンテナンス分離型JSエンジンを結合して返す
        """
        surfaces = cls.get_surfaces()
        surface_css = surfaces.get(surface_name, {}).get(
            "css", "/* Surface CSS not found */
:root {}"
        )

        layout_data = cls.get_layout(layout_name)
        if not layout_data:
            layout_data = cls.get_layout("poster")

        html_template = layout_data.get("html_template", "<div class='{surface}'><h1>{title}</h1></div>")
        layout_css = layout_data.get("layout_css", "")
        engine_name = layout_data.get("script_engine", "")
        default_config = layout_data.get("default_config", {})

        merged_config = {**default_config, **(custom_config or {})}
        config_json_str = json.dumps(merged_config, ensure_ascii=False, indent=2)

        # HTMLの組み立て（データ定義JSONと汎用JSエンジンを分離注入）
        rendered_html = (
            html_template
            .replace("{surface}", surface_name)
            .replace("{title}", title)
        )

        if engine_name:
            js_engine_code = cls.get_script_engine(engine_name)
            script_block = (
                f"
<!-- 1. メンテナンス用データ定義 (ここを書き換えるだけで調整可能) -->
"
                f"<script id="app-config-data" type="application/json">
{config_json_str}
</script>
"
                f"<!-- 2. 汎用イベントエンジン ({engine_name}.js) -->
"
                f"<script>
{js_engine_code}
</script>"
            )
            rendered_html = rendered_html + script_block

        combined_css = f"/* === Surface: {surface_name} === */
{surface_css}

/* === Layout: {layout_name} === */
{layout_css}"

        return {
            "html": rendered_html,
            "css": combined_css,
            "layout": layout_name,
            "surface": surface_name,
        }
