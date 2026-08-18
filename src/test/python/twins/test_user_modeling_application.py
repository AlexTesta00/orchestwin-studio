"""Tests for governed User Modeling application services."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
)
from orchestwin.models.fake_user_modeling import (
    FakeDeterministicUserModelingAdapter,
)
from orchestwin.models.user_modeling import (
    PersonaProposalRequest,
    PersonaProposalResult,
    UserTwinProposalRequest,
    UserTwinProposalResult,
)
from orchestwin.projects.brief_gate import (
    project_brief_artifact_reference,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    GroundedSnapshotGenerationResult,
    LocalUserModelingApplicationService,
    PersonaOwnerDecision,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
)
from orchestwin.twins.persistence.repositories import (
    VersionAppendStatus,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaProfileVersion,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
BRIEF_GATE_ID = UUID("00000000-0000-4000-8000-000000000030")
BRIEF_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000031")
BRIEF_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000032")

TEAM_ID = UUID("00000000-0000-4000-8000-000000000040")
TEAM_HASH = "c" * 64

CREATED_AT = datetime(
    2026,
    8,
    13,
    13,
    0,
    tzinfo=UTC,
)
GENERATED_AT = datetime(
    2026,
    8,
    13,
    14,
    0,
    tzinfo=UTC,
)

TEAM_REFERENCE = VersionedArtifactReference(
    artifact_id=TEAM_ID,
    version_number=2,
    content_hash=TEAM_HASH,
)


def brief_version(
    *,
    target_users: tuple[
        str,
        ...,
    ] = ("Hotel receptionist",),
) -> ProjectBriefVersion:
    """Create one deterministic Project Brief version."""
    unknown_fields = [
        field
        for field in BriefField
        if field
        not in {
            BriefField.NAME,
            BriefField.TARGET_USERS,
        }
    ]

    brief = create_project_brief(
        name="Hotel Operations Studio",
        target_users=list(target_users),
        unknown_fields=(unknown_fields),
    )

    return ProjectBriefVersion(
        id=BRIEF_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=(brief.content_hash),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def approved_brief_gate(
    version: ProjectBriefVersion,
) -> HumanGate:
    """Create an approved Gate 1 for the exact supplied Brief."""
    draft = create_human_gate(
        gate_id=BRIEF_GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=(CREATED_AT + timedelta(minutes=1)),
    )

    submitted = transition_human_gate(
        draft,
        action=(HumanGateAction.SUBMIT),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        event_id=(BRIEF_SUBMIT_EVENT_ID),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)

    approved = transition_human_gate(
        submitted.gate,
        action=(HumanGateAction.APPROVE),
        actor_user_id=OWNER_ID,
        occurred_at=(CREATED_AT + timedelta(minutes=3)),
        event_id=(BRIEF_APPROVE_EVENT_ID),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)

    return approved.gate


def ready_context(
    *,
    target_users: tuple[
        str,
        ...,
    ] = ("Hotel receptionist",),
) -> GovernedUserModelingContext:
    """Create one fully governed User Modeling context."""
    version = brief_version(target_users=target_users)

    return GovernedUserModelingContext(
        project_id=PROJECT_ID,
        brief_version=version,
        brief_gate=(approved_brief_gate(version)),
        team_reference=(TEAM_REFERENCE),
        approved_team_reference=(TEAM_REFERENCE),
        catalog_version=(AGENT_CATALOG_VERSION),
        catalog_content_hash=(AGENT_CATALOG_CONTENT_HASH),
    )


def changed_team_context(
    context: GovernedUserModelingContext,
) -> GovernedUserModelingContext:
    """Return an equally approved but different Agent Team revision."""
    changed_reference = VersionedArtifactReference(
        artifact_id=UUID("00000000-0000-4000-8000-000000000041"),
        version_number=3,
        content_hash="e" * 64,
    )

    return replace(
        context,
        team_reference=(changed_reference),
        approved_team_reference=(changed_reference),
    )


class FakeGovernancePort:
    """Deterministic owner-scoped governance context provider."""

    def __init__(
        self,
        contexts: list[GovernedUserModelingContext | None],
    ) -> None:
        """Store contexts returned by subsequent reads."""
        if not contexts:
            raise ValueError("at least one fake context is required")

        self._contexts = list(contexts)

    def set_contexts(
        self,
        contexts: list[GovernedUserModelingContext | None],
    ) -> None:
        """Replace subsequent governance responses."""
        if not contexts:
            raise ValueError("at least one fake context is required")

        self._contexts = list(contexts)

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedUserModelingContext | None:
        """Return the configured owner/project context."""
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None

        if len(self._contexts) > 1:
            return self._contexts.pop(0)

        return self._contexts[0]


class MemoryStore:
    """Shared in-memory persistence backing multiple fake UoWs."""

    def __init__(
        self,
    ) -> None:
        """Create empty version histories."""
        self.personas: dict[
            tuple[
                UUID,
                UUID,
            ],
            list[PersonaProfileVersion],
        ] = {}

        self.twins: dict[
            tuple[
                UUID,
                UUID,
            ],
            list[UserTwinProfileVersion],
        ] = {}

        self.snapshots: dict[
            UUID,
            list[UserModelingSnapshotVersion],
        ] = {}


class MemoryPersonaRepository:
    """In-memory persona repository implementing the C08 contract."""

    def __init__(
        self,
        store: MemoryStore,
    ) -> None:
        """Use one shared store."""
        self._store = store

    async def append(
        self,
        version: PersonaProfileVersion,
    ) -> VersionAppendStatus:
        """Append one immutable persona version."""
        key = (
            version.project_id,
            version.persona_id,
        )

        history = self._store.personas.setdefault(
            key,
            [],
        )

        history.append(version)

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
        version_number: int,
    ) -> PersonaProfileVersion | None:
        """Read one exact version."""
        for version in self._store.personas.get(
            (
                project_id,
                persona_id,
            ),
            [],
        ):
            if version.version_number == version_number:
                return version

        return None

    async def current(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> PersonaProfileVersion | None:
        """Read the latest persona revision."""
        history = self._store.personas.get(
            (
                project_id,
                persona_id,
            ),
            [],
        )

        if not history:
            return None

        return max(
            history,
            key=lambda version: version.version_number,
        )

    async def history(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Read persona history in version order."""
        return tuple(
            sorted(
                self._store.personas.get(
                    (
                        project_id,
                        persona_id,
                    ),
                    [],
                ),
                key=lambda version: version.version_number,
            )
        )

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Read one current revision per project persona."""
        current = []

        for (
            stored_project_id,
            persona_id,
        ) in self._store.personas:
            if stored_project_id != project_id:
                continue

            version = await self.current(
                project_id=project_id,
                persona_id=persona_id,
            )

            if version is not None:
                current.append(version)

        return tuple(
            sorted(
                current,
                key=lambda version: version.persona_id.hex,
            )
        )


class MemoryUserTwinRepository:
    """In-memory User Twin repository implementing the C08 contract."""

    def __init__(
        self,
        store: MemoryStore,
    ) -> None:
        """Use one shared store."""
        self._store = store

    async def append(
        self,
        version: UserTwinProfileVersion,
    ) -> VersionAppendStatus:
        """Append one User Twin version."""
        key = (
            version.project_id,
            version.twin_id,
        )

        self._store.twins.setdefault(
            key,
            [],
        ).append(version)

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
        version_number: int,
    ) -> UserTwinProfileVersion | None:
        """Read one exact twin version."""
        for version in self._store.twins.get(
            (
                project_id,
                twin_id,
            ),
            [],
        ):
            if version.version_number == version_number:
                return version

        return None

    async def current(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileVersion | None:
        """Read latest twin revision."""
        history = self._store.twins.get(
            (
                project_id,
                twin_id,
            ),
            [],
        )

        if not history:
            return None

        return max(
            history,
            key=lambda version: version.version_number,
        )

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Read complete twin history."""
        return tuple(
            sorted(
                self._store.twins.get(
                    (
                        project_id,
                        twin_id,
                    ),
                    [],
                ),
                key=lambda version: version.version_number,
            )
        )

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Read one current version per User Twin."""
        current = []

        for (
            stored_project_id,
            twin_id,
        ) in self._store.twins:
            if stored_project_id != project_id:
                continue

            version = await self.current(
                project_id=project_id,
                twin_id=twin_id,
            )

            if version is not None:
                current.append(version)

        return tuple(
            sorted(
                current,
                key=lambda version: version.twin_id.hex,
            )
        )


class MemorySnapshotRepository:
    """In-memory complete User Modeling snapshot repository."""

    def __init__(
        self,
        store: MemoryStore,
    ) -> None:
        """Use one shared store."""
        self._store = store

    async def append(
        self,
        version: UserModelingSnapshotVersion,
    ) -> VersionAppendStatus:
        """Append one complete snapshot."""
        self._store.snapshots.setdefault(
            version.project_id,
            [],
        ).append(version)

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        version_number: int,
    ) -> UserModelingSnapshotVersion | None:
        """Read one exact snapshot version."""
        for version in self._store.snapshots.get(
            project_id,
            [],
        ):
            if version.version_number == version_number:
                return version

        return None

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Read the latest snapshot."""
        history = self._store.snapshots.get(
            project_id,
            [],
        )

        if not history:
            return None

        return max(
            history,
            key=lambda version: version.version_number,
        )

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserModelingSnapshotVersion,
        ...,
    ]:
        """Read snapshot history."""
        return tuple(
            sorted(
                self._store.snapshots.get(
                    project_id,
                    [],
                ),
                key=lambda version: version.version_number,
            )
        )


