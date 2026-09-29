from __future__ import annotations

from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.proposal_generation import ProposalGenerationError
from src.test.python.api.test_training_api import OWNER_ID, _user

PROJECT = uuid4()
USAGE_PATH = f"/api/v1/projects/{PROJECT}/model-usage"
BUDGET_PATH = "/api/v1/model-runtime/budget"
ITEM = {
    "generation_id": str(uuid4()),
    "recorded_at": "2026-09-29T09:12:03+00:00",
    "task": "design",
    "purpose": "DESIGN_MOCKUP_HTML",
    "provider_kind": "ANTHROPIC_HOSTED",
    "model": "claude-opus-5-5",
    "status": "SUCCEEDED",
    "failure_code": None,
    "input_tokens": 10234,
    "output_tokens": 17890,
    "reasoning_tokens": 6400,
    "cache_read_input_tokens": 0,
    "cache_write_input_tokens": 0,
    "cost_microusd": 398736,
    "latency_milliseconds": 184000,
}


class Store:
    def __init__(self, spent=1_250_000):
        self.spent, self.usage_calls, self.spent_calls = spent, [], []

    async def model_usage(self, *, owner_user_id, project_id, limit):
        self.usage_calls.append((owner_user_id, project_id, limit))
        if owner_user_id != OWNER_ID or project_id != PROJECT:
            return None
        return {
            "items": [ITEM],
            "totals": {
                "generations": 1,
                "input_tokens": 10234,
                "output_tokens": 17890,
                "reasoning_tokens": 6400,
                "cost_microusd": 398736,
            },
        }

    async def spent_microusd(self, *, project_id=None, since=None):
        self.spent_calls.append((project_id, since))
        return self.spent


def client(store=None, real=None, user=True):
    app = create_app(
        ApplicationSettings(api_prefix="/api/v1"),
        runtime=ApplicationRuntime(
            proposal_evidence_store=store, real_model_runtime=real, identity_service=object()
        ),
    )
    if user:
        app.dependency_overrides[current_user_dependency] = _user
    return TestClient(app)


def test_the_owner_reads_the_usage_of_the_project_in_the_contract_shape():
    store = Store()
    response = client(store).get(USAGE_PATH)
    assert response.status_code == 200
    assert response.json() == {
        "items": [ITEM],
        "totals": {
            "generations": 1,
            "input_tokens": 10234,
            "output_tokens": 17890,
            "reasoning_tokens": 6400,
            "cost_microusd": 398736,
        },
    }
    assert store.usage_calls == [(OWNER_ID, PROJECT, 200)]


def test_usage_of_a_project_that_is_not_owned_is_not_found():
    http = client(Store())
    http.app.dependency_overrides[current_user_dependency] = lambda: replace(_user(), id=uuid4())
    response = http.get(USAGE_PATH)
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}
    assert client(Store()).get(f"/api/v1/projects/{uuid4()}/model-usage").status_code == 404


def test_usage_and_budget_require_authentication_and_an_evidence_store():
    anonymous = client(Store(), user=False)
    assert anonymous.get(USAGE_PATH).status_code == 401
    assert anonymous.get(BUDGET_PATH).status_code == 401
    response = client(None).get(USAGE_PATH)
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "PROPOSAL_EVIDENCE_UNAVAILABLE"}}


def test_the_budget_reports_ceilings_spending_and_remainder():
    store = Store()
    budget = GenerationBudget(1_500_000, 10_000_000, 60_000_000, date(2026, 9, 1))
    response = client(store, SimpleNamespace(budget=budget)).get(BUDGET_PATH)
    assert response.status_code == 200
    assert response.json() == {
        "currency": "USD",
        "per_generation_microusd": 1_500_000,
        "per_project_microusd": 10_000_000,
        "total_microusd": 60_000_000,
        "spent_total_microusd": 1_250_000,
        "remaining_total_microusd": 58_750_000,
        "period_start": "2026-09-01",
    }
    assert store.spent_calls == [(None, date(2026, 9, 1))]


def test_the_budget_needs_a_real_runtime_with_a_budget():
    missing = client(Store()).get(BUDGET_PATH)
    assert missing.status_code == 503
    assert missing.json() == {"detail": {"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"}}
    local = client(Store(), SimpleNamespace(budget=None)).get(BUDGET_PATH)
    assert local.status_code == 503
    assert local.json() == {"detail": {"code": "GENERATION_BUDGET_NOT_CONFIGURED"}}


def test_a_budget_refusal_surfaced_by_an_endpoint_answers_payment_required():
    http = client(Store())

    async def refused():
        raise ProposalGenerationError("GENERATION_BUDGET_EXCEEDED")

    async def unreadable():
        raise ProposalGenerationError("GENERATION_BUDGET_UNAVAILABLE")

    http.app.add_api_route("/api/v1/synthetic-refusal", refused, methods=["POST"])
    http.app.add_api_route("/api/v1/synthetic-unreadable", unreadable, methods=["POST"])
    response = http.post("/api/v1/synthetic-refusal")
    assert response.status_code == 402
    assert response.json() == {
        "detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}
    }
    assert http.post("/api/v1/synthetic-unreadable").status_code == 503
