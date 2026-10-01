from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_loop import DesignEvaluationMode, DesignLoopApplication
from orchestwin.api.services import create_default_runtime
from orchestwin.config import ApplicationSettings, ModelRuntimeMode
from orchestwin.models import real_runtime
from orchestwin.models.generation_routing import RoutingProposalGenerator
from src.test.python.api.test_training_api import _user
from src.test.python.models.test_hosted_support import (
    ANTHROPIC_KEY_ENV,
    GATEWAY_KEY,
    GATEWAY_KEY_ENV,
    TEST_KEY,
    claude_code_document,
    providers_document,
    readiness_runner,
)


@pytest.fixture
def composed(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, TEST_KEY)
    monkeypatch.setenv(GATEWAY_KEY_ENV, GATEWAY_KEY)
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:synthetic@127.0.0.1:1/test"
    )
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "synthetic-test-auth-secret-" + "x" * 40)
    providers_file = tmp_path / "model-providers.json"
    providers_file.write_text(json.dumps(providers_document()), encoding="utf-8")
    manifest = tmp_path / "models-hosted.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "providers_config_file": str(providers_file),
                "final_evaluator_config_file": None,
            }
        ),
        encoding="utf-8",
    )
    runtime = create_default_runtime(
        ApplicationSettings(
            model_runtime_mode=ModelRuntimeMode.REAL_REQUIRED,
            model_runtime_config_file=manifest,
            _env_file=None,
        )
    )
    try:
        yield runtime
    finally:
        asyncio.run(runtime.close())


def test_a_hosted_runtime_without_evaluator_composes_every_service(composed):
    models = composed.real_model_runtime
    assert composed.final_evaluator_runtime is None
    assert models.final_evaluator is None and models.schema_version == 2
    assert composed.team_proposal_service._proposal_port is models.team
    assert isinstance(models.team.generator, RoutingProposalGenerator)
    for stage in ("requirements", "design"):
        service = getattr(composed, stage + "_generation_service")
        assert service._proposals is getattr(models, stage).proposal_port
    assert TEST_KEY not in repr(composed) and GATEWAY_KEY not in repr(composed)


def test_the_static_check_answers_that_no_evaluator_is_configured(composed):
    application = DesignLoopApplication(composed)
    with pytest.raises(HTTPException) as failure:
        application._mode(DesignEvaluationMode.STATIC_CHECK)
    assert failure.value.status_code == 503
    assert failure.value.detail == {"code": "DESIGN_EVALUATOR_NOT_CONFIGURED"}
    mode, reviewer = application._mode(None)
    assert mode is DesignEvaluationMode.TWIN_REVIEW
    assert reviewer is composed.real_model_runtime.user_modeling.proposal_port.generator
    assert application._mode(DesignEvaluationMode.TWIN_REVIEW)[1] is reviewer


def test_the_readiness_endpoint_returns_the_hosted_report(composed, monkeypatch):
    async def schema(_):
        return {"revision": "0062_hosted_model_providers"}

    async def probe(configuration):
        return {"model": configuration.model, "ready": True}

    monkeypatch.setattr(real_runtime, "_check_schema", schema)
    for check in composed.real_model_runtime._hosted_checks:
        object.__setattr__(check, "probe", probe)

    async def spent(_runtime, _session_factory):
        return 0

    monkeypatch.setattr(type(composed.real_model_runtime), "spent_total_microusd", spent)
    app = create_app(ApplicationSettings(api_prefix="/api/v1"), runtime=composed)
    app.dependency_overrides[current_user_dependency] = _user
    http = TestClient(app)
    response = http.get("/api/v1/model-runtime/readiness")
    assert response.status_code == 200
    report = response.json()
    assert report["manifest_schema_version"] == 2 and report["ready"] is True
    assert set(report["components"]) == {"provider:anthropic", "provider:gateway", "database"}
    assert report["budget"]["remaining_total_microusd"] == 60_000_000
    assert TEST_KEY not in response.text and GATEWAY_KEY not in response.text


@pytest.fixture
def subscription(tmp_path, monkeypatch):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:synthetic@127.0.0.1:1/test"
    )
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "synthetic-test-auth-secret-" + "x" * 40)
    providers_file = tmp_path / "model-providers.json"
    document = claude_code_document(executable=str(tmp_path / "claude-synthetic"))
    providers_file.write_text(json.dumps(document), encoding="utf-8")
    manifest = tmp_path / "models-hosted.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "providers_config_file": str(providers_file),
                "final_evaluator_config_file": None,
            }
        ),
        encoding="utf-8",
    )
    runtime = create_default_runtime(
        ApplicationSettings(
            model_runtime_mode=ModelRuntimeMode.REAL_REQUIRED,
            model_runtime_config_file=manifest,
            _env_file=None,
        )
    )
    try:
        yield runtime
    finally:
        asyncio.run(runtime.close())


def test_a_subscription_runtime_answers_readiness_and_budget_without_api_keys(
    subscription, monkeypatch
):
    async def schema(_):
        return {"revision": "0067_claude_code_provider"}

    async def spent(*, project_id=None, since=None):
        return 0

    async def spent_total(_runtime, _session_factory):
        return 0

    monkeypatch.setattr(real_runtime, "_check_schema", schema)
    monkeypatch.setattr(subscription.proposal_evidence_store, "spent_microusd", spent)
    monkeypatch.setattr(type(subscription.real_model_runtime), "spent_total_microusd", spent_total)
    [check] = subscription.real_model_runtime._hosted_checks
    runner = readiness_runner()
    object.__setattr__(check, "run", runner)
    app = create_app(ApplicationSettings(api_prefix="/api/v1"), runtime=subscription)
    app.dependency_overrides[current_user_dependency] = _user
    http = TestClient(app)
    response = http.get("/api/v1/model-runtime/readiness")
    assert response.status_code == 200
    report = response.json()
    assert report["ready"] is True
    assert set(report["components"]) == {"provider:claude-code", "database"}
    component = report["components"]["provider:claude-code"]
    assert set(component) == {
        "ready",
        "kind",
        "executable",
        "version",
        "logged_in",
        "subscription",
        "models",
    }
    assert (component["kind"], component["version"], component["subscription"]) == (
        "CLAUDE_CODE_CLI",
        "2.1.286",
        "max",
    )
    assert len(runner.calls) == 2
    budget = http.get("/api/v1/model-runtime/budget")
    assert budget.status_code == 200
    assert budget.json()["billing"] == "SUBSCRIPTION"
    assert budget.json()["total_microusd"] == 60_000_000


def test_a_subscription_runtime_that_is_not_logged_in_is_not_ready(subscription, monkeypatch):
    async def schema(_):
        return {"revision": "0067_claude_code_provider"}

    async def spent_total(_runtime, _session_factory):
        return 0

    monkeypatch.setattr(real_runtime, "_check_schema", schema)
    monkeypatch.setattr(type(subscription.real_model_runtime), "spent_total_microusd", spent_total)
    [check] = subscription.real_model_runtime._hosted_checks
    object.__setattr__(check, "run", readiness_runner({"loggedIn": False}))
    app = create_app(ApplicationSettings(api_prefix="/api/v1"), runtime=subscription)
    app.dependency_overrides[current_user_dependency] = _user
    response = TestClient(app).get("/api/v1/model-runtime/readiness")
    assert response.status_code == 503
    component = response.json()["components"]["provider:claude-code"]
    assert (component["ready"], component["code"], component["logged_in"]) == (
        False,
        "CLAUDE_CODE_NOT_LOGGED_IN",
        False,
    )
