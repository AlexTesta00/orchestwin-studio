"""Authenticated HTTP contract with real service/gates and explicit storage/Docker doubles."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.static_inspections import create_static_inspection_router

from .static_inspection_support import setup_service


@pytest.fixture
def harness(tmp_path):
    service, store, backend, args = setup_service(tmp_path)
    app = FastAPI()
    app.state.identity_service = SimpleNamespace()
    app.state.static_inspection_service = service
    app.include_router(create_static_inspection_router(), prefix="/api/v1")
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=store.owner)
    prefix = f"/api/v1/projects/{store.project}/static-browser-inspections"
    with TestClient(app) as client:
        yield app, client, store, backend, args, prefix


def request_body(backend, args):
    return {
        "request_id": str(args["request_id"]),
        "source_revision_id": str(backend.job.revision_id),
        "scenarios": [item.snapshot() for item in backend.job.scenarios],
    }


def test_http_prepare_approve_execute_and_read(harness):
    _, client, store, backend, args, prefix = harness
    prepared = client.post(prefix, json=request_body(backend, args))
    assert prepared.status_code == 201
    snapshot = prepared.json()["snapshot"]
    expected = {"expected_plan_content_hash": snapshot["plan"]["plan_content_hash"]}
    route = f"{prefix}/{args['request_id']}"
    assert client.post(route + "/execute", json=expected).status_code == 409
    decided = client.post(
        route + "/gate", json={**expected, "expected_gate_event_sequence": 1, "action": "APPROVE"}
    )
    assert decided.status_code == 200
    executed = client.post(route + "/execute", json=expected)
    assert executed.status_code == 200
    assert executed.json()["snapshot"]["result"]["assertion_status"] == "PASSED"
    assert client.get(route).json() == executed.json()
    assert len(client.get(prefix).json()["items"]) == 1
    assert len(backend.calls) == 1 and len(store.events) == 2


@pytest.mark.parametrize(
    "forged", ["owner_user_id", "runner_manifest", "command", "authorization_id"]
)
def test_body_cannot_supply_owner_host_path_command_or_authority(harness, forged):
    _, client, _, backend, args, prefix = harness
    response = client.post(prefix, json={**request_body(backend, args), forged: "untrusted"})
    assert response.status_code == 422
    assert backend.calls == []


def test_cross_owner_lookup_returns_not_found(harness):
    app, client, _, backend, args, prefix = harness
    assert client.post(prefix, json=request_body(backend, args)).status_code == 201
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=uuid4())
    assert client.get(prefix + "/" + str(args["request_id"])).status_code == 404


def test_registered_route_is_disabled_without_runtime(harness):
    app, client, _, _, _, prefix = harness
    app.state.static_inspection_service = None
    response = client.get(prefix)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "STATIC_INSPECTION_SERVICE_DISABLED"


def test_real_auth_dependency_remains_required(harness):
    app, client, _, _, _, prefix = harness
    app.dependency_overrides.clear()
    # No identity service is injected into this miniature app.
    response = client.get(prefix)
    assert response.status_code == 401
    assert response.status_code != 200


def test_expected_sequence_rejects_boolean(harness):
    _, client, _, backend, args, prefix = harness
    initial = client.post(prefix, json=request_body(backend, args)).json()["snapshot"]
    response = client.post(
        prefix + "/" + str(args["request_id"]) + "/gate",
        json={
            "expected_plan_content_hash": initial["plan"]["plan_content_hash"],
            "expected_gate_event_sequence": True,
            "action": "APPROVE",
        },
    )
    assert response.status_code == 422


def test_schema_documents_six_distinct_operations(harness):
    app, _, _, _, _, _ = harness
    operations = [
        entry["operationId"]
        for methods in app.openapi()["paths"].values()
        for entry in methods.values()
    ]
    assert len(operations) == len(set(operations)) == 6
