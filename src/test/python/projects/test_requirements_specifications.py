"""Tests for immutable versioned requirements specifications."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    RiskImpact,
    RiskLikelihood,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_project_risk,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
    create_requirements_specification,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
SECOND_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
RISK_ID = UUID("00000000-0000-4000-8000-000000000050")
DOD_ID = UUID("00000000-0000-4000-8000-000000000060")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000070")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000080")
CREATED_AT = datetime(
    2026,
    8,
    17,
    12,
    0,
    tzinfo=UTC,
)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create an exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create the exact User Twin used by the specification."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def brief_source() -> RequirementSourceReference:
    """Create one Project Brief requirement source."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )


def build_specification() -> RequirementsSpecification:
    """Create one complete valid requirements specification."""
    primary_requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Manage reservations",
        statement=("The system must create and update reservations."),
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(brief_source(),),
        user_twin_references=(twin_reference(),),
    )
    constraint = create_requirement(
        requirement_id=SECOND_REQUIREMENT_ID,
        code="REQ-002",
        title="Protect concurrent updates",
        statement=("Reservation updates must preserve consistency."),
        kind=RequirementKind.CONSTRAINT,
        priority=RequirementPriority.MUST,
        sources=(brief_source(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest without double booking",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement=("A valid reservation receives a unique identifier."),
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=("The receptionist is authenticated.",),
        trigger="A guest requests a room.",
        steps=(
            "Search available rooms.",
            "Select a room.",
            "Save the reservation.",
        ),
        expected_outcome=("The reservation can be retrieved by its identifier."),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    risk = create_project_risk(
        risk_id=RISK_ID,
        code="RSK-001",
        summary=("Concurrent updates may create duplicate bookings."),
        likelihood=RiskLikelihood.POSSIBLE,
        impact=RiskImpact.HIGH,
        mitigation=("Use transactional uniqueness checks."),
        requirement_ids=(SECOND_REQUIREMENT_ID,),
        sources=(brief_source(),),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement=("All automated acceptance tests pass."),
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        applicability=(DefinitionOfDoneApplicability.REQUIRED),
        requirement_ids=(REQUIREMENT_ID,),
    )

    return create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(
            constraint,
            primary_requirement,
        ),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(risk,),
        definition_of_done=(done,),
    )


def test_specification_canonicalizes_artifacts_and_hashes_complete_content() -> None:
    """Create a deterministic baseline from all requirement artifacts."""
    specification = build_specification()

    assert tuple(value.code for value in specification.requirements) == (
        "REQ-001",
        "REQ-002",
    )
    assert specification.user_twin_references == (twin_reference(),)
    assert specification.to_snapshot()["schema_version"] == 1
    assert len(specification.content_hash) == 64


def test_specification_rejects_orphaned_links() -> None:
    """Reject downstream artifacts referencing absent requirements."""
    specification = build_specification()
    story = replace(
        specification.user_stories[0],
        requirement_ids=(UUID(int=999),),
    )

    with pytest.raises(
        ValueError,
        match=("user-story requirement IDs contain unknown references"),
    ):
        replace(
            specification,
            user_stories=(story,),
        )


def test_specification_rejects_user_twins_outside_the_governed_snapshot() -> None:
    """Keep every requirement actor inside the User Modeling context."""
    specification = build_specification()
    foreign_twin = UserTwinVersionReference(
        twin_id=UUID(int=999),
        version_number=1,
        content_hash="d" * 64,
        name="Foreign Twin",
    )
    story = replace(
        specification.user_stories[0],
        user_twin_reference=foreign_twin,
    )

    with pytest.raises(
        ValueError,
        match="User Twin in the specification",
    ):
        replace(
            specification,
            user_stories=(story,),
        )


def test_context_references_must_use_the_expected_kinds() -> None:
    """Do not confuse governed Brief, Team, and User Modeling inputs."""
    specification = build_specification()

    with pytest.raises(
        ValueError,
        match=("Project Brief reference uses the wrong context kind"),
    ):
        replace(
            specification,
            project_brief_reference=context_reference(
                RequirementsContextKind.AGENT_TEAM,
                11,
            ),
        )


def test_specification_version_requires_matching_hash_and_linear_lineage() -> None:
    """Bind each immutable version to one complete specification."""
    specification = build_specification()
    version = RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )

    assert version.to_snapshot()["version_number"] == 1
    assert version.based_on_version_number is None

    with pytest.raises(
        ValueError,
        match="hash must match",
    ):
        replace(
            version,
            content_hash="0" * 64,
        )

    with pytest.raises(
        ValueError,
        match="immediately preceding version",
    ):
        replace(
            version,
            version_number=2,
            based_on_version_number=None,
        )


def test_specification_hash_is_independent_from_input_collection_order() -> None:
    """Keep semantically identical specifications content-addressable."""
    first = build_specification()
    second = create_requirements_specification(
        project_id=first.project_id,
        project_brief_reference=(first.project_brief_reference),
        agent_team_reference=(first.agent_team_reference),
        user_modeling_reference=(first.user_modeling_reference),
        catalog_version=first.catalog_version,
        catalog_content_hash=(first.catalog_content_hash),
        user_twin_references=reversed(first.user_twin_references),
        requirements=reversed(first.requirements),
        user_stories=reversed(first.user_stories),
        acceptance_criteria=reversed(first.acceptance_criteria),
        scenarios=reversed(first.scenarios),
        risks=reversed(first.risks),
        definition_of_done=reversed(first.definition_of_done),
    )

    assert first.to_snapshot() == second.to_snapshot()
    assert first.content_hash == second.content_hash
