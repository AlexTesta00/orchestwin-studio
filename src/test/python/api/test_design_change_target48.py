from __future__ import annotations

import asyncio
import hashlib
import json
import re
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.design import (
    DesignChangeRequest,
    DesignChangeTargetElementRequest,
    DesignChangeTargetRequest,
)
from orchestwin.api.design_iterations import (
    REQUESTED_TARGET,
    DesignIterationApplication,
    IterationRequest,
)
from orchestwin.api.design_mockups import MockupCommandError
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.artifacts.design_change_targets import (
    DESIGN_CHANGE_TARGET_INVALID,
    describe_target,
)
from orchestwin.artifacts.generated_mockup_zones import ZONE_ATTRIBUTE, derive_zones
from orchestwin.models.design_change import (
    INSTRUCTION,
    TARGET_FIELDS,
    TARGET_PART_FIELDS,
    DesignChangeTarget,
    DesignChangeTargetElement,
    target_sentence,
)
from orchestwin.models.generated_mockup_instructions import (
    target_sentence as mockup_target_sentence,
)
from orchestwin.projects.design_change_application import (
    DesignChangeIssueCode,
    DesignChangeStatus,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.api import test_design_review_pins as pins
from src.test.python.api.test_design_change_api import (
    ASYNC,
    CALL,
    CHANGES,
    JOBS,
    OWNER_REQUEST,
    PROJECT,
    ScriptedChanges,
    answered,
    application,
    created,
    refused,
)
from src.test.python.api.test_design_iterations_api import (
    ITERATIONS,
    applied_versions,
    iterate,
    request_body,
)
from src.test.python.api.test_generated_mockup_api import MOCKUPS, client_for
from src.test.python.artifacts import design_fixtures
from src.test.python.models.test_generated_mockup_support import (
    GUIDED_ID,
    OWNER_ID,
    PROJECT_ID,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    applied_package,
    iteration_payload,
    requirements_version,
    runtime,
    version,
)
from src.test.python.projects.test_design_change_application import Harness

ZONE_BODY = {"screen_code": "SCR-003", "element_code": "ZON-013", "label": "  Dati   personali "}
ZONE_SNAPSHOT = {"screen_code": "SCR-003", "element_code": "ZON-013", "label": "Dati personali"}
ZONE_DOMAIN = DesignChangeTarget(
    screen_code="SCR-003", element_code="ZON-013", label="Dati personali"
)
PARTS_BODY = {
    "screen_code": "SCR-001",
    "elements": [{"element_code": "ELM-018", "label": " Continua "}, {"element_code": "ZON-003"}],
}
PARTS_SNAPSHOT = {
    "screen_code": "SCR-001",
    "elements": [{"element_code": "ELM-018", "label": "Continua"}, {"element_code": "ZON-003"}],
}
ELEMENT = {"screen_code": "SCR-001", "element_code": "ELM-018"}
FIRST = {"element_code": "ELM-018"}
SECOND = {"element_code": "ZON-003"}
OPINION = "00000000-0000-4000-8000-0000000048a1"
REFUSED = {"detail": {"code": DESIGN_CHANGE_TARGET_INVALID}}
PART_REFUSALS = (
    ({"screen_code": "SCR-001", "elements": [FIRST]}, ["body", "target", "elements"], "too_short"),
    (
        {
            "screen_code": "SCR-001",
            "elements": [{"element_code": f"ELM-{number:03d}"} for number in range(1, 10)],
        },
        ["body", "target", "elements"],
        "too_long",
    ),
    (
        {"screen_code": "SCR-001", "elements": "ELM-018"},
        ["body", "target", "elements"],
        "list_type",
    ),
    (
        {"screen_code": "SCR-001", "elements": [{"element_code": "ZON-03"}, SECOND]},
        ["body", "target", "elements", 0, "element_code"],
        "string_pattern_mismatch",
    ),
    (
        {"screen_code": "SCR-001", "elements": [{**FIRST, "kind": "zone"}, SECOND]},
        ["body", "target", "elements", 0, "kind"],
        "extra_forbidden",
    ),
    (
        {"screen_code": "SCR-001", "elements": [{**FIRST, "label": " "}, SECOND]},
        ["body", "target", "elements", 0, "label"],
        "value_error",
    ),
    (
        {"screen_code": "SCR-001", "elements": [FIRST, {**FIRST, "label": "Continua"}]},
        ["body", "target"],
        "value_error",
    ),
    (
        {"screen_code": "SCR-001", "element_code": "ELM-018", "elements": [FIRST, SECOND]},
        ["body", "target"],
        "value_error",
    ),
    (
        {"screen_code": "SCR-001", "label": "Continua", "elements": [FIRST, SECOND]},
        ["body", "target"],
        "value_error",
    ),
    (
        {"screen_code": "SCR-001", "element_code": "ZON-0000003"},
        ["body", "target", "element_code"],
        "string_pattern_mismatch",
    ),
)


def refusal(location, kind):
    return {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]}


