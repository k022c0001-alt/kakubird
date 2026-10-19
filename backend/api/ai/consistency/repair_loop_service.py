# -*- coding: utf-8 -*-
"""repair_loop_service.py

修正・再評価・結果採用を管理する。
"""

from typing import Any, Dict, Optional

from .consistency_service import ConsistencyService
from .consistency_result import ConsistencyResult
from .repair_request import RepairRequest
from .repair_planner import RepairPlanner
from .image_repair_service import ImageRepairService

from ..image.generation_config import GenerationConfig


class RepairLoopService:
    """画像の修正と評価を統合する。"""

    def __init__(
        self,
        consistency_service: ConsistencyService,
        repair_planner: RepairPlanner,
        image_repair_service: ImageRepairService,
    ):
        self.consistency_service = (
            consistency_service
        )

        self.repair_planner = repair_planner

        self.image_repair_service = (
            image_repair_service
        )

    def repair_and_validate(
        self,
        reference_image: str,
        generated_image: str,
        user_prompt: str = "",
        config: Optional[GenerationConfig] = None,
    ) -> Dict[str, Any]:
        """生成画像を検証し、必要に応じて修正する。"""

        before = (
            self.consistency_service.validate_images(
                reference_image=reference_image,
                generated_image=generated_image,
            )
        )

        if before.passed:
            return {
                "success": True,
                "accepted": True,
                "image_path": generated_image,
                "before": before.to_dict(),
                "after": before.to_dict(),
                "message": (
                    "Image passed consistency validation."
                ),
            }

        plan: RepairRequest = (
            self.repair_planner.create_plan(
                result=before,
                source_image=generated_image,
                user_prompt=user_prompt,
            )
        )

        if not plan.targets:
            return {
                "success": False,
                "accepted": False,
                "image_path": generated_image,
                "before": before.to_dict(),
                "after": None,
                "repair_plan": plan.to_dict(),
                "message": (
                    "No safe automatic repair plan "
                    "could be created."
                ),
            }

        repair_result = (
            self.image_repair_service.repair(
                repair_request=plan,
                base_config=config,
            )
        )

        candidate = repair_result.get(
            "final_image"
        )

        if (
            not repair_result.get("success")
            or not candidate
        ):
            return {
                "success": False,
                "accepted": False,
                "image_path": generated_image,
                "before": before.to_dict(),
                "after": None,
                "repair": repair_result,
                "message": (
                    "Repair failed. Original generated "
                    "image was retained."
                ),
            }

        after = (
            self.consistency_service.validate_images(
                reference_image=reference_image,
                generated_image=candidate,
            )
        )

        # 必須項目を評価できない結果は採用しない。
        if not after.analysis_available:
            accepted = False

        # 検証に合格した場合は採用する。
        elif after.passed:
            accepted = True

        # 不合格の場合は、修正前より改善したかを確認。
        elif (
            before.overall_score is not None
            and after.overall_score is not None
        ):
            accepted = (
                after.overall_score
                > before.overall_score
            )

        else:
            accepted = False

        return {
            "success": True,
            "accepted": accepted,
            "image_path": (
                candidate
                if accepted
                else generated_image
            ),
            "before": before.to_dict(),
            "after": after.to_dict(),
            "repair": repair_result,
            "message": (
                "Repaired image accepted."
                if accepted
                else (
                    "Repaired image was not accepted. "
                    "Original image retained."
                )
            ),
        }
