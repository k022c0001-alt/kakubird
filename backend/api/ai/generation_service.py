# -*- coding: utf-8 -*-
"""
generation_service.py

Character / Body / Pose / Face / Hand / Style
から画像生成Requestを構築する。
"""

from typing import Optional

from .generation_config import GenerationConfig
from .generation_request import (
    GenerationRequest,
    GenerationCondition,
)
from .generation_result import GenerationResult
from .image_generator import ImageGenerator

from ..models.character_model import CharacterModel
from ..models.pose_model import PoseModel
from ..models.face_model import FaceModel
from ..models.hand_model import HandModel
from ..models.style_model import StyleModel
from ..models.body_model import BodyModel


class GenerationService:

    def __init__(
        self,
        image_generator: ImageGenerator,
    ):
        self.image_generator = image_generator

    def generate_character(
        self,
        character: CharacterModel,
        pose: Optional[PoseModel] = None,
        face: Optional[FaceModel] = None,
        hand: Optional[HandModel] = None,
        body: Optional[BodyModel] = None,
        style: Optional[StyleModel] = None,
        config: Optional[GenerationConfig] = None,
        source_image: Optional[str] = None,
    ) -> GenerationResult:

        if config is None:
            config = GenerationConfig()

        prompt = self._build_prompt(
            character=character,
            pose=pose,
            face=face,
            hand=hand,
            body=body,
            style=style,
            config=config,
        )

        request = GenerationRequest(
            config=config,
            prompt=prompt,
            negative_prompt=config.negative_prompt,
            source_image=source_image,
        )

        self._add_character_condition(
            request,
            character,
            config,
        )

        if pose is not None:
            self._add_pose_condition(
                request,
                pose,
                config,
            )

        if face is not None:
            self._add_face_condition(
                request,
                face,
                config,
            )

        if hand is not None:
            self._add_hand_condition(
                request,
                hand,
                config,
            )

        if body is not None:
            self._add_body_condition(
                request,
                body,
            )

        if style is not None:
            self._add_style_condition(
                request,
                style,
                config,
            )

        return self.image_generator.generate(
            request
        )

    def _build_prompt(
        self,
        character,
        pose,
        face,
        hand,
        body,
        style,
        config,
    ) -> str:

        parts = []

        if character.name:
            parts.append(
                f"character named {character.name}"
            )

        appearance = character.appearance

        if appearance is not None:

            if appearance.hair_color:
                parts.append(
                    f"{appearance.hair_color} hair"
                )

            if appearance.eye_color:
                parts.append(
                    f"{appearance.eye_color} eyes"
                )

            if appearance.clothing:
                parts.append(
                    f"wearing {appearance.clothing}"
                )

            if appearance.accessories:
                parts.append(
                    appearance.accessories
                )

            if appearance.description:
                parts.append(
                    appearance.description
                )

        if pose is not None:
            parts.append(
                f"pose: {pose.name}"
            )

            if pose.description:
                parts.append(
                    pose.description
                )

        if face is not None:
            parts.append(
                f"expression: {face.expression}"
            )

        if style is not None:
            parts.append(
                f"art style: {style.name}"
            )

        parts.append(
            f"detail level {config.detail_strength:.2f}"
        )

        return ", ".join(parts)

    def _add_character_condition(
        self,
        request: GenerationRequest,
        character: CharacterModel,
        config: GenerationConfig,
    ):

        reference_images = (
            character.reference_images
        )

        if not reference_images:
            return

        request.add_condition(
            GenerationCondition(
                name="character_reference",
                image_path=reference_images[0],
                weight=config.character_strength,
                data={
                    "style_id": character.style_id,
                    "character_id": character.character_id,
                },
            )
        )

    def _add_pose_condition(
        self,
        request: GenerationRequest,
        pose: PoseModel,
        config: GenerationConfig,
    ):

        request.add_condition(
            GenerationCondition(
                name="pose",
                weight=config.pose_strength,
                data={
                    "pose_id": pose.pose_id,
                    "joints": {
                        name: joint.to_dict()
                        for name, joint
                        in pose.joints.items()
                    },
                },
            )
        )

    def _add_face_condition(
        self,
        request: GenerationRequest,
        face: FaceModel,
        config: GenerationConfig,
    ):

        request.add_condition(
            GenerationCondition(
                name="face",
                weight=config.face_strength,
                data=face.to_dict(),
            )
        )

    def _add_hand_condition(
        self,
        request: GenerationRequest,
        hand: HandModel,
        config: GenerationConfig,
    ):

        request.add_condition(
            GenerationCondition(
                name="hand",
                weight=config.hand_strength,
                data=hand.to_dict(),
            )
        )

    def _add_body_condition(
        self,
        request: GenerationRequest,
        body: BodyModel,
    ):

        request.add_condition(
            GenerationCondition(
                name="body",
                weight=1.0,
                data=body.to_dict(),
            )
        )

    def _add_style_condition(
        self,
        request: GenerationRequest,
        style: StyleModel,
        config: GenerationConfig,
    ):

        reference_image = None

        if style.reference_images:
            reference_image = (
                style.reference_images[0]
            )

        request.add_condition(
            GenerationCondition(
                name="style",
                image_path=reference_image,
                weight=config.style_strength,
                data={
                    "style_id": style.style_id,
                    "model_name": style.model_name,
                    "lora_name": style.lora_name,
                    "lora_strength": (
                        style.lora_strength
                        if hasattr(
                            style,
                            "lora_strength",
                        )
                        else config.lora_strength
                    ),
                    "line_weight": style.line_weight,
                    "color_strength": (
                        style.color_strength
                    ),
                    "shading_strength": (
                        style.shading_strength
                    ),
                },
            )
        )
