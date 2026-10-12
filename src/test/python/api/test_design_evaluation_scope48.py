from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestwin.api.design_loop import DesignEvaluationRequest, DesignEvaluationScope
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.artifacts.design_evaluation import (
    DESIGN_EVALUATION_SCOPE_INVALID,
    ELEMENT_SCOPE,
    PARTS_SCOPE,
    ZONE_SCOPE,
    DesignEvaluationError,
    DesignReviewScope,
    design_review_anchors,
    design_review_scope,
)
from orchestwin.evaluation.proposer_evaluator import (
    INSTRUCTION,
    SCOPE_SENTENCE,
    TWIN_REVIEW_PROMPT_VERSION,
    scope_sentence,
    scoped_prompt_version,
    twin_review_instruction,
)
from src.test.python.api import test_design_loop_api as loop
from src.test.python.api.test_design_change_api import application
from src.test.python.api.test_design_evaluation_scope43 import PATH, body_of, scoped
from src.test.python.api.test_design_review_pins import generated_version
from src.test.python.artifacts import design_fixtures

ZONE = {"screen_code": "SCR-001", "element_code": "ZON-006"}
PARTS = {"screen_code": "SCR-001", "element_codes": ["ELM-017", "ZON-006"]}
SCREEN_PLACE = "SCR-001 Prestiti in corso"
ZONE_PLACE = f"{SCREEN_PLACE} · ZON-006 Filtri del registro"
PARTS_PLACE = f"{SCREEN_PLACE} · ELM-017 Prestiti da controllare, ZON-006 Filtri del registro"
ZONE_SUBJECT = (
    'the zone ZON-006 "Filtri del registro" of the screen SCR-001, which holds the elements '
    "ELM-018, ELM-019"
)
PARTS_SUBJECT = (
    'these parts of the screen SCR-001: the element ELM-017 "Prestiti da controllare", '
    'the zone ZON-006 "Filtri del registro"'
)
CODES_REFUSALS = (
    (
        {"screen_code": "SCR-001", "element_codes": ["ELM-017"]},
        ["body", "scope", "element_codes"],
        "too_short",
    ),
    (
        {"screen_code": "SCR-001", "element_codes": [f"ELM-{n:03d}" for n in range(1, 10)]},
        ["body", "scope", "element_codes"],
        "too_long",
    ),
    (
        {"screen_code": "SCR-001", "element_codes": ["ZON-06", "ELM-017"]},
        ["body", "scope", "element_codes", 0],
        "string_pattern_mismatch",
    ),
    (
        {"screen_code": "SCR-001", "element_codes": "ZON-006"},
        ["body", "scope", "element_codes"],
        "list_type",
    ),
    (
        {"screen_code": "SCR-001", "element_codes": ["ZON-006", "ZON-006"]},
        ["body", "scope"],
        "value_error",
    ),
    (
        {
            "screen_code": "SCR-001",
            "element_code": "ELM-017",
            "element_codes": ["ZON-006", "ELM-018"],
        },
        ["body", "scope"],
        "value_error",
    ),
    (
        {"screen_code": "SCR-001", "element_code": "ZON-0000006"},
        ["body", "scope", "element_code"],
        "string_pattern_mismatch",
    ),
)


def scope_of(version, scope):
    return design_review_scope(
        version,
        screen_code=scope["screen_code"],
        element_code=scope.get("element_code"),
        element_codes=tuple(scope.get("element_codes", ())),
    )


def test_the_scope_of_a_review_names_its_parts_after_the_single_element():
    version = generated_version()
    assert tuple(DesignEvaluationScope.model_fields) == (
        "screen_code",
        "element_code",
        "element_codes",
    )
    bodies = [
        DesignEvaluationRequest.model_validate({**body_of(version), "scope": scope})
        for scope in ({"screen_code": "SCR-001", "element_code": "ELM-017"}, ZONE, PARTS)
    ]
    element, zone, parts = (body.model_dump(mode="json")["scope"] for body in bodies)
    assert element == {"screen_code": "SCR-001", "element_code": "ELM-017"}
    assert zone == ZONE
    assert parts == {**PARTS, "element_code": None}
    keys = {
        request_key(GenerationOperation.DESIGN_EVALUATION, {"project_id": version.project_id}, body)
        for body in bodies
    }
    assert len(keys) == 3


def test_an_invalid_list_of_parts_is_refused_at_once():
    version = generated_version()
    with TestClient(application(None)) as client:
        for scope, location, kind in CODES_REFUSALS:
            answer = client.post(PATH, json={**body_of(version), "scope": scope})
            assert (answer.status_code, answer.json()) == (
                422,
                {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]},
            ), scope
        for scope in (ZONE, PARTS):
            assert client.post(PATH, json={**body_of(version), "scope": scope}).status_code == 503


