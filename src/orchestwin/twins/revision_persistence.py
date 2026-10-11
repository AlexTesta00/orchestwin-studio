"""Owner-scoped persistence for User Twin profile diffs."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

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
from orchestwin.twins.record_values import datetime_value as _datetime
from orchestwin.twins.record_values import field as _field
from orchestwin.twins.record_values import integer as _integer
from orchestwin.twins.record_values import optional_datetime as _optional_datetime
from orchestwin.twins.record_values import optional_integer as _optional_integer
from orchestwin.twins.record_values import optional_string as _optional_string
from orchestwin.twins.record_values import optional_uuid as _optional_uuid
from orchestwin.twins.record_values import owned_project_exists as _owned_project_exists
from orchestwin.twins.record_values import project_is_owned as _project_is_owned
from orchestwin.twins.record_values import real as _real
from orchestwin.twins.record_values import sequence as _sequence
from orchestwin.twins.record_values import string as _string
from orchestwin.twins.record_values import uuid_value as _uuid
from orchestwin.twins.revisions import (
    USER_TWIN_PROFILE_DIFF_SCHEMA_VERSION,
    ProfileDiffOperation,
    UserTwinProfileDiff,
    UserTwinProfileDiffStatus,
)
from orchestwin.twins.user_twins import (
    UserTwinField,
)


class DiffPersistenceStatus(StrEnum):
    """Stable results of profile-diff persistence operations."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    CONFLICT = "CONFLICT"


