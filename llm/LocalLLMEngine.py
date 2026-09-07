# api/services/llm/LocalLLMEngine.py

from __future__ import annotations

import threading

from typing import Any, Dict, List, Optional

from .BaseLLMEngine import BaseLLMEngine
from .GenerationResult import GenerationResult
from .LLMConfig import LLMConfig
from .ModelLoader import ModelLoader


class LocalLLMEngine(
    BaseLLMEngine
):
    """
    ローカルGGUFモデルを直接利用するLLMEngine。

    Gemini API
    Anthropic API
    OpenAI API
    Ollama

    は使用しない。

    llama-cpp-python経由で
    ローカルモデルを直接推論する。
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        config_path: Optional[str] = None,
    ) -> None:

        # ----------------------------------------------------
        # Config
        # ----------------------------------------------------

        if config is not None:

            self.config = config

        elif config_path:

            self.config = (
                LLMConfig.from_json_file(
                    config_path
                )
            )

        else:

            self.config = (
                LLMConfig()
            )

        # ----------------------------------------------------
        # Loader
        # ----------------------------------------------------

        self.loader = ModelLoader(
            self.config
        )

        # 同時生成防止
        self._generation_lock = (
            threading.Lock()
        )

    # ========================================================
    # Availability
    # ========================================================

    def is_available(
        self,
    ) -> bool:

        if self.loader.is_loaded():
            return True

        return self.loader.can_load()

    # ========================================================
    # Lazy Load
    # ========================================================

    def _get_model(
        self,
    ):

        return self.loader.load()

    # ========================================================
    # Normal Generate
    # ========================================================

    def generate(
        self,
        prompt: str,
        **kwargs,
    ) -> GenerationResult:

        if not isinstance(
            prompt,
            str,
        ):

            prompt = str(
                prompt
            )

        prompt = prompt.strip()

        if not prompt:

            return GenerationResult.fail(
                "prompt が空です。"
            )

        try:

            model = (
                self._get_model()
            )

        except Exception as exc:

            return GenerationResult.fail(
                str(exc)
            )

        max_tokens = int(
            kwargs.get(
                "max_tokens",
                self.config.max_tokens,
            )
        )

        temperature = float(
            kwargs.get(
                "temperature",
                self.config.temperature,
            )
        )

        top_p = float(
            kwargs.get(
                "top_p",
                self.config.top_p,
            )
        )

        top_k = int(
            kwargs.get(
                "top_k",
                self.config.top_k,
            )
        )

        repeat_penalty = float(
            kwargs.get(
                "repeat_penalty",
                self.config.repeat_penalty,
            )
        )

        stop = kwargs.get(
            "stop",
            None,
        )

        try:

            with self._generation_lock:

                result = (
                    model.create_completion(
                        prompt=prompt,

                        max_tokens=
                            max_tokens,

                        temperature=
                            temperature,

                        top_p=
                            top_p,

                        top_k=
                            top_k,

                        repeat_penalty=
                            repeat_penalty,

                        stop=
                            stop,

                        stream=False,
                    )
                )

            return self._parse_completion(
                result
            )

        except Exception as exc:

            return GenerationResult.fail(
                "LocalLLM generate failed: "
                f"{exc}"
            )

    # ========================================================
    # Chat Generate
    # ========================================================

    def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> GenerationResult:

        if not messages:

            return GenerationResult.fail(
                "messages が空です。"
            )

        normalized_messages = []

        for message in messages:

            if not isinstance(
                message,
                dict,
            ):
                continue

            role = str(
                message.get(
                    "role",
                    "user",
                )
            )

            content = str(
                message.get(
                    "content",
                    "",
                )
            ).strip()

            if not content:
                continue

            if role not in (
                "system",
                "user",
                "assistant",
            ):

                role = "user"

            normalized_messages.append(
                {
                    "role": role,
                    "content": content,
                }
            )

        if not normalized_messages:

            return GenerationResult.fail(
                "有効なmessageがありません。"
            )

        try:

            model = (
                self._get_model()
            )

        except Exception as exc:

            return GenerationResult.fail(
                str(exc)
            )

        try:

            with self._generation_lock:

                result = (
                    model.create_chat_completion(
                        messages=
                            normalized_messages,

                        max_tokens=
                            int(
                                kwargs.get(
                                    "max_tokens",
                                    self.config.max_tokens,
                                )
                            ),

                        temperature=
                            float(
                                kwargs.get(
                                    "temperature",
                                    self.config.temperature,
                                )
                            ),

                        top_p=
                            float(
                                kwargs.get(
                                    "top_p",
                                    self.config.top_p,
                                )
                            ),

                        top_k=
                            int(
                                kwargs.get(
                                    "top_k",
                                    self.config.top_k,
                                )
                            ),

                        repeat_penalty=
                            float(
                                kwargs.get(
                                    "repeat_penalty",
                                    self.config.repeat_penalty,
                                )
                            ),

                        stream=False,
                    )
                )

            return self._parse_chat_completion(
                result
            )

        except Exception as exc:

            return GenerationResult.fail(
                "LocalLLM chat failed: "
                f"{exc}"
            )

    # ========================================================
    # Completion Parser
    # ========================================================

    def _parse_completion(
        self,
        result: Dict[str, Any],
    ) -> GenerationResult:

        try:

            choices = result.get(
                "choices",
                []
            )

            if not choices:

                return GenerationResult.fail(
                    "LLMのchoicesが空です。"
                )

            choice = choices[0]

            text = str(
                choice.get(
                    "text",
                    "",
                )
            ).strip()

            usage = result.get(
                "usage",
                {}
            )

            return GenerationResult.ok(
                text=text,

                finish_reason=
                    choice.get(
                        "finish_reason"
                    ),

                model_name=
                    self.config.model_name,

                prompt_tokens=
                    int(
                        usage.get(
                            "prompt_tokens",
                            0,
                        )
                    ),

                completion_tokens=
                    int(
                        usage.get(
                            "completion_tokens",
                            0,
                        )
                    ),

                total_tokens=
                    int(
                        usage.get(
                            "total_tokens",
                            0,
                        )
                    ),

                raw=result,
            )

        except Exception as exc:

            return GenerationResult.fail(
                "Completion parse failed: "
                f"{exc}"
            )

    # ========================================================
    # Chat Parser
    # ========================================================

    def _parse_chat_completion(
        self,
        result: Dict[str, Any],
    ) -> GenerationResult:

        try:

            choices = result.get(
                "choices",
                []
            )

            if not choices:

                return GenerationResult.fail(
                    "Chat choicesが空です。"
                )

            choice = choices[0]

            message = choice.get(
                "message",
                {}
            )

            text = str(
                message.get(
                    "content",
                    "",
                )
            ).strip()

            usage = result.get(
                "usage",
                {}
            )

            return GenerationResult.ok(
                text=text,

                finish_reason=
                    choice.get(
                        "finish_reason"
                    ),

                model_name=
                    self.config.model_name,

                prompt_tokens=
                    int(
                        usage.get(
                            "prompt_tokens",
                            0,
                        )
                    ),

                completion_tokens=
                    int(
                        usage.get(
                            "completion_tokens",
                            0,
                        )
                    ),

                total_tokens=
                    int(
                        usage.get(
                            "total_tokens",
                            0,
                        )
                    ),

                raw=result,
            )

        except Exception as exc:

            return GenerationResult.fail(
                "Chat completion parse failed: "
                f"{exc}"
            )

    # ========================================================
    # Health
    # ========================================================

    def health(
        self,
    ) -> Dict[str, Any]:

        return {
            "engine":
                "local_llm",

            "backend":
                "llama_cpp",

            "available":
                self.is_available(),

            "loaded":
                self.loader.is_loaded(),

            "model_name":
                self.config.model_name,

            "model_path":
                self.config.model_path,

            "context_length":
                self.config.context_length,

            "gpu_layers":
                self.config.gpu_layers,

            "error":
                self.loader.error,
        }

    # ========================================================
    # Unload
    # ========================================================

    def unload(
        self,
    ) -> None:

        self.loader.unload()