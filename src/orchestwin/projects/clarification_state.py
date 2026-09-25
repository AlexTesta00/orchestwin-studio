"""Persistent domain state for clarification rounds and assumptions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.briefs import BriefField

MAX_ASSUMPTION_STATEMENT_LENGTH: Final = 2000
MAX_ASSUMPTION_REASON_LENGTH: Final = 2000


class BriefAssumptionSource(StrEnum):
    """Provenance categories for a proposed assumption."""

    OWNER_PROVIDED = "OWNER_PROVIDED"
    MODEL_PROPOSED = "MODEL_PROPOSED"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"


class BriefAssumptionStatus(StrEnum):
    """Lifecycle states of a Project Brief assumption."""

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class BriefAssumption:
    """One explicit assumption kept separate from provided facts."""

    id: UUID
    project_id: UUID
    brief_version_number: int
    field: BriefField
    statement: str
    source: BriefAssumptionSource
    status: BriefAssumptionStatus
    created_by_user_id: UUID
    created_at: datetime
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        """Protect provenance and decision-state invariants."""
        if self.brief_version_number < 1:
            raise ValueError("assumption brief version number must be positive")

        if not self.statement:
            raise ValueError("assumption statement is required")

        if self.statement != (" ".join(self.statement.split())):
            raise ValueError("assumption statement must be normalized")

        if len(self.statement) > MAX_ASSUMPTION_STATEMENT_LENGTH:
            raise ValueError("assumption statement exceeds maximum length")

        if self.created_at.tzinfo is None:
            raise ValueError("assumption created_at must be timezone-aware")

        if self.decided_at is not None and self.decided_at.tzinfo is None:
            raise ValueError("assumption decided_at must be timezone-aware")

        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("assumption cannot be decided before creation")

        if self.decision_reason is not None:
            normalized_reason = " ".join(self.decision_reason.split())

            if not normalized_reason or self.decision_reason != normalized_reason:
                raise ValueError("assumption decision reason must be normalized")

            if len(self.decision_reason) > MAX_ASSUMPTION_REASON_LENGTH:
                raise ValueError("assumption decision reason exceeds maximum length")

        if self.status is BriefAssumptionStatus.PROPOSED:
            if (
                self.decided_by_user_id is not None
                or self.decided_at is not None
                or self.decision_reason is not None
            ):
                raise ValueError("a proposed assumption must not contain decision data")

            return

        if self.decided_by_user_id is None or self.decided_at is None:
            raise ValueError("a decided assumption requires actor and timestamp")

        if self.status is BriefAssumptionStatus.REJECTED and self.decision_reason is None:
            raise ValueError("a rejected assumption requires a reason")


def normalize_assumption_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int,
) -> str:
    """Normalize and validate an assumption text value."""
    normalized = " ".join(value.split())

    if not normalized:
        raise ValueError(f"{field_name} is required")

    if len(normalized) > maximum_length:
        raise ValueError(f"{field_name} exceeds maximum length")

    return normalized


def create_brief_assumption(
    *,
    project_id: UUID,
    brief_version_number: int,
    field: BriefField,
    statement: str,
    source: BriefAssumptionSource,
    created_by_user_id: UUID,
    assumption_id: UUID | None = None,
    created_at: datetime | None = None,
) -> BriefAssumption:
    """Create a proposed assumption with explicit provenance."""
    return BriefAssumption(
        id=assumption_id or uuid4(),
        project_id=project_id,
        brief_version_number=(brief_version_number),
        field=field,
        statement=normalize_assumption_text(
            statement,
            field_name="assumption statement",
            maximum_length=(MAX_ASSUMPTION_STATEMENT_LENGTH),
        ),
        source=source,
        status=BriefAssumptionStatus.PROPOSED,
        created_by_user_id=created_by_user_id,
        created_at=created_at or datetime.now(UTC),
    )


def accept_brief_assumption(
    assumption: BriefAssumption,
    *,
    decided_by_user_id: UUID,
    decided_at: datetime | None = None,
    reason: str | None = None,
) -> BriefAssumption:
    """Accept one proposed assumption."""
    if assumption.status is not BriefAssumptionStatus.PROPOSED:
        raise ValueError("only a proposed assumption can be accepted")

    normalized_reason = (
        normalize_assumption_text(
            reason,
            field_name="assumption decision reason",
            maximum_length=(MAX_ASSUMPTION_REASON_LENGTH),
        )
        if reason is not None
        else None
    )

    return replace(
        assumption,
        status=BriefAssumptionStatus.ACCEPTED,
        decided_by_user_id=decided_by_user_id,
        decided_at=decided_at or datetime.now(UTC),
        decision_reason=normalized_reason,
    )


def reject_brief_assumption(
    assumption: BriefAssumption,
    *,
    decided_by_user_id: UUID,
    reason: str,
    decided_at: datetime | None = None,
) -> BriefAssumption:
    """Reject one proposed assumption with a required reason."""
    if assumption.status is not BriefAssumptionStatus.PROPOSED:
        raise ValueError("only a proposed assumption can be rejected")

    return replace(
        assumption,
        status=BriefAssumptionStatus.REJECTED,
        decided_by_user_id=decided_by_user_id,
        decided_at=decided_at or datetime.now(UTC),
        decision_reason=normalize_assumption_text(
            reason,
            field_name="assumption rejection reason",
            maximum_length=(MAX_ASSUMPTION_REASON_LENGTH),
        ),
    )