class UserTwinProfileDiffRepository(Protocol):
    """Persistence boundary for reviewable User Twin profile diffs."""

    async def create(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Persist one proposed diff."""

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read one exact owner-scoped diff."""

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_snapshot_version_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read the proposed diff for an exact base snapshot/twin."""

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileDiff,
        ...,
    ]:
        """Read diff history in creation order."""

    async def save_decision(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Persist an approved/rejected decision."""


_UUID = postgresql.UUID(as_uuid=True)

SNAPSHOTS = sa.table(
    "user_modeling_snapshot_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
)

TWINS = sa.table(
    "user_twin_profile_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("twin_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
)

DIFFS = sa.table(
    "user_twin_profile_diffs",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("base_snapshot_version_id", _UUID),
    sa.column(
        "base_snapshot_version_number",
        sa.Integer(),
    ),
    sa.column(
        "base_snapshot_content_hash",
        sa.String(64),
    ),
    sa.column("twin_id", _UUID),
    sa.column("base_twin_version_id", _UUID),
    sa.column(
        "base_twin_version_number",
        sa.Integer(),
    ),
    sa.column(
        "base_twin_content_hash",
        sa.String(64),
    ),
    sa.column("proposal_hash", sa.String(64)),
    sa.column(
        "diff_snapshot",
        postgresql.JSONB(),
    ),
    sa.column("status", sa.String(16)),
    sa.column("created_by_user_id", _UUID),
    sa.column(
        "created_at",
        sa.DateTime(timezone=True),
    ),
    sa.column("decided_by_user_id", _UUID),
    sa.column(
        "decided_at",
        sa.DateTime(timezone=True),
    ),
    sa.column("decision_reason", sa.Text()),
    sa.column(
        "applied_snapshot_version_id",
        _UUID,
    ),
)


class SqlAlchemyUserTwinProfileDiffRepository:
    """SQLAlchemy implementation of owner-scoped profile-diff storage."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind diff access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Persist a proposed diff only for an exact owned base context."""
        if not await _project_is_owned(
            self._session,
            project_id=diff.project_id,
            owner_user_id=(self._owner_user_id),
        ):
            return DiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _base_context_exists(
            self._session,
            diff,
        ):
            return DiffPersistenceStatus.CONTEXT_NOT_FOUND

        await self._session.execute(sa.insert(DIFFS).values(**diff_to_record(diff)))

        return DiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read an exact owner-scoped diff."""
        statement = _owned_select(
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).where(DIFFS.c.id == diff_id)

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return diff_from_record(row)

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_snapshot_version_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Read the proposed diff for the exact current snapshot."""
        statement = (
            _owned_select(
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(
                DIFFS.c.base_snapshot_version_id == base_snapshot_version_id,
                DIFFS.c.twin_id == twin_id,
                DIFFS.c.status == UserTwinProfileDiffStatus.PROPOSED.value,
            )
            .limit(1)
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return diff_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileDiff,
        ...,
    ]:
        """Read all profile diffs for one project User Twin."""
        statement = (
            _owned_select(
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(DIFFS.c.twin_id == twin_id)
            .order_by(
                DIFFS.c.created_at.asc(),
                DIFFS.c.id.asc(),
            )
        )

        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(diff_from_record(row) for row in rows)

    async def save_decision(
        self,
        diff: UserTwinProfileDiff,
    ) -> DiffPersistenceStatus:
        """Update only decision metadata of an existing proposed diff."""
        if diff.status is UserTwinProfileDiffStatus.PROPOSED:
            raise ValueError("cannot persist a decision while diff status is PROPOSED")

        statement = (
            sa.update(DIFFS)
            .where(
                DIFFS.c.id == diff.id,
                DIFFS.c.project_id == diff.project_id,
                DIFFS.c.status == UserTwinProfileDiffStatus.PROPOSED.value,
                _owned_project_exists(
                    project_id=(diff.project_id),
                    owner_user_id=(self._owner_user_id),
                ),
            )
            .values(
                status=diff.status.value,
                decided_by_user_id=(diff.decided_by_user_id),
                decided_at=diff.decided_at,
                decision_reason=(diff.decision_reason),
                applied_snapshot_version_id=(diff.applied_snapshot_version_id),
            )
            .returning(DIFFS.c.id)
        )

        updated_id = (await self._session.execute(statement)).scalar_one_or_none()

        if updated_id is None:
            return DiffPersistenceStatus.CONFLICT

        return DiffPersistenceStatus.UPDATED


def diff_to_record(
    diff: UserTwinProfileDiff,
) -> dict[str, object]:
    """Convert one domain diff to database values."""
    return {
        "id": diff.id,
        "project_id": diff.project_id,
        "base_snapshot_version_id": (diff.base_snapshot_version_id),
        "base_snapshot_version_number": (diff.base_snapshot_version_number),
        "base_snapshot_content_hash": (diff.base_snapshot_content_hash),
        "twin_id": diff.twin_id,
        "base_twin_version_id": (diff.base_twin_version_id),
        "base_twin_version_number": (diff.base_twin_version_number),
        "base_twin_content_hash": (diff.base_twin_content_hash),
        "proposal_hash": diff.proposal_hash,
        "diff_snapshot": diff.proposal_snapshot(),
        "status": diff.status.value,
        "created_by_user_id": (diff.created_by_user_id),
        "created_at": diff.created_at,
        "decided_by_user_id": (diff.decided_by_user_id),
        "decided_at": diff.decided_at,
        "decision_reason": (diff.decision_reason),
        "applied_snapshot_version_id": (diff.applied_snapshot_version_id),
    }


def diff_from_record(
    record: Mapping[str, object],
) -> UserTwinProfileDiff:
    """Reconstruct and validate one persisted profile diff."""
    payload = _field(record, "diff_snapshot", _mapping, "profile diff snapshot")

    if (
        _field(payload, "schema_version", _integer, "profile diff schema version")
        != USER_TWIN_PROFILE_DIFF_SCHEMA_VERSION
    ):
        raise ValueError("unsupported User Twin profile diff schema")

    base_snapshot = _field(payload, "base_snapshot", _mapping, "base snapshot reference")
    base_twin = _field(payload, "base_twin", _mapping, "base User Twin reference")

    operations = tuple(
        _operation_from_snapshot(item)
        for item in _field(payload, "operations", _mapping_sequence, "profile diff operations")
    )

    diff = UserTwinProfileDiff(
        id=_field(payload, "id", _uuid, "profile diff ID"),
        project_id=_field(payload, "project_id", _uuid, "profile diff project ID"),
        base_snapshot_version_id=_field(
            base_snapshot, "version_id", _uuid, "base snapshot version ID"
        ),
        base_snapshot_version_number=_field(
            base_snapshot, "version_number", _integer, "base snapshot version number"
        ),
        base_snapshot_content_hash=_field(
            base_snapshot, "content_hash", _string, "base snapshot hash"
        ),
        twin_id=_field(base_twin, "twin_id", _uuid, "profile diff User Twin ID"),
        base_twin_version_id=_field(base_twin, "version_id", _uuid, "base User Twin version ID"),
        base_twin_version_number=_field(
            base_twin, "version_number", _integer, "base User Twin version number"
        ),
        base_twin_content_hash=_field(base_twin, "content_hash", _string, "base User Twin hash"),
        operations=operations,
        created_by_user_id=_field(payload, "created_by_user_id", _uuid, "profile diff creator ID"),
        created_at=_field(payload, "created_at", _datetime, "profile diff creation timestamp"),
        status=UserTwinProfileDiffStatus(_field(record, "status", _string, "profile diff status")),
        decided_by_user_id=_optional_uuid(
            record.get("decided_by_user_id"),
            label="profile diff decision actor",
        ),
        decided_at=_optional_datetime(
            record.get("decided_at"),
            label="profile diff decision timestamp",
        ),
        decision_reason=_optional_string(
            record.get("decision_reason"),
            label="profile diff decision reason",
        ),
        applied_snapshot_version_id=(
            _optional_uuid(
                record.get("applied_snapshot_version_id"),
                label=("applied snapshot version ID"),
            )
        ),
    )

    if diff.proposal_hash != _field(record, "proposal_hash", _string, "profile diff proposal hash"):
        raise ValueError("persisted profile diff proposal hash does not match its snapshot")

    if diff.proposal_snapshot() != dict(payload):
        raise ValueError("persisted profile diff snapshot is not canonical")

    return diff


def _operation_from_snapshot(
    payload: Mapping[str, object],
) -> ProfileDiffOperation:
    """Reconstruct one typed diff operation."""
    before_payload = payload.get("before")

    return ProfileDiffOperation(
        field=UserTwinField(_field(payload, "field", _string, "profile diff field")),
        before=(
            None
            if before_payload is None
            else _observation_from_snapshot(
                _mapping(
                    before_payload,
                    label="before observation",
                )
            )
        ),
        after=_observation_from_snapshot(_field(payload, "after", _mapping, "after observation")),
    )


def _observation_from_snapshot(
    payload: Mapping[str, object],
) -> ProfileObservation:
    """Reconstruct one profile observation from canonical JSON."""
    value_payload = _field(payload, "value", _mapping, "observation value")

    references = tuple(
        _evidence_from_snapshot(item)
        for item in _field(payload, "provenance", _mapping_sequence, "observation provenance")
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
        provenance=ObservationProvenance(references=references),
        human_validation=HumanValidationRequirement(
            _field(payload, "human_validation", _string, "human validation requirement")
        ),
        rationale=_optional_string(
            payload.get("rationale"),
            label="observation rationale",
        ),
    )

    if observation.to_snapshot() != dict(payload):
        raise ValueError("persisted profile observation is not canonical")

    return observation


def _evidence_from_snapshot(
    payload: Mapping[str, object],
) -> EvidenceReference:
    """Reconstruct one evidence reference."""
    reference = EvidenceReference(
        source_kind=EvidenceSourceKind(
            _field(payload, "source_kind", _string, "evidence source kind")
        ),
        source_id=_field(payload, "source_id", _string, "evidence source ID"),
        source_version=_optional_integer(
            payload.get("source_version"),
            label="evidence source version",
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

    if reference.to_snapshot() != dict(payload):
        raise ValueError("persisted evidence reference is not canonical")

    return reference


def _owned_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> sa.Select:
    """Create an owner/project-scoped diff select."""
    return sa.select(*DIFFS.c).where(
        DIFFS.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        ),
    )


async def _base_context_exists(
    session: AsyncSession,
    diff: UserTwinProfileDiff,
) -> bool:
    """Verify exact snapshot and User Twin versions before diff creation."""
    snapshot_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(SNAPSHOTS)
        .where(
            SNAPSHOTS.c.id == diff.base_snapshot_version_id,
            SNAPSHOTS.c.project_id == diff.project_id,
            SNAPSHOTS.c.version_number == diff.base_snapshot_version_number,
            SNAPSHOTS.c.content_hash == diff.base_snapshot_content_hash,
        )
    )

    twin_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(TWINS)
        .where(
            TWINS.c.id == diff.base_twin_version_id,
            TWINS.c.project_id == diff.project_id,
            TWINS.c.twin_id == diff.twin_id,
            TWINS.c.version_number == diff.base_twin_version_number,
            TWINS.c.content_hash == diff.base_twin_content_hash,
        )
    )

    result = await session.execute(
        sa.select(sa.literal(True)).where(
            snapshot_exists,
            twin_exists,
        )
    )

    return result.scalar_one_or_none() is True


def _mapping(
    value: object,
    *,
    label: str,
) -> Mapping[str, object]:
    """Require a string-keyed mapping."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")

    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must use string keys")

    return dict(value)


def _mapping_sequence(
    value: object,
    *,
    label: str,
) -> tuple[
    Mapping[str, object],
    ...,
]:
    """Require an array of mappings."""
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