def applied_mockup():
    return applied_package().generated_mockup.mockup


def guided_answer(alternative):
    [workflow] = alternative.workflows
    return {
        "accessibility_considerations": list(alternative.accessibility_considerations),
        "advantages": list(alternative.advantages),
        "assumptions": list(alternative.assumptions),
        "changes": ["Il riepilogo dei dati personali ora separa nome e contatti."],
        "information_architecture": list(alternative.information_architecture),
        "open_questions": list(alternative.open_questions),
        "rationale": alternative.rationale,
        "security_considerations": list(alternative.security_considerations),
        "summary": "Una direzione di progetto con un riepilogo dei dati personali più chiaro.",
        "trade_offs": list(alternative.trade_offs),
        "workflows": [
            {
                "code": workflow.code,
                "requirement_codes": ["REQ-001"],
                "steps": list(workflow.steps),
                "title": workflow.title,
            }
        ],
    }


def applied_harness(*outcomes):
    return Harness(
        *outcomes, version=version(applied_package()), requirements=requirements_version()
    )


def change(harness, target):
    return asyncio.run(
        harness.service.request_change(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=PROJECT_ID,
            owner_request="Rendi più chiaro il riepilogo dei dati personali.",
            locale="it-IT",
            target=target,
        )
    )


def test_the_fields_of_a_target_and_of_its_parts_follow_the_contract():
    assert tuple(DesignChangeTargetRequest.model_fields) == TARGET_FIELDS
    assert tuple(DesignChangeTargetElementRequest.model_fields) == TARGET_PART_FIELDS
    assert tuple(IterationRequest.model_fields)[-2:] == ("critique_source_id", "opinion_id")
    parts = DesignChangeTargetRequest.model_validate(PARTS_BODY).to_domain()
    assert parts == DesignChangeTarget(
        screen_code="SCR-001",
        elements=(
            DesignChangeTargetElement(element_code="ELM-018", label="Continua"),
            DesignChangeTargetElement(element_code="ZON-003"),
        ),
    )
    assert parts.to_snapshot() == PARTS_SNAPSHOT
    assert DesignChangeTargetRequest.model_validate(ZONE_BODY).to_domain() == ZONE_DOMAIN


def test_a_target_of_today_keeps_its_body_and_the_key_of_its_job():
    today = {
        "screen_code": "SCR-001",
        "element_code": "ELM-018",
        "label": "Continua",
        "html": '<a data-elm="ELM-018">Continua</a>',
    }
    aimed = DesignChangeRequest.model_validate({"request": OWNER_REQUEST, "target": today})
    screen = DesignChangeRequest.model_validate(
        {"request": OWNER_REQUEST, "target": {"screen_code": "SCR-001"}}
    )
    parts = DesignChangeRequest.model_validate({"request": OWNER_REQUEST, "target": PARTS_BODY})
    assert aimed.model_dump(mode="json") == {"request": OWNER_REQUEST, "target": today}
    assert screen.model_dump(mode="json")["target"] == {
        "screen_code": "SCR-001",
        "element_code": None,
        "label": None,
        "html": None,
    }
    digest = hashlib.sha256(
        canonical_json({"request": OWNER_REQUEST, "target": today}).encode("utf-8")
    ).hexdigest()
    keys = [
        request_key(GenerationOperation.DESIGN_CHANGE, {"project_id": str(PROJECT)}, body)
        for body in (aimed, screen, parts)
    ]
    assert keys[0] == f"DESIGN_CHANGE:{digest}"
    assert len(set(keys)) == 3
    assert parts.model_dump(mode="json")["target"]["elements"] == [
        {"element_code": "ELM-018", "label": "Continua", "html": None},
        {"element_code": "ZON-003", "label": None, "html": None},
    ]