class TransactionTracker:
    """Observe active fake application transactions."""

    def __init__(
        self,
    ) -> None:
        """Initialize counters."""
        self.active = 0
        self.commits = 0
        self.rollbacks = 0


class MemoryUserModelingUnitOfWork:
    """Minimal UoW over shared in-memory repositories."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        tracker: TransactionTracker,
    ) -> None:
        """Create repositories over one shared store."""
        self.personas = MemoryPersonaRepository(store)
        self.twins = MemoryUserTwinRepository(store)
        self.snapshots = MemorySnapshotRepository(store)

        self._tracker = tracker
        self._completed = False

    async def __aenter__(
        self,
    ) -> MemoryUserModelingUnitOfWork:
        """Enter the fake transaction."""
        self._completed = False
        self._tracker.active += 1

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object | None,
    ) -> None:
        """Rollback uncommitted fake transactions and leave."""
        del exc_type
        del exc_value
        del traceback

        if not self._completed:
            await self.rollback()

        self._tracker.active -= 1

    async def commit(
        self,
    ) -> None:
        """Record explicit commit."""
        self._tracker.commits += 1
        self._completed = True

    async def rollback(
        self,
    ) -> None:
        """Record implicit or explicit rollback."""
        self._tracker.rollbacks += 1
        self._completed = True


class MemoryUowFactory:
    """Create fake UoWs sharing the same persistence state."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        tracker: TransactionTracker,
    ) -> None:
        """Store shared dependencies."""
        self._store = store
        self._tracker = tracker

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> MemoryUserModelingUnitOfWork:
        """Create an owner-scoped fake UoW."""
        if owner_user_id != OWNER_ID:
            raise AssertionError("unexpected fake owner")

        return MemoryUserModelingUnitOfWork(
            store=self._store,
            tracker=self._tracker,
        )


class TrackingProposalPort:
    """Wrap the real deterministic fake and enforce transaction isolation."""

    def __init__(
        self,
        tracker: TransactionTracker,
    ) -> None:
        """Create the wrapped deterministic adapter."""
        self._tracker = tracker
        self._inner = FakeDeterministicUserModelingAdapter()

        self.persona_calls = 0
        self.twin_calls = 0

    async def propose_personas(
        self,
        request: PersonaProposalRequest,
    ) -> PersonaProposalResult:
        """Require persona proposal outside active persistence work."""
        assert self._tracker.active == 0

        self.persona_calls += 1

        return await self._inner.propose_personas(request)

    async def propose_user_twins(
        self,
        request: UserTwinProposalRequest,
    ) -> UserTwinProposalResult:
        """Require twin proposal outside active persistence work."""
        assert self._tracker.active == 0

        self.twin_calls += 1

        return await self._inner.propose_user_twins(request)


class DeterministicUuidFactory:
    """Generate deterministic unique UUIDs for tests."""

    def __init__(
        self,
        start: int = 10_000,
    ) -> None:
        """Set the first integer-backed UUID."""
        self._next = start

    def __call__(
        self,
    ) -> UUID:
        """Return the next deterministic UUID."""
        value = UUID(int=self._next)

        self._next += 1

        return value


