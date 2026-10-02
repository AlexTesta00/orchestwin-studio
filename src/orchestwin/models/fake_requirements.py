"""Deterministic fake adapter for governed requirements proposals."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
from orchestwin.models.requirements_drafts import (
    RequirementsDraft,
    _require_journey_scope,
    requirements_context,
    requirements_limits,
    requirements_view,
)
from orchestwin.projects.requirements import (
    Requirement,
    RequirementKind,
    RequirementPriority,
    UserStory,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_journeys import create_journey_phase, create_user_journey
from orchestwin.projects.requirements_needs import create_user_need
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
    locators: tuple[str, ...]


class FakeDeterministicRequirementsAdapter:
    """Conservative local provider with no network or model dependency."""

    async def propose(
        self,
        request: RequirementsProposalRequest,
    ) -> RequirementsProposalResult:
        """Produce a deterministic specification from governed inputs."""
        if AgentIdentifier.REQUIREMENTS_ANALYST not in request.team.selected_agent_ids:
            return _rejected(RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED)

        if request.current_specification is not None and request.owner_request is not None:
            return _changed(request)

        if not _requirement_seeds(request):
            return _rejected(RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED)

        try:
            seeds = _merged_seeds(request)
            specification = _build_specification(request, seeds)
            _validate_specification(request, specification)
        except ValueError:
            return _rejected(RequirementsProposalIssueCode.INVALID_PROVIDER_OUTPUT)

        return RequirementsProposalResult(
            status=(RequirementsProposalStatus.PROPOSED),
            provider_kind=(RequirementsProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id=(FAKE_REQUIREMENTS_PROVIDER_ID),
            provider_version=(FAKE_REQUIREMENTS_PROVIDER_VERSION),
            specification=specification,
        )


def _changed(request: RequirementsProposalRequest) -> RequirementsProposalResult:
    specification = request.current_specification
    first, *others = specification.requirements

    try:
        if specification.schema_version == 1:
            specification = _enriched_legacy(request)
            first, *others = specification.requirements
        if request.include_journeys:
            changed = replace(specification, journeys=_journeys(request, specification))
        else:
            statement = _bounded_text(f"{first.statement} ({request.owner_request})")
            changed = replace(
                specification,
                requirements=(replace(first, statement=statement), *others),
            )
        _validate_specification(request, changed)
    except (ValueError, KeyError):
        return _rejected(RequirementsProposalIssueCode.INVALID_PROVIDER_OUTPUT)

    return RequirementsProposalResult(
        status=RequirementsProposalStatus.PROPOSED,
        provider_kind=RequirementsProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id=FAKE_REQUIREMENTS_PROVIDER_ID,
        provider_version=FAKE_REQUIREMENTS_PROVIDER_VERSION,
        specification=changed,
    )


def _enriched_legacy(request):
    specification = request.current_specification
    requirements = {item.id: item for item in specification.requirements}
    twins = {item.reference: item for item in request.user_modeling.user_twins}
    scenarios = tuple(
        replace(
            item,
            context=_context(request),
            goal=_bounded_text(_story_goal(twins[item.actor].observations, item.title)),
            sources=_scenario_sources(
                request,
                twins[item.actor],
                tuple(requirements[value] for value in item.requirement_ids),
            ),
        )
        for item in specification.scenarios
    )
    actors = {item.actor for item in scenarios}
    next_code = max(int(item.code.split("-")[1]) for item in scenarios) + 1
    added = []
    for story in specification.user_stories:
        if story.user_twin_reference in actors:
            continue
        actors.add(story.user_twin_reference)
        added.append(
            create_usage_scenario(
                scenario_id=_artifact_id(request.content_hash, "scenario", next_code),
                code=f"SCN-{next_code:03d}",
                title=_title(story.goal),
                actor=story.user_twin_reference,
                preconditions=(),
                trigger=f"{story.user_twin_reference.name} starts the requested workflow.",
                steps=tuple(requirements[value].statement for value in story.requirement_ids),
                expected_outcome=_scenario_outcome(story, specification.acceptance_criteria),
                requirement_ids=story.requirement_ids,
                acceptance_criterion_ids=tuple(
                    item.id
                    for item in specification.acceptance_criteria
                    if set(item.requirement_ids).intersection(story.requirement_ids)
                ),
                context=_context(request),
                goal=story.goal,
                sources=_scenario_sources(
                    request,
                    twins[story.user_twin_reference],
                    tuple(requirements[value] for value in story.requirement_ids),
                ),
            )
        )
        next_code += 1
    scenarios = (*scenarios, *added)
    needs = _needs(request.content_hash, scenarios)
    need_ids = tuple(sorted((item.id for item in needs), key=lambda value: value.hex))
    actor_needs = {
        item.actor: tuple(
            sorted(
                (need.id for need in needs if item.id in need.scenario_ids),
                key=lambda value: value.hex,
            )
        )
        for item in scenarios
    }
    return replace(
        specification,
        requirements=tuple(replace(item, need_ids=need_ids) for item in specification.requirements),
        user_stories=tuple(
            replace(item, need_ids=actor_needs[item.user_twin_reference])
            for item in specification.user_stories
        ),
        scenarios=scenarios,
        needs=needs,
        schema_version=2,
    )


def _validate_specification(request, specification):
    _, sources, twins = requirements_context(request)
    draft = RequirementsDraft.model_validate(requirements_view(specification, sources, twins))
    for name, limit in requirements_limits(request).items():
        if len(getattr(draft, name)) > limit:
            raise ValueError(f"fake list {name} exceeds its limit of {limit}")
    _require_journey_scope(request, specification)


def _journeys(request, specification):
    existing = {item.scenario_id: item for item in specification.journeys}
    next_code = (
        max((int(item.code.split("-")[1]) for item in specification.journeys), default=0) + 1
    )
    journeys = list(specification.journeys)
    for scenario in specification.scenarios:
        if scenario.id in existing:
            continue
        needs = tuple(item for item in specification.needs if scenario.id in item.scenario_ids)
        count = min(len(scenario.steps), 32)
        actions = tuple(
            _bounded_text(
                "; ".join(
                    scenario.steps[
                        index * len(scenario.steps) // count : (index + 1)
                        * len(scenario.steps)
                        // count
                    ]
                )
            )
            for index in range(count)
        )
        journeys.append(
            create_user_journey(
                journey_id=_artifact_id(request.content_hash, "journey", next_code),
                code=f"JRN-{next_code:03d}",
                title=scenario.title,
                scenario_id=scenario.id,
                phases=tuple(
                    create_journey_phase(
                        title=_title(action),
                        action=action,
                        touchpoint=None,
                        criticalities=scenario.criticalities if index == 0 else (),
                        need_ids=tuple(item.id for item in needs),
                    )
                    for index, action in enumerate(actions)
                ),
                sources=tuple(
                    {*scenario.sources, *(source for item in needs for source in item.sources)}
                ),
            )
        )
        next_code += 1
    return tuple(sorted(journeys, key=lambda item: item.code))


def _requirement_seeds(
    request: RequirementsProposalRequest,
) -> tuple[_RequirementSeed, ...]:
    """Map only explicit Project Brief statements to requirements."""
    seeds: list[_RequirementSeed] = []

    for (
        index,
        statement,
    ) in enumerate(_known_list(request, "functional_requirements")):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.FUNCTIONAL),
                priority=(RequirementPriority.MUST),
                statement=statement,
                locators=(f"functional_requirements[{index}]",),
            )
        )

    for (
        index,
        statement,
    ) in enumerate(_known_list(request, "non_functional_requirements")):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.NON_FUNCTIONAL),
                priority=(RequirementPriority.SHOULD),
                statement=statement,
                locators=(f"non_functional_requirements[{index}]",),
            )
        )

    for (
        index,
        statement,
    ) in enumerate(_known_list(request, "technical_constraints")):
        seeds.append(
            _RequirementSeed(
                kind=(RequirementKind.CONSTRAINT),
                priority=(RequirementPriority.MUST),
                statement=statement,
                locators=(f"technical_constraints[{index}]",),
            )
        )

    return tuple(seeds)


def _known_list(request, name):
    return () if name in request.brief.unknown_fields else getattr(request.brief, name)


def _bounded_text(text):
    normalized = " ".join(text.split())
    if not normalized or len(normalized) > 2000:
        raise ValueError("fake content cannot preserve all brief text within the draft text limit")
    return normalized


def _merged_seeds(request):
    seeds = _requirement_seeds(request)
    maximum = requirements_limits(request)["requirements"]
    groups = {kind: tuple(seed for seed in seeds if seed.kind is kind) for kind in RequirementKind}
    quality_kinds = [
        kind for kind in groups if kind is not RequirementKind.FUNCTIONAL and groups[kind]
    ]
    slots = {kind: 1 for kind in quality_kinds}
    remaining = min(
        sum(len(groups[kind]) for kind in quality_kinds),
        maximum - len(groups[RequirementKind.FUNCTIONAL]),
    ) - len(slots)
    while remaining:
        for kind in quality_kinds:
            if slots[kind] < len(groups[kind]) and remaining:
                slots[kind] += 1
                remaining -= 1
    slots[RequirementKind.FUNCTIONAL] = len(groups[RequirementKind.FUNCTIONAL])
    merged = []
    for kind, items in groups.items():
        count = slots.get(kind, 0)
        for index in range(count):
            group = items[index * len(items) // count : (index + 1) * len(items) // count]
            merged.append(
                _RequirementSeed(
                    kind=kind,
                    priority=group[0].priority,
                    statement=_bounded_text("; ".join(item.statement for item in group)),
                    locators=tuple(locator for item in group for locator in item.locators),
                )
            )
    if len(merged) > maximum:
        raise ValueError("fake requirements exceed their brief limit")
    return tuple(merged)


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
        request,
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

    needs = _needs(request_hash, scenarios)

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
        needs=needs,
        schema_version=2,
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
                    locator,
                )
                for locator in seed.locators
            ),
            need_ids=tuple(
                _artifact_id(request_hash, "need", ordinal)
                for ordinal in range(1, len(request.user_modeling.user_twins) + 1)
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
            need_ids=(_artifact_id(request_hash, "need", index),),
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
            statement=(
                f"The delivered system demonstrably satisfies: {requirement.statement}"
                if len(requirement.statement) <= 1956
                else requirement.statement
            ),
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
    request: RequirementsProposalRequest,
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
                requirements_by_id[requirement_id].statement
                for requirement_id in story.requirement_ids
            ),
            expected_outcome=(
                _scenario_outcome(
                    story,
                    criteria,
                )
            ),
            context=_context(request),
            goal=_bounded_text(story.goal),
            sources=_scenario_sources(
                request, request.user_modeling.user_twins[index - 1], requirements
            ),
            criticalities=tuple(_bounded_text(value) for value in _known_list(request, "risks")),
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
            summary=_bounded_text(summary),
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
            _known_list(request, "risks"),
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
    statements = _known_list(request, "definition_of_done") or (
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
            statement=_bounded_text(statement),
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


def _context(request):
    brief = request.brief
    if brief.problem is not None and "problem" not in brief.unknown_fields:
        return _bounded_text(brief.problem)
    return _bounded_text(brief.name)


def _scenario_sources(request, twin, requirements):
    cited = {source for item in requirements for source in item.sources}
    context_locator = (
        "problem"
        if request.brief.problem is not None and "problem" not in request.brief.unknown_fields
        else "name"
    )
    cited.add(_brief_source(request, context_locator))
    for index, _ in enumerate(_known_list(request, "risks")):
        cited.add(_brief_source(request, f"risks[{index}]"))
    for item in twin.observations:
        if (
            item.observation_key == "user_twin.goals"
            and item.value.kind is not ObservationValueKind.UNKNOWN
        ):
            cited.add(
                RequirementSourceReference(
                    kind=RequirementSourceKind.USER_TWIN,
                    source_id=str(twin.reference.twin_id),
                    source_version=twin.reference.version_number,
                    content_hash=twin.reference.content_hash,
                    locator=item.observation_key,
                )
            )
    return tuple(sorted(cited, key=lambda source: source.sort_key))


def _needs(request_hash, scenarios):
    actors = tuple(dict.fromkeys(item.actor for item in scenarios))
    return tuple(
        create_user_need(
            need_id=_artifact_id(request_hash, "need", index),
            code=f"NED-{index:03d}",
            title=_title(next(item.goal for item in scenarios if item.actor == actor)),
            statement=next(item.goal for item in scenarios if item.actor == actor),
            scenario_ids=tuple(item.id for item in scenarios if item.actor == actor),
            sources=tuple(
                {source for item in scenarios if item.actor == actor for source in item.sources}
            ),
        )
        for index, actor in enumerate(actors, 1)
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
    if _known_list(request, "goals"):
        return request.brief.goals[0]

    if request.brief.problem is not None and "problem" not in request.brief.unknown_fields:
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