def test_a_zone_or_several_parts_are_reviewed_from_their_screen():
    version = generated_version()
    assert scope_of(version, ZONE) == DesignReviewScope(
        screen_code="SCR-001",
        element_code=None,
        label="Filtri del registro",
        place=ZONE_PLACE,
        kind=ZONE_SCOPE,
        parts=(("ZON-006", "Filtri del registro"),),
        holds=("ELM-018", "ELM-019"),
    )
    assert scope_of(version, PARTS) == DesignReviewScope(
        screen_code="SCR-001",
        element_code=None,
        label="Prestiti in corso",
        place=PARTS_PLACE,
        kind=PARTS_SCOPE,
        parts=(("ELM-017", "Prestiti da controllare"), ("ZON-006", "Filtri del registro")),
    )
    assert {scope_of(version, scope).anchor_key for scope in (ZONE, PARTS)} == {"SCR-001"}
    element = scope_of(version, {"screen_code": "SCR-001", "element_code": "ELM-018"})
    assert element == DesignReviewScope(
        "SCR-001", "ELM-018", "Lettore o titolo", f"{SCREEN_PLACE} · ELM-018 Lettore o titolo"
    )
    assert (element.kind, element.parts, element.holds) == (ELEMENT_SCOPE, (), ())


@pytest.mark.parametrize(
    "scope",
    [
        {"screen_code": "SCR-001", "element_code": "ZON-099"},
        {"screen_code": "SCR-001", "element_code": "ZON-008"},
        {"screen_code": "SCR-001", "element_codes": ["ELM-017", "ELM-036"]},
        {"screen_code": "SCR-001", "element_codes": ["ZON-006", "ZON-099"]},
    ],
    ids=["zone", "zone-elsewhere", "part-elsewhere", "zone-part"],
)
def test_a_zone_or_a_part_that_the_applied_mockup_lacks_is_refused(scope):
    with pytest.raises(DesignEvaluationError, match=DESIGN_EVALUATION_SCOPE_INVALID):
        scope_of(generated_version(), scope)


def test_a_zone_needs_a_generated_mockup():
    declarative = design_fixtures.design_version()
    assert declarative.package.generated_mockup is None
    for scope in (
        {"screen_code": "SCR-001", "element_code": "ZON-001"},
        {"screen_code": "SCR-001", "element_codes": ["ELM-001", "ZON-001"]},
    ):
        with pytest.raises(DesignEvaluationError, match=DESIGN_EVALUATION_SCOPE_INVALID):
            scope_of(declarative, scope)
    parts = scope_of(
        declarative, {"screen_code": "SCR-001", "element_codes": ["ELM-001", "ELM-002"]}
    )
    assert (parts.kind, [code for code, _label in parts.parts]) == (
        PARTS_SCOPE,
        ["ELM-001", "ELM-002"],
    )


def test_the_twins_are_told_which_zone_or_which_parts_the_owner_changed():
    version = generated_version()
    zone = scope_of(version, ZONE)
    parts = scope_of(version, PARTS)
    assert scope_sentence(zone) == SCOPE_SENTENCE.format(subject=ZONE_SUBJECT, anchor="SCR-001")
    assert scope_sentence(parts) == SCOPE_SENTENCE.format(subject=PARTS_SUBJECT, anchor="SCR-001")
    assert twin_review_instruction(hosted=False, scope=zone) == (
        f"{INSTRUCTION} {scope_sentence(zone)}"
    )
    element = scope_of(version, {"screen_code": "SCR-001", "element_code": "ELM-018"})
    assert scope_sentence(element) == SCOPE_SENTENCE.format(
        subject='the element ELM-018 "Lettore o titolo" of the screen SCR-001',
        anchor="SCR-001/ELM-018",
    )


def test_the_screen_of_a_zone_or_of_several_parts_is_described_by_their_place():
    version = generated_version()
    plain = design_review_anchors(version)
    for scope, place in ((ZONE, ZONE_PLACE), (PARTS, PARTS_PLACE)):
        anchors = design_review_anchors(version, scope=scope_of(version, scope))
        assert list(anchors) == list(plain)
        assert anchors == {**plain, "SCR-001": place}
    element = scope_of(version, {"screen_code": "SCR-001", "element_code": "ELM-018"})
    assert design_review_anchors(version, scope=element) == plain
    assert plain["SCR-001"] == SCREEN_PLACE


@pytest.mark.parametrize(("scope", "place"), [(ZONE, ZONE_PLACE), (PARTS, PARTS_PLACE)])
def test_a_review_of_a_zone_or_of_several_parts_reaches_the_twins_from_their_screen(
    monkeypatch, scope, place
):
    version = generated_version()
    app, body, generator, evidence = loop.reviewing(
        monkeypatch, loop.review(anchor="SCR-001"), version=version
    )

    run = loop.evaluate(app, scoped(body, **scope)).run

    [call] = generator.calls
    assert call["instruction"] == f"{INSTRUCTION} {scope_sentence(scope_of(version, scope))}"
    assert run.evaluator.prompt_version_ref == scoped_prompt_version(TWIN_REVIEW_PROMPT_VERSION)
    [finding] = run.to_snapshot()["responses"][0]["findings"]
    assert (finding["anchor_key"], finding["location"]) == ("SCR-001", place)
    assert "element_code" not in finding
    assert evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]


def test_a_review_of_a_zone_that_the_design_lacks_is_refused_before_the_twins(monkeypatch):
    app, body, generator, _evidence = loop.reviewing(
        monkeypatch, loop.review(anchor="SCR-001"), version=generated_version()
    )
    with pytest.raises(HTTPException) as failure:
        loop.evaluate(app, scoped(body, screen_code="SCR-002", element_code="ZON-006"))
    assert (failure.value.status_code, failure.value.detail) == (
        422,
        {"code": DESIGN_EVALUATION_SCOPE_INVALID},
    )
    assert (generator.calls, loop.MemoryRuns.runs) == ([], [])
