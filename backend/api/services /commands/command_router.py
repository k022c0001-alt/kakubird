# api/services/commands/command_router.py

from .animation_command import (
    AnimationCommand,
    AnimationCommandSet,
)

from .command_validator import (
    CommandValidator,
)


class CommandRouter:

    def __init__(
        self,
        pose_handler,
        rotation_handler,
        face_handler,
        hand_handler,
    ):

        self.pose_handler = pose_handler
        self.rotation_handler = rotation_handler
        self.face_handler = face_handler
        self.hand_handler = hand_handler

        self.validator = CommandValidator()

    def execute(
        self,
        command_set: AnimationCommandSet,
        context: dict,
    ):

        errors = self.validator.validate(
            command_set
        )

        if errors:

            return {
                "success": False,
                "stage": "command_validation",
                "errors": errors,
            }

        results = []

        for command in command_set.commands:

            results.append(
                self._execute_command(
                    command,
                    context,
                )
            )

        return {
            "success": all(
                result.get(
                    "success",
                    False
                )
                for result in results
            ),
            "results": results,
        }

    def _execute_command(
        self,
        command: AnimationCommand,
        context: dict,
    ):

        if command.type == "pose":

            return self.pose_handler.handle(
                action=command.action,
                side=command.side,
                context=context,
            )

        if command.type == "rotation":

            return self.rotation_handler.handle(
                action=command.action,
                target=command.target,
                axis=command.axis,
                value=command.value,
                direction=command.direction,
                context=context,
            )

        if command.type == "face":

            return self.face_handler.handle(
                action=command.action,
                expression=command.expression,
                context=context,
            )

        if command.type == "hand":

            return self.hand_handler.handle(
                action=command.action,
                side=command.side,
                context=context,
            )

        return {
            "success": False,
            "error": (
                f"未対応のcommand type: "
                f"{command.type}"
            ),
        }
