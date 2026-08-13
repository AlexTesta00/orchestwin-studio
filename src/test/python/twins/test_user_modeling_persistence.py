"""Tests for User Modeling snapshots, repositories, and Unit of Work."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)
from orchestwin.twins.persistence.repositories import (
    SqlAlchemyPersonaVersionRepository,
    SqlAlchemyUserModelingSnapshotRepository,
    VersionAppendStatus,
)
from orchestwin.twins.persistence.snapshots import (
    persona_version_from_record,
    persona_version_to_record,
    user_modeling_snapshot_version_from_record,
    user_modeling_snapshot_version_to_record,
    user_twin_version_from_record,
    user_twin_version_to_record,
)
from orchestwin.twins.persistence.uow import (
    SqlAlchemyUserModelingUnitOfWork,
)
from orchestwin.twins.personas import (
    PersonaField,
    PersonaProfileVersion,
    create_owner_provided_persona,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000021")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")
TWIN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000031")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000000040")
TEAM_ID = UUID("00000000-0000-4000-8000-000000000050")
SNAPSHOT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000060")

BRIEF_HASH = "b" * 64
TEAM_HASH = "c" * 64
CATALOG_HASH = "d" * 64

CREATED_AT = datetime(
    2026,
    8,
    13,
    12,
    0,
    tzinfo=UTC,
)

BRIEF_REFERENCE = VersionedArtifactReference(
    artifact_id=BRIEF_ID,
    version_number=4,
    content_hash=BRIEF_HASH,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=TEAM_ID,
    version_number=2,
    content_hash=TEAM_HASH,
)

_LIST_TWIN_FIELDS = frozenset(
    {
        UserTwinField.EXPERTISE,
        UserTwinField.GOALS,
        UserTwinField.RECURRING_TASKS,
        UserTwinField.INFORMATION_NEEDS,
        UserTwinField.DECISION_CRITERIA,
        UserTwinField.PREFERRED_VOCABULARY,
        UserTwinField.FRUSTRATIONS,
        UserTwinField.PAIN_POINTS,
        UserTwinField.TRUST_CONCERNS,
        UserTwinField.ACCESSIBILITY_NEEDS,
        UserTwinField.OPERATIONAL_CONSTRAINTS,
        UserTwinField.ASSUMPTIONS,
    }
)


def evidence(
    locator: str,
) -> EvidenceReference:
    """Create one deterministic approved-brief evidence reference."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=str(BRIEF_ID),
        source_version=4,
        content_hash=BRIEF_HASH,
        locator=locator,
        summary=("Owner-provided project context."),
    )


