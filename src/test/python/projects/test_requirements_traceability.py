"""Tests for typed requirements traceability and coverage."""

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
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.projects.requirements_traceability import (
    RequirementsTraceability,
    TraceabilityLink,
    TraceabilityLinkKind,
    TraceabilityNode,
    TraceabilityNodeKind,
    TraceabilityNodeReference,
    build_requirements_traceability,
    summarize_requirements_coverage,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
UNCOVERED_REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000011")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000070")
CREATED_AT = datetime(
    2026,
    8,
    17,
    13,
    0,
    tzinfo=UTC,
)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create the User Twin grounding the story and scenario."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def source() -> RequirementSourceReference:
    """Create one exact Project Brief source."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )


def specification_version(
    *,
    include_uncovered_requirement: bool = False,
) -> RequirementsSpecificationVersion:
    """Create one traceable specification-version fixture."""
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Manage reservations",
        statement=("The system must create reservations."),
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source(),),
        user_twin_references=(twin_reference(),),
    )
    requirements = [requirement]

    if include_uncovered_requirement:
        requirements.append(
            create_requirement(
                requirement_id=UNCOVERED_REQUIREMENT_ID,
                code="REQ-002",
                title="Export reservations",
                statement=("The system should export reservation data."),
                kind=RequirementKind.FUNCTIONAL,
                priority=RequirementPriority.SHOULD,
                sources=(source(),),
            )
        )

    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve the guest",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement=("A reservation receives a unique identifier."),
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save a valid reservation.",),
        expected_outcome=("The reservation can be retrieved."),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All acceptance tests pass.",
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        applicability=(DefinitionOfDoneApplicability.REQUIRED),
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
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
        requirements=requirements,
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def reference(
    kind: TraceabilityNodeKind,
    artifact_id: UUID,
) -> TraceabilityNodeReference:
    """Create one concise node reference."""
    return TraceabilityNodeReference(
        kind=kind,
        artifact_id=artifact_id,
    )


def test_traceability_contains_the_user_twin_to_acceptance_chain() -> None:
    """Expose the User Twin → story → requirement → criterion path."""
    traceability = build_requirements_traceability(specification_version())

    twin_to_story = TraceabilityLink(
        kind=TraceabilityLinkKind.ACTS_AS,
        source=reference(
            TraceabilityNodeKind.USER_TWIN,
            TWIN_ID,
        ),
        target=reference(
            TraceabilityNodeKind.USER_STORY,
            STORY_ID,
        ),
    )
    story_to_requirement = TraceabilityLink(
        kind=TraceabilityLinkKind.MOTIVATES,
        source=reference(
            TraceabilityNodeKind.USER_STORY,
            STORY_ID,
        ),
        target=reference(
            TraceabilityNodeKind.REQUIREMENT,
            REQUIREMENT_ID,
        ),
    )
    requirement_to_criterion = TraceabilityLink(
        kind=TraceabilityLinkKind.VERIFIED_BY,
        source=reference(
            TraceabilityNodeKind.REQUIREMENT,
            REQUIREMENT_ID,
        ),
        target=reference(
            TraceabilityNodeKind.ACCEPTANCE_CRITERION,
            CRITERION_ID,
        ),
    )

    assert twin_to_story in traceability.links
    assert story_to_requirement in traceability.links
    assert requirement_to_criterion in traceability.links
    assert traceability.outgoing(twin_to_story.source) == (twin_to_story,)
    assert len(traceability.content_hash) == 64


def test_coverage_reports_missing_links_without_inventing_them() -> None:
    """Keep uncovered requirements explicit in the report."""
    coverage = summarize_requirements_coverage(
        specification_version(include_uncovered_requirement=True)
    )

    assert coverage.requirement_ids_without_user_stories == (UNCOVERED_REQUIREMENT_ID,)
    assert coverage.requirement_ids_without_acceptance_criteria == (UNCOVERED_REQUIREMENT_ID,)
    assert coverage.user_story_ids_without_acceptance_criteria == ()
    assert coverage.acceptance_criterion_ids_without_scenarios == ()
    assert coverage.has_full_acceptance_coverage is False


def test_complete_acceptance_coverage_is_derived_from_existing_links() -> None:
    """Report complete acceptance coverage for a linked fixture."""
    coverage = summarize_requirements_coverage(specification_version())

    assert coverage.has_full_acceptance_coverage is True
    assert coverage.requirement_ids_without_acceptance_criteria == ()
    assert coverage.user_story_ids_without_acceptance_criteria == ()


def test_traceability_rejects_orphaned_and_semantically_invalid_links() -> None:
    """Protect graph integrity independently from the aggregate."""
    version = specification_version()
    graph = build_requirements_traceability(version)
    orphan = TraceabilityLink(
        kind=TraceabilityLinkKind.MOTIVATES,
        source=reference(
            TraceabilityNodeKind.USER_STORY,
            STORY_ID,
        ),
        target=reference(
            TraceabilityNodeKind.REQUIREMENT,
            UUID(int=999),
        ),
    )

    with pytest.raises(
        ValueError,
        match="must reference graph nodes",
    ):
        replace(
            graph,
            links=tuple(
                sorted(
                    (
                        *graph.links,
                        orphan,
                    ),
                    key=lambda link: link.sort_key,
                )
            ),
        )

    invalid = TraceabilityLink(
        kind=TraceabilityLinkKind.GOVERNS,
        source=reference(
            TraceabilityNodeKind.USER_STORY,
            STORY_ID,
        ),
        target=reference(
            TraceabilityNodeKind.REQUIREMENT,
            REQUIREMENT_ID,
        ),
    )

    with pytest.raises(
        ValueError,
        match="incompatible with its nodes",
    ):
        replace(
            graph,
            links=tuple(
                sorted(
                    (
                        *graph.links,
                        invalid,
                    ),
                    key=lambda link: link.sort_key,
                )
            ),
        )


def test_traceability_requires_unique_nodes_and_display_codes() -> None:
    """Reject ambiguous graph identities used by UI and exports."""
    version = specification_version()
    graph = build_requirements_traceability(version)
    existing = graph.nodes[0]
    duplicate_code = TraceabilityNode(
        reference=reference(
            TraceabilityNodeKind.RISK,
            UUID(int=998),
        ),
        display_code=existing.display_code,
    )

    with pytest.raises(
        ValueError,
        match="display codes must be unique",
    ):
        RequirementsTraceability(
            project_id=graph.project_id,
            specification_version_id=(graph.specification_version_id),
            specification_version_number=(graph.specification_version_number),
            specification_content_hash=(graph.specification_content_hash),
            nodes=tuple(
                sorted(
                    (
                        *graph.nodes,
                        duplicate_code,
                    ),
                    key=lambda node: node.sort_key,
                )
            ),
            links=graph.links,
        )
