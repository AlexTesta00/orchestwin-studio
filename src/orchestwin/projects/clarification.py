"""Deterministic clarification questions for incomplete Project Briefs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from orchestwin.projects.briefs import (
    LIST_FIELDS,
    TEXT_FIELDS,
    BriefField,
    ProjectBrief,
)

CLARIFICATION_CATALOG_VERSION: Final = 1


class ClarificationAnswerType(StrEnum):
    """Structured answer shapes supported by clarification questions."""

    TEXT = "text"
    ITEM_LIST = "item_list"


@dataclass(frozen=True, slots=True)
class ClarificationQuestionSpec:
    """Versioned metadata for one focused clarification question."""

    question_id: str
    catalog_version: int
    field: BriefField
    answer_type: ClarificationAnswerType
    priority: int
    prompt_key: str
    hint_key: str
    unknown_allowed: bool

    def __post_init__(self) -> None:
        """Protect the stable clarification-question contract."""
        if self.catalog_version < 1:
            raise ValueError("clarification catalog version must be positive")

        if self.priority < 1:
            raise ValueError("clarification question priority must be positive")

        expected_question_id = f"project-brief.{self.field.value}.v{self.catalog_version}"

        if self.question_id != expected_question_id:
            raise ValueError(
                "clarification question ID does not match its field and catalog version"
            )

        expected_key_prefix = f"clarification.questions.{self.field.value}"

        if self.prompt_key != f"{expected_key_prefix}.prompt":
            raise ValueError("clarification prompt key does not match its field")

        if self.hint_key != f"{expected_key_prefix}.hint":
            raise ValueError("clarification hint key does not match its field")


def answer_type_for(
    field: BriefField,
) -> ClarificationAnswerType:
    """Return the structured answer type associated with a brief field."""
    if field in TEXT_FIELDS:
        return ClarificationAnswerType.TEXT

    if field in LIST_FIELDS:
        return ClarificationAnswerType.ITEM_LIST

    raise ValueError(f"unsupported Project Brief field: {field.value}")


def build_question_spec(
    *,
    field: BriefField,
    priority: int,
) -> ClarificationQuestionSpec:
    """Build one versioned clarification-question specification."""
    key_prefix = f"clarification.questions.{field.value}"

    return ClarificationQuestionSpec(
        question_id=(f"project-brief.{field.value}.v{CLARIFICATION_CATALOG_VERSION}"),
        catalog_version=(CLARIFICATION_CATALOG_VERSION),
        field=field,
        answer_type=answer_type_for(field),
        priority=priority,
        prompt_key=f"{key_prefix}.prompt",
        hint_key=f"{key_prefix}.hint",
        unknown_allowed=(field is not BriefField.NAME),
    )


CLARIFICATION_QUESTION_CATALOG: Final[
    Mapping[
        BriefField,
        ClarificationQuestionSpec,
    ]
] = MappingProxyType(
    {
        field: build_question_spec(
            field=field,
            priority=priority,
        )
        for priority, field in enumerate(
            BriefField,
            start=1,
        )
    }
)


def clarification_question_for(
    field: BriefField,
) -> ClarificationQuestionSpec:
    """Return the catalog entry for one Project Brief field."""
    return CLARIFICATION_QUESTION_CATALOG[field]


def all_clarification_questions() -> tuple[ClarificationQuestionSpec, ...]:
    """Return the complete catalog in deterministic priority order."""
    return tuple(
        sorted(
            CLARIFICATION_QUESTION_CATALOG.values(),
            key=lambda question: (
                question.priority,
                question.field.value,
            ),
        )
    )


def focused_clarification_questions(
    brief: ProjectBrief,
    *,
    maximum_questions: int = 5,
) -> tuple[ClarificationQuestionSpec, ...]:
    """Select focused questions for fields currently marked as missing."""
    if maximum_questions < 1:
        raise ValueError("maximum clarification questions must be positive")

    missing_fields = brief.missing_fields

    questions = (
        question for question in all_clarification_questions() if question.field in missing_fields
    )

    return tuple(questions)[:maximum_questions]
