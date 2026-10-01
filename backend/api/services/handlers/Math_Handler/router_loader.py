import asyncio
import importlib
import inspect
import logging
from typing import Any, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


class MathHandlerConfigurationError(RuntimeError):
    """Raised when the math plugin package cannot be loaded."""


# Import candidates allow the project to migrate from the old
# ``plugins/math`` or ``Math`` package into the recommended
# ``api/services/math/plugins`` package without changing this handler.
ROUTER_IMPORT_CANDIDATES: Sequence[Tuple[str, str]] = (
    (
        "api.services.math.plugins.MathPluginRouter",
        "api.services.math.plugins.BasicMathPlugin",
    ),
    (
        "api.services.math.MathPluginRouter",
        "api.services.math.plugins.BasicMathPlugin",
    ),
    (
        "api.services.plugins.math.MathPluginRouter",
        "api.services.plugins.math.BasicMathPlugin",
    ),
    (
        "plugins.math.MathPluginRouter",
        "plugins.math.BasicMathPlugin",
    ),
    (
        "Math.MathPluginRouter",
        "Math.BasicMathPlugin",
    ),
)


def build_default_router(plugins: Optional[Sequence[Any]] = None) -> Any:
    """
    インポート候補のリストから有効なパスを探し出し、MathPluginRouter をロードしてインスタンス化します。
    """
    errors = []
    for router_module_name, basic_module_name in ROUTER_IMPORT_CANDIDATES:
        try:
            router_module = importlib.import_module(router_module_name)
            basic_module = importlib.import_module(basic_module_name)
            
            router_class = getattr(router_module, "MathPluginRouter")
            basic_class = getattr(basic_module, "BasicMathPlugin")
            
            configured_plugins = list(plugins) if plugins is not None else [basic_class()]
            return router_class(configured_plugins)
            
        except ModuleNotFoundError as exc:
            # Continue only when the requested candidate package itself is missing.
            # A missing dependency inside an existing plugin is a real error.
            if exc.name and not (
                router_module_name.startswith(exc.name)
                or basic_module_name.startswith(exc.name)
            ):
                raise MathHandlerConfigurationError(
                    f"Math plugin dependency is missing: {exc.name}"
                ) from exc
            errors.append(f"{router_module_name}: {exc}")
        except (AttributeError, TypeError) as exc:
            errors.append(f"{router_module_name}: {exc}")

    expected = ", ".join(item[0] for item in ROUTER_IMPORT_CANDIDATES)
    detail = "; ".join(errors[-3:])
    raise MathHandlerConfigurationError(
        "MathPluginRouter / BasicMathPluginを読み込めません。"
        f"候補module: {expected}. 詳細: {detail}"
    )


async def call_router_method(router: Any, method_name: str, *args: Any) -> Any:
    """
    指定されたルーターインスタンスのメソッドを安全に呼び出します。
    同期関数だった場合は、イベントループをブロックしないよう別スレッドに委譲します。
    """
    method = getattr(router, method_name, None)
    if not callable(method):
        raise MathHandlerConfigurationError(
            f"MathPluginRouterに{method_name}()がありません。"
        )

    if inspect.iscoroutinefunction(method):
        return await method(*args)

    # A synchronous plugin may perform CPU work; keep it off the API event loop.
    # If a legacy sync wrapper returns an awaitable, await it too.
    value = await asyncio.to_thread(method, *args)
    if inspect.isawaitable(value):
        value = await value
    return value