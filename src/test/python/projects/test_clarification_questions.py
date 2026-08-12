"""Tests for deterministic Project Brief clarification questions."""

import pytest

from orchestwin.projects.briefs import (
    LIST_FIELDS,
    TEXT_FIELDS,
    BriefField,
    create_project_brief,
)
from orchestwin.projects.clarification import (
    CLARIFICATION_CATALOG_VERSION,
    ClarificationAnswerType,
    all_clarification_questions,
    clarification_question_for,
    focused_clarification_questions,
)


def test_catalog_contains_one_stable_question_per_brief_field() -> None:
    """Cover the complete Project Brief with unique question IDs."""
    questions = all_clarification_questions()

    assert tuple(question.field for question in questions) == tuple(BriefField)

    assert len(questions) == len(BriefField)

    assert len({question.question_id for question in questions}) == len(BriefField)

    assert all(question.catalog_version == CLARIFICATION_CATALOG_VERSION for question in questions)

    assert all(
        question.question_id
        == (f"project-brief.{question.field.value}.v{CLARIFICATION_CATALOG_VERSION}")
        for question in questions
    )


def test_catalog_exposes_stable_localization_keys() -> None:
    """Keep translated text outside the backend question catalog."""
    question = clarification_question_for(BriefField.PROBLEM)

    assert question.prompt_key == ("clarification.questions.problem.prompt")
    assert question.hint_key == ("clarification.questions.problem.hint")


@pytest.mark.parametrize(
    "field",
    sorted(
        TEXT_FIELDS,
        key=lambda candidate: candidate.value,
    ),
)
def test_text_fields_require_text_answers(
    field: BriefField,
) -> None:
    """Map scalar Project Brief fields to text answers."""
    question = clarification_question_for(field)

    assert question.answer_type is (ClarificationAnswerType.TEXT)


@pytest.mark.parametrize(
    "field",
    sorted(
        LIST_FIELDS,
        key=lambda candidate: candidate.value,
    ),
)
def test_list_fields_require_item_list_answers(
    field: BriefField,
) -> None:
    """Map structured Project Brief collections to item-list answers."""
    question = clarification_question_for(field)

    assert question.answer_type is (ClarificationAnswerType.ITEM_LIST)


def test_name_requires_a_value_while_other_fields_allow_unknown() -> None:
    """Keep a project identity mandatory without inventing other facts."""
    name_question = clarification_question_for(BriefField.NAME)
    remaining_questions = (
        question
        for question in all_clarification_questions()
        if question.field is not BriefField.NAME
    )

    assert name_question.unknown_allowed is False

    assert all(question.unknown_allowed for question in remaining_questions)


def test_questions_are_generated_only_for_missing_fields() -> None:
    """Exclude owner-provided and explicitly unknown fields."""
    brief = create_project_brief(
        name="Hotel Management",
        budget=None,
        unknown_fields=[
            BriefField.BUDGET,
        ],
    )

    questions = focused_clarification_questions(
        brief,
        maximum_questions=4,
    )

    assert tuple(question.field for question in questions) == (
        BriefField.DESCRIPTION,
        BriefField.PROBLEM,
        BriefField.GOALS,
        BriefField.TARGET_USERS,
    )

    assert all(question.field is not BriefField.NAME for question in questions)

    assert all(question.field is not BriefField.BUDGET for question in questions)


def test_question_limit_preserves_deterministic_priority_order() -> None:
    """Truncate a round without changing catalog ordering."""
    brief = create_project_brief(name="Project")

    first_round = focused_clarification_questions(
        brief,
        maximum_questions=3,
    )
    repeated_round = focused_clarification_questions(
        brief,
        maximum_questions=3,
    )

    assert first_round == repeated_round

    assert tuple(question.field for question in first_round) == (
        BriefField.DESCRIPTION,
        BriefField.PROBLEM,
        BriefField.GOALS,
    )


def test_complete_epistemic_state_requires_no_questions() -> None:
    """Return no questions when every field is provided or unknown."""
    brief = create_project_brief(
        name="Project",
        unknown_fields=[field for field in BriefField if field is not BriefField.NAME],
    )

    assert focused_clarification_questions(brief) == ()


@pytest.mark.parametrize(
    "maximum_questions",
    [
        0,
        -1,
    ],
)
def test_question_limit_must_be_positive(
    maximum_questions: int,
) -> None:
    """Reject invalid clarification-round configuration."""
    brief = create_project_brief(name="Project")

    with pytest.raises(
        ValueError,
        match=("maximum clarification questions must be positive"),
    ):
        focused_clarification_questions(
            brief,
            maximum_questions=maximum_questions,
        )
