# api/services/commands/command_parser.py

import re

from .animation_command import (
    AnimationCommand,
    AnimationCommandSet,
)


class CommandParser:

    def parse(
        self,
        text: str,
    ) -> AnimationCommandSet:

        result = AnimationCommandSet(
            original_text=text
        )

        if not text:
            return result

        normalized = text.strip()

        self._parse_rotation(
            normalized,
            result,
        )

        self._parse_arm(
            normalized,
            result,
        )

        self._parse_leg(
            normalized,
            result,
        )

        self._parse_expression(
            normalized,
            result,
        )

        return result

    def _parse_rotation(
        self,
        text,
        result,
    ):

        pattern = (
            r"(\d+(?:\.\d+)?)\s*度"
            r"\s*(右|左)"
            r"\s*(?:を)?\s*(?:向いて|向く|回転)"
        )

        match = re.search(
            pattern,
            text
        )

        if not match:
            return

        angle = float(
            match.group(1)
        )

        direction = match.group(2)

        if direction == "右":
            angle = abs(angle)

        else:
            angle = -abs(angle)

        result.add(
            AnimationCommand(
                type="rotation",
                action="rotate",
                target="body",
                axis="y",
                value=angle,
                direction=(
                    "right"
                    if angle >= 0
                    else "left"
                ),
            )
        )

    def _parse_arm(
        self,
        text,
        result,
    ):

        side = None

        if "右腕" in text or "右うで" in text:
            side = "right"

        elif "左腕" in text or "左うで" in text:
            side = "left"

        if side is None:
            return

        if any(
            keyword in text
            for keyword in [
                "上げて",
                "上げる",
                "挙げて",
                "挙げる",
            ]
        ):

            result.add(
                AnimationCommand(
                    type="pose",
                    action="raise_arm",
                    side=side,
                )
            )

        elif any(
            keyword in text
            for keyword in [
                "下げて",
                "下げる",
            ]
        ):

            result.add(
                AnimationCommand(
                    type="pose",
                    action="lower_arm",
                    side=side,
                )
            )

    def _parse_leg(
        self,
        text,
        result,
    ):

        side = None

        if "右足" in text or "右脚" in text:
            side = "right"

        elif "左足" in text or "左脚" in text:
            side = "left"

        if side is None:
            return

        if any(
            keyword in text
            for keyword in [
                "前に出して",
                "前に出す",
                "前へ出して",
                "前へ出す",
            ]
        ):

            result.add(
                AnimationCommand(
                    type="pose",
                    action="move_leg",
                    side=side,
                    direction="forward",
                )
            )

    def _parse_expression(
        self,
        text,
        result,
    ):

        expressions = {
            "笑顔": "smile",
            "笑って": "smile",
            "笑う": "smile",
            "怒って": "angry",
            "怒る": "angry",
            "悲しい顔": "sad",
            "驚いて": "surprised",
            "真顔": "neutral",
        }

        for keyword, expression in expressions.items():

            if keyword in text:

                result.add(
                    AnimationCommand(
                        type="face",
                        action="expression",
                        expression=expression,
                    )
                )

                break