@pytest.mark.parametrize(("target", "location", "kind"), PART_REFUSALS)
def test_an_invalid_zone_or_part_is_refused_at_once_on_both_routes(target, location, kind):
    service = ScriptedChanges(created())
    versions = applied_versions()
    generator = ScriptedMockupGenerator()
    iterations, registry = client_for(runtime(generator, versions=versions))
    body = {"request": OWNER_REQUEST, "target": target}

    with TestClient(application(service)) as client:
        synchronous = client.post(CHANGES, json=body)
        preferred = client.post(CHANGES, json=body, headers=ASYNC)
        jobs = client.get(JOBS).json()
    with iterations:
        iterated = iterations.post(f"{ITERATIONS}/jobs", json=request_body(versions, target=target))

    assert (synchronous.status_code, synchronous.json()) == (422, refusal(location, kind))
    assert answered(preferred) == answered(synchronous)
    assert (iterated.status_code, iterated.json()["detail"][0]["loc"]) == (422, location)
    assert (jobs, service.calls, len(registry), generator.calls) == ({"items": []}, [], 0, [])


@pytest.mark.parametrize(
    "target",
    [
        {"screen_code": "SCR-009"},
        {"screen_code": "SCR-002", "element_code": "ELM-018"},
        {"screen_code": "SCR-001", "element_code": "ZON-013"},
        {"screen_code": "SCR-001", "element_code": "ZON-099"},
        {"screen_code": "SCR-001", "elements": [FIRST, {"element_code": "ELM-019"}]},
        {"screen_code": "SCR-001", "elements": [{"element_code": "ZON-099"}, SECOND]},
    ],
    ids=["screen", "element-elsewhere", "zone-elsewhere", "zone", "part", "zone-part"],
)
def test_an_iteration_on_a_code_that_the_applied_mockup_lacks_is_refused_before_any_job(target):
    versions = applied_versions()
    generator = ScriptedMockupGenerator()
    client, registry = client_for(runtime(generator, versions=versions))

    with client:
        response = client.post(f"{ITERATIONS}/jobs", json=request_body(versions, target=target))

    assert (response.status_code, response.json()) == (422, REFUSED)
    assert (len(registry), generator.calls) == (0, [])


def test_the_job_of_an_iteration_checks_the_codes_again_before_the_model():
    versions = applied_versions()
    generator = ScriptedMockupGenerator()
    store = MemoryMockupStore()
    app = DesignIterationApplication(runtime(generator, store, versions))
    body = IterationRequest.model_validate(
        request_body(versions, target={"screen_code": "SCR-001", "element_code": "ZON-099"})
    )

    with pytest.raises(MockupCommandError) as failure:
        asyncio.run(
            app.generate_iteration(owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=body)
        )

    assert (failure.value.status_code, failure.value.detail) == (422, REFUSED["detail"])
    assert (generator.calls, store.order) == ([], [])


def test_an_iteration_on_a_zone_gives_the_model_the_zone_that_the_studio_reads():
    versions = applied_versions()
    store = MemoryMockupStore()
    generator = ScriptedMockupGenerator(answer(iteration_payload()))
    client, registry = client_for(runtime(generator, store, versions))

    with client:
        _started, done = iterate(client, registry, versions, target=ZONE_BODY)
        [item] = client.get(ITERATIONS).json()["items"]

    assert done["status"] == "SUCCEEDED", done["failure"]
    assert done["result"]["changes"] == [
        "Modifica mirata a ZON-013 di SCR-003",
        *iteration_payload()["changes"],
    ]
    [call] = generator.calls
    context = call["context"]
    view = describe_target(ZONE_SNAPSHOT, applied_mockup())
    assert context["target"] == view
    assert (view["kind"], view["label"], view["holds"]) == (
        "section",
        "Dati personali",
        ["ELM-042", "ELM-043", "ELM-044", "ELM-045", "ELM-046", "ELM-047"],
    )
    assert f'{ZONE_ATTRIBUTE}="ZON-013"' in view["html"]
    keys = list(context)
    assert keys.index("target") == keys.index("owner_request") + 1
    assert (keys[-1], context[REQUESTED_TARGET]) == (REQUESTED_TARGET, ZONE_SNAPSHOT)
    assert mockup_target_sentence(view) in call["instruction"]
    assert view["html"] not in call["instruction"]
    assert store.context(store.order[0])[REQUESTED_TARGET] == ZONE_SNAPSHOT
    assert (item["target"], item["opinion_id"]) == (ZONE_SNAPSHOT, None)