def fixed_clock() -> datetime:
    """Return one deterministic generation timestamp."""
    return GENERATED_AT


def build_service(
    context: GovernedUserModelingContext,
) -> tuple[
    LocalUserModelingApplicationService,
    FakeGovernancePort,
    TrackingProposalPort,
    MemoryStore,
    TransactionTracker,
]:
    """Create one completely deterministic application fixture."""
    store = MemoryStore()
    tracker = TransactionTracker()
    governance = FakeGovernancePort(
        [
            context,
        ]
    )
    proposals = TrackingProposalPort(tracker)
    uow_factory = MemoryUowFactory(
        store=store,
        tracker=tracker,
    )

    service = LocalUserModelingApplicationService(
        governance=governance,
        proposals=proposals,
        uow_factory=uow_factory,
        uuid_factory=(DeterministicUuidFactory()),
        clock=fixed_clock,
    )

    return (
        service,
        governance,
        proposals,
        store,
        tracker,
    )


async def propose_and_confirm(
    service: LocalUserModelingApplicationService,
) -> PersonaProfileVersion:
    """Create and confirm the first deterministic persona."""
    proposal = await service.propose_personas(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
    )

    assert proposal.status is (UserModelingApplicationStatus.CREATED)
    assert len(proposal.versions) == 1

    pending = proposal.versions[0]

    confirmation = await service.decide_persona(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        persona_id=(pending.persona_id),
        decision=(PersonaOwnerDecision.CONFIRM),
    )

    assert confirmation.status is (UserModelingApplicationStatus.APPLIED)
    assert confirmation.version is not None

    return confirmation.version


def test_gate_two_approval_is_required_before_persona_proposal() -> None:
    """Do not call the provider until the exact current team is approved."""
    context = replace(
        ready_context(),
        approved_team_reference=None,
    )

    (
        service,
        _governance,
        proposals,
        store,
        _tracker,
    ) = build_service(context)

    result = asyncio.run(
        service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )

    assert result.status is (UserModelingApplicationStatus.REJECTED)
    assert result.issue is (UserModelingApplicationIssueCode.TEAM_APPROVAL_REQUIRED)
    assert proposals.persona_calls == 0
    assert store.personas == {}


def test_persona_proposal_persists_pending_versions_after_recheck() -> None:
    """Persist provider output only after the governed context is rechecked."""
    (
        service,
        _governance,
        proposals,
        store,
        tracker,
    ) = build_service(ready_context())

    result = asyncio.run(
        service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )

    assert result.status is (UserModelingApplicationStatus.CREATED)
    assert result.issue is None
    assert len(result.versions) == 1

    version = result.versions[0]

    assert version.version_number == 1
    assert version.based_on_version_number is None
    assert version.profile.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION

    assert proposals.persona_calls == 1
    assert tracker.active == 0
    assert len(store.personas) == 1


