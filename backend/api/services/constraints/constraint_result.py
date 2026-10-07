# api/services/constraints/constraint_result.py

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ConstraintIssue:
    code: str
    message: str
    target: str = ""
    actual: Any = None
    expected: Any = None
    severity: str = "warning"
    repairable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "target": self.target,
            "actual": self.actual,
            "expected": self.expected,
            "severity": self.severity,
            "repairable": self.repairable,
        }


@dataclass
class ConstraintResult:
    satisfied: bool = True
    issues: List[ConstraintIssue] = field(
        default_factory=list
    )

    def add_issue(
        self,
        code: str,
        message: str,
        target: str = "",
        actual: Any = None,
        expected: Any = None,
        severity: str = "warning",
        repairable: bool = True,
    ) -> None:

        self.issues.append(
            ConstraintIssue(
                code=code,
                message=message,
                target=target,
                actual=actual,
                expected=expected,
                severity=severity,
                repairable=repairable,
            )
        )

        if severity == "error":
            self.satisfied = False

    def add_error(
        self,
        code: str,
        message: str,
        target: str = "",
        actual: Any = None,
        expected: Any = None,
        repairable: bool = True,
    ) -> None:

        self.add_issue(
            code=code,
            message=message,
            target=target,
            actual=actual,
            expected=expected,
            severity="error",
            repairable=repairable,
        )

    def add_warning(
        self,
        code: str,
        message: str,
        target: str = "",
        actual: Any = None,
        expected: Any = None,
        repairable: bool = True,
    ) -> None:

        self.add_issue(
            code=code,
            message=message,
            target=target,
            actual=actual,
            expected=expected,
            severity="warning",
            repairable=repairable,
        )

    def merge(self, other: "ConstraintResult") -> None:

        self.issues.extend(other.issues)

        if not other.satisfied:
            self.satisfied = False

    def to_dict(self) -> Dict[str, Any]:

        return {
            "satisfied": self.satisfied,
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }
