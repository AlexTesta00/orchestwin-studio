"""SQLAlchemy persistence for clarification rounds and assumptions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.briefs import BriefField
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    accept_brief_assumption,
    reject_brief_assumption,
)
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
    ProjectRecord,
)


def assumption_record_to_domain(
    record: BriefAssumptionRecord,
) -> BriefAssumption:
    """Translate an assumption record into immutable domain state."""
    return BriefAssumption(
        id=record.id,
        project_id=record.project_id,
        brief_version_number=(record.brief_version_number),
        field=BriefField(record.field_name),
        statement=record.statement,
        source=BriefAssumptionSource(record.source),
        status=BriefAssumptionStatus(record.status),
        created_by_user_id=(record.created_by_user_id),
        created_at=record.created_at,
        decided_by_user_id=(record.decided_by_user_id),
        decided_at=record.decided_at,
        decision_reason=record.decision_reason,
    )


def owned_assumptions_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[BriefAssumptionRecord]]:
    """Build the canonical owner-scoped assumption query."""
    return (
        select(BriefAssumptionRecord)
        .join(
            ProjectRecord,
            ProjectRecord.id == BriefAssumptionRecord.project_id,
        )
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
    )


def owned_assumption_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    assumption_id: UUID,
) -> Select[tuple[BriefAssumptionRecord]]:
    """Build an owner-scoped query for one assumption."""
    return owned_assumptions_statement(
        project_id=project_id,
        owner_user_id=owner_user_id,
    ).where(BriefAssumptionRecord.id == assumption_id)


class SqlAlchemyBriefAssumptionRepository:
    """Owner-scoped SQLAlchemy assumption repository."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def add(
        self,
        assumption: BriefAssumption,
    ) -> BriefAssumption:
        """Add a proposed assumption to the transaction."""
        record = BriefAssumptionRecord(
            id=assumption.id,
            project_id=assumption.project_id,
            brief_version_number=(assumption.brief_version_number),
            field_name=assumption.field.value,
            statement=assumption.statement,
            source=assumption.source.value,
            status=assumption.status.value,
            created_by_user_id=(assumption.created_by_user_id),
            created_at=assumption.created_at,
            decided_by_user_id=(assumption.decided_by_user_id),
            decided_at=assumption.decided_at,
            decision_reason=(assumption.decision_reason),
        )

        self._session.add(record)
        await self._session.flush()

        return assumption_record_to_domain(record)

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
    ) -> BriefAssumption | None:
        """Return one assumption for its project owner."""
        record = await self._session.scalar(
            owned_assumption_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                assumption_id=assumption_id,
            )
        )

        if record is None:
            return None

        return assumption_record_to_domain(record)

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[BriefAssumption, ...]:
        """Return assumptions in deterministic creation order."""
        result = await self._session.scalars(
            owned_assumptions_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).order_by(
                BriefAssumptionRecord.created_at,
                BriefAssumptionRecord.id,
            )
        )

        return tuple(assumption_record_to_domain(record) for record in result.all())

    async def accept_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str | None = None,
    ) -> BriefAssumption | None:
        """Accept a proposed assumption under a row lock."""
        record = await self._session.scalar(
            owned_assumption_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                assumption_id=assumption_id,
            ).with_for_update()
        )

        if record is None:
            return None

        accepted = accept_brief_assumption(
            assumption_record_to_domain(record),
            decided_by_user_id=owner_user_id,
            decided_at=decided_at,
            reason=reason,
        )

        self._apply_decision(
            record,
            accepted,
        )
        await self._session.flush()

        return assumption_record_to_domain(record)

    async def reject_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str,
    ) -> BriefAssumption | None:
        """Reject a proposed assumption under a row lock."""
        record = await self._session.scalar(
            owned_assumption_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                assumption_id=assumption_id,
            ).with_for_update()
        )

        if record is None:
            return None

        rejected = reject_brief_assumption(
            assumption_record_to_domain(record),
            decided_by_user_id=owner_user_id,
            decided_at=decided_at,
            reason=reason,
        )

        self._apply_decision(
            record,
            rejected,
        )
        await self._session.flush()

        return assumption_record_to_domain(record)

    @staticmethod
    def _apply_decision(
        record: BriefAssumptionRecord,
        assumption: BriefAssumption,
    ) -> None:
        """Copy a validated domain decision into an ORM record."""
        record.status = assumption.status.value
        record.decided_by_user_id = assumption.decided_by_user_id
        record.decided_at = assumption.decided_at
        record.decision_reason = assumption.decision_reason
