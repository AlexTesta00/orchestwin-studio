"""Authenticated generic Web operation reads and exact Gate 7 decisions."""

from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.web_operations import create_web_operations_router
from orchestwin.web_execution.operation_governance import WebOperationError

OWNER, PROJECT, OPERATION = UUID(int=1), UUID(int=2), UUID(int=3)
URL = f"/projects/{PROJECT}/web-operations/{OPERATION}"


class Store:
    def __init__(self):
        self.calls = []
        self.error = None

    async def get(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"id": str(OPERATION), "content_hash": "a" * 64}

    async def history(self, **kwargs):
        return (await self.get(**kwargs),)

    async def decide(self, **kwargs):
        return await self.get(**kwargs)


def client(store=None):
    app = FastAPI()
    app.include_router(create_web_operations_router())
    app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER)
    if store is not None:
        app.state.web_operation_store = store
    return TestClient(app)


def test_operation_get_is_scoped_to_authenticated_owner_and_project():
    store = Store()
    with client(store) as http:
        response = http.get(URL)
    assert response.status_code == 200
    assert response.json()["snapshot"]["id"] == str(OPERATION)
    assert store.calls == [
        {"owner_user_id": OWNER, "project_id": PROJECT, "operation_id": OPERATION}
    ]


def test_operation_decision_requires_exact_hash_sequence_and_owner():
    store = Store()
    with client(store) as http:
        response = http.post(
            URL + "/gate",
            json={
                "expected_content_hash": "a" * 64,
                "expected_gate_event_sequence": 1,
                "action": "APPROVE",
            },
        )
        invalid = http.post(
            URL + "/gate",
            json={
                "expected_content_hash": "a" * 64,
                "expected_gate_event_sequence": True,
                "action": "APPROVE",
            },
        )
    assert response.status_code == 200 and invalid.status_code == 422
    assert len(store.calls) == 1
    assert store.calls[0]["owner_user_id"] == OWNER
    assert store.calls[0]["expected_hash"] == "a" * 64
    assert store.calls[0]["expected_event_sequence"] == 1


def test_missing_store_or_foreign_operation_never_returns_a_success_snapshot():
    with client() as http:
        assert http.get(URL).status_code == 503
    store = Store()
    store.error = WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
    with client(store) as http:
        response = http.get(URL)
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "WEB_OPERATION_NOT_FOUND"}}
