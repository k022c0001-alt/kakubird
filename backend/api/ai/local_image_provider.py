# -*- coding: utf-8 -*-
"""
local_image_provider.py

ローカル画像生成エンジン用Provider。

実際のDiffusion/ComfyUI/Diffusers等との接続部分は
このクラスに閉じ込める。
"""

from pathlib import Path
from typing import Callable, Optional

from .generation_request import GenerationRequest
from .generation_result import GenerationResult
from .image_generation_provider import (
    ImageGenerationProvider,
)


class LocalImageProvider(ImageGenerationProvider):
    """
    ローカル画像生成エンジンを利用するProvider。

    generate_functionなどを外から注入できるため、
    特定ライブラリへの依存を避けられる。
    """

    def __init__(
        self,
        output_directory: str = "storage/generated",
        generate_function: Optional[
            Callable
        ] = None,
        img2img_function: Optional[
            Callable
        ] = None,
        inpaint_function: Optional[
            Callable
        ] = None,
    ):
        self.output_directory = Path(
            output_directory
        )

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.generate_function = generate_function
        self.img2img_function = img2img_function
        self.inpaint_function = inpaint_function

    def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResult:

        if self.generate_function is None:
            return GenerationResult(
                success=False,
                message=(
                    "Local image generation engine "
                    "is not connected."
                ),
                errors=[
                    "generate_function is None"
                ],
            )

        try:
            result = self.generate_function(
                request
            )

            return self._normalize_result(
                result,
                request,
            )

        except Exception as exc:
            return GenerationResult(
                success=False,
                message="Local generation failed.",
                errors=[str(exc)],
            )

    def image_to_image(
        self,
        request: GenerationRequest,
    ) -> GenerationResult:

        if self.img2img_function is None:
            return GenerationResult(
                success=False,
                message=(
                    "Image-to-image engine "
                    "is not connected."
                ),
                errors=[
                    "img2img_function is None"
                ],
            )

        try:
            result = self.img2img_function(
                request
            )

            return self._normalize_result(
                result,
                request,
            )

        except Exception as exc:
            return GenerationResult(
                success=False,
                message="Image-to-image failed.",
                errors=[str(exc)],
            )

    def inpaint(
        self,
        request: GenerationRequest,
    ) -> GenerationResult:

        if self.inpaint_function is None:
            return GenerationResult(
                success=False,
                message=(
                    "Inpainting engine "
                    "is not connected."
                ),
                errors=[
                    "inpaint_function is None"
                ],
            )

        try:
            result = self.inpaint_function(
                request
            )

            return self._normalize_result(
                result,
                request,
            )

        except Exception as exc:
            return GenerationResult(
                success=False,
                message="Inpainting failed.",
                errors=[str(exc)],
            )

    def _normalize_result(
        self,
        result,
        request: GenerationRequest,
    ) -> GenerationResult:

        if isinstance(
            result,
            GenerationResult,
        ):
            return result

        if isinstance(result, str):
            return GenerationResult(
                success=True,
                image_path=result,
                seed=request.config.seed,
                model_name=(
                    request.config.model_name
                ),
                message="Generation completed.",
            )

        if isinstance(result, dict):

            return GenerationResult(
                success=result.get(
                    "success",
                    True,
                ),
                image_path=result.get(
                    "image_path"
                ),
                seed=result.get(
                    "seed",
                    request.config.seed,
                ),
                model_name=result.get(
                    "model_name",
                    request.config.model_name,
                ),
                message=result.get(
                    "message",
                    "Generation completed.",
                ),
                errors=result.get(
                    "errors",
                    [],
                ),
                metadata=result.get(
                    "metadata",
                    {},
                ),
            )

        return GenerationResult(
            success=False,
            message="Unknown generation result.",
            errors=[
                "Provider returned unsupported result."
            ],
        )

    def health_check(self) -> bool:
        return (
            self.generate_function is not None
            or self.img2img_function is not None
            or self.inpaint_function is not None
        )
