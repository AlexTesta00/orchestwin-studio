"""SQLAlchemy persistence for team-selection context and proposals."""

from __future__ import annotations

from collections.abc import (
    Mapping,
)
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Select,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from orchestwin.agents.catalog import (
    AgentIdentifier,
)
from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamProposalVersionCreationResult,
    TeamProposalVersionCreationStatus,
    TeamSelectionContext,
)
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    RuleEvidence,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionReason,
    TeamSelectionReasonCode,
)
from orchestwin.models.team_proposals import (
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
)
from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.persistence.briefs import (
    brief_record_to_domain,
)
from orchestwin.projects.persistence.models import (
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.workflow.gates import (
    HumanGateType,
)
from orchestwin.workflow.persistence.models import (
    HumanGateRecord,
)
from orchestwin.workflow.persistence.repositories import (
    gate_record_to_domain,
)

Clock = type[lambda: datetime]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _required_mapping(
    value: object,
    *,
    label: str,
) -> Mapping[str, object]:
    """Return one required JSON object."""
    if not isinstance(
        value,
        Mapping,
    ):
        raise ValueError(f"{label} must be an object")

    return value


def _required_list(
    value: object,
    *,
    label: str,
) -> list[object]:
    """Return one required JSON array."""
    if not isinstance(
        value,
        list,
    ):
        raise ValueError(f"{label} must be an array")

    return value


def _required_string(
    value: object,
    *,
    label: str,
) -> str:
    """Return one required JSON string."""
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
    """Return an optional JSON string."""
    if value is None:
        return None

    return _required_string(
        value,
        label=label,
    )


def _required_integer(
    value: object,
    *,
    label: str,
) -> int:
    """Return one required non-boolean JSON integer."""
    if isinstance(
        value,
        bool,
    ) or not isinstance(
        value,
        int,
    ):
        raise ValueError(f"{label} must be an integer")

    return value


def _required_boolean(
    value: object,
    *,
    label: str,
) -> bool:
    """Return one required JSON boolean."""
    if not isinstance(
        value,
        bool,
    ):
        raise ValueError(f"{label} must be a boolean")

    return value


def _required_uuid(
    value: object,
    *,
    label: str,
) -> UUID:
    """Return one required UUID string."""
    return UUID(
        _required_string(
            value,
            label=label,
        )
    )


def _evidence_from_snapshot(
    value: object,
) -> RuleEvidence:
    """Reconstruct deterministic rule evidence."""
    snapshot = _required_mapping(
        value,
        label="constraint evidence",
    )
    raw_fields = _required_list(
        snapshot.get("fields"),
        label="constraint evidence fields",
    )
    raw_terms = _required_list(
        snapshot.get("terms"),
        label="constraint evidence terms",
    )

    return RuleEvidence(
        fields=tuple(
            BriefField(
                _required_string(
                    field,
                    label=("constraint evidence field"),
                )
            )
            for field in raw_fields
        ),
        terms=tuple(
            _required_string(
                term,
                label=("constraint evidence term"),
            )
            for term in raw_terms
        ),
    )


def _reason_from_snapshot(
    value: object,
) -> TeamSelectionReason:
    """Reconstruct one deterministic selection reason."""
    snapshot = _required_mapping(
        value,
        label="constraint reason",
    )

    return TeamSelectionReason(
        code=TeamSelectionReasonCode(
            _required_string(
                snapshot.get("code"),
                label="constraint reason code",
            )
        ),
        evidence=_evidence_from_snapshot(snapshot.get("evidence")),
    )


def constraints_from_snapshot(
    value: object,
) -> DeterministicTeamConstraints:
    """Reconstruct persisted deterministic team constraints."""
    snapshot = _required_mapping(
        value,
        label="team constraints",
    )
    raw_issues = _required_list(
        snapshot.get("issues"),
        label="team constraint issues",
    )

    if raw_issues:
        raise ValueError("a persisted proposal must not contain constraint conflicts")

    raw_constraints = _required_list(
        snapshot.get("role_constraints"),
        label="team role constraints",
    )
    constraints: list[TeamRoleConstraint] = []

    for raw_constraint in raw_constraints:
        constraint_snapshot = _required_mapping(
            raw_constraint,
            label="team role constraint",
        )
        raw_reasons = _required_list(
            constraint_snapshot.get("reasons"),
            label=("team role constraint reasons"),
        )
        constraint = TeamRoleConstraint(
            agent_id=AgentIdentifier(
                _required_string(
                    constraint_snapshot.get("agent_id"),
                    label=("team role constraint agent ID"),
                )
            ),
            kind=TeamRoleConstraintKind(
                _required_string(
                    constraint_snapshot.get("kind"),
                    label=("team role constraint kind"),
                )
            ),
            reasons=tuple(_reason_from_snapshot(reason) for reason in raw_reasons),
        )

        expected_owner_editable = _required_boolean(
            constraint_snapshot.get("owner_editable"),
            label=("team role constraint owner-editable flag"),
        )

        if constraint.owner_editable is not expected_owner_editable:
            raise ValueError("persisted owner-editable flag does not match the role constraint")

        constraints.append(constraint)

    result = DeterministicTeamConstraints(
        catalog_version=(
            _required_integer(
                snapshot.get("catalog_version"),
                label=("constraint catalog version"),
            )
        ),
        catalog_content_hash=(
            _required_string(
                snapshot.get("catalog_content_hash"),
                label=("constraint catalog hash"),
            )
        ),
        project_mode=ProjectMode(
            _required_string(
                snapshot.get("project_mode"),
                label=("constraint project mode"),
            )
        ),
        role_constraints=tuple(constraints),
    )

    if result.to_snapshot() != dict(snapshot):
        raise ValueError("persisted team constraints do not match their canonical snapshot")

    return result


def _justification_from_snapshot(
    value: object,
) -> TeamProposalJustification:
    """Reconstruct one persisted member justification."""
    snapshot = _required_mapping(
        value,
        label="team member justification",
    )
    raw_fields = _required_list(
        snapshot.get("evidence_fields"),
        label=("team member justification fields"),
    )
    raw_terms = _required_list(
        snapshot.get("evidence_terms"),
        label=("team member justification terms"),
    )

    return TeamProposalJustification(
        kind=TeamProposalJustificationKind(
            _required_string(
                snapshot.get("kind"),
                label=("team member justification kind"),
            )
        ),
        code=_required_string(
            snapshot.get("code"),
            label=("team member justification code"),
        ),
        evidence_fields=tuple(
            BriefField(
                _required_string(
                    field,
                    label=("team member evidence field"),
                )
            )
            for field in raw_fields
        ),
        evidence_terms=tuple(
            _required_string(
                term,
                label=("team member evidence term"),
            )
            for term in raw_terms
        ),
        statement=_optional_string(
            snapshot.get("statement"),
            label=("team member justification statement"),
        ),
    )


def _member_from_snapshot(
    value: object,
) -> ProposedTeamMember:
    """Reconstruct one persisted proposed team member."""
    snapshot = _required_mapping(
        value,
        label="team proposal member",
    )
    raw_justifications = _required_list(
        snapshot.get("justifications"),
        label=("team proposal member justifications"),
    )

    return ProposedTeamMember(
        agent_id=AgentIdentifier(
            _required_string(
                snapshot.get("agent_id"),
                label=("team proposal member agent ID"),
            )
        ),
        source=TeamProposalMemberSource(
            _required_string(
                snapshot.get("source"),
                label=("team proposal member source"),
            )
        ),
        justifications=tuple(
            _justification_from_snapshot(justification) for justification in raw_justifications
        ),
    )


def proposal_from_snapshot(
    value: object,
) -> AgentTeamProposal:
    """Reconstruct and validate a persisted proposal snapshot."""
    snapshot = _required_mapping(
        value,
        label="team proposal",
    )
    provider = _required_mapping(
        snapshot.get("provider"),
        label="team proposal provider",
    )
    brief = _required_mapping(
        snapshot.get("brief_version"),
        label="team proposal brief version",
    )
    catalog = _required_mapping(
        snapshot.get("catalog"),
        label="team proposal catalog",
    )
    constraints = constraints_from_snapshot(snapshot.get("constraints"))
    constraints_hash = _required_string(
        snapshot.get("constraints_content_hash"),
        label=("team proposal constraints hash"),
    )

    if constraints.content_hash != constraints_hash:
        raise ValueError("persisted constraint hash does not match its snapshot")

    raw_members = _required_list(
        snapshot.get("members"),
        label="team proposal members",
    )
    proposal = AgentTeamProposal(
        schema_version=(
            _required_integer(
                snapshot.get("schema_version"),
                label=("team proposal schema version"),
            )
        ),
        provider_kind=(
            TeamProposalProviderKind(
                _required_string(
                    provider.get("kind"),
                    label=("team proposal provider kind"),
                )
            )
        ),
        provider_id=_required_string(
            provider.get("provider_id"),
            label=("team proposal provider ID"),
        ),
        provider_version=(
            _required_integer(
                provider.get("provider_version"),
                label=("team proposal provider version"),
            )
        ),
        project_id=_required_uuid(
            snapshot.get("project_id"),
            label="team proposal project ID",
        ),
        project_mode=ProjectMode(
            _required_string(
                snapshot.get("project_mode"),
                label=("team proposal project mode"),
            )
        ),
        brief_version_id=_required_uuid(
            brief.get("id"),
            label=("team proposal brief version ID"),
        ),
        brief_version_number=(
            _required_integer(
                brief.get("version_number"),
                label=("team proposal brief version number"),
            )
        ),
        brief_content_hash=(
            _required_string(
                brief.get("content_hash"),
                label=("team proposal brief hash"),
            )
        ),
        catalog_version=(
            _required_integer(
                catalog.get("version"),
                label=("team proposal catalog version"),
            )
        ),
        catalog_content_hash=(
            _required_string(
                catalog.get("content_hash"),
                label=("team proposal catalog hash"),
            )
        ),
        constraints=constraints,
        members=tuple(_member_from_snapshot(member) for member in raw_members),
    )

    if proposal.to_snapshot() != dict(snapshot):
        raise ValueError("persisted team proposal does not match its canonical snapshot")

    return proposal


def team_proposal_record_to_domain(
    record: TeamProposalVersionRecord,
) -> TeamProposalVersion:
    """Translate a persisted proposal record into domain state."""
    proposal = proposal_from_snapshot(record.content)

    record_matches_proposal = (
        record.project_id == proposal.project_id
        and record.schema_version == proposal.schema_version
        and record.brief_version_id == proposal.brief_version_id
        and record.brief_version_number == proposal.brief_version_number
        and record.brief_content_hash == proposal.brief_content_hash
        and record.catalog_version == proposal.catalog_version
        and record.catalog_content_hash == proposal.catalog_content_hash
        and record.constraints_content_hash == proposal.constraints.content_hash
        and record.provider_kind == proposal.provider_kind.value
        and record.provider_id == proposal.provider_id
        and record.provider_version == proposal.provider_version
        and record.content_hash == proposal.content_hash
    )

    if not record_matches_proposal:
        raise ValueError("team-proposal record metadata does not match its snapshot")

    return TeamProposalVersion(
        id=record.id,
        project_id=record.project_id,
        version_number=(record.version_number),
        proposal=proposal,
        revision_kind=(TeamProposalRevisionKind(record.revision_kind)),
        based_on_version_number=(record.based_on_version_number),
        created_by_user_id=(record.created_by_user_id),
        created_at=record.created_at,
    )


def owned_team_proposals_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[TeamProposalVersionRecord,]]:
    """Build the canonical owner-scoped proposal query."""
    return (
        select(TeamProposalVersionRecord)
        .join(
            ProjectRecord,
            ProjectRecord.id == TeamProposalVersionRecord.project_id,
        )
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
    )


