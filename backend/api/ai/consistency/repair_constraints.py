。

### `ai/consistency/repair_constraints.py`

```python
# -*- coding: utf-8 -*-
"""画像修正時の維持条件を定義する。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RepairConstraints:
    """修正時に維持すべき特徴と変更可能な範囲。"""

    category: str

    # 維持する特徴
    preserve_character_identity: bool = True
    preserve_face: bool = True
    preserve_hairstyle: bool = True
    preserve_clothing: bool = True
    preserve_color_palette: bool = True
    preserve_art_style: bool = True

    # 修正対象以外を変えないための設定
    preserve_unmasked_regions: bool = True

    # 画像全体を変更してよいか
    allow_global_changes: bool = False

    # 修正強度の上限
    max_denoise_strength: float = 0.45

    # 検証用の最低スコア
    minimum_consistency_score: float = 0.80

    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """制約設定を検証する。"""

        if not self.category.strip():
            raise ValueError("categoryは必須です。")

        if not 0.0 <= self.max_denoise_strength <= 1.0:
            raise ValueError(
                "max_denoise_strengthは0～1の範囲で指定してください。"
            )

        if not 0.0 <= self.minimum_consistency_score <= 1.0:
            raise ValueError(
                "minimum_consistency_scoreは0～1の範囲で指定してください。"
            )

        # 部分修正のつもりなのに画像全体を変更する設定を防ぐ。
        if (
            self.preserve_unmasked_regions
            and self.allow_global_changes
        ):
            raise ValueError(
                "未修正領域の維持と画像全体の変更は、"
                "同じ設定では両立できません。"
            )

    def to_dict(self) -> dict[str, Any]:
        """設定を辞書形式に変換する。"""
        return {
            "category": self.category,
            "preserve_character_identity": (
                self.preserve_character_identity
            ),
            "preserve_face": self.preserve_face,
            "preserve_hairstyle": self.preserve_hairstyle,
            "preserve_clothing": self.preserve_clothing,
            "preserve_color_palette": self.preserve_color_palette,
            "preserve_art_style": self.preserve_art_style,
            "preserve_unmasked_regions": (
                self.preserve_unmasked_regions
            ),
            "allow_global_changes": self.allow_global_changes,
            "max_denoise_strength": self.max_denoise_strength,
            "minimum_consistency_score": (
                self.minimum_consistency_score
            ),
            "metadata": self.metadata,
        }
