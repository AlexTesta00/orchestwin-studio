from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.design import DesignChangeRequest, DesignChangeTargetRequest
from orchestwin.api.design_iterations import IterationRequest
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.models.design_change import TARGETED_CHANGE_TEXTS
from src.test.python.api.test_design_change_api import application

from .support.fake_studio import (
    ALIGNMENT_TEXTS,
    CHANGE_TARGET_FIELDS,
    DESIGN_CHANGE_FIELDS,
    ITERATION_CHANGES,
    ITERATION_FIELDS,
    PREFIX,
    FakeStudio,
)
from .test_fake_studio_routes import EMAIL, PREFER, chosen_alternative, poll, signed

TARGET = {
    "screen_code": "SCR-002",
    "element_code": "ELM-012",
    "label": "  Calcola \n la mancia ",
    "html": ' <button data-elm="ELM-012">Calcola</button>\n',
}
SNAPSHOT = {
    "screen_code": "SCR-002",
    "element_code": "ELM-012",
    "label": "Calcola la mancia",
    "html": '<button data-elm="ELM-012">Calcola</button>',
}
REQUESTS = {"it": "Ingrandisci il pulsante del calcolo.", "en": "Make the button larger."}
KEPT = {"it": "Il pulsante principale resta visibile", "en": "The main button stays visible"}
ITERATION_REQUEST = "Metti il pulsante in alto"
TARGET_REFUSALS = (
    ("SCR-002", ["body", "target"], "model_attributes_type"),
    ([], ["body", "target"], "model_attributes_type"),
    ({}, ["body", "target", "screen_code"], "missing"),
    ({"screen_code": 7}, ["body", "target", "screen_code"], "string_type"),
    ({"screen_code": "SCR-02"}, ["body", "target", "screen_code"], "string_pattern_mismatch"),
    ({"screen_code": "SCR-002\n"}, ["body", "target", "screen_code"], "string_pattern_mismatch"),
    (
        {"screen_code": "SCR-002", "element_code": "ELM-1"},
        ["body", "target", "element_code"],
        "string_pattern_mismatch",
    ),
    ({"screen_code": "SCR-002", "label": ""}, ["body", "target", "label"], "value_error"),
    ({"screen_code": "SCR-002", "label": "x" * 121}, ["body", "target", "label"], "value_error"),
    ({"screen_code": "SCR-002", "label": 5}, ["body", "target", "label"], "string_type"),
    ({"screen_code": "SCR-002", "html": " "}, ["body", "target", "html"], "value_error"),
    (
        {"screen_code": "SCR-002", "html": "<b>\u0000</b>"},
        ["body", "target", "html"],
        "value_error",
    ),
    ({"screen_code": "SCR-002", "html": "x" * 2049}, ["body", "target", "html"], "value_error"),
    ({"screen_code": "SCR-002", "other": 1}, ["body", "target", "other"], "extra_forbidden"),
)


def iteration_body(project, **values):
    current = project.current("design")
    return {
        "design_version_id": current["id"],
        "design_content_hash": current["content_hash"],
        "request": ITERATION_REQUEST,
        **values,
    }


def element_line(language):
    return TARGETED_CHANGE_TEXTS[language]["element"].format(element="ELM-012", screen="SCR-002")


def test_the_fields_and_the_texts_of_a_target_are_those_of_the_real_application() -> None:
    assert tuple(DesignChangeRequest.model_fields) == DESIGN_CHANGE_FIELDS
    assert tuple(DesignChangeTargetRequest.model_fields) == CHANGE_TARGET_FIELDS
    assert tuple(IterationRequest.model_fields) == ITERATION_FIELDS
    for language in ("it", "en"):
        texts = ALIGNMENT_TEXTS[language]
        assert texts["targeted_element"] == TARGETED_CHANGE_TEXTS[language]["element"]
        assert texts["targeted_screen"] == TARGETED_CHANGE_TEXTS[language]["screen"]


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_design_change_with_a_target_names_it_first_in_the_changes(language: str) -> None:
    request = REQUESTS[language]
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        chosen = chosen_alternative(project)
        status, payload = client.call(
            "POST", base + "/design/change-requests", {"request": request, "target": TARGET}
        )
        assert status == 201, payload
        assert payload["changes"] == [
            element_line(language),
            ALIGNMENT_TEXTS[language]["design_change"].format(
                title=chosen["title"], request=request
            ),
        ]
        assert payload["revision"]["diff"]["status"] == "PROPOSED"
        assert studio.errors == []


