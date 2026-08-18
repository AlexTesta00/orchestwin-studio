"""Tests for versioned team-proposal application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.agents.proposals import (
    LocalTeamProposalApplicationService,
    TeamProposalApplicationStatus,
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamProposalVersionCreationResult,
    TeamProposalVersionCreationStatus,
    TeamSelectionContext,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    TeamProposalGenerationResult,
    TeamProposalPort,
    TeamProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_artifact_reference,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


def complete_brief_version(
    *,
    version_number: int = 1,
    description: str = ("A Vue web application with a FastAPI backend."),
) -> ProjectBriefVersion:
    """Create a deterministic epistemically complete brief."""
    provided_fields = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
    }
    brief = create_project_brief(
        name="Team proposal project",
        description=description,
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
        ],
        unknown_fields=[field for field in BriefField if field not in provided_fields],
    )

    return ProjectBriefVersion(
        id=UUID(int=100 + version_number),
        project_id=PROJECT_ID,
        version_number=version_number,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def approved_gate(
    version: ProjectBriefVersion,
):
    """Create one approved Gate 1 for the supplied brief."""
    draft = create_human_gate(
        gate_id=UUID(int=200 + version.version_number),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=(project_brief_artifact_reference(version)),
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=(NOW + timedelta(seconds=1)),
        event_id=UUID(int=300 + version.version_number),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=(NOW + timedelta(seconds=2)),
        event_id=UUID(int=400 + version.version_number),
    )

    assert approved.status is (HumanGateTransitionStatus.APPLIED)

    return approved.gate


def selection_context(
    *,
    version: ProjectBriefVersion | None,
    gate=None,
    owner_user_id: UUID = OWNER_ID,
) -> TeamSelectionContext:
    """Create a deterministic project selection context."""
    return TeamSelectionContext(
        project_id=PROJECT_ID,
        owner_user_id=owner_user_id,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief_version=version,
        brief_gate=gate,
    )


class InMemoryTeamSelectionContextRepository:
    """Mutable adapter double used to simulate context changes."""

    def __init__(self) -> None:
        self.contexts: dict[
            tuple[UUID, UUID],
            TeamSelectionContext,
        ] = {}

    def set_context(
        self,
        context: TeamSelectionContext,
    ) -> None:
        """Set the current context for one owner and project."""
        self.contexts[
            (
                context.project_id,
                context.owner_user_id,
            )
        ] = context

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return current owner-scoped context."""
        return self.contexts.get(
            (
                project_id,
                owner_user_id,
            )
        )

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return the same context as the in-memory row lock."""
        return await self.get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )


class InMemoryTeamProposalVersionRepository:
    """In-memory immutable proposal-version repository."""

    def __init__(self) -> None:
        self.versions: dict[
            UUID,
            list[TeamProposalVersion],
        ] = {}

    async def create_generated_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        proposal,
    ) -> TeamProposalVersionCreationResult:
        """Create or reuse one generated proposal version."""
        existing = self.versions.setdefault(
            project_id,
            [],
        )

        if existing and existing[-1].content_hash == proposal.content_hash:
            return TeamProposalVersionCreationResult(
                status=(TeamProposalVersionCreationStatus.UNCHANGED),
                version=existing[-1],
            )

        version = TeamProposalVersion(
            id=UUID(int=1000 + len(existing)),
            project_id=project_id,
            version_number=(len(existing) + 1),
            proposal=proposal,
            revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED),
            created_by_user_id=(owner_user_id),
            created_at=NOW,
        )
        existing.append(version)

        return TeamProposalVersionCreationResult(
            status=(TeamProposalVersionCreationStatus.CREATED),
            version=version,
        )

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest in-memory proposal."""
        void_owner = owner_user_id
        del void_owner

        versions = self.versions.get(
            project_id,
            [],
        )

        return versions[-1] if versions else None

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> TeamProposalVersion | None:
        """Return one in-memory proposal version."""
        void_owner = owner_user_id
        del void_owner

        return next(
            (
                version
                for version in self.versions.get(
                    project_id,
                    [],
                )
                if version.version_number == version_number
            ),
            None,
        )

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return immutable in-memory history."""
        void_owner = owner_user_id
        del void_owner

        return tuple(
            self.versions.get(
                project_id,
                [],
            )
        )


class InMemoryTeamProposalUnitOfWork:
    """Reusable in-memory proposal transaction boundary."""

    def __init__(
        self,
        contexts: (InMemoryTeamSelectionContextRepository),
        proposals: (InMemoryTeamProposalVersionRepository),
    ) -> None:
        self.contexts = contexts
        self.proposals = proposals

    async def __aenter__(
        self,
    ) -> InMemoryTeamProposalUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class ContextMutatingProposalAdapter:
    """Delegate proposal generation and then replace the current context."""

    def __init__(
        self,
        *,
        contexts: (InMemoryTeamSelectionContextRepository),
        replacement_context: TeamSelectionContext,
    ) -> None:
        self._contexts = contexts
        self._replacement_context = replacement_context
        self._delegate = FakeDeterministicTeamProposalAdapter()

    async def propose(
        self,
        request: TeamProposalRequest,
    ) -> TeamProposalGenerationResult:
        """Generate normally before simulating concurrent context change."""
        result = await self._delegate.propose(request)
        self._contexts.set_context(self._replacement_context)

        return result


def build_service(
    contexts: (InMemoryTeamSelectionContextRepository),
    proposals: (InMemoryTeamProposalVersionRepository),
    *,
    proposal_port: TeamProposalPort | None = None,
) -> LocalTeamProposalApplicationService:
    """Create a deterministic application service."""
    return LocalTeamProposalApplicationService(
        unit_of_work_factory=lambda: InMemoryTeamProposalUnitOfWork(
            contexts,
            proposals,
        ),
        proposal_port=(proposal_port or FakeDeterministicTeamProposalAdapter()),
    )


def test_approved_brief_creates_first_proposal_version() -> None:
    """Generate and persist proposal version one."""
    version = complete_brief_version()
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    contexts.set_context(
        selection_context(
            version=version,
            gate=approved_gate(version),
        )
    )
    service = build_service(
        contexts,
        proposals,
    )

    result = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (TeamProposalApplicationStatus.CREATED)
    assert result.version is not None
    assert result.version.version_number == 1
    assert result.version.proposal.brief_version_id == version.id
    assert result.version.proposal.brief_content_hash == version.content_hash
    assert result.version.revision_kind is (TeamProposalRevisionKind.PROPOSER_GENERATED)


def test_identical_generation_reuses_current_version() -> None:
    """Avoid duplicate immutable rows for identical fake output."""
    version = complete_brief_version()
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    contexts.set_context(
        selection_context(
            version=version,
            gate=approved_gate(version),
        )
    )
    service = build_service(
        contexts,
        proposals,
    )

    first = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    repeated = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert first.status is (TeamProposalApplicationStatus.CREATED)
    assert repeated.status is (TeamProposalApplicationStatus.UNCHANGED)
    assert repeated.version == first.version
    assert len(proposals.versions[PROJECT_ID]) == 1


def test_gate_one_approval_is_required() -> None:
    """Block proposal generation before Project Brief approval."""
    version = complete_brief_version()
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    contexts.set_context(
        selection_context(
            version=version,
            gate=None,
        )
    )
    service = build_service(
        contexts,
        proposals,
    )

    result = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (TeamProposalApplicationStatus.BRIEF_NOT_APPROVED)
    assert proposals.versions == {}


def test_constraint_conflict_blocks_persistence() -> None:
    """Keep contradictory briefs out of the proposal history."""
    version = complete_brief_version(
        description=("Use Vue for the frontend, but the final product must have no frontend.")
    )
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    contexts.set_context(
        selection_context(
            version=version,
            gate=approved_gate(version),
        )
    )
    service = build_service(
        contexts,
        proposals,
    )

    result = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (TeamProposalApplicationStatus.BLOCKED_BY_CONSTRAINTS)
    assert result.version is None
    assert result.issues
    assert proposals.versions == {}


def test_context_change_during_generation_prevents_persistence() -> None:
    """Recheck the locked brief and gate after adapter execution."""
    first_version = complete_brief_version()
    second_version = complete_brief_version(
        version_number=2,
        description=("A revised Vue application with an updated backend."),
    )
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    initial_context = selection_context(
        version=first_version,
        gate=approved_gate(first_version),
    )
    replacement_context = selection_context(
        version=second_version,
        gate=approved_gate(second_version),
    )
    contexts.set_context(initial_context)
    adapter = ContextMutatingProposalAdapter(
        contexts=contexts,
        replacement_context=(replacement_context),
    )
    service = build_service(
        contexts,
        proposals,
        proposal_port=adapter,
    )

    result = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (TeamProposalApplicationStatus.CONTEXT_CHANGED)
    assert proposals.versions == {}


def test_other_owner_cannot_load_selection_context() -> None:
    """Return project-not-found without exposing another owner's project."""
    version = complete_brief_version()
    contexts = InMemoryTeamSelectionContextRepository()
    proposals = InMemoryTeamProposalVersionRepository()
    contexts.set_context(
        selection_context(
            version=version,
            gate=approved_gate(version),
        )
    )
    service = build_service(
        contexts,
        proposals,
    )

    result = asyncio.run(
        service.generate(
            project_id=PROJECT_ID,
            owner_user_id=(OTHER_OWNER_ID),
        )
    )

    assert result.status is (TeamProposalApplicationStatus.PROJECT_NOT_FOUND)
