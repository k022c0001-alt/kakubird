# -*- coding: utf-8 -*-
"""
generation_result.py
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class GenerationResult:
    """
    画像生成結果。
    """

    success: bool

    image_path: Optional[str] = None

    seed: Optional[int] = None

    model_name: Optional[str] = None

    message: str = ""

    errors: list[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def add_error(self, message: str):
        self.errors.append(message)
        self.success = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "image_path": self.image_path,
            "seed": self.seed,
            "model_name": self.model_name,
            "message": self.message,
            "errors": self.errors,
            "metadata": self.metadata,
        }
