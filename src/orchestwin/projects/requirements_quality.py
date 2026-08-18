"""Acceptance, scenario, risk, and Definition of Done artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    RequirementSourceReference,
    UserTwinVersionReference,
    canonical_requirement_sources,
    canonical_uuid_tuple,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)

_MAX_STATEMENT_LENGTH: Final = 4000
_MAX_TITLE_LENGTH: Final = 200
_MAX_SCENARIO_STEP_LENGTH: Final = 2000
_MAX_CONDITION_LENGTH: Final = 2000
_MAX_RISK_SUMMARY_LENGTH: Final = 2000
_MAX_RISK_MITIGATION_LENGTH: Final = 4000


class VerificationMethod(StrEnum):
    """How an acceptance or completion statement can be verified."""

    AUTOMATED_TEST = "AUTOMATED_TEST"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    INSPECTION = "INSPECTION"
    DEMONSTRATION = "DEMONSTRATION"
    ANALYSIS = "ANALYSIS"


class RiskLikelihood(StrEnum):
    """Qualitative likelihood used by project risks."""

    RARE = "RARE"
    UNLIKELY = "UNLIKELY"
    POSSIBLE = "POSSIBLE"
    LIKELY = "LIKELY"
    ALMOST_CERTAIN = "ALMOST_CERTAIN"


class RiskImpact(StrEnum):
    """Qualitative impact used by project risks."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskReviewStatus(StrEnum):
    """Owner review state of a proposed project risk."""

    PROPOSED = "PROPOSED"
    OWNER_ACKNOWLEDGED = "OWNER_ACKNOWLEDGED"
    OWNER_REJECTED = "OWNER_REJECTED"


