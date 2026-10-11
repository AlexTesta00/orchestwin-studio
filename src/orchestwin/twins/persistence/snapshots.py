"""Pure mapping between User Modeling domain values and persistence records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

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
    PERSONA_PROFILE_SCHEMA_VERSION,
    PersonaConfirmationStatus,
    PersonaKind,
    PersonaProfile,
    PersonaProfileVersion,
    PersonaSource,
)
from orchestwin.twins.record_values import datetime_value as _datetime
from orchestwin.twins.record_values import field as _field
from orchestwin.twins.record_values import integer as _integer
from orchestwin.twins.record_values import optional_integer as _optional_integer
from orchestwin.twins.record_values import optional_string as _optional_string
from orchestwin.twins.record_values import real as _real
from orchestwin.twins.record_values import sequence as _sequence
from orchestwin.twins.record_values import string as _string
from orchestwin.twins.record_values import uuid_value as _uuid
from orchestwin.twins.user_twins import (
    USER_MODELING_SNAPSHOT_SCHEMA_VERSION,
    USER_TWIN_PROFILE_SCHEMA_VERSION,
    ConfirmedPersonaReference,
    UserModelingSnapshot,
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    UserTwinProfile,
    UserTwinProfileVersion,
    VersionedArtifactReference,
)

type PersistenceRecord = dict[
    str,
    object,
]


def persona_version_to_record(
    version: PersonaProfileVersion,
) -> PersistenceRecord:
    """Convert one immutable persona version into its database record."""
    profile = version.profile

    return {
        "id": version.id,
        "project_id": version.project_id,
        "persona_id": version.persona_id,
        "version_number": version.version_number,
        "based_on_version_number": (version.based_on_version_number),
        "profile_schema_version": (PERSONA_PROFILE_SCHEMA_VERSION),
        "profile_source": (profile.source.value),
        "profile_kind": (profile.kind.value),
        "confirmation_status": (profile.confirmation_status.value),
        "rejection_reason": (profile.rejection_reason),
        "content_hash": (version.content_hash),
        "profile_snapshot": (profile.to_snapshot()),
        "created_by_user_id": (version.created_by_user_id),
        "created_at": version.created_at,
    }


def persona_version_from_record(
    record: Mapping[
        str,
        object,
    ],
) -> PersonaProfileVersion:
    """Reconstruct and validate one persona version database record."""
    profile_snapshot = _field(record, "profile_snapshot", _mapping, "persona profile snapshot")
    profile = _persona_profile_from_snapshot(profile_snapshot)

    if (
        _field(record, "profile_schema_version", _integer, "persona profile schema version")
        != PERSONA_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError("persisted persona schema version does not match the domain schema")

    if _field(record, "profile_source", _string, "persona source") != profile.source.value:
        raise ValueError("persisted persona source does not match its snapshot")

    if _field(record, "profile_kind", _string, "persona kind") != profile.kind.value:
        raise ValueError("persisted persona kind does not match its snapshot")

    if (
        _field(record, "confirmation_status", _string, "persona confirmation status")
        != profile.confirmation_status.value
    ):
        raise ValueError("persisted persona confirmation status does not match its snapshot")

    if (
        _optional_string(
            record.get("rejection_reason"),
            label="persona rejection reason",
        )
        != profile.rejection_reason
    ):
        raise ValueError("persisted persona rejection reason does not match its snapshot")

    return PersonaProfileVersion(
        id=_field(record, "id", _uuid, "persona version ID"),
        project_id=_field(record, "project_id", _uuid, "persona project ID"),
        persona_id=_field(record, "persona_id", _uuid, "persona ID"),
        version_number=_field(record, "version_number", _integer, "persona version number"),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("persona base version number"),
            )
        ),
        profile=profile,
        content_hash=_field(record, "content_hash", _string, "persona content hash"),
        created_by_user_id=_field(record, "created_by_user_id", _uuid, "persona creator ID"),
        created_at=_field(record, "created_at", _datetime, "persona creation timestamp"),
    )


def user_twin_version_to_record(
    version: UserTwinProfileVersion,
) -> PersistenceRecord:
    """Convert one immutable User Twin version into a database record."""
    profile = version.profile

    return {
        "id": version.id,
        "project_id": version.project_id,
        "twin_id": version.twin_id,
        "version_number": version.version_number,
        "based_on_version_number": (version.based_on_version_number),
        "profile_schema_version": (USER_TWIN_PROFILE_SCHEMA_VERSION),
        "persona_id": (profile.persona_reference.persona_id),
        "persona_version_number": (profile.persona_reference.version_number),
        "validation_status": (profile.validation_status.value),
        "content_hash": (version.content_hash),
        "profile_snapshot": (profile.to_snapshot()),
        "created_by_user_id": (version.created_by_user_id),
        "created_at": version.created_at,
    }


def user_twin_version_from_record(
    record: Mapping[
        str,
        object,
    ],
) -> UserTwinProfileVersion:
    """Reconstruct and validate one User Twin version record."""
    profile_snapshot = _field(record, "profile_snapshot", _mapping, "User Twin profile snapshot")
    profile = _user_twin_profile_from_snapshot(profile_snapshot)

    if (
        _field(record, "profile_schema_version", _integer, "User Twin schema version")
        != USER_TWIN_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError("persisted User Twin schema version does not match the domain schema")

    if (
        _field(record, "persona_id", _uuid, "User Twin persona ID")
        != profile.persona_reference.persona_id
    ):
        raise ValueError("persisted User Twin persona ID does not match its snapshot")

    if (
        _field(record, "persona_version_number", _integer, "User Twin persona version")
        != profile.persona_reference.version_number
    ):
        raise ValueError("persisted User Twin persona version does not match its snapshot")

    if (
        _field(record, "validation_status", _string, "User Twin validation status")
        != profile.validation_status.value
    ):
        raise ValueError("persisted User Twin lifecycle status does not match its snapshot")

    return UserTwinProfileVersion(
        id=_field(record, "id", _uuid, "User Twin version ID"),
        project_id=_field(record, "project_id", _uuid, "User Twin project ID"),
        twin_id=_field(record, "twin_id", _uuid, "User Twin ID"),
        version_number=_field(record, "version_number", _integer, "User Twin version number"),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("User Twin base version number"),
            )
        ),
        profile=profile,
        content_hash=_field(record, "content_hash", _string, "User Twin content hash"),
        created_by_user_id=_field(record, "created_by_user_id", _uuid, "User Twin creator ID"),
        created_at=_field(record, "created_at", _datetime, "User Twin creation timestamp"),
    )


def user_modeling_snapshot_version_to_record(
    version: UserModelingSnapshotVersion,
) -> PersistenceRecord:
    """Convert one complete User Modeling version into a database record."""
    snapshot = version.snapshot
    brief = snapshot.project_brief_reference
    team = snapshot.agent_team_reference

    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": (version.based_on_version_number),
        "snapshot_schema_version": (USER_MODELING_SNAPSHOT_SCHEMA_VERSION),
        "brief_version_id": (brief.artifact_id),
        "brief_version_number": (brief.version_number),
        "brief_content_hash": (brief.content_hash),
        "team_proposal_id": (team.artifact_id),
        "team_version_number": (team.version_number),
        "team_content_hash": (team.content_hash),
        "catalog_version": (snapshot.catalog_version),
        "catalog_content_hash": (snapshot.catalog_content_hash),
        "persona_count": (snapshot.persona_count),
        "twin_count": (snapshot.twin_count),
        "content_hash": (version.content_hash),
        "snapshot": (snapshot.to_snapshot()),
        "created_by_user_id": (version.created_by_user_id),
        "created_at": version.created_at,
    }


def user_modeling_snapshot_version_from_record(
    record: Mapping[
        str,
        object,
    ],
) -> UserModelingSnapshotVersion:
    """Reconstruct and validate a complete persisted modeling version."""
    snapshot_payload = _field(record, "snapshot", _mapping, "User Modeling snapshot")
    snapshot = _user_modeling_snapshot_from_snapshot(snapshot_payload)

    if (
        _field(record, "snapshot_schema_version", _integer, "User Modeling snapshot schema version")
        != USER_MODELING_SNAPSHOT_SCHEMA_VERSION
    ):
        raise ValueError("persisted User Modeling schema version does not match the domain schema")

    brief = snapshot.project_brief_reference
    team = snapshot.agent_team_reference

    persisted_brief = VersionedArtifactReference(
        artifact_id=_field(record, "brief_version_id", _uuid, "brief version ID"),
        version_number=_field(record, "brief_version_number", _integer, "brief version number"),
        content_hash=_field(record, "brief_content_hash", _string, "brief content hash"),
    )

    persisted_team = VersionedArtifactReference(
        artifact_id=_field(record, "team_proposal_id", _uuid, "team proposal ID"),
        version_number=_field(record, "team_version_number", _integer, "team version number"),
        content_hash=_field(record, "team_content_hash", _string, "team content hash"),
    )

    if persisted_brief != brief:
        raise ValueError(
            "persisted Project Brief reference does not match the User Modeling snapshot"
        )

    if persisted_team != team:
        raise ValueError("persisted Agent Team reference does not match the User Modeling snapshot")

    if (
        _field(record, "catalog_version", _integer, "catalog version") != snapshot.catalog_version
        or _field(record, "catalog_content_hash", _string, "catalog content hash")
        != snapshot.catalog_content_hash
    ):
        raise ValueError("persisted catalog metadata does not match the User Modeling snapshot")

    if (
        _field(record, "persona_count", _integer, "persona count") != snapshot.persona_count
        or _field(record, "twin_count", _integer, "User Twin count") != snapshot.twin_count
    ):
        raise ValueError("persisted User Modeling counts do not match the snapshot")

    return UserModelingSnapshotVersion(
        id=_field(record, "id", _uuid, "User Modeling version ID"),
        project_id=_field(record, "project_id", _uuid, "User Modeling project ID"),
        version_number=_field(record, "version_number", _integer, "User Modeling version number"),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("User Modeling base version"),
            )
        ),
        snapshot=snapshot,
        content_hash=_field(record, "content_hash", _string, "User Modeling content hash"),
        created_by_user_id=_field(record, "created_by_user_id", _uuid, "User Modeling creator ID"),
        created_at=_field(record, "created_at", _datetime, "User Modeling creation timestamp"),
    )


def _persona_profile_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> PersonaProfile:
    """Reconstruct one PersonaProfile from canonical JSON."""
    schema_version = _field(payload, "schema_version", _integer, "persona schema version")

    if schema_version != PERSONA_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported persona profile schema")

    observations = tuple(
        _profile_observation_from_snapshot(item)
        for item in _field(payload, "observations", _mapping_sequence, "persona observations")
    )

    profile = PersonaProfile(
        name=_field(payload, "name", _string, "persona name"),
        source=PersonaSource(_field(payload, "source", _string, "persona source")),
        kind=PersonaKind(_field(payload, "kind", _string, "persona kind")),
        confirmation_status=PersonaConfirmationStatus(
            _field(payload, "confirmation_status", _string, "persona confirmation status")
        ),
        rejection_reason=(
            _optional_string(
                payload.get("rejection_reason"),
                label=("persona rejection reason"),
            )
        ),
        observations=observations,
        archived=payload.get("archived", False),
    )

    _require_snapshot_match(
        actual=profile.to_snapshot(),
        expected=payload,
        label="persona profile",
    )

    return profile


def _persona_version_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> PersonaProfileVersion:
    """Reconstruct a nested PersonaProfileVersion snapshot."""
    profile = _persona_profile_from_snapshot(
        _field(payload, "profile", _mapping, "persona version profile")
    )

    version = PersonaProfileVersion(
        id=_field(payload, "id", _uuid, "persona version ID"),
        project_id=_field(payload, "project_id", _uuid, "persona project ID"),
        persona_id=_field(payload, "persona_id", _uuid, "persona ID"),
        version_number=_field(payload, "version_number", _integer, "persona version number"),
        based_on_version_number=(
            _optional_integer(
                payload.get("based_on_version_number"),
                label="persona base version",
            )
        ),
        profile=profile,
        content_hash=_field(payload, "content_hash", _string, "persona content hash"),
        created_by_user_id=_field(payload, "created_by_user_id", _uuid, "persona creator ID"),
        created_at=_field(payload, "created_at", _datetime, "persona creation timestamp"),
    )

    _require_snapshot_match(
        actual=version.to_snapshot(),
        expected=payload,
        label="persona version",
    )

    return version


def _user_twin_profile_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> UserTwinProfile:
    """Reconstruct one UserTwinProfile from canonical JSON."""
    schema_version = _field(payload, "schema_version", _integer, "User Twin schema version")

    if schema_version != USER_TWIN_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported User Twin profile schema")

    persona_payload = _field(payload, "persona_reference", _mapping, "User Twin persona reference")

    catalog_payload = _field(payload, "catalog", _mapping, "User Twin catalog")

    profile = UserTwinProfile(
        name=_field(payload, "name", _string, "User Twin name"),
        persona_reference=ConfirmedPersonaReference(
            persona_id=_field(persona_payload, "persona_id", _uuid, "persona ID"),
            version_number=_field(
                persona_payload, "version_number", _integer, "persona version number"
            ),
            content_hash=_field(persona_payload, "content_hash", _string, "persona content hash"),
            source=PersonaSource(_field(persona_payload, "source", _string, "persona source")),
            kind=PersonaKind(_field(persona_payload, "kind", _string, "persona kind")),
            confirmation_status=PersonaConfirmationStatus(
                _field(
                    persona_payload, "confirmation_status", _string, "persona confirmation status"
                )
            ),
        ),
        project_brief_reference=_artifact_reference_from_snapshot(
            _field(payload, "project_brief_reference", _mapping, "Project Brief reference")
        ),
        agent_team_reference=_artifact_reference_from_snapshot(
            _field(payload, "agent_team_reference", _mapping, "Agent Team reference")
        ),
        catalog_version=_field(catalog_payload, "version", _integer, "catalog version"),
        catalog_content_hash=_field(
            catalog_payload, "content_hash", _string, "catalog content hash"
        ),
        validation_status=UserTwinLifecycleStatus(
            _field(payload, "validation_status", _string, "User Twin lifecycle status")
        ),
        observations=tuple(
            _profile_observation_from_snapshot(item)
            for item in _field(payload, "observations", _mapping_sequence, "User Twin observations")
        ),
    )

    _require_snapshot_match(
        actual=profile.to_snapshot(),
        expected=payload,
        label="User Twin profile",
    )

    return profile


def _user_twin_version_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> UserTwinProfileVersion:
    """Reconstruct a nested UserTwinProfileVersion snapshot."""
    profile = _user_twin_profile_from_snapshot(
        _field(payload, "profile", _mapping, "User Twin version profile")
    )

    version = UserTwinProfileVersion(
        id=_field(payload, "id", _uuid, "User Twin version ID"),
        project_id=_field(payload, "project_id", _uuid, "User Twin project ID"),
        twin_id=_field(payload, "twin_id", _uuid, "User Twin ID"),
        version_number=_field(payload, "version_number", _integer, "User Twin version number"),
        based_on_version_number=(
            _optional_integer(
                payload.get("based_on_version_number"),
                label="User Twin base version",
            )
        ),
        profile=profile,
        content_hash=_field(payload, "content_hash", _string, "User Twin content hash"),
        created_by_user_id=_field(payload, "created_by_user_id", _uuid, "User Twin creator ID"),
        created_at=_field(payload, "created_at", _datetime, "User Twin creation timestamp"),
    )

    _require_snapshot_match(
        actual=version.to_snapshot(),
        expected=payload,
        label="User Twin version",
    )

    return version


def _user_modeling_snapshot_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> UserModelingSnapshot:
    """Reconstruct one complete User Modeling snapshot."""
    schema_version = _field(payload, "schema_version", _integer, "User Modeling snapshot schema")

    if schema_version != USER_MODELING_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported User Modeling snapshot schema")

    catalog_payload = _field(payload, "catalog", _mapping, "User Modeling catalog")

    snapshot = UserModelingSnapshot(
        project_id=_field(payload, "project_id", _uuid, "User Modeling project ID"),
        project_brief_reference=_artifact_reference_from_snapshot(
            _field(payload, "project_brief_reference", _mapping, "Project Brief reference")
        ),
        agent_team_reference=_artifact_reference_from_snapshot(
            _field(payload, "agent_team_reference", _mapping, "Agent Team reference")
        ),
        catalog_version=_field(catalog_payload, "version", _integer, "catalog version"),
        catalog_content_hash=_field(
            catalog_payload, "content_hash", _string, "catalog content hash"
        ),
        persona_versions=tuple(
            _persona_version_from_snapshot(item)
            for item in _field(payload, "persona_versions", _mapping_sequence, "persona versions")
        ),
        twin_versions=tuple(
            _user_twin_version_from_snapshot(item)
            for item in _field(payload, "twin_versions", _mapping_sequence, "User Twin versions")
        ),
    )

    _require_snapshot_match(
        actual=snapshot.to_snapshot(),
        expected=payload,
        label="User Modeling snapshot",
    )

    return snapshot


def _profile_observation_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> ProfileObservation:
    """Reconstruct one epistemically explicit profile observation."""
    value_payload = _field(payload, "value", _mapping, "observation value")

    provenance_payload = _field(payload, "provenance", _sequence, "observation provenance")

    references = tuple(
        _evidence_reference_from_snapshot(
            _mapping(
                item,
                label="evidence reference",
            )
        )
        for item in provenance_payload
    )

    observation = ProfileObservation(
        observation_key=_field(payload, "observation_key", _string, "observation key"),
        value=ObservationValue(
            kind=ObservationValueKind(
                _field(value_payload, "kind", _string, "observation value kind")
            ),
            text=_optional_string(
                value_payload.get("text"),
                label="observation text",
            ),
            items=tuple(
                _string(
                    item,
                    label="observation item",
                )
                for item in _sequence(
                    value_payload.get(
                        "items",
                        [],
                    ),
                    label="observation items",
                )
            ),
            reason=_optional_string(
                value_payload.get("reason"),
                label="observation reason",
            ),
        ),
        epistemic_status=EpistemicStatus(
            _field(payload, "epistemic_status", _string, "epistemic status")
        ),
        confidence=ConfidenceScore(_field(payload, "confidence", _real, "confidence")),
        provenance=(ObservationProvenance(references=references)),
        human_validation=HumanValidationRequirement(
            _field(payload, "human_validation", _string, "human validation requirement")
        ),
        rationale=_optional_string(
            payload.get("rationale"),
            label="observation rationale",
        ),
    )

    _require_snapshot_match(
        actual=observation.to_snapshot(),
        expected=payload,
        label="profile observation",
    )

    return observation


def _evidence_reference_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> EvidenceReference:
    """Reconstruct one evidence reference."""
    reference = EvidenceReference(
        source_kind=EvidenceSourceKind(
            _field(payload, "source_kind", _string, "evidence source kind")
        ),
        source_id=_field(payload, "source_id", _string, "evidence source ID"),
        source_version=(
            _optional_integer(
                payload.get("source_version"),
                label=("evidence source version"),
            )
        ),
        content_hash=_optional_string(
            payload.get("content_hash"),
            label="evidence content hash",
        ),
        locator=_optional_string(
            payload.get("locator"),
            label="evidence locator",
        ),
        summary=_optional_string(
            payload.get("summary"),
            label="evidence summary",
        ),
    )

    _require_snapshot_match(
        actual=reference.to_snapshot(),
        expected=payload,
        label="evidence reference",
    )

    return reference


def _artifact_reference_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> VersionedArtifactReference:
    """Reconstruct one exact immutable artifact reference."""
    reference = VersionedArtifactReference(
        artifact_id=_field(payload, "artifact_id", _uuid, "artifact ID"),
        version_number=_field(payload, "version_number", _integer, "artifact version number"),
        content_hash=_field(payload, "content_hash", _string, "artifact content hash"),
    )

    _require_snapshot_match(
        actual=reference.to_snapshot(),
        expected=payload,
        label="artifact reference",
    )

    return reference


def _require_snapshot_match(
    *,
    actual: Mapping[
        str,
        object,
    ],
    expected: Mapping[
        str,
        object,
    ],
    label: str,
) -> None:
    """Reject JSONB that cannot round-trip to the canonical domain form."""
    if dict(actual) != dict(expected):
        raise ValueError(f"{label} is not canonical")


def _mapping(
    value: object,
    *,
    label: str,
) -> Mapping[
    str,
    object,
]:
    """Require one string-keyed mapping."""
    if not isinstance(
        value,
        Mapping,
    ):
        raise ValueError(f"{label} must be an object")

    if not all(
        isinstance(
            key,
            str,
        )
        for key in value
    ):
        raise ValueError(f"{label} must use string keys")

    return cast(
        Mapping[
            str,
            object,
        ],
        value,
    )


def _mapping_sequence(
    value: object,
    *,
    label: str,
) -> tuple[
    Mapping[
        str,
        object,
    ],
    ...,
]:
    """Require an array whose elements are objects."""
    return tuple(
        _mapping(
            item,
            label=label,
        )
        for item in _sequence(
            value,
            label=label,
        )
    )


def persona_version_from_snapshot(payload: Mapping[str, object]) -> PersonaProfileVersion:
    return _persona_version_from_snapshot(payload)


def user_twin_version_from_snapshot(payload: Mapping[str, object]) -> UserTwinProfileVersion:
    return _user_twin_version_from_snapshot(payload)


def user_modeling_snapshot_from_snapshot(payload: Mapping[str, object]) -> UserModelingSnapshot:
    return _user_modeling_snapshot_from_snapshot(payload)


def persona_profile_from_snapshot(payload: Mapping[str, object]) -> PersonaProfile:
    return _persona_profile_from_snapshot(payload)


def user_twin_profile_from_snapshot(payload: Mapping[str, object]) -> UserTwinProfile:
    return _user_twin_profile_from_snapshot(payload)
