from copy import deepcopy
from uuid import UUID

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.workflow_inputs import create_workflow_inputs_router, protect_provided_consumers
from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_CODE_UNAVAILABLE,
    PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE,
    PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE,
    PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE,
    PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE,
)
from src.test.python.api.test_artifact_why import OWNER_ID, PROJECT_ID, owner
from src.test.python.artifacts.test_workflow_runtime36 import (
    invoke,
    runtime_setup,
    supplied_request,
)

PATH = f"/projects/{PROJECT_ID}"


def browser(service, *, authenticated=True):
    app = FastAPI()
    app.state.identity_service = object()
    app.state.workflow_inputs_service = service
    app.include_router(create_workflow_inputs_router())
    if authenticated:
        app.dependency_overrides[current_user_dependency] = owner
    return TestClient(app)


def test_workflow_http_requires_authentication_and_masks_foreign_project(monkeypatch):
    setup = runtime_setup(monkeypatch)
    assert (
        browser(setup.service, authenticated=False).get(PATH + "/workflow-inputs").status_code
        == 401
    )
    client = browser(setup.service)
    foreign = f"/projects/{UUID(int=8000)}"
    for method, suffix, payload in (
        ("GET", "/workflow-inputs", None),
        ("GET", "/provided-prototypes/state", None),
        (
            "POST",
            "/workflow-inputs/decisions",
            {"target": "EVIDENCE", "action": "DECLARE_MISSING", "reason": "Missing."},
        ),
        ("POST", "/provided-prototypes", supplied_request()),
    ):
        response = client.request(method, foreign + suffix, json=payload)
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert setup.store.commits == 0
    assert all(entry[1] == OWNER_ID for entry in setup.store.audit if entry[0] == "owned")


@pytest.mark.parametrize(
    "payload,code",
    [
        ({"target": "EVIDENCE", "action": "DECLARE_MISSING"}, "WORKFLOW_REASON_INVALID"),
        (
            {
                "target": "EVIDENCE",
                "action": "DECLARE_MISSING",
                "reason": " ",
                "unexpected": "private text",
            },
            "WORKFLOW_RECORDS_INVALID",
        ),
        (
            {
                "target": "NOT_A_SECTION",
                "action": "DECLARE_MISSING",
                "reason": "Private synthetic source.",
            },
            "WORKFLOW_TARGET_INVALID",
        ),
    ],
)
def test_workflow_http_rejects_invalid_gap_without_echoing_input(monkeypatch, payload, code):
    setup = runtime_setup(monkeypatch)
    response = browser(setup.service).post(PATH + "/workflow-inputs/decisions", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": code}}
    assert not setup.store.decisions and setup.store.commits == 0


def test_workflow_http_roundtrips_gap_and_supplied_prototype_without_automatic_approval(
    monkeypatch,
):
    setup = runtime_setup(monkeypatch)
    client = browser(setup.service)
    decision = client.post(
        PATH + "/workflow-inputs/decisions",
        json={
            "target": "EVIDENCE",
            "action": "DECLARE_MISSING",
            "reason": "No interviews are available.",
        },
    )
    assert decision.status_code == 201
    request = supplied_request()
    original = deepcopy(request)
    response = client.post(PATH + "/provided-prototypes", json=request)
    assert response.status_code == 201 and request == original
    prototype = response.json()
    assert prototype["declared_origin"] == "Figma desktop"
    records = client.get(PATH + "/workflow-inputs").json()
    assert records["decisions"] == [decision.json()]
    assert records["prototypes"] == [prototype]
    assert client.get(PATH + "/provided-prototypes/current").json() == prototype
    state = client.get(PATH + "/provided-prototypes/state").json()
    assert state["source"] == "PROVIDED_PROTOTYPE" and not state["approved"]
    assert state["gate"] is None


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("hash", 409, "WORKFLOW_CONTEXT_CHANGED"),
        ("version", 409, "PROVIDED_PROTOTYPE_VERSION_CONFLICT"),
        ("screen", 422, "SCREEN_COUNT"),
        ("field", 422, "PROVIDED_PROTOTYPE_INPUT_INVALID"),
    ],
)
def test_prototype_http_preserves_conflict_and_input_error_codes(monkeypatch, case, status, code):
    setup = runtime_setup(monkeypatch)
    payload = supplied_request()
    if case == "hash":
        payload["expected_definition_reference"]["content_hash"] = "f" * 64
    elif case == "version":
        payload["expected_version_number"] = 9
    elif case == "screen":
        payload["mockup"]["screens"] = payload["mockup"]["screens"][:1]
    else:
        payload["unexpected"] = "private source"
    response = browser(setup.service).post(PATH + "/provided-prototypes", json=payload)
    assert response.status_code == status
    detail = {"code": code}
    if case == "screen":
        detail["message"] = "1 screens"
    elif case == "field":
        detail["message"] = "unknown prototype fields"
    assert response.json() == {"detail": detail}
    assert not setup.store.prototypes and setup.store.gate is None