class DefinitionOfDoneApplicability(StrEnum):
    """Whether a Definition of Done item always or conditionally applies."""

    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One verifiable outcome linked to requirements or user stories."""

    id: UUID
    code: str
    statement: str
    verification_method: VerificationMethod
    requirement_ids: tuple[UUID, ...] = ()
    user_story_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        """Protect identity, normalized text, and traceable ownership."""
        validate_display_code(
            self.code,
            prefix="AC",
            label="acceptance-criterion code",
        )

        if (
            normalize_required_text(
                self.statement,
                label="acceptance-criterion statement",
                maximum_length=_MAX_STATEMENT_LENGTH,
            )
            != self.statement
        ):
            raise ValueError("acceptance-criterion statement must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="acceptance-criterion requirement IDs",
            require_items=False,
        ):
            raise ValueError("acceptance-criterion requirement IDs must use canonical order")

        if self.user_story_ids != canonical_uuid_tuple(
            self.user_story_ids,
            label="acceptance-criterion user-story IDs",
            require_items=False,
        ):
            raise ValueError("acceptance-criterion user-story IDs must use canonical order")

        if not self.requirement_ids and not self.user_story_ids:
            raise ValueError("an acceptance criterion must reference a requirement or user story")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic acceptance-criterion snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "statement": self.statement,
            "verification_method": (self.verification_method.value),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this acceptance criterion."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class UsageScenario:
    """One ordered usage scenario exercising requirements and criteria."""

    id: UUID
    code: str
    title: str
    actor: UserTwinVersionReference
    preconditions: tuple[str, ...]
    trigger: str
    steps: tuple[str, ...]
    expected_outcome: str
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect ordered behavior and traceable references."""
        validate_display_code(
            self.code,
            prefix="SCN",
            label="scenario code",
        )

        for value, label, maximum_length in (
            (
                self.title,
                "scenario title",
                _MAX_TITLE_LENGTH,
            ),
            (
                self.trigger,
                "scenario trigger",
                _MAX_STATEMENT_LENGTH,
            ),
            (
                self.expected_outcome,
                "scenario expected outcome",
                _MAX_STATEMENT_LENGTH,
            ),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=maximum_length,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")

        if self.preconditions != normalize_text_items(
            self.preconditions,
            label="scenario preconditions",
            maximum_item_length=_MAX_SCENARIO_STEP_LENGTH,
            require_items=False,
            require_unique=False,
        ):
            raise ValueError("scenario preconditions must be normalized")

        if self.steps != normalize_text_items(
            self.steps,
            label="scenario steps",
            maximum_item_length=_MAX_SCENARIO_STEP_LENGTH,
            require_items=True,
            require_unique=False,
        ):
            raise ValueError("scenario steps must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="scenario requirement IDs",
            require_items=True,
        ):
            raise ValueError("scenario requirement IDs must use canonical order")

        if self.acceptance_criterion_ids != canonical_uuid_tuple(
            self.acceptance_criterion_ids,
            label="scenario acceptance-criterion IDs",
            require_items=True,
        ):
            raise ValueError("scenario acceptance-criterion IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic usage-scenario snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "actor": self.actor.to_snapshot(),
            "preconditions": list(self.preconditions),
            "trigger": self.trigger,
            "steps": list(self.steps),
            "expected_outcome": self.expected_outcome,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this scenario."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class ProjectRisk:
    """One inspectable project risk with explicit owner-review state."""

    id: UUID
    code: str
    summary: str
    likelihood: RiskLikelihood
    impact: RiskImpact
    mitigation: str
    requirement_ids: tuple[UUID, ...]
    sources: tuple[RequirementSourceReference, ...]
    review_status: RiskReviewStatus = RiskReviewStatus.PROPOSED

    def __post_init__(self) -> None:
        """Protect risk identity, grounding, and affected requirements."""
        validate_display_code(
            self.code,
            prefix="RSK",
            label="risk code",
        )

        if (
            normalize_required_text(
                self.summary,
                label="risk summary",
                maximum_length=_MAX_RISK_SUMMARY_LENGTH,
            )
            != self.summary
        ):
            raise ValueError("risk summary must be normalized")

        if (
            normalize_required_text(
                self.mitigation,
                label="risk mitigation",
                maximum_length=_MAX_RISK_MITIGATION_LENGTH,
            )
            != self.mitigation
        ):
            raise ValueError("risk mitigation must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="risk requirement IDs",
            require_items=True,
        ):
            raise ValueError("risk requirement IDs must use canonical order")

        if self.sources != canonical_requirement_sources(
            self.sources,
            require_items=True,
        ):
            raise ValueError("risk sources must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic project-risk snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "summary": self.summary,
            "likelihood": self.likelihood.value,
            "impact": self.impact.value,
            "mitigation": self.mitigation,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "sources": [source.to_snapshot() for source in self.sources],
            "review_status": self.review_status.value,
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this risk."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class DefinitionOfDoneItem:
    """One approved completion condition, not a claim of satisfaction."""

    id: UUID
    code: str
    statement: str
    verification_method: VerificationMethod
    applicability: DefinitionOfDoneApplicability
    condition: str | None = None
    requirement_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        """Protect completion semantics and conditional applicability."""
        validate_display_code(
            self.code,
            prefix="DOD",
            label="Definition of Done code",
        )

        if (
            normalize_required_text(
                self.statement,
                label="Definition of Done statement",
                maximum_length=_MAX_STATEMENT_LENGTH,
            )
            != self.statement
        ):
            raise ValueError("Definition of Done statement must be normalized")

        normalized_condition = normalize_optional_text(
            self.condition,
            label="Definition of Done condition",
            maximum_length=_MAX_CONDITION_LENGTH,
        )

        if normalized_condition != self.condition:
            raise ValueError("Definition of Done condition must be normalized")

        if (
            self.applicability is DefinitionOfDoneApplicability.REQUIRED
            and self.condition is not None
        ):
            raise ValueError("a required Definition of Done item must not define a condition")

        if (
            self.applicability is DefinitionOfDoneApplicability.CONDITIONAL
            and self.condition is None
        ):
            raise ValueError("a conditional Definition of Done item requires a condition")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="Definition of Done requirement IDs",
            require_items=False,
        ):
            raise ValueError("Definition of Done requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic Definition of Done snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "statement": self.statement,
            "verification_method": (self.verification_method.value),
            "applicability": self.applicability.value,
            "condition": self.condition,
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this Definition of Done item."""
        return snapshot_content_hash(self.to_snapshot())


def create_acceptance_criterion(
    *,
    criterion_id: UUID,
    code: str,
    statement: str,
    verification_method: VerificationMethod,
    requirement_ids: Iterable[UUID] = (),
    user_story_ids: Iterable[UUID] = (),
) -> AcceptanceCriterion:
    """Create a normalized and traceable acceptance criterion."""
    return AcceptanceCriterion(
        id=criterion_id,
        code=code,
        statement=normalize_required_text(
            statement,
            label="acceptance-criterion statement",
            maximum_length=_MAX_STATEMENT_LENGTH,
        ),
        verification_method=verification_method,
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="acceptance-criterion requirement IDs",
            require_items=False,
        ),
        user_story_ids=canonical_uuid_tuple(
            user_story_ids,
            label="acceptance-criterion user-story IDs",
            require_items=False,
        ),
    )


def create_usage_scenario(
    *,
    scenario_id: UUID,
    code: str,
    title: str,
    actor: UserTwinVersionReference,
    preconditions: Iterable[str],
    trigger: str,
    steps: Iterable[str],
    expected_outcome: str,
    requirement_ids: Iterable[UUID],
    acceptance_criterion_ids: Iterable[UUID],
) -> UsageScenario:
    """Create a normalized scenario while preserving ordered steps."""
    return UsageScenario(
        id=scenario_id,
        code=code,
        title=normalize_required_text(
            title,
            label="scenario title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        actor=actor,
        preconditions=normalize_text_items(
            preconditions,
            label="scenario preconditions",
            maximum_item_length=_MAX_SCENARIO_STEP_LENGTH,
            require_items=False,
            require_unique=False,
        ),
        trigger=normalize_required_text(
            trigger,
            label="scenario trigger",
            maximum_length=_MAX_STATEMENT_LENGTH,
        ),
        steps=normalize_text_items(
            steps,
            label="scenario steps",
            maximum_item_length=_MAX_SCENARIO_STEP_LENGTH,
            require_items=True,
            require_unique=False,
        ),
        expected_outcome=normalize_required_text(
            expected_outcome,
            label="scenario expected outcome",
            maximum_length=_MAX_STATEMENT_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="scenario requirement IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="scenario acceptance-criterion IDs",
            require_items=True,
        ),
    )


def create_project_risk(
    *,
    risk_id: UUID,
    code: str,
    summary: str,
    likelihood: RiskLikelihood,
    impact: RiskImpact,
    mitigation: str,
    requirement_ids: Iterable[UUID],
    sources: Iterable[RequirementSourceReference],
    review_status: RiskReviewStatus = (RiskReviewStatus.PROPOSED),
) -> ProjectRisk:
    """Create a normalized and inspectably grounded project risk."""
    return ProjectRisk(
        id=risk_id,
        code=code,
        summary=normalize_required_text(
            summary,
            label="risk summary",
            maximum_length=_MAX_RISK_SUMMARY_LENGTH,
        ),
        likelihood=likelihood,
        impact=impact,
        mitigation=normalize_required_text(
            mitigation,
            label="risk mitigation",
            maximum_length=_MAX_RISK_MITIGATION_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="risk requirement IDs",
            require_items=True,
        ),
        sources=canonical_requirement_sources(
            sources,
            require_items=True,
        ),
        review_status=review_status,
    )


def create_definition_of_done_item(
    *,
    item_id: UUID,
    code: str,
    statement: str,
    verification_method: VerificationMethod,
    applicability: DefinitionOfDoneApplicability,
    condition: str | None = None,
    requirement_ids: Iterable[UUID] = (),
) -> DefinitionOfDoneItem:
    """Create a normalized Definition of Done item."""
    return DefinitionOfDoneItem(
        id=item_id,
        code=code,
        statement=normalize_required_text(
            statement,
            label="Definition of Done statement",
            maximum_length=_MAX_STATEMENT_LENGTH,
        ),
        verification_method=verification_method,
        applicability=applicability,
        condition=normalize_optional_text(
            condition,
            label="Definition of Done condition",
            maximum_length=_MAX_CONDITION_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="Definition of Done requirement IDs",
            require_items=False,
        ),
    )


__all__ = [
    "AcceptanceCriterion",
    "DefinitionOfDoneApplicability",
    "DefinitionOfDoneItem",
    "ProjectRisk",
    "RiskImpact",
    "RiskLikelihood",
    "RiskReviewStatus",
    "UsageScenario",
    "VerificationMethod",
    "create_acceptance_criterion",
    "create_definition_of_done_item",
    "create_project_risk",
    "create_usage_scenario",
]
