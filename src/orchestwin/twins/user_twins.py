"""Immutable User Twin profiles and User Modeling snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.twins.epistemics import (
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaKind,
    PersonaProfileVersion,
    PersonaSource,
)

USER_TWIN_PROFILE_SCHEMA_VERSION: Final = 1
USER_MODELING_SNAPSHOT_SCHEMA_VERSION: Final = 1

MIN_PROJECT_USER_TWINS: Final = 1
MAX_PROJECT_USER_TWINS: Final = 4

_MAX_USER_TWIN_NAME_LENGTH: Final = 200
_SHA256_HEX_LENGTH: Final = 64


class UserTwinLifecycleStatus(StrEnum):
    """Lifecycle and validation states for a User Twin."""

    PROTO_UT = "PROTO_UT"
    PROJECT_GROUNDED_UT = "PROJECT_GROUNDED_UT"
    OWNER_APPROVED_UT = "OWNER_APPROVED_UT"
    EMPIRICALLY_GROUNDED_UT = "EMPIRICALLY_GROUNDED_UT"
    EMPIRICALLY_VALIDATED_UT = "EMPIRICALLY_VALIDATED_UT"


class UserTwinField(StrEnum):
    """Structured fields contained in a User Twin profile."""

    ROLE = "role"
    AGE_RANGE = "age_range"
    EXPERTISE = "expertise"
    GOALS = "goals"
    RECURRING_TASKS = "recurring_tasks"
    CONTEXT_OF_USE = "context_of_use"
    INFORMATION_NEEDS = "information_needs"
    DECISION_CRITERIA = "decision_criteria"
    PREFERRED_VOCABULARY = "preferred_vocabulary"
    FRUSTRATIONS = "frustrations"
    PAIN_POINTS = "pain_points"
    TRUST_CONCERNS = "trust_concerns"
    ACCESSIBILITY_NEEDS = "accessibility_needs"
    OPERATIONAL_CONSTRAINTS = "operational_constraints"
    TECHNICAL_LITERACY = "technical_literacy"
    RISK_SENSITIVITY = "risk_sensitivity"
    ASSUMPTIONS = "assumptions"

    @property
    def observation_key(self) -> str:
        """Return the stable observation key for this field."""
        return f"user_twin.{self.value}"


_USER_TWIN_FIELD_ORDER: Final = tuple(UserTwinField)

_USER_TWIN_FIELD_BY_KEY: Final = {field.observation_key: field for field in UserTwinField}

_REQUIRED_USER_TWIN_FIELDS: Final = frozenset(
    field for field in UserTwinField if field is not UserTwinField.AGE_RANGE
)

_TEXT_OR_UNCERTAINTY: Final = frozenset(
    {
        ObservationValueKind.TEXT,
        ObservationValueKind.UNKNOWN,
        ObservationValueKind.ABSTAINED,
    }
)

_ITEMS_OR_UNCERTAINTY: Final = frozenset(
    {
        ObservationValueKind.ITEMS,
        ObservationValueKind.UNKNOWN,
        ObservationValueKind.ABSTAINED,
    }
)

_ALLOWED_VALUE_KINDS: Final = {
    UserTwinField.ROLE: frozenset(
        {
            ObservationValueKind.TEXT,
        }
    ),
    UserTwinField.AGE_RANGE: (_TEXT_OR_UNCERTAINTY),
    UserTwinField.EXPERTISE: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.GOALS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.RECURRING_TASKS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.CONTEXT_OF_USE: (_TEXT_OR_UNCERTAINTY),
    UserTwinField.INFORMATION_NEEDS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.DECISION_CRITERIA: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.PREFERRED_VOCABULARY: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.FRUSTRATIONS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.PAIN_POINTS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.TRUST_CONCERNS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.ACCESSIBILITY_NEEDS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.OPERATIONAL_CONSTRAINTS: (_ITEMS_OR_UNCERTAINTY),
    UserTwinField.TECHNICAL_LITERACY: (_TEXT_OR_UNCERTAINTY),
    UserTwinField.RISK_SENSITIVITY: (_TEXT_OR_UNCERTAINTY),
    UserTwinField.ASSUMPTIONS: (_ITEMS_OR_UNCERTAINTY),
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


def _user_twin_field(
    observation: ProfileObservation,
) -> UserTwinField:
    """Resolve and validate the field of one User Twin observation."""
    field = _USER_TWIN_FIELD_BY_KEY.get(observation.observation_key)

    if field is None:
        raise ValueError("User Twin observations must use registered User Twin field keys")

    return field


def _ordered_observations(
    observations: Iterable[ProfileObservation],
) -> tuple[
    ProfileObservation,
    ...,
]:
    """Return unique observations in canonical User Twin order."""
    observations_by_field: dict[
        UserTwinField,
        ProfileObservation,
    ] = {}

    for observation in observations:
        field = _user_twin_field(observation)

        if field in observations_by_field:
            raise ValueError("User Twin observations must contain unique fields")

        observations_by_field[field] = observation

    return tuple(
        observations_by_field[field]
        for field in _USER_TWIN_FIELD_ORDER
        if field in observations_by_field
    )


@dataclass(
    frozen=True,
    slots=True,
)
class VersionedArtifactReference:
    """Exact reference to one immutable versioned artifact."""

    artifact_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        """Protect artifact version and hash metadata."""
        _validate_positive_integer(
            self.version_number,
            label="artifact version number",
        )

        if not _is_sha256_digest(self.content_hash):
            raise ValueError("artifact content hash must be a lowercase SHA-256 digest")

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic artifact reference snapshot."""
        return {
            "artifact_id": str(self.artifact_id),
            "version_number": (self.version_number),
            "content_hash": (self.content_hash),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class ConfirmedPersonaReference:
    """Exact confirmed persona version grounding a User Twin."""

    persona_id: UUID
    version_number: int
    content_hash: str
    source: PersonaSource
    kind: PersonaKind
    confirmation_status: PersonaConfirmationStatus

    def __post_init__(self) -> None:
        """Protect confirmation and persona-origin invariants."""
        _validate_positive_integer(
            self.version_number,
            label="persona version number",
        )

        if not _is_sha256_digest(self.content_hash):
            raise ValueError("persona content hash must be a lowercase SHA-256 digest")

        if self.confirmation_status is not PersonaConfirmationStatus.CONFIRMED:
            raise ValueError("a User Twin requires a confirmed persona")

        owner_persona = (
            self.source is PersonaSource.OWNER_PROVIDED and self.kind is PersonaKind.PERSONA
        )
        confirmed_proto_persona = (
            self.source is PersonaSource.SYSTEM_PROPOSED and self.kind is PersonaKind.PROTO_PERSONA
        )

        if not (owner_persona or confirmed_proto_persona):
            raise ValueError("confirmed persona source and kind are inconsistent")

    @classmethod
    def from_version(
        cls,
        version: PersonaProfileVersion,
    ) -> ConfirmedPersonaReference:
        """Create an exact reference from a confirmed persona version."""
        if not (version.profile.ready_for_twin_creation):
            raise ValueError("a User Twin requires a confirmed persona")

        return cls(
            persona_id=(version.persona_id),
            version_number=(version.version_number),
            content_hash=(version.content_hash),
            source=(version.profile.source),
            kind=version.profile.kind,
            confirmation_status=(version.profile.confirmation_status),
        )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic persona reference snapshot."""
        return {
            "persona_id": str(self.persona_id),
            "version_number": (self.version_number),
            "content_hash": (self.content_hash),
            "source": self.source.value,
            "kind": self.kind.value,
            "confirmation_status": (self.confirmation_status.value),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class UserTwinProfile:
    """One immutable project-grounded User Twin profile."""

    name: str
    persona_reference: ConfirmedPersonaReference
    project_brief_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str
    validation_status: UserTwinLifecycleStatus
    observations: tuple[
        ProfileObservation,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect profile completeness, ordering, and value shapes."""
        normalized_name = _normalized_text(
            self.name,
            label="User Twin name",
            maximum_length=(_MAX_USER_TWIN_NAME_LENGTH),
        )
        object.__setattr__(
            self,
            "name",
            normalized_name,
        )

        _validate_positive_integer(
            self.catalog_version,
            label="catalog version",
        )

        if not _is_sha256_digest(self.catalog_content_hash):
            raise ValueError("catalog content hash must be a lowercase SHA-256 digest")

        fields = tuple(_user_twin_field(observation) for observation in self.observations)
        field_set = set(fields)

        if len(fields) != len(field_set):
            raise ValueError("User Twin observations must contain unique fields")

        expected_order = tuple(field for field in _USER_TWIN_FIELD_ORDER if field in field_set)

        if fields != expected_order:
            raise ValueError("User Twin observations must use canonical field order")

        missing_fields = _REQUIRED_USER_TWIN_FIELDS - field_set

        if missing_fields:
            raise ValueError(
                "User Twin profile is missing "
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
                    "User Twin field "
                    f"{field.value} "
                    "does not support "
                    f"{observation.value.kind.value} "
                    "values"
                )

    @property
    def requires_human_validation(
        self,
    ) -> bool:
        """Return whether at least one observation requires review."""
        return any(observation.requires_human_validation for observation in self.observations)

    @property
    def unresolved_fields(
        self,
    ) -> tuple[
        UserTwinField,
        ...,
    ]:
        """Return fields represented as unknown or abstained."""
        return tuple(
            field
            for (
                observation,
                field,
            ) in zip(
                self.observations,
                (_user_twin_field(observation) for observation in self.observations),
                strict=True,
            )
            if observation.value.kind
            in {
                ObservationValueKind.UNKNOWN,
                ObservationValueKind.ABSTAINED,
            }
        )

    def observation_for(
        self,
        field: UserTwinField,
    ) -> ProfileObservation | None:
        """Return one structured observation by User Twin field."""
        for observation in self.observations:
            if observation.observation_key == field.observation_key:
                return observation

        return None

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable profile snapshot."""
        return {
            "schema_version": (USER_TWIN_PROFILE_SCHEMA_VERSION),
            "name": self.name,
            "persona_reference": (self.persona_reference.to_snapshot()),
            "project_brief_reference": (self.project_brief_reference.to_snapshot()),
            "agent_team_reference": (self.agent_team_reference.to_snapshot()),
            "catalog": {
                "version": (self.catalog_version),
                "content_hash": (self.catalog_content_hash),
            },
            "validation_status": (self.validation_status.value),
            "requires_human_validation": (self.requires_human_validation),
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
        """Return the SHA-256 hash of the complete User Twin profile."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class UserTwinProfileVersion:
    """One immutable version of a project-specific User Twin."""

    id: UUID
    project_id: UUID
    twin_id: UUID
    version_number: int
    profile: UserTwinProfile
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect numbering, hash, timestamp, and linear lineage."""
        _validate_positive_integer(
            self.version_number,
            label="User Twin version number",
        )

        if self.created_at.utcoffset() is None:
            raise ValueError("User Twin version timestamp must be timezone-aware")

        if not _is_sha256_digest(self.content_hash):
            raise ValueError("User Twin version content hash must be a lowercase SHA-256 digest")

        if self.content_hash != self.profile.content_hash:
            raise ValueError("User Twin version content hash must match its profile")

        expected_base_version = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base_version:
            raise ValueError(
                "User Twin version lineage must reference the immediately preceding version"
            )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic version snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "twin_id": str(self.twin_id),
            "version_number": (self.version_number),
            "based_on_version_number": (self.based_on_version_number),
            "content_hash": (self.content_hash),
            "profile": (self.profile.to_snapshot()),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": (self.created_at.isoformat()),
        }


@dataclass(
    frozen=True,
    slots=True,
)
class UserModelingSnapshot:
    """Complete personas and User Twins for one governed project state."""

    project_id: UUID
    project_brief_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str
    persona_versions: tuple[
        PersonaProfileVersion,
        ...,
    ]
    twin_versions: tuple[
        UserTwinProfileVersion,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect cardinality, ownership, ordering, and grounding."""
        _validate_positive_integer(
            self.catalog_version,
            label="snapshot catalog version",
        )

        if not _is_sha256_digest(self.catalog_content_hash):
            raise ValueError("snapshot catalog hash must be a lowercase SHA-256 digest")

        twin_count = len(self.twin_versions)

        if not (MIN_PROJECT_USER_TWINS <= twin_count <= MAX_PROJECT_USER_TWINS):
            raise ValueError("a User Modeling snapshot requires between one and four User Twins")

        if len(self.persona_versions) != twin_count:
            raise ValueError(
                "a User Modeling snapshot requires one confirmed persona version for each User Twin"
            )

        persona_ids = tuple(version.persona_id for version in self.persona_versions)
        twin_ids = tuple(version.twin_id for version in self.twin_versions)

        if len(persona_ids) != len(set(persona_ids)):
            raise ValueError("snapshot persona identities must be unique")

        if len(twin_ids) != len(set(twin_ids)):
            raise ValueError("snapshot User Twin identities must be unique")

        expected_persona_order = tuple(
            sorted(
                self.persona_versions,
                key=lambda version: version.persona_id.hex,
            )
        )
        expected_twin_order = tuple(
            sorted(
                self.twin_versions,
                key=lambda version: version.twin_id.hex,
            )
        )

        if self.persona_versions != expected_persona_order:
            raise ValueError("snapshot personas must use canonical identity order")

        if self.twin_versions != expected_twin_order:
            raise ValueError("snapshot User Twins must use canonical identity order")

        personas_by_id = {version.persona_id: version for version in self.persona_versions}

        for persona_version in self.persona_versions:
            if persona_version.project_id != self.project_id:
                raise ValueError("snapshot personas must belong to the snapshot project")

            if not (persona_version.profile.ready_for_twin_creation):
                raise ValueError("snapshot personas must be confirmed for User Twin creation")

        for twin_version in self.twin_versions:
            if twin_version.project_id != self.project_id:
                raise ValueError("snapshot User Twins must belong to the snapshot project")

            profile = twin_version.profile

            if (
                profile.project_brief_reference != self.project_brief_reference
                or profile.agent_team_reference != self.agent_team_reference
            ):
                raise ValueError(
                    "snapshot User Twins must use the same Project Brief and Agent Team"
                )

            if (
                profile.catalog_version != self.catalog_version
                or profile.catalog_content_hash != self.catalog_content_hash
            ):
                raise ValueError("snapshot User Twins must use the same agent catalog")

            persona_version = personas_by_id.get(profile.persona_reference.persona_id)

            if persona_version is None:
                raise ValueError(
                    "every User Twin must reference a persona contained in the snapshot"
                )

            expected_reference = ConfirmedPersonaReference.from_version(persona_version)

            if profile.persona_reference != expected_reference:
                raise ValueError("User Twin persona reference must match the exact persona version")

        referenced_persona_ids = {
            twin_version.profile.persona_reference.persona_id for twin_version in self.twin_versions
        }

        if referenced_persona_ids != set(persona_ids):
            raise ValueError("every snapshot persona must ground exactly one User Twin")

    @property
    def persona_count(self) -> int:
        """Return the number of confirmed persona versions."""
        return len(self.persona_versions)

    @property
    def twin_count(self) -> int:
        """Return the number of User Twin versions."""
        return len(self.twin_versions)

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable modeling snapshot."""
        return {
            "schema_version": (USER_MODELING_SNAPSHOT_SCHEMA_VERSION),
            "project_id": str(self.project_id),
            "project_brief_reference": (self.project_brief_reference.to_snapshot()),
            "agent_team_reference": (self.agent_team_reference.to_snapshot()),
            "catalog": {
                "version": (self.catalog_version),
                "content_hash": (self.catalog_content_hash),
            },
            "persona_versions": [version.to_snapshot() for version in self.persona_versions],
            "twin_versions": [version.to_snapshot() for version in self.twin_versions],
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the snapshot with deterministic ordering."""
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
        """Return the SHA-256 hash of the complete modeling snapshot."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(
    frozen=True,
    slots=True,
)
class UserModelingSnapshotVersion:
    """One immutable version of the complete User Modeling snapshot."""

    id: UUID
    project_id: UUID
    version_number: int
    snapshot: UserModelingSnapshot
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect project scope, hash, timestamp, and lineage."""
        _validate_positive_integer(
            self.version_number,
            label=("User Modeling snapshot version number"),
        )

        if self.snapshot.project_id != self.project_id:
            raise ValueError("User Modeling snapshot version must belong to its project")

        if self.created_at.utcoffset() is None:
            raise ValueError("User Modeling snapshot timestamp must be timezone-aware")

        if not _is_sha256_digest(self.content_hash):
            raise ValueError("User Modeling snapshot hash must be a lowercase SHA-256 digest")

        if self.content_hash != self.snapshot.content_hash:
            raise ValueError("User Modeling snapshot hash must match its content")

        expected_base_version = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base_version:
            raise ValueError(
                "User Modeling snapshot lineage must reference the immediately preceding version"
            )

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic snapshot-version representation."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": (self.version_number),
            "based_on_version_number": (self.based_on_version_number),
            "content_hash": (self.content_hash),
            "snapshot": (self.snapshot.to_snapshot()),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": (self.created_at.isoformat()),
        }


