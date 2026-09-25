"""Tests for clarification-round and assumption domain state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.clarification_state import (
    BriefAssumptionSource,
    BriefAssumptionStatus,
    accept_brief_assumption,
    create_brief_assumption,
    reject_brief_assumption,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
ASSUMPTION_ID = UUID("00000000-0000-4000-8000-000000000040")
CREATED_AT = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


def build_assumption():
    """Create one deterministic proposed assumption."""
    return create_brief_assumption(
        assumption_id=ASSUMPTION_ID,
        project_id=PROJECT_ID,
        brief_version_number=1,
        field=BriefField.BUDGET,
        statement=(" The initial budget is approximately EUR 5,000. "),
        source=(BriefAssumptionSource.OWNER_PROVIDED),
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_assumption_is_normalized_and_proposed() -> None:
    """Keep a new assumption separate from approved facts."""
    assumption = build_assumption()

    assert assumption.statement == ("The initial budget is approximately EUR 5,000.")
    assert assumption.status is (BriefAssumptionStatus.PROPOSED)
    assert assumption.decided_at is None


def test_assumption_can_be_accepted_once() -> None:
    """Create an immutable accepted decision."""
    proposed = build_assumption()

    accepted = accept_brief_assumption(
        proposed,
        decided_by_user_id=OWNER_ID,
        decided_at=(CREATED_AT + timedelta(minutes=1)),
        reason=" Confirmed by the owner. ",
    )

    assert accepted.status is (BriefAssumptionStatus.ACCEPTED)
    assert accepted.decision_reason == ("Confirmed by the owner.")

    with pytest.raises(
        ValueError,
        match=("only a proposed assumption can be accepted"),
    ):
        accept_brief_assumption(
            accepted,
            decided_by_user_id=OWNER_ID,
        )


def test_assumption_rejection_requires_reason() -> None:
    """Reject assumptions only through an explicit rationale."""
    proposed = build_assumption()

    with pytest.raises(
        ValueError,
        match=("assumption rejection reason is required"),
    ):
        reject_brief_assumption(
            proposed,
            decided_by_user_id=OWNER_ID,
            reason="   ",
        )

    rejected = reject_brief_assumption(
        proposed,
        decided_by_user_id=OWNER_ID,
        reason="The owner supplied a different budget.",
        decided_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert rejected.status is (BriefAssumptionStatus.REJECTED)
    assert rejected.decision_reason == ("The owner supplied a different budget.")
