"""Deterministic clarification questions and answer application."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from orchestwin.projects.briefs import (
    LIST_FIELDS,
    TEXT_FIELDS,
    BriefField,
    ProjectBrief,
    normalize_optional_items,
    normalize_optional_text,
)

CLARIFICATION_CATALOG_VERSION: Final = 1


class ClarificationAnswerType(StrEnum):
    """Structured answer shapes supported by clarification questions."""

    TEXT = "text"
    ITEM_LIST = "item_list"


class ClarificationAnswerKind(StrEnum):
    """Kinds of owner responses accepted during clarification."""

    TEXT = "text"
    ITEM_LIST = "item_list"
    UNKNOWN = "unknown"


class ClarificationAnswerIssueCode(StrEnum):
    """Stable reasons for rejecting a clarification answer."""

    UNKNOWN_QUESTION = "unknown_question"
    DUPLICATE_FIELD = "duplicate_field"
    FIELD_NOT_MISSING = "field_not_missing"
    ANSWER_TYPE_MISMATCH = "answer_type_mismatch"
    UNKNOWN_NOT_ALLOWED = "unknown_not_allowed"
    EMPTY_VALUE = "empty_value"


class ClarificationApplicationStatus(StrEnum):
    """Stable outcomes of applying a clarification-answer batch."""

    APPLIED = "applied"
    NO_ANSWERS = "no_answers"
    REJECTED = "rejected"


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

        if self.prompt_key != (f"{expected_key_prefix}.prompt"):
            raise ValueError("clarification prompt key does not match its field")

        if self.hint_key != (f"{expected_key_prefix}.hint"):
            raise ValueError("clarification hint key does not match its field")


@dataclass(frozen=True, slots=True)
class ClarificationAnswer:
    """One structured owner response to a clarification question."""

    question_id: str
    kind: ClarificationAnswerKind
    text_value: str | None = None
    item_values: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Protect the discriminated clarification-answer shape."""
        normalized_question_id = self.question_id.strip()

        if not normalized_question_id or normalized_question_id != self.question_id:
            raise ValueError("clarification question ID must be normalized")

        if self.kind is ClarificationAnswerKind.TEXT:
            if self.text_value is None or self.item_values is not None:
                raise ValueError("text clarification answers require only text_value")

            return

        if self.kind is ClarificationAnswerKind.ITEM_LIST:
            if self.item_values is None or self.text_value is not None:
                raise ValueError("item-list clarification answers require only item_values")

            return

        if self.text_value is not None or self.item_values is not None:
            raise ValueError("UNKNOWN clarification answers must not contain values")

    @classmethod
    def text(
        cls,
        *,
        question_id: str,
        value: str,
    ) -> ClarificationAnswer:
        """Create a textual clarification answer."""
        return cls(
            question_id=question_id,
            kind=ClarificationAnswerKind.TEXT,
            text_value=value,
        )

    @classmethod
    def item_list(
        cls,
        *,
        question_id: str,
        values: Iterable[str],
    ) -> ClarificationAnswer:
        """Create a structured list clarification answer."""
        if isinstance(values, str):
            raise ValueError("item-list clarification answer must not be a string")

        return cls(
            question_id=question_id,
            kind=ClarificationAnswerKind.ITEM_LIST,
            item_values=tuple(values),
        )

    @classmethod
    def unknown(
        cls,
        *,
        question_id: str,
    ) -> ClarificationAnswer:
        """Create an explicit UNKNOWN clarification answer."""
        return cls(
            question_id=question_id,
            kind=ClarificationAnswerKind.UNKNOWN,
        )


@dataclass(frozen=True, slots=True)
class ClarificationAnswerIssue:
    """One validation issue found in a clarification-answer batch."""

    code: ClarificationAnswerIssueCode
    question_id: str
    field: BriefField | None = None


@dataclass(frozen=True, slots=True)
class ClarificationApplicationResult:
    """Typed result of atomically applying clarification answers."""

    status: ClarificationApplicationStatus
    updated_brief: ProjectBrief | None = None
    applied_fields: tuple[BriefField, ...] = ()
    issues: tuple[ClarificationAnswerIssue, ...] = ()

    def __post_init__(self) -> None:
        """Protect result-state invariants."""
        if self.status is ClarificationApplicationStatus.APPLIED:
            if self.updated_brief is None or not self.applied_fields or self.issues:
                raise ValueError(
                    "APPLIED clarification results require "
                    "a brief and applied fields without issues"
                )

            return

        if self.status is ClarificationApplicationStatus.NO_ANSWERS:
            if self.updated_brief is not None or self.applied_fields or self.issues:
                raise ValueError("NO_ANSWERS clarification results must not contain data")

            return

        if self.updated_brief is not None or self.applied_fields or not self.issues:
            raise ValueError(
                "REJECTED clarification results require issues without an updated brief"
            )


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


CLARIFICATION_QUESTION_BY_ID: Final[
    Mapping[
        str,
        ClarificationQuestionSpec,
    ]
] = MappingProxyType(
    {question.question_id: question for question in CLARIFICATION_QUESTION_CATALOG.values()}
)


