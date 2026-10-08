from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.design_loop import DesignEvaluationRequest, DesignEvaluationScope
from orchestwin.api.generation_jobs import GenerationOperation
from orchestwin.api.generation_requests import request_key
from orchestwin.artifacts.design_evaluation import (
    DESIGN_EVALUATION_SCOPE_INVALID,
    anchor_element,
    design_evaluation_run_from_snapshot,
    synthetic_finding_from_snapshot,
)
from orchestwin.evaluation.proposer_evaluator import scoped_prompt_version
from src.test.python.api.test_design_change_api import application
from src.test.python.api.test_design_evaluation_scope43 import SCOPE_REFUSALS

from .support.fake_studio import (
    EVALUATION_FIELDS,
    EVALUATOR,
    PREFIX,
    SCOPE_FIELDS,
    SCOPED_FINDINGS,
    FakeStudio,
)
from .test_fake_studio_routes import EMAIL, PREFER, poll, signed

EVALUATIONS = "/design/evaluations"


def review_body(project, **values) -> dict[str, object]:
    current = project.current("design")
    return {
        "design_version_id": current["id"],
        "design_content_hash": current["content_hash"],
        **values,
    }


def pointed(project) -> dict[str, object]:
    screen = next(
        item
        for item in project.current("design")["package"]["prototype"]["screens"]
        if item["elements"]
    )
    return {"screen_code": screen["code"], "element_code": screen["elements"][-1]["code"]}


def findings_of(run) -> list[dict[str, object]]:
    return [finding for response in run["responses"] for finding in response["findings"]]


def test_the_fields_of_a_review_and_of_its_scope_are_those_of_the_real_request() -> None:
    assert tuple(DesignEvaluationRequest.model_fields) == EVALUATION_FIELDS
    assert tuple(DesignEvaluationScope.model_fields) == SCOPE_FIELDS


