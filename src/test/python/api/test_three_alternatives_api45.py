from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.api.design import DesignPackagePayload
from orchestwin.models.design_systems import APPLE_HIG, design_system_view
from orchestwin.models.generated_mockup_drafts import bind_generated_mockup
from orchestwin.models.generated_mockup_instructions import (
    DESIGN_SYSTEM_HEADING,
    ITERATION_SENTENCE,
    design_system_section,
)
from src.test.python.api.test_design_iterations_api import BROKEN, iterate
from src.test.python.api.test_generated_mockup_api import client_for, generated, without_command
from src.test.python.artifacts.test_visual_directions import SYSTEM_NAME, system_language
from src.test.python.models.test_generated_mockup_support import (
    DASHBOARD,
    DASHBOARD_ID,
    GUIDED,
    GUIDED_CODES,
    GUIDED_ID,
    DesignVersions,
    ScriptedMockupGenerator,
    alternative,
    answer,
    critique,
    draft,
    draft_payload,
    iteration_payload,
    package,
    requirements_version,
    runtime,
    with_markup,
)

SYSTEM_ID = UUID("00000000-0000-4000-8000-000000002412")
CODES = ("DES-001", "DES-002", "DES-003")
BROKEN_MOCKUP = with_markup(draft_payload(), "<h1>", "<h1>Lorem ipsum ")
OFF_CASES = ("turned off", "not in the runtime")


def system_alternative():
    base = alternative(GUIDED, SYSTEM_ID, "DES-003", GUIDED_CODES)
    return replace(base, visual_language=system_language(base.visual_language))


def three():
    base = package()
    return replace(
        base,
        alternatives=(*base.alternatives, system_alternative()),
        critiques=(*base.critiques, critique(SYSTEM_ID, "CRQ-003")),
    )


def applied(alternative_id):
    base = three()
    chosen = next(item for item in base.alternatives if item.id == alternative_id)
    binding = bind_generated_mockup(
        draft(GUIDED), alternative=chosen, requirements=requirements_version(), language="it"
    )
    return replace(
        base,
        owner_selected_alternative_id=alternative_id,
        prototype=binding.prototype,
        generated_mockup=binding.mockup,
    )


def studio(generator, versions, case="apple"):
    value = runtime(generator, versions=versions)
    if case != "not in the runtime":
        value.design_system = None if case == "turned off" else APPLE_HIG
    return client_for(value)


def asked_with_the_system(call):
    assert call["context"]["design_system"] == design_system_view(APPLE_HIG)
    assert call["instruction"].count(APPLE_HIG.instruction) == 1
    assert f"{DESIGN_SYSTEM_HEADING}{APPLE_HIG.name}" in call["instruction"]


def asked_without_the_system(call):
    assert "design_system" not in call["context"]
    assert APPLE_HIG.instruction not in call["instruction"]
    assert DESIGN_SYSTEM_HEADING not in call["instruction"]


def drawn(alternative_id, *outcomes, case="apple"):
    versions = DesignVersions(three())
    generator = ScriptedMockupGenerator(*outcomes)
    client, registry = studio(generator, versions, case)
    with client:
        done = generated(client, registry, versions, alternative_id)
    return done, generator.calls


def iterated(alternative_id, *outcomes, case="apple"):
    versions = DesignVersions(three(), applied(alternative_id))
    generator = ScriptedMockupGenerator(*outcomes)
    client, registry = studio(generator, versions, case)
    with client:
        started, done = iterate(client, registry, versions)
    assert started["alternative_id"] == str(alternative_id)
    return done, generator.calls


def test_only_the_third_of_the_three_alternatives_follows_the_design_system():
    proposed = three()
    third = proposed.alternatives[2]

    assert tuple(item.code for item in proposed.alternatives) == CODES
    assert [item.visual_language.design_system for item in proposed.alternatives] == [
        None,
        None,
        APPLE_HIG.identifier,
    ]
    assert third.id == SYSTEM_ID
    assert third.visual_language.direction.name == SYSTEM_NAME
    assert {name: third.visual_language.token_values[name] for name in APPLE_HIG.tokens} == dict(
        APPLE_HIG.tokens
    )
    assert all(item.visual_language.direction is None for item in proposed.alternatives[:2])


