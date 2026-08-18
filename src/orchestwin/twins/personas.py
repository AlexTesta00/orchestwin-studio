"""Immutable, versioned persona and proto-persona domain values."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.twins.epistemics import (
    ObservationValueKind,
    ProfileObservation,
)

PERSONA_PROFILE_SCHEMA_VERSION: Final = 1

_MAX_PERSONA_NAME_LENGTH: Final = 200
_MAX_PERSONA_REJECTION_REASON_LENGTH: Final = 2000
_SHA256_HEX_LENGTH: Final = 64


class PersonaSource(StrEnum):
    """Origin of a project-specific persona profile."""

    OWNER_PROVIDED = "OWNER_PROVIDED"
    SYSTEM_PROPOSED = "SYSTEM_PROPOSED"


class PersonaKind(StrEnum):
    """Whether a profile is an owner persona or a proto-persona."""

    PERSONA = "PERSONA"
    PROTO_PERSONA = "PROTO_PERSONA"


class PersonaConfirmationStatus(StrEnum):
    """Explicit owner-confirmation state for a persona profile."""

    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class PersonaField(StrEnum):
    """Structured fields available in a persona profile."""

    ROLE = "role"
    AGE_RANGE = "age_range"
    SUMMARY = "summary"
    GOALS = "goals"
    CONTEXT_OF_USE = "context_of_use"

    @property
    def observation_key(self) -> str:
        """Return the stable observation key for this persona field."""
        return f"persona.{self.value}"


class PersonaDecisionStatus(StrEnum):
    """Stable outcomes of confirming or rejecting a proto-persona."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class PersonaDecisionIssueCode(StrEnum):
    """Stable reasons a proto-persona decision cannot be applied."""

    NOT_A_PROTO_PERSONA = "NOT_A_PROTO_PERSONA"
    ALREADY_CONFIRMED = "ALREADY_CONFIRMED"
    ALREADY_REJECTED = "ALREADY_REJECTED"
    REASON_REQUIRED = "REASON_REQUIRED"
    REASON_TOO_LONG = "REASON_TOO_LONG"


_PERSONA_FIELD_ORDER: Final = tuple(PersonaField)
_PERSONA_FIELD_BY_KEY: Final = {field.observation_key: field for field in PersonaField}
_REQUIRED_PERSONA_FIELDS: Final = frozenset(
    {
        PersonaField.ROLE,
        PersonaField.SUMMARY,
        PersonaField.GOALS,
        PersonaField.CONTEXT_OF_USE,
    }
)
_ALLOWED_VALUE_KINDS: Final = {
    PersonaField.ROLE: frozenset(
        {
            ObservationValueKind.TEXT,
        }
    ),
    PersonaField.AGE_RANGE: frozenset(
        {
            ObservationValueKind.TEXT,
            ObservationValueKind.UNKNOWN,
            ObservationValueKind.ABSTAINED,
        }
    ),
    PersonaField.SUMMARY: frozenset(
        {
            ObservationValueKind.TEXT,
        }
    ),
    PersonaField.GOALS: frozenset(
        {
            ObservationValueKind.ITEMS,
            ObservationValueKind.UNKNOWN,
            ObservationValueKind.ABSTAINED,
        }
    ),
    PersonaField.CONTEXT_OF_USE: frozenset(
        {
            ObservationValueKind.TEXT,
            ObservationValueKind.UNKNOWN,
            ObservationValueKind.ABSTAINED,
        }
    ),
}


def _normalized_text(
    value: str,
    *,
    label: str,
    maximum_length: int,
) -> str:
    """Return normalized non-empty text or raise a domain error."""
    normalized = " ".join(value.split())

    if not normalized:
        raise ValueError(f"{label} must not be empty")

    if len(normalized) > maximum_length:
        raise ValueError(f"{label} exceeds maximum length")

    return normalized


def _persona_field(
    observation: ProfileObservation,
) -> PersonaField:
    """Resolve and validate the persona field of one observation."""
    field = _PERSONA_FIELD_BY_KEY.get(observation.observation_key)

    if field is None:
        raise ValueError("persona observations must use registered persona field keys")

    return field


