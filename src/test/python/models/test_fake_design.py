"""Tests for deterministic governed design proposal generation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.models import fake_design
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignProposalIssueCode,
    DesignProposalProviderKind,
    DesignProposalRequest,
    DesignProposalStatus,
    DesignRequirementsInput,
    DesignUserModelingInput,
    DesignUserTwinInput,
)
from orchestwin.models.fake_design import (
    FAKE_DESIGN_PROVIDER_ID,
    FAKE_DESIGN_PROVIDER_VERSION,
    FakeDeterministicDesignAdapter,
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
STORY_ONE_ID = UUID("00000000-0000-4000-8000-000000000020")
STORY_TWO_ID = UUID("00000000-0000-4000-8000-000000000021")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ONE_ID = UUID("00000000-0000-4000-8000-000000000040")
SCENARIO_TWO_ID = UUID("00000000-0000-4000-8000-000000000041")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ONE_ID = UUID("00000000-0000-4000-8000-000000000060")
TWIN_TWO_ID = UUID("00000000-0000-4000-8000-000000000061")
CREATED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


def requirements_context(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact Requirements-stage context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference(
    *,
    ordinal: int,
) -> UserTwinVersionReference:
    """Create one exact approved User Twin reference."""
    if ordinal == 1:
        return UserTwinVersionReference(
            twin_id=TWIN_ONE_ID,
            version_number=2,
            content_hash="a" * 64,
            name="Hotel Receptionist Twin",
        )

    return UserTwinVersionReference(
        twin_id=TWIN_TWO_ID,
        version_number=1,
        content_hash="e" * 64,
        name="Hotel Manager Twin",
    )


def grounded_observation(
    *,
    ordinal: int,
) -> ProfileObservation:
    """Create one concrete owner-provided User Twin observation."""
    if ordinal == 1:
        key = "user_twin.goals"
        value = ObservationValue.from_items(("Complete reservation updates accurately",))
    else:
        key = "user_twin.information_needs"
        value = ObservationValue.from_items(("See reservation status across daily operations",))

    return ProfileObservation(
        observation_key=key,
        value=value,
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(1.0),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.PROJECT_BRIEF,
                    source_id="brief-version",
                    source_version=1,
                    content_hash="b" * 64,
                    locator=f"target_users[{ordinal - 1}]",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )


def abstained_observation(
    *,
    ordinal: int,
) -> ProfileObservation:
    """Create an explicit model abstention with no concrete profile content."""
    return ProfileObservation(
        observation_key=f"user_twin.profile_gap_{ordinal}",
        value=ObservationValue.abstained(
            "The approved profile does not contain concrete design-relevant content."
        ),
        epistemic_status=EpistemicStatus.MODEL_INFERRED,
        confidence=ConfidenceScore(0.0),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.SYSTEM_ARTIFACT,
                    source_id=f"user-modeling-version-{ordinal}",
                    source_version=1,
                    content_hash=f"{ordinal:x}" * 64,
                    locator="profile",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.REQUIRED,
        rationale="The deterministic test fixture records an explicit abstention.",
    )


def requirements_version() -> RequirementsSpecificationVersion:
    """Create one complete Requirements baseline with two exact User Twins."""
    twins = (
        twin_reference(ordinal=1),
        twin_reference(ordinal=2),
    )
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
        title="Manage reservations",
        statement="The system must create and review reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source,),
        user_twin_references=twins,
    )
    stories = (
        create_user_story(
            story_id=STORY_ONE_ID,
            code="USR-001",
            user_twin_reference=twins[0],
            goal="create a reservation accurately",
            benefit="serve a guest without avoidable booking errors",
            requirement_ids=(REQUIREMENT_ID,),
        ),
        create_user_story(
            story_id=STORY_TWO_ID,
            code="USR-002",
            user_twin_reference=twins[1],
            goal="review reservation status",
            benefit="coordinate daily hotel operations",
            requirement_ids=(REQUIREMENT_ID,),
        ),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="Created reservations are visible in the current operational status.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=tuple(story.id for story in stories),
    )
    scenarios = (
        create_usage_scenario(
            scenario_id=SCENARIO_ONE_ID,
            code="SCN-001",
            title="Create a reservation",
            actor=twins[0],
            preconditions=(),
            trigger="A guest requests a room.",
            steps=("Create the reservation.",),
            expected_outcome="The reservation appears in operational status.",
            requirement_ids=(REQUIREMENT_ID,),
            acceptance_criterion_ids=(CRITERION_ID,),
        ),
        create_usage_scenario(
            scenario_id=SCENARIO_TWO_ID,
            code="SCN-002",
            title="Review reservation status",
            actor=twins[1],
            preconditions=(),
            trigger="The manager reviews daily operations.",
            steps=("Review current reservation status.",),
            expected_outcome="The manager can identify the current booking state.",
            requirement_ids=(REQUIREMENT_ID,),
            acceptance_criterion_ids=(CRITERION_ID,),
        ),
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
        user_twin_references=twins,
        requirements=(requirement,),
        user_stories=stories,
        acceptance_criteria=(criterion,),
        scenarios=scenarios,
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


def proposal_request(
    *,
    include_designer: bool = True,
    grounded: bool = True,
) -> DesignProposalRequest:
    """Create one complete governed Design Proposal request."""
    version = requirements_version()
    specification = version.specification
    selected_agent_ids = (
        (
            AgentIdentifier.WORKFLOW_ORCHESTRATOR,
            AgentIdentifier.UX_UI_DESIGNER,
            AgentIdentifier.QA_TEST_ENGINEER,
        )
        if include_designer
        else (
            AgentIdentifier.WORKFLOW_ORCHESTRATOR,
            AgentIdentifier.QA_TEST_ENGINEER,
        )
    )

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
            selected_agent_ids=selected_agent_ids,
        ),
        user_modeling=DesignUserModelingInput(
            reference=VersionedArtifactReference(
                kind=ArtifactKind.USER_MODELING,
                artifact_id=specification.user_modeling_reference.artifact_id,
                version_number=specification.user_modeling_reference.version_number,
                content_hash=specification.user_modeling_reference.content_hash,
            ),
            user_twins=tuple(
                DesignUserTwinInput(
                    reference=twin_reference(ordinal=ordinal),
                    observations=(
                        grounded_observation(ordinal=ordinal)
                        if grounded
                        else abstained_observation(ordinal=ordinal),
                    ),
                )
                for ordinal in (1, 2)
            ),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
    )


def propose(request: DesignProposalRequest):
    """Run the fake adapter synchronously for concise unit tests."""
    return asyncio.run(FakeDeterministicDesignAdapter().propose(request))


def test_fake_design_proposal_is_reproducible_and_explicitly_identified() -> None:
    """Return identical provider output for identical governed input."""
    request = proposal_request()

    first = propose(request)
    second = propose(request)

    assert first.status is DesignProposalStatus.PROPOSED
    assert first.provider_kind is DesignProposalProviderKind.FAKE_DETERMINISTIC
    assert first.provider_id == FAKE_DESIGN_PROVIDER_ID
    assert first.provider_version == FAKE_DESIGN_PROVIDER_VERSION
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.package is not None
    assert len(first.package.alternatives) == 3
    assert first.package.owner_selected_alternative_id is None
    assert first.package.prototype is None
    assert not first.package.ready_for_gate


def test_fake_design_proposal_preserves_exact_grounding_and_traceability() -> None:
    """Keep every generated alternative scoped to the approved artifact tuple."""
    request = proposal_request()
    result = propose(request)

    assert result.package is not None

    package = result.package
    grounding = package.grounding

    assert grounding.requirements_reference == request.requirements.reference
    assert grounding.agent_team_reference == request.team.reference
    assert grounding.user_modeling_reference == request.user_modeling.reference
    assert grounding.catalog_version == request.catalog_version
    assert grounding.catalog_content_hash == request.catalog_content_hash
    assert grounding.user_twin_references == request.user_modeling.user_twin_references

    for alternative in package.alternatives:
        assert alternative.requirement_ids == grounding.requirement_ids
        assert alternative.user_story_ids == grounding.user_story_ids
        assert alternative.acceptance_criterion_ids == grounding.acceptance_criterion_ids
        assert alternative.user_twin_references == grounding.user_twin_references
        assert alternative.workflows


def test_fake_design_proposal_creates_genuinely_distinct_directions() -> None:
    """Vary strategy, information architecture, workflow, and trade-offs."""
    result = propose(proposal_request())

    assert result.package is not None

    alternatives = result.package.alternatives

    assert len({alternative.approach for alternative in alternatives}) == len(alternatives)
    assert len({alternative.title for alternative in alternatives}) == len(alternatives)
    assert len({alternative.summary for alternative in alternatives}) == len(alternatives)
    assert len({alternative.information_architecture for alternative in alternatives}) == len(
        alternatives
    )
    assert len({alternative.trade_offs for alternative in alternatives}) == len(alternatives)
    assert len(
        {
            tuple(step for workflow in alternative.workflows for step in workflow.steps)
            for alternative in alternatives
        }
    ) == len(alternatives)
    assert result.package.recommended_alternative_id == alternatives[0].id


def test_fake_design_proposal_covers_every_alternative_and_user_twin_pair() -> None:
    """Generate synthetic review hypotheses for the complete Cartesian product."""
    request = proposal_request()
    result = propose(request)

    assert result.package is not None

    package = result.package
    expected_pairs = {
        (alternative.id, twin.reference)
        for alternative in package.alternatives
        for twin in request.user_modeling.user_twins
    }
    actual_pairs = {
        (critique.design_alternative_id, critique.user_twin_reference)
        for critique in package.critiques
    }

    assert actual_pairs == expected_pairs
    assert len(package.critiques) == len(expected_pairs)

    for critique in package.critiques:
        assert critique.epistemic_status is EpistemicStatus.MODEL_INFERRED
        assert critique.human_validation is HumanValidationRequirement.REQUIRED
        assert critique.requires_human_validation
        assert any(
            reference.source_kind is EvidenceSourceKind.MODEL_OUTPUT
            and reference.source_id == FAKE_DESIGN_PROVIDER_ID
            and reference.source_version == FAKE_DESIGN_PROVIDER_VERSION
            for reference in critique.provenance.references
        )
        assert any(
            reference.source_kind is EvidenceSourceKind.PROJECT_BRIEF
            for reference in critique.provenance.references
        )


def test_fake_design_proposal_rejects_a_team_without_ux_designer() -> None:
    """Require the approved UX/UI Designer before generating design artifacts."""
    result = propose(proposal_request(include_designer=False))

    assert result.status is DesignProposalStatus.REJECTED
    assert result.issue is DesignProposalIssueCode.UX_DESIGNER_REQUIRED
    assert result.package is None


def test_fake_design_proposal_rejects_profiles_without_concrete_grounding() -> None:
    """Do not fabricate role-specific critiques from abstentions alone."""
    result = propose(proposal_request(grounded=False))

    assert result.status is DesignProposalStatus.REJECTED
    assert result.issue is DesignProposalIssueCode.GROUNDED_INPUT_REQUIRED
    assert result.package is None


def test_fake_design_proposal_maps_invalid_domain_output_to_typed_issue(
    monkeypatch,
) -> None:
    """Keep deterministic domain-construction failures inside the typed boundary."""

    def invalid_package(request: DesignProposalRequest):
        del request
        raise ValueError("invalid deterministic package")

    monkeypatch.setattr(fake_design, "_build_package", invalid_package)

    result = propose(proposal_request())

    assert result.status is DesignProposalStatus.REJECTED
    assert result.issue is DesignProposalIssueCode.INVALID_PROVIDER_OUTPUT
    assert result.package is None
