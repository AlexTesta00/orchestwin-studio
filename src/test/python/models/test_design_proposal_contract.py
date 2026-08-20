"""Tests for provider-independent design proposal contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.artifacts.design import (
    DesignApproach,
    create_design_alternative,
    create_design_workflow,
    create_synthetic_design_critique,
)
from orchestwin.artifacts.design_packages import (
    create_design_exploration_package,
    create_design_grounding,
)
from orchestwin.artifacts.references import (
    ArtifactKind,
    VersionedArtifactReference,
)
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignProposalIssueCode,
    DesignProposalPort,
    DesignProposalProviderKind,
    DesignProposalRequest,
    DesignProposalResult,
    DesignProposalStatus,
    DesignRequirementsInput,
    DesignUserModelingInput,
    DesignUserTwinInput,
)
from orchestwin.projects.domain import ProjectMode
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
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUIREMENTS_VERSION_ID = UUID("00000000-0000-4000-8000-000000000003")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
CREATED_AT = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)


def requirements_context(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact Requirements context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def stage_reference(
    kind: ArtifactKind,
    ordinal: int,
) -> VersionedArtifactReference:
    """Create one exact post-Requirements context reference."""
    return VersionedArtifactReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def observation() -> ProfileObservation:
    """Create one grounded User Twin goal observation."""
    return ProfileObservation(
        observation_key="user_twin.goals",
        value=ObservationValue.from_items(("Reduce booking errors",)),
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(1.0),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.PROJECT_BRIEF,
                    source_id="brief-version",
                    source_version=1,
                    content_hash="b" * 64,
                    locator="goals[0]",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )


def requirements_version() -> RequirementsSpecificationVersion:
    """Create one complete Requirements input version."""
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source,),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
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
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=requirements_context(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=requirements_context(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=requirements_context(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=REQUIREMENTS_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def proposal_request() -> DesignProposalRequest:
    """Create one complete governed design request."""
    version = requirements_version()
    specification = version.specification

    return DesignProposalRequest(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=DesignRequirementsInput(version=version),
        team=DesignAgentTeamInput(
            reference=VersionedArtifactReference(
                kind=ArtifactKind.AGENT_TEAM,
                artifact_id=specification.agent_team_reference.artifact_id,
                version_number=specification.agent_team_reference.version_number,
                content_hash=specification.agent_team_reference.content_hash,
            ),
            selected_agent_ids=(
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.UX_UI_DESIGNER,
                AgentIdentifier.QA_TEST_ENGINEER,
            ),
        ),
        user_modeling=DesignUserModelingInput(
            reference=VersionedArtifactReference(
                kind=ArtifactKind.USER_MODELING,
                artifact_id=specification.user_modeling_reference.artifact_id,
                version_number=specification.user_modeling_reference.version_number,
                content_hash=specification.user_modeling_reference.content_hash,
            ),
            user_twins=(
                DesignUserTwinInput(
                    reference=twin_reference(),
                    observations=(observation(),),
                ),
            ),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
    )


def proposed_package():
    """Create one valid provider output package without owner selection."""
    request = proposal_request()
    alternatives = []
    critiques = []

    for index, approach in (
        (1, DesignApproach.GUIDED_WORKFLOW),
        (2, DesignApproach.DASHBOARD_FIRST),
    ):
        alternative_id = UUID(int=100 + index)
        workflow = create_design_workflow(
            workflow_id=UUID(int=200 + index),
            code=f"FLOW-{index:03d}",
            title="Create a reservation",
            steps=("Review availability.", "Save the reservation."),
            requirement_ids=(REQUIREMENT_ID,),
            user_story_ids=(STORY_ID,),
        )
        alternative = create_design_alternative(
            alternative_id=alternative_id,
            code=f"DES-{index:03d}",
            approach=approach,
            title=(
                "Guided reservation workflow" if index == 1 else "Reservation operations dashboard"
            ),
            summary="Represent the approved reservation workflow.",
            rationale="Offer a reviewable design direction.",
            requirement_ids=(REQUIREMENT_ID,),
            user_story_ids=(STORY_ID,),
            acceptance_criterion_ids=(CRITERION_ID,),
            user_twin_references=(twin_reference(),),
            workflows=(workflow,),
            information_architecture=("Availability", "Reservation"),
            accessibility_considerations=("Controls have persistent labels",),
            security_considerations=("Guest data is minimized",),
            advantages=("The primary task remains visible",),
            trade_offs=("The design requires owner review",),
        )
        provenance = ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.MODEL_OUTPUT,
                    source_id="fake-design-provider:1",
                    source_version=1,
                    content_hash="d" * 64,
                    locator=f"alternatives.DES-{index:03d}",
                ),
            )
        )
        critique = create_synthetic_design_critique(
            critique_id=UUID(int=300 + index),
            code=f"CRQ-{index:03d}",
            design_alternative_id=alternative_id,
            user_twin_reference=twin_reference(),
            strengths=("The main action is visible.",),
            concerns=("The design still requires human review.",),
            provenance=provenance,
            confidence=ConfidenceScore(0.6),
            rationale="The critique is inferred from the approved User Twin.",
        )
        alternatives.append(alternative)
        critiques.append(critique)

    return create_design_exploration_package(
        project_id=PROJECT_ID,
        grounding=create_design_grounding(request.requirements.version),
        alternatives=alternatives,
        critiques=critiques,
        recommended_alternative_id=alternatives[0].id,
    )


def test_request_preserves_exact_requirements_team_and_user_modeling_context() -> None:
    """Expose all approved inputs through a deterministic provider contract."""
    request = proposal_request()
    snapshot = request.to_snapshot()

    assert request.requirements.reference.artifact_id == REQUIREMENTS_VERSION_ID
    assert snapshot["team"]["reference"]["kind"] == "AGENT_TEAM"
    assert snapshot["user_modeling"]["reference"]["kind"] == "USER_MODELING"
    assert request.user_modeling.user_twin_references == (twin_reference(),)
    assert len(request.content_hash) == 64


def test_team_input_requires_unique_fixed_catalog_order() -> None:
    """Keep the provider request aligned with the approved catalog."""
    with pytest.raises(ValueError, match="must be unique"):
        DesignAgentTeamInput(
            reference=stage_reference(ArtifactKind.AGENT_TEAM, 14),
            selected_agent_ids=(
                AgentIdentifier.UX_UI_DESIGNER,
                AgentIdentifier.UX_UI_DESIGNER,
            ),
        )

    with pytest.raises(ValueError, match="fixed-catalog order"):
        DesignAgentTeamInput(
            reference=stage_reference(ArtifactKind.AGENT_TEAM, 14),
            selected_agent_ids=(
                AgentIdentifier.QA_TEST_ENGINEER,
                AgentIdentifier.UX_UI_DESIGNER,
            ),
        )


def test_request_requires_user_twins_from_the_requirements_baseline() -> None:
    """Reject User Modeling context inconsistent with approved Requirements."""
    request = proposal_request()
    foreign_reference = replace(
        twin_reference(),
        twin_id=UUID("00000000-0000-4000-8000-000000000099"),
    )
    user_modeling = replace(
        request.user_modeling,
        user_twins=(replace(request.user_modeling.user_twins[0], reference=foreign_reference),),
    )

    with pytest.raises(ValueError, match="must match the Requirements"):
        replace(request, user_modeling=user_modeling)


def test_request_rejects_noncurrent_catalog_metadata() -> None:
    """Keep design proposals reproducible against the fixed current catalog."""
    request = proposal_request()

    with pytest.raises(ValueError, match="current agent catalog"):
        replace(request, catalog_content_hash="0" * 64)


def test_result_enforces_proposed_and_rejected_shapes() -> None:
    """Keep expected provider failures typed rather than exceptional."""
    proposed = DesignProposalResult(
        status=DesignProposalStatus.PROPOSED,
        provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-design",
        provider_version=1,
        package=proposed_package(),
    )
    rejected = DesignProposalResult(
        status=DesignProposalStatus.REJECTED,
        provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-design",
        provider_version=1,
        issue=DesignProposalIssueCode.UX_DESIGNER_REQUIRED,
    )

    assert proposed.package is not None
    assert proposed.issue is None
    assert rejected.package is None
    assert rejected.issue is DesignProposalIssueCode.UX_DESIGNER_REQUIRED
    assert len(proposed.content_hash) == 64

    with pytest.raises(ValueError, match="requires a package"):
        DesignProposalResult(
            status=DesignProposalStatus.PROPOSED,
            provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id="fake-design",
            provider_version=1,
        )


def test_design_proposal_port_is_runtime_checkable() -> None:
    """Allow composition roots to validate the provider boundary."""

    class FakePort:
        async def propose(
            self,
            request: DesignProposalRequest,
        ) -> DesignProposalResult:
            del request

            return DesignProposalResult(
                status=DesignProposalStatus.REJECTED,
                provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
                provider_id="fake-design",
                provider_version=1,
                issue=DesignProposalIssueCode.GROUNDED_INPUT_REQUIRED,
            )

    assert isinstance(FakePort(), DesignProposalPort)


def test_identical_requests_and_results_are_reproducibly_hashed() -> None:
    """Keep design provider input and output content-addressable."""
    first_request = proposal_request()
    second_request = proposal_request()
    first_result = DesignProposalResult(
        status=DesignProposalStatus.PROPOSED,
        provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-design",
        provider_version=1,
        package=proposed_package(),
    )
    second_result = DesignProposalResult(
        status=DesignProposalStatus.PROPOSED,
        provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-design",
        provider_version=1,
        package=proposed_package(),
    )

    assert first_request.to_snapshot() == second_request.to_snapshot()
    assert first_request.content_hash == second_request.content_hash
    assert first_result.to_snapshot() == second_result.to_snapshot()
    assert first_result.content_hash == second_result.content_hash
