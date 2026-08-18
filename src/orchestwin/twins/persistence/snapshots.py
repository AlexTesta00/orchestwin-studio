"""Pure mapping between User Modeling domain values and persistence records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from numbers import Real
from typing import cast
from uuid import UUID

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
    profile_snapshot = _mapping(
        _required(
            record,
            "profile_snapshot",
        ),
        label="persona profile snapshot",
    )
    profile = _persona_profile_from_snapshot(profile_snapshot)

    if (
        _integer(
            _required(
                record,
                "profile_schema_version",
            ),
            label="persona profile schema version",
        )
        != PERSONA_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError("persisted persona schema version does not match the domain schema")

    if (
        _string(
            _required(
                record,
                "profile_source",
            ),
            label="persona source",
        )
        != profile.source.value
    ):
        raise ValueError("persisted persona source does not match its snapshot")

    if (
        _string(
            _required(
                record,
                "profile_kind",
            ),
            label="persona kind",
        )
        != profile.kind.value
    ):
        raise ValueError("persisted persona kind does not match its snapshot")

    if (
        _string(
            _required(
                record,
                "confirmation_status",
            ),
            label="persona confirmation status",
        )
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
        id=_uuid(
            _required(
                record,
                "id",
            ),
            label="persona version ID",
        ),
        project_id=_uuid(
            _required(
                record,
                "project_id",
            ),
            label="persona project ID",
        ),
        persona_id=_uuid(
            _required(
                record,
                "persona_id",
            ),
            label="persona ID",
        ),
        version_number=_integer(
            _required(
                record,
                "version_number",
            ),
            label="persona version number",
        ),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("persona base version number"),
            )
        ),
        profile=profile,
        content_hash=_string(
            _required(
                record,
                "content_hash",
            ),
            label="persona content hash",
        ),
        created_by_user_id=_uuid(
            _required(
                record,
                "created_by_user_id",
            ),
            label="persona creator ID",
        ),
        created_at=_datetime(
            _required(
                record,
                "created_at",
            ),
            label="persona creation timestamp",
        ),
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
    profile_snapshot = _mapping(
        _required(
            record,
            "profile_snapshot",
        ),
        label="User Twin profile snapshot",
    )
    profile = _user_twin_profile_from_snapshot(profile_snapshot)

    if (
        _integer(
            _required(
                record,
                "profile_schema_version",
            ),
            label="User Twin schema version",
        )
        != USER_TWIN_PROFILE_SCHEMA_VERSION
    ):
        raise ValueError("persisted User Twin schema version does not match the domain schema")

    if (
        _uuid(
            _required(
                record,
                "persona_id",
            ),
            label="User Twin persona ID",
        )
        != profile.persona_reference.persona_id
    ):
        raise ValueError("persisted User Twin persona ID does not match its snapshot")

    if (
        _integer(
            _required(
                record,
                "persona_version_number",
            ),
            label="User Twin persona version",
        )
        != profile.persona_reference.version_number
    ):
        raise ValueError("persisted User Twin persona version does not match its snapshot")

    if (
        _string(
            _required(
                record,
                "validation_status",
            ),
            label="User Twin validation status",
        )
        != profile.validation_status.value
    ):
        raise ValueError("persisted User Twin lifecycle status does not match its snapshot")

    return UserTwinProfileVersion(
        id=_uuid(
            _required(
                record,
                "id",
            ),
            label="User Twin version ID",
        ),
        project_id=_uuid(
            _required(
                record,
                "project_id",
            ),
            label="User Twin project ID",
        ),
        twin_id=_uuid(
            _required(
                record,
                "twin_id",
            ),
            label="User Twin ID",
        ),
        version_number=_integer(
            _required(
                record,
                "version_number",
            ),
            label="User Twin version number",
        ),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("User Twin base version number"),
            )
        ),
        profile=profile,
        content_hash=_string(
            _required(
                record,
                "content_hash",
            ),
            label="User Twin content hash",
        ),
        created_by_user_id=_uuid(
            _required(
                record,
                "created_by_user_id",
            ),
            label="User Twin creator ID",
        ),
        created_at=_datetime(
            _required(
                record,
                "created_at",
            ),
            label="User Twin creation timestamp",
        ),
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
    snapshot_payload = _mapping(
        _required(
            record,
            "snapshot",
        ),
        label="User Modeling snapshot",
    )
    snapshot = _user_modeling_snapshot_from_snapshot(snapshot_payload)

    if (
        _integer(
            _required(
                record,
                "snapshot_schema_version",
            ),
            label=("User Modeling snapshot schema version"),
        )
        != USER_MODELING_SNAPSHOT_SCHEMA_VERSION
    ):
        raise ValueError("persisted User Modeling schema version does not match the domain schema")

    brief = snapshot.project_brief_reference
    team = snapshot.agent_team_reference

    persisted_brief = VersionedArtifactReference(
        artifact_id=_uuid(
            _required(
                record,
                "brief_version_id",
            ),
            label="brief version ID",
        ),
        version_number=_integer(
            _required(
                record,
                "brief_version_number",
            ),
            label="brief version number",
        ),
        content_hash=_string(
            _required(
                record,
                "brief_content_hash",
            ),
            label="brief content hash",
        ),
    )

    persisted_team = VersionedArtifactReference(
        artifact_id=_uuid(
            _required(
                record,
                "team_proposal_id",
            ),
            label="team proposal ID",
        ),
        version_number=_integer(
            _required(
                record,
                "team_version_number",
            ),
            label="team version number",
        ),
        content_hash=_string(
            _required(
                record,
                "team_content_hash",
            ),
            label="team content hash",
        ),
    )

    if persisted_brief != brief:
        raise ValueError(
            "persisted Project Brief reference does not match the User Modeling snapshot"
        )

    if persisted_team != team:
        raise ValueError("persisted Agent Team reference does not match the User Modeling snapshot")

    if (
        _integer(
            _required(
                record,
                "catalog_version",
            ),
            label="catalog version",
        )
        != snapshot.catalog_version
        or _string(
            _required(
                record,
                "catalog_content_hash",
            ),
            label="catalog content hash",
        )
        != snapshot.catalog_content_hash
    ):
        raise ValueError("persisted catalog metadata does not match the User Modeling snapshot")

    if (
        _integer(
            _required(
                record,
                "persona_count",
            ),
            label="persona count",
        )
        != snapshot.persona_count
        or _integer(
            _required(
                record,
                "twin_count",
            ),
            label="User Twin count",
        )
        != snapshot.twin_count
    ):
        raise ValueError("persisted User Modeling counts do not match the snapshot")

    return UserModelingSnapshotVersion(
        id=_uuid(
            _required(
                record,
                "id",
            ),
            label="User Modeling version ID",
        ),
        project_id=_uuid(
            _required(
                record,
                "project_id",
            ),
            label="User Modeling project ID",
        ),
        version_number=_integer(
            _required(
                record,
                "version_number",
            ),
            label="User Modeling version number",
        ),
        based_on_version_number=(
            _optional_integer(
                record.get("based_on_version_number"),
                label=("User Modeling base version"),
            )
        ),
        snapshot=snapshot,
        content_hash=_string(
            _required(
                record,
                "content_hash",
            ),
            label="User Modeling content hash",
        ),
        created_by_user_id=_uuid(
            _required(
                record,
                "created_by_user_id",
            ),
            label="User Modeling creator ID",
        ),
        created_at=_datetime(
            _required(
                record,
                "created_at",
            ),
            label=("User Modeling creation timestamp"),
        ),
    )


def _persona_profile_from_snapshot(
    payload: Mapping[
        str,
        object,
    ],
) -> PersonaProfile:
    """Reconstruct one PersonaProfile from canonical JSON."""
    schema_version = _integer(
        _required(
            payload,
            "schema_version",
        ),
        label="persona schema version",
    )

    if schema_version != PERSONA_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported persona profile schema")

    observations = tuple(
        _profile_observation_from_snapshot(item)
        for item in _mapping_sequence(
            _required(
                payload,
                "observations",
            ),
            label="persona observations",
        )
    )

    profile = PersonaProfile(
        name=_string(
            _required(
                payload,
                "name",
            ),
            label="persona name",
        ),
        source=PersonaSource(
            _string(
                _required(
                    payload,
                    "source",
                ),
                label="persona source",
            )
        ),
        kind=PersonaKind(
            _string(
                _required(
                    payload,
                    "kind",
                ),
                label="persona kind",
            )
        ),
        confirmation_status=(
            PersonaConfirmationStatus(
                _string(
                    _required(
                        payload,
                        "confirmation_status",
                    ),
                    label=("persona confirmation status"),
                )
            )
        ),
        rejection_reason=(
            _optional_string(
                payload.get("rejection_reason"),
                label=("persona rejection reason"),
            )
        ),
        observations=observations,
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
        _mapping(
            _required(
                payload,
                "profile",
            ),
            label="persona version profile",
        )
    )

    version = PersonaProfileVersion(
        id=_uuid(
            _required(
                payload,
                "id",
            ),
            label="persona version ID",
        ),
        project_id=_uuid(
            _required(
                payload,
                "project_id",
            ),
            label="persona project ID",
        ),
        persona_id=_uuid(
            _required(
                payload,
                "persona_id",
            ),
            label="persona ID",
        ),
        version_number=_integer(
            _required(
                payload,
                "version_number",
            ),
            label="persona version number",
        ),
        based_on_version_number=(
            _optional_integer(
                payload.get("based_on_version_number"),
                label="persona base version",
            )
        ),
        profile=profile,
        content_hash=_string(
            _required(
                payload,
                "content_hash",
            ),
            label="persona content hash",
        ),
        created_by_user_id=_uuid(
            _required(
                payload,
                "created_by_user_id",
            ),
            label="persona creator ID",
        ),
        created_at=_datetime(
            _required(
                payload,
                "created_at",
            ),
            label="persona creation timestamp",
        ),
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
    schema_version = _integer(
        _required(
            payload,
            "schema_version",
        ),
        label="User Twin schema version",
    )

    if schema_version != USER_TWIN_PROFILE_SCHEMA_VERSION:
        raise ValueError("unsupported User Twin profile schema")

    persona_payload = _mapping(
        _required(
            payload,
            "persona_reference",
        ),
        label="User Twin persona reference",
    )

    catalog_payload = _mapping(
        _required(
            payload,
            "catalog",
        ),
        label="User Twin catalog",
    )

    profile = UserTwinProfile(
        name=_string(
            _required(
                payload,
                "name",
            ),
            label="User Twin name",
        ),
        persona_reference=(
            ConfirmedPersonaReference(
                persona_id=_uuid(
                    _required(
                        persona_payload,
                        "persona_id",
                    ),
                    label="persona ID",
                ),
                version_number=_integer(
                    _required(
                        persona_payload,
                        "version_number",
                    ),
                    label="persona version number",
                ),
                content_hash=_string(
                    _required(
                        persona_payload,
                        "content_hash",
                    ),
                    label="persona content hash",
                ),
                source=PersonaSource(
                    _string(
                        _required(
                            persona_payload,
                            "source",
                        ),
                        label="persona source",
                    )
                ),
                kind=PersonaKind(
                    _string(
                        _required(
                            persona_payload,
                            "kind",
                        ),
                        label="persona kind",
                    )
                ),
                confirmation_status=(
                    PersonaConfirmationStatus(
                        _string(
                            _required(
                                persona_payload,
                                "confirmation_status",
                            ),
                            label=("persona confirmation status"),
                        )
                    )
                ),
            )
        ),
        project_brief_reference=(
            _artifact_reference_from_snapshot(
                _mapping(
                    _required(
                        payload,
                        "project_brief_reference",
                    ),
                    label=("Project Brief reference"),
                )
            )
        ),
        agent_team_reference=(
            _artifact_reference_from_snapshot(
                _mapping(
                    _required(
                        payload,
                        "agent_team_reference",
                    ),
                    label="Agent Team reference",
                )
            )
        ),
        catalog_version=_integer(
            _required(
                catalog_payload,
                "version",
            ),
            label="catalog version",
        ),
        catalog_content_hash=_string(
            _required(
                catalog_payload,
                "content_hash",
            ),
            label="catalog content hash",
        ),
        validation_status=(
            UserTwinLifecycleStatus(
                _string(
                    _required(
                        payload,
                        "validation_status",
                    ),
                    label=("User Twin lifecycle status"),
                )
            )
        ),
        observations=tuple(
            _profile_observation_from_snapshot(item)
            for item in _mapping_sequence(
                _required(
                    payload,
                    "observations",
                ),
                label=("User Twin observations"),
            )
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
        _mapping(
            _required(
                payload,
                "profile",
            ),
            label=("User Twin version profile"),
        )
    )

    version = UserTwinProfileVersion(
        id=_uuid(
            _required(
                payload,
                "id",
            ),
            label="User Twin version ID",
        ),
        project_id=_uuid(
            _required(
                payload,
                "project_id",
            ),
            label="User Twin project ID",
        ),
        twin_id=_uuid(
            _required(
                payload,
                "twin_id",
            ),
            label="User Twin ID",
        ),
        version_number=_integer(
            _required(
                payload,
                "version_number",
            ),
            label="User Twin version number",
        ),
        based_on_version_number=(
            _optional_integer(
                payload.get("based_on_version_number"),
                label="User Twin base version",
            )
        ),
        profile=profile,
        content_hash=_string(
            _required(
                payload,
                "content_hash",
            ),
            label="User Twin content hash",
        ),
        created_by_user_id=_uuid(
            _required(
                payload,
                "created_by_user_id",
            ),
            label="User Twin creator ID",
        ),
        created_at=_datetime(
            _required(
                payload,
                "created_at",
            ),
            label="User Twin creation timestamp",
        ),
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
    schema_version = _integer(
        _required(
            payload,
            "schema_version",
        ),
        label=("User Modeling snapshot schema"),
    )

    if schema_version != USER_MODELING_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported User Modeling snapshot schema")

    catalog_payload = _mapping(
        _required(
            payload,
            "catalog",
        ),
        label="User Modeling catalog",
    )

    snapshot = UserModelingSnapshot(
        project_id=_uuid(
            _required(
                payload,
                "project_id",
            ),
            label="User Modeling project ID",
        ),
        project_brief_reference=(
            _artifact_reference_from_snapshot(
                _mapping(
                    _required(
                        payload,
                        "project_brief_reference",
                    ),
                    label=("Project Brief reference"),
                )
            )
        ),
        agent_team_reference=(
            _artifact_reference_from_snapshot(
                _mapping(
                    _required(
                        payload,
                        "agent_team_reference",
                    ),
                    label="Agent Team reference",
                )
            )
        ),
        catalog_version=_integer(
            _required(
                catalog_payload,
                "version",
            ),
            label="catalog version",
        ),
        catalog_content_hash=_string(
            _required(
                catalog_payload,
                "content_hash",
            ),
            label="catalog content hash",
        ),
        persona_versions=tuple(
            _persona_version_from_snapshot(item)
            for item in _mapping_sequence(
                _required(
                    payload,
                    "persona_versions",
                ),
                label="persona versions",
            )
        ),
        twin_versions=tuple(
            _user_twin_version_from_snapshot(item)
            for item in _mapping_sequence(
                _required(
                    payload,
                    "twin_versions",
                ),
                label="User Twin versions",
            )
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
    value_payload = _mapping(
        _required(
            payload,
            "value",
        ),
        label="observation value",
    )

    provenance_payload = _sequence(
        _required(
            payload,
            "provenance",
        ),
        label="observation provenance",
    )

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
        observation_key=_string(
            _required(
                payload,
                "observation_key",
            ),
            label="observation key",
        ),
        value=ObservationValue(
            kind=ObservationValueKind(
                _string(
                    _required(
                        value_payload,
                        "kind",
                    ),
                    label="observation value kind",
                )
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
        epistemic_status=(
            EpistemicStatus(
                _string(
                    _required(
                        payload,
                        "epistemic_status",
                    ),
                    label="epistemic status",
                )
            )
        ),
        confidence=ConfidenceScore(
            _real(
                _required(
                    payload,
                    "confidence",
                ),
                label="confidence",
            )
        ),
        provenance=(ObservationProvenance(references=references)),
        human_validation=(
            HumanValidationRequirement(
                _string(
                    _required(
                        payload,
                        "human_validation",
                    ),
                    label=("human validation requirement"),
                )
            )
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
            _string(
                _required(
                    payload,
                    "source_kind",
                ),
                label="evidence source kind",
            )
        ),
        source_id=_string(
            _required(
                payload,
                "source_id",
            ),
            label="evidence source ID",
        ),
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
        artifact_id=_uuid(
            _required(
                payload,
                "artifact_id",
            ),
            label="artifact ID",
        ),
        version_number=_integer(
            _required(
                payload,
                "version_number",
            ),
            label="artifact version number",
        ),
        content_hash=_string(
            _required(
                payload,
                "content_hash",
            ),
            label="artifact content hash",
        ),
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


def _required(
    mapping: Mapping[
        str,
        object,
    ],
    key: str,
) -> object:
    """Return one required persistence value."""
    if key not in mapping:
        raise ValueError(f"missing persistence field: {key}")

    return mapping[key]


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


def _sequence(
    value: object,
    *,
    label: str,
) -> Sequence[object,]:
    """Require one non-string sequence."""
    if isinstance(
        value,
        str,
    ) or not isinstance(
        value,
        Sequence,
    ):
        raise ValueError(f"{label} must be an array")

    return value


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


def _string(
    value: object,
    *,
    label: str,
) -> str:
    """Require one string."""
    if not isinstance(
        value,
        str,
    ):
        raise ValueError(f"{label} must be a string")

    return value


def _optional_string(
    value: object,
    *,
    label: str,
) -> str | None:
    """Require a string or null."""
    if value is None:
        return None

    return _string(
        value,
        label=label,
    )


def _integer(
    value: object,
    *,
    label: str,
) -> int:
    """Require one non-boolean integer."""
    if isinstance(
        value,
        bool,
    ) or not isinstance(
        value,
        int,
    ):
        raise ValueError(f"{label} must be an integer")

    return value


def _optional_integer(
    value: object,
    *,
    label: str,
) -> int | None:
    """Require an integer or null."""
    if value is None:
        return None

    return _integer(
        value,
        label=label,
    )


def _real(
    value: object,
    *,
    label: str,
) -> float:
    """Require one non-boolean real number."""
    if isinstance(
        value,
        bool,
    ) or not isinstance(
        value,
        Real,
    ):
        raise ValueError(f"{label} must be a real number")

    return float(value)


def _uuid(
    value: object,
    *,
    label: str,
) -> UUID:
    """Require or reconstruct one UUID."""
    if isinstance(
        value,
        UUID,
    ):
        return value

    if isinstance(
        value,
        str,
    ):
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a UUID") from error

    raise ValueError(f"{label} must be a UUID")


def _datetime(
    value: object,
    *,
    label: str,
) -> datetime:
    """Require or reconstruct one timezone-aware datetime."""
    if isinstance(
        value,
        datetime,
    ):
        parsed = value
    elif isinstance(
        value,
        str,
    ):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO datetime") from error
    else:
        raise ValueError(f"{label} must be a datetime")

    if parsed.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return parsed
