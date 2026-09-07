import os
import re
from typing import Dict, Any

class HTMLSnipper:
    def __init__(self, template_dir: str = "templates/dummies", rules_dir: str = "templates/rules"):
        self.template_dir = template_dir
        self.rules_dir = rules_dir

    def _sanitize_filename(self, name: str) -> str:
        """パストラバーサルを防ぐための簡易サニタイズ"""
        return re.sub(r'[^a-zA-Z0-9_-]', '', str(name))

    def _read_file(self, filepath: str) -> str:
        if not os.path.exists(filepath):
            return ""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def _load_dummy_html_plugin(self):
        try:
            from plugins.Dummy_HTML.app import load_dummy_assets
            return load_dummy_assets()
        except Exception as e:
            return f"Error: {e}"

    def snip(self, intent_data: Dict[str, Any]) -> str:
        snippets = []

        # ----------------------------
        # 1. Dummy_HTMLプラグインからテンプレート取得
        # ----------------------------
        plugin_data = self._load_dummy_html_plugin()
        if isinstance(plugin_data, dict):
            html_content = plugin_data.get("html", "")
            css_content = plugin_data.get("css", "")
            
            if html_content:
                snippets.append("### Base HTML Template\n" + html_content)
            if css_content:
                snippets.append("### Base CSS Template\n" + css_content)
        elif isinstance(plugin_data, str):
            snippets.append(f"### Plugin Load Error\n{plugin_data}")

        # ----------------------------
        # 2. ターゲット別HTML
        # ----------------------------
        targets = intent_data.get("targets", [])
        if not targets and "create" in intent_data.get("actions", []):
            targets = ["base_container"]

        for target in targets:
            safe_target = self._sanitize_filename(target)
            html_path = os.path.join(self.template_dir, f"{safe_target}.html")
            js_path = os.path.join(self.template_dir, f"{safe_target}.js")

            html_content = self._read_file(html_path)
            if html_content:
                snippets.append(f"### Dummy HTML for [{safe_target}]\n" + html_content)

            js_content = self._read_file(js_path)
            if js_content:
                snippets.append(f"### Dummy JS for [{safe_target}]\n" + js_content)

        # ----------------------------
        # 3. テーマルール & 4. Surfaceルール
        # ----------------------------
        for rule_type in ["theme", "surface"]:
            rule_val = intent_data.get(rule_type)
            if rule_val:
                safe_val = self._sanitize_filename(rule_val)
                rule_path = os.path.join(self.rules_dir, f"{rule_type}_{safe_val}.yaml")
                rule_content = self._read_file(rule_path)
                if rule_content:
                    snippets.append(f"### {rule_type.capitalize()} Rules for: {safe_val}\n" + rule_content)

        # ----------------------------
        # 5. レスポンシブ制約
        # ----------------------------
        if intent_data.get("responsive"):
            snippets.append("### Constraints\n- 必須要件: レスポンシブ対応を実装すること")

        # ----------------------------
        # 6. AIへの最終指示 (モーダル出力用フォーマット指定の追加)
        # ----------------------------
        snippets.append(
            """### Instructions
上記テンプレートを参考にしてください。
ユーザーの要求を満たすために、必要なHTML/CSS/JSを編集・追加してください。
既存テンプレートを完全に破棄するのではなく、可能な限り再利用してください。

【重要：出力形式】
モーダルエディタで展開するため、出力は必ず以下の形式のJSONで返してください：
```json
{
  "html": "編集後のHTMLコード",
  "css": "編集後のCSSコード",
  "js": "編集後のJSコード",
  "message": "ユーザーへの説明文"
}
```"""
        )

        return "\n\n".join(snippets)