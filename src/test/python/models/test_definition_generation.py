from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_packages import create_design_grounding
from orchestwin.artifacts.design_realignment import (
    missing_item_ids,
    realign_design,
    uncovered_requirement_codes,
)
from orchestwin.models.design_drafts import (
    requirement_code_map,
)
from orchestwin.models.design_drafts import (
    requirements_view as design_requirements_view,
)
from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.models.model_proposals import ModelDesignAdapter, ModelRequirementsAdapter
from orchestwin.models.requirements import RequirementsProposalIssueCode
from orchestwin.models.requirements_drafts import (
    RequirementsDraft,
    bind_requirements,
    requirements_context,
    requirements_limits,
    requirements_view,
)
from orchestwin.models.test_planning import PLAN_INSTRUCTION, plan_tests
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.requirements_needs import create_user_need
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
    canonical_json,
    canonical_requirement_sources,
)
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts import test_design_realignment as mockup_fixtures

from . import test_fake_design as design_request_fixtures
from .draft_fixtures import proposal_draft
from .test_fake_requirements import proposal_request
from .test_model_proposals import make_generator
from .test_requirements_change_proposals import (
    change_request,
    generated_specification,
    legacy_projection,
    sha256,
)
from .test_requirements_limits import at_limits, example_request, with_twins
from .test_test_planning import (
    CRITERIA,
    material,
    plan_output,
    planning_context,
)

LEGACY_DESIGN_VIEW_SHA256 = "35be539d01da9df45725918a21b17a27c999a870e944164cfc51f8b03d6acad4"
DEFINITION_DESIGN_VIEW_SHA256 = "7d8fd69f2c9387137940d5ecdd4107c507fdd3edd5767dd10140f128b6cfe1fd"
TEST_PLAN_SCHEMA_SHA256 = "e33ac0bcadbdc641104e307acb21c307a545b01e5bf25ea627d9f53870ce48b7"
TEST_PLAN_INSTRUCTION_SHA256 = "846d0c0e47d355950147ee7147267132534894d2ab1ea7edc20786e6bd677fe9"
REQUIREMENTS_SCHEMA_SHA256 = {
    "baseline": "8b520303183a8bd3e8e9c9ca6cfefc6eb467f131c2329ad416bbd0cca307ae80",
    "change": "9aae707045690678e92fa2584d03682fac043a79cf6f196296c3a80471380cce",
}


def fake(request):
    return asyncio.run(FakeDeterministicRequirementsAdapter().propose(request))