def test_persona_provider_result_is_discarded_when_team_changes() -> None:
    """Do not persist a proposal generated against stale Gate 2 context."""
    context = ready_context()

    (
        service,
        governance,
        proposals,
        store,
        _tracker,
    ) = build_service(context)

    governance.set_contexts(
        [
            context,
            changed_team_context(context),
        ]
    )

    result = asyncio.run(
        service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )

    assert proposals.persona_calls == 1

    assert result.status is (UserModelingApplicationStatus.REJECTED)
    assert result.issue is (UserModelingApplicationIssueCode.CONTEXT_CHANGED)

    assert store.personas == {}


def test_confirming_proto_persona_creates_new_immutable_version() -> None:
    """Represent owner confirmation as a new persona revision."""
    (
        service,
        _governance,
        _proposals,
        store,
        _tracker,
    ) = build_service(ready_context())

    async def scenario() -> tuple[
        PersonaProfileVersion,
        PersonaProfileVersion,
    ]:
        proposed = await service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        first = proposed.versions[0]

        decided = await service.decide_persona(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            persona_id=(first.persona_id),
            decision=(PersonaOwnerDecision.CONFIRM),
        )

        assert decided.version is not None

        return (
            first,
            decided.version,
        )

    (
        first,
        confirmed,
    ) = asyncio.run(scenario())

    assert first.profile.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION

    assert confirmed.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED

    assert confirmed.persona_id == first.persona_id
    assert confirmed.version_number == 2
    assert confirmed.based_on_version_number == 1
    assert confirmed.content_hash != first.content_hash

    history = store.personas[
        (
            PROJECT_ID,
            first.persona_id,
        )
    ]

    assert len(history) == 2


def test_pending_persona_blocks_user_twin_generation() -> None:
    """Require an explicit owner decision before any User Twin exists."""
    (
        service,
        _governance,
        proposals,
        store,
        _tracker,
    ) = build_service(ready_context())

    async def scenario() -> GroundedSnapshotGenerationResult:
        proposed = await service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        assert proposed.status is (UserModelingApplicationStatus.CREATED)

        return await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

    result = asyncio.run(scenario())

    assert result.status is (UserModelingApplicationStatus.REJECTED)
    assert result.issue is (UserModelingApplicationIssueCode.PERSONA_CONFIRMATION_REQUIRED)

    assert proposals.twin_calls == 0
    assert store.twins == {}
    assert store.snapshots == {}


def test_confirmed_persona_creates_grounded_twin_and_snapshot() -> None:
    """Persist the complete governed User Modeling artifact atomically."""
    context = ready_context()

    (
        service,
        _governance,
        proposals,
        store,
        tracker,
    ) = build_service(context)

    async def scenario() -> GroundedSnapshotGenerationResult:
        confirmed = await propose_and_confirm(service)

        assert confirmed.version_number == 2

        return await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

    result = asyncio.run(scenario())

    assert result.status is (UserModelingApplicationStatus.CREATED)
    assert result.issue is None

    assert result.snapshot_version is not None

    assert len(result.twin_versions) == 1

    twin = result.twin_versions[0]

    assert twin.profile.validation_status is UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
    assert twin.profile.project_brief_reference == context.brief_reference
    assert twin.profile.agent_team_reference == TEAM_REFERENCE
    assert twin.profile.catalog_version == AGENT_CATALOG_VERSION
    assert twin.profile.catalog_content_hash == AGENT_CATALOG_CONTENT_HASH

    snapshot_version = result.snapshot_version

    assert snapshot_version.version_number == 1
    assert snapshot_version.based_on_version_number is None
    assert snapshot_version.snapshot.persona_count == 1
    assert snapshot_version.snapshot.twin_count == 1

    assert proposals.twin_calls == 1
    assert tracker.active == 0

    assert len(store.twins) == 1
    assert len(store.snapshots[PROJECT_ID]) == 1