def clarification_question_for(
    field: BriefField,
) -> ClarificationQuestionSpec:
    """Return the catalog entry for one Project Brief field."""
    return CLARIFICATION_QUESTION_CATALOG[field]


def clarification_question_by_id(
    question_id: str,
) -> ClarificationQuestionSpec | None:
    """Return the current catalog entry for a stable question ID."""
    return CLARIFICATION_QUESTION_BY_ID.get(question_id)


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


def apply_clarification_answers(
    brief: ProjectBrief,
    answers: Iterable[ClarificationAnswer],
) -> ClarificationApplicationResult:
    """Atomically apply valid answers to a new immutable Project Brief."""
    answer_batch = tuple(answers)

    if not answer_batch:
        return ClarificationApplicationResult(status=(ClarificationApplicationStatus.NO_ANSWERS))

    missing_fields = brief.missing_fields
    seen_fields: set[BriefField] = set()
    issues: list[ClarificationAnswerIssue] = []
    validated_answers: list[
        tuple[
            ClarificationQuestionSpec,
            str | tuple[str, ...] | None,
            bool,
        ]
    ] = []

    for answer in answer_batch:
        question = clarification_question_by_id(answer.question_id)

        if question is None:
            issues.append(
                ClarificationAnswerIssue(
                    code=(ClarificationAnswerIssueCode.UNKNOWN_QUESTION),
                    question_id=answer.question_id,
                )
            )
            continue

        field = question.field

        if field in seen_fields:
            issues.append(
                ClarificationAnswerIssue(
                    code=(ClarificationAnswerIssueCode.DUPLICATE_FIELD),
                    question_id=answer.question_id,
                    field=field,
                )
            )
            continue

        seen_fields.add(field)

        if field not in missing_fields:
            issues.append(
                ClarificationAnswerIssue(
                    code=(ClarificationAnswerIssueCode.FIELD_NOT_MISSING),
                    question_id=answer.question_id,
                    field=field,
                )
            )
            continue

        if answer.kind is ClarificationAnswerKind.UNKNOWN:
            if not question.unknown_allowed:
                issues.append(
                    ClarificationAnswerIssue(
                        code=(ClarificationAnswerIssueCode.UNKNOWN_NOT_ALLOWED),
                        question_id=(answer.question_id),
                        field=field,
                    )
                )
                continue

            validated_answers.append(
                (
                    question,
                    None,
                    True,
                )
            )
            continue

        if answer.kind is ClarificationAnswerKind.TEXT:
            if question.answer_type is not ClarificationAnswerType.TEXT:
                issues.append(
                    ClarificationAnswerIssue(
                        code=(ClarificationAnswerIssueCode.ANSWER_TYPE_MISMATCH),
                        question_id=(answer.question_id),
                        field=field,
                    )
                )
                continue

            normalized_text = normalize_optional_text(answer.text_value)

            if normalized_text is None:
                issues.append(
                    ClarificationAnswerIssue(
                        code=(ClarificationAnswerIssueCode.EMPTY_VALUE),
                        question_id=(answer.question_id),
                        field=field,
                    )
                )
                continue

            validated_answers.append(
                (
                    question,
                    normalized_text,
                    False,
                )
            )
            continue

        if question.answer_type is not ClarificationAnswerType.ITEM_LIST:
            issues.append(
                ClarificationAnswerIssue(
                    code=(ClarificationAnswerIssueCode.ANSWER_TYPE_MISMATCH),
                    question_id=answer.question_id,
                    field=field,
                )
            )
            continue

        normalized_items = normalize_optional_items(answer.item_values)

        if normalized_items is None:
            issues.append(
                ClarificationAnswerIssue(
                    code=(ClarificationAnswerIssueCode.EMPTY_VALUE),
                    question_id=answer.question_id,
                    field=field,
                )
            )
            continue

        validated_answers.append(
            (
                question,
                normalized_items,
                False,
            )
        )

    if issues:
        return ClarificationApplicationResult(
            status=(ClarificationApplicationStatus.REJECTED),
            issues=tuple(issues),
        )

    validated_answers.sort(
        key=lambda entry: (
            entry[0].priority,
            entry[0].field.value,
        )
    )

    unknown_fields = set(brief.unknown_fields)
    updates: dict[str, object] = {}

    for (
        question,
        value,
        marks_unknown,
    ) in validated_answers:
        field = question.field

        if marks_unknown:
            unknown_fields.add(field)
            updates[field.value] = None
        else:
            unknown_fields.discard(field)
            updates[field.value] = value

    updates["unknown_fields"] = frozenset(unknown_fields)

    updated_brief = replace(
        brief,
        **updates,
    )

    return ClarificationApplicationResult(
        status=(ClarificationApplicationStatus.APPLIED),
        updated_brief=updated_brief,
        applied_fields=tuple(
            question.field
            for (
                question,
                _,
                _,
            ) in validated_answers
        ),
    )
