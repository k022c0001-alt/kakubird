# -*- coding: utf-8 -*-
"""
inpainting.py
"""

from .generation_request import GenerationRequest
from .generation_result import GenerationResult
from .image_generation_provider import (
    ImageGenerationProvider,
)


class InpaintingGenerator:
    """
    指定領域だけを再生成する。
    """

    def __init__(
        self,
        provider: ImageGenerationProvider,
    ):
        self.provider = provider

    def generate(
        self,
        source_image: str,
        mask_image: str,
        request: GenerationRequest,
    ) -> GenerationResult:

        request.source_image = source_image
        request.mask_image = mask_image

        return self.provider.inpaint(
            request
        )