def test_only_the_mockup_of_the_third_alternative_is_asked_with_the_design_system():
    versions = DesignVersions(three())
    generator = ScriptedMockupGenerator(
        answer(draft_payload(GUIDED)), answer(draft_payload(DASHBOARD)), answer(draft_payload())
    )
    client, registry = studio(generator, versions)
    with client:
        done = [
            generated(client, registry, versions, alternative_id)
            for alternative_id in (GUIDED_ID, DASHBOARD_ID, SYSTEM_ID)
        ]

    assert [item["status"] for item in done] == ["SUCCEEDED"] * 3, [
        item["failure"] for item in done
    ]
    first, second, third = generator.calls
    asked_without_the_system(first)
    asked_without_the_system(second)
    asked_with_the_system(third)
    assert [call["context"]["alternative"]["code"] for call in generator.calls] == list(CODES)
    proposed = DesignPackagePayload.model_validate(done[2]["result"]["package"]).to_domain()
    assert proposed.owner_selected_alternative_id == SYSTEM_ID
    assert proposed.generated_mockup.design_alternative_id == SYSTEM_ID
    assert proposed.alternatives == versions.versions[-1].package.alternatives


def test_the_mockup_of_the_third_alternative_keeps_the_design_system_on_its_second_attempt():
    done, calls = drawn(SYSTEM_ID, answer(BROKEN_MOCKUP), answer(draft_payload()))

    assert done["status"] == "SUCCEEDED", done["failure"]
    first, second = calls
    assert "rejection" in second["context"]
    for call in (first, second):
        asked_with_the_system(call)


def test_an_iteration_of_the_third_alternative_carries_the_design_system_on_every_attempt():
    done, calls = iterated(SYSTEM_ID, answer(BROKEN), answer(iteration_payload()))

    assert done["status"] == "SUCCEEDED", done["failure"]
    first, second = calls
    assert "rejection" in second["context"]
    for call in (first, second):
        assert "current_mockup" in call["context"]
        assert ITERATION_SENTENCE in call["instruction"]
        asked_with_the_system(call)


def test_an_iteration_of_a_free_alternative_is_asked_without_the_design_system():
    done, calls = iterated(GUIDED_ID, answer(iteration_payload()))

    assert done["status"] == "SUCCEEDED", done["failure"]
    [call] = calls
    assert call["context"]["alternative"]["code"] == "DES-001"
    assert ITERATION_SENTENCE in call["instruction"]
    asked_without_the_system(call)


@pytest.mark.parametrize("case", OFF_CASES)
def test_without_the_design_system_in_the_studio_the_third_alternative_is_asked_as_before(case):
    mockup, (drawing,) = drawn(SYSTEM_ID, answer(draft_payload()), case=case)
    iteration, (changing,) = iterated(SYSTEM_ID, answer(iteration_payload()), case=case)

    assert [mockup["status"], iteration["status"]] == ["SUCCEEDED", "SUCCEEDED"]
    asked_without_the_system(drawing)
    asked_without_the_system(changing)
    assert ITERATION_SENTENCE in changing["instruction"]


@pytest.mark.parametrize("draw", [drawn, iterated])
def test_the_design_system_only_adds_its_section_and_its_view_to_the_third_alternative(draw):
    off_answer, on_answer = (
        (answer(draft_payload()), answer(draft_payload()))
        if draw is drawn
        else (answer(iteration_payload()), answer(iteration_payload()))
    )
    off_done, (off,) = draw(SYSTEM_ID, off_answer, case="turned off")
    on_done, (on,) = draw(SYSTEM_ID, on_answer)

    section = f" {design_system_section(APPLE_HIG)}"
    assert [off_done["status"], on_done["status"]] == ["SUCCEEDED", "SUCCEEDED"]
    assert on["instruction"].count(section) == 1
    assert on["instruction"].replace(section, "") == off["instruction"]
    assert without_command(on["context"]) == {
        **without_command(off["context"]),
        "design_system": design_system_view(APPLE_HIG),
    }
