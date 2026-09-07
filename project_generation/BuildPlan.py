"""Validated intermediate representation for project generation."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union


_WINDOWS_ABSOLUTE = re.compile(r"^[a-zA-Z]:[/\\]")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")
_SUPPORTED_FILE_TYPES = {
    "file",
    "api",
    "asset",
    "component",
    "config",
    "data",
    "documentation",
    "entry",
    "html",
    "layout",
    "page",
    "script",
    "style",
    "test",
}


class BuildPlanValidationError(ValueError):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = [str(error) for error in errors]
        super().__init__(" ".join(self.errors))


@dataclass
class BuildFile:
    """Design information for one generated file."""

    path: str
    type: str = "file"
    description: str = ""
    language: Optional[str] = None
    required: bool = True
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path = self.normalize_path(self.path)
        self.type = str(self.type or "file").strip().lower()
        self.description = str(self.description or "").strip()
        self.language = str(self.language).strip() if self.language else None
        self.required = _coerce_bool(self.required, default=True)
        self.dependencies = _unique_strings(self.dependencies)
        self.metadata = copy.deepcopy(dict(self.metadata or {}))

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.path:
            return ["ファイルパスが空です。"]
        if len(self.path) > 240:
            errors.append(f"ファイルパスが長すぎます: {self.path}")
        if _CONTROL_CHARACTER.search(self.path):
            errors.append(f"制御文字を含むファイルパスです: {self.path!r}")
        if self.path.startswith(("/", "//", "~")) or _WINDOWS_ABSOLUTE.match(self.path):
            errors.append(f"絶対パスは使用できません: {self.path}")
        if self.path.endswith("/"):
            errors.append(f"ファイルパスがディレクトリ形式です: {self.path}")

        parts = PurePosixPath(self.path).parts
        if any(part in {"", ".", ".."} for part in parts):
            errors.append(f"相対移動を含むファイルパスです: {self.path}")
        if self.type not in _SUPPORTED_FILE_TYPES:
            errors.append(f"未対応のBuildFile.typeです: {self.type}")
        return errors

    def is_valid(self) -> bool:
        return not self.validate()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildFile":
        if not isinstance(data, Mapping):
            raise TypeError("BuildFile data must be a mapping")
        return cls(
            path=str(data.get("path", "") or "").strip(),
            type=str(data.get("type", "file") or "file").strip(),
            description=str(data.get("description", "") or "").strip(),
            language=(str(data["language"]).strip() if data.get("language") else None),
            required=_coerce_bool(data.get("required", True), default=True),
            dependencies=_string_list(data.get("dependencies", [])),
            metadata=copy.deepcopy(data.get("metadata", {}) or {}),
        )

    @staticmethod
    def normalize_path(path: Any) -> str:
        # Keep leading/trailing slashes so validation can detect absolute paths
        # and directory-shaped entries instead of silently making them safe.
        return str(path or "").replace("\\", "/").strip()


@dataclass
class BuildPlan:
    """ProjectPlanner output consumed by the generation pipeline."""

    project_name: str
    description: str = ""
    framework: str = "react"
    features: List[str] = field(default_factory=list)
    pages: List[str] = field(default_factory=list)
    files: List[BuildFile] = field(default_factory=list)
    target_user: Optional[str] = None
    purpose: Optional[str] = None
    database: Optional[str] = None
    backend: Optional[str] = None
    design_preferences: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    dev_dependencies: List[str] = field(default_factory=list)
    scripts: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    MAX_FILES = 2000

    def __post_init__(self) -> None:
        self.normalize()

    def normalize(self) -> "BuildPlan":
        self.project_name = str(self.project_name or "").strip()
        self.description = str(self.description or "").strip()
        self.framework = str(self.framework or "").strip().lower()
        self.features = _unique_strings(self.features)
        self.pages = _unique_strings(self.pages)
        self.target_user = str(self.target_user).strip() if self.target_user else None
        self.purpose = str(self.purpose).strip() if self.purpose else None
        self.database = str(self.database).strip() if self.database else None
        self.backend = str(self.backend).strip() if self.backend else None
        self.design_preferences = _unique_strings(self.design_preferences)
        self.constraints = _unique_strings(self.constraints)
        self.dependencies = _unique_strings(self.dependencies)
        self.dev_dependencies = _unique_strings(self.dev_dependencies)
        self.scripts = {
            str(name).strip(): str(command).strip()
            for name, command in dict(self.scripts or {}).items()
            if str(name).strip() and str(command).strip()
        }
        self.metadata = copy.deepcopy(dict(self.metadata or {}))

        normalized_files: List[BuildFile] = []
        for item in self.files or []:
            normalized_files.append(
                item if isinstance(item, BuildFile) else BuildFile.from_dict(item)
            )
        self.files = normalized_files
        return self

    def add_file(self, build_file: Union[BuildFile, Mapping[str, Any]]) -> bool:
        candidate = (
            build_file
            if isinstance(build_file, BuildFile)
            else BuildFile.from_dict(build_file)
        )
        if not candidate.is_valid() or self.has_file(candidate.path):
            return False
        self.files.append(candidate)
        return True

    def has_file(self, path: str) -> bool:
        normalized = BuildFile.normalize_path(path).casefold()
        return any(file.path.casefold() == normalized for file in self.files)

    def get_file(self, path: str) -> Optional[BuildFile]:
        normalized = BuildFile.normalize_path(path).casefold()
        return next((file for file in self.files if file.path.casefold() == normalized), None)

    @property
    def required_files(self) -> List[BuildFile]:
        return [file for file in self.files if file.required]

    def get_required_files(self) -> List[BuildFile]:
        """Backward-compatible method used by older pipeline components."""
        return self.required_files

    @property
    def optional_files(self) -> List[BuildFile]:
        return [file for file in self.files if not file.required]

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.project_name:
            errors.append("project_name が空です。")
        elif (
            self.project_name in {".", ".."}
            or "/" in self.project_name
            or "\\" in self.project_name
            or _CONTROL_CHARACTER.search(self.project_name)
        ):
            errors.append("project_name に使用できない文字が含まれています。")
        if not self.framework:
            errors.append("framework が空です。")
        if not self.files:
            errors.append("生成対象ファイルがありません。")
        if len(self.files) > self.MAX_FILES:
            errors.append(f"生成対象ファイルは{self.MAX_FILES}件以内にしてください。")

        seen: set[str] = set()
        for build_file in self.files:
            for error in build_file.validate():
                errors.append(f"{build_file.path or '<empty>'}: {error}")
            normalized = build_file.path.casefold()
            if normalized in seen:
                errors.append(f"ファイルが重複しています: {build_file.path}")
            seen.add(normalized)

        known_paths = {build_file.path.casefold() for build_file in self.files}
        for build_file in self.files:
            for dependency in build_file.dependencies:
                normalized_dependency = BuildFile.normalize_path(dependency).casefold()
                if normalized_dependency and normalized_dependency not in known_paths:
                    errors.append(
                        f"{build_file.path} が存在しない依存ファイルを参照しています: "
                        f"{dependency}"
                    )
        return errors

    @property
    def is_valid(self) -> bool:
        return not self.validate()

    def validate_or_raise(self) -> None:
        errors = self.validate()
        if errors:
            raise BuildPlanValidationError(errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_name": self.project_name,
            "description": self.description,
            "framework": self.framework,
            "features": list(self.features),
            "pages": list(self.pages),
            "target_user": self.target_user,
            "purpose": self.purpose,
            "database": self.database,
            "backend": self.backend,
            "design_preferences": list(self.design_preferences),
            "constraints": list(self.constraints),
            "dependencies": list(self.dependencies),
            "dev_dependencies": list(self.dev_dependencies),
            "scripts": dict(self.scripts),
            "file_structure": [file.to_dict() for file in self.files],
            "metadata": copy.deepcopy(self.metadata),
        }

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BuildPlan":
        if not isinstance(data, Mapping):
            raise TypeError("BuildPlan data must be a mapping")
        raw_files = data.get("file_structure") or data.get("files") or []
        files = [
            item if isinstance(item, BuildFile) else BuildFile.from_dict(item)
            for item in raw_files
            if isinstance(item, (BuildFile, Mapping))
        ] if isinstance(raw_files, list) else []

        return cls(
            project_name=str(data.get("project_name", "generated-app") or "").strip(),
            description=str(data.get("description", "") or "").strip(),
            framework=str(data.get("framework", "react") or "").strip(),
            features=_string_list(data.get("features", [])),
            pages=_string_list(data.get("pages", [])),
            files=files,
            target_user=(str(data["target_user"]).strip() if data.get("target_user") else None),
            purpose=(str(data["purpose"]).strip() if data.get("purpose") else None),
            database=(str(data["database"]).strip() if data.get("database") else None),
            backend=(str(data["backend"]).strip() if data.get("backend") else None),
            design_preferences=_string_list(data.get("design_preferences", [])),
            constraints=_string_list(data.get("constraints", [])),
            dependencies=_string_list(data.get("dependencies", [])),
            dev_dependencies=_string_list(data.get("dev_dependencies", [])),
            scripts=dict(data.get("scripts", {}) or {}),
            metadata=copy.deepcopy(data.get("metadata", {}) or {}),
        )

    @classmethod
    def from_json(cls, value: str) -> "BuildPlan":
        try:
            data = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise BuildPlanValidationError(["BuildPlan JSONが不正です。"]) from exc
        if not isinstance(data, Mapping):
            raise BuildPlanValidationError(["BuildPlan JSONのルートはobjectである必要があります。"])
        return cls.from_dict(data)


def _string_list(value: Any) -> List[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value]
    return [str(value)]


def _unique_strings(value: Any) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for item in _string_list(value):
        normalized = item.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


__all__ = ["BuildFile", "BuildPlan", "BuildPlanValidationError"]
