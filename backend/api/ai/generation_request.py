# -*- coding: utf-8 -*-
"""
generation_request.py

画像生成Providerへ渡すための中間データ。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any

from .generation_config import GenerationConfig


@dataclass
class GenerationCondition:
    """
    生成条件。

    image_path:
        元画像やControl画像など。

    weight:
        その条件をどれくらい重視するか。
    """

    name: str

    image_path: Optional[str] = None

    weight: float = 1.0

    data: Dict[str, Any] = field(default_factory=dict)

    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "image_path": self.image_path,
            "weight": self.weight,
            "data": self.data,
            "enabled": self.enabled,
        }


@dataclass
class GenerationRequest:
    """
    実際に画像生成Providerへ渡す要求。
    """

    config: GenerationConfig

    prompt: str

    negative_prompt: str

    conditions: Dict[str, GenerationCondition] = field(
        default_factory=dict
    )

    source_image: Optional[str] = None

    mask_image: Optional[str] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def add_condition(
        self,
        condition: GenerationCondition,
    ):
        self.conditions[condition.name] = condition

    def get_condition(
        self,
        name: str,
    ) -> Optional[GenerationCondition]:
        return self.conditions.get(name)

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "conditions": {
                key: value.to_dict()
                for key, value in self.conditions.items()
            },
            "source_image": self.source_image,
            "mask_image": self.mask_image,
            "metadata": self.metadata,
        }