def _ordered_observations(
    observations: Iterable[ProfileObservation],
) -> tuple[
    ProfileObservation,
    ...,
]:
    """Return unique observations in canonical persona-field order."""
    observations_by_field: dict[
        PersonaField,
        ProfileObservation,
    ] = {}

    for observation in observations:
        field = _persona_field(observation)

        if field in observations_by_field:
            raise ValueError("persona observations must contain unique fields")

        observations_by_field[field] = observation

    return tuple(
        observations_by_field[field]
        for field in _PERSONA_FIELD_ORDER
        if field in observations_by_field
    )


def _is_sha256_digest(
    value: str,
) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return len(value) == _SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaProfile:
    """One immutable owner persona or system-proposed proto-persona."""

    name: str
    source: PersonaSource
    kind: PersonaKind
    confirmation_status: PersonaConfirmationStatus
    observations: tuple[
        ProfileObservation,
        ...,
    ]
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        """Protect profile shape, provenance label, and decision state."""
        normalized_name = _normalized_text(
            self.name,
            label="persona name",
            maximum_length=(_MAX_PERSONA_NAME_LENGTH),
        )
        object.__setattr__(
            self,
            "name",
            normalized_name,
        )

        fields = tuple(_persona_field(observation) for observation in self.observations)
        field_set = set(fields)

        if len(fields) != len(field_set):
            raise ValueError("persona observations must contain unique fields")

        expected_order = tuple(field for field in _PERSONA_FIELD_ORDER if field in field_set)

        if fields != expected_order:
            raise ValueError("persona observations must use canonical field order")

        missing_fields = _REQUIRED_PERSONA_FIELDS - field_set

        if missing_fields:
            raise ValueError(
                "persona profile is missing "
                "required fields: " + ", ".join(sorted(field.value for field in missing_fields))
            )

        for (
            observation,
            field,
        ) in zip(
            self.observations,
            fields,
            strict=True,
        ):
            if observation.value.kind not in _ALLOWED_VALUE_KINDS[field]:
                raise ValueError(
                    "persona field "
                    f"{field.value} "
                    "does not support "
                    f"{observation.value.kind.value} "
                    "values"
                )

        owner_profile = (
            self.source is PersonaSource.OWNER_PROVIDED
            and self.kind is PersonaKind.PERSONA
            and self.confirmation_status is PersonaConfirmationStatus.CONFIRMED
        )
        proposed_profile = (
            self.source is PersonaSource.SYSTEM_PROPOSED and self.kind is PersonaKind.PROTO_PERSONA
        )

        if not (owner_profile or proposed_profile):
            raise ValueError("persona source, kind, and confirmation status are inconsistent")

        if self.confirmation_status is PersonaConfirmationStatus.REJECTED:
            if self.rejection_reason is None:
                raise ValueError("a rejected proto-persona requires a rejection reason")

            normalized_reason = _normalized_text(
                self.rejection_reason,
                label=("persona rejection reason"),
                maximum_length=(_MAX_PERSONA_REJECTION_REASON_LENGTH),
            )
            object.__setattr__(
                self,
                "rejection_reason",
                normalized_reason,
            )
        elif self.rejection_reason is not None:
            raise ValueError("only a rejected proto-persona may contain a rejection reason")

    @property
    def requires_confirmation(
        self,
    ) -> bool:
        """Return whether the owner must decide this proto-persona."""
        return self.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION

    @property
    def ready_for_twin_creation(
        self,
    ) -> bool:
        """Return whether this profile may ground a User Twin."""
        return self.confirmation_status is PersonaConfirmationStatus.CONFIRMED

    def observation_for(
        self,
        field: PersonaField,
    ) -> ProfileObservation | None:
        """Return one structured persona observation by field."""
        for observation in self.observations:
            if observation.observation_key == field.observation_key:
                return observation

        return None

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable profile snapshot."""
        return {
            "schema_version": (PERSONA_PROFILE_SCHEMA_VERSION),
            "name": self.name,
            "source": self.source.value,
            "kind": self.kind.value,
            "confirmation_status": (self.confirmation_status.value),
            "rejection_reason": (self.rejection_reason),
            "observations": [observation.to_snapshot() for observation in self.observations],
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the profile with deterministic ordering."""
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
        """Return the SHA-256 hash of the complete profile content."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaDecisionResult:
    """Typed result of confirming or rejecting a proto-persona."""

    status: PersonaDecisionStatus
    profile: PersonaProfile
    issue: PersonaDecisionIssueCode | None = None

    def __post_init__(self) -> None:
        """Associate issues only with rejected decisions."""
        rejected = self.status is PersonaDecisionStatus.REJECTED

        if rejected != (self.issue is not None):
            raise ValueError("rejected persona decisions require exactly one issue")


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaProfileVersion:
    """One immutable version of a project-specific persona profile."""

    id: UUID
    project_id: UUID
    persona_id: UUID
    version_number: int
    profile: PersonaProfile
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect version numbering, lineage, timestamp, and hash."""
        if (
            isinstance(
                self.version_number,
                bool,
            )
            or not isinstance(
                self.version_number,
                int,
            )
            or self.version_number < 1
        ):
            raise ValueError("persona version number must be positive")

        if self.created_at.utcoffset() is None:
            raise ValueError("persona version timestamp must be timezone-aware")

        if not _is_sha256_digest(self.content_hash):
            raise ValueError("persona version content hash must be a lowercase SHA-256 digest")

        if self.content_hash != self.profile.content_hash:
            raise ValueError("persona version content hash must match its profile")

        expected_base_version = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base_version:
            raise ValueError(
                "persona version lineage must reference the immediately preceding version"
            )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable version snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "persona_id": str(self.persona_id),
            "version_number": (self.version_number),
            "based_on_version_number": (self.based_on_version_number),
            "content_hash": (self.content_hash),
            "profile": (self.profile.to_snapshot()),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": (self.created_at.isoformat()),
        }


