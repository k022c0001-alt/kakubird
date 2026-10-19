# ai/consistency/repair_loop_service.py

from __future__ import annotations

import logging
from typing import Any, Optional

from ai.consistency.consistency_service import ConsistencyService
from ai.consistency.repair_planner import RepairPlanner
from ai.consistency.image_repair_service import ImageRepairService

from ai.image.generation_config import GenerationConfig

logger = logging.getLogger(__name__)


class RepairLoopService:
    """
    画像の検証・修正・再検証を管理するサービス。

    処理:
        1. 生成画像を検証
        2. 問題があれば修正計画を作成
        3. 画像を修正
        4. 修正画像を再検証
        5. 修正前後を比較
        6. 採用する画像を決定
    """

    def __init__(
        self,
        consistency_service: ConsistencyService,
        repair_planner: RepairPlanner,
        image_repair_service: ImageRepairService,
        category_drop_tolerance: float = 0.05,
        minimum_overall_score: float = 0.82,
    ) -> None:
        self.consistency_service = consistency_service
        self.repair_planner = repair_planner
        self.image_repair_service = image_repair_service

        self.category_drop_tolerance = max(
            0.0,
            float(category_drop_tolerance),
        )
        self.minimum_overall_score = max(
            0.0,
            min(1.0, float(minimum_overall_score)),
        )

    def repair_and_validate(
        self,
        reference_image: str,
        generated_image: str,
        user_prompt: str = "",
        config: Optional[GenerationConfig] = None,
    ) -> dict[str, Any]:
        """
        画像を検証し、必要に応じて修正する。

        戻り値:
        {
            "success": bool,
            "accepted": bool,
            "original_image": str,
            "final_image": str,
            "before": dict,
            "after": dict | None,
            "repair": dict | None,
            "message": str,
            "errors": list
        }
        """
        if not reference_image:
            return self._failure(
                generated_image,
                "参照画像が指定されていません。",
            )

        if not generated_image:
            return self._failure(
                generated_image,
                "検証する生成画像が指定されていません。",
            )

        # 第1段階: 修正前の画像を検証
        before = self.consistency_service.validate_images(
            reference_image=reference_image,
            generated_image=generated_image,
        )

        before_dict = self._result_to_dict(before)

        # 解析できない場合は、自動修正の判断をしない。
        if not before.analysis_available:
            return {
                "success": False,
                "accepted": False,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": None,
                "repair": None,
                "message": (
                    "画像の一貫性を解析できませんでした。"
                    "解析モデルの接続状態を確認してください。"
                ),
                "errors": [
                    "analysis_unavailable",
                ],
            }

        # 既に合格しているなら修正しない。
        if self._is_acceptable(before):
            return {
                "success": True,
                "accepted": True,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": before_dict,
                "repair": None,
                "message": "生成画像は検証に合格しました。修正は不要です。",
                "errors": [],
            }

        # 第2段階: 修正計画を作成
        repair_request = self.repair_planner.create_plan(
            result=before,
            source_image=generated_image,
            user_prompt=user_prompt,
        )

        if not repair_request.targets:
            return {
                "success": False,
                "accepted": False,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": None,
                "repair": None,
                "message": (
                    "修正対象を決定できませんでした。"
                    "生成画像は変更せずに保持します。"
                ),
                "errors": ["no_repair_targets"],
            }

        # 第3段階: 修正を実行
        repair_output = self.image_repair_service.repair(
            request=repair_request,
            base_config=config,
        )

        if not repair_output.get("success"):
            return {
                "success": False,
                "accepted": False,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": None,
                "repair": repair_output,
                "message": (
                    "画像修正に失敗しました。"
                    "元の生成画像を保持します。"
                ),
                "errors": repair_output.get("errors", []),
            }

        candidate_image = repair_output.get("final_image")

        if not candidate_image:
            return {
                "success": False,
                "accepted": False,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": None,
                "repair": repair_output,
                "message": "修正結果の画像パスがありません。",
                "errors": ["missing_candidate_image"],
            }

        # 第4段階: 修正画像を再検証
        after = self.consistency_service.validate_images(
            reference_image=reference_image,
            generated_image=candidate_image,
        )

        after_dict = self._result_to_dict(after)

        # 再検証できなかった画像を自動採用しない。
        if not after.analysis_available:
            return {
                "success": False,
                "accepted": False,
                "original_image": generated_image,
                "final_image": generated_image,
                "before": before_dict,
                "after": after_dict,
                "repair": repair_output,
                "message": (
                    "修正画像の再検証に失敗しました。"
                    "安全のため修正前の画像を採用します。"
                ),
                "errors": ["post_repair_analysis_unavailable"],
            }

        # 第5段階: 修正前後を比較
        accepted, reason = self._should_accept(
            before=before,
            after=after,
        )

        if accepted:
            return {
                "success": True,
                "accepted": True,
                "original_image": generated_image,
                "final_image": candidate_image,
                "before": before_dict,
                "after": after_dict,
                "repair": repair_output,
                "message": reason,
                "errors": [],
            }

        # 修正結果を採用しない場合は元画像を返す。
        return {
            "success": False,
            "accepted": False,
            "original_image": generated_image,
            "final_image": generated_image,
            "before": before_dict,
            "after": after_dict,
            "repair": repair_output,
            "message": reason,
            "errors": ["repair_candidate_rejected"],
        }

    def _should_accept(
        self,
        before: Any,
        after: Any,
    ) -> tuple[bool, str]:
        """
        修正前後を比較して採用可否を決定する。
        """
        if not before.analysis_available or not after.analysis_available:
            return False, "比較に必要な画像解析結果が不足しています。"

        before_score = before.overall_score
        after_score = after.overall_score

        if before_score is None or after_score is None:
            return False, "全体スコアが不足しているため採用できません。"

        # 一部カテゴリの大幅な悪化を防ぐ。
        before_scores = before.scores or {}
        after_scores = after.scores or {}

        for category, old_score in before_scores.items():
            new_score = after_scores.get(category)

            # 比較可能なスコアがない場合は、このカテゴリを比較しない。
            if old_score is None or new_score is None:
                continue

            drop = float(old_score) - float(new_score)

            if drop > self.category_drop_tolerance:
                return (
                    False,
                    (
                        f"{category} のスコアが "
                        f"{old_score:.3f} から {new_score:.3f} に低下しました。"
                        "修正画像は採用しません。"
                    ),
                )

        # 合格した場合は、品質基準を満たした画像として採用する。
        if after.passed and after_score >= self.minimum_overall_score:
            return True, "修正画像が一貫性チェックに合格しました。"

        # 不合格でも、全体スコアが改善していれば採用できる場合がある。
        # ただし、上記のカテゴリ別悪化チェックを通過していることが条件。
        if after_score > before_score:
            return (
                True,
                (
                    f"全体スコアが {before_score:.3f} から "
                    f"{after_score:.3f} に改善しました。"
                    "品質基準への合格は別途確認してください。"
                ),
            )

        return (
            False,
            (
                f"修正後のスコア ({after_score:.3f}) が "
                f"修正前 ({before_score:.3f}) を上回りませんでした。"
            ),
        )

    def _is_acceptable(self, result: Any) -> bool:
        if not result.analysis_available:
            return False

        if not result.passed:
            return False

        if result.overall_score is None:
            return False

        return result.overall_score >= self.minimum_overall_score

    @staticmethod
    def _result_to_dict(result: Any) -> dict[str, Any]:
        if hasattr(result, "to_dict"):
            return result.to_dict()

        return {
            "passed": getattr(result, "passed", False),
            "overall_score": getattr(result, "overall_score", None),
            "scores": getattr(result, "scores", {}),
            "analysis_available": getattr(
                result,
                "analysis_available",
                False,
            ),
            "issues": getattr(result, "issues", []),
        }

    @staticmethod
    def _failure(
        original_image: str,
        message: str,
    ) -> dict[str, Any]:
        return {
            "success": False,
            "accepted": False,
            "original_image": original_image,
            "final_image": original_image,
            "before": None,
            "after": None,
            "repair": None,
            "message": message,
            "errors": [message],
        }
