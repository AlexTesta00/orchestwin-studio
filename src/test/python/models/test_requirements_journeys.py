from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from orchestwin.artifacts.design_packages import create_design_grounding
from orchestwin.models.design_drafts import requirement_code_map
from orchestwin.models.design_drafts import requirements_view as design_view
from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.models.model_proposals import ModelRequirementsAdapter
from orchestwin.models.planning_schema import constrain_planning_schema
from orchestwin.models.requirements_drafts import (
    REQUIREMENTS_JOURNEYS_INSTRUCTION,
    RequirementsDraft,
    bind_requirements,
    requirements_context,
    requirements_limits,
    requirements_view,
)
from orchestwin.projects.requirements_primitives import (
    RequirementSourceKind,
    RequirementSourceReference,
    canonical_json,
    canonical_requirement_sources,
)

from .test_fake_requirements import proposal_request
from .test_model_proposals import make_generator
from .test_requirements_change_proposals import (
    FAKE_RESULT_SHA256,
    REQUEST_SHA256,
    base_version,
    change_request,
    generated_specification,
    legacy_projection,
    sha256,
)
from .test_requirements_limits import with_twins
from .test_test_planning import material, planning_context

JOURNEY_CONTEXT_SHA256 = "f88c602d06279d40887fd34270869aebc9abe20e7258f6cd1a2b0c827028a5af"
JOURNEY_SCHEMA_SHA256 = "df1be0443272ceeb448e103e5032d42c8b8658315f8bdacb6f818d82e16b4a45"
JOURNEY_SPECIFICATION_SHA256 = "b4ebd3dd6d75567795bc56c6f868f7ced2d698f0b02a6ad1b2cd264b4e04d4c5"


def requested(current=None):
    return replace(change_request(current), include_journeys=True)


def fake(request):
    return asyncio.run(FakeDeterministicRequirementsAdapter().propose(request))


def answer_for(request):
    _, sources, twins = requirements_context(request)
    specification = fake(request).specification
    return requirements_view(specification, sources, twins), sources, twins


def bind(answer, request, sources, twins):
    return bind_requirements(RequirementsDraft.model_validate(answer), request, sources, twins)


@pytest.mark.parametrize("value", [None, 0, 1, "true", "false", (), []])
def test_include_journeys_is_a_strict_boolean(value):
    with pytest.raises(ValueError, match="include_journeys must be a boolean"):
        replace(proposal_request(), include_journeys=value)


def test_journey_generation_requires_an_explicit_change_and_preserves_false_request_hash():
    request = proposal_request()
    assert request.include_journeys is False
    assert "include_journeys" not in request.to_snapshot()
    assert request.content_hash == REQUEST_SHA256
    with pytest.raises(ValueError, match="current specification and owner request"):
        replace(request, include_journeys=True)
    explicit = requested()
    assert explicit.to_snapshot()["include_journeys"] is True
    assert explicit.content_hash != change_request().content_hash


def test_ordinary_generation_keeps_prior_context_specification_and_fake_fingerprints():
    request = proposal_request()
    context, _, _ = requirements_context(request)
    result = fake(request)
    assert "include_journeys" not in context and "current_schema_version" not in context
    assert "journeys" not in context["limits"]
    assert "journeys" not in result.specification.to_snapshot()
    assert result.specification.journeys == ()
    assert result.content_hash == FAKE_RESULT_SHA256
    schema = RequirementsDraft.model_json_schema()
    constrain_planning_schema(schema, context, "requirements")
    assert schema["properties"]["journeys"]["maxItems"] == 0


def test_fake_journey_only_is_reproducible_and_preserves_every_other_schema_two_item():
    request = requested()
    first, second = fake(request), fake(request)
    proposed = first.specification
    assert first == second
    assert proposed.journeys
    assert replace(proposed, journeys=()) == request.current_specification
    assert proposed.content_hash == JOURNEY_SPECIFICATION_SHA256
    scenarios = {item.id: item for item in proposed.scenarios}
    needs = {item.id: item for item in proposed.needs}
    for journey in proposed.journeys:
        scenario = scenarios[journey.scenario_id]
        assert tuple(phase.action for phase in journey.phases) == scenario.steps
        assert all(phase.touchpoint is None for phase in journey.phases)
        assert all(
            journey.scenario_id in needs[value].scenario_ids
            for phase in journey.phases
            for value in phase.need_ids
        )
        assert set(scenario.sources) <= set(journey.sources)


def test_fake_explicit_legacy_journey_enrichment_preserves_existing_identity_and_text():
    current = legacy_projection(generated_specification())
    request = requested(current)
    proposed = fake(request).specification
    assert proposed.schema_version == 2 and proposed.journeys
    for before, after in zip(current.requirements, proposed.requirements, strict=True):
        assert replace(after, need_ids=()) == before
    for before, after in zip(current.user_stories, proposed.user_stories, strict=True):
        assert replace(after, need_ids=()) == before
    for before, after in zip(current.scenarios, proposed.scenarios, strict=True):
        assert replace(after, context=None, goal=None, criticalities=(), sources=()) == before
    assert proposed.acceptance_criteria == current.acceptance_criteria
    assert proposed.risks == current.risks
    assert proposed.definition_of_done == current.definition_of_done