def create_project_grounded_user_twin(
    *,
    name: str,
    persona_version: PersonaProfileVersion,
    project_brief_reference: (VersionedArtifactReference),
    agent_team_reference: (VersionedArtifactReference),
    catalog_version: int,
    catalog_content_hash: str,
    observations: Iterable[ProfileObservation],
) -> UserTwinProfile:
    """Create a project-grounded twin from one confirmed persona."""
    return UserTwinProfile(
        name=name,
        persona_reference=(ConfirmedPersonaReference.from_version(persona_version)),
        project_brief_reference=(project_brief_reference),
        agent_team_reference=(agent_team_reference),
        catalog_version=(catalog_version),
        catalog_content_hash=(catalog_content_hash),
        validation_status=(UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
        observations=(_ordered_observations(observations)),
    )


def create_user_modeling_snapshot(
    *,
    project_id: UUID,
    project_brief_reference: (VersionedArtifactReference),
    agent_team_reference: (VersionedArtifactReference),
    catalog_version: int,
    catalog_content_hash: str,
    persona_versions: Iterable[PersonaProfileVersion],
    twin_versions: Iterable[UserTwinProfileVersion],
) -> UserModelingSnapshot:
    """Create a complete snapshot in canonical persona and twin order."""
    ordered_personas = tuple(
        sorted(
            persona_versions,
            key=lambda version: version.persona_id.hex,
        )
    )
    ordered_twins = tuple(
        sorted(
            twin_versions,
            key=lambda version: version.twin_id.hex,
        )
    )

    return UserModelingSnapshot(
        project_id=project_id,
        project_brief_reference=(project_brief_reference),
        agent_team_reference=(agent_team_reference),
        catalog_version=(catalog_version),
        catalog_content_hash=(catalog_content_hash),
        persona_versions=(ordered_personas),
        twin_versions=(ordered_twins),
    )
