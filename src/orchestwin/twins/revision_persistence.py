"""Owner-scoped persistence for User Twin profile diffs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from numbers import Real
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

PROJECTS = sa.table(
    "projects",
    sa.column("id", _UUID),
    sa.column("owner_user_id", _UUID),
)

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
    payload = _mapping(
        _required(
            record,
            "diff_snapshot",
        ),
        label="profile diff snapshot",
    )

    if (
        _integer(
            _required(
                payload,
                "schema_version",
            ),
            label="profile diff schema version",
        )
        != USER_TWIN_PROFILE_DIFF_SCHEMA_VERSION
    ):
        raise ValueError("unsupported User Twin profile diff schema")

    base_snapshot = _mapping(
        _required(
            payload,
            "base_snapshot",
        ),
        label="base snapshot reference",
    )
    base_twin = _mapping(
        _required(
            payload,
            "base_twin",
        ),
        label="base User Twin reference",
    )

    operations = tuple(
        _operation_from_snapshot(item)
        for item in _mapping_sequence(
            _required(
                payload,
                "operations",
            ),
            label="profile diff operations",
        )
    )

    diff = UserTwinProfileDiff(
        id=_uuid(
            _required(
                payload,
                "id",
            ),
            label="profile diff ID",
        ),
        project_id=_uuid(
            _required(
                payload,
                "project_id",
            ),
            label="profile diff project ID",
        ),
        base_snapshot_version_id=_uuid(
            _required(
                base_snapshot,
                "version_id",
            ),
            label="base snapshot version ID",
        ),
        base_snapshot_version_number=_integer(
            _required(
                base_snapshot,
                "version_number",
            ),
            label="base snapshot version number",
        ),
        base_snapshot_content_hash=_string(
            _required(
                base_snapshot,
                "content_hash",
            ),
            label="base snapshot hash",
        ),
        twin_id=_uuid(
            _required(
                base_twin,
                "twin_id",
            ),
            label="profile diff User Twin ID",
        ),
        base_twin_version_id=_uuid(
            _required(
                base_twin,
                "version_id",
            ),
            label="base User Twin version ID",
        ),
        base_twin_version_number=_integer(
            _required(
                base_twin,
                "version_number",
            ),
            label="base User Twin version number",
        ),
        base_twin_content_hash=_string(
            _required(
                base_twin,
                "content_hash",
            ),
            label="base User Twin hash",
        ),
        operations=operations,
        created_by_user_id=_uuid(
            _required(
                payload,
                "created_by_user_id",
            ),
            label="profile diff creator ID",
        ),
        created_at=_datetime(
            _required(
                payload,
                "created_at",
            ),
            label="profile diff creation timestamp",
        ),
        status=UserTwinProfileDiffStatus(
            _string(
                _required(
                    record,
                    "status",
                ),
                label="profile diff status",
            )
        ),
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

    if diff.proposal_hash != _string(
        _required(
            record,
            "proposal_hash",
        ),
        label="profile diff proposal hash",
    ):
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
        field=UserTwinField(
            _string(
                _required(
                    payload,
                    "field",
                ),
                label="profile diff field",
            )
        ),
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
        after=_observation_from_snapshot(
            _mapping(
                _required(
                    payload,
                    "after",
                ),
                label="after observation",
            )
        ),
    )


def _observation_from_snapshot(
    payload: Mapping[str, object],
) -> ProfileObservation:
    """Reconstruct one profile observation from canonical JSON."""
    value_payload = _mapping(
        _required(
            payload,
            "value",
        ),
        label="observation value",
    )

    references = tuple(
        _evidence_from_snapshot(item)
        for item in _mapping_sequence(
            _required(
                payload,
                "provenance",
            ),
            label="observation provenance",
        )
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
        epistemic_status=EpistemicStatus(
            _string(
                _required(
                    payload,
                    "epistemic_status",
                ),
                label="epistemic status",
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
        provenance=ObservationProvenance(references=references),
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

    if observation.to_snapshot() != dict(payload):
        raise ValueError("persisted profile observation is not canonical")

    return observation


def _evidence_from_snapshot(
    payload: Mapping[str, object],
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


def _owned_project_exists(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> sa.ColumnElement[bool]:
    """Create a reusable owner-project EXISTS predicate."""
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(PROJECTS)
        .where(
            PROJECTS.c.id == project_id,
            PROJECTS.c.owner_user_id == owner_user_id,
        )
    )


async def _project_is_owned(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> bool:
    """Resolve ownership without leaking foreign-project existence."""
    result = await session.execute(
        sa.select(sa.literal(True)).where(
            _owned_project_exists(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )
    )

    return result.scalar_one_or_none() is True


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


def _required(
    mapping: Mapping[str, object],
    key: str,
) -> object:
    """Return one required persistence field."""
    if key not in mapping:
        raise ValueError(f"missing persistence field: {key}")

    return mapping[key]


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


def _sequence(
    value: object,
    *,
    label: str,
) -> Sequence[object]:
    """Require a non-string sequence."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")

    return value


def _string(
    value: object,
    *,
    label: str,
) -> str:
    """Require a string."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")

    return value


def _optional_string(
    value: object,
    *,
    label: str,
) -> str | None:
    """Require string or null."""
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
    """Require a non-boolean integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")

    return value


def _optional_integer(
    value: object,
    *,
    label: str,
) -> int | None:
    """Require integer or null."""
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
    """Require a non-boolean real number."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a real number")

    return float(value)


def _uuid(
    value: object,
    *,
    label: str,
) -> UUID:
    """Require or reconstruct a UUID."""
    if isinstance(value, UUID):
        return value

    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a UUID") from error

    raise ValueError(f"{label} must be a UUID")


def _optional_uuid(
    value: object,
    *,
    label: str,
) -> UUID | None:
    """Require UUID or null."""
    if value is None:
        return None

    return _uuid(
        value,
        label=label,
    )


def _datetime(
    value: object,
    *,
    label: str,
) -> datetime:
    """Require or reconstruct a timezone-aware datetime."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"{label} must be an ISO datetime") from error
    else:
        raise ValueError(f"{label} must be a datetime")

    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return result


def _optional_datetime(
    value: object,
    *,
    label: str,
) -> datetime | None:
    """Require datetime or null."""
    if value is None:
        return None

    return _datetime(
        value,
        label=label,
    )
