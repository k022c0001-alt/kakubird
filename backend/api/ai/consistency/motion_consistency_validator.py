# ai/consistency/motion_consistency_validator.py

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MotionIssue:
    """フレーム間で検出された動きの問題。"""

    code: str
    message: str
    frame_index: int
    joint_name: Optional[str] = None
    severity: str = "warning"
    distance: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "frame_index": self.frame_index,
            "joint_name": self.joint_name,
            "severity": self.severity,
            "distance": self.distance,
            "metadata": self.metadata,
        }


@dataclass
class MotionValidationResult:
    """アニメーションの動きの検証結果。"""

    passed: bool
    frame_count: int
    overall_score: Optional[float]
    issues: list[MotionIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis_available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "frame_count": self.frame_count,
            "overall_score": self.overall_score,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": self.warnings,
            "analysis_available": self.analysis_available,
            "metadata": self.metadata,
        }


class MotionConsistencyValidator:
    """
    フレーム間の関節位置を比較し、急激な移動を検出する。

    入力例:
        [
            {
                "pose_landmarks": {
                    "head": [0.50, 0.20],
                    "left_hand": [0.35, 0.50],
                    "right_hand": [0.65, 0.50]
                }
            },
            {
                "pose_landmarks": {
                    "head": [0.51, 0.20],
                    "left_hand": [0.36, 0.49],
                    "right_hand": [0.64, 0.49]
                }
            }
        ]

    座標は画像サイズで正規化された値を推奨する。
    例: x / width, y / height

    注意:
        このクラスは動きの不自然さを検出するための初期実装。
        意図的な高速動作、カメラ移動、ジャンプなどを
        自動的に理解するものではない。
    """

    def __init__(
        self,
        max_joint_distance: float = 0.20,
        max_problem_ratio: float = 0.15,
        minimum_common_joints: int = 3,
    ) -> None:
        if max_joint_distance <= 0:
            raise ValueError("max_joint_distance は正数にしてください。")

        if not 0 <= max_problem_ratio <= 1:
            raise ValueError("max_problem_ratio は 0～1 にしてください。")

        if minimum_common_joints < 1:
            raise ValueError("minimum_common_joints は1以上にしてください。")

        self.max_joint_distance = max_joint_distance
        self.max_problem_ratio = max_problem_ratio
        self.minimum_common_joints = minimum_common_joints

    def validate(
        self,
        frames: list[dict[str, Any]],
        fps: Optional[float] = None,
    ) -> MotionValidationResult:
        """
        フレーム間の関節位置を検証する。

        Args:
            frames:
                pose_landmarks を含むフレーム特徴量の配列。

            fps:
                再生フレームレート。指定した場合、結果に記録する。

        Returns:
            MotionValidationResult
        """
        if len(frames) < 2:
            return MotionValidationResult(
                passed=False,
                frame_count=len(frames),
                overall_score=None,
                analysis_available=False,
                warnings=[
                    "フレーム間の比較には2フレーム以上必要です。"
                ],
            )

        issues: list[MotionIssue] = []
        warnings: list[str] = []

        compared_joints = 0
        problem_joints = 0
        total_distance = 0.0

        for frame_index in range(1, len(frames)):
            previous = self._extract_landmarks(frames[frame_index - 1])
            current = self._extract_landmarks(frames[frame_index])

            common_names = sorted(set(previous) & set(current))

            if len(common_names) < self.minimum_common_joints:
                warnings.append(
                    f"フレーム {frame_index - 1} → {frame_index}: "
                    "比較できる関節数が不足しています。"
                )
                continue

            for joint_name in common_names:
                old_point = previous[joint_name]
                new_point = current[joint_name]

                distance = math.dist(old_point, new_point)

                compared_joints += 1
                total_distance += distance

                if distance > self.max_joint_distance:
                    problem_joints += 1

                    issues.append(
                        MotionIssue(
                            code="JOINT_POSITION_JUMP",
                            message=(
                                f"{joint_name} の位置が隣接フレーム間で "
                                f"{distance:.3f} 移動しています。"
                            ),
                            frame_index=frame_index,
                            joint_name=joint_name,
                            severity="warning",
                            distance=distance,
                            metadata={
                                "previous_frame": frame_index - 1,
                                "current_frame": frame_index,
                                "threshold": self.max_joint_distance,
                            },
                        )
                    )

        if compared_joints == 0:
            return MotionValidationResult(
                passed=False,
                frame_count=len(frames),
                overall_score=None,
                issues=issues,
                warnings=warnings + [
                    "比較できる関節座標がありません。"
                ],
                analysis_available=False,
            )

        problem_ratio = problem_joints / compared_joints
        average_distance = total_distance / compared_joints

        # 検出した問題の割合から初期スコアを算出する。
        score = max(0.0, min(1.0, 1.0 - problem_ratio))

        passed = problem_ratio <= self.max_problem_ratio

        return MotionValidationResult(
            passed=passed,
            frame_count=len(frames),
            overall_score=score,
            issues=issues,
            warnings=warnings,
            analysis_available=True,
            metadata={
                "compared_joints": compared_joints,
                "problem_joints": problem_joints,
                "problem_ratio": problem_ratio,
                "average_joint_distance": average_distance,
                "max_joint_distance": self.max_joint_distance,
                "max_problem_ratio": self.max_problem_ratio,
                "fps": fps,
            },
        )

    @staticmethod
    def _extract_landmarks(
        frame: dict[str, Any],
    ) -> dict[str, tuple[float, float]]:
        """
        フレームから関節座標を抽出する。

        対応形式:
            {"head": [0.5, 0.2]}
            {"head": {"x": 0.5, "y": 0.2}}

        confidence がある場合、0.0～1.0の値が0.2未満の関節は
        信頼度が低いものとして比較対象から除外する。
        """
        landmarks = frame.get("pose_landmarks")

        if not isinstance(landmarks, dict):
            return {}

        output: dict[str, tuple[float, float]] = {}

        for name, value in landmarks.items():
            try:
                if isinstance(value, dict):
                    x = float(value["x"])
                    y = float(value["y"])

                    confidence = value.get("confidence")

                    if confidence is not None and float(confidence) < 0.2:
                        continue

                elif isinstance(value, (list, tuple)) and len(value) >= 2:
                    x = float(value[0])
                    y = float(value[1])

                else:
                    continue

                if not math.isfinite(x) or not math.isfinite(y):
                    continue

                output[str(name)] = (x, y)

            except (TypeError, ValueError, KeyError, OverflowError):
                continue

        return output
