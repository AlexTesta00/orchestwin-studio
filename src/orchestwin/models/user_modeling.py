"""Provider-independent contracts for User Modeling proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.twins.persona_candidates import (
    ProjectPersonaCandidate,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaKind,
    PersonaProfile,
    PersonaProfileVersion,
    PersonaSource,
)
from orchestwin.twins.user_twins import (
    MAX_PROJECT_USER_TWINS,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    VersionedArtifactReference,
)

USER_MODELING_PROPOSAL_SCHEMA_VERSION: Final = 1

_SHA256_HEX_LENGTH: Final = 64


class UserModelingProposalProviderKind(StrEnum):
    """Stable provider categories for User Modeling proposals."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class UserModelingProposalStatus(StrEnum):
    """Stable outcome of a proposal operation."""

    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"


class UserModelingProposalIssueCode(StrEnum):
    """Expected reasons a proposal cannot be produced."""

    CANDIDATES_REQUIRED = "CANDIDATES_REQUIRED"
    CANDIDATE_LIMIT_EXCEEDED = "CANDIDATE_LIMIT_EXCEEDED"
    CANDIDATE_PROJECT_MISMATCH = "CANDIDATE_PROJECT_MISMATCH"
    PERSONAS_REQUIRED = "PERSONAS_REQUIRED"
    PERSONA_LIMIT_EXCEEDED = "PERSONA_LIMIT_EXCEEDED"
    PERSONA_PROJECT_MISMATCH = "PERSONA_PROJECT_MISMATCH"
    DUPLICATE_PERSONA = "DUPLICATE_PERSONA"
    PERSONA_NOT_CONFIRMED = "PERSONA_NOT_CONFIRMED"


def _is_sha256_digest(
    value: str,
) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _positive_integer(
    value: int,
    *,
    label: str,
) -> None:
    """Validate one positive non-boolean integer."""
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


