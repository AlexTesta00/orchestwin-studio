"""Deterministic persona-candidate derivation from an approved Project Brief."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.brief_gate import (
    project_brief_gate_is_currently_approved,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaKind,
    PersonaSource,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
)
from orchestwin.workflow.gates import (
    HumanGate,
)

PERSONA_CANDIDATE_SCHEMA_VERSION: Final = 1
PERSONA_CANDIDATE_SET_SCHEMA_VERSION: Final = 1

_SHA256_HEX_LENGTH: Final = 64
_MAX_TARGET_USER_LENGTH: Final = 500


class PersonaCandidateDerivationStatus(StrEnum):
    """Stable outcome of deterministic candidate derivation."""

    DERIVED = "DERIVED"
    REJECTED = "REJECTED"


class PersonaCandidateIssueCode(StrEnum):
    """Stable reason candidate derivation cannot proceed."""

    BRIEF_NOT_APPROVED = "BRIEF_NOT_APPROVED"
    TARGET_USERS_MISSING = "TARGET_USERS_MISSING"
    TARGET_USERS_UNKNOWN = "TARGET_USERS_UNKNOWN"
    TARGET_USER_LIMIT_EXCEEDED = "TARGET_USER_LIMIT_EXCEEDED"
    DUPLICATE_TARGET_USER = "DUPLICATE_TARGET_USER"


def _normalized_text(
    value: str,
    *,
    label: str,
    maximum_length: int,
) -> str:
    """Return normalized non-empty text."""
    normalized = " ".join(value.split())

    if not normalized:
        raise ValueError(f"{label} must not be empty")

    if len(normalized) > maximum_length:
        raise ValueError(f"{label} exceeds maximum length")

    return normalized


def _is_sha256_digest(
    value: str,
) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_positive_integer(
    value: int,
    *,
    label: str,
) -> None:
    """Validate one non-boolean positive integer."""
    if (
        isinstance(
            value,
            bool,
        )
        or not isinstance(
            value,
            int,
        )
        or value < 1
    ):
        raise ValueError(f"{label} must be positive")


@dataclass(
    frozen=True,
    slots=True,
)
class ProjectPersonaCandidate:
    """One target-user role that may seed a future proto-persona."""

    project_id: UUID
    ordinal: int
    target_user: str
    role_observation: ProfileObservation
    source_brief_version_id: UUID
    source_brief_version_number: int
    source_brief_content_hash: str

    def __post_init__(self) -> None:
        """Protect provenance and prevent candidate-level fabrication."""
        _validate_positive_integer(
            self.ordinal,
            label="persona candidate ordinal",
        )
        _validate_positive_integer(
            self.source_brief_version_number,
            label=("persona candidate source brief version number"),
        )

        normalized_target_user = _normalized_text(
            self.target_user,
            label="target user",
            maximum_length=(_MAX_TARGET_USER_LENGTH),
        )
        object.__setattr__(
            self,
            "target_user",
            normalized_target_user,
        )

        if not _is_sha256_digest(self.source_brief_content_hash):
            raise ValueError(
                "persona candidate source brief hash must be a lowercase SHA-256 digest"
            )

        observation = self.role_observation

        if observation.observation_key != PersonaField.ROLE.observation_key:
            raise ValueError("a persona candidate may contain only the persona role observation")

        if (
            observation.value.kind is not ObservationValueKind.TEXT
            or observation.value.text != self.target_user
        ):
            raise ValueError("persona candidate role must match the target user exactly")

        if observation.epistemic_status is not EpistemicStatus.USER_PROVIDED:
            raise ValueError("Project Brief target users must remain USER_PROVIDED")

        if observation.confidence != ConfidenceScore(1.0):
            raise ValueError("Project Brief target-user roles must retain confidence 1.0")

        if observation.human_validation is not HumanValidationRequirement.NOT_REQUIRED:
            raise ValueError(
                "an explicitly supplied target-user role must not require re-validation"
            )

        references = observation.provenance.references

        if len(references) != 1:
            raise ValueError(
                "persona candidate role provenance must contain exactly one Project Brief reference"
            )

        reference = references[0]

        if (
            reference.source_kind is not EvidenceSourceKind.PROJECT_BRIEF
            or reference.source_id != str(self.source_brief_version_id)
            or reference.source_version != self.source_brief_version_number
            or reference.content_hash != self.source_brief_content_hash
        ):
            raise ValueError(
                "persona candidate role provenance must match the exact Project Brief version"
            )

        expected_locator = f"brief.target_users[{self.ordinal - 1}]"

        if reference.locator != expected_locator:
            raise ValueError("persona candidate role locator must match its target-user position")

    @property
    def future_profile_source(
        self,
    ) -> PersonaSource:
        """Return the origin of the future generated profile."""
        return PersonaSource.SYSTEM_PROPOSED

    @property
    def future_profile_kind(
        self,
    ) -> PersonaKind:
        """Return the kind of the future generated profile."""
        return PersonaKind.PROTO_PERSONA

    @property
    def confirmation_required(
        self,
    ) -> bool:
        """Require owner confirmation before User Twin creation."""
        return True

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return the complete deterministic candidate representation."""
        return {
            "schema_version": (PERSONA_CANDIDATE_SCHEMA_VERSION),
            "project_id": str(self.project_id),
            "ordinal": self.ordinal,
            "target_user": (self.target_user),
            "role_observation": (self.role_observation.to_snapshot()),
            "source_brief": {
                "version_id": str(self.source_brief_version_id),
                "version_number": (self.source_brief_version_number),
                "content_hash": (self.source_brief_content_hash),
            },
            "future_profile": {
                "source": (self.future_profile_source.value),
                "kind": (self.future_profile_kind.value),
                "confirmation_required": (self.confirmation_required),
            },
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the candidate deterministically."""
        return json.dumps(
            self.to_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @property
    def content_hash(
        self,
    ) -> str:
        """Return the SHA-256 hash of the candidate."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaCandidateDerivationResult:
    """Typed result of deterministic Project Brief candidate derivation."""

    status: PersonaCandidateDerivationStatus
    project_id: UUID
    brief_version_id: UUID
    brief_version_number: int
    brief_content_hash: str
    candidates: tuple[
        ProjectPersonaCandidate,
        ...,
    ] = ()
    issue: PersonaCandidateIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect successful and rejected result shapes."""
        _validate_positive_integer(
            self.brief_version_number,
            label=("candidate result brief version number"),
        )

        if not _is_sha256_digest(self.brief_content_hash):
            raise ValueError("candidate result brief hash must be a lowercase SHA-256 digest")

        derived = self.status is PersonaCandidateDerivationStatus.DERIVED

        if derived:
            if self.issue is not None:
                raise ValueError("successful candidate derivation must not contain an issue")

            if not (1 <= len(self.candidates) <= MAX_PROJECT_USER_TWINS):
                raise ValueError(
                    "successful candidate derivation requires between one and four candidates"
                )
        else:
            if self.issue is None or self.candidates:
                raise ValueError(
                    "rejected candidate derivation requires one issue and no candidates"
                )

        for (
            expected_ordinal,
            candidate,
        ) in enumerate(
            self.candidates,
            start=1,
        ):
            if (
                candidate.project_id != self.project_id
                or candidate.ordinal != expected_ordinal
                or candidate.source_brief_version_id != self.brief_version_id
                or candidate.source_brief_version_number != self.brief_version_number
                or candidate.source_brief_content_hash != self.brief_content_hash
            ):
                raise ValueError("persona candidates must belong to the exact derivation context")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic candidate-set snapshot."""
        return {
            "schema_version": (PERSONA_CANDIDATE_SET_SCHEMA_VERSION),
            "status": self.status.value,
            "project_id": str(self.project_id),
            "brief_version_id": str(self.brief_version_id),
            "brief_version_number": (self.brief_version_number),
            "brief_content_hash": (self.brief_content_hash),
            "candidates": [candidate.to_snapshot() for candidate in self.candidates],
            "issue": (None if self.issue is None else self.issue.value),
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the complete derivation deterministically."""
        return json.dumps(
            self.to_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @property
    def content_hash(
        self,
    ) -> str:
        """Return a stable hash of the complete derivation."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def derive_project_persona_candidates(
    *,
    brief_version: ProjectBriefVersion,
    brief_gate: HumanGate,
) -> PersonaCandidateDerivationResult:
    """Derive candidate roles only from approved Project Brief target users."""
    if not (
        project_brief_gate_is_currently_approved(
            brief_gate,
            brief_version,
        )
    ):
        return _rejected(
            brief_version,
            PersonaCandidateIssueCode.BRIEF_NOT_APPROVED,
        )

    brief = brief_version.brief

    if BriefField.TARGET_USERS in brief.unknown_fields:
        return _rejected(
            brief_version,
            PersonaCandidateIssueCode.TARGET_USERS_UNKNOWN,
        )

    target_users = tuple(brief.target_users or ())

    if not target_users:
        return _rejected(
            brief_version,
            PersonaCandidateIssueCode.TARGET_USERS_MISSING,
        )

    if len(target_users) > MAX_PROJECT_USER_TWINS:
        return _rejected(
            brief_version,
            PersonaCandidateIssueCode.TARGET_USER_LIMIT_EXCEEDED,
        )

    normalized_target_users = tuple(
        _normalized_text(
            target_user,
            label="target user",
            maximum_length=(_MAX_TARGET_USER_LENGTH),
        )
        for target_user in target_users
    )

    identity_keys = tuple(target_user.casefold() for target_user in normalized_target_users)

    if len(identity_keys) != len(set(identity_keys)):
        return _rejected(
            brief_version,
            PersonaCandidateIssueCode.DUPLICATE_TARGET_USER,
        )

    candidates = tuple(
        _candidate_from_target_user(
            brief_version=(brief_version),
            ordinal=ordinal,
            target_user=target_user,
        )
        for (
            ordinal,
            target_user,
        ) in enumerate(
            normalized_target_users,
            start=1,
        )
    )

    return PersonaCandidateDerivationResult(
        status=(PersonaCandidateDerivationStatus.DERIVED),
        project_id=(brief_version.project_id),
        brief_version_id=(brief_version.id),
        brief_version_number=(brief_version.version_number),
        brief_content_hash=(brief_version.content_hash),
        candidates=candidates,
    )


def _candidate_from_target_user(
    *,
    brief_version: ProjectBriefVersion,
    ordinal: int,
    target_user: str,
) -> ProjectPersonaCandidate:
    """Create one evidence-backed role candidate without added claims."""
    evidence = EvidenceReference(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=str(brief_version.id),
        source_version=(brief_version.version_number),
        content_hash=(brief_version.content_hash),
        locator=(f"brief.target_users[{ordinal - 1}]"),
        summary=("Target user group supplied in the approved Project Brief."),
    )

    role_observation = ProfileObservation(
        observation_key=(PersonaField.ROLE.observation_key),
        value=(ObservationValue.from_text(target_user)),
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=(ConfidenceScore(1.0)),
        provenance=(ObservationProvenance.from_references((evidence,))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )

    return ProjectPersonaCandidate(
        project_id=(brief_version.project_id),
        ordinal=ordinal,
        target_user=target_user,
        role_observation=(role_observation),
        source_brief_version_id=(brief_version.id),
        source_brief_version_number=(brief_version.version_number),
        source_brief_content_hash=(brief_version.content_hash),
    )


def _rejected(
    brief_version: ProjectBriefVersion,
    issue: PersonaCandidateIssueCode,
) -> PersonaCandidateDerivationResult:
    """Return one rejected derivation without invented candidates."""
    return PersonaCandidateDerivationResult(
        status=(PersonaCandidateDerivationStatus.REJECTED),
        project_id=(brief_version.project_id),
        brief_version_id=(brief_version.id),
        brief_version_number=(brief_version.version_number),
        brief_content_hash=(brief_version.content_hash),
        issue=issue,
    )
