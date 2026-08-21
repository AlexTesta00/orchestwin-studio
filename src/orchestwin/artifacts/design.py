"""Immutable design alternatives and synthetic User Twin critiques."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    canonical_uuid_tuple,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    HumanValidationRequirement,
    ObservationProvenance,
)

_MAX_TITLE_LENGTH: Final = 200
_MAX_SUMMARY_LENGTH: Final = 3000
_MAX_RATIONALE_LENGTH: Final = 4000
_MAX_ITEM_LENGTH: Final = 2000
_MAX_CRITIQUE_RATIONALE_LENGTH: Final = 2000


class DesignApproach(StrEnum):
    """High-level strategies used to distinguish design alternatives."""

    GUIDED_WORKFLOW = "GUIDED_WORKFLOW"
    DASHBOARD_FIRST = "DASHBOARD_FIRST"
    TASK_FOCUSED = "TASK_FOCUSED"
    INFORMATION_RICH = "INFORMATION_RICH"


class DesignCritiqueKind(StrEnum):
    """Explicit classification of generated design feedback."""

    SYNTHETIC_USER_TWIN = "SYNTHETIC_USER_TWIN"


@dataclass(frozen=True, slots=True)
class DesignWorkflow:
    """One ordered workflow represented by a design alternative."""

    id: UUID
    code: str
    title: str
    steps: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect identity, ordered steps, and traceability."""
        validate_display_code(
            self.code,
            prefix="FLOW",
            label="design workflow code",
        )

        if (
            normalize_required_text(
                self.title,
                label="design workflow title",
                maximum_length=_MAX_TITLE_LENGTH,
            )
            != self.title
        ):
            raise ValueError("design workflow title must be normalized")

        if self.steps != normalize_text_items(
            self.steps,
            label="design workflow steps",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
            require_unique=False,
        ):
            raise ValueError("design workflow steps must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="design workflow requirement IDs",
            require_items=True,
        ):
            raise ValueError("design workflow requirement IDs must use canonical order")

        if self.user_story_ids != canonical_uuid_tuple(
            self.user_story_ids,
            label="design workflow user-story IDs",
            require_items=True,
        ):
            raise ValueError("design workflow user-story IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic workflow snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "steps": list(self.steps),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
        }


