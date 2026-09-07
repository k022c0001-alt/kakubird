# api/services/llm/ModelLoader.py

from __future__ import annotations

import os
import threading

from typing import Any, Optional

from .LLMConfig import LLMConfig


class ModelLoader:
    """
    ローカルLLMモデルのロードを担当。

    llama_cppはこのクラスの中だけで扱う。

    Modelを複数回読み込むとRAM/VRAMを大量消費するため、
    一度ロードしたインスタンスを保持する。
    """

    def __init__(
        self,
        config: LLMConfig,
    ) -> None:

        self.config = config

        self._model: Optional[Any] = None

        self._load_error: Optional[str] = None

        self._lock = threading.Lock()

    # ========================================================
    # Public
    # ========================================================

    def load(
        self,
    ) -> Any:

        if self._model is not None:
            return self._model

        with self._lock:

            if self._model is not None:
                return self._model

            self._validate_model()

            try:

                from llama_cpp import Llama

            except ImportError as exc:

                self._load_error = (
                    "llama-cpp-python が"
                    "インストールされていません。"
                )

                raise RuntimeError(
                    self._load_error
                ) from exc

            try:

                print(
                    "🧠 [ModelLoader] "
                    f"Loading local model: "
                    f"{self.config.model_path}",
                    flush=True,
                )

                self._model = Llama(
                    model_path=
                        self.config.model_path,

                    n_ctx=
                        self.config.context_length,

                    n_threads=
                        self.config.threads,

                    n_gpu_layers=
                        self.config.gpu_layers,

                    n_batch=
                        self.config.batch_size,

                    seed=
                        self.config.seed,

                    verbose=
                        self.config.verbose,
                )

                self._load_error = None

                print(
                    "✅ [ModelLoader] "
                    "Local model loaded.",
                    flush=True,
                )

                return self._model

            except Exception as exc:

                self._load_error = str(
                    exc
                )

                self._model = None

                raise RuntimeError(
                    "Local model load failed: "
                    f"{exc}"
                ) from exc

    # ========================================================
    # Status
    # ========================================================

    def is_loaded(
        self,
    ) -> bool:

        return (
            self._model
            is not None
        )

    def can_load(
        self,
    ) -> bool:

        return os.path.isfile(
            self.config.model_path
        )

    @property
    def error(
        self,
    ) -> Optional[str]:

        return self._load_error

    # ========================================================
    # Unload
    # ========================================================

    def unload(
        self,
    ) -> None:

        with self._lock:

            self._model = None

            print(
                "🧹 [ModelLoader] "
                "Model released.",
                flush=True,
            )

    # ========================================================
    # Validation
    # ========================================================

    def _validate_model(
        self,
    ) -> None:

        path = (
            self.config.model_path
        )

        if not path:
            raise ValueError(
                "model_path が設定されていません。"
            )

        if not os.path.isfile(
            path
        ):

            raise FileNotFoundError(
                "LocalLLMモデルが"
                "見つかりません: "
                f"{path}"
            )

        if not path.lower().endswith(
            ".gguf"
        ):

            raise ValueError(
                "現在のModelLoaderでは"
                "GGUFモデルを想定しています: "
                f"{path}"
            )