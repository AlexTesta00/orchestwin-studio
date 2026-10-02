from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.models.hosted_schema import (
    SchemaViolation,
    retry_sentence,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.model_proposals import ModelRequirementsAdapter
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.requirements_drafts import (
    RequirementsDraft,
    bind_requirements,
    requirements_context,
    requirements_limits,
    requirements_view,
)
from orchestwin.projects.briefs import BriefField

from .test_fake_requirements import proposal_request
from .test_model_proposals import make_generator
from .test_perspective_guidance import DEFINITION_SENTENCES
from .test_proposal_evidence import Command, MemoryEvidence, audited_generator
from .test_requirements_change_proposals import (
    OWNER_REQUEST,
    baseline_instruction,
    legacy_instruction,
    sha256,
)

LISTS = (
    "requirements",
    "user_stories",
    "acceptance_criteria",
    "scenarios",
    "needs",
    "risks",
    "definition_of_done",
)
BRIEF_LISTS = (
    BriefField.FUNCTIONAL_REQUIREMENTS,
    BriefField.NON_FUNCTIONAL_REQUIREMENTS,
    BriefField.TECHNICAL_CONSTRAINTS,
    BriefField.RISKS,
    BriefField.DEFINITION_OF_DONE,
)
COVERAGE = "Cover every brief requirement and each twin with a story and scenario."
PROPORTION = (
    "Be proportionate to the project: context.limits holds the largest number of items that "
    "each list may have. A limit is a ceiling and not a target: write fewer items when the "
    "project needs fewer. When the brief names more needs than a limit allows, merge related "
    "needs into one requirement and name every merged need among its sources. Every statement "
    "is one sentence, two at most."
)
PREVIOUS_INSTRUCTION_SHA256 = "2f88c3238becce75c6de8fc06ce003813766abe336228db5b7f3ba0f16d5b1b9"


def limits(*values):
    return dict(zip(LISTS, values, strict=True))


FIXTURE_LIMITS = limits(5, 2, 5, 1, 5, 3, 3)


def needs(label, count):
    return tuple(f"{label} {index}" for index in range(1, count + 1))


def with_twins(request, count):
    template = request.user_modeling.user_twins[0]
    first = template.reference.twin_id.int
    twins = tuple(
        replace(template, reference=replace(template.reference, twin_id=UUID(int=first + index)))
        for index in range(count)
    )
    return replace(request, user_modeling=replace(request.user_modeling, user_twins=twins))


def example_request(constraints=5):
    request = with_twins(proposal_request(), 2)
    brief = replace(
        request.brief,
        functional_requirements=needs("Functional need", 8),
        non_functional_requirements=needs("Quality need", 5),
        technical_constraints=needs("Technical constraint", constraints),
        risks=needs("Project risk", 1),
        definition_of_done=needs("Completion condition", 5),
    )
    return replace(request, brief=brief)


def generated(request):
    return asyncio.run(FakeDeterministicRequirementsAdapter().propose(request)).specification


def change_of(request):
    return replace(request, current_specification=generated(request), owner_request=OWNER_REQUEST)


def grown(items, count):
    prefix = items[0]["code"].split("-")[0]
    return [
        *items,
        *(
            {**deepcopy(items[0]), "code": f"{prefix}-{index:03d}"}
            for index in range(len(items) + 1, count + 1)
        ),
    ]


def at_limits(request):
    context, sources, twins = requirements_context(request)
    answer = requirements_view(generated(request), sources, twins)
    for name, limit in context["limits"].items():
        answer[name] = grown(answer[name], limit)
    for item in answer["requirements"]:
        item["needs"] = [need["code"] for need in answer["needs"]]
    for item in answer["needs"]:
        item["scenarios"] = [scenario["code"] for scenario in answer["scenarios"]]
    return answer, sources, twins


def bound(answer, request, sources, twins):
    return bind_requirements(RequirementsDraft.model_validate(answer), request, sources, twins)


def sent_to_model(tmp_path, request, answer):
    generator, transport = make_generator(tmp_path, answer)
    result = asyncio.run(ModelRequirementsAdapter(generator).propose(request))
    [call] = transport.calls
    return call["payload"], result


def test_the_brief_of_the_example_gets_twelve_requirements_and_two_scenarios():
    assert requirements_limits(example_request()) == limits(12, 4, 12, 2, 12, 3, 5)


@pytest.mark.parametrize("filled", [False, True], ids=["empty", "filled"])
def test_five_unknown_lists_and_one_twin_get_the_smallest_limits(filled):
    request = proposal_request()
    brief = replace(
        request.brief,
        unknown_fields=frozenset(BRIEF_LISTS),
        **{field.value: needs("Stated need", 9) if filled else () for field in BRIEF_LISTS},
    )

    assert requirements_limits(replace(request, brief=brief)) == limits(3, 2, 3, 1, 3, 3, 3)


def test_eight_twins_get_one_story_and_one_scenario_each():
    assert requirements_limits(with_twins(proposal_request(), 8)) == limits(5, 8, 5, 8, 8, 3, 3)


def test_a_change_on_twelve_requirements_keeps_them_and_leaves_room_for_two_more():
    request = example_request(constraints=4)
    change = change_of(request)
    current = change.current_specification
    context, sources, twins = requirements_context(change)
    answer = deepcopy(context["current_requirements"])

    assert len(current.requirements) == 12
    assert requirements_limits(request) == limits(12, 4, 12, 2, 12, 3, 5)
    assert requirements_limits(change) == limits(14, 4, 14, 4, 12, 3, 7)
    assert bound(answer, change, sources, twins) == current

    answer["requirements"] = grown(answer["requirements"], 14)
    assert len(bound(answer, change, sources, twins).requirements) == 14

    answer["requirements"] = grown(answer["requirements"], 15)
    with pytest.raises(ValueError, match=r"^draft list requirements exceeds its limit of 14$"):
        bound(answer, change, sources, twins)


def test_the_context_carries_the_limits_of_the_request():
    request = proposal_request()
    change = change_of(request)

    assert requirements_context(request)[0]["limits"] == FIXTURE_LIMITS
    assert requirements_context(change)[0]["limits"] == limits(6, 3, 6, 3, 5, 3, 3)


def test_the_schema_bounds_the_seven_lists_and_changes_nothing_else():
    context, _, _ = requirements_context(proposal_request())
    bounded = RequirementsDraft.model_json_schema()
    free = RequirementsDraft.model_json_schema()

    constrain_planning_schema(bounded, context, "requirements")
    constrain_planning_schema(
        free, {key: value for key, value in context.items() if key != "limits"}, "requirements"
    )

    assert {name: bounded["properties"][name].pop("maxItems") for name in LISTS} == FIXTURE_LIMITS
    assert bounded == free


def test_the_model_receives_the_limits_in_the_schema_of_contract_seven(tmp_path):
    request = proposal_request()
    answer, _, _ = at_limits(request)

    payload, result = sent_to_model(tmp_path, request, answer)
    output_schema = payload["response_format"]["json_schema"]
    sent = json.loads(payload["messages"][1]["content"])

    assert output_schema["name"] == "proposal-requirements-v7"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-requirements-v7"
    assert sent["context"]["limits"] == FIXTURE_LIMITS
    assert {
        name: output_schema["schema"]["properties"][name]["maxItems"] for name in LISTS
    } == FIXTURE_LIMITS
    assert [len(getattr(result.specification, name)) for name in LISTS] == [5, 2, 5, 1, 5, 3, 3]


def test_the_full_schema_of_the_hosted_route_names_the_list_above_its_limit(tmp_path):
    request = proposal_request()
    answer, _, _ = at_limits(request)
    payload, _ = sent_to_model(tmp_path, request, answer)
    schema = payload["response_format"]["json_schema"]["schema"]
    above = {**answer, "scenarios": grown(answer["scenarios"], 2)}

    violations = validate_against_schema(above, schema)

    assert validate_against_schema(answer, schema) == ()
    assert violations == (SchemaViolation("$.scenarios", "maxItems"),)
    assert retry_sentence(violation_message(violations)) == (
        "The previous answer did not follow output_schema at $.scenarios (maxItems); answer "
        "again with the complete JSON object."
    )


def test_a_draft_at_every_limit_is_accepted():
    request = proposal_request()
    answer, sources, twins = at_limits(request)

    specification = bound(answer, request, sources, twins)

    assert [len(getattr(specification, name)) for name in LISTS] == [5, 2, 5, 1, 5, 3, 3]


@pytest.mark.parametrize(("name", "limit"), list(FIXTURE_LIMITS.items()))
def test_a_draft_above_one_limit_is_refused_by_the_binder(name, limit):
    request = proposal_request()
    answer, sources, twins = at_limits(request)
    answer[name] = grown(answer[name], limit + 1)

    with pytest.raises(ValueError, match=rf"^draft list {name} exceeds its limit of {limit}$"):
        bound(answer, request, sources, twins)


def test_the_local_route_records_why_an_answer_above_a_limit_is_refused(tmp_path):
    request = proposal_request()
    answer, _, _ = at_limits(request)
    answer["scenarios"] = grown(answer["scenarios"], 2)
    generator, transport = audited_generator(tmp_path, answer)
    store = MemoryEvidence()
    command = Command(store, lambda: ModelRequirementsAdapter(generator).propose(request))

    with pytest.raises(ProposalGenerationError, match="INVALID_PROVIDER_OUTPUT"):
        asyncio.run(command.run(owner_user_id=uuid4(), project_id=uuid4()))
    [events] = store.events.values()
    rejected = next(payload for kind, payload, _ in events if kind == "ADAPTER_REJECTED")

    assert len(transport.calls) == 1
    assert rejected["reason"] == "draft list scenarios exceeds its limit of 1"


def test_the_instruction_asks_for_proportion_right_after_the_coverage_and_keeps_the_rest():
    instruction = baseline_instruction()
    added = f" {PROPORTION} {DEFINITION_SENTENCES}"

    assert COVERAGE in instruction
    assert (
        f"{PROPORTION} {DEFINITION_SENTENCES} Keep criteria concrete and testable." in instruction
    )
    assert instruction.count(PROPORTION) == 1
    assert instruction.count("context.limits") == 2
    assert sha256(legacy_instruction(instruction).replace(added, "")) == PREVIOUS_INSTRUCTION_SHA256
