"""SQLAlchemy persistence for clarification rounds and assumptions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.briefs import BriefField
from orchestwin.projects.clarification import (
    ClarificationAnswerType,
    ClarificationQuestionSpec,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
    ClarificationRound,
    ClarificationRoundStatus,
    accept_brief_assumption,
    complete_clarification_round,
    reject_brief_assumption,
)
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
    ClarificationRoundRecord,
    ProjectRecord,
)


def question_spec_to_snapshot(
    question: ClarificationQuestionSpec,
) -> dict[str, object]:
    """Serialize a clarification question for JSONB persistence."""
    return {
        "question_id": question.question_id,
        "catalog_version": question.catalog_version,
        "field": question.field.value,
        "answer_type": question.answer_type.value,
        "priority": question.priority,
        "prompt_key": question.prompt_key,
        "hint_key": question.hint_key,
        "unknown_allowed": question.unknown_allowed,
    }


def required_string(
    snapshot: Mapping[str, object],
    key: str,
) -> str:
    """Read one required string from a question snapshot."""
    value = snapshot.get(key)

    if not isinstance(value, str):
        raise ValueError(f"clarification question {key} must be a string")

    return value


def required_integer(
    snapshot: Mapping[str, object],
    key: str,
) -> int:
    """Read one required non-boolean integer."""
    value = snapshot.get(key)

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"clarification question {key} must be an integer")

    return value


def required_boolean(
    snapshot: Mapping[str, object],
    key: str,
) -> bool:
    """Read one required boolean."""
    value = snapshot.get(key)

    if not isinstance(value, bool):
        raise ValueError(f"clarification question {key} must be a boolean")

    return value


def question_spec_from_snapshot(
    snapshot: Mapping[str, object],
) -> ClarificationQuestionSpec:
    """Reconstruct and validate a persisted question snapshot."""
    return ClarificationQuestionSpec(
        question_id=required_string(
            snapshot,
            "question_id",
        ),
        catalog_version=required_integer(
            snapshot,
            "catalog_version",
        ),
        field=BriefField(
            required_string(
                snapshot,
                "field",
            )
        ),
        answer_type=ClarificationAnswerType(
            required_string(
                snapshot,
                "answer_type",
            )
        ),
        priority=required_integer(
            snapshot,
            "priority",
        ),
        prompt_key=required_string(
            snapshot,
            "prompt_key",
        ),
        hint_key=required_string(
            snapshot,
            "hint_key",
        ),
        unknown_allowed=required_boolean(
            snapshot,
            "unknown_allowed",
        ),
    )


def round_record_to_domain(
    record: ClarificationRoundRecord,
) -> ClarificationRound:
    """Translate a clarification-round record into domain state."""
    return ClarificationRound(
        id=record.id,
        project_id=record.project_id,
        source_brief_version_number=(record.source_brief_version_number),
        round_number=record.round_number,
        catalog_version=record.catalog_version,
        questions=tuple(question_spec_from_snapshot(snapshot) for snapshot in record.questions),
        status=ClarificationRoundStatus(record.status),
        created_by_user_id=(record.created_by_user_id),
        created_at=record.created_at,
        answered_at=record.answered_at,
        resulting_brief_version_number=(record.resulting_brief_version_number),
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


def owned_rounds_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[ClarificationRoundRecord]]:
    """Build the canonical owner-scoped round-history query."""
    return (
        select(ClarificationRoundRecord)
        .join(
            ProjectRecord,
            ProjectRecord.id == ClarificationRoundRecord.project_id,
        )
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
    )


def owned_round_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    round_id: UUID,
) -> Select[tuple[ClarificationRoundRecord]]:
    """Build an owner-scoped query for one clarification round."""
    return owned_rounds_statement(
        project_id=project_id,
        owner_user_id=owner_user_id,
    ).where(ClarificationRoundRecord.id == round_id)


def current_open_round_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[ClarificationRoundRecord]]:
    """Build the owner-scoped query for the current open round."""
    return (
        owned_rounds_statement(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
        .where(ClarificationRoundRecord.status == ClarificationRoundStatus.OPEN.value)
        .order_by(ClarificationRoundRecord.round_number.desc())
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


class SqlAlchemyClarificationRoundRepository:
    """Owner-scoped SQLAlchemy clarification-round repository."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def add(
        self,
        round_state: ClarificationRound,
    ) -> ClarificationRound:
        """Add a clarification round to the current transaction."""
        record = ClarificationRoundRecord(
            id=round_state.id,
            project_id=round_state.project_id,
            source_brief_version_number=(round_state.source_brief_version_number),
            round_number=round_state.round_number,
            catalog_version=(round_state.catalog_version),
            questions=[question_spec_to_snapshot(question) for question in round_state.questions],
            status=round_state.status.value,
            created_by_user_id=(round_state.created_by_user_id),
            created_at=round_state.created_at,
            answered_at=round_state.answered_at,
            resulting_brief_version_number=(round_state.resulting_brief_version_number),
        )

        self._session.add(record)
        await self._session.flush()

        return round_record_to_domain(record)

    async def count_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> int:
        """Count clarification rounds for an active owned project."""
        count = await self._session.scalar(
            select(func.count(ClarificationRoundRecord.id))
            .join(
                ProjectRecord,
                ProjectRecord.id == ClarificationRoundRecord.project_id,
            )
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
        )

        return int(count or 0)

    async def get_current_open_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRound | None:
        """Return the current open round."""
        record = await self._session.scalar(
            current_open_round_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if record is None:
            return None

        return round_record_to_domain(record)

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
    ) -> ClarificationRound | None:
        """Return one clarification round for its owner."""
        record = await self._session.scalar(
            owned_round_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                round_id=round_id,
            )
        )

        if record is None:
            return None

        return round_record_to_domain(record)

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ClarificationRound, ...]:
        """Return clarification-round history."""
        result = await self._session.scalars(
            owned_rounds_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).order_by(ClarificationRoundRecord.round_number)
        )

        return tuple(round_record_to_domain(record) for record in result.all())

    async def complete_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        resulting_brief_version_number: int,
        answered_at: datetime,
    ) -> ClarificationRound | None:
        """Complete an open round under an owner-scoped row lock."""
        record = await self._session.scalar(
            owned_round_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                round_id=round_id,
            ).with_for_update()
        )

        if record is None:
            return None

        completed = complete_clarification_round(
            round_record_to_domain(record),
            resulting_brief_version_number=(resulting_brief_version_number),
            answered_at=answered_at,
        )

        record.status = completed.status.value
        record.answered_at = completed.answered_at
        record.resulting_brief_version_number = completed.resulting_brief_version_number

        await self._session.flush()

        return round_record_to_domain(record)


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