def test_an_iteration_on_several_parts_reads_them_in_the_order_of_the_page():
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(iteration_payload()))
    client, registry = client_for(runtime(generator, MemoryMockupStore(), versions))

    with client:
        _started, done = iterate(client, registry, versions, target=PARTS_BODY)
        [item] = client.get(ITERATIONS).json()["items"]

    assert done["result"]["changes"][0] == "Modifica mirata a ELM-018 e ZON-003 di SCR-001"
    [call] = generator.calls
    context = call["context"]
    assert context["target"] == describe_target(PARTS_SNAPSHOT, applied_mockup())
    assert [
        (part["element_code"], part["kind"], part["label"])
        for part in context["target"]["elements"]
    ] == [
        ("ZON-003", "navigation", "Passaggi dell'iscrizione"),
        ("ELM-018", "element", "Continua"),
    ]
    assert context[REQUESTED_TARGET] == PARTS_SNAPSHOT
    assert mockup_target_sentence(context["target"]) in call["instruction"]
    assert item["target"] == PARTS_SNAPSHOT


def test_a_single_element_keeps_the_context_of_today_or_gets_its_texts_from_the_studio():
    present = {
        **ELEMENT,
        "label": "Continua",
        "html": '<a class="button button-primary" data-elm="ELM-018">Continua</a>',
    }
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(iteration_payload()), answer(iteration_payload()))
    client, registry = client_for(runtime(generator, MemoryMockupStore(), versions))

    with client:
        iterate(client, registry, versions, target=present)
        iterate(client, registry, versions, target=ELEMENT)
        listed = client.get(ITERATIONS).json()["items"]

    today, bare = generator.calls
    assert json.dumps(today["context"]["target"]) == json.dumps(present)
    assert REQUESTED_TARGET not in today["context"]
    assert bare["context"]["target"] == {
        **ELEMENT,
        "label": "Continua",
        "html": '<a class="button button-primary" data-elm="ELM-018" href="#SCR-002">Continua</a>',
    }
    assert bare["context"][REQUESTED_TARGET] == ELEMENT
    assert [item["target"] for item in listed] == [ELEMENT, present]


def test_the_opinion_of_the_twins_is_recorded_beside_the_request_and_listed():
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(iteration_payload()), answer(iteration_payload()))
    client, registry = client_for(runtime(generator, MemoryMockupStore(), versions))

    with client:
        iterate(client, registry, versions, target=ZONE_BODY, opinion_id=OPINION)
        iterate(client, registry, versions)
        listed = client.get(ITERATIONS).json()["items"]
        invalid = client.post(f"{ITERATIONS}/jobs", json=request_body(versions, opinion_id="x"))

    asked, plain = generator.calls
    assert asked["context"]["opinion_id"] == OPINION
    assert list(asked["context"])[-2:] == ["opinion_id", REQUESTED_TARGET]
    assert "opinion_id" not in plain["context"]
    assert [item["opinion_id"] for item in listed] == [None, OPINION]
    assert (invalid.status_code, invalid.json()["detail"][0]["loc"]) == (
        422,
        ["body", "opinion_id"],
    )
    plain_body = IterationRequest.model_validate(request_body(versions))
    asked_body = IterationRequest.model_validate(request_body(versions, opinion_id=OPINION))
    assert "opinion_id" not in plain_body.model_dump(mode="json")
    assert asked_body.model_dump(mode="json")["opinion_id"] == OPINION


