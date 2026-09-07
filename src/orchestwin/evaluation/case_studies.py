"""Versioned contracts for reproducible formal case-study definitions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

_FORBIDDEN_MOBILE_TOKENS: Final = (
    "android",
    "flutter",
    "jetpack",
    "compose",
    "apk",
    "adb",
    "emulator",
)
_MAX_TEXT_LENGTH: Final = 4_000


class EvaluationFamily(StrEnum):
    """Execution family used by a formal case study."""

    WEB = "WEB"
    JVM = "JVM"


class CaseStudyEvidenceKind(StrEnum):
    """Evidence categories required by a case-specific Definition of Done."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    REQUIREMENTS = "REQUIREMENTS"
    TRACEABILITY = "TRACEABILITY"
    BUILD_REPORT = "BUILD_REPORT"
    TEST_REPORT = "TEST_REPORT"
    RUNTIME_REPORT = "RUNTIME_REPORT"
    ACCESSIBILITY_REPORT = "ACCESSIBILITY_REPORT"
    SCREENSHOT = "SCREENSHOT"
    USER_TWIN_FINDINGS = "USER_TWIN_FINDINGS"
    REPAIR_HISTORY = "REPAIR_HISTORY"
    FINAL_EXPORT = "FINAL_EXPORT"


def _normalize_text(value: str, *, label: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > _MAX_TEXT_LENGTH:
        raise ValueError(f"{label} exceeds maximum length")
    if normalized != value:
        raise ValueError(f"{label} must be normalized")
    return normalized


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _assert_no_mobile_scope(payload: object) -> None:
    serialized = _canonical_json(payload).lower()
    found = [token for token in _FORBIDDEN_MOBILE_TOKENS if token in serialized]
    if found:
        raise ValueError(f"case-study definition contains stale mobile scope: {', '.join(found)}")


@dataclass(frozen=True, slots=True)
class DefinitionOfDoneItem:
    """One immutable completion criterion and its required evidence categories."""

    criterion_id: str
    description: str
    evidence: tuple[CaseStudyEvidenceKind, ...]

    def __post_init__(self) -> None:
        _normalize_text(self.criterion_id, label="Definition of Done criterion ID")
        _normalize_text(self.description, label="Definition of Done description")
        if not self.evidence:
            raise ValueError("Definition of Done evidence must not be empty")
        if len(self.evidence) != len(set(self.evidence)):
            raise ValueError("Definition of Done evidence must be unique")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "description": self.description,
            "evidence": [item.value for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class CaseStudyDefinition:
    """Frozen project brief, target profile, and evidence-aware Definition of Done."""

    schema_version: int
    case_id: str
    version: int
    title: str
    family: EvaluationFamily
    execution_profile: str
    technologies: tuple[str, ...]
    project_brief: str
    user_twin_roles: tuple[str, ...]
    constraints: tuple[str, ...]
    definition_of_done: tuple[DefinitionOfDoneItem, ...]
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported case-study schema version")
        if self.version < 1:
            raise ValueError("case-study version must be positive")
        _normalize_text(self.case_id, label="case-study ID")
        _normalize_text(self.title, label="case-study title")
        _normalize_text(self.execution_profile, label="execution profile")
        _normalize_text(self.project_brief, label="project brief")
        if not self.technologies or len(self.technologies) != len(set(self.technologies)):
            raise ValueError("case-study technologies must be non-empty and unique")
        if not self.definition_of_done:
            raise ValueError("case-study Definition of Done must not be empty")
        criterion_ids = [item.criterion_id for item in self.definition_of_done]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Definition of Done criterion IDs must be unique")
        if self.family is EvaluationFamily.WEB and not self.execution_profile.startswith("WEB_"):
            raise ValueError("web case studies require a WEB_* execution profile")
        if self.family is EvaluationFamily.JVM and not self.execution_profile.startswith("JVM_"):
            raise ValueError("JVM case studies require a JVM_* execution profile")
        if self.content_hash != case_study_content_hash(self.to_snapshot(include_hash=False)):
            raise ValueError("case-study content hash is inconsistent")
        _assert_no_mobile_scope(self.to_snapshot())

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "version": self.version,
            "title": self.title,
            "family": self.family.value,
            "execution_profile": self.execution_profile,
            "technologies": list(self.technologies),
            "project_brief": self.project_brief,
            "user_twin_roles": list(self.user_twin_roles),
            "constraints": list(self.constraints),
            "definition_of_done": [item.to_snapshot() for item in self.definition_of_done],
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def case_study_content_hash(payload: object) -> str:
    """Return the deterministic SHA-256 identity of semantic case-study content."""
    return _content_hash(payload)


def load_case_study_definition(path: Path) -> CaseStudyDefinition:
    """Load and validate one frozen JSON case-study definition."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    _assert_no_mobile_scope(payload)
    definition_of_done = tuple(
        DefinitionOfDoneItem(
            criterion_id=item["criterion_id"],
            description=item["description"],
            evidence=tuple(CaseStudyEvidenceKind(value) for value in item["evidence"]),
        )
        for item in payload["definition_of_done"]
    )
    without_hash = {key: value for key, value in payload.items() if key != "content_hash"}
    expected_hash = case_study_content_hash(without_hash)
    supplied_hash = payload.get("content_hash", expected_hash)
    return CaseStudyDefinition(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        version=payload["version"],
        title=payload["title"],
        family=EvaluationFamily(payload["family"]),
        execution_profile=payload["execution_profile"],
        technologies=tuple(payload["technologies"]),
        project_brief=payload["project_brief"],
        user_twin_roles=tuple(payload["user_twin_roles"]),
        constraints=tuple(payload["constraints"]),
        definition_of_done=definition_of_done,
        content_hash=supplied_hash,
    )
