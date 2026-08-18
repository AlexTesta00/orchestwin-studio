"""Tests for provider-independent requirements proposal contracts."""

from __future__ import annotations

from uuid import UUID

import pytest

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsProposalIssueCode,
    RequirementsProposalPort,
    RequirementsProposalProviderKind,
    RequirementsProposalRequest,
    RequirementsProposalResult,
    RequirementsProposalStatus,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
    RequirementsUserTwinInput,
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
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")


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
    """Create one exact User Twin version reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def observation() -> ProfileObservation:
    """Create one grounded User Twin observation."""
    return ProfileObservation(
        observation_key="user_twin.goals",
        value=ObservationValue.from_items(("Reduce booking errors",)),
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=ConfidenceScore(1.0),
        provenance=(
            ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
                        source_id="brief-version",
                        source_version=1,
                        content_hash="b" * 64,
                        locator="goals[0]",
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def request() -> RequirementsProposalRequest:
    """Create one complete provider request fixture."""
    brief = RequirementsBriefInput(
        reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        name="Hotel Operations",
        problem="Booking updates are error-prone.",
        goals=("Reduce booking errors",),
        target_users=("Hotel receptionists",),
        functional_requirements=("Create reservations",),
        definition_of_done=("Automated tests pass",),
    )
    team = RequirementsTeamInput(
        reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        selected_agent_ids=tuple(
            agent_id
            for agent_id in AgentIdentifier
            if agent_id
            in {
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.REQUIREMENTS_ANALYST,
                AgentIdentifier.QA_TEST_ENGINEER,
            }
        ),
    )
    user_modeling = RequirementsUserModelingInput(
        reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        user_twins=(
            RequirementsUserTwinInput(
                reference=twin_reference(),
                observations=(observation(),),
            ),
        ),
    )

    return RequirementsProposalRequest(
        project_id=PROJECT_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
        team=team,
        user_modeling=user_modeling,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=(AGENT_CATALOG_CONTENT_HASH),
    )


def specification():
    """Create one valid proposed requirements specification."""
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
        statement=("The system must create reservations."),
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
        steps=("Save the reservation.",),
        expected_outcome=("The reservation can be retrieved."),
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement=("All automated acceptance tests pass."),
        verification_method=(VerificationMethod.AUTOMATED_TEST),
        applicability=(DefinitionOfDoneApplicability.REQUIRED),
        requirement_ids=(REQUIREMENT_ID,),
    )
    proposal_request = request()

    return create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=(proposal_request.brief.reference),
        agent_team_reference=(proposal_request.team.reference),
        user_modeling_reference=(proposal_request.user_modeling.reference),
        catalog_version=proposal_request.catalog_version,
        catalog_content_hash=(proposal_request.catalog_content_hash),
        user_twin_references=(proposal_request.user_modeling.user_twin_references),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )


def test_request_preserves_governed_context_and_provider_inputs() -> None:
    """Expose exact Brief, Team, User Modeling, and twin content."""
    proposal_request = request()
    snapshot = proposal_request.to_snapshot()

    assert snapshot["project_id"] == str(PROJECT_ID)
    assert snapshot["brief"]["reference"]["kind"] == "PROJECT_BRIEF"
    assert snapshot["team"]["reference"]["kind"] == "AGENT_TEAM"
    assert snapshot["user_modeling"]["reference"]["kind"] == "USER_MODELING"
    assert proposal_request.user_modeling.user_twin_references == (twin_reference(),)
    assert len(proposal_request.content_hash) == 64


def test_team_input_requires_unique_fixed_catalog_order() -> None:
    """Keep requests aligned with the approved fixed catalog."""
    with pytest.raises(
        ValueError,
        match="must be unique",
    ):
        RequirementsTeamInput(
            reference=context_reference(
                RequirementsContextKind.AGENT_TEAM,
                12,
            ),
            selected_agent_ids=(
                AgentIdentifier.REQUIREMENTS_ANALYST,
                AgentIdentifier.REQUIREMENTS_ANALYST,
            ),
        )

    with pytest.raises(
        ValueError,
        match="fixed-catalog order",
    ):
        RequirementsTeamInput(
            reference=context_reference(
                RequirementsContextKind.AGENT_TEAM,
                12,
            ),
            selected_agent_ids=(
                AgentIdentifier.QA_TEST_ENGINEER,
                AgentIdentifier.REQUIREMENTS_ANALYST,
            ),
        )


def test_user_modeling_input_requires_canonical_unique_observations() -> None:
    """Prevent ambiguous User Twin evidence reaching a provider."""
    with pytest.raises(
        ValueError,
        match="observations must be unique",
    ):
        RequirementsUserTwinInput(
            reference=twin_reference(),
            observations=(
                observation(),
                observation(),
            ),
        )


def test_proposal_result_enforces_success_and_rejection_shapes() -> None:
    """Keep expected provider failures typed rather than exceptions."""
    proposed = RequirementsProposalResult(
        status=RequirementsProposalStatus.PROPOSED,
        provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id="fake-requirements",
        provider_version=1,
        specification=specification(),
    )
    rejected = RequirementsProposalResult(
        status=RequirementsProposalStatus.REJECTED,
        provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id="fake-requirements",
        provider_version=1,
        issue=(RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED),
    )

    assert proposed.specification is not None
    assert proposed.issue is None
    assert rejected.specification is None
    assert rejected.issue is (RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED)
    assert len(proposed.content_hash) == 64

    with pytest.raises(
        ValueError,
        match="requires a specification",
    ):
        RequirementsProposalResult(
            status=(RequirementsProposalStatus.PROPOSED),
            provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id="fake-requirements",
            provider_version=1,
        )


def test_requirements_proposal_port_is_runtime_checkable() -> None:
    """Allow composition roots to validate the provider boundary."""

    class FakePort:
        async def propose(
            self,
            proposal_request: RequirementsProposalRequest,
        ) -> RequirementsProposalResult:
            del proposal_request

            return RequirementsProposalResult(
                status=(RequirementsProposalStatus.REJECTED),
                provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
                provider_id="fake-requirements",
                provider_version=1,
                issue=(RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED),
            )

    assert isinstance(
        FakePort(),
        RequirementsProposalPort,
    )


def test_identical_requests_and_results_are_reproducibly_hashed() -> None:
    """Make provider inputs and outputs deterministic."""
    first_request = request()
    second_request = request()
    first_result = RequirementsProposalResult(
        status=RequirementsProposalStatus.PROPOSED,
        provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id="fake-requirements",
        provider_version=1,
        specification=specification(),
    )
    second_result = RequirementsProposalResult(
        status=RequirementsProposalStatus.PROPOSED,
        provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id="fake-requirements",
        provider_version=1,
        specification=specification(),
    )

    assert first_request.to_snapshot() == second_request.to_snapshot()
    assert first_request.content_hash == second_request.content_hash
    assert first_result.to_snapshot() == second_result.to_snapshot()
    assert first_result.content_hash == second_result.content_hash
