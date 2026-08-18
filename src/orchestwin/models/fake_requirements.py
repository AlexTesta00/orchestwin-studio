"""Deterministic fake adapter for governed requirements proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.models.requirements import (
    RequirementsProposalIssueCode,
    RequirementsProposalProviderKind,
    RequirementsProposalRequest,
    RequirementsProposalResult,
    RequirementsProposalStatus,
)
from orchestwin.projects.requirements import (
    Requirement,
    RequirementKind,
    RequirementPriority,
    UserStory,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
)
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    DefinitionOfDoneApplicability,
    DefinitionOfDoneItem,
    ProjectRisk,
    RiskImpact,
    RiskLikelihood,
    UsageScenario,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_project_risk,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    create_requirements_specification,
)
from orchestwin.twins.epistemics import (
    ObservationValueKind,
    ProfileObservation,
)

FAKE_REQUIREMENTS_PROVIDER_ID: Final = "fake-deterministic-requirements"
FAKE_REQUIREMENTS_PROVIDER_VERSION: Final = 1

_FAKE_REQUIREMENTS_NAMESPACE: Final = UUID("f21dbeec-60b7-4c12-80e7-375849f94740")
_MAX_TITLE_LENGTH: Final = 200


@dataclass(frozen=True, slots=True)
class _RequirementSeed:
    """One Project Brief item mapped to a typed requirement."""

    kind: RequirementKind
    priority: RequirementPriority
    statement: str
    locator: str


class FakeDeterministicRequirementsAdapter:
    """Conservative local provider with no network or model dependency."""

    async def propose(
        self,
        request: RequirementsProposalRequest,
    ) -> RequirementsProposalResult:
        """Produce a deterministic specification from governed inputs."""
        if AgentIdentifier.REQUIREMENTS_ANALYST not in request.team.selected_agent_ids:
            return _rejected(RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED)

        seeds = _requirement_seeds(request)

        if not seeds:
            return _rejected(RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED)

        try:
            specification = _build_specification(
                request,
                seeds,
            )
        except ValueError:
            return _rejected(RequirementsProposalIssueCode.INVALID_PROVIDER_OUTPUT)

        return RequirementsProposalResult(
            status=(RequirementsProposalStatus.PROPOSED),
            provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id=(FAKE_REQUIREMENTS_PROVIDER_ID),
            provider_version=(FAKE_REQUIREMENTS_PROVIDER_VERSION),
            specification=specification,
        )


def _requirement_seeds(
    request: RequirementsProposalRequest,
) -> tuple[_RequirementSeed, ...]:
    """Map only explicit Project Brief statements to requirements."""
    seeds: list[_RequirementSeed] = []

    for (
        index,
        statement,
    ) in enumerate(request.brief.functional_requirements):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.FUNCTIONAL),
                priority=(RequirementPriority.MUST),
                statement=statement,
                locator=(f"functional_requirements[{index}]"),
            )
        )

    for (
        index,
        statement,
    ) in enumerate(request.brief.non_functional_requirements):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.NON_FUNCTIONAL),
                priority=(RequirementPriority.SHOULD),
                statement=statement,
                locator=(f"non_functional_requirements[{index}]"),
            )
        )

    for (
        index,
        statement,
    ) in enumerate(request.brief.technical_constraints):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.CONSTRAINT),
                priority=(RequirementPriority.MUST),
                statement=statement,
                locator=(f"technical_constraints[{index}]"),
            )
        )

    return tuple(seeds)


def _build_specification(
    request: RequirementsProposalRequest,
    seeds: tuple[
        _RequirementSeed,
        ...,
    ],
) -> RequirementsSpecification:
    """Build every specification collection from deterministic inputs."""
    request_hash = request.content_hash

    requirements = _requirements(
        request,
        request_hash,
        seeds,
    )
    stories = _user_stories(
        request,
        request_hash,
        requirements,
    )
    criteria = _acceptance_criteria(
        request_hash,
        requirements,
        stories,
    )
    scenarios = _scenarios(
        request_hash,
        requirements,
        stories,
        criteria,
    )
    risks = _risks(
        request,
        request_hash,
        requirements,
    )
    done = _definition_of_done(
        request,
        request_hash,
        requirements,
    )

    return create_requirements_specification(
        project_id=(request.project_id),
        project_brief_reference=(request.brief.reference),
        agent_team_reference=(request.team.reference),
        user_modeling_reference=(request.user_modeling.reference),
        catalog_version=(request.catalog_version),
        catalog_content_hash=(request.catalog_content_hash),
        user_twin_references=(request.user_modeling.user_twin_references),
        requirements=requirements,
        user_stories=stories,
        acceptance_criteria=criteria,
        scenarios=scenarios,
        risks=risks,
        definition_of_done=done,
    )


def _requirements(
    request: RequirementsProposalRequest,
    request_hash: str,
    seeds: tuple[
        _RequirementSeed,
        ...,
    ],
) -> tuple[
    Requirement,
    ...,
]:
    """Create requirements from exact Project Brief list items."""
    affected_twins = request.user_modeling.user_twin_references

    return tuple(
        create_requirement(
            requirement_id=(
                _artifact_id(
                    request_hash,
                    "requirement",
                    index,
                )
            ),
            code=(f"REQ-{index:03d}"),
            title=_title(seed.statement),
            statement=(seed.statement),
            kind=seed.kind,
            priority=seed.priority,
            sources=(
                _brief_source(
                    request,
                    seed.locator,
                ),
            ),
            user_twin_references=(
                affected_twins if seed.kind is not RequirementKind.CONSTRAINT else ()
            ),
        )
        for (
            index,
            seed,
        ) in enumerate(
            seeds,
            start=1,
        )
    )


def _user_stories(
    request: RequirementsProposalRequest,
    request_hash: str,
    requirements: tuple[
        Requirement,
        ...,
    ],
) -> tuple[
    UserStory,
    ...,
]:
    """Create one traceable story for each exact User Twin."""
    functional_ids = tuple(
        requirement.id
        for requirement in requirements
        if requirement.kind is RequirementKind.FUNCTIONAL
    )

    linked_ids = functional_ids or tuple(requirement.id for requirement in requirements)

    fallback_goal = requirements[0].title

    benefit = _story_benefit(
        request,
        fallback_goal,
    )

    return tuple(
        create_user_story(
            story_id=(
                _artifact_id(
                    request_hash,
                    "user-story",
                    index,
                )
            ),
            code=(f"USR-{index:03d}"),
            user_twin_reference=(twin.reference),
            goal=_story_goal(
                twin.observations,
                fallback_goal,
            ),
            benefit=benefit,
            requirement_ids=(linked_ids),
        )
        for (
            index,
            twin,
        ) in enumerate(
            request.user_modeling.user_twins,
            start=1,
        )
    )


def _acceptance_criteria(
    request_hash: str,
    requirements: tuple[
        Requirement,
        ...,
    ],
    stories: tuple[
        UserStory,
        ...,
    ],
) -> tuple[
    AcceptanceCriterion,
    ...,
]:
    """Create one deterministic criterion for every requirement."""
    return tuple(
        create_acceptance_criterion(
            criterion_id=(
                _artifact_id(
                    request_hash,
                    "criterion",
                    index,
                )
            ),
            code=(f"AC-{index:03d}"),
            statement=(f"The delivered system demonstrably satisfies: {requirement.statement}"),
            verification_method=(
                VerificationMethod.AUTOMATED_TEST
                if requirement.kind is RequirementKind.FUNCTIONAL
                else VerificationMethod.ANALYSIS
            ),
            requirement_ids=(requirement.id,),
            user_story_ids=tuple(
                story.id for story in stories if requirement.id in story.requirement_ids
            ),
        )
        for (
            index,
            requirement,
        ) in enumerate(
            requirements,
            start=1,
        )
    )


def _scenarios(
    request_hash: str,
    requirements: tuple[
        Requirement,
        ...,
    ],
    stories: tuple[
        UserStory,
        ...,
    ],
    criteria: tuple[
        AcceptanceCriterion,
        ...,
    ],
) -> tuple[
    UsageScenario,
    ...,
]:
    """Create one minimal reviewable scenario for every user story."""
    requirements_by_id = {requirement.id: requirement for requirement in requirements}

    return tuple(
        create_usage_scenario(
            scenario_id=(
                _artifact_id(
                    request_hash,
                    "scenario",
                    index,
                )
            ),
            code=(f"SCN-{index:03d}"),
            title=_title(f"Complete {story.goal}"),
            actor=(story.user_twin_reference),
            preconditions=(),
            trigger=(f"{story.user_twin_reference.name} starts the requested workflow."),
            steps=tuple(
                f"Perform the behavior defined by {requirements_by_id[requirement_id].code}."
                for requirement_id in story.requirement_ids
            ),
            expected_outcome=(
                _scenario_outcome(
                    story,
                    criteria,
                )
            ),
            requirement_ids=(story.requirement_ids),
            acceptance_criterion_ids=tuple(
                criterion.id
                for criterion in criteria
                if set(criterion.requirement_ids).intersection(story.requirement_ids)
            ),
        )
        for (
            index,
            story,
        ) in enumerate(
            stories,
            start=1,
        )
    )


def _risks(
    request: RequirementsProposalRequest,
    request_hash: str,
    requirements: tuple[
        Requirement,
        ...,
    ],
) -> tuple[
    ProjectRisk,
    ...,
]:
    """Create risks only from the explicit Project Brief risk list."""
    requirement_ids = tuple(requirement.id for requirement in requirements)

    return tuple(
        create_project_risk(
            risk_id=(
                _artifact_id(
                    request_hash,
                    "risk",
                    index,
                )
            ),
            code=(f"RSK-{index:03d}"),
            summary=summary,
            likelihood=(RiskLikelihood.POSSIBLE),
            impact=(RiskImpact.MEDIUM),
            mitigation=("Define and verify an explicit mitigation before implementation approval."),
            requirement_ids=(requirement_ids),
            sources=(
                _brief_source(
                    request,
                    f"risks[{index - 1}]",
                ),
            ),
        )
        for (
            index,
            summary,
        ) in enumerate(
            request.brief.risks,
            start=1,
        )
    )


def _definition_of_done(
    request: RequirementsProposalRequest,
    request_hash: str,
    requirements: tuple[
        Requirement,
        ...,
    ],
) -> tuple[
    DefinitionOfDoneItem,
    ...,
]:
    """Create explicit completion conditions without claiming satisfaction."""
    statements = request.brief.definition_of_done or (
        "Every acceptance criterion has recorded verification evidence.",
    )

    requirement_ids = tuple(requirement.id for requirement in requirements)

    return tuple(
        create_definition_of_done_item(
            item_id=(
                _artifact_id(
                    request_hash,
                    "definition-of-done",
                    index,
                )
            ),
            code=(f"DOD-{index:03d}"),
            statement=statement,
            verification_method=(_verification_method(statement)),
            applicability=(DefinitionOfDoneApplicability.REQUIRED),
            requirement_ids=(requirement_ids),
        )
        for (
            index,
            statement,
        ) in enumerate(
            statements,
            start=1,
        )
    )


def _brief_source(
    request: RequirementsProposalRequest,
    locator: str,
) -> RequirementSourceReference:
    """Create one exact source reference into the governed Project Brief."""
    reference = request.brief.reference

    return RequirementSourceReference(
        kind=(RequirementSourceKind.PROJECT_BRIEF),
        source_id=str(reference.artifact_id),
        source_version=(reference.version_number),
        content_hash=(reference.content_hash),
        locator=locator,
    )


def _story_goal(
    observations: tuple[
        ProfileObservation,
        ...,
    ],
    fallback: str,
) -> str:
    """Use supported User Twin goal content or a Brief-derived fallback."""
    goal = next(
        (
            observation
            for observation in observations
            if observation.observation_key == "user_twin.goals"
        ),
        None,
    )

    if goal is None:
        return fallback

    if goal.value.kind is ObservationValueKind.TEXT and goal.value.text is not None:
        return goal.value.text

    if goal.value.kind is ObservationValueKind.ITEMS and goal.value.items:
        return goal.value.items[0]

    return fallback


def _story_benefit(
    request: RequirementsProposalRequest,
    fallback: str,
) -> str:
    """Select a benefit from explicit Brief goals or problem context."""
    if request.brief.goals:
        return request.brief.goals[0]

    if request.brief.problem is not None:
        return request.brief.problem

    return fallback


def _scenario_outcome(
    story: UserStory,
    criteria: tuple[
        AcceptanceCriterion,
        ...,
    ],
) -> str:
    """Use the first criterion linked to the story as expected outcome."""
    requirement_ids = frozenset(story.requirement_ids)

    criterion = next(
        (value for value in criteria if requirement_ids.intersection(value.requirement_ids)),
        None,
    )

    if criterion is None:
        return f"The linked requirements for {story.code} are satisfied."

    return criterion.statement


def _verification_method(
    statement: str,
) -> VerificationMethod:
    """Choose a deterministic verification method from explicit wording."""
    normalized = statement.casefold()

    if "test" in normalized:
        return VerificationMethod.AUTOMATED_TEST

    return VerificationMethod.INSPECTION


def _title(
    statement: str,
) -> str:
    """Return a readable bounded title derived from supplied text."""
    candidate = statement.rstrip(".?!")

    if len(candidate) <= _MAX_TITLE_LENGTH:
        return candidate

    return f"{candidate[: _MAX_TITLE_LENGTH - 3].rstrip()}..."


def _artifact_id(
    request_hash: str,
    artifact_kind: str,
    ordinal: int,
) -> UUID:
    """Derive a stable identity from exact provider input and position."""
    return uuid5(
        _FAKE_REQUIREMENTS_NAMESPACE,
        (f"{request_hash}:{artifact_kind}:{ordinal}"),
    )


def _rejected(
    issue: RequirementsProposalIssueCode,
) -> RequirementsProposalResult:
    """Return one typed deterministic rejection."""
    return RequirementsProposalResult(
        status=(RequirementsProposalStatus.REJECTED),
        provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
        provider_id=(FAKE_REQUIREMENTS_PROVIDER_ID),
        provider_version=(FAKE_REQUIREMENTS_PROVIDER_VERSION),
        issue=issue,
    )


__all__ = [
    "FAKE_REQUIREMENTS_PROVIDER_ID",
    "FAKE_REQUIREMENTS_PROVIDER_VERSION",
    "FakeDeterministicRequirementsAdapter",
]