def definition_version(version=None):
    version = design_fixtures.requirements_version() if version is None else version
    specification = version.specification
    sources = specification.requirements[0].sources
    scenarios = tuple(
        replace(
            item,
            context="The receptionist works at the hotel desk.",
            goal="Record the guest's reservation accurately.",
            criticalities=("Room availability can change during a reservation.",),
            sources=sources,
        )
        for item in specification.scenarios
    )
    actors = {item.actor for item in scenarios}
    for actor in specification.user_twin_references:
        if actor not in actors:
            actors.add(actor)
            story = next(
                (item for item in specification.user_stories if item.user_twin_reference == actor),
                None,
            )
            ordinal = len(scenarios) + 1
            scenarios = (
                *scenarios,
                replace(
                    scenarios[0],
                    id=UUID(int=0xA000 + ordinal),
                    code=f"SCN-{ordinal:03d}",
                    actor=actor,
                    goal=story.goal if story is not None else specification.requirements[0].title,
                    requirement_ids=story.requirement_ids
                    if story is not None
                    else scenarios[0].requirement_ids,
                ),
            )
    actors = tuple(dict.fromkeys(item.actor for item in scenarios))
    needs = tuple(
        create_user_need(
            need_id=UUID(int=0x9000 + index),
            code=f"NED-{index:03d}",
            title="Record a reservation accurately",
            statement="Keep the reservation and available rooms consistent.",
            scenario_ids=tuple(item.id for item in scenarios if item.actor == actor),
            sources=sources,
        )
        for index, actor in enumerate(actors, 1)
    )
    need_ids = tuple(item.id for item in needs)
    actor_needs = {
        actor: tuple(
            need.id
            for need in needs
            if any(item.actor == actor and item.id in need.scenario_ids for item in scenarios)
        )
        for actor in actors
    }
    specification = replace(
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
    return replace(version, specification=specification, content_hash=specification.content_hash)


def test_fake_schema_two_covers_the_full_chain_for_eight_twins():
    request = with_twins(proposal_request(), 8)
    specification = fake(request).specification
    assert specification.schema_version == 2
    assert len(specification.needs) == len(specification.scenarios) == 8
    context, sources, twins = requirements_context(request)
    draft = RequirementsDraft.model_validate(requirements_view(specification, sources, twins))
    assert all(len(getattr(draft, name)) <= limit for name, limit in context["limits"].items())
    scenarios = {item.id: item for item in specification.scenarios}
    for story in specification.user_stories:
        need = next(item for item in specification.needs if item.id in story.need_ids)
        assert all(
            scenarios[value].actor == story.user_twin_reference for value in need.scenario_ids
        )
        assert need.statement == story.goal
    assert all(item.need_ids for item in specification.requirements)
    assert all(
        item.context == request.brief.problem and item.sources for item in scenarios.values()
    )
    assert all(item.goal != item.expected_outcome for item in scenarios.values())


def test_fake_merges_quality_lists_without_losing_any_brief_text_or_source():
    request = example_request()
    specification = fake(request).specification
    assert len(specification.requirements) == requirements_limits(request)["requirements"] == 12
    cited = {source.locator for item in specification.requirements for source in item.sources}
    for name in ("functional_requirements", "non_functional_requirements", "technical_constraints"):
        for index, text in enumerate(getattr(request.brief, name)):
            assert f"{name}[{index}]" in cited
            assert any(text in item.statement for item in specification.requirements)
    assert [item.summary for item in specification.risks] == list(request.brief.risks)
    assert [item.statement for item in specification.definition_of_done] == list(
        request.brief.definition_of_done
    )
    assert set(cited) <= {source.locator for item in specification.needs for source in item.sources}
    assert set(cited) <= {
        source.locator for item in specification.scenarios for source in item.sources
    }


def test_fake_unknown_lists_do_not_create_requirements_risks_or_completion_conditions():
    request = proposal_request()
    unknown = frozenset(
        {
            BriefField.FUNCTIONAL_REQUIREMENTS,
            BriefField.NON_FUNCTIONAL_REQUIREMENTS,
            BriefField.RISKS,
            BriefField.DEFINITION_OF_DONE,
        }
    )
    request = replace(request, brief=replace(request.brief, unknown_fields=unknown))
    specification = fake(request).specification
    assert len(specification.requirements) == 1
    assert specification.requirements[0].statement == request.brief.technical_constraints[0]
    assert specification.risks == ()
    assert specification.scenarios[0].criticalities == ()
    assert request.brief.definition_of_done[0] not in {
        item.statement for item in specification.definition_of_done
    }


def test_fake_refuses_lossless_text_that_cannot_fit_the_schema_ceiling():
    request = proposal_request()
    request = replace(
        request,
        brief=replace(
            request.brief,
            non_functional_requirements=tuple(
                f"Quality {index} " + "x" * 1490 for index in range(8)
            ),
            technical_constraints=(),
        ),
    )
    result = fake(request)
    assert result.issue is RequirementsProposalIssueCode.INVALID_PROVIDER_OUTPUT
    assert result.specification is None


def test_change_retains_sources_cited_only_by_needs_and_scenarios():
    current = generated_specification()
    need_source = RequirementSourceReference(
        kind=RequirementSourceKind.OWNER_INPUT, source_id="owner", locator="need-insight"
    )
    scenario_source = RequirementSourceReference(
        kind=RequirementSourceKind.OWNER_INPUT, source_id="owner", locator="scenario-insight"
    )
    current = replace(
        current,
        needs=tuple(
            replace(
                item,
                sources=canonical_requirement_sources(
                    (*item.sources, need_source), require_items=True
                ),
            )
            for item in current.needs
        ),
        scenarios=tuple(
            replace(
                item,
                sources=canonical_requirement_sources(
                    (*item.sources, scenario_source), require_items=True
                ),
            )
            for item in current.scenarios
        ),
    )
    request = change_request(current)
    context, sources, twins = requirements_context(request)
    assert {sources["source:1"], sources["source:2"]} == {need_source, scenario_source}
    draft = RequirementsDraft.model_validate(context["current_requirements"])
    assert bind_requirements(draft, request, sources, twins) == current
    assert {context["evidence"][key]["locator"] for key in ("source:1", "source:2")} == {
        "need-insight",
        "scenario-insight",
    }


def test_change_preserves_surviving_need_and_scenario_ids():
    request = change_request()
    current = request.current_specification
    context, sources, twins = requirements_context(request)
    answer = deepcopy(context["current_requirements"])
    answer["needs"][0]["statement"] = "Record the reservation without duplicating the room booking."
    answer["scenarios"][0]["context"] = (
        "The receptionist serves a guest while reviewing availability."
    )
    changed = bind_requirements(RequirementsDraft.model_validate(answer), request, sources, twins)
    assert changed.needs[0].id == current.needs[0].id
    assert changed.scenarios[0].id == current.scenarios[0].id
    assert changed.requirements == current.requirements
    assert changed.user_stories == current.user_stories


@pytest.mark.parametrize(
    "group,field", [("scenarios", "context"), ("scenarios", "goal"), ("needs", "statement")]
)
def test_new_text_fields_enforce_the_two_thousand_character_cap(group, field):
    request = change_request()
    answer = deepcopy(requirements_context(request)[0]["current_requirements"])
    answer[group][0][field] = "x" * 2001
    with pytest.raises(ValidationError):
        RequirementsDraft.model_validate(answer)


@pytest.mark.parametrize("missing", ["needs", "context", "goal", "sources", "criticalities"])
def test_an_incomplete_legacy_model_answer_is_rejected_without_adaptation(missing):
    request = change_request()
    answer = deepcopy(requirements_context(request)[0]["current_requirements"])
    if missing == "needs":
        answer.pop("needs")
    else:
        answer["scenarios"][0].pop(missing)
    with pytest.raises(ValidationError):
        RequirementsDraft.model_validate(answer)


def test_fake_explicit_legacy_change_preserves_ids_and_untouched_texts():
    legacy = legacy_projection(generated_specification())
    request = change_request(legacy)
    changed = fake(request).specification
    assert legacy.schema_version == 1 and changed.schema_version == 2
    assert [item.id for item in changed.requirements] == [item.id for item in legacy.requirements]
    assert [item.id for item in changed.scenarios] == [item.id for item in legacy.scenarios]
    assert changed.requirements[1].statement == legacy.requirements[1].statement
    for before, after in zip(legacy.scenarios, changed.scenarios, strict=True):
        assert replace(after, context=None, goal=None, criticalities=(), sources=()) == before
    assert changed.needs and all(item.need_ids for item in changed.user_stories)


def test_a_legacy_change_adds_the_scenario_required_by_an_existing_story():
    request = with_twins(proposal_request(), 2)
    legacy = legacy_projection(fake(request).specification)
    legacy = replace(legacy, scenarios=(legacy.scenarios[0],))
    request = replace(request, current_specification=legacy, owner_request="Export reservations")
    changed = fake(request).specification
    assert changed.schema_version == 2
    assert len(changed.scenarios) == 2
    assert changed.scenarios[0].id == legacy.scenarios[0].id
    assert [item.id for item in changed.user_stories] == [item.id for item in legacy.user_stories]
    assert {item.actor for item in changed.scenarios} == {
        item.user_twin_reference for item in changed.user_stories
    }


def test_all_seven_change_lists_get_two_slots_above_the_current_count():
    request = proposal_request()
    answer, sources, twins = at_limits(request)
    specification = bind_requirements(
        RequirementsDraft.model_validate(answer), request, sources, twins
    )
    request = replace(
        request, current_specification=specification, owner_request="Review reservations"
    )
    assert requirements_limits(request) == {
        name: len(getattr(specification, name)) + 2 for name in requirements_limits(request)
    }


def test_schema_two_design_view_uses_codes_and_keeps_the_three_grounding_indexes():
    legacy = design_fixtures.requirements_version()
    definition = definition_version(legacy)
    view = design_requirements_view(definition)
    specification = definition.specification
    assert sha256(canonical_json(view)) == DEFINITION_DESIGN_VIEW_SHA256
    assert view["schema_version"] == 2
    assert view["needs"][0]["scenario_ids"] == ["SCN-001"]
    assert view["requirements"][0]["need_ids"] == ["NED-001"]
    assert view["stories"][0]["need_ids"] == ["NED-001"]
    assert view["scenarios"][0]["context"] == specification.scenarios[0].context
    assert view["scenarios"][0]["goal"] == specification.scenarios[0].goal
    assert view["scenarios"][0]["criticalities"] == list(specification.scenarios[0].criticalities)
    semantic = canonical_json({key: value for key, value in view.items() if key != "reference"})
    assert all(
        str(item.id) not in semantic
        for group in (specification.scenarios, specification.needs)
        for item in group
    )
    assert set(requirement_code_map(specification)) == {"REQ-001", "USR-001", "AC-001"}
    old, new = create_design_grounding(legacy), create_design_grounding(definition)
    assert (new.requirement_ids, new.user_story_ids, new.acceptance_criterion_ids) == (
        old.requirement_ids,
        old.user_story_ids,
        old.acceptance_criterion_ids,
    )
    assert new.requirements_reference.content_hash == definition.content_hash
    assert new.requirements_reference != old.requirements_reference


def test_schema_one_design_view_retains_its_complete_historical_fingerprint():
    view = design_requirements_view(design_fixtures.requirements_version())
    assert sha256(canonical_json(view)) == LEGACY_DESIGN_VIEW_SHA256
    assert "needs" not in view and "schema_version" not in view
    assert "context" not in view["scenarios"][0]
    assert "need_ids" not in view["requirements"][0]


def test_realignment_on_schema_two_does_not_expand_prototype_coverage():
    definition = definition_version()
    specification = definition.specification
    extra = replace(
        specification.requirements[0],
        id=UUID(int=0x9999),
        code="REQ-002",
        statement="Export the reservation as a document.",
    )
    specification = replace(specification, requirements=(*specification.requirements, extra))
    definition = replace(
        definition, specification=specification, content_hash=specification.content_hash
    )
    package = design_fixtures.design_package(selected=True, include_prototype=True)
    assert missing_item_ids(package, definition) == frozenset()
    assert uncovered_requirement_codes(package, definition) == ("REQ-002",)
    aligned = realign_design(package, definition)
    assert aligned.prototype is package.prototype
    assert uncovered_requirement_codes(aligned, definition) == ("REQ-002",)


def test_schema_two_mockup_keeps_missing_and_uncovered_requirement_indexes():
    definition = definition_version(mockup_fixtures.requirements_with_a_new_requirement())
    package = mockup_fixtures.design_package()
    assert package.generated_mockup is not None
    assert missing_item_ids(package, definition) == frozenset()
    assert uncovered_requirement_codes(package, definition) == ("REQ-003", "REQ-004")
    aligned = realign_design(package, definition)
    assert aligned.generated_mockup is package.generated_mockup
    assert uncovered_requirement_codes(aligned, definition) == ("REQ-003", "REQ-004")
    removed = definition_version(mockup_fixtures.requirements_without_a_cited_requirement())
    assert missing_item_ids(package, removed) == frozenset(
        {
            mockup_fixtures.NIGHT_REPORT,
            mockup_fixtures.NIGHT_REPORT_STORY,
            mockup_fixtures.NIGHT_REPORT_CRITERION,
        }
    )


@pytest.mark.parametrize("purpose", ["baseline", "change"])
def test_requirements_generation_uses_version_six_and_the_actual_full_schema(tmp_path, purpose):
    request = proposal_request() if purpose == "baseline" else change_request()
    _, sources, twins = requirements_context(request)
    specification = (
        generated_specification() if purpose == "baseline" else request.current_specification
    )
    generator, transport = make_generator(
        tmp_path, requirements_view(specification, sources, twins)
    )
    result = asyncio.run(ModelRequirementsAdapter(generator).propose(request))
    [call] = transport.calls
    schema = call["payload"]["response_format"]["json_schema"]
    assert result.specification.schema_version == 2
    assert schema["name"] == "proposal-requirements-v6"
    assert (
        call["payload"]["metadata"]["orchestwin_prompt_version_ref"] == "proposal-requirements-v6"
    )
    assert sha256(canonical_json(schema["schema"])) == REQUIREMENTS_SCHEMA_SHA256[purpose]
    if purpose == "change":
        assert result.specification == request.current_specification


def test_design_generation_reads_definition_two_and_binds_only_approved_design_codes(tmp_path):
    request = design_request_fixtures.proposal_request()
    definition = definition_version(request.requirements.version)
    request = replace(request, requirements=replace(request.requirements, version=definition))
    expected = design_request_fixtures.propose(request).package
    generator, transport = make_generator(tmp_path, proposal_draft("design", expected, request))
    result = asyncio.run(ModelDesignAdapter(generator).propose(request))
    assert result.package.grounding == create_design_grounding(definition)
    assert result.package.grounding.requirements_reference.content_hash == definition.content_hash
    assert set(requirement_code_map(definition.specification)) == {
        "REQ-001",
        "USR-001",
        "USR-002",
        "AC-001",
    }
    assert transport.calls


def test_test_plan_keeps_version_five_and_its_actual_schema_and_instruction(tmp_path):
    generator, transport = make_generator(tmp_path, plan_output())
    context = planning_context()
    asyncio.run(plan_tests(generator, context))
    [call] = transport.calls
    payload = call["payload"]
    schema = payload["response_format"]["json_schema"]
    assert schema["name"] == "proposal-requirements-v5"
    assert payload["metadata"]["orchestwin_prompt_version_ref"] == "proposal-requirements-v5"
    assert sha256(canonical_json(schema["schema"])) == TEST_PLAN_SCHEMA_SHA256
    assert sha256(PLAN_INSTRUCTION) == TEST_PLAN_INSTRUCTION_SHA256
    assert schema["schema"]["$defs"]["PlanNotCovered"]["properties"]["criterion"]["enum"] == list(
        CRITERIA
    )


def test_test_plan_material_carries_the_definition_chain_without_extra_criteria():
    definition = definition_version()
    output = material(requirements=definition)
    assert output["requirements"]["needs"][0]["scenario_ids"] == ["SCN-001"]
    assert output["requirements"]["reference"]["content_hash"] == definition.content_hash
    assert [item["code"] for item in output["acceptance_criteria"]] == ["AC-001"]
    context = planning_context(material=output, criteria_codes=("AC-001", "AC-999"))
    assert [item["code"] for item in context["acceptance_criteria"]] == ["AC-001"]
