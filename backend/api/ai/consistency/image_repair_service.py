# ai/consistency/image_repair_service.py

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

from ai.image.generation_config import GenerationConfig
from ai.image.generation_request import GenerationRequest
from ai.image.generation_result import GenerationResult

from ai.consistency.repair_request import RepairRequest, RepairTarget

logger = logging.getLogger(__name__)


class ImageRepairService:
    """
    画像の一貫性チェック結果に基づいて画像を修正するサービス。

    対応方式:
        - inpaint: マスク領域を中心に修正
        - img2img: 元画像を参考に画像を再生成

    注意:
        実際の画像生成は、注入された Generator が担当する。
        このクラス自体は画像生成モデルをロードしない。
    """

    SUPPORTED_METHODS = {"inpaint", "img2img"}

    CATEGORY_PROMPTS = {
        "character": (
            "Preserve the identity of the original character. "
            "Maintain the same hairstyle, hair color, eye color, "
            "clothing, accessories, and body proportions. "
            "Change only what is necessary to correct the inconsistency."
        ),
        "face": (
            "Correct the facial features while preserving the character's "
            "identity, age appearance, hairstyle, and artistic style. "
            "Keep the expression and gaze consistent with the instructions."
        ),
        "pose": (
            "Correct the character's body pose while preserving identity, "
            "clothing, proportions, and artistic style. "
            "Keep the intended action and direction of movement."
        ),
        "hands": (
            "Correct the hands and fingers. Preserve the original character, "
            "pose, clothing, lighting, and art style. "
            "Avoid extra fingers, missing fingers, and fused fingers."
        ),
        "style": (
            "Bring the image closer to the reference artistic style. "
            "Preserve the character identity, composition, pose, and clothing."
        ),
    }

    def __init__(
        self,
        inpainting_generator: Any,
        region_detector: Any,
        output_directory: str = "storage/repaired",
        image_to_image_generator: Any = None,
    ) -> None:
        """
        Args:
            inpainting_generator:
                InpaintingGenerator のインスタンス。

            region_detector:
                RegionDetectionProvider のインスタンス。

            output_directory:
                修正結果を保存するディレクトリ。
                実際の出力先は Generator 側の実装にも依存する。

            image_to_image_generator:
                ImageToImageGenerator のインスタンス。
                None の場合、img2img 修正は実行できない。
        """
        self.inpainting_generator = inpainting_generator
        self.image_to_image_generator = image_to_image_generator
        self.region_detector = region_detector

        self.output_directory = Path(output_directory)
        self.output_directory.mkdir(parents=True, exist_ok=True)

    def repair(
        self,
        request: RepairRequest,
        base_config: Optional[GenerationConfig] = None,
    ) -> dict[str, Any]:
        """
        RepairRequest に基づいて順番に修正する。

        戻り値の基本形式:
        {
            "success": bool,
            "all_success": bool,
            "original_image": str,
            "final_image": str,
            "results": list,
            "errors": list
        }

        success:
            1つ以上の修正が成功したか。

        all_success:
            要求されたすべての修正が成功したか。
        """
        original_image = request.source_image

        if not original_image:
            return self._failure(
                original_image="",
                error="修正元画像が指定されていません。",
            )

        if not Path(original_image).is_file():
            return self._failure(
                original_image=original_image,
                error=f"修正元画像が存在しません: {original_image}",
            )

        if not request.targets:
            return {
                "success": False,
                "all_success": False,
                "original_image": original_image,
                "final_image": original_image,
                "results": [],
                "errors": ["修正対象がありません。"],
            }

        config = base_config or GenerationConfig()

        current_image = original_image
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        successful_repairs = 0

        for index, target in enumerate(request.targets, start=1):
            try:
                result = self._repair_one(
                    source_image=current_image,
                    target=target,
                    request=request,
                    base_config=config,
                    index=index,
                )

                results.append(result)

                if result["success"]:
                    repaired_path = result.get("image_path")

                    if not repaired_path or not Path(repaired_path).is_file():
                        error = (
                            f"{target.category}: Generator は成功を返しましたが、"
                            "修正後の画像ファイルを確認できません。"
                        )
                        result["success"] = False
                        result["error"] = error
                        errors.append(error)
                        continue

                    current_image = repaired_path
                    successful_repairs += 1

                else:
                    errors.append(
                        result.get("error", f"{target.category}: 修正に失敗しました。")
                    )

            except Exception as exc:
                logger.exception(
                    "画像修正中に例外が発生しました: category=%s",
                    target.category,
                )

                error = f"{target.category}: {type(exc).__name__}: {exc}"

                results.append(
                    {
                        "success": False,
                        "category": target.category,
                        "method": target.method,
                        "image_path": None,
                        "error": error,
                    }
                )
                errors.append(error)

        return {
            "success": successful_repairs > 0,
            "all_success": (
                successful_repairs == len(request.targets)
                and len(request.targets) > 0
            ),
            "original_image": original_image,
            "final_image": current_image,
            "results": results,
            "errors": errors,
            "successful_repairs": successful_repairs,
            "requested_repairs": len(request.targets),
        }

    def _repair_one(
        self,
        source_image: str,
        target: RepairTarget,
        request: RepairRequest,
        base_config: GenerationConfig,
        index: int,
    ) -> dict[str, Any]:
        method = (target.method or "").strip().lower()

        if method not in self.SUPPORTED_METHODS:
            return self._target_failure(
                target,
                f"未対応の修正方式です: {method}",
            )

        if method == "inpaint":
            return self._repair_inpaint(
                source_image=source_image,
                target=target,
                request=request,
                base_config=base_config,
                index=index,
            )

        if method == "img2img":
            return self._repair_img2img(
                source_image=source_image,
                target=target,
                request=request,
                base_config=base_config,
                index=index,
            )

        return self._target_failure(target, "修正方式を判定できません。")

    def _repair_inpaint(
        self,
        source_image: str,
        target: RepairTarget,
        request: RepairRequest,
        base_config: GenerationConfig,
        index: int,
    ) -> dict[str, Any]:
        if self.inpainting_generator is None:
            return self._target_failure(
                target,
                "InpaintingGenerator が接続されていません。",
            )

        mask_path = target.mask_path

        # 明示的なマスクがなければ領域検出器に依頼する。
        if not mask_path and self.region_detector is not None:
            detected = self.region_detector.detect(
                source_image,
                target.category,
            )

            if detected is not None:
                mask_path = getattr(detected, "mask_path", None)

        if not mask_path:
            return self._target_failure(
                target,
                (
                    f"{target.category}: 修正マスクがありません。"
                    "RegionDetectionProvider を実装するか、"
                    "RepairTarget.mask_path を指定してください。"
                ),
            )

        if not Path(mask_path).is_file():
            return self._target_failure(
                target,
                f"マスク画像が存在しません: {mask_path}",
            )

        config = self._build_config(
            base_config=base_config,
            target=target,
            index=index,
        )

        generation_request = self._build_request(
            source_image=source_image,
            mask_image=mask_path,
            target=target,
            request=request,
            config=config,
            method="inpaint",
        )

        generated = self.inpainting_generator.generate(
            source_image,
            mask_path,
            generation_request,
        )

        return self._normalize_result(
            generated=generated,
            target=target,
            method="inpaint",
        )

    def _repair_img2img(
        self,
        source_image: str,
        target: RepairTarget,
        request: RepairRequest,
        base_config: GenerationConfig,
        index: int,
    ) -> dict[str, Any]:
        if self.image_to_image_generator is None:
            return self._target_failure(
                target,
                "ImageToImageGenerator が接続されていません。",
            )

        config = self._build_config(
            base_config=base_config,
            target=target,
            index=index,
        )

        generation_request = self._build_request(
            source_image=source_image,
            mask_image=None,
            target=target,
            request=request,
            config=config,
            method="img2img",
        )

        generated = self.image_to_image_generator.generate(
            source_image,
            generation_request,
        )

        return self._normalize_result(
            generated=generated,
            target=target,
            method="img2img",
        )

    def _build_config(
        self,
        base_config: GenerationConfig,
        target: RepairTarget,
        index: int,
    ) -> GenerationConfig:
        """
        元の設定を複製し、修正対象に応じた強度を適用する。

        元の base_config 自体は変更しない。
        """
        config = replace(base_config)

        strength = max(0.0, min(1.0, float(target.strength)))
        config.denoise_strength = strength

        # 修正対象ごとに、どの条件を強めるかを調整する。
        category_field = {
            "character": "character_strength",
            "face": "face_strength",
            "pose": "pose_strength",
            "hands": "hand_strength",
            "style": "style_strength",
        }.get(target.category)

        if category_field and hasattr(config, category_field):
            setattr(config, category_field, max(
                float(getattr(config, category_field)),
                0.85,
            ))

        # 修正の再現性を確保したい場合は、呼び出し側で seed を指定する。
        # ここでは既存 seed を不用意に上書きしない。
        config.metadata = dict(getattr(config, "metadata", {}) or {})
        config.metadata.update(
            {
                "repair_category": target.category,
                "repair_method": target.method,
                "repair_index": index,
            }
        )

        return config

    def _build_request(
        self,
        source_image: str,
        mask_image: Optional[str],
        target: RepairTarget,
        request: RepairRequest,
        config: GenerationConfig,
        method: str,
    ) -> GenerationRequest:
        category_prompt = self.CATEGORY_PROMPTS.get(
            target.category,
            "Preserve the original character identity and composition.",
        )

        prompts = [
            request.prompt.strip(),
            category_prompt,
            target.reason.strip(),
        ]
        prompt = "\n".join(part for part in prompts if part)

        negative_prompt = request.negative_prompt.strip()

        metadata = dict(request.metadata or {})
        metadata.update(
            {
                "repair_category": target.category,
                "repair_method": method,
                "repair_reason": target.reason,
                "repair_region_data": dict(target.region_data or {}),
            }
        )

        return GenerationRequest(
            config=config,
            prompt=prompt,
            negative_prompt=negative_prompt,
            source_image=source_image,
            mask_image=mask_image,
            metadata=metadata,
        )

    @staticmethod
    def _normalize_result(
        generated: Any,
        target: RepairTarget,
        method: str,
    ) -> dict[str, Any]:
        """
        Generator の返却形式を統一する。

        GenerationResult / dict / str に対応する。
        """
        if isinstance(generated, GenerationResult):
            success = generated.success
            image_path = generated.image_path
            message = generated.message
            errors = list(generated.errors or [])

        elif isinstance(generated, dict):
            success = bool(generated.get("success", False))
            image_path = generated.get("image_path") or generated.get("path")
            message = str(generated.get("message", ""))
            errors = list(generated.get("errors") or [])

        elif isinstance(generated, str):
            success = bool(generated)
            image_path = generated or None
            message = ""
            errors = []

        else:
            success = False
            image_path = None
            message = ""
            errors = [
                f"未対応の Generator 返却形式: {type(generated).__name__}"
            ]

        if not success:
            detail = "; ".join(str(error) for error in errors)
            return {
                "success": False,
                "category": target.category,
                "method": method,
                "image_path": None,
                "error": detail or message or "画像生成に失敗しました。",
            }

        if not image_path:
            return {
                "success": False,
                "category": target.category,
                "method": method,
                "image_path": None,
                "error": "成功結果に画像パスがありません。",
            }

        return {
            "success": True,
            "category": target.category,
            "method": method,
            "image_path": str(image_path),
            "message": message,
            "error": None,
        }

    @staticmethod
    def _target_failure(
        target: RepairTarget,
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "category": target.category,
            "method": target.method,
            "image_path": None,
            "error": error,
        }

    @staticmethod
    def _failure(
        original_image: str,
        error: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "all_success": False,
            "original_image": original_image,
            "final_image": original_image,
            "results": [],
            "errors": [error],
        }