def test_prototype_http_submission_and_approval_are_distinct_audited_actions(monkeypatch):
    setup = runtime_setup(monkeypatch)
    client = browser(setup.service)
    saved = client.post(PATH + "/provided-prototypes", json=supplied_request()).json()
    assert (
        client.post(
            PATH + "/provided-prototypes/gate/decision", json={"action": "APPROVE"}
        ).status_code
        == 409
    )
    submitted = client.post(PATH + "/provided-prototypes/gate/submit")
    assert submitted.status_code == 200 and submitted.json()["status"] == "PENDING_APPROVAL"
    assert not client.get(PATH + "/provided-prototypes/state").json()["approved"]
    approved = client.post(PATH + "/provided-prototypes/gate/decision", json={"action": "APPROVE"})
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"
    assert client.get(PATH + "/provided-prototypes/state").json()["approved"]
    assert [event.kind.value for event in setup.store.events] == ["SUBMIT", "APPROVE"]
    artifact = approved.json()["artifact"]
    assert artifact["artifact_id"] == saved["id"]
    assert (
        artifact["version"] == saved["version_number"]
        and artifact["content_hash"] == saved["content_hash"]
    )


@pytest.mark.parametrize(
    "payload",
    (
        {"action": "SUBMIT"},
        {"action": 12},
        {"action": "APPROVE", "reason": 123},
        {"reason": "Missing action"},
        {"action": "APPROVE", "extra": True},
    ),
)
def test_prototype_http_decision_rejects_submission_and_malformed_payloads_before_audit(
    monkeypatch, payload
):
    setup = runtime_setup(monkeypatch)
    invoke(setup, "save_prototype", request=supplied_request())
    invoke(setup, "gate_action", action="SUBMIT")
    previous = list(setup.store.events)
    response = browser(setup.service).post(
        PATH + "/provided-prototypes/gate/decision", json=payload
    )
    assert response.status_code == 422
    assert setup.store.events == previous


@pytest.mark.parametrize(
    "method,suffix,code",
    [
        ("POST", "/code-changes", PROVIDED_PROTOTYPE_CODE_UNAVAILABLE),
        ("POST", "/code-tasks", PROVIDED_PROTOTYPE_CODE_UNAVAILABLE),
        ("POST", "/design/reviews", PROVIDED_PROTOTYPE_REVIEW_UNAVAILABLE),
        ("POST", "/design/evaluations", PROVIDED_PROTOTYPE_EVALUATION_UNAVAILABLE),
        ("POST", "/design/iterations", PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE),
        ("GET", "/validation/walkthrough", PROVIDED_PROTOTYPE_WALKTHROUGH_UNAVAILABLE),
    ],
)
def test_each_supplied_design_consumer_rejects_before_calling_generated_service(
    monkeypatch, method, suffix, code
):
    setup = runtime_setup(monkeypatch)
    invoke(setup, "save_prototype", request=supplied_request())
    invoke(setup, "gate_action", action="SUBMIT")
    invoke(setup, "gate_action", action="APPROVE")
    calls = []

    async def generated_endpoint(project_id: UUID):
        calls.append(project_id)
        return {"generated": True}

    router = APIRouter()
    router.add_api_route("/projects/{project_id}" + suffix, generated_endpoint, methods=[method])
    app = FastAPI()
    app.state.workflow_inputs_service = setup.service
    app.include_router(protect_provided_consumers(router))
    app.dependency_overrides[current_user_dependency] = owner
    response = TestClient(app).request(method, PATH + suffix)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": code}}
    assert calls == []


def test_existing_exploration_consumer_remains_available_without_supplied_artifacts(monkeypatch):
    setup = runtime_setup(monkeypatch)
    calls = []

    async def generated_endpoint(project_id: UUID):
        calls.append(project_id)
        return {"generated": True}

    router = APIRouter()
    router.add_api_route(
        "/projects/{project_id}/design/reviews", generated_endpoint, methods=["POST"]
    )
    app = FastAPI()
    app.state.workflow_inputs_service = setup.service
    app.include_router(protect_provided_consumers(router))
    app.dependency_overrides[current_user_dependency] = owner
    response = TestClient(app).post(PATH + "/design/reviews")
    assert response.status_code == 200 and calls == [PROJECT_ID]