def test_the_job_key_of_a_targeted_change_is_the_key_of_the_real_application() -> None:
    body = {"request": REQUESTS["en"], "target": TARGET}
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        status, started = client.call(
            "POST", base + "/design/change-requests", body, headers=PREFER
        )
        assert (status, started["operation"]) == (202, "DESIGN_CHANGE")
        assert studio._jobs[started["job_id"]].key == request_key(
            GenerationOperation.DESIGN_CHANGE,
            {"project_id": project.id},
            DesignChangeRequest.model_validate(body),
        )
        finished = poll(client, base, started["job_id"])
        assert finished["status"] == "SUCCEEDED"
        assert finished["response"]["body"]["changes"][0] == element_line("en")
        assert studio.errors == []


@pytest.mark.parametrize("language", ["it", "en"])
def test_an_iteration_with_a_target_returns_it_beside_the_request(language: str) -> None:
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        body = iteration_body(project, target=TARGET, assertions=[KEPT[language]])
        status, started = client.call("POST", base + "/design/iterations/jobs", body)
        assert status == 202, started
        _, job = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
        assert job["status"] == "SUCCEEDED", job
        changes = [element_line(language), *ITERATION_CHANGES[language]]
        assert job["result"]["changes"] == changes
        _, listed = client.call("GET", base + "/design/iterations")
        [item] = listed["items"]
        assert list(item)[:4] == ["generation_id", "requested_at", "request", "target"]
        assert (item["request"], item["target"], item["status"]) == (
            ITERATION_REQUEST,
            SNAPSHOT,
            "PROPOSED",
        )
        assert item["changes"] == changes
        status, proposed = client.call(
            "POST", base + "/design/revisions", {"package": job["result"]["package"]}
        )
        assert status == 201, proposed
        status, decided = client.call(
            "POST",
            f"{base}/design/revisions/{proposed['diff']['id']}/decision",
            {"decision": "APPROVE"},
        )
        assert status == 200, decided
        _, after = client.call("GET", base + "/design/iterations")
        [applied] = after["items"]
        assert (applied["status"], applied["target"], applied["changes"]) == (
            "APPLIED",
            SNAPSHOT,
            changes,
        )
        assert studio.errors == []


def test_an_iteration_on_a_screen_or_without_a_target_keeps_the_shape_of_today() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        status, started = client.call(
            "POST",
            base + "/design/iterations/jobs",
            iteration_body(project, target={"screen_code": "SCR-001", "element_code": None}),
        )
        assert status == 202, started
        _, aimed = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
        status, started = client.call(
            "POST", base + "/design/iterations/jobs", iteration_body(project)
        )
        assert status == 202, started
        _, plain = client.call("GET", f"{base}/design/iterations/jobs/{started['job_id']}")
        _, listed = client.call("GET", base + "/design/iterations")
        assert aimed["result"]["changes"] == [
            "Targeted change to SCR-001",
            *ITERATION_CHANGES["en"],
        ]
        assert plain["result"]["changes"] == list(ITERATION_CHANGES["en"])
        assert [item["target"] for item in listed["items"]] == [None, {"screen_code": "SCR-001"}]
        assert studio.errors == []


def test_invalid_targets_answer_like_the_real_application() -> None:
    with TestClient(application(None)) as real, FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        routes = (
            ("/design/change-requests", {"request": REQUESTS["it"]}),
            ("/design/iterations/jobs", iteration_body(project)),
        )
        for path, body in routes:
            for target, location, kind in TARGET_REFUSALS:
                sent = {**body, "target": target}
                answer = real.post(PREFIX + base + path, json=sent)
                expected = {
                    "detail": "invalid_request",
                    "errors": [{"loc": location, "type": kind}],
                }
                assert (answer.status_code, answer.json()) == (422, expected), (path, target)
                assert client.call("POST", base + path, sent) == (422, expected), (path, target)
        assert project.iterations == []
        assert studio.errors == []