@pytest.mark.parametrize("language", ["it", "en"])
def test_a_scoped_review_answers_with_the_element_of_each_finding(language: str) -> None:
    with FakeStudio(language=language, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        scope = pointed(project)
        key = f"{scope['screen_code']}/{scope['element_code']}"
        status, run = client.call("POST", base + EVALUATIONS, review_body(project, scope=scope))
        assert status == 201, run
        summary, severity, criterion, action = SCOPED_FINDINGS[language]
        for response in run["responses"]:
            assert response["evaluator"]["prompt_version_ref"] == (
                scoped_prompt_version(EVALUATOR["prompt_version_ref"])
            )
            first = response["findings"][0]
            assert (first["anchor_key"], first["element_code"]) == (key, scope["element_code"])
            assert (first["summary"], first["severity"], first["criterion"]) == (
                summary,
                severity,
                criterion,
            )
            assert first["recommended_action"] == action
        for finding in findings_of(run):
            assert finding.get("element_code") == anchor_element(str(finding["anchor_key"]))
            assert synthetic_finding_from_snapshot(finding).to_snapshot() == finding
        assert design_evaluation_run_from_snapshot(run).to_snapshot() == run
        status, whole = client.call("POST", base + EVALUATIONS, review_body(project))
        assert status == 201, whole
        assert all("element_code" not in finding for finding in findings_of(whole))
        assert {item["evaluator"]["prompt_version_ref"] for item in whole["responses"]} == {
            EVALUATOR["prompt_version_ref"]
        }
        _, listed = client.call("GET", base + EVALUATIONS)
        assert [item["id"] for item in listed] == [whole["id"], run["id"]]
        assert studio.errors == []


def test_the_comparison_of_the_fake_leaves_out_the_reviews_of_a_changed_element() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        scope = pointed(project)
        _, first = client.call("POST", base + EVALUATIONS, review_body(project))
        client.call("POST", base + EVALUATIONS, review_body(project, scope=scope))
        status, refused = client.call("GET", base + EVALUATIONS + "/comparison")
        assert (status, refused) == (
            404,
            {"detail": {"code": "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"}},
        )
        _, second = client.call("POST", base + EVALUATIONS, review_body(project))
        client.call("POST", base + EVALUATIONS, review_body(project, scope=scope))
        status, comparison = client.call("GET", base + EVALUATIONS + "/comparison")
        assert status == 200, comparison
        assert (comparison["base_run_id"], comparison["head_run_id"]) == (first["id"], second["id"])
        assert studio.errors == []


def test_a_scope_that_the_design_lacks_is_refused_like_the_real_application() -> None:
    with FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        screens = project.current("design")["package"]["prototype"]["screens"]
        elsewhere = next(item for item in screens[1:] if item["elements"])["elements"][0]["code"]
        for scope in (
            {"screen_code": "SCR-099"},
            {"screen_code": screens[0]["code"], "element_code": "ELM-999"},
            {"screen_code": screens[0]["code"], "element_code": elsewhere},
        ):
            answer = client.call("POST", base + EVALUATIONS, review_body(project, scope=scope))
            assert answer == (422, {"detail": {"code": DESIGN_EVALUATION_SCOPE_INVALID}}), scope
        assert project.runs == []
        assert studio.errors == []


def test_invalid_scopes_answer_like_the_real_application() -> None:
    with TestClient(application(None)) as real, FakeStudio(job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        cases = [
            (review_body(project, scope=scope), location, kind)
            for scope, location, kind in SCOPE_REFUSALS
        ]
        cases.append(
            (
                review_body(project, mode="STATIC_CHECK", scope={"screen_code": "SCR-001"}),
                ["body"],
                "value_error",
            )
        )
        for body, location, kind in cases:
            expected = {"detail": "invalid_request", "errors": [{"loc": location, "type": kind}]}
            answer = real.post(PREFIX + base + EVALUATIONS, json=body)
            assert (answer.status_code, answer.json()) == (422, expected), body
            assert client.call("POST", base + EVALUATIONS, body) == (422, expected), body
        assert project.runs == []
        assert studio.errors == []


def test_a_scoped_review_needs_the_model_that_plays_the_twins() -> None:
    with FakeStudio(hosted=False, job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Calcolo mancia", through="design")
        base = f"/projects/{project.id}"
        scoped = client.call(
            "POST", base + EVALUATIONS, review_body(project, scope={"screen_code": "SCR-001"})
        )
        whole = client.call("POST", base + EVALUATIONS, review_body(project))
        assert scoped == (503, {"detail": {"code": "DESIGN_REVIEWER_NOT_CONFIGURED"}})
        assert whole == (503, {"detail": {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"}})
        assert studio.errors == []


def test_the_job_key_of_a_scoped_review_is_the_key_of_the_real_application() -> None:
    with FakeStudio(language="en", job_polls=0) as studio:
        client = signed(studio)
        project = studio.seed_project(owner=EMAIL, name="Tip calculator", through="design")
        base = f"/projects/{project.id}"
        scope = pointed(project)
        bodies = [
            review_body(project),
            review_body(project, scope=scope),
            review_body(project, scope={"screen_code": scope["screen_code"]}),
            review_body(project, mode="TWIN_REVIEW", locale="en-US", scope=scope),
        ]
        keys = []
        for body in bodies:
            status, started = client.call("POST", base + EVALUATIONS, body, headers=PREFER)
            assert (status, started["operation"]) == (202, "DESIGN_EVALUATION"), started
            key = studio._jobs[started["job_id"]].key
            assert key == request_key(
                GenerationOperation.DESIGN_EVALUATION,
                {"project_id": project.id},
                DesignEvaluationRequest.model_validate(body),
            )
            keys.append(key)
            finished = poll(client, base, started["job_id"])
            assert finished["status"] == "SUCCEEDED", finished
        assert len(set(keys)) == len(bodies)
        assert studio.errors == []
