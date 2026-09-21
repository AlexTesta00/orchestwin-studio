"""Immutable launch inputs for human-governed formal case-study runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_CASE_ID_PATTERN: Final = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_MAX_TEXT: Final = 4_000
_MOBILE_TOKENS: Final = (
    "android",
    "flutter",
    "jetpack compose",
    "apk",
    "adb",
    "emulator",
)
SUPPORTED_TECHNOLOGIES: Final = frozenset(
    {
        "HTML",
        "CSS",
        "JavaScript",
        "Node.js",
        "Vue",
        "Express",
        "Java",
        "Kotlin",
        "Scala",
    }
)


class FormalGateType(StrEnum):
    """Gate names mirrored from the governed production workflow for evidence capture."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    AGENT_TEAM = "AGENT_TEAM"
    USER_MODELING = "USER_MODELING"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    ARCHITECTURE = "ARCHITECTURE"
    HIGH_IMPACT_OPERATION = "HIGH_IMPACT_OPERATION"
    FINAL_OUTPUT = "FINAL_OUTPUT"


REQUIRED_FORMAL_GATES: Final = (
    FormalGateType.PROJECT_BRIEF,
    FormalGateType.AGENT_TEAM,
    FormalGateType.USER_MODELING,
    FormalGateType.REQUIREMENTS,
    FormalGateType.DESIGN,
    FormalGateType.ARCHITECTURE,
    FormalGateType.HIGH_IMPACT_OPERATION,
    FormalGateType.FINAL_OUTPUT,
)