@dataclass(frozen=True, slots=True)
class DesignAlternative:
    """One inspectable and traceable design direction."""

    id: UUID
    code: str
    approach: DesignApproach
    title: str
    summary: str
    rationale: str
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReference, ...]
    workflows: tuple[DesignWorkflow, ...]
    information_architecture: tuple[str, ...]
    accessibility_considerations: tuple[str, ...]
    security_considerations: tuple[str, ...]
    advantages: tuple[str, ...]
    trade_offs: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect canonical content and internal traceability."""
        validate_display_code(
            self.code,
            prefix="DES",
            label="design alternative code",
        )

        for value, label, maximum_length in (
            (self.title, "design alternative title", _MAX_TITLE_LENGTH),
            (self.summary, "design alternative summary", _MAX_SUMMARY_LENGTH),
            (self.rationale, "design alternative rationale", _MAX_RATIONALE_LENGTH),
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

        for values, label, require_items in (
            (self.requirement_ids, "design alternative requirement IDs", True),
            (self.user_story_ids, "design alternative user-story IDs", True),
            (
                self.acceptance_criterion_ids,
                "design alternative acceptance-criterion IDs",
                True,
            ),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must use canonical order")

        if self.user_twin_references != canonical_user_twin_references(
            self.user_twin_references,
            require_items=True,
        ):
            raise ValueError("design alternative User Twin references must use canonical order")

        expected_workflows = _canonical_workflows(self.workflows)

        if self.workflows != expected_workflows:
            raise ValueError("design workflows must use canonical code order")

        for values, label, require_items, require_unique in (
            (
                self.information_architecture,
                "design information architecture",
                True,
                True,
            ),
            (
                self.accessibility_considerations,
                "design accessibility considerations",
                True,
                True,
            ),
            (
                self.security_considerations,
                "design security considerations",
                True,
                True,
            ),
            (self.advantages, "design advantages", True, True),
            (self.trade_offs, "design trade-offs", True, True),
            (self.assumptions, "design assumptions", False, True),
            (self.open_questions, "design open questions", False, True),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
                require_unique=require_unique,
            ):
                raise ValueError(f"{label} must be normalized")

        requirement_ids = frozenset(self.requirement_ids)
        user_story_ids = frozenset(self.user_story_ids)

        for workflow in self.workflows:
            if not frozenset(workflow.requirement_ids).issubset(requirement_ids):
                raise ValueError("design workflows contain unknown requirement references")

            if not frozenset(workflow.user_story_ids).issubset(user_story_ids):
                raise ValueError("design workflows contain unknown user-story references")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic alternative snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "approach": self.approach.value,
            "title": self.title,
            "summary": self.summary,
            "rationale": self.rationale,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "user_twin_references": [
                reference.to_snapshot() for reference in self.user_twin_references
            ],
            "workflows": [workflow.to_snapshot() for workflow in self.workflows],
            "information_architecture": list(self.information_architecture),
            "accessibility_considerations": list(self.accessibility_considerations),
            "security_considerations": list(self.security_considerations),
            "advantages": list(self.advantages),
            "trade_offs": list(self.trade_offs),
            "assumptions": list(self.assumptions),
            "open_questions": list(self.open_questions),
        }

    def canonical_json(self) -> str:
        """Serialize this alternative deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this alternative."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class SyntheticDesignCritique:
    """Synthetic User Twin feedback that never claims empirical status."""

    id: UUID
    code: str
    design_alternative_id: UUID
    user_twin_reference: UserTwinVersionReference
    strengths: tuple[str, ...]
    concerns: tuple[str, ...]
    unmet_needs: tuple[str, ...]
    accessibility_observations: tuple[str, ...]
    trust_concerns: tuple[str, ...]
    questions: tuple[str, ...]
    suggested_changes: tuple[str, ...]
    provenance: ObservationProvenance
    confidence: ConfidenceScore
    epistemic_status: EpistemicStatus
    human_validation: HumanValidationRequirement
    rationale: str
    kind: DesignCritiqueKind = DesignCritiqueKind.SYNTHETIC_USER_TWIN

    def __post_init__(self) -> None:
        """Protect explicit synthetic and review-required semantics."""
        validate_display_code(
            self.code,
            prefix="CRQ",
            label="design critique code",
        )

        for values, label, require_items in (
            (self.strengths, "design critique strengths", True),
            (self.concerns, "design critique concerns", True),
            (self.unmet_needs, "design critique unmet needs", False),
            (
                self.accessibility_observations,
                "design critique accessibility observations",
                False,
            ),
            (self.trust_concerns, "design critique trust concerns", False),
            (self.questions, "design critique questions", False),
            (self.suggested_changes, "design critique suggested changes", False),
        ):
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_ITEM_LENGTH,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must be normalized")

        if (
            normalize_required_text(
                self.rationale,
                label="design critique rationale",
                maximum_length=_MAX_CRITIQUE_RATIONALE_LENGTH,
            )
            != self.rationale
        ):
            raise ValueError("design critique rationale must be normalized")

        if self.kind is not DesignCritiqueKind.SYNTHETIC_USER_TWIN:
            raise ValueError("design critique must be explicitly synthetic")

        if self.epistemic_status is not EpistemicStatus.MODEL_INFERRED:
            raise ValueError("synthetic design critique must remain MODEL_INFERRED")

        if self.human_validation is not HumanValidationRequirement.REQUIRED:
            raise ValueError("synthetic design critique requires human validation")

    @property
    def requires_human_validation(self) -> bool:
        """Return the mandatory validation state of synthetic feedback."""
        return True

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic synthetic-critique snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "kind": self.kind.value,
            "design_alternative_id": str(self.design_alternative_id),
            "user_twin_reference": self.user_twin_reference.to_snapshot(),
            "strengths": list(self.strengths),
            "concerns": list(self.concerns),
            "unmet_needs": list(self.unmet_needs),
            "accessibility_observations": list(self.accessibility_observations),
            "trust_concerns": list(self.trust_concerns),
            "questions": list(self.questions),
            "suggested_changes": list(self.suggested_changes),
            "provenance": self.provenance.to_snapshot(),
            "confidence": self.confidence.to_snapshot(),
            "epistemic_status": self.epistemic_status.value,
            "human_validation": self.human_validation.value,
            "rationale": self.rationale,
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this critique."""
        return snapshot_content_hash(self.to_snapshot())


def _canonical_workflows(
    values: Iterable[DesignWorkflow],
) -> tuple[DesignWorkflow, ...]:
    """Return identity-safe workflows in stable code order."""
    workflows = tuple(values)

    if not workflows:
        raise ValueError("design workflows must not be empty")

    ids = tuple(workflow.id for workflow in workflows)
    codes = tuple(workflow.code for workflow in workflows)

    if len(ids) != len(set(ids)):
        raise ValueError("design workflow identities must be unique")

    if len(codes) != len(set(codes)):
        raise ValueError("design workflow codes must be unique")

    return tuple(sorted(workflows, key=lambda workflow: workflow.code))


def create_design_workflow(
    *,
    workflow_id: UUID,
    code: str,
    title: str,
    steps: Iterable[str],
    requirement_ids: Iterable[UUID],
    user_story_ids: Iterable[UUID],
) -> DesignWorkflow:
    """Create a normalized workflow with canonical references."""
    return DesignWorkflow(
        id=workflow_id,
        code=code,
        title=normalize_required_text(
            title,
            label="design workflow title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        steps=normalize_text_items(
            steps,
            label="design workflow steps",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
            require_unique=False,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="design workflow requirement IDs",
            require_items=True,
        ),
        user_story_ids=canonical_uuid_tuple(
            user_story_ids,
            label="design workflow user-story IDs",
            require_items=True,
        ),
    )


def create_design_alternative(
    *,
    alternative_id: UUID,
    code: str,
    approach: DesignApproach,
    title: str,
    summary: str,
    rationale: str,
    requirement_ids: Iterable[UUID],
    user_story_ids: Iterable[UUID],
    acceptance_criterion_ids: Iterable[UUID],
    user_twin_references: Iterable[UserTwinVersionReference],
    workflows: Iterable[DesignWorkflow],
    information_architecture: Iterable[str],
    accessibility_considerations: Iterable[str],
    security_considerations: Iterable[str],
    advantages: Iterable[str],
    trade_offs: Iterable[str],
    assumptions: Iterable[str] = (),
    open_questions: Iterable[str] = (),
) -> DesignAlternative:
    """Create a normalized and deterministic design alternative."""
    return DesignAlternative(
        id=alternative_id,
        code=code,
        approach=approach,
        title=normalize_required_text(
            title,
            label="design alternative title",
            maximum_length=_MAX_TITLE_LENGTH,
        ),
        summary=normalize_required_text(
            summary,
            label="design alternative summary",
            maximum_length=_MAX_SUMMARY_LENGTH,
        ),
        rationale=normalize_required_text(
            rationale,
            label="design alternative rationale",
            maximum_length=_MAX_RATIONALE_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="design alternative requirement IDs",
            require_items=True,
        ),
        user_story_ids=canonical_uuid_tuple(
            user_story_ids,
            label="design alternative user-story IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            acceptance_criterion_ids,
            label="design alternative acceptance-criterion IDs",
            require_items=True,
        ),
        user_twin_references=canonical_user_twin_references(
            user_twin_references,
            require_items=True,
        ),
        workflows=_canonical_workflows(workflows),
        information_architecture=normalize_text_items(
            information_architecture,
            label="design information architecture",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        accessibility_considerations=normalize_text_items(
            accessibility_considerations,
            label="design accessibility considerations",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        security_considerations=normalize_text_items(
            security_considerations,
            label="design security considerations",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        advantages=normalize_text_items(
            advantages,
            label="design advantages",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        trade_offs=normalize_text_items(
            trade_offs,
            label="design trade-offs",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        assumptions=normalize_text_items(
            assumptions,
            label="design assumptions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        open_questions=normalize_text_items(
            open_questions,
            label="design open questions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
    )


def create_synthetic_design_critique(
    *,
    critique_id: UUID,
    code: str,
    design_alternative_id: UUID,
    user_twin_reference: UserTwinVersionReference,
    strengths: Iterable[str],
    concerns: Iterable[str],
    provenance: ObservationProvenance,
    confidence: ConfidenceScore,
    rationale: str,
    unmet_needs: Iterable[str] = (),
    accessibility_observations: Iterable[str] = (),
    trust_concerns: Iterable[str] = (),
    questions: Iterable[str] = (),
    suggested_changes: Iterable[str] = (),
) -> SyntheticDesignCritique:
    """Create explicitly synthetic, model-inferred design feedback."""
    return SyntheticDesignCritique(
        id=critique_id,
        code=code,
        design_alternative_id=design_alternative_id,
        user_twin_reference=user_twin_reference,
        strengths=normalize_text_items(
            strengths,
            label="design critique strengths",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        concerns=normalize_text_items(
            concerns,
            label="design critique concerns",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=True,
        ),
        unmet_needs=normalize_text_items(
            unmet_needs,
            label="design critique unmet needs",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        accessibility_observations=normalize_text_items(
            accessibility_observations,
            label="design critique accessibility observations",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        trust_concerns=normalize_text_items(
            trust_concerns,
            label="design critique trust concerns",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        questions=normalize_text_items(
            questions,
            label="design critique questions",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        suggested_changes=normalize_text_items(
            suggested_changes,
            label="design critique suggested changes",
            maximum_item_length=_MAX_ITEM_LENGTH,
            require_items=False,
        ),
        provenance=provenance,
        confidence=confidence,
        epistemic_status=EpistemicStatus.MODEL_INFERRED,
        human_validation=HumanValidationRequirement.REQUIRED,
        rationale=normalize_required_text(
            rationale,
            label="design critique rationale",
            maximum_length=_MAX_CRITIQUE_RATIONALE_LENGTH,
        ),
    )


__all__ = [
    "DesignAlternative",
    "DesignApproach",
    "DesignCritiqueKind",
    "DesignWorkflow",
    "SyntheticDesignCritique",
    "create_design_alternative",
    "create_design_workflow",
    "create_synthetic_design_critique",
]