def create_owner_provided_persona(
    *,
    name: str,
    observations: Iterable[ProfileObservation],
) -> PersonaProfile:
    """Create a confirmed persona explicitly supplied by the owner."""
    return PersonaProfile(
        name=name,
        source=(PersonaSource.OWNER_PROVIDED),
        kind=PersonaKind.PERSONA,
        confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
        observations=(_ordered_observations(observations)),
    )


def create_proto_persona(
    *,
    name: str,
    observations: Iterable[ProfileObservation],
) -> PersonaProfile:
    """Create a system-proposed proto-persona awaiting confirmation."""
    return PersonaProfile(
        name=name,
        source=(PersonaSource.SYSTEM_PROPOSED),
        kind=(PersonaKind.PROTO_PERSONA),
        confirmation_status=(PersonaConfirmationStatus.PENDING_CONFIRMATION),
        observations=(_ordered_observations(observations)),
    )


def confirm_proto_persona(
    profile: PersonaProfile,
) -> PersonaDecisionResult:
    """Confirm one pending proto-persona without mutating the source."""
    if (
        profile.source is not PersonaSource.SYSTEM_PROPOSED
        or profile.kind is not PersonaKind.PROTO_PERSONA
    ):
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.NOT_A_PROTO_PERSONA),
        )

    if profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.NO_CHANGE),
            profile=profile,
        )

    if profile.confirmation_status is PersonaConfirmationStatus.REJECTED:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.ALREADY_REJECTED),
        )

    return PersonaDecisionResult(
        status=(PersonaDecisionStatus.APPLIED),
        profile=replace(
            profile,
            confirmation_status=(PersonaConfirmationStatus.CONFIRMED),
        ),
    )


def reject_proto_persona(
    profile: PersonaProfile,
    *,
    reason: str,
) -> PersonaDecisionResult:
    """Reject one pending proto-persona with an explicit owner reason."""
    if (
        profile.source is not PersonaSource.SYSTEM_PROPOSED
        or profile.kind is not PersonaKind.PROTO_PERSONA
    ):
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.NOT_A_PROTO_PERSONA),
        )

    if profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.ALREADY_CONFIRMED),
        )

    if profile.confirmation_status is PersonaConfirmationStatus.REJECTED:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.NO_CHANGE),
            profile=profile,
        )

    normalized_reason = " ".join(reason.split())

    if not normalized_reason:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.REASON_REQUIRED),
        )

    if len(normalized_reason) > _MAX_PERSONA_REJECTION_REASON_LENGTH:
        return PersonaDecisionResult(
            status=(PersonaDecisionStatus.REJECTED),
            profile=profile,
            issue=(PersonaDecisionIssueCode.REASON_TOO_LONG),
        )

    return PersonaDecisionResult(
        status=(PersonaDecisionStatus.APPLIED),
        profile=replace(
            profile,
            confirmation_status=(PersonaConfirmationStatus.REJECTED),
            rejection_reason=(normalized_reason),
        ),
    )