def latest_owned_team_proposal_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[TeamProposalVersionRecord,]]:
    """Build the latest owner-scoped proposal query."""
    return (
        owned_team_proposals_statement(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        .order_by(TeamProposalVersionRecord.version_number.desc())
        .limit(1)
    )


def owned_team_proposal_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    version_number: int,
) -> Select[tuple[TeamProposalVersionRecord,]]:
    """Build an owner-scoped query for one proposal version."""
    return owned_team_proposals_statement(
        project_id=project_id,
        owner_user_id=owner_user_id,
    ).where(TeamProposalVersionRecord.version_number == version_number)


def owned_team_selection_project_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    for_update: bool = False,
) -> Select[tuple[ProjectRecord,]]:
    """Build the owner-scoped project query used by team selection."""
    statement = select(ProjectRecord).where(
        ProjectRecord.id == project_id,
        ProjectRecord.owner_user_id == owner_user_id,
        ProjectRecord.archived_at.is_(None),
    )

    if for_update:
        statement = statement.with_for_update()

    return statement


class SqlAlchemyTeamSelectionContextRepository:
    """Load Project Brief and Gate 1 through project ownership."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Return current selection context without a row lock."""
        return await self._get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
            for_update=False,
        )

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamSelectionContext | None:
        """Lock the project and return current selection context."""
        return await self._get_current_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
            for_update=True,
        )

    async def _get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        for_update: bool,
    ) -> TeamSelectionContext | None:
        """Load project, current brief, and latest Gate 1."""
        project = await self._session.scalar(
            owned_team_selection_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                for_update=for_update,
            )
        )

        if project is None:
            return None

        if project.current_brief_version < 1:
            return TeamSelectionContext(
                project_id=project.id,
                owner_user_id=(project.owner_user_id),
                project_mode=(project.project_mode),
                brief_version=None,
                brief_gate=None,
            )

        brief_statement = select(ProjectBriefVersionRecord).where(
            ProjectBriefVersionRecord.project_id == project.id,
            ProjectBriefVersionRecord.version_number == project.current_brief_version,
        )

        if for_update:
            brief_statement = brief_statement.with_for_update()

        brief_record = await self._session.scalar(brief_statement)

        if brief_record is None:
            raise RuntimeError("project current brief version is missing")

        gate_statement = (
            select(HumanGateRecord)
            .where(
                HumanGateRecord.project_id == project.id,
                HumanGateRecord.owner_user_id == project.owner_user_id,
                HumanGateRecord.gate_type == HumanGateType.PROJECT_BRIEF.value,
            )
            .order_by(
                HumanGateRecord.iteration.desc(),
                HumanGateRecord.created_at.desc(),
                HumanGateRecord.id.desc(),
            )
            .limit(1)
        )

        if for_update:
            gate_statement = gate_statement.with_for_update()

        gate_record = await self._session.scalar(gate_statement)

        return TeamSelectionContext(
            project_id=project.id,
            owner_user_id=(project.owner_user_id),
            project_mode=(project.project_mode),
            brief_version=(brief_record_to_domain(brief_record)),
            brief_gate=(gate_record_to_domain(gate_record) if gate_record is not None else None),
        )


