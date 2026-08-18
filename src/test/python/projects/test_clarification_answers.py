"""Tests for pure Project Brief clarification-answer application."""

import pytest

from orchestwin.projects.briefs import (
    BriefField,
    create_project_brief,
)
from orchestwin.projects.clarification import (
    ClarificationAnswer,
    ClarificationAnswerIssueCode,
    ClarificationApplicationStatus,
    apply_clarification_answers,
    clarification_question_for,
)


def question_id(
    field: BriefField,
) -> str:
    """Return the stable catalog question ID for a field."""
    return clarification_question_for(field).question_id


def test_text_and_list_answers_create_a_new_normalized_brief() -> None:
    """Apply valid answers without mutating the original brief."""
    original = create_project_brief()

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.item_list(
                question_id=question_id(BriefField.GOALS),
                values=[
                    " Manage rooms ",
                    " Track   reservations ",
                ],
            ),
            ClarificationAnswer.text(
                question_id=question_id(BriefField.NAME),
                value=" Hotel   Management ",
            ),
        ],
    )

    assert result.status is (ClarificationApplicationStatus.APPLIED)
    assert result.updated_brief is not None
    assert result.issues == ()

    assert original.name is None
    assert original.goals is None

    assert result.updated_brief.name == ("Hotel Management")
    assert result.updated_brief.goals == (
        "Manage rooms",
        "Track reservations",
    )

    assert result.applied_fields == (
        BriefField.NAME,
        BriefField.GOALS,
    )


def test_unknown_answer_changes_epistemic_state() -> None:
    """Move one field from MISSING to UNKNOWN explicitly."""
    original = create_project_brief(name="Project")

    result = apply_clarification_answers(
        original,
        [ClarificationAnswer.unknown(question_id=question_id(BriefField.BUDGET))],
    )

    assert result.status is (ClarificationApplicationStatus.APPLIED)
    assert result.updated_brief is not None

    assert BriefField.BUDGET in (result.updated_brief.unknown_fields)
    assert BriefField.BUDGET not in (result.updated_brief.missing_fields)
    assert result.updated_brief.budget is None

    assert BriefField.BUDGET not in (original.unknown_fields)
    assert BriefField.BUDGET in (original.missing_fields)


def test_name_cannot_be_marked_unknown() -> None:
    """Require a concrete project identity."""
    original = create_project_brief()

    result = apply_clarification_answers(
        original,
        [ClarificationAnswer.unknown(question_id=question_id(BriefField.NAME))],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)
    assert result.updated_brief is None
    assert result.issues[0].code is (ClarificationAnswerIssueCode.UNKNOWN_NOT_ALLOWED)
    assert result.issues[0].field is (BriefField.NAME)


def test_provided_and_unknown_fields_cannot_be_answered_again() -> None:
    """Accept answers only for fields currently marked as missing."""
    original = create_project_brief(
        name="Project",
        unknown_fields=[BriefField.BUDGET],
    )

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.text(
                question_id=question_id(BriefField.NAME),
                value="Replacement project",
            ),
            ClarificationAnswer.text(
                question_id=question_id(BriefField.BUDGET),
                value="EUR 5,000",
            ),
        ],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)
    assert result.updated_brief is None

    assert tuple(issue.code for issue in result.issues) == (
        ClarificationAnswerIssueCode.FIELD_NOT_MISSING,
        ClarificationAnswerIssueCode.FIELD_NOT_MISSING,
    )


def test_wrong_answer_type_rejects_the_complete_batch() -> None:
    """Avoid partially applying a batch containing a type mismatch."""
    original = create_project_brief()

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.text(
                question_id=question_id(BriefField.NAME),
                value="Project",
            ),
            ClarificationAnswer.text(
                question_id=question_id(BriefField.GOALS),
                value="This should be a list",
            ),
        ],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)
    assert result.updated_brief is None
    assert result.applied_fields == ()

    assert result.issues == (result.issues[0],)
    assert result.issues[0].code is (ClarificationAnswerIssueCode.ANSWER_TYPE_MISMATCH)

    assert original.name is None
    assert original.goals is None


def test_empty_text_and_item_lists_are_rejected() -> None:
    """Reject answers that do not provide meaningful information."""
    original = create_project_brief(name="Project")

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.text(
                question_id=question_id(BriefField.DESCRIPTION),
                value="   ",
            ),
            ClarificationAnswer.item_list(
                question_id=question_id(BriefField.GOALS),
                values=[
                    " ",
                    "\t",
                ],
            ),
        ],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)

    assert tuple(issue.code for issue in result.issues) == (
        ClarificationAnswerIssueCode.EMPTY_VALUE,
        ClarificationAnswerIssueCode.EMPTY_VALUE,
    )


def test_unknown_question_is_rejected() -> None:
    """Reject question identifiers outside the versioned catalog."""
    original = create_project_brief()

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.text(
                question_id=("project-brief.unregistered-field.v1"),
                value="Value",
            )
        ],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)
    assert result.updated_brief is None
    assert result.issues == (result.issues[0],)
    assert result.issues[0].code is (ClarificationAnswerIssueCode.UNKNOWN_QUESTION)
    assert result.issues[0].field is None


def test_duplicate_answers_for_one_field_are_rejected_atomically() -> None:
    """Require at most one answer for each field in a batch."""
    original = create_project_brief()

    result = apply_clarification_answers(
        original,
        [
            ClarificationAnswer.text(
                question_id=question_id(BriefField.NAME),
                value="First project name",
            ),
            ClarificationAnswer.text(
                question_id=question_id(BriefField.NAME),
                value="Second project name",
            ),
        ],
    )

    assert result.status is (ClarificationApplicationStatus.REJECTED)
    assert result.updated_brief is None
    assert result.issues[0].code is (ClarificationAnswerIssueCode.DUPLICATE_FIELD)
    assert original.name is None


def test_empty_answer_batch_produces_no_changes() -> None:
    """Represent a missing submission without manufacturing a new brief."""
    original = create_project_brief(name="Project")

    result = apply_clarification_answers(
        original,
        [],
    )

    assert result.status is (ClarificationApplicationStatus.NO_ANSWERS)
    assert result.updated_brief is None
    assert result.applied_fields == ()
    assert result.issues == ()


def test_item_list_factory_rejects_a_string_value() -> None:
    """Prevent a string from being split into character items."""
    with pytest.raises(
        ValueError,
        match=("item-list clarification answer must not be a string"),
    ):
        ClarificationAnswer.item_list(
            question_id=question_id(BriefField.GOALS),
            values="Not a list",
        )
