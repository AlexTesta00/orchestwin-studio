"""Tests for clarification-round and assumption domain state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.clarification import (
    CLARIFICATION_CATALOG_VERSION,
    clarification_question_for,
)
from orchestwin.projects.clarification_state import (
    BriefAssumptionSource,
    BriefAssumptionStatus,
    ClarificationRoundStatus,
    accept_brief_assumption,
    complete_clarification_round,
    create_brief_assumption,
    create_clarification_round,
    reject_brief_assumption,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
ROUND_ID = UUID("00000000-0000-4000-8000-000000000030")
ASSUMPTION_ID = UUID("00000000-0000-4000-8000-000000000040")
CREATED_AT = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


def build_round(
    *,
    round_number: int = 1,
):
    """Create a deterministic open clarification round."""
    return create_clarification_round(
        round_id=ROUND_ID,
        project_id=PROJECT_ID,
        source_brief_version_number=1,
        round_number=round_number,
        catalog_version=(CLARIFICATION_CATALOG_VERSION),
        questions=[
            clarification_question_for(BriefField.GOALS),
            clarification_question_for(BriefField.PROBLEM),
        ],
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def test_round_normalizes_question_order_and_starts_open() -> None:
    """Create an ordered round without completion state."""
    round_state = build_round()

    assert round_state.status is (ClarificationRoundStatus.OPEN)
    assert tuple(question.field for question in round_state.questions) == (
        BriefField.PROBLEM,
        BriefField.GOALS,
    )
    assert round_state.answered_at is None
    assert round_state.resulting_brief_version_number is None


@pytest.mark.parametrize(
    "round_number",
    [
        0,
        4,
    ],
)
def test_round_number_respects_operational_limit(
    round_number: int,
) -> None:
    """Prevent a fourth clarification round."""
    with pytest.raises(
        ValueError,
        match=("clarification round number must be between 1 and 3"),
    ):
        build_round(round_number=round_number)


def test_complete_round_returns_new_answered_state() -> None:
    """Link an answered round to the new immutable brief version."""
    original = build_round()
    answered_at = CREATED_AT + timedelta(minutes=5)

    completed = complete_clarification_round(
        original,
        resulting_brief_version_number=2,
        answered_at=answered_at,
    )

    assert completed is not original
    assert original.status is (ClarificationRoundStatus.OPEN)
    assert completed.status is (ClarificationRoundStatus.ANSWERED)
    assert completed.answered_at == answered_at
    assert completed.resulting_brief_version_number == 2


def test_resulting_version_must_follow_source_version() -> None:
    """Reject a round result that does not create a new version."""
    with pytest.raises(
        ValueError,
        match=("resulting brief version must follow"),
    ):
        complete_clarification_round(
            build_round(),
            resulting_brief_version_number=1,
            answered_at=(CREATED_AT + timedelta(minutes=1)),
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