def _normalize(value: str, *, label: str, maximum: int = _MAX_TEXT) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if normalized != value:
        raise ValueError(f"{label} must be normalized")
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds maximum length")
    return value


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_definition_path(value: str) -> None:
    _normalize(value, label="case definition path", maximum=500)
    if "\\" in value:
        raise ValueError("case definition path must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("case definition path must remain repository-relative")
    if path.parts[:2] != ("experiments", "case-studies"):
        raise ValueError("case definition path must stay under experiments/case-studies")
    if path.suffix != ".json":
        raise ValueError("case definition path must reference JSON")


def _assert_no_mobile_scope(payload: object) -> None:
    serialized = _canonical_json(payload).lower()
    found = [token for token in _MOBILE_TOKENS if token in serialized]
    if found:
        raise ValueError(f"formal launch input contains stale mobile scope: {', '.join(found)}")


@dataclass(frozen=True, slots=True)
class FormalCaseLaunchInput:
    """Frozen owner input and governance requirements for one formal case run."""

    schema_version: int
    case_id: str
    case_version: int
    case_content_hash: str
    title: str
    definition_path: str
    project_mode: str
    owner_request: str
    execution_profile: str
    technologies: tuple[str, ...]
    user_twin_roles: tuple[str, ...]
    constraints: tuple[str, ...]
    required_gates: tuple[FormalGateType, ...]
    network_policy: str
    operator_instructions: tuple[str, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported formal launch input schema version")
        if self.case_version < 1:
            raise ValueError("formal launch input case version must be positive")
        if _CASE_ID_PATTERN.fullmatch(self.case_id) is None:
            raise ValueError("formal launch input case ID is invalid")
        if _SHA256_PATTERN.fullmatch(self.case_content_hash) is None:
            raise ValueError("case content hash must be a lowercase SHA-256 digest")
        _normalize(self.title, label="formal launch title", maximum=300)
        _validate_definition_path(self.definition_path)
        if self.project_mode != "GREENFIELD":
            raise ValueError("formal case launches must use GREENFIELD project mode")
        _normalize(self.owner_request, label="formal launch owner request")
        _normalize(self.execution_profile, label="formal launch execution profile", maximum=200)
        if not self.execution_profile.startswith("WEB_"):
            raise ValueError("formal Sprint 12 case launches must use a Web execution profile")
        if not self.technologies or len(self.technologies) != len(set(self.technologies)):
            raise ValueError("formal launch technologies must be non-empty and unique")
        unsupported = set(self.technologies) - SUPPORTED_TECHNOLOGIES
        if unsupported:
            raise ValueError(
                "formal launch contains unsupported technologies: " + ", ".join(sorted(unsupported))
            )
        if "PHP" in self.technologies:
            raise ValueError("PHP is outside the revised formal Sprint 12 scope")
        if not self.user_twin_roles or len(self.user_twin_roles) != len(set(self.user_twin_roles)):
            raise ValueError("formal launch User Twin roles must be non-empty and unique")
        for role in self.user_twin_roles:
            _normalize(role, label="formal launch User Twin role", maximum=300)
        if len(self.constraints) != len(set(self.constraints)):
            raise ValueError("formal launch constraints must be unique")
        for constraint in self.constraints:
            _normalize(constraint, label="formal launch constraint")
        if self.required_gates != REQUIRED_FORMAL_GATES:
            raise ValueError("formal launch must preserve the complete owner gate sequence")
        _normalize(self.network_policy, label="formal launch network policy", maximum=1_000)
        if not self.operator_instructions:
            raise ValueError("formal launch operator instructions must not be empty")
        if len(self.operator_instructions) != len(set(self.operator_instructions)):
            raise ValueError("formal launch operator instructions must be unique")
        for instruction in self.operator_instructions:
            _normalize(instruction, label="formal launch operator instruction")
        if _SHA256_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("formal launch content hash must be a lowercase SHA-256 digest")
        if self.content_hash != formal_case_launch_input_hash(self.to_snapshot(include_hash=False)):
            raise ValueError("formal launch input content hash is inconsistent")
        _assert_no_mobile_scope(self.to_snapshot())

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "case_version": self.case_version,
            "case_content_hash": self.case_content_hash,
            "title": self.title,
            "definition_path": self.definition_path,
            "project_mode": self.project_mode,
            "owner_request": self.owner_request,
            "execution_profile": self.execution_profile,
            "technologies": list(self.technologies),
            "user_twin_roles": list(self.user_twin_roles),
            "constraints": list(self.constraints),
            "required_gates": [gate.value for gate in self.required_gates],
            "network_policy": self.network_policy,
            "operator_instructions": list(self.operator_instructions),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def formal_case_launch_input_hash(payload: object) -> str:
    """Return the deterministic identity of one formal launch input."""
    return _hash(payload)


def load_formal_case_launch_input(path: Path) -> FormalCaseLaunchInput:
    """Load and validate one immutable formal case launch JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    without_hash = {key: value for key, value in payload.items() if key != "content_hash"}
    supplied_hash = payload.get("content_hash", formal_case_launch_input_hash(without_hash))
    return FormalCaseLaunchInput(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        case_version=payload["case_version"],
        case_content_hash=payload["case_content_hash"],
        title=payload["title"],
        definition_path=payload["definition_path"],
        project_mode=payload["project_mode"],
        owner_request=payload["owner_request"],
        execution_profile=payload["execution_profile"],
        technologies=tuple(payload["technologies"]),
        user_twin_roles=tuple(payload["user_twin_roles"]),
        constraints=tuple(payload["constraints"]),
        required_gates=tuple(FormalGateType(value) for value in payload["required_gates"]),
        network_policy=payload["network_policy"],
        operator_instructions=tuple(payload["operator_instructions"]),
        content_hash=supplied_hash,
    )


def case_definition_content_hash(payload: dict[str, object]) -> str:
    """Match the semantic case-definition hash used by case_studies.py."""
    without_hash = {key: value for key, value in payload.items() if key != "content_hash"}
    return _hash(without_hash)


def validate_launch_input_against_definition(
    launch: FormalCaseLaunchInput,
    definition: dict[str, object],
) -> None:
    """Require the frozen launch input to match the exact case definition it references."""
    checks = (
        (launch.case_id, definition.get("case_id"), "case ID"),
        (launch.case_version, definition.get("version"), "case version"),
        (launch.title, definition.get("title"), "title"),
        (launch.owner_request, definition.get("project_brief"), "owner request"),
        (launch.execution_profile, definition.get("execution_profile"), "execution profile"),
        (list(launch.technologies), definition.get("technologies"), "technologies"),
        (list(launch.user_twin_roles), definition.get("user_twin_roles"), "User Twin roles"),
        (list(launch.constraints), definition.get("constraints"), "constraints"),
    )
    for observed, expected, label in checks:
        if observed != expected:
            raise ValueError(f"formal launch {label} differs from the frozen case definition")
    if launch.case_content_hash != case_definition_content_hash(definition):
        raise ValueError("formal launch case content hash differs from the frozen definition")
