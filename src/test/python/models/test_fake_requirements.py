"""Tests for deterministic requirements proposal generation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.models.fake_requirements import (
    FAKE_REQUIREMENTS_PROVIDER_ID,
    FAKE_REQUIREMENTS_PROVIDER_VERSION,
    FakeDeterministicRequirementsAdapter,
)
from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsProposalIssueCode,
    RequirementsProposalProviderKind,
    RequirementsProposalRequest,
    RequirementsProposalStatus,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
    RequirementsUserTwinInput,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.requirements import (
    RequirementKind,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
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
TWIN_ID = UUID("00000000-0000-4000-8000-000000000010")


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed input reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=2,
        content_hash=(f"{ordinal:x}" * 64),
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=3,
        content_hash="a" * 64,
        name=("Hotel Receptionist Twin"),
    )


def observation(
    key: str,
    value: ObservationValue,
) -> ProfileObservation:
    """Create one grounded User Twin observation."""
    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=(ConfidenceScore(1.0)),
        provenance=(
            ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
                        source_id=("brief-version"),
                        source_version=2,
                        content_hash=("b" * 64),
                        locator=key,
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def proposal_request() -> RequirementsProposalRequest:
    """Create one complete deterministic proposal request."""
    return RequirementsProposalRequest(
        project_id=PROJECT_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=RequirementsBriefInput(
            reference=context_reference(
                RequirementsContextKind.PROJECT_BRIEF,
                11,
            ),
            name="Hotel Operations",
            problem=("Reservation updates are error-prone."),
            goals=("Reduce booking errors",),
            target_users=("Hotel receptionists",),
            technical_constraints=("Use PostgreSQL",),
            functional_requirements=(
                ("Create and update reservations"),
                "Search room availability",
            ),
            non_functional_requirements=(("Reservation searches respond promptly"),),
            risks=(("Concurrent updates may create conflicts"),),
            definition_of_done=("All automated tests pass",),
        ),
        team=RequirementsTeamInput(
            reference=context_reference(
                RequirementsContextKind.AGENT_TEAM,
                12,
            ),
            selected_agent_ids=(
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.REQUIREMENTS_ANALYST,
                AgentIdentifier.QA_TEST_ENGINEER,
            ),
        ),
        user_modeling=(
            RequirementsUserModelingInput(
                reference=context_reference(
                    RequirementsContextKind.USER_MODELING,
                    13,
                ),
                user_twins=(
                    RequirementsUserTwinInput(
                        reference=(twin_reference()),
                        observations=(
                            observation(
                                "user_twin.goals",
                                (ObservationValue.from_items(("Reduce booking errors",))),
                            ),
                            observation(
                                "user_twin.role",
                                (ObservationValue.from_text("Hotel receptionist")),
                            ),
                        ),
                    ),
                ),
            )
        ),
        catalog_version=(AGENT_CATALOG_VERSION),
        catalog_content_hash=(AGENT_CATALOG_CONTENT_HASH),
    )


def propose(
    request: RequirementsProposalRequest,
):
    """Run the fake adapter synchronously for concise tests."""
    return asyncio.run(FakeDeterministicRequirementsAdapter().propose(request))


def test_fake_proposal_is_reproducible_and_explicitly_identified() -> None:
    """Return identical provider output for identical governed input."""
    request = proposal_request()

    first = propose(request)
    second = propose(request)

    assert first.status is (RequirementsProposalStatus.PROPOSED)
    assert first.provider_kind is (RequirementsProposalProviderKind.FAKE_DETERMINISTIC)
    assert first.provider_id == (FAKE_REQUIREMENTS_PROVIDER_ID)
    assert first.provider_version == (FAKE_REQUIREMENTS_PROVIDER_VERSION)
    assert first == second
    assert first.content_hash == second.content_hash


def test_fake_proposal_preserves_exact_context_and_brief_sources() -> None:
    """Ground every generated requirement in exact governed inputs."""
    request = proposal_request()
    result = propose(request)

    assert result.specification is not None

    specification = result.specification

    assert specification.project_brief_reference == request.brief.reference
    assert specification.agent_team_reference == request.team.reference
    assert specification.user_modeling_reference == request.user_modeling.reference
    assert specification.user_twin_references == (twin_reference(),)
    assert tuple(value.kind for value in specification.requirements) == (
        RequirementKind.FUNCTIONAL,
        RequirementKind.FUNCTIONAL,
        RequirementKind.NON_FUNCTIONAL,
        RequirementKind.CONSTRAINT,
    )

    for requirement in specification.requirements:
        source = requirement.sources[0]

        assert source.source_id == str(request.brief.reference.artifact_id)
        assert source.source_version == (request.brief.reference.version_number)
        assert source.content_hash == (request.brief.reference.content_hash)


def test_fake_proposal_creates_traceable_stories_criteria_and_scenarios() -> None:
    """Create reviewable downstream artifacts without losing stable links."""
    result = propose(proposal_request())

    assert result.specification is not None

    specification = result.specification
    story = specification.user_stories[0]
    scenario = specification.scenarios[0]

    assert story.user_twin_reference == twin_reference()
    assert story.goal == ("Reduce booking errors")
    assert story.requirement_ids
    assert all(criterion.requirement_ids for criterion in specification.acceptance_criteria)
    assert scenario.actor == twin_reference()
    assert scenario.requirement_ids == story.requirement_ids
    assert scenario.acceptance_criterion_ids
    assert specification.risks[0].summary == ("Concurrent updates may create conflicts")
    assert specification.definition_of_done[0].statement == "All automated tests pass"


def test_fake_proposal_rejects_a_team_without_requirements_analyst() -> None:
    """Require the approved specialist role before proposal generation."""
    request = proposal_request()
    team = replace(
        request.team,
        selected_agent_ids=(
            AgentIdentifier.WORKFLOW_ORCHESTRATOR,
            AgentIdentifier.QA_TEST_ENGINEER,
        ),
    )

    result = propose(
        replace(
            request,
            team=team,
        )
    )

    assert result.status is (RequirementsProposalStatus.REJECTED)
    assert result.issue is (RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED)
    assert result.specification is None


def test_fake_proposal_rejects_missing_requirement_grounding() -> None:
    """Do not invent requirements when the governed Brief has none."""
    request = proposal_request()
    brief = replace(
        request.brief,
        technical_constraints=(),
        functional_requirements=(),
        non_functional_requirements=(),
    )

    result = propose(
        replace(
            request,
            brief=brief,
        )
    )

    assert result.status is (RequirementsProposalStatus.REJECTED)
    assert result.issue is (RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED)
    assert result.specification is None
