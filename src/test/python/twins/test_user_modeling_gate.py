"""Tests for Gate 3 User Modeling approval."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

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
from orchestwin.twins.personas import (
    PersonaField,
    PersonaProfileVersion,
    create_owner_provided_persona,
)
from orchestwin.twins.user_modeling_gate import (
    LocalUserModelingGateService,
    UserModelingGateDecisionStatus,
    UserModelingGateSubmissionStatus,
    user_modeling_approval_manifest,
    user_modeling_approval_state,
    user_modeling_artifact_reference,
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_project_grounded_user_twin,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateEventKind,
    HumanGateStatus,
    HumanGateType,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")

PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
PERSONA_VERSION_ID = UUID("00000000-0000-4000-8000-000000000021")

TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")
TWIN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000031")

BRIEF_ID = UUID("00000000-0000-4000-8000-000000000040")
TEAM_ID = UUID("00000000-0000-4000-8000-000000000050")

SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000060")
SECOND_SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000061")

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
    content_hash="b" * 64,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=TEAM_ID,
    version_number=2,
    content_hash="c" * 64,
)

CATALOG_HASH = "d" * 64

_LIST_FIELDS = frozenset(
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
    """Create deterministic Project Brief evidence."""
    return EvidenceReference(
        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
        source_id=str(BRIEF_ID),
        source_version=4,
        content_hash="b" * 64,
        locator=locator,
    )


def observation(
    key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one deterministic user-provided observation."""
    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(ObservationProvenance.from_references((evidence(key),))),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def persona_version() -> PersonaProfileVersion:
    """Create one confirmed persona version."""
    profile = create_owner_provided_persona(
        name="Hotel Receptionist",
        observations=(
            observation(
                PersonaField.ROLE.observation_key,
                ObservationValue.from_text("Hotel receptionist"),
            ),
            observation(
                PersonaField.SUMMARY.observation_key,
                ObservationValue.from_text("Front-desk staff."),
            ),
            observation(
                PersonaField.GOALS.observation_key,
                ObservationValue.from_items(("Serve guests efficiently",)),
            ),
            observation(
                PersonaField.CONTEXT_OF_USE.observation_key,
                ObservationValue.from_text("Hotel front desk"),
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
        elif field in _LIST_FIELDS:
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


def snapshot_version() -> UserModelingSnapshotVersion:
    """Create the first project-grounded modeling snapshot."""
    persona = persona_version()

    twin_profile = create_project_grounded_user_twin(
        name="Receptionist Twin",
        persona_version=persona,
        project_brief_reference=(BRIEF_REFERENCE),
        agent_team_reference=(TEAM_REFERENCE),
        catalog_version=1,
        catalog_content_hash=(CATALOG_HASH),
        observations=(twin_observations()),
    )

    twin = UserTwinProfileVersion(
        id=TWIN_VERSION_ID,
        project_id=PROJECT_ID,
        twin_id=TWIN_ID,
        version_number=1,
        profile=twin_profile,
        content_hash=(twin_profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

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
        id=SNAPSHOT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        snapshot=snapshot,
        content_hash=(snapshot.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def revised_snapshot_version(
    first: UserModelingSnapshotVersion,
) -> UserModelingSnapshotVersion:
    """Create one newer immutable snapshot with User Twin version 2."""
    original_twin = first.snapshot.twin_versions[0]

    revised_profile = replace(
        original_twin.profile,
        name=("Receptionist Twin Revised"),
    )

    revised_twin = UserTwinProfileVersion(
        id=UUID("00000000-0000-4000-8000-000000000032"),
        project_id=PROJECT_ID,
        twin_id=TWIN_ID,
        version_number=2,
        based_on_version_number=1,
        profile=revised_profile,
        content_hash=(revised_profile.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=(CREATED_AT + timedelta(hours=1)),
    )

    revised_snapshot = create_user_modeling_snapshot(
        project_id=PROJECT_ID,
        project_brief_reference=(first.snapshot.project_brief_reference),
        agent_team_reference=(first.snapshot.agent_team_reference),
        catalog_version=(first.snapshot.catalog_version),
        catalog_content_hash=(first.snapshot.catalog_content_hash),
        persona_versions=(first.snapshot.persona_versions),
        twin_versions=(revised_twin,),
    )

    return UserModelingSnapshotVersion(
        id=SECOND_SNAPSHOT_ID,
        project_id=PROJECT_ID,
        version_number=2,
        based_on_version_number=1,
        snapshot=revised_snapshot,
        content_hash=(revised_snapshot.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=(CREATED_AT + timedelta(hours=1)),
    )


class MemoryCurrentSnapshotRepository:
    """Owner-scoped in-memory current snapshot repository."""

    def __init__(
        self,
        version: (UserModelingSnapshotVersion | None),
    ) -> None:
        """Set the current snapshot."""
        self.version = version

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Return current snapshot only for its owner/project."""
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return None

        return self.version


class MemoryHumanGateRepository:
    """Minimal in-memory implementation of HumanGateRepository behavior."""

    def __init__(self) -> None:
        """Create empty Gate 3 state."""
        self.latest: HumanGate | None = None
        self.events: dict[
            UUID,
            list[HumanGateEvent],
        ] = {}

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        """Return latest gate only for exact owner scope."""
        gate = self.latest

        if gate is None:
            return None

        if (
            project_id != gate.project_id
            or owner_user_id != gate.owner_user_id
            or gate_type is not gate.gate_type
        ):
            return None

        return gate

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist a newly submitted gate and initial event."""
        self.latest = gate

        self.events.setdefault(
            gate.id,
            [],
        ).append(event)

        return gate

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist one transition while keeping event history append-only."""
        if previous_gate.id != updated_gate.id:
            raise AssertionError("gate transition must keep gate identity")

        self.latest = updated_gate

        self.events.setdefault(
            updated_gate.id,
            [],
        ).append(event)

        return updated_gate

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Return gate events without cross-owner leakage."""
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return ()

        return tuple(
            self.events.get(
                gate_id,
                [],
            )
        )


class MemoryGateUnitOfWork:
    """Shared fake UoW for Gate 3 tests."""

    def __init__(
        self,
        *,
        current_snapshots: (MemoryCurrentSnapshotRepository),
        gates: MemoryHumanGateRepository,
    ) -> None:
        """Store repository adapters."""
        self.current_snapshots = current_snapshots
        self.gates = gates

    async def __aenter__(
        self,
    ) -> MemoryGateUnitOfWork:
        """Enter fake transaction."""
        return self

    async def __aexit__(
        self,
        exception_type: (type[BaseException] | None),
        exception: (BaseException | None),
        traceback: (TracebackType | None),
    ) -> None:
        """Leave fake transaction."""
        del exception_type
        del exception
        del traceback


class MemoryGateUowFactory:
    """Create Gate 3 UoWs over shared repositories."""

    def __init__(
        self,
        version: (UserModelingSnapshotVersion | None),
    ) -> None:
        """Seed shared persistence state."""
        self.current_snapshots = MemoryCurrentSnapshotRepository(version)
        self.gates = MemoryHumanGateRepository()

    def __call__(
        self,
    ) -> MemoryGateUnitOfWork:
        """Create one fake transactional boundary."""
        return MemoryGateUnitOfWork(
            current_snapshots=(self.current_snapshots),
            gates=self.gates,
        )


class DeterministicUuidFactory:
    """Generate deterministic UUIDs."""

    def __init__(
        self,
        start: int,
    ) -> None:
        """Configure first integer-backed UUID."""
        self._next = start

    def __call__(
        self,
    ) -> UUID:
        """Return next deterministic UUID."""
        result = UUID(int=self._next)
        self._next += 1

        return result


class MutableClock:
    """Deterministic monotonic test clock."""

    def __init__(
        self,
        value: datetime,
    ) -> None:
        """Set current time."""
        self.value = value

    def __call__(
        self,
    ) -> datetime:
        """Return configured time."""
        return self.value


def build_service(
    version: (UserModelingSnapshotVersion | None),
) -> tuple[
    LocalUserModelingGateService,
    MemoryGateUowFactory,
    MutableClock,
]:
    """Build one deterministic Gate 3 fixture."""
    unit_factory = MemoryGateUowFactory(version)

    clock = MutableClock(CREATED_AT + timedelta(hours=2))

    service = LocalUserModelingGateService(
        unit_of_work_factory=(unit_factory),
        clock=clock,
        gate_id_factory=(DeterministicUuidFactory(10_000)),
        event_id_factory=(DeterministicUuidFactory(20_000)),
    )

    return (
        service,
        unit_factory,
        clock,
    )


def test_user_modeling_gate_type_and_artifact_reference_are_exact() -> None:
    """Bind Gate 3 to the exact immutable User Modeling version."""
    version = snapshot_version()

    reference = user_modeling_artifact_reference(version)

    assert HumanGateType.USER_MODELING.value == "USER_MODELING"

    assert reference.project_id == PROJECT_ID
    assert reference.gate_type is (HumanGateType.USER_MODELING)
    assert reference.artifact_id == version.id
    assert reference.version == version.version_number
    assert reference.content_hash == version.content_hash


def test_gate_manifest_exposes_every_exact_governed_version() -> None:
    """Make Gate 3 composition inspectable rather than hash-only."""
    version = snapshot_version()

    manifest = user_modeling_approval_manifest(version)

    assert manifest.snapshot_version_id == version.id
    assert manifest.snapshot_version_number == 1
    assert manifest.snapshot_content_hash == version.content_hash

    assert manifest.project_brief_reference == BRIEF_REFERENCE
    assert manifest.agent_team_reference == TEAM_REFERENCE

    assert len(manifest.persona_versions) == 1

    persona = manifest.persona_versions[0]

    assert persona.persona_id == PERSONA_ID
    assert persona.version_id == PERSONA_VERSION_ID
    assert persona.version_number == 1

    assert len(manifest.twin_versions) == 1

    twin = manifest.twin_versions[0]

    assert twin.twin_id == TWIN_ID
    assert twin.version_id == TWIN_VERSION_ID
    assert twin.version_number == 1


def test_submit_requires_current_owned_snapshot() -> None:
    """Do not create Gate 3 before User Modeling exists."""
    (
        service,
        _factory,
        _clock,
    ) = build_service(None)

    result = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (UserModelingGateSubmissionStatus.SNAPSHOT_NOT_FOUND)
    assert result.gate is None


def test_submit_and_approve_derive_owner_approved_lifecycle() -> None:
    """Approve Gate 3 without mutating persisted User Twin state."""
    version = snapshot_version()

    (
        service,
        _factory,
        clock,
    ) = build_service(version)

    async def scenario():
        submitted = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        assert submitted.gate is not None

        clock.value += timedelta(minutes=1)

        approved = await service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )

        return (
            submitted,
            approved,
        )

    (
        submitted,
        approved,
    ) = asyncio.run(scenario())

    assert submitted.status is (UserModelingGateSubmissionStatus.SUBMITTED)

    assert submitted.gate is not None
    assert submitted.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert submitted.gate.iteration == 1

    assert approved.status is (UserModelingGateDecisionStatus.APPLIED)
    assert approved.gate is not None
    assert approved.gate.status is HumanGateStatus.APPROVED

    assert (
        user_modeling_gate_is_currently_approved(
            approved.gate,
            version,
        )
        is True
    )

    state = user_modeling_approval_state(
        version=version,
        gate=approved.gate,
    )

    assert state.approved is True
    assert len(state.twins) == 1

    twin_state = state.twins[0]

    assert twin_state.persisted_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert twin_state.effective_status is UserTwinLifecycleStatus.OWNER_APPROVED_UT

    persisted_twin = version.snapshot.twin_versions[0]

    assert persisted_twin.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT


def test_repeated_submit_reports_already_pending() -> None:
    """Do not create duplicate Gate 3 iterations for one snapshot."""
    version = snapshot_version()

    (
        service,
        _factory,
        _clock,
    ) = build_service(version)

    async def scenario():
        first = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        second = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        return first, second

    first, second = asyncio.run(scenario())

    assert first.status is (UserModelingGateSubmissionStatus.SUBMITTED)

    assert second.status is (UserModelingGateSubmissionStatus.ALREADY_PENDING)

    assert second.gate == first.gate


def test_new_snapshot_immediately_invalidates_effective_approval() -> None:
    """Never apply an old Gate 3 approval to a newer snapshot."""
    first = snapshot_version()
    second = revised_snapshot_version(first)

    (
        service,
        _factory,
        clock,
    ) = build_service(first)

    async def scenario() -> HumanGate:
        await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        clock.value += timedelta(minutes=1)

        approved = await service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )

        assert approved.gate is not None

        return approved.gate

    old_gate = asyncio.run(scenario())

    assert (
        user_modeling_gate_is_currently_approved(
            old_gate,
            first,
        )
        is True
    )

    assert (
        user_modeling_gate_is_currently_approved(
            old_gate,
            second,
        )
        is False
    )

    state = user_modeling_approval_state(
        version=second,
        gate=old_gate,
    )

    assert state.approved is False
    assert state.twins[0].effective_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT


def test_submitting_new_snapshot_marks_old_gate_stale_and_starts_next_iteration() -> None:
    """Persist the supersession event before opening Gate 3 iteration two."""
    first = snapshot_version()
    second = revised_snapshot_version(first)

    (
        service,
        factory,
        clock,
    ) = build_service(first)

    async def scenario():
        await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        clock.value += timedelta(minutes=1)

        approved = await service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )

        assert approved.gate is not None

        old_gate_id = approved.gate.id

        factory.current_snapshots.version = second

        clock.value += timedelta(hours=1)

        submitted_second = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        old_events = await factory.gates.list_events_owned(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            gate_id=old_gate_id,
        )

        return (
            submitted_second,
            old_events,
        )

    (
        submitted_second,
        old_events,
    ) = asyncio.run(scenario())

    assert submitted_second.status is UserModelingGateSubmissionStatus.SUBMITTED

    assert submitted_second.gate is not None
    assert submitted_second.gate.iteration == 2
    assert submitted_second.gate.artifact == user_modeling_artifact_reference(second)
    assert submitted_second.gate.status is HumanGateStatus.PENDING_APPROVAL

    assert len(submitted_second.events) == 2

    assert submitted_second.events[0].kind is HumanGateEventKind.ARTIFACT_SUPERSEDED

    assert any(event.kind is HumanGateEventKind.ARTIFACT_SUPERSEDED for event in old_events)


def test_revision_request_requires_new_snapshot_before_resubmission() -> None:
    """Do not resubmit the same rejected/revision-requested artifact."""
    version = snapshot_version()

    (
        service,
        _factory,
        clock,
    ) = build_service(version)

    async def scenario():
        await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        clock.value += timedelta(minutes=1)

        revision = await service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.REQUEST_REVISION),
            reason=("Clarify the User Twin goals before approval."),
        )

        clock.value += timedelta(minutes=1)

        repeated = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        return (
            revision,
            repeated,
        )

    revision, repeated = asyncio.run(scenario())

    assert revision.status is (UserModelingGateDecisionStatus.APPLIED)
    assert revision.gate is not None
    assert revision.gate.status is HumanGateStatus.REVISION_REQUESTED

    assert repeated.status is (UserModelingGateSubmissionStatus.NEW_SNAPSHOT_REQUIRED)


def test_decision_against_superseded_snapshot_marks_gate_stale() -> None:
    """Reject an owner decision if the authoritative snapshot changed first."""
    first = snapshot_version()
    second = revised_snapshot_version(first)

    (
        service,
        factory,
        clock,
    ) = build_service(first)

    async def scenario():
        submitted = await service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )

        assert submitted.gate is not None

        factory.current_snapshots.version = second

        clock.value += timedelta(hours=1)

        return await service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )

    result = asyncio.run(scenario())

    assert result.status is (UserModelingGateDecisionStatus.ARTIFACT_STALE)
    assert result.gate is not None
    assert result.gate.status is HumanGateStatus.STALE
    assert result.event is not None
    assert result.event.kind is HumanGateEventKind.ARTIFACT_SUPERSEDED