class SqlAlchemyTeamProposalVersionRepository:
    """Owner-scoped immutable team-proposal repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock=utc_now,
        uuid_factory=uuid4,
    ) -> None:
        self._session = session
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def create_generated_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        proposal: AgentTeamProposal,
    ) -> TeamProposalVersionCreationResult:
        """Create or reuse a generated proposal version."""
        project = await self._session.scalar(
            owned_team_selection_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                for_update=True,
            )
        )

        if project is None:
            return TeamProposalVersionCreationResult(
                status=(TeamProposalVersionCreationStatus.PROJECT_NOT_FOUND)
            )

        if proposal.project_id != project.id:
            raise ValueError("team proposal must belong to the locked project")

        if proposal.project_mode is not project.project_mode:
            raise ValueError("team proposal mode must match the locked project")

        if proposal.brief_version_number != project.current_brief_version:
            raise ValueError("team proposal must reference the current Project Brief")

        latest_record = await self._session.scalar(
            latest_owned_team_proposal_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if latest_record is not None and latest_record.content_hash == proposal.content_hash:
            return TeamProposalVersionCreationResult(
                status=(TeamProposalVersionCreationStatus.UNCHANGED),
                version=(team_proposal_record_to_domain(latest_record)),
            )

        created_at = self._clock()

        if created_at.tzinfo is None:
            raise ValueError("team-proposal persistence clock must be timezone-aware")

        version_number = 1 if latest_record is None else (latest_record.version_number + 1)
        record = TeamProposalVersionRecord(
            id=self._uuid_factory(),
            project_id=project.id,
            version_number=version_number,
            schema_version=(proposal.schema_version),
            revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED.value),
            based_on_version_number=None,
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

        return TeamProposalVersionCreationResult(
            status=(TeamProposalVersionCreationStatus.CREATED),
            version=(team_proposal_record_to_domain(record)),
        )

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the latest owner-scoped proposal version."""
        record = await self._session.scalar(
            latest_owned_team_proposal_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if record is None:
            return None

        return team_proposal_record_to_domain(record)

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> TeamProposalVersion | None:
        """Return one owner-scoped proposal version."""
        record = await self._session.scalar(
            owned_team_proposal_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                version_number=version_number,
            )
        )

        if record is None:
            return None

        return team_proposal_record_to_domain(record)

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return proposal history in ascending version order."""
        result = await self._session.scalars(
            owned_team_proposals_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).order_by(TeamProposalVersionRecord.version_number)
        )

        return tuple(team_proposal_record_to_domain(record) for record in result.all())
