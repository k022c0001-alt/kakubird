import math
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

DEFAULT_SCORE = 0
MAX_SCORE = 100
DEFAULT_HANDLER_NAME = "MathHandler"

def unpack_route_score(value: Any) -> Tuple[Any, Any]:
    if isinstance(value, tuple):
        if len(value) >= 2:
            return value[0], value[1]
        if len(value) == 1:
            return value[0], DEFAULT_SCORE
    if isinstance(value, Mapping):
        return (
            value.get("plugin"),
            value.get("score", DEFAULT_SCORE),
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None, value
    plugin = getattr(value, "plugin", None)
    score = getattr(value, "score", DEFAULT_SCORE)
    return plugin, score

def normalize_score(value: Any) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SCORE
    if not math.isfinite(numeric):
        return DEFAULT_SCORE
    return max(0, min(MAX_SCORE, int(round(numeric))))

def plugin_name(plugin: Any) -> Optional[str]:
    if plugin is None:
        return None
    if isinstance(plugin, str):
        return plugin
    for attribute in ("HANDLER_NAME", "PLUGIN_NAME", "name"):
        value = getattr(plugin, attribute, None)
        if value:
            return str(value)
    return type(plugin).__name__

def result_to_dict(result: Any) -> Dict[str, Any]:
    if result is None:
        return {
            "success": False,
            "error_code": "empty_plugin_result",
            "error_message": "計算プラグインから結果が返されませんでした。",
        }
    if isinstance(result, Mapping):
        return dict(result)
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        value = to_dict()
        if isinstance(value, Mapping):
            return dict(value)
        return {"success": True, "result": value}
    if is_dataclass(result) and not isinstance(result, type):
        return dict(asdict(result))
    if isinstance(result, (int, float)) and not isinstance(result, bool):
        return {"success": True, "result": result}
    return {"success": True, "result": str(result)}

def contains_error(data: Mapping[str, Any]) -> bool:
    if data.get("success") is False:
        return True
    return bool(
        data.get("error")
        or data.get("error_code")
        or data.get("error_message")
    )

def error_from_exception(
    exc: Exception,
    expression: str,
    handler_name: str = DEFAULT_HANDLER_NAME
) -> Dict[str, Any]:
    code = str(
        getattr(exc, "code", None)
        or getattr(exc, "error_code", None)
        or "math_execution_failed"
    )
    message = str(
        getattr(exc, "message", None)
        or getattr(exc, "error_message", None)
        or exc
        or "計算に失敗しました。"
    )
    return error_data(code, message, expression=expression, handler_name=handler_name)

def error_data(
    code: str,
    message: str,
    *,
    expression: str,
    handler_name: str = DEFAULT_HANDLER_NAME
) -> Dict[str, Any]:
    return {
        "success": False,
        "expression": expression,
        "error_code": str(code),
        "error_message": str(message),
        "metadata": {"handler": handler_name},
    }