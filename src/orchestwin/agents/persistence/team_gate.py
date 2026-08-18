"""SQLAlchemy persistence and unit of work for editable agent teams."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamSelectionContextRepository,
    latest_owned_team_proposal_statement,
    owned_team_selection_project_statement,
    team_proposal_record_to_domain,
)
from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
)
from orchestwin.agents.team_gate import (
    OwnerEditedProposalPersistenceResult,
    OwnerEditedProposalPersistenceStatus,
)
from orchestwin.models.team_proposals import (
    AgentTeamProposal,
)
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def latest_owned_team_proposal_for_update_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    """Build the locked owner-scoped current-proposal query."""
    return latest_owned_team_proposal_statement(
        project_id=project_id,
        owner_user_id=owner_user_id,
    ).with_for_update()


class SqlAlchemyEditableTeamProposalRepository:
    """Persist owner-edited immutable proposal versions."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._session = session
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Lock and return the latest owner-scoped proposal."""
        record = await self._session.scalar(
            latest_owned_team_proposal_for_update_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if record is None:
            return None

        return team_proposal_record_to_domain(record)

    async def create_owner_edited_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        based_on: TeamProposalVersion,
        proposal: AgentTeamProposal,
    ) -> OwnerEditedProposalPersistenceResult:
        """Create or reuse an immutable owner-edited proposal."""
        project = await self._session.scalar(
            owned_team_selection_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                for_update=True,
            )
        )

        if project is None:
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.PROJECT_NOT_FOUND)
            )

        latest_record = await self._session.scalar(
            latest_owned_team_proposal_for_update_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if latest_record is None:
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.BASE_VERSION_CHANGED)
            )

        latest = team_proposal_record_to_domain(latest_record)

        if (
            latest.id != based_on.id
            or latest.version_number != based_on.version_number
            or latest.content_hash != based_on.content_hash
        ):
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.BASE_VERSION_CHANGED)
            )

        self._validate_edit_basis(
            project_mode=(project.project_mode),
            current_brief_version=(project.current_brief_version),
            based_on=based_on,
            proposal=proposal,
        )

        if proposal.content_hash == latest.content_hash:
            return OwnerEditedProposalPersistenceResult(
                status=(OwnerEditedProposalPersistenceStatus.UNCHANGED),
                version=latest,
            )

        created_at = self._clock()

        if created_at.tzinfo is None:
            raise ValueError("owner-edited proposal clock must be timezone-aware")

        version_number = latest.version_number + 1
        record = TeamProposalVersionRecord(
            id=self._uuid_factory(),
            project_id=project.id,
            version_number=version_number,
            schema_version=(proposal.schema_version),
            revision_kind=(TeamProposalRevisionKind.OWNER_EDITED.value),
            based_on_version_number=(latest.version_number),
            brief_version_id=(proposal.brief_version_id),
            brief_version_number=(proposal.brief_version_number),
            brief_content_hash=(proposal.brief_content_hash),
            catalog_version=(proposal.catalog_version),
            catalog_content_hash=(proposal.catalog_content_hash),
            constraints_content_hash=(proposal.constraints.content_hash),
            provider_kind=(proposal.provider_kind.value),
            provider_id=(proposal.provider_id),
            provider_version=(proposal.provider_version),
            content=proposal.to_snapshot(),
            content_hash=(proposal.content_hash),
            created_by_user_id=(owner_user_id),
            created_at=created_at,
        )

        self._session.add(record)
        await self._session.flush()

        return OwnerEditedProposalPersistenceResult(
            status=(OwnerEditedProposalPersistenceStatus.CREATED),
            version=(team_proposal_record_to_domain(record)),
        )

    @staticmethod
    def _validate_edit_basis(
        *,
        project_mode,
        current_brief_version: int,
        based_on: TeamProposalVersion,
        proposal: AgentTeamProposal,
    ) -> None:
        """Ensure an owner edit changes only team membership."""
        previous = based_on.proposal

        same_context = (
            proposal.project_id == previous.project_id
            and proposal.project_mode is project_mode
            and proposal.project_mode is previous.project_mode
            and proposal.brief_version_id == previous.brief_version_id
            and proposal.brief_version_number == current_brief_version
            and proposal.brief_version_number == previous.brief_version_number
            and proposal.brief_content_hash == previous.brief_content_hash
            and proposal.catalog_version == previous.catalog_version
            and proposal.catalog_content_hash == previous.catalog_content_hash
            and proposal.constraints == previous.constraints
            and proposal.provider_kind is previous.provider_kind
            and proposal.provider_id == previous.provider_id
            and proposal.provider_version == previous.provider_version
            and proposal.schema_version == previous.schema_version
        )

        if not same_context:
            raise ValueError("an owner edit may change only the selected team members")


class SqlAlchemyAgentTeamUnitOfWork:
    """One SQLAlchemy transaction for team editing and Gate 2."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._contexts: SqlAlchemyTeamSelectionContextRepository | None = None
        self._proposals: SqlAlchemyEditableTeamProposalRepository | None = None
        self._gates: SqlAlchemyHumanGateRepository | None = None

    @property
    def contexts(
        self,
    ) -> SqlAlchemyTeamSelectionContextRepository:
        """Return the context repository after entry."""
        if self._contexts is None:
            raise RuntimeError("Agent Team unit of work is not open")

        return self._contexts

    @property
    def proposals(
        self,
    ) -> SqlAlchemyEditableTeamProposalRepository:
        """Return the editable proposal repository after entry."""
        if self._proposals is None:
            raise RuntimeError("Agent Team unit of work is not open")

        return self._proposals

    @property
    def gates(
        self,
    ) -> SqlAlchemyHumanGateRepository:
        """Return the Gate 2 repository after entry."""
        if self._gates is None:
            raise RuntimeError("Agent Team unit of work is not open")

        return self._gates

    async def __aenter__(
        self,
    ) -> SqlAlchemyAgentTeamUnitOfWork:
        """Open a SQLAlchemy session and transaction."""
        self._session = self._session_factory()
        await self._session.begin()

        self._contexts = SqlAlchemyTeamSelectionContextRepository(self._session)
        self._proposals = SqlAlchemyEditableTeamProposalRepository(self._session)
        self._gates = SqlAlchemyHumanGateRepository(self._session)

        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit successful work or roll back failures."""
        if self._session is None:
            return

        try:
            if exception_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None
            self._contexts = None
            self._proposals = None
            self._gates = None


class SqlAlchemyAgentTeamUnitOfWorkFactory:
    """Create a fresh Agent Team unit of work per use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
    ) -> SqlAlchemyAgentTeamUnitOfWork:
        """Return one unopened Agent Team unit of work."""
        return SqlAlchemyAgentTeamUnitOfWork(self._session_factory)
