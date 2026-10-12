from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.design_opinions import DesignOpinionRequest
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.artifacts.design_change_targets import DESIGN_CHANGE_TARGET_INVALID
from src.test.python.api.test_design_change_api import application

from .support.fake_studio import COSTS, OPINION_FIELDS, OPINION_TEXTS, PREFIX, FakeStudio
from .test_fake_studio_routes import EMAIL, PREFER, poll, signed

OPINIONS = "/design/opinions"
RUN_KEYS = [
    "run_id",
    "design_version_id",
    "design_content_hash",
    "design_version_number",
    "request",
    "target",
    "locale",
    "requested_at",
    "opinions",
    "contrast",
    "cost_microusd",
]
OPINION_KEYS = [
    "twin_id",
    "twin_version",
    "twin_name",
    "verdict",
    "why",
    "what_to_do",
    "try_this",
    "profile_keys",
    "confidence",
    "generation_id",
]
COLOURED = {"it": "Fai la barra rossa con il testo blu e bianco", "en": "Use red and blue"}
BODY_REFUSALS = (
    ({"request": 5}, ["body", "request"], "string_type"),
    ({"request": "   "}, ["body", "request"], "value_error"),
    ({"request": "x" * 1001}, ["body", "request"], "value_error"),
    ({"target": None}, ["body", "target"], "model_attributes_type"),
    ({"target": {}}, ["body", "target", "screen_code"], "missing"),
    ({"locale": "x"}, ["body", "locale"], "string_too_short"),
    ({"other": 1}, ["body", "other"], "extra_forbidden"),
)


def opinion_body(project, **values) -> dict[str, object]:
    current = project.current("design")
    screen = current["package"]["prototype"]["screens"][0]
    return {
        "design_version_id": current["id"],
        "design_content_hash": current["content_hash"],
        "request": "Make the main button larger",
        "target": {"screen_code": screen["code"], "element_code": screen["elements"][0]["code"]},
        "locale": "en-US",
        **values,
    }


def test_the_fields_of_an_opinion_are_those_of_the_real_request() -> None:
    assert tuple(DesignOpinionRequest.model_fields) == OPINION_FIELDS


@pytest.mark.parametrize("language", ["it", "en"])
def test_an_opinion_gives_one_verdict_for_each_twin_and_is_listed_first(language: str) -> None:
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        status, plain = client.call("POST", base + OPINIONS, opinion_body(project))
        _, coloured = client.call(
            "POST", base + OPINIONS, opinion_body(project, request=COLOURED[language])
        )
        _, listed = client.call("GET", base + OPINIONS)
        purposes = [item["purpose"] for item in project.usage[:4]]
        assert status == 201, plain
        assert list(plain) == RUN_KEYS
        assert all(list(item) == OPINION_KEYS for item in plain["opinions"])
        assert [item["verdict"] for item in plain["opinions"]] == ["SLOWS", "HELPS"]
        assert [item["verdict"] for item in coloured["opinions"]] == ["BLOCKS", "HELPS"]
        assert [item["try_this"] for item in plain["opinions"]] == [
            OPINION_TEXTS[language]["try_this"],
            None,
        ]
        assert plain["target"] == opinion_body(project)["target"]
        assert plain["design_version_number"] == project.current("design")["version_number"]
        assert plain["cost_microusd"] == 2 * COSTS["DESIGN_CHANGE_OPINION"]
        assert plain["contrast"]["control_border_threshold"] == 3.0
        assert [item["run_id"] for item in listed["items"]] == [
            coloured["run_id"],
            plain["run_id"],
        ]
        assert purposes == ["DESIGN_CHANGE_OPINION"] * 4
        assert studio.errors == []


def test_the_job_key_of_an_opinion_is_the_key_of_the_real_application() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        body = opinion_body(project, request="  Make the main button  larger ")
        status, started = client.call("POST", base + OPINIONS, body, headers=PREFER)
        assert (status, started["operation"]) == (202, "DESIGN_CHANGE_OPINION"), started
        assert studio._jobs[started["job_id"]].key == request_key(
            GenerationOperation.DESIGN_CHANGE_OPINION,
            {"project_id": project.id},
            DesignOpinionRequest.model_validate(body),
        )
        finished = poll(client, base, started["job_id"])
        assert finished["status"] == "SUCCEEDED", finished
        assert finished["response"]["status_code"] == 201
        assert finished["response"]["body"]["request"] == "Make the main button larger"
        assert studio.errors == []


def test_invalid_opinions_answer_like_the_real_application() -> None:
    with TestClient(application(None)) as real, FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        for values, location, kind in BODY_REFUSALS:
            body = opinion_body(project, **values)
            expected = {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]}
            answer = real.post(PREFIX + base + OPINIONS, json=body)
            assert (answer.status_code, answer.json()) == (422, expected), values
            assert client.call("POST", base + OPINIONS, body) == (422, expected), values
        missing = {key: value for key, value in opinion_body(project).items() if key != "target"}
        answer = real.post(PREFIX + base + OPINIONS, json=missing)
        assert answer.status_code == 422
        assert client.call("POST", base + OPINIONS, missing) == (422, answer.json())
        assert project.opinions == []
        assert studio.errors == []


def test_a_part_that_the_mockup_lacks_or_a_design_that_changed_is_refused() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        refused = (422, {"detail": {"code": DESIGN_CHANGE_TARGET_INVALID}})
        for target in (
            {"screen_code": "SCR-009"},
            {"screen_code": "SCR-001", "element_code": "ELM-999"},
            {"screen_code": "SCR-001", "element_code": "ZON-099"},
        ):
            sent = opinion_body(project, target=target)
            assert client.call("POST", base + OPINIONS, sent) == refused, target
        changed = client.call(
            "POST", base + OPINIONS, opinion_body(project, design_content_hash="0" * 64)
        )
        assert changed == (409, {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}})
        studio.hosted = False
        silent = client.call("POST", base + OPINIONS, opinion_body(project))
        assert silent == (503, {"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}})
        assert project.opinions == []
        assert studio.errors == []
