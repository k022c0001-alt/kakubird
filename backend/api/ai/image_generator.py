# -*- coding: utf-8 -*-
"""
image_generator.py
"""

from .generation_request import GenerationRequest
from .generation_result import GenerationResult
from .image_generation_provider import (
    ImageGenerationProvider,
)


class ImageGenerator:
    """
    通常の画像生成を担当するFacade。
    """

    def __init__(
        self,
        provider: ImageGenerationProvider,
    ):
        self.provider = provider

    def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResult:

        return self.provider.generate(
            request
        )

    def health_check(self) -> bool:
        return self.provider.health_check()