def test_rejected_persona_is_excluded_when_confirmed_persona_remains() -> None:
    """Allow the owner to reduce the modeled target-user set explicitly."""
    context = ready_context(
        target_users=(
            "Hotel receptionist",
            "Hotel manager",
        )
    )

    (
        service,
        _governance,
        _proposals,
        _store,
        _tracker,
    ) = build_service(context)

    async def scenario() -> GroundedSnapshotGenerationResult:
        proposed = await service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        assert len(proposed.versions) == 2

        first = proposed.versions[0]
        second = proposed.versions[1]

        confirmation = await service.decide_persona(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            persona_id=(first.persona_id),
            decision=(PersonaOwnerDecision.CONFIRM),
        )

        assert confirmation.status is (UserModelingApplicationStatus.APPLIED)

        rejection = await service.decide_persona(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            persona_id=(second.persona_id),
            decision=(PersonaOwnerDecision.REJECT),
            reason=("Hotel managers are outside the first project iteration."),
        )

        assert rejection.status is (UserModelingApplicationStatus.APPLIED)

        return await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

    result = asyncio.run(scenario())

    assert result.status is (UserModelingApplicationStatus.CREATED)
    assert result.snapshot_version is not None
    assert result.snapshot_version.snapshot.persona_count == 1
    assert result.snapshot_version.snapshot.twin_count == 1


def test_all_rejected_personas_leave_no_grounded_snapshot() -> None:
    """Require at least one confirmed target-user representation."""
    (
        service,
        _governance,
        proposals,
        store,
        _tracker,
    ) = build_service(ready_context())

    async def scenario() -> GroundedSnapshotGenerationResult:
        proposed = await service.propose_personas(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        persona = proposed.versions[0]

        rejected = await service.decide_persona(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            persona_id=(persona.persona_id),
            decision=(PersonaOwnerDecision.REJECT),
            reason=("This target group is not part of the current scope."),
        )

        assert rejected.status is (UserModelingApplicationStatus.APPLIED)

        return await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

    result = asyncio.run(scenario())

    assert result.status is (UserModelingApplicationStatus.REJECTED)
    assert result.issue is (UserModelingApplicationIssueCode.PERSONAS_REQUIRED)

    assert proposals.twin_calls == 0
    assert store.twins == {}
    assert store.snapshots == {}


def test_twin_provider_result_is_discarded_when_governance_changes() -> None:
    """Recheck Gate 2 after the provider and before persistence."""
    context = ready_context()

    (
        service,
        governance,
        proposals,
        store,
        _tracker,
    ) = build_service(context)

    async def scenario() -> GroundedSnapshotGenerationResult:
        await propose_and_confirm(service)

        governance.set_contexts(
            [
                context,
                changed_team_context(context),
            ]
        )

        return await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

    result = asyncio.run(scenario())

    assert proposals.twin_calls == 1

    assert result.status is (UserModelingApplicationStatus.REJECTED)
    assert result.issue is (UserModelingApplicationIssueCode.CONTEXT_CHANGED)

    assert store.twins == {}
    assert store.snapshots == {}


def test_second_initial_snapshot_generation_is_rejected() -> None:
    """Do not silently regenerate a second initial User Modeling snapshot."""
    (
        service,
        _governance,
        proposals,
        _store,
        _tracker,
    ) = build_service(ready_context())

    async def scenario() -> tuple[
        GroundedSnapshotGenerationResult,
        GroundedSnapshotGenerationResult,
    ]:
        await propose_and_confirm(service)

        first = await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        second = await service.generate_grounded_snapshot(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )

        return (
            first,
            second,
        )

    (
        first,
        second,
    ) = asyncio.run(scenario())

    assert first.status is (UserModelingApplicationStatus.CREATED)

    assert second.status is (UserModelingApplicationStatus.REJECTED)
    assert second.issue is (UserModelingApplicationIssueCode.SNAPSHOT_ALREADY_EXISTS)

    assert proposals.twin_calls == 1
