# # backend/api/services/snippers/html_snipper.py

# import os
# from typing import Dict, Any

# class HTMLSnipper:
#     def __init__(self, template_dir: str = "templates/dummies", rules_dir: str = "templates/rules"):
#         # ダミーのコードやYAMLルールを置いておくディレクトリ
#         self.template_dir = template_dir
#         self.rules_dir = rules_dir

# def snip(self, intent_data: Dict[str, Any]) -> str:
#     """
#     IntentInspectorの解析結果を受け取り、
#     AIに渡すコンテキストを生成する
#     """

#     snippets = []

#     # ----------------------------
#     # 1. Dummy_HTMLプラグインからテンプレート取得
#     # ----------------------------

#     try:

#         from plugins.Dummy_HTML.app import load_dummy_assets

#         plugin_data = load_dummy_assets()

#         if plugin_data:

#             html_content = plugin_data.get("html", "")
#             css_content = plugin_data.get("css", "")

#             if html_content:

#                 snippets.append(
#                     "### Base HTML Template"
#                 )

#                 snippets.append(
#                     html_content
#                 )

#             if css_content:

#                 snippets.append(
#                     "### Base CSS Template"
#                 )

#                 snippets.append(
#                     css_content
#                 )

#     except Exception as e:

#         snippets.append(
#             f"### Plugin Load Error\n{str(e)}"
#         )

#     # ----------------------------
#     # 2. ターゲット別HTML
#     # ----------------------------

#     targets = intent_data.get(
#         "targets",
#         []
#     )

#     if (
#         not targets and
#         "create" in intent_data.get(
#             "actions",
#             []
#         )
#     ):
#         targets = ["base_container"]

#     for target in targets:

#         html_path = os.path.join(
#             self.template_dir,
#             f"{target}.html"
#         )

#         js_path = os.path.join(
#             self.template_dir,
#             f"{target}.js"
#         )

#         snippets.append(
#             f"### Dummy HTML for [{target}]"
#         )

#         snippets.append(
#             self._read_file(
#                 html_path,
#                 target
#             )
#         )

#         if os.path.exists(js_path):

#             snippets.append(
#                 f"### Dummy JS for [{target}]"
#             )

#             snippets.append(
#                 self._read_file(
#                     js_path,
#                     target
#                 )
#             )

#     # ----------------------------
#     # 3. テーマルール
#     # ----------------------------

#     theme = intent_data.get(
#         "theme"
#     )

#     if theme:

#         theme_rule_path = os.path.join(
#             self.rules_dir,
#             f"theme_{theme}.yaml"
#         )

#         snippets.append(
#             f"### Design Rules for Theme: {theme}"
#         )

#         snippets.append(
#             self._read_file(
#                 theme_rule_path,
#                 theme
#             )
#         )

#     # ----------------------------
#     # 4. Surfaceルール
#     # ----------------------------

#     surface = intent_data.get(
#         "surface"
#     )

#     if surface:

#         surface_rule_path = os.path.join(
#             self.rules_dir,
#             f"surface_{surface}.yaml"
#         )

#         snippets.append(
#             f"### Surface Rules for: {surface}"
#         )

#         snippets.append(
#             self._read_file(
#                 surface_rule_path,
#                 surface
#             )
#         )

#     # ----------------------------
#     # 5. レスポンシブ制約
#     # ----------------------------

#     if intent_data.get(
#         "responsive"
#     ):

#         snippets.append(
#             "### Constraints"
#         )

#         snippets.append(
#             "- 必須要件: レスポンシブ対応を実装すること"
#         )

#     # ----------------------------
#     # 6. AIへの最終指示
#     # ----------------------------

#     snippets.append(
#         """
# ### Instructions

# 上記テンプレートを参考にしてください。

# ユーザーの要求を満たすために、
# 必要なHTML/CSS/JSを編集・追加してください。

# 既存テンプレートを完全に破棄するのではなく、
# 可能な限り再利用してください。
# """
#     )

#     return "\n\n".join(snippets)
# def _read_file(self, filepath: str, item_name: str) -> str:
#         if not os.path.exists(filepath):
#             return ""
#         try:
#             with open(filepath, "r", encoding="utf-8") as f:
#                 return f.read()
#         except Exception:
#             return ""

# def _load_dummy_html_plugin(self):
#         try:
#             from plugins.Dummy_HTML.app import load_dummy_assets
#             return load_dummy_assets() # 必要であればここにも引数を設定できます
#         except Exception as e:
#             print(f"Dummy_HTML plugin load error: {e}")
#             return None