def observation(
    observation_key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one deterministic user-provided observation."""
    return ProfileObservation(
        observation_key=(observation_key),
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(ObservationProvenance.from_references((evidence(observation_key),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def persona_version() -> PersonaProfileVersion:
    """Create one complete confirmed persona version."""
    profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=(
            observation(
                PersonaField.ROLE.observation_key,
                ObservationValue.from_text("Hotel receptionist"),
            ),
            observation(
                PersonaField.SUMMARY.observation_key,
                ObservationValue.from_text(
                    "Front-desk staff coordinating guests and reservations."
                ),
            ),
            observation(
                PersonaField.GOALS.observation_key,
                ObservationValue.from_items(
                    (
                        "Avoid booking conflicts",
                        "Serve guests quickly",
                    )
                ),
            ),
            observation(
                PersonaField.CONTEXT_OF_USE.observation_key,
                ObservationValue.from_text("Uses the application at the hotel front desk."),
            ),
        ),
    )

    return PersonaProfileVersion(
        id=PERSONA_VERSION_ID,
        project_id=PROJECT_ID,
        persona_id=PERSONA_ID,
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def twin_observations() -> tuple[
    ProfileObservation,
    ...,
]:
    """Create all required User Twin observations."""
    values: list[ProfileObservation] = []

    for field in UserTwinField:
        if field is UserTwinField.AGE_RANGE:
            continue

        if field is UserTwinField.ROLE:
            value = ObservationValue.from_text("Hotel receptionist")
        elif field in _LIST_TWIN_FIELDS:
            value = ObservationValue.from_items((f"Known {field.value}",))
        else:
            value = ObservationValue.from_text(f"Known {field.value}")

        values.append(
            observation(
                field.observation_key,
                value,
            )
        )

    return tuple(values)


def twin_version() -> UserTwinProfileVersion:
    """Create one complete User Twin version."""
    persona = persona_version()

    profile = create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=persona,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(twin_observations()),
    )

    return UserTwinProfileVersion(
        id=TWIN_VERSION_ID,
        project_id=PROJECT_ID,
        twin_id=TWIN_ID,
        version_number=1,
        profile=profile,
        content_hash=(profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def snapshot_version() -> UserModelingSnapshotVersion:
    """Create one complete immutable User Modeling snapshot version."""
    persona = persona_version()
    twin = twin_version()

    snapshot = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        persona_versions=(persona,),
        twin_versions=(twin,),
    )

    return UserModelingSnapshotVersion(
        id=SNAPSHOT_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        snapshot=snapshot,
        content_hash=(snapshot.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_persona_record_round_trips_without_losing_epistemic_metadata() -> None:
    """Reconstruct a persona exactly from relational and JSONB state."""
    original = persona_version()

    recovered = persona_version_from_record(persona_version_to_record(original))

    assert recovered == original
    assert recovered.profile.to_snapshot() == original.profile.to_snapshot()


def test_user_twin_record_round_trips_exact_grounding() -> None:
    """Preserve persona, brief, team, catalog, and observations."""
    original = twin_version()

    recovered = user_twin_version_from_record(user_twin_version_to_record(original))

    assert recovered == original
    assert recovered.profile.persona_reference == original.profile.persona_reference
    assert recovered.profile.project_brief_reference == BRIEF_REFERENCE
    assert recovered.profile.agent_team_reference == TEAM_REFERENCE


def test_complete_snapshot_record_round_trips() -> None:
    """Reconstruct the authoritative User Modeling artifact exactly."""
    original = snapshot_version()

    recovered = user_modeling_snapshot_version_from_record(
        user_modeling_snapshot_version_to_record(original)
    )

    assert recovered == original
    assert recovered.content_hash == original.content_hash
    assert recovered.snapshot.persona_count == 1
    assert recovered.snapshot.twin_count == 1


class FakeMappings:
    """Minimal SQLAlchemy mappings-result double."""

    def __init__(
        self,
        rows: list[
            dict[
                str,
                object,
            ]
        ],
    ) -> None:
        """Store deterministic rows."""
        self._rows = rows

    def one_or_none(
        self,
    ) -> (
        dict[
            str,
            object,
        ]
        | None
    ):
        """Return zero or one row."""
        if not self._rows:
            return None

        if len(self._rows) != 1:
            raise AssertionError("expected zero or one fake row")

        return self._rows[0]

    def all(
        self,
    ) -> list[
        dict[
            str,
            object,
        ]
    ]:
        """Return all fake mapping rows."""
        return list(self._rows)


class FakeResult:
    """Minimal SQLAlchemy Result double."""

    def __init__(
        self,
        *,
        scalar: object = None,
        rows: list[
            dict[
                str,
                object,
            ]
        ]
        | None = None,
    ) -> None:
        """Store fake scalar and mapping values."""
        self._scalar = scalar
        self._rows = rows if rows is not None else []

    def scalar_one_or_none(
        self,
    ) -> object:
        """Return the configured scalar."""
        return self._scalar

    def mappings(
        self,
    ) -> FakeMappings:
        """Return mapping access."""
        return FakeMappings(self._rows)


class RecordingSession:
    """Async session double recording executed SQLAlchemy statements."""

    def __init__(
        self,
        results: list[FakeResult] | None = None,
    ) -> None:
        """Prepare deterministic execute results."""
        self.results = list(results if results is not None else [])
        self.statements: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(
        self,
        statement: Any,
    ) -> FakeResult:
        """Record one statement and return the next fake result."""
        self.statements.append(statement)

        if self.results:
            return self.results.pop(0)

        return FakeResult()

    async def commit(
        self,
    ) -> None:
        """Record a commit."""
        self.commits += 1

    async def rollback(
        self,
    ) -> None:
        """Record a rollback."""
        self.rollbacks += 1


def test_persona_reads_are_owner_scoped() -> None:
    """Require both project and authenticated owner in read queries."""

    async def scenario() -> str:
        session = RecordingSession(
            [
                FakeResult(rows=[]),
            ]
        )
        repository = SqlAlchemyPersonaVersionRepository(
            cast(
                AsyncSession,
                session,
            ),
            owner_user_id=OWNER_ID,
        )

        result = await repository.current(
            project_id=PROJECT_ID,
            persona_id=PERSONA_ID,
        )

        assert result is None
        assert len(session.statements) == 1

        return str(session.statements[0].compile(dialect=(postgresql.dialect()))).lower()

    sql = asyncio.run(scenario())

    assert "persona_profile_versions" in sql
    assert "projects" in sql
    assert "owner_user_id" in sql
    assert "project_id" in sql
    assert "exists" in sql


def test_append_hides_foreign_project_as_not_found() -> None:
    """Do not insert versions when ownership cannot be established."""

    async def scenario() -> tuple[
        VersionAppendStatus,
        int,
    ]:
        session = RecordingSession(
            [
                FakeResult(scalar=None),
            ]
        )

        repository = SqlAlchemyPersonaVersionRepository(
            cast(
                AsyncSession,
                session,
            ),
            owner_user_id=OWNER_ID,
        )

        status = await repository.append(persona_version())

        return (
            status,
            len(session.statements),
        )

    (
        status,
        statement_count,
    ) = asyncio.run(scenario())

    assert status is (VersionAppendStatus.PROJECT_NOT_FOUND)

    assert statement_count == 1


def test_snapshot_append_requires_exact_brief_and_team_context() -> None:
    """Reject stale or cross-project context before snapshot insertion."""

    async def scenario() -> tuple[
        VersionAppendStatus,
        int,
        str,
    ]:
        session = RecordingSession(
            [
                FakeResult(scalar=True),
                FakeResult(scalar=None),
            ]
        )

        repository = SqlAlchemyUserModelingSnapshotRepository(
            cast(
                AsyncSession,
                session,
            ),
            owner_user_id=OWNER_ID,
        )

        status = await repository.append(snapshot_version())

        context_sql = str(session.statements[1].compile(dialect=(postgresql.dialect()))).lower()

        return (
            status,
            len(session.statements),
            context_sql,
        )

    (
        status,
        statement_count,
        context_sql,
    ) = asyncio.run(scenario())

    assert status is (VersionAppendStatus.CONTEXT_NOT_FOUND)
    assert statement_count == 2

    assert "project_brief_versions" in context_sql
    assert "team_proposals" in context_sql
    assert "content_hash" in context_sql
    assert "version_number" in context_sql


def test_unit_of_work_commits_or_rolls_back_explicitly() -> None:
    """Keep transaction completion controlled by the application layer."""

    async def scenario() -> tuple[
        RecordingSession,
        RecordingSession,
    ]:
        committed_session = RecordingSession()
        committed_uow = SqlAlchemyUserModelingUnitOfWork(
            cast(
                AsyncSession,
                committed_session,
            ),
            owner_user_id=OWNER_ID,
        )

        async with committed_uow:
            await committed_uow.commit()

        rolled_back_session = RecordingSession()
        rolled_back_uow = SqlAlchemyUserModelingUnitOfWork(
            cast(
                AsyncSession,
                rolled_back_session,
            ),
            owner_user_id=OWNER_ID,
        )

        async with rolled_back_uow:
            pass

        return (
            committed_session,
            rolled_back_session,
        )

    (
        committed,
        rolled_back,
    ) = asyncio.run(scenario())

    assert committed.commits == 1
    assert committed.rollbacks == 0

    assert rolled_back.commits == 0
    assert rolled_back.rollbacks == 1