def _canonical_hash(
    payload: dict[str, object],
) -> str:
    """Hash one deterministic JSON-compatible payload."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaProposalRequest:
    """Request complete proto-personas for deterministic candidates."""

    project_id: UUID
    candidates: tuple[
        ProjectPersonaCandidate,
        ...,
    ]


@dataclass(
    frozen=True,
    slots=True,
)
class ProposedPersonaProfile:
    """One complete system-proposed proto-persona."""

    candidate_ordinal: int
    candidate_content_hash: str
    profile: PersonaProfile

    def __post_init__(self) -> None:
        """Protect candidate linkage and provisional persona semantics."""
        _positive_integer(
            self.candidate_ordinal,
            label=("persona proposal candidate ordinal"),
        )

        if not _is_sha256_digest(self.candidate_content_hash):
            raise ValueError("candidate content hash must be a lowercase SHA-256 digest")

        if (
            self.profile.source is not PersonaSource.SYSTEM_PROPOSED
            or self.profile.kind is not PersonaKind.PROTO_PERSONA
            or (
                self.profile.confirmation_status
                is not PersonaConfirmationStatus.PENDING_CONFIRMATION
            )
        ):
            raise ValueError("proposed personas must remain pending system-proposed proto-personas")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic proposed-persona snapshot."""
        return {
            "candidate_ordinal": (self.candidate_ordinal),
            "candidate_content_hash": (self.candidate_content_hash),
            "profile_content_hash": (self.profile.content_hash),
            "profile": (self.profile.to_snapshot()),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaProposalResult:
    """Typed result returned by persona-proposal adapters."""

    status: UserModelingProposalStatus
    provider_kind: UserModelingProposalProviderKind
    provider_id: str
    provider_version: int
    proposals: tuple[
        ProposedPersonaProfile,
        ...,
    ] = ()
    issue: UserModelingProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect provider metadata and result shape."""
        if not self.provider_id.strip():
            raise ValueError("provider ID must not be empty")

        _positive_integer(
            self.provider_version,
            label="provider version",
        )

        proposed = self.status is UserModelingProposalStatus.PROPOSED

        if proposed:
            if not self.proposals or self.issue is not None:
                raise ValueError("successful persona proposals require output and no issue")
        elif self.proposals or self.issue is None:
            raise ValueError("rejected persona proposals require one issue and no output")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic proposal-result snapshot."""
        return {
            "schema_version": (USER_MODELING_PROPOSAL_SCHEMA_VERSION),
            "status": self.status.value,
            "provider": {
                "kind": (self.provider_kind.value),
                "id": self.provider_id,
                "version": (self.provider_version),
            },
            "proposals": [proposal.to_snapshot() for proposal in self.proposals],
            "issue": (None if self.issue is None else self.issue.value),
        }

    @property
    def content_hash(
        self,
    ) -> str:
        """Return a stable hash of the complete adapter response."""
        return _canonical_hash(self.to_snapshot())


@dataclass(
    frozen=True,
    slots=True,
)
class UserTwinProposalRequest:
    """Request project-grounded twins for confirmed persona versions."""

    project_id: UUID
    persona_versions: tuple[
        PersonaProfileVersion,
        ...,
    ]
    project_brief_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str

    def __post_init__(self) -> None:
        """Protect catalog identity metadata."""
        _positive_integer(
            self.catalog_version,
            label="catalog version",
        )

        if not _is_sha256_digest(self.catalog_content_hash):
            raise ValueError("catalog content hash must be a lowercase SHA-256 digest")


@dataclass(
    frozen=True,
    slots=True,
)
class ProposedUserTwinProfile:
    """One project-grounded User Twin proposed for a persona."""

    persona_id: UUID
    persona_version_number: int
    persona_content_hash: str
    profile: UserTwinProfile

    def __post_init__(self) -> None:
        """Protect exact persona linkage and grounded state."""
        _positive_integer(
            self.persona_version_number,
            label=("proposed User Twin persona version number"),
        )

        if not _is_sha256_digest(self.persona_content_hash):
            raise ValueError("persona content hash must be a lowercase SHA-256 digest")

        reference = self.profile.persona_reference

        if (
            reference.persona_id != self.persona_id
            or reference.version_number != self.persona_version_number
            or reference.content_hash != self.persona_content_hash
        ):
            raise ValueError("proposed User Twin must reference the exact persona version")

        if self.profile.validation_status is not UserTwinLifecycleStatus.PROJECT_GROUNDED_UT:
            raise ValueError("proposed User Twins must begin as PROJECT_GROUNDED_UT")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic proposed-twin snapshot."""
        return {
            "persona_id": str(self.persona_id),
            "persona_version_number": (self.persona_version_number),
            "persona_content_hash": (self.persona_content_hash),
            "profile_content_hash": (self.profile.content_hash),
            "profile": (self.profile.to_snapshot()),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class UserTwinProposalResult:
    """Typed result returned by User Twin proposal adapters."""

    status: UserModelingProposalStatus
    provider_kind: UserModelingProposalProviderKind
    provider_id: str
    provider_version: int
    proposals: tuple[
        ProposedUserTwinProfile,
        ...,
    ] = ()
    issue: UserModelingProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect provider metadata and result shape."""
        if not self.provider_id.strip():
            raise ValueError("provider ID must not be empty")

        _positive_integer(
            self.provider_version,
            label="provider version",
        )

        proposed = self.status is UserModelingProposalStatus.PROPOSED

        if proposed:
            if not self.proposals or self.issue is not None:
                raise ValueError("successful User Twin proposals require output and no issue")
        elif self.proposals or self.issue is None:
            raise ValueError("rejected User Twin proposals require one issue and no output")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic proposal-result snapshot."""
        return {
            "schema_version": (USER_MODELING_PROPOSAL_SCHEMA_VERSION),
            "status": self.status.value,
            "provider": {
                "kind": (self.provider_kind.value),
                "id": self.provider_id,
                "version": (self.provider_version),
            },
            "proposals": [proposal.to_snapshot() for proposal in self.proposals],
            "issue": (None if self.issue is None else self.issue.value),
        }

    @property
    def content_hash(
        self,
    ) -> str:
        """Return a stable hash of the complete adapter response."""
        return _canonical_hash(self.to_snapshot())


class UserModelingProposalPort(Protocol):
    """Provider-independent boundary for User Modeling proposals."""

    async def propose_personas(
        self,
        request: PersonaProposalRequest,
    ) -> PersonaProposalResult:
        """Propose complete proto-personas from grounded candidates."""

    async def propose_user_twins(
        self,
        request: UserTwinProposalRequest,
    ) -> UserTwinProposalResult:
        """Propose project-grounded twins from confirmed personas."""


__all__ = [
    "MAX_PROJECT_USER_TWINS",
    "PersonaProposalRequest",
    "PersonaProposalResult",
    "ProposedPersonaProfile",
    "ProposedUserTwinProfile",
    "UserModelingProposalIssueCode",
    "UserModelingProposalPort",
    "UserModelingProposalProviderKind",
    "UserModelingProposalStatus",
    "UserTwinProposalRequest",
    "UserTwinProposalResult",
]
