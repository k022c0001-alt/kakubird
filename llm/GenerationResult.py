# api/services/llm/GenerationResult.py

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class GenerationResult:
    """
    LocalLLMEngineの共通返却形式。

    ChatHandlerやProjectGenerator側は
    llama.cppなどの内部実装を意識せず、
    このオブジェクトだけ扱う。
    """

    success: bool

    text: str = ""

    finish_reason: Optional[str] = None

    model_name: Optional[str] = None

    prompt_tokens: int = 0

    completion_tokens: int = 0

    total_tokens: int = 0

    error: Optional[str] = None

    raw: Optional[Dict[str, Any]] = field(
        default=None,
        repr=False,
    )

    @classmethod
    def ok(
        cls,
        text: str,
        *,
        finish_reason: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        raw: Optional[Dict[str, Any]] = None,
    ) -> "GenerationResult":

        return cls(
            success=True,
            text=text,
            finish_reason=finish_reason,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw=raw,
        )

    @classmethod
    def fail(
        cls,
        error: str,
    ) -> "GenerationResult":

        return cls(
            success=False,
            text="",
            error=error,
        )

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)

        # rawは巨大になる可能性があるので、
        # Frontendへ通常送らない。
        data.pop(
            "raw",
            None,
        )

        return data