def test_a_second_explicit_request_preserves_existing_journey_codes_and_ids():
    current = fake(requested()).specification
    request = requested(current)
    answer, sources, twins = answer_for(request)
    answer["journeys"][0]["phases"][0]["action"] = "Review the reservation details before saving."
    proposed = bind(answer, request, sources, twins)
    assert proposed.journeys[0].id == current.journeys[0].id
    assert proposed.journeys[0].code == current.journeys[0].code
    assert replace(proposed, journeys=current.journeys) == current
    assert fake(request).specification == current


def test_ordinary_changes_keep_existing_journeys_exactly():
    current = fake(requested()).specification
    request = change_request(current)
    proposed = fake(request).specification
    assert proposed.journeys == current.journeys
    answer, sources, twins = answer_for(request)
    assert bind(answer, request, sources, twins) == proposed
    schema = RequirementsDraft.model_json_schema()
    constrain_planning_schema(schema, requirements_context(request)[0], "requirements")
    assert schema["properties"]["journeys"]["minItems"] == 1
    assert schema["properties"]["journeys"]["maxItems"] == 1
    assert "journeys" in schema["required"]


@pytest.mark.parametrize("change", ["remove", "rename", "new-code", "phase"])
def test_ordinary_changes_cannot_remove_or_rewrite_journeys(change):
    current = fake(requested()).specification
    request = change_request(current)
    answer, sources, twins = answer_for(request)
    if change == "remove":
        answer["journeys"] = []
    elif change == "rename":
        answer["journeys"][0]["title"] = "A different journey"
    elif change == "new-code":
        answer["journeys"][0]["code"] = "JRN-002"
    else:
        answer["journeys"][0]["phases"][0]["action"] = "A different action"
    with pytest.raises(ValueError, match="unrequested journeys must remain unchanged"):
        bind(answer, request, sources, twins)


def test_a_baseline_cannot_accept_spontaneous_journeys_from_a_provider():
    explicit = requested()
    answer, _, _ = answer_for(explicit)
    request = proposal_request()
    _, sources, twins = requirements_context(request)
    with pytest.raises(ValueError, match="unrequested journeys must remain unchanged"):
        bind(answer, request, sources, twins)


@pytest.mark.parametrize(
    "group,field",
    [
        ("requirements", "statement"),
        ("user_stories", "goal"),
        ("acceptance_criteria", "statement"),
        ("scenarios", "context"),
        ("needs", "statement"),
        ("risks", "summary"),
        ("definition_of_done", "statement"),
    ],
)
def test_journey_only_cannot_change_any_other_schema_two_collection(group, field):
    request = requested()
    answer, sources, twins = answer_for(request)
    answer[group][0][field] = "An unrelated change to existing content."
    with pytest.raises(ValueError, match="journey-only request must preserve the rest"):
        bind(answer, request, sources, twins)


def test_journey_only_cannot_change_a_source_of_an_existing_requirement():
    request = requested()
    answer, sources, twins = answer_for(request)
    answer["requirements"][0]["sources"] = ["brief:goals[0]"]
    with pytest.raises(ValueError, match="journey-only request must preserve the rest"):
        bind(answer, request, sources, twins)


def test_explicit_journey_request_requires_at_least_one_journey_and_keeps_existing_ones():
    current = fake(requested()).specification
    request = requested(current)
    answer, sources, twins = answer_for(request)
    answer["journeys"] = []
    with pytest.raises(ValueError, match="requires at least one journey"):
        bind(answer, request, sources, twins)
    answer, sources, twins = answer_for(request)
    answer["journeys"][0]["code"] = "JRN-002"
    with pytest.raises(ValueError, match="existing journeys must retain their identities"):
        bind(answer, request, sources, twins)


def test_journey_phase_needs_must_belong_to_the_expanded_scenario():
    baseline = with_twins(proposal_request(), 2)
    current = fake(baseline).specification
    request = replace(
        baseline,
        current_specification=current,
        owner_request="Request journeys",
        include_journeys=True,
    )
    answer, sources, twins = answer_for(request)
    answer["journeys"][0]["phases"][0]["needs"] = ["NED-002"]
    with pytest.raises(ValueError):
        bind(answer, request, sources, twins)


@pytest.mark.parametrize("field,value", [("scenario", "SCN-999"), ("sources", ["invented source"])])
def test_journey_references_resolve_only_exact_known_codes_and_sources(field, value):
    request = requested()
    answer, sources, twins = answer_for(request)
    answer["journeys"][0][field] = value
    with pytest.raises(ValueError, match="unknown draft reference"):
        bind(answer, request, sources, twins)


@pytest.mark.parametrize("field", ["action", "touchpoint", "criticalities"])
def test_phase_text_is_bounded_at_two_thousand_characters(field):
    request = requested()
    answer, _, _ = answer_for(request)
    answer["journeys"][0]["phases"][0][field] = (
        ["x" * 2001] if field == "criticalities" else "x" * 2001
    )
    with pytest.raises(ValidationError):
        RequirementsDraft.model_validate(answer)


@pytest.mark.parametrize("count", [0, 33])
def test_journey_phases_have_one_to_thirty_two_items(count):
    request = requested()
    answer, _, _ = answer_for(request)
    answer["journeys"][0]["phases"] = [
        deepcopy(answer["journeys"][0]["phases"][0]) for _ in range(count)
    ]
    with pytest.raises(ValidationError):
        RequirementsDraft.model_validate(answer)


def test_journey_limit_tracks_scenario_ceiling_and_binder_checks_it():
    request = requested()
    assert (
        requirements_limits(request)["journeys"] == requirements_limits(request)["scenarios"] == 3
    )
    answer, sources, twins = answer_for(request)
    answer["journeys"] = [
        {**deepcopy(answer["journeys"][0]), "code": f"JRN-{index:03d}"} for index in range(1, 5)
    ]
    with pytest.raises(ValueError, match="draft list journeys exceeds its limit of 3"):
        bind(answer, request, sources, twins)


def test_historical_sources_cited_only_by_a_journey_remain_available_in_change_context():
    current = fake(requested()).specification
    source = RequirementSourceReference(
        kind=RequirementSourceKind.OWNER_INPUT, source_id="owner", locator="journey-observation"
    )
    journey = replace(
        current.journeys[0],
        sources=canonical_requirement_sources(
            (*current.journeys[0].sources, source), require_items=True
        ),
    )
    current = replace(current, journeys=(journey,))
    request = change_request(current)
    context, sources, twins = requirements_context(request)
    assert sources["source:1"] == source
    assert "source:1" in context["current_requirements"]["journeys"][0]["sources"]
    assert bind(context["current_requirements"], request, sources, twins) == current


def test_design_semantic_journey_links_use_codes_and_keep_the_three_grounding_indexes():
    request = requested()
    current = request.current_specification
    proposed = fake(request).specification
    before, after = (
        create_design_grounding(base_version(current)),
        create_design_grounding(base_version(proposed)),
    )
    assert (before.requirement_ids, before.user_story_ids, before.acceptance_criterion_ids) == (
        after.requirement_ids,
        after.user_story_ids,
        after.acceptance_criterion_ids,
    )
    assert before.requirements_reference != after.requirements_reference
    assert set(requirement_code_map(current)) == set(requirement_code_map(proposed))
    view = design_view(base_version(proposed))
    assert view["journeys"][0]["scenario_id"] == "SCN-001"
    assert view["journeys"][0]["phases"][0]["need_ids"] == ["NED-001"]
    semantic = canonical_json(view["journeys"])
    assert str(proposed.journeys[0].id) not in semantic
    assert str(proposed.scenarios[0].id) not in semantic
    assert "journeys" not in design_view(base_version(current))


def test_model_receives_explicit_journey_schema_seven_and_keeps_other_content(tmp_path):
    request = requested()
    context, _, _ = requirements_context(request)
    answer, _, _ = answer_for(request)
    generator, transport = make_generator(tmp_path, answer)
    result = asyncio.run(ModelRequirementsAdapter(generator).propose(request))
    schema = transport.calls[0]["payload"]["response_format"]["json_schema"]
    assert schema["name"] == "proposal-requirements-v7"
    assert sha256(canonical_json(schema["schema"])) == JOURNEY_SCHEMA_SHA256
    assert sha256(canonical_json(context)) == JOURNEY_CONTEXT_SHA256
    assert "journeys" in schema["schema"]["required"]
    assert schema["schema"]["properties"]["journeys"]["minItems"] == 1
    assert schema["schema"]["$defs"]["JourneyDraft"]["properties"]["scenario"]["enum"] == [
        "SCN-001"
    ]
    assert schema["schema"]["$defs"]["JourneyPhaseDraft"]["properties"]["needs"]["items"][
        "enum"
    ] == ["NED-001"]
    assert (
        REQUIREMENTS_JOURNEYS_INSTRUCTION in transport.calls[0]["payload"]["messages"][0]["content"]
    )
    assert replace(result.specification, journeys=()) == request.current_specification


def test_test_plan_material_adds_journey_context_without_inventing_criteria():
    current = fake(requested()).specification
    output = material(requirements=base_version(current))
    assert output["requirements"]["journeys"][0]["scenario_id"] == "SCN-001"
    assert {item["code"] for item in output["acceptance_criteria"]} == {
        item.code for item in current.acceptance_criteria
    }
    context = planning_context(material=output, criteria_codes=("AC-001", "AC-999"))
    assert [item["code"] for item in context["acceptance_criteria"]] == ["AC-001"]