def test_a_change_request_on_a_code_that_the_mockup_lacks_answers_422_in_both_ways():
    service = ScriptedChanges(refused(DesignChangeIssueCode.TARGET_INVALID)())
    app = application(service)
    body = {"request": OWNER_REQUEST, "target": ZONE_BODY}

    with TestClient(app, raise_server_exceptions=False) as client:
        synchronous = client.post(CHANGES, json=body)
        started = client.post(CHANGES, json=body, headers=ASYNC)
        job_id = started.json()["job_id"]
        client.portal.call(app.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()

    assert (synchronous.status_code, synchronous.json()) == (422, REFUSED)
    assert (job["status"], job["response"]) == ("FAILED", answered(synchronous))
    assert service.calls == [{**CALL, "target": ZONE_DOMAIN}] * 2


def test_the_change_service_refuses_an_absent_code_before_the_model():
    for target in (
        DesignChangeTarget(screen_code="SCR-003", element_code="ZON-099"),
        DesignChangeTarget(
            screen_code="SCR-001",
            elements=(DesignChangeTargetElement("ELM-018"), DesignChangeTargetElement("ELM-019")),
        ),
    ):
        harness = applied_harness()
        result = change(harness, target)
        assert (result.status, result.issue) == (
            DesignChangeStatus.REJECTED,
            DesignChangeIssueCode.TARGET_INVALID,
        )
        assert result.issue.value == DESIGN_CHANGE_TARGET_INVALID
        assert (harness.calls, harness.diffs.created) == ([], [])
    declarative = Harness()
    result = asyncio.run(
        declarative.service.request_change(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=design_fixtures.PROJECT_ID,
            owner_request=OWNER_REQUEST,
            target=ZONE_DOMAIN,
        )
    )
    assert result.issue is DesignChangeIssueCode.TARGET_INVALID
    assert declarative.calls == []


def test_a_change_on_a_zone_reaches_the_model_with_the_view_of_the_zone():
    alternative = next(item for item in applied_package().alternatives if item.id == GUIDED_ID)
    harness = applied_harness(guided_answer(alternative))

    result = change(harness, ZONE_DOMAIN)

    assert result.status is DesignChangeStatus.CREATED, result.issue
    assert result.changes == (
        "Modifica mirata a ZON-013 di SCR-003",
        "Il riepilogo dei dati personali ora separa nome e contatti.",
    )
    [call] = harness.calls
    view = describe_target(ZONE_SNAPSHOT, applied_mockup())
    assert call["context"]["target"] == view
    assert call["instruction"] == f"{INSTRUCTION} {target_sentence(view)}"
    assert view["html"] not in call["instruction"]


def test_the_document_numbers_the_zones_only_when_it_is_asked():
    versions = applied_versions()
    client, _registry = client_for(runtime(ScriptedMockupGenerator(), versions=versions))
    params = {"alternative_id": str(GUIDED_ID), "source": "applied"}

    with client:
        plain = client.get(f"{MOCKUPS}/document", params=params).json()
        unzoned = client.get(f"{MOCKUPS}/document", params={**params, "zones": "false"}).json()
        zoned = client.get(f"{MOCKUPS}/document", params={**params, "zones": "true"}).json()

    zones = derive_zones(applied_mockup())
    assert plain == unzoned
    assert ZONE_ATTRIBUTE not in plain["html"]
    assert zoned["html"].count(f'{ZONE_ATTRIBUTE}="') == len(zones) == 20
    assert re.sub(f' {ZONE_ATTRIBUTE}="ZON-[0-9]+"', "", zoned["html"]) == plain["html"]
    assert {key: value for key, value in zoned.items() if key not in ("html", "content_hash")} == {
        key: value for key, value in plain.items() if key not in ("html", "content_hash")
    }
    assert zoned["content_hash"] == hashlib.sha256(zoned["html"].encode("utf-8")).hexdigest()


def test_the_review_document_numbers_the_zones_only_when_it_is_asked(monkeypatch):
    current = pins.generated_version()
    http = pins.client(monkeypatch, runs=(pins.scenario_run(current),), versions=(current,))

    plain = http.get(f"{pins.PATH}/document").json()
    zoned = http.get(f"{pins.PATH}/document", params={"zones": "true"}).json()

    zones = derive_zones(current.package.generated_mockup.mockup)
    assert ZONE_ATTRIBUTE not in plain["html"]
    assert zoned["html"].count(f'{ZONE_ATTRIBUTE}="') == len(zones) == 22
    assert re.sub(f' {ZONE_ATTRIBUTE}="ZON-[0-9]+"', "", zoned["html"]) == plain["html"]
