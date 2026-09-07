# api/services/llm/BaseLLMEngine.py

from __future__ import annotations

from abc import ABC, abstractmethod

from typing import Any, Dict, List, Optional

from .GenerationResult import GenerationResult


class BaseLLMEngine(ABC):
    """
    全LLMEngine共通インターフェース。

    ChatHandler / ProjectGenerator側は
    LocalLLMEngineの実装詳細を知らない。
    """

    @abstractmethod
    def is_available(
        self,
    ) -> bool:
        """
        モデルが利用可能か。
        """
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> GenerationResult:
        """
        通常のPrompt生成。
        """
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> GenerationResult:
        """
        Chat形式生成。
        """
        raise NotImplementedError

    def health(
        self,
    ) -> Dict[str, Any]:

        return {
            "available":
                self.is_available(),

            "engine":
                self.__class__.__name__,
        }