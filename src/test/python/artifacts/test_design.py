"""Tests for immutable design alternatives and synthetic critiques."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts.design import (
    DesignApproach,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
)

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
SECOND_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000040")
WORKFLOW_ID = UUID("00000000-0000-4000-8000-000000000050")
ALTERNATIVE_ID = UUID("00000000-0000-4000-8000-000000000060")
CRITIQUE_ID = UUID("00000000-0000-4000-8000-000000000070")


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def provenance() -> ObservationProvenance:
    """Create explicit synthetic-feedback provenance."""
    return ObservationProvenance.from_references(
        (
            EvidenceReference(
                source_kind=EvidenceSourceKind.MODEL_OUTPUT,
                source_id="fake-design-provider:1",
                source_version=1,
                content_hash="b" * 64,
                locator="alternatives.DES-001.critiques.UT-001",
                summary="Deterministic synthetic User Twin critique.",
            ),
        )
    )


def workflow():
    """Create one normalized design workflow."""
    return create_design_workflow(
        workflow_id=WORKFLOW_ID,
        code="FLOW-001",
        title="  Create   reservation ",
        steps=(
            " Search available rooms. ",
            "Select a room.",
            "Save the reservation.",
        ),
        requirement_ids=(SECOND_REQUIREMENT_ID, REQUIREMENT_ID),
        user_story_ids=(STORY_ID,),
    )


def alternative():
    """Create one complete design alternative."""
    return create_design_alternative(
        alternative_id=ALTERNATIVE_ID,
        code="DES-001",
        approach=DesignApproach.GUIDED_WORKFLOW,
        title=" Guided reservation workflow ",
        summary=" A step-by-step reservation experience. ",
        rationale="Reduce errors by exposing one decision at a time.",
        requirement_ids=(SECOND_REQUIREMENT_ID, REQUIREMENT_ID),
        user_story_ids=(STORY_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
        user_twin_references=(twin_reference(),),
        workflows=(workflow(),),
        information_architecture=(
            "Availability search",
            "Reservation details",
            "Confirmation",
        ),
        accessibility_considerations=("Every form control has a persistent label",),
        security_considerations=("Sensitive guest data is not exposed in summaries",),
        advantages=("Reduces cognitive load",),
        trade_offs=("Requires more navigation steps",),
        assumptions=("Receptionists prefer guided data entry",),
        open_questions=("Should room comparison remain visible?",),
    )


def test_design_alternative_is_normalized_traceable_and_hashable() -> None:
    """Create one deterministic alternative from unordered input."""
    value = alternative()

    assert value.title == "Guided reservation workflow"
    assert value.requirement_ids == (
        REQUIREMENT_ID,
        SECOND_REQUIREMENT_ID,
    )
    assert value.workflows == (workflow(),)
    assert value.user_twin_references == (twin_reference(),)
    assert len(value.content_hash) == 64


def test_design_workflows_must_remain_inside_alternative_scope() -> None:
    """Reject workflows that reference requirements absent from the alternative."""
    value = alternative()
    foreign_requirement = UUID("00000000-0000-4000-8000-000000000099")
    invalid_workflow = replace(
        workflow(),
        requirement_ids=(foreign_requirement,),
    )

    with pytest.raises(
        ValueError,
        match="unknown requirement references",
    ):
        replace(
            value,
            workflows=(invalid_workflow,),
        )


def test_synthetic_critique_is_explicitly_model_inferred_and_review_required() -> None:
    """Prevent synthetic feedback from being represented as empirical evidence."""
    critique = create_synthetic_design_critique(
        critique_id=CRITIQUE_ID,
        code="CRQ-001",
        design_alternative_id=ALTERNATIVE_ID,
        user_twin_reference=twin_reference(),
        strengths=("The workflow exposes a clear next action.",),
        concerns=("Repeated navigation may slow expert users.",),
        accessibility_observations=("Focus order must follow the workflow.",),
        suggested_changes=("Add a compact expert mode later.",),
        provenance=provenance(),
        confidence=ConfidenceScore(0.65),
        rationale="The feedback is inferred from the approved User Twin profile.",
    )

    assert critique.epistemic_status is EpistemicStatus.MODEL_INFERRED
    assert critique.human_validation is HumanValidationRequirement.REQUIRED
    assert critique.requires_human_validation is True
    assert critique.to_snapshot()["kind"] == "SYNTHETIC_USER_TWIN"


@pytest.mark.parametrize(
    ("epistemic_status", "human_validation", "expected_message"),
    (
        (
            EpistemicStatus.EMPIRICALLY_SUPPORTED,
            HumanValidationRequirement.REQUIRED,
            "must remain MODEL_INFERRED",
        ),
        (
            EpistemicStatus.MODEL_INFERRED,
            HumanValidationRequirement.NOT_REQUIRED,
            "requires human validation",
        ),
    ),
)
def test_synthetic_critique_rejects_epistemic_overclaiming(
    epistemic_status: EpistemicStatus,
    human_validation: HumanValidationRequirement,
    expected_message: str,
) -> None:
    """Reject empirical or validation-free synthetic critique states."""
    critique = create_synthetic_design_critique(
        critique_id=CRITIQUE_ID,
        code="CRQ-001",
        design_alternative_id=ALTERNATIVE_ID,
        user_twin_reference=twin_reference(),
        strengths=("The primary action is visible.",),
        concerns=("The workflow may be slower for experts.",),
        provenance=provenance(),
        confidence=ConfidenceScore(0.65),
        rationale="This is synthetic feedback.",
    )

    with pytest.raises(ValueError, match=expected_message):
        replace(
            critique,
            epistemic_status=epistemic_status,
            human_validation=human_validation,
        )


def test_identical_alternatives_have_identical_snapshots_and_hashes() -> None:
    """Keep design output reproducible for equal typed input."""
    first = alternative()
    second = alternative()

    assert first.to_snapshot() == second.to_snapshot()
    assert first.canonical_json() == second.canonical_json()
    assert first.content_hash == second.content_hash
