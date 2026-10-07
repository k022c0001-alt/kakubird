# api/services/commands/animation_command.py

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AnimationCommand:
    """
    自然言語から変換された1つの操作命令。
    """

    type: str

    action: str

    target: Optional[str] = None

    side: Optional[str] = None

    axis: Optional[str] = None

    value: Optional[float] = None

    direction: Optional[str] = None

    expression: Optional[str] = None

    duration: Optional[float] = None

    frame_count: Optional[int] = None

    strength: Optional[float] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "type": self.type,
            "action": self.action,
            "target": self.target,
            "side": self.side,
            "axis": self.axis,
            "value": self.value,
            "direction": self.direction,
            "expression": self.expression,
            "duration": self.duration,
            "frame_count": self.frame_count,
            "strength": self.strength,
            "metadata": self.metadata,
        }


@dataclass
class AnimationCommandSet:
    """
    複数のAnimationCommandをまとめたもの。
    """

    commands: List[AnimationCommand] = field(
        default_factory=list
    )

    original_text: str = ""

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def add(
        self,
        command: AnimationCommand,
    ) -> None:

        self.commands.append(command)

    def to_dict(self) -> Dict[str, Any]:

        return {
            "commands": [
                command.to_dict()
                for command in self.commands
            ],
            "original_text": self.original_text,
            "metadata": self.metadata,
        }
