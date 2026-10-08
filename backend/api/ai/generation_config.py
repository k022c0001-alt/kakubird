# -*- coding: utf-8 -*-
"""
generation_config.py

画像生成に関する設定モデル。
「品質」を単純な1つの数値ではなく、
キャラクター・ポーズ・画風・顔・手などに分離して制御する。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class GenerationConfig:
    """
    画像生成設定。

    すべてのstrengthは0.0～1.0を基本とする。

    0.0 = AIによる変更を弱くする
    1.0 = AIによる制御を強くする
    """

    # -------------------------
    # 基本生成
    # -------------------------

    width: int = 1024
    height: int = 1024

    steps: int = 30

    guidance_scale: float = 7.0

    seed: Optional[int] = None

    # -------------------------
    # AI介入力
    # -------------------------

    denoise_strength: float = 0.45

    style_strength: float = 0.75

    character_strength: float = 0.90

    pose_strength: float = 0.85

    face_strength: float = 0.80

    hand_strength: float = 0.80

    color_strength: float = 0.70

    shading_strength: float = 0.60

    detail_strength: float = 0.70

    # -------------------------
    # Control系
    # -------------------------

    use_pose_control: bool = True

    use_depth_control: bool = False

    use_edge_control: bool = True

    use_face_control: bool = True

    use_hand_control: bool = True

    # -------------------------
    # Model / LoRA
    # -------------------------

    model_name: str = "local-default"

    lora_name: Optional[str] = None

    lora_strength: float = 0.75

    # -------------------------
    # Prompt
    # -------------------------

    prompt: str = ""

    negative_prompt: str = (
        "low quality, blurry, distorted body, "
        "bad anatomy, extra fingers, missing fingers, "
        "extra arms, extra legs, malformed hands"
    )

    # -------------------------
    # 拡張設定
    # -------------------------

    control_weights: Dict[str, float] = field(default_factory=dict)

    metadata: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        self.validate()

    def validate(self):
        """設定値を検証する。"""

        if self.width <= 0:
            raise ValueError("width must be greater than 0")

        if self.height <= 0:
            raise ValueError("height must be greater than 0")

        if self.steps <= 0:
            raise ValueError("steps must be greater than 0")

        self.denoise_strength = self._clamp(self.denoise_strength)
        self.style_strength = self._clamp(self.style_strength)
        self.character_strength = self._clamp(
            self.character_strength
        )
        self.pose_strength = self._clamp(self.pose_strength)
        self.face_strength = self._clamp(self.face_strength)
        self.hand_strength = self._clamp(self.hand_strength)
        self.color_strength = self._clamp(self.color_strength)
        self.shading_strength = self._clamp(
            self.shading_strength
        )
        self.detail_strength = self._clamp(
            self.detail_strength
        )
        self.lora_strength = self._clamp(
            self.lora_strength
        )

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def set_quality_profile(self, profile: str):
        """
        プリセット。

        注意:
        qualityという1つの数値でAIに全部任せるのではなく、
        実際には各strengthを変更する。
        """

        profile = profile.lower()

        if profile == "draft":
            self.steps = 15
            self.denoise_strength = 0.60
            self.style_strength = 0.55
            self.character_strength = 0.70
            self.pose_strength = 0.70
            self.face_strength = 0.60
            self.hand_strength = 0.60
            self.detail_strength = 0.45

        elif profile == "balanced":
            self.steps = 30
            self.denoise_strength = 0.45
            self.style_strength = 0.75
            self.character_strength = 0.90
            self.pose_strength = 0.85
            self.face_strength = 0.80
            self.hand_strength = 0.80
            self.detail_strength = 0.70

        elif profile == "final":
            self.steps = 45
            self.denoise_strength = 0.35
            self.style_strength = 0.90
            self.character_strength = 0.95
            self.pose_strength = 0.95
            self.face_strength = 0.90
            self.hand_strength = 0.90
            self.detail_strength = 0.90

        else:
            raise ValueError(
                f"Unknown quality profile: {profile}"
            )

        self.validate()

    def set_control_weight(
        self,
        name: str,
        weight: float,
    ):
        self.control_weights[name] = self._clamp(weight)

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "steps": self.steps,
            "guidance_scale": self.guidance_scale,
            "seed": self.seed,
            "denoise_strength": self.denoise_strength,
            "style_strength": self.style_strength,
            "character_strength": self.character_strength,
            "pose_strength": self.pose_strength,
            "face_strength": self.face_strength,
            "hand_strength": self.hand_strength,
            "color_strength": self.color_strength,
            "shading_strength": self.shading_strength,
            "detail_strength": self.detail_strength,
            "use_pose_control": self.use_pose_control,
            "use_depth_control": self.use_depth_control,
            "use_edge_control": self.use_edge_control,
            "use_face_control": self.use_face_control,
            "use_hand_control": self.use_hand_control,
            "model_name": self.model_name,
            "lora_name": self.lora_name,
            "lora_strength": self.lora_strength,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "control_weights": self.control_weights,
            "metadata": self.metadata,
        }
