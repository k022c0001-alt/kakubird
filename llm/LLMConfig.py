# api/services/llm/LLMConfig.py

from __future__ import annotations

import json
import os

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


@dataclass
class LLMConfig:
    """
    LocalLLMの設定。

    APIキーは不要。
    ローカルGGUFファイルを指定する。
    """

    model_path: str = "models/chat.gguf"

    model_name: str = "local-model"

    # Context window
    context_length: int = 4096

    # 最大生成Token
    max_tokens: int = 512

    # 生成設定
    temperature: float = 0.7

    top_p: float = 0.9

    top_k: int = 40

    repeat_penalty: float = 1.1

    # CPU thread
    threads: Optional[int] = None

    # GPUへ何layer送るか
    #
    # 0:
    # CPUのみ
    #
    # -1:
    # 可能なら全layer GPU
    #
    gpu_layers: int = 0

    # Batch size
    batch_size: int = 512

    # Seed
    seed: int = -1

    # Debug
    verbose: bool = False

    def __post_init__(self) -> None:

        if self.context_length <= 0:
            self.context_length = 4096

        if self.max_tokens <= 0:
            self.max_tokens = 512

        self.temperature = max(
            0.0,
            min(
                float(self.temperature),
                2.0,
            ),
        )

        self.top_p = max(
            0.0,
            min(
                float(self.top_p),
                1.0,
            ),
        )

        if self.threads is None:

            cpu_count = (
                os.cpu_count()
                or 4
            )

            self.threads = max(
                1,
                cpu_count - 1,
            )

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
    ) -> "LLMConfig":

        allowed = {
            field_name
            for field_name in cls.__dataclass_fields__
        }

        filtered = {
            key: value
            for key, value in data.items()
            if key in allowed
        }

        return cls(
            **filtered
        )

    @classmethod
    def from_json_file(
        cls,
        path: str,
    ) -> "LLMConfig":

        if not os.path.exists(path):

            return cls()

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if not isinstance(
            data,
            dict,
        ):
            return cls()

        return cls.from_dict(
            data
        )

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return asdict(
            self
        )

    def model_exists(
        self,
    ) -> bool:

        return os.path.isfile(
            self.model_path
        )