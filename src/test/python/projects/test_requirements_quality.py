"""Tests for acceptance, scenario, risk, and Definition of Done artifacts."""

from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    RiskImpact,
    RiskLikelihood,
    RiskReviewStatus,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_project_risk,
    create_usage_scenario,
)

REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
SECOND_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
RISK_ID = UUID("00000000-0000-4000-8000-000000000050")
DOD_ID = UUID("00000000-0000-4000-8000-000000000060")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000070")


def owner_source() -> RequirementSourceReference:
    """Create an explicit owner-provided source."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.OWNER_INPUT,
        source_id=("owner:00000000-0000-4000-8000-000000000001"),
        locator="requirements.risks",
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin actor reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def test_acceptance_criterion_is_verifiable_and_traceable() -> None:
    """Bind one verifiable criterion to stable requirement and story IDs."""
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement=("  A reservation is saved with a unique identifier. "),
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        requirement_ids=(
            SECOND_REQUIREMENT_ID,
            REQUIREMENT_ID,
        ),
        user_story_ids=(STORY_ID,),
    )

    assert criterion.statement == ("A reservation is saved with a unique identifier.")
    assert criterion.requirement_ids == (
        REQUIREMENT_ID,
        SECOND_REQUIREMENT_ID,
    )
    assert criterion.user_story_ids == (STORY_ID,)
    assert criterion.to_snapshot()["verification_method"] == "AUTOMATED_TEST"


def test_acceptance_criterion_requires_a_traceability_target() -> None:
    """Reject a criterion that verifies no requirement or user story."""
    with pytest.raises(
        ValueError,
        match="must reference a requirement or user story",
    ):
        create_acceptance_criterion(
            criterion_id=CRITERION_ID,
            code="AC-001",
            statement="A reservation is saved.",
            verification_method=(VerificationMethod.AUTOMATED_TEST),
        )


def test_usage_scenario_preserves_ordered_steps_and_exact_actor() -> None:
    """Keep scenario execution order while canonicalizing references."""
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="  Create a reservation ",
        actor=twin_reference(),
        preconditions=(" The receptionist is authenticated. ",),
        trigger=" A guest requests a room. ",
        steps=(
            "Search available rooms.",
            "Select a room.",
            "Save the reservation.",
        ),
        expected_outcome=(" The reservation is available for later retrieval. "),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )

    assert scenario.actor == twin_reference()
    assert scenario.steps == (
        "Search available rooms.",
        "Select a room.",
        "Save the reservation.",
    )
    assert scenario.preconditions == ("The receptionist is authenticated.",)


def test_usage_scenario_requires_steps_and_acceptance_links() -> None:
    """Reject a scenario that cannot exercise observable behavior."""
    with pytest.raises(
        ValueError,
        match="scenario steps must not be empty",
    ):
        create_usage_scenario(
            scenario_id=SCENARIO_ID,
            code="SCN-001",
            title="Create a reservation",
            actor=twin_reference(),
            preconditions=(),
            trigger="A guest requests a room.",
            steps=(),
            expected_outcome="The reservation is stored.",
            requirement_ids=(REQUIREMENT_ID,),
            acceptance_criterion_ids=(CRITERION_ID,),
        )


def test_project_risk_preserves_likelihood_impact_and_owner_review_state() -> None:
    """Keep risk severity and owner acknowledgement distinct."""
    risk = create_project_risk(
        risk_id=RISK_ID,
        code="RSK-001",
        summary=(" Duplicate bookings may be created during concurrent updates. "),
        likelihood=RiskLikelihood.POSSIBLE,
        impact=RiskImpact.HIGH,
        mitigation=" Use transactional uniqueness checks. ",
        requirement_ids=(REQUIREMENT_ID,),
        sources=(owner_source(),),
        review_status=RiskReviewStatus.OWNER_ACKNOWLEDGED,
    )

    assert risk.likelihood is RiskLikelihood.POSSIBLE
    assert risk.impact is RiskImpact.HIGH
    assert risk.review_status is RiskReviewStatus.OWNER_ACKNOWLEDGED
    assert risk.sources == (owner_source(),)


def test_definition_of_done_distinguishes_required_and_conditional_items() -> None:
    """Represent applicability without claiming that an item is satisfied."""
    required = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement=" All automated tests pass. ",
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        applicability=(DefinitionOfDoneApplicability.REQUIRED),
    )
    conditional = create_definition_of_done_item(
        item_id=UUID("00000000-0000-4000-8000-000000000061"),
        code="DOD-002",
        statement="Accessibility findings are resolved.",
        verification_method=VerificationMethod.INSPECTION,
        applicability=(DefinitionOfDoneApplicability.CONDITIONAL),
        condition=(" The delivered interface contains interactive UI. "),
        requirement_ids=(REQUIREMENT_ID,),
    )

    assert required.condition is None
    assert conditional.condition == ("The delivered interface contains interactive UI.")
    assert "satisfied" not in required.to_snapshot()


@pytest.mark.parametrize(
    (
        "applicability",
        "condition",
        "expected_message",
    ),
    (
        (
            DefinitionOfDoneApplicability.REQUIRED,
            "Only for web projects.",
            "must not define a condition",
        ),
        (
            DefinitionOfDoneApplicability.CONDITIONAL,
            None,
            "requires a condition",
        ),
    ),
)
def test_definition_of_done_enforces_applicability_shape(
    applicability: DefinitionOfDoneApplicability,
    condition: str | None,
    expected_message: str,
) -> None:
    """Reject contradictory Definition of Done applicability metadata."""
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        create_definition_of_done_item(
            item_id=DOD_ID,
            code="DOD-001",
            statement="All automated tests pass.",
            verification_method=(VerificationMethod.AUTOMATED_TEST),
            applicability=applicability,
            condition=condition,
        )


def test_quality_artifact_hashes_are_stable() -> None:
    """Keep downstream artifact identities deterministic."""
    first = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation is saved.",
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        requirement_ids=(
            SECOND_REQUIREMENT_ID,
            REQUIREMENT_ID,
        ),
    )
    second = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation is saved.",
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        requirement_ids=(
            REQUIREMENT_ID,
            SECOND_REQUIREMENT_ID,
        ),
    )

    assert first.to_snapshot() == second.to_snapshot()
    assert first.content_hash == second.content_hash
