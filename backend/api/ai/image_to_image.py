# -*- coding: utf-8 -*-
"""
image_to_image.py
"""

from .generation_request import GenerationRequest
from .generation_result import GenerationResult
from .image_generation_provider import (
    ImageGenerationProvider,
)


class ImageToImageGenerator:
    """
    ユーザー画像をベースに画像を再生成する。
    """

    def __init__(
        self,
        provider: ImageGenerationProvider,
    ):
        self.provider = provider

    def generate(
        self,
        source_image: str,
        request: GenerationRequest,
    ) -> GenerationResult:

        request.source_image = source_image

        return self.provider.image_to_image(
            request
        )
