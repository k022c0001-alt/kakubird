import re
from typing import Any, Mapping, Optional

# extract.py から関数をインポート
from .extract import normalized_signal


# ``Pythonコード`` must not be captured by the deterministic calculator.
PYTHON_PATTERN = re.compile(
    r"(?:python|パイソン|\.py(?:\s|$)|\bpy\b)",
    re.IGNORECASE,
)
CODE_REQUEST_PATTERN = re.compile(
    r"(?:コード|プログラム|スクリプト|関数|実装|アルゴリズム|"
    r"書いて|生成|変換|code|program|script|function|implement|generate)",
    re.IGNORECASE,
)
PROJECT_PATTERN = re.compile(
    r"(?:Webアプリ|アプリケーション|アプリ|サイト|システム|プロジェクト|"
    r"ZIP|複数ファイル|フロントエンド|バックエンド|APIサーバー|"
    r"application|website|system|project|multi[\s\-]?file)",
    re.IGNORECASE,
)
PROJECT_ACTION_PATTERN = re.compile(
    r"(?:作って|構築|生成|実装|設計|build|create|generate|implement|design)",
    re.IGNORECASE,
)


def must_yield_to_another_handler(
    text: str,
    current_signals: Optional[Mapping[str, Any]],
) -> bool:
    """
    リクエスト内容が他の専用ハンドラで処理されるべきか（MathHandlerから処理を譲るべきか）を判定します。
    """
    signals = dict(current_signals or {})
    selected = normalized_signal(
        signals.get("forced_handler")
        or signals.get("selected_handler")
        or signals.get("handler_name")
    )
    route = normalized_signal(
        signals.get("route_name")
        or signals.get("intent_route")
        or signals.get("mode")
    )

    # 強制指定されたハンドラがあるが、それがMathHandler系ではない場合
    if selected and selected not in {"mathhandler", "math_handler", "math"}:
        return True

    # 意図（route）がPythonコード生成やプロジェクト作成に向いている場合
    if route in {
        "python_code",
        "python_snippet",
        "math_to_python",
        "project_builder",
        "project_generation",
        "project_structure",
    }:
        return True

    # 本文の正規表現マッチングによる判定
    if PYTHON_PATTERN.search(text) and CODE_REQUEST_PATTERN.search(text):
        return True
    if PROJECT_PATTERN.search(text) and PROJECT_ACTION_PATTERN.search(text):
        return True

    return False


def recommended_handler(text: str) -> str:
    """
    must_yield_to_another_handler が True になった場合に、代わりに推奨されるハンドラ名を返します。
    """
    if PYTHON_PATTERN.search(text) and CODE_REQUEST_PATTERN.search(text):
        return "PythonCodeHandler"
    if PROJECT_PATTERN.search(text):
        return "ProjectBuilderHandler"
    return "ChatHandler"