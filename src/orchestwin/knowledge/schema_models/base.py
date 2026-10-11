from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, Strict

from orchestwin.knowledge.state import (
    MAX_COMMIT_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MIN_COMMIT_LENGTH,
)
from orchestwin.projects.briefs import BriefField
from orchestwin.twins.epistemics import EvidenceSourceKind

_UUID_PATTERN: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_SHA256_PATTERN: Final = r"^[0-9a-f]{64}$"
_TIMESTAMP_PATTERN: Final = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?"
    r"(Z|[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?)$"
)
_SLUG_PATTERN: Final = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_COMMIT_PATTERN: Final = rf"^[0-9a-f]{{{MIN_COMMIT_LENGTH},{MAX_COMMIT_LENGTH}}}$"


def _code(prefix: str) -> str:
    return rf"^{prefix}-[0-9]{{3,6}}$"


def _never_null(value: object) -> object:
    if value is None:
        raise ValueError("an optional property is left out when it has no value, never null")
    return value


type Uuid = Annotated[
    str,
    Field(
        pattern=_UUID_PATTERN,
        description="Canonical lowercase UUID in the 8-4-4-4-12 hexadecimal form.",
    ),
]
type Sha256 = Annotated[
    str,
    Field(
        pattern=_SHA256_PATTERN,
        description="SHA-256 digest written as 64 lowercase hexadecimal characters.",
    ),
]
type Timestamp = Annotated[
    str,
    Field(
        pattern=_TIMESTAMP_PATTERN,
        description=(
            "Timezone-aware ISO 8601 date and time as written by Python's datetime.isoformat, "
            "for example 2026-09-27T18:00:00+00:00."
        ),
    ),
]
type CommitHash = Annotated[
    str,
    Field(
        pattern=_COMMIT_PATTERN,
        description=(
            f"Hash of a git commit written as {MIN_COMMIT_LENGTH} to {MAX_COMMIT_LENGTH} "
            "lowercase hexadecimal characters."
        ),
    ),
]

_BY_VALUE: Final = Strict(False)
_OPTIONAL: Final = BeforeValidator(_never_null)
_Version = Annotated[int, Field(ge=1)]
_Count = Annotated[int, Field(ge=0)]
_Confidence = Annotated[float, Field(ge=0, le=1)]
_BriefFieldName = Annotated[BriefField, _BY_VALUE]
_RequirementCode = Annotated[str, Field(pattern=_code("REQ"))]
_ScreenCode = Annotated[str, Field(pattern=_code("SCR"))]
_AlternativeCode = Annotated[str, Field(pattern=_code("DES"))]
_Summary = Annotated[str, Field(max_length=MAX_SUMMARY_LENGTH)]
_CriterionCode = Annotated[str, Field(pattern=_code("AC"))]
_OwnerNote = Annotated[str, Field(max_length=MAX_TASK_NOTE_LENGTH)]
_TwinName = Annotated[str, Field(min_length=1)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class CatalogReference(_Record):
    version: _Version = Field(description="Version of the fixed agent catalog that was used.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that agent catalog.")


class ArtifactReference(_Record):
    artifact_id: Uuid = Field(description="Identifier of the referenced artifact version.")
    version_number: _Version = Field(description="Version number of the referenced artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the referenced artifact content.")


class ApprovedVersionReference(_Record):
    version_id: Uuid = Field(description="Identifier of the approved version.")
    version_number: _Version = Field(description="Version number of the approved artifact.")
    content_hash: Sha256 = Field(description="SHA-256 digest of the approved artifact content.")


class UserTwinReference(_Record):
    twin_id: Uuid = Field(description="Stable identifier of the user twin across its versions.")
    version_number: _Version = Field(description="Version of the user twin that is referenced.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that user twin version.")
    name: str = Field(description="Display name of the user twin at that version.")


class EvidenceReference(_Record):
    source_kind: Annotated[EvidenceSourceKind, _BY_VALUE] = Field(
        description="Category of the source that supports the statement."
    )
    source_id: str = Field(description="Identifier of the source, such as an artifact identifier.")
    source_version: _Version | None = Field(
        description="Version of the source, or null when the source has no version."
    )
    content_hash: Sha256 | None = Field(
        description="SHA-256 digest of the source content, or null when it is not known."
    )
    locator: str | None = Field(
        description="Position inside the source, such as a field name, or null."
    )
    summary: str | None = Field(description="Short summary of what the source says, or null.")
