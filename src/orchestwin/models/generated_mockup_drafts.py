from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orchestwin.artifacts.bound_mockups import (
    BoundGeneratedMockup,
    create_bound_mockup,
    markup_requirement_codes,
)
from orchestwin.artifacts.generated_mockup_repair import repair_generated_mockup
from orchestwin.artifacts.generated_mockup_review import (
    MockupIssue,
    MockupIssueSeverity,
    MockupReport,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockup_structure import nodes_text
from orchestwin.artifacts.generated_mockup_styles import GeneratedMockupError
from orchestwin.artifacts.generated_mockups import (
    MAX_MARKUP_LENGTH,
    MAX_SCREENS,
    MAX_STYLES_LENGTH,
    MIN_SCREENS,
    GeneratedMockup,
    create_generated_mockup,
    screen_trees,
)
from orchestwin.artifacts.prototypes import DeclarativePrototype, PrototypeScreenState
from orchestwin.artifacts.visual_catalog import ARCHETYPES, MODES
from orchestwin.models.output_language import LANGUAGE_NAMES, written_in_another_language
from orchestwin.models.requirements_drafts import Title

MAX_APPROACH_LENGTH: Final = 600
MAX_CHANGES: Final = 8
MAX_CHANGE_LENGTH: Final = 300
MAX_REJECTION_REASONS: Final = 20
MAX_REASON_DETAIL_LENGTH: Final = 300
EXTRA_STATE_SCREENS: Final = 2
UNSAFE_MOCKUP_OUTPUT: Final = "UNSAFE_MOCKUP_OUTPUT"
MOCKUP_QUALITY_REJECTED: Final = "MOCKUP_QUALITY_REJECTED"
MOCKUP_LANGUAGE_MISMATCH: Final = "MOCKUP_LANGUAGE_MISMATCH"
MOCKUP_SCREEN_COUNT: Final = "MOCKUP_SCREEN_COUNT"
MOCKUP_COVERAGE_TOO_LOW: Final = "MOCKUP_COVERAGE_TOO_LOW"
GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE: Final = "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE"
REQUIREMENTS_NOT_COVERED: Final = "REQUIREMENTS_NOT_COVERED"
SCREEN_LANGUAGE: Final = "SCREEN_LANGUAGE"
SCREEN_COUNT: Final = "SCREEN_COUNT"
REJECTION_CODES: Final = (
    UNSAFE_MOCKUP_OUTPUT,
    MOCKUP_QUALITY_REJECTED,
    MOCKUP_LANGUAGE_MISMATCH,
    MOCKUP_SCREEN_COUNT,
    MOCKUP_COVERAGE_TOO_LOW,
    GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE,
)
_SCREEN_PREFIX: Final = re.compile(r"(SCR-[0-9]{3}): ")

ScreenCode = Annotated[str, Field(pattern=r"^SCR-[0-9]{3}$")]
ScreenMarkup = Annotated[str, Field(min_length=1, max_length=MAX_MARKUP_LENGTH)]
StyleSheetText = Annotated[str, Field(min_length=1, max_length=MAX_STYLES_LENGTH)]
Approach = Annotated[str, Field(min_length=1, max_length=MAX_APPROACH_LENGTH)]
Change = Annotated[str, Field(min_length=1, max_length=MAX_CHANGE_LENGTH)]


class GeneratedScreenDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: ScreenCode
    heading: Title
    kind: PrototypeScreenState
    markup: ScreenMarkup


Screens = Annotated[
    tuple[GeneratedScreenDraft, ...], Field(min_length=MIN_SCREENS, max_length=MAX_SCREENS)
]


class GeneratedMockupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approach: Approach
    css: StyleSheetText
    screens: Screens


class GeneratedIterationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    approach: Approach
    changes: Annotated[tuple[Change, ...], Field(min_length=1, max_length=MAX_CHANGES)]
    css: StyleSheetText
    screens: Screens


@dataclass(frozen=True, slots=True)
class MockupRejectionReason:
    code: str
    screen_code: str | None
    detail: str

    def to_snapshot(self) -> dict[str, object]:
        return {"code": self.code, "screen_code": self.screen_code, "detail": self.detail}


class GeneratedMockupRejection(ValueError):
    def __init__(self, code: str, reasons: Iterable[MockupRejectionReason] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.reasons = tuple(reasons)[:MAX_REJECTION_REASONS]

    def to_snapshot(self) -> dict[str, object]:
        return {"code": self.code, "reasons": [reason.to_snapshot() for reason in self.reasons]}

    def reason_text(self) -> str:
        return "; ".join(
            " ".join(part for part in (reason.code, reason.screen_code, reason.detail) if part)
            for reason in self.reasons
        )


@dataclass(frozen=True, slots=True)
class GeneratedMockupBinding:
    mockup: BoundGeneratedMockup
    prototype: DeclarativePrototype
    report: MockupReport
    warnings: tuple[MockupIssue, ...]

    def warning_snapshots(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {"code": issue.code, "screen_code": issue.screen_code, "detail": issue.detail}
            for issue in self.warnings
        )


def screen_limits(alternative, *, iteration: bool = False) -> tuple[int, int]:
    visual = alternative.visual_language
    if visual is None:
        raise GeneratedMockupRejection(
            GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE,
            (_reason(GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE, None, alternative.code),),
        )
    spec = ARCHETYPES[visual.choices.archetype]
    if iteration:
        return spec.minimum_screens, MAX_SCREENS
    return spec.minimum_screens, min(spec.maximum_screens + EXTRA_STATE_SCREENS, MAX_SCREENS)


def requirement_codes(requirements) -> dict[str, UUID]:
    return {item.code: item.id for item in requirements.specification.requirements}


def declared_requirement_codes(alternative, requirements) -> tuple[str, ...]:
    codes = {item.id: item.code for item in requirements.specification.requirements}
    return tuple(sorted(codes[value] for value in alternative.requirement_ids if value in codes))


def _bounded(text: str) -> str:
    normalized = " ".join(str(text).split())
    return normalized[:MAX_REASON_DETAIL_LENGTH]


def _reason(code: str, screen_code: str | None, detail: str) -> MockupRejectionReason:
    return MockupRejectionReason(code, screen_code, _bounded(detail))


def _issue_reason(issue: MockupIssue) -> MockupRejectionReason:
    return _reason(issue.code, issue.screen_code, issue.detail)


def _unsafe(error: Exception) -> GeneratedMockupRejection:
    code = getattr(error, "code", type(error).__name__)
    detail = str(getattr(error, "detail", error))
    match = _SCREEN_PREFIX.match(detail)
    return GeneratedMockupRejection(
        UNSAFE_MOCKUP_OUTPUT, (_reason(code, match.group(1) if match else None, detail),)
    )


def _language_reasons(mockup: GeneratedMockup, language: str | None) -> list[MockupRejectionReason]:
    if language is None:
        return []
    name = LANGUAGE_NAMES.get(language, language)
    trees = screen_trees(mockup)
    return [
        _reason(SCREEN_LANGUAGE, screen.code, f"the visible text is not written in {name}")
        for screen in mockup.screens
        if written_in_another_language(nodes_text(trees[screen.code]), language)
    ]


def bind_generated_mockup(
    draft: GeneratedMockupDraft | GeneratedIterationDraft,
    *,
    alternative,
    requirements,
    language: str | None,
) -> GeneratedMockupBinding:
    minimum, maximum = screen_limits(
        alternative, iteration=isinstance(draft, GeneratedIterationDraft)
    )
    visual = alternative.visual_language
    tokens = visual.token_values
    known = requirement_codes(requirements)
    declared = declared_requirement_codes(alternative, requirements)
    repair = repair_generated_mockup(
        styles=draft.css,
        screens=[(screen.code, screen.markup) for screen in draft.screens],
        requirement_codes=known,
        token_names=tokens,
        declared_codes=declared,
    )
    try:
        mockup = create_generated_mockup(
            design_alternative_id=alternative.id,
            title=visual.product_name,
            styles=repair.styles,
            screens=[
                {
                    "code": screen.code,
                    "title": screen.heading,
                    "state": screen.kind,
                    "markup": markup,
                }
                for screen, markup in zip(draft.screens, repair.markups, strict=True)
            ],
            token_names=tokens,
        )
    except GeneratedMockupError as error:
        raise _unsafe(error) from error
    report = review_generated_mockup(
        mockup,
        tokens=tokens,
        requirement_codes=frozenset(known),
        text_contrast_threshold=MODES[visual.choices.color_mode].text_threshold,
    )
    errors = [issue for issue in report.issues if issue.severity is MockupIssueSeverity.ERROR]
    warnings = [
        *(
            MockupIssue(note.code, MockupIssueSeverity.WARNING, note.screen_code, note.detail)
            for note in repair.notes
        ),
        *(issue for issue in report.issues if issue.severity is MockupIssueSeverity.WARNING),
    ]
    failures: list[tuple[str, list[MockupRejectionReason]]] = []
    if errors:
        failures.append((MOCKUP_QUALITY_REJECTED, [_issue_reason(issue) for issue in errors]))
    mismatched = _language_reasons(mockup, language)
    if mismatched:
        failures.append((MOCKUP_LANGUAGE_MISMATCH, mismatched))
    count = len(mockup.screens)
    expected = f"{count} screens, expected {minimum} to {maximum}"
    if count < minimum:
        failures.append((MOCKUP_SCREEN_COUNT, [_reason(SCREEN_COUNT, None, expected)]))
    elif count > maximum:
        warnings.append(MockupIssue(SCREEN_COUNT, MockupIssueSeverity.WARNING, None, expected))
    covered = set(report.covered_requirement_codes)
    missing = tuple(code for code in declared if code not in covered)
    if declared and 2 * (len(declared) - len(missing)) < len(declared):
        failures.append(
            (
                MOCKUP_COVERAGE_TOO_LOW,
                [
                    _reason(
                        REQUIREMENTS_NOT_COVERED,
                        None,
                        f"{len(declared) - len(missing)} of {len(declared)} declared requirements "
                        f"covered; missing {', '.join(missing)}",
                    )
                ],
            )
        )
    if failures:
        reasons = [reason for _code, items in failures for reason in items]
        reasons.extend(_issue_reason(issue) for issue in warnings)
        raise GeneratedMockupRejection(failures[0][0], reasons)
    try:
        bound = create_bound_mockup(
            mockup=mockup,
            requirement_ids_by_code={
                code: known[code] for code in markup_requirement_codes(mockup)
            },
        )
        prototype = bound.prototype()
    except (GeneratedMockupError, KeyError, TypeError, ValueError) as error:
        raise _unsafe(error) from error
    notes = list(warnings)
    if missing:
        notes.append(
            MockupIssue(
                REQUIREMENTS_NOT_COVERED, MockupIssueSeverity.WARNING, None, ", ".join(missing)
            )
        )
    return GeneratedMockupBinding(
        mockup=bound, prototype=prototype, report=report, warnings=tuple(notes)
    )


__all__ = [
    "EXTRA_STATE_SCREENS",
    "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
    "MAX_APPROACH_LENGTH",
    "MAX_CHANGES",
    "MAX_CHANGE_LENGTH",
    "MAX_REASON_DETAIL_LENGTH",
    "MAX_REJECTION_REASONS",
    "MOCKUP_COVERAGE_TOO_LOW",
    "MOCKUP_LANGUAGE_MISMATCH",
    "MOCKUP_QUALITY_REJECTED",
    "MOCKUP_SCREEN_COUNT",
    "REJECTION_CODES",
    "REQUIREMENTS_NOT_COVERED",
    "UNSAFE_MOCKUP_OUTPUT",
    "GeneratedIterationDraft",
    "GeneratedMockupBinding",
    "GeneratedMockupDraft",
    "GeneratedMockupRejection",
    "GeneratedScreenDraft",
    "MockupRejectionReason",
    "bind_generated_mockup",
    "declared_requirement_codes",
    "requirement_codes",
    "screen_limits",
]
