from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.briefs import BriefField
from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

MAX_INSIGHT_TEXT_LENGTH: Final = 2000
MAX_SOURCE_ID_LENGTH: Final = 200
MAX_TARGET_CODE_LENGTH: Final = 16
BRIEF_LIST_TARGETS: Final = (
    BriefField.GOALS,
    BriefField.TARGET_USERS,
    BriefField.TECHNICAL_CONSTRAINTS,
    BriefField.FUNCTIONAL_REQUIREMENTS,
    BriefField.NON_FUNCTIONAL_REQUIREMENTS,
    BriefField.RISKS,
    BriefField.STAKEHOLDERS,
    BriefField.DEFINITION_OF_DONE,
)
DEFAULT_BRIEF_FIELD: Final = BriefField.FUNCTIONAL_REQUIREMENTS


class InsightSourceKind(StrEnum):
    TWIN_CHAT_INSIGHT = "TWIN_CHAT_INSIGHT"
    DESIGN_CRITIQUE = "DESIGN_CRITIQUE"
    SYNTHETIC_FINDING = "SYNTHETIC_FINDING"


class InsightTarget(StrEnum):
    BRIEF = "BRIEF"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"


@dataclass(frozen=True, slots=True)
class InsightApplication:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    source_kind: InsightSourceKind
    source_id: str
    source_twin_id: UUID | None
    text: str
    target: InsightTarget
    target_field: BriefField | None
    target_version_id: UUID
    target_version_number: int
    target_code: str | None
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, InsightSourceKind):
            raise ValueError("insight source kind must be an InsightSourceKind")
        if not isinstance(self.target, InsightTarget):
            raise ValueError("insight target must be an InsightTarget")
        for value, label, maximum in (
            (self.source_id, "insight source ID", MAX_SOURCE_ID_LENGTH),
            (self.text, "insight text", MAX_INSIGHT_TEXT_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum) != value:
                raise ValueError(f"{label} must be normalized")
        if (self.target is InsightTarget.BRIEF) != (self.target_field is not None):
            raise ValueError("only brief applications name a brief field")
        if self.target_field is not None and self.target_field not in BRIEF_LIST_TARGETS:
            raise ValueError("insights can only extend list fields of the brief")
        if (self.target is InsightTarget.BRIEF) == (self.target_code is not None):
            raise ValueError("requirements and design applications carry the created code")
        if (
            self.target_code is not None
            and normalize_optional_text(
                self.target_code, label="insight target code", maximum_length=MAX_TARGET_CODE_LENGTH
            )
            != self.target_code
        ):
            raise ValueError("insight target code must be normalized")
        validate_positive_integer(self.target_version_number, label="insight target version")
        validate_sha256(self.content_hash, label="insight application hash")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("insight application timestamp must be timezone-aware")
        if self.content_hash != insight_application_hash(self):
            raise ValueError("insight application hash is inconsistent")

    def semantic_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "source_kind": self.source_kind.value,
            "source_id": self.source_id,
            "source_twin_id": None if self.source_twin_id is None else str(self.source_twin_id),
            "text": self.text,
            "target": self.target.value,
            "target_field": None if self.target_field is None else self.target_field.value,
            "target_version_id": str(self.target_version_id),
            "target_version_number": self.target_version_number,
            "target_code": self.target_code,
            "created_at": self.created_at.isoformat(),
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def insight_application_hash(application: InsightApplication) -> str:
    return snapshot_content_hash(application.semantic_snapshot())


def create_insight_application(
    *,
    application_id: UUID,
    project_id: UUID,
    owner_user_id: UUID,
    source_kind: InsightSourceKind,
    source_id: str,
    source_twin_id: UUID | None,
    text: str,
    target: InsightTarget,
    target_field: BriefField | None,
    target_version_id: UUID,
    target_version_number: int,
    target_code: str | None,
    created_at: datetime,
) -> InsightApplication:
    values = {
        "id": application_id,
        "project_id": project_id,
        "owner_user_id": owner_user_id,
        "source_kind": source_kind,
        "source_id": normalize_required_text(
            source_id, label="insight source ID", maximum_length=MAX_SOURCE_ID_LENGTH
        ),
        "source_twin_id": source_twin_id,
        "text": normalize_required_text(
            text, label="insight text", maximum_length=MAX_INSIGHT_TEXT_LENGTH
        ),
        "target": target,
        "target_field": target_field,
        "target_version_id": target_version_id,
        "target_version_number": target_version_number,
        "target_code": normalize_optional_text(
            target_code, label="insight target code", maximum_length=MAX_TARGET_CODE_LENGTH
        ),
        "created_at": created_at,
    }
    semantic = {
        "id": str(application_id),
        "project_id": str(project_id),
        "owner_user_id": str(owner_user_id),
        "source_kind": source_kind.value,
        "source_id": values["source_id"],
        "source_twin_id": None if source_twin_id is None else str(source_twin_id),
        "text": values["text"],
        "target": target.value,
        "target_field": None if target_field is None else target_field.value,
        "target_version_id": str(target_version_id),
        "target_version_number": target_version_number,
        "target_code": values["target_code"],
        "created_at": created_at.isoformat(),
    }
    return InsightApplication(**values, content_hash=snapshot_content_hash(semantic))


def insight_application_from_snapshot(payload) -> InsightApplication:
    application = InsightApplication(
        id=UUID(str(payload["id"])),
        project_id=UUID(str(payload["project_id"])),
        owner_user_id=UUID(str(payload["owner_user_id"])),
        source_kind=InsightSourceKind(str(payload["source_kind"])),
        source_id=str(payload["source_id"]),
        source_twin_id=None
        if payload["source_twin_id"] is None
        else UUID(str(payload["source_twin_id"])),
        text=str(payload["text"]),
        target=InsightTarget(str(payload["target"])),
        target_field=None
        if payload["target_field"] is None
        else BriefField(str(payload["target_field"])),
        target_version_id=UUID(str(payload["target_version_id"])),
        target_version_number=int(payload["target_version_number"]),
        target_code=None if payload["target_code"] is None else str(payload["target_code"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        content_hash=str(payload["content_hash"]),
    )
    if application.to_snapshot() != dict(payload):
        raise ValueError("insight application snapshot is not canonical")
    return application


__all__ = [
    "BRIEF_LIST_TARGETS",
    "DEFAULT_BRIEF_FIELD",
    "MAX_INSIGHT_TEXT_LENGTH",
    "MAX_SOURCE_ID_LENGTH",
    "InsightApplication",
    "InsightSourceKind",
    "InsightTarget",
    "create_insight_application",
    "insight_application_from_snapshot",
    "insight_application_hash",
]
