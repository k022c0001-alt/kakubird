# api/services/commands/command_normalizer.py

from .animation_command import (
    AnimationCommand,
    AnimationCommandSet,
)


class CommandNormalizer:

    SIDE_MAP = {
        "右": "right",
        "右腕": "right",
        "右うで": "right",
        "右の腕": "right",
        "右脚": "right",
        "右足": "right",

        "左": "left",
        "左腕": "left",
        "左うで": "left",
        "左の腕": "left",
        "左脚": "left",
        "左足": "left",
    }

    EXPRESSION_MAP = {
        "笑顔": "smile",
        "笑う": "smile",
        "にっこり": "smile",

        "怒る": "angry",
        "怒った顔": "angry",

        "悲しい": "sad",
        "悲しむ": "sad",

        "驚く": "surprised",
        "びっくり": "surprised",

        "真顔": "neutral",
        "通常": "neutral",
    }

    DIRECTION_MAP = {
        "右": "right",
        "右側": "right",
        "左": "left",
        "左側": "left",
        "前": "forward",
        "前方": "forward",
        "後ろ": "backward",
        "後方": "backward",
    }

    def normalize(
        self,
        command_set: AnimationCommandSet,
    ) -> AnimationCommandSet:

        for command in command_set.commands:

            if command.side:

                command.side = (
                    self.SIDE_MAP.get(
                        command.side,
                        command.side,
                    )
                )

            if command.expression:

                command.expression = (
                    self.EXPRESSION_MAP.get(
                        command.expression,
                        command.expression,
                    )
                )

            if command.direction:

                command.direction = (
                    self.DIRECTION_MAP.get(
                        command.direction,
                        command.direction,
                    )
                )

            if command.axis:

                command.axis = (
                    command.axis.lower()
                )

        return command_set
