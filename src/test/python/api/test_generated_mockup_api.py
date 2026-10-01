from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.perspectives import GuidanceStage, perspective_guidance
from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.design_iterations import create_design_iteration_router
from orchestwin.api.design_mockups import create_design_mockup_router
from orchestwin.api.generation_jobs import GenerationJobKind, GenerationJobRegistry
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState
from src.test.python.api.test_design_context import sections_port
from src.test.python.models.test_generated_mockup_support import (
    DASHBOARD,
    DASHBOARD_ID,
    GUIDED_ID,
    OWNER_ID,
    PROJECT_ID,
    STRANGER_ID,
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    applied_package,
    draft_payload,
    failure,
    iteration_payload,
    package,
    requirements_version,
    runtime,
    with_markup,
)
from src.test.python.models.test_hosted_support import claude_code_document, providers

NOW = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
BASE = f"/api/v1/projects/{PROJECT_ID}/design"
MOCKUPS = f"{BASE}/mockups"
BROKEN = with_markup(draft_payload(), "<h1>", "<h1>Lorem ipsum ")
RESULT_KEYS = {
    "status",
    "generation_id",
    "design_version_id",
    "design_content_hash",
    "package",
    "approach",
    "changes",
    "warnings",
    "cost_microusd",
}


def user(identifier=OWNER_ID):
    return UserAccount(
        id=identifier,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def client_for(runtime_value, *, identity=OWNER_ID, registry=None):
    registry = GenerationJobRegistry() if registry is None else registry

    @asynccontextmanager
    async def lifespan(_application):
        try:
            yield
        finally:
            await registry.close()

    application = FastAPI(lifespan=lifespan)
    application.state.application_runtime = runtime_value
    application.state.generation_jobs = registry
    application.include_router(create_design_mockup_router(), prefix="/api/v1")
    application.include_router(create_design_iteration_router(), prefix="/api/v1")
    application.dependency_overrides[current_user_dependency] = lambda: user(identity)
    return TestClient(application), registry


def body(versions, alternative_id=GUIDED_ID, **changes):
    current = versions.versions[-1]
    return {
        "design_version_id": str(current.id),
        "design_content_hash": current.content_hash,
        "alternative_id": str(alternative_id),
        **changes,
    }


def settle(client, registry, job):
    client.portal.call(registry.wait, UUID(job["job_id"]))
    return client.get(f"{MOCKUPS}/jobs/{job['job_id']}").json()


def generated(client, registry, versions, alternative_id=GUIDED_ID):
    started = client.post(f"{MOCKUPS}/jobs", json=body(versions, alternative_id))
    assert started.status_code == 202, started.json()
    return settle(client, registry, started.json())


def wired_runtime(generator, versions, *, selected_agent_ids=(), states=None):
    legacy = runtime(generator, versions=versions)
    reference = versions.versions[-1].package.grounding.agent_team_reference
    team = SimpleNamespace(
        project_id=PROJECT_ID,
        id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
        proposal=SimpleNamespace(selected_agent_ids=selected_agent_ids),
    )
    team_port = SimpleNamespace(value=team, calls=[])

    async def current(**scope):
        assert scope == {"owner_user_id": OWNER_ID, "project_id": PROJECT_ID}
        team_port.calls.append(scope)
        return team_port.value

    team_port.current = current
    value = ApplicationRuntime(
        real_model_runtime=legacy.real_model_runtime,
        proposal_evidence_store=legacy.proposal_evidence_store,
        design_query_service=legacy.design_query_service,
        requirements_query_service=legacy.requirements_query_service,
        team_proposal_service=team_port,
        sections_service=sections_port(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID, states=states
        ),
    )
    return value, team_port


@pytest.mark.parametrize("security", (False, True))
def test_generated_mockup_uses_only_exact_selected_team_guidance_and_keeps_it_on_retry(security):
    selected = (AgentIdentifier.UX_UI_DESIGNER,) + (
        (AgentIdentifier.SECURITY_REVIEWER,) if security else ()
    )
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(answer(BROKEN), answer(draft_payload()))
    value, team = wired_runtime(
        generator,
        versions,
        selected_agent_ids=selected,
        states={ProjectStage.DESIGN: SectionState.IN_PROGRESS} if security else None,
    )
    client, registry = client_for(value)
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "SUCCEEDED"
    assert len(generator.calls) == 2 and len(team.calls) >= 2
    expected = perspective_guidance(selected, GuidanceStage.DESIGN)
    assert all(call["context"]["perspectives"] == expected for call in generator.calls)
    assert any(item["perspective"] == "SECURITY" for item in expected) is security
    assert all(
        "not empirical evidence about real users" in call["instruction"] for call in generator.calls
    )


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("id", uuid4()),
        ("version_number", 99),
        ("content_hash", "a" * 64),
        ("project_id", uuid4()),
        ("missing", None),
        ("service_missing", None),
    ],
)
def test_real_runtime_team_mismatch_is_refused_before_provider(field, new_value):
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator()
    value, team = wired_runtime(generator, versions)
    if field == "missing":
        team.value = None
    elif field == "service_missing":
        value.team_proposal_service = None
    else:
        setattr(team.value, field, new_value)
    client, registry = client_for(value)
    with client:
        response = client.post(f"{MOCKUPS}/jobs", json=body(versions))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "DESIGN_CONTEXT_CHANGED"}
    assert generator.calls == [] and len(registry) == 0


@pytest.mark.parametrize(
    "key,state",
    [
        (ProjectStage.USER_TWINS, SectionState.TO_UPDATE),
        (ProjectStage.DESIGN, SectionState.TO_UPDATE),
        (ProjectStage.TEAM, SectionState.IN_PROGRESS),
    ],
)
def test_stale_sections_after_archetype_edit_prevent_mockup_generation(key, state):
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator()
    value, _team = wired_runtime(generator, versions, states={key: state})
    client, registry = client_for(value)
    with client:
        response = client.post(f"{MOCKUPS}/jobs", json=body(versions))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "DESIGN_CONTEXT_CHANGED"}
    assert generator.calls == [] and len(registry) == 0


def test_archetype_edit_during_provider_refuses_adapter_acceptance():
    states = {}

    class Changed(ScriptedMockupGenerator):
        async def generate(self, **options):
            draft = await super().generate(**options)
            states[ProjectStage.USER_TWINS] = SectionState.TO_UPDATE
            return draft

    versions = DesignVersions(package())
    generator = Changed(answer(draft_payload()))
    value, _team = wired_runtime(generator, versions, states=states)
    client, registry = client_for(value)
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "FAILED"
    assert done["failure"]["code"] == "DESIGN_CONTEXT_CHANGED"
    assert len(generator.calls) == 1
    assert "ADAPTER_ACCEPTED" not in value.proposal_evidence_store.kinds(
        value.proposal_evidence_store.order[-1]
    )


def test_team_changed_during_provider_refuses_adapter_acceptance():
    class Changed(ScriptedMockupGenerator):
        async def generate(self, **options):
            draft = await super().generate(**options)
            team.value.version_number += 1
            return draft

    versions = DesignVersions(package())
    generator = Changed(answer(draft_payload()))
    value, team = wired_runtime(generator, versions)
    client, registry = client_for(value)
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "FAILED"
    assert done["failure"]["code"] == "DESIGN_CONTEXT_CHANGED"
    assert len(generator.calls) == 1
    assert "ADAPTER_ACCEPTED" not in value.proposal_evidence_store.kinds(
        value.proposal_evidence_store.order[-1]
    )


class Gated(ScriptedMockupGenerator):
    def __init__(self, *outcomes):
        super().__init__(*outcomes)
        self.gate = None
        self.entered = threading.Event()

    async def generate(self, **options):
        if self.gate is None:
            self.gate = asyncio.Event()
        self.entered.set()
        await self.gate.wait()
        return await super().generate(**options)


class Routed:
    def __init__(self, routes):
        self.routes = routes
        self.configuration = routes["default"].configuration

    def route(self, task, purpose=None):
        return self.routes.get(purpose, self.routes["default"])


def subscription_generator(*outcomes, budget=None):
    generator = ScriptedMockupGenerator(*outcomes, budget=budget)
    generator.configuration = providers(claude_code_document()).hosted_model("design")
    return generator


def test_capabilities_follow_the_route_of_each_purpose():
    hosted = ScriptedMockupGenerator()
    local = SimpleNamespace(
        configuration=SimpleNamespace(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            max_output_tokens=16_384,
        )
    )
    small = ScriptedMockupGenerator(entry="review")
    cases = [
        (
            hosted,
            True,
            {
                "generated_mockups": True,
                "iterations": True,
                "model": "claude-opus-5-5",
                "static_check": False,
                "paid": True,
            },
        ),
        (
            local,
            True,
            {
                "generated_mockups": False,
                "iterations": False,
                "model": None,
                "static_check": False,
                "paid": True,
            },
        ),
        (
            hosted,
            False,
            {
                "generated_mockups": False,
                "iterations": False,
                "model": None,
                "static_check": False,
                "paid": True,
            },
        ),
        (
            Routed({"default": local, "DESIGN_MOCKUP_HTML": hosted, "DESIGN_ITERATION": small}),
            True,
            {
                "generated_mockups": True,
                "iterations": False,
                "model": "claude-opus-5-5",
                "static_check": False,
                "paid": True,
            },
        ),
        (
            ScriptedMockupGenerator(entry="general"),
            True,
            {
                "generated_mockups": True,
                "iterations": True,
                "model": "claude-sonnet-5",
                "static_check": False,
                "paid": True,
            },
        ),
    ]
    for generator, real, expected in cases:
        client, _registry = client_for(runtime(generator, real=real))
        with client:
            response = client.get(f"{MOCKUPS}/capabilities")
        assert response.status_code == 200
        assert response.json() == expected


def test_capabilities_are_not_paid_when_the_route_that_draws_uses_the_subscription():
    hosted = ScriptedMockupGenerator()
    subscription = subscription_generator()
    local = SimpleNamespace(
        configuration=SimpleNamespace(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            max_output_tokens=16_384,
        )
    )
    cases = [
        (subscription, (True, True, False)),
        (Routed({"default": local, "DESIGN_ITERATION": subscription}), (False, True, False)),
        (
            Routed(
                {"default": local, "DESIGN_MOCKUP_HTML": hosted, "DESIGN_ITERATION": subscription}
            ),
            (True, True, True),
        ),
        (
            Routed(
                {"default": local, "DESIGN_MOCKUP_HTML": subscription, "DESIGN_ITERATION": hosted}
            ),
            (True, True, False),
        ),
    ]
    for generator, (mockups, iterations, paid) in cases:
        client, _registry = client_for(runtime(generator))
        with client:
            response = client.get(f"{MOCKUPS}/capabilities")
        assert response.status_code == 200
        assert response.json() == {
            "generated_mockups": mockups,
            "iterations": iterations,
            "model": "claude-opus-5-5",
            "static_check": False,
            "paid": paid,
        }


def test_a_route_without_prices_starts_the_jobs_whatever_was_spent():
    budget = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
    versions = DesignVersions(package())
    store = MemoryMockupStore(project=10**12, total=10**12)
    generator = subscription_generator(answer(draft_payload(), cost=None), budget=budget)
    client, registry = client_for(runtime(generator, store, versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "SUCCEEDED"
    assert done["result"]["cost_microusd"] == 0
    applied = DesignVersions(package(), applied_package())
    current = applied.versions[-1]
    iterating = subscription_generator(answer(iteration_payload(), cost=None), budget=budget)
    client, registry = client_for(runtime(iterating, store, applied))
    with client:
        started = client.post(
            f"{BASE}/iterations/jobs",
            json={
                "design_version_id": str(current.id),
                "design_content_hash": current.content_hash,
                "request": "Mostra la sede di ritiro della tessera.",
            },
        )
        assert started.status_code == 202, started.json()
        job_id = started.json()["job_id"]
        client.portal.call(registry.wait, UUID(job_id))
        iteration = client.get(f"{BASE}/iterations/jobs/{job_id}").json()
    assert iteration["status"] == "SUCCEEDED", iteration["failure"]
    assert store.reads == []
    priced = ScriptedMockupGenerator(budget=budget)
    client, registry = client_for(runtime(priced, MemoryMockupStore(project=10**12), versions))
    with client:
        refused = client.post(f"{MOCKUPS}/jobs", json=body(versions))
    assert refused.status_code == 402
    assert refused.json()["detail"] == {"code": "GENERATION_BUDGET_EXCEEDED"}


def test_capabilities_say_whether_the_runtime_has_the_final_evaluator():
    cases = [
        (ScriptedMockupGenerator(), True, None, (True, True, "claude-opus-5-5", False, True)),
        (
            ScriptedMockupGenerator(),
            True,
            SimpleNamespace(),
            (True, True, "claude-opus-5-5", True, True),
        ),
        (None, False, SimpleNamespace(), (False, False, None, True, True)),
        (None, False, None, (False, False, None, False, True)),
    ]
    keys = ("generated_mockups", "iterations", "model", "static_check", "paid")
    for generator, real, evaluator, expected in cases:
        value = runtime(generator, real=real)
        value.final_evaluator_runtime = evaluator
        client, _registry = client_for(value)
        with client:
            response = client.get(f"{MOCKUPS}/capabilities")
            schema = client.app.openapi()["components"]["schemas"]["MockupCapabilities"]
        assert response.status_code == 200
        assert response.json() == dict(zip(keys, expected, strict=True))
    assert sorted(schema["required"]) == [
        "generated_mockups",
        "iterations",
        "model",
        "paid",
        "static_check",
    ]
    assert schema["properties"]["static_check"]["type"] == "boolean"
    assert schema["properties"]["paid"]["type"] == "boolean"
    assert schema["additionalProperties"] is False


def test_a_mockup_job_runs_in_the_background_and_answers_the_result():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        started = client.post(f"{MOCKUPS}/jobs", json=body(versions))
        assert started.status_code == 202
        job = started.json()
        assert job["kind"] == "MOCKUP"
        assert job["alternative_id"] == str(GUIDED_ID)
        assert job["status"] in {"RUNNING", "SUCCEEDED"}
        done = settle(client, registry, job)
    assert done["status"] == "SUCCEEDED"
    assert done["stage"] is None
    assert done["failure"] is None
    result = done["result"]
    assert set(result) == RESULT_KEYS
    assert result["status"] == "MOCKUP_GENERATED"
    assert result["design_version_id"] == str(versions.versions[-1].id)
    assert result["changes"] == [] and result["warnings"] == []
    assert result["cost_microusd"] == 410_000
    assert result["approach"] == draft_payload()["approach"]
    proposed = DesignPackagePayload.model_validate(result["package"]).to_domain()
    assert proposed.owner_selected_alternative_id == GUIDED_ID
    assert proposed.generated_mockup.design_alternative_id == GUIDED_ID
    assert generator.calls[0]["retry_schema_errors"] is False


def test_a_second_request_for_the_same_design_and_alternative_joins_the_running_job():
    versions = DesignVersions(package())
    generator = Gated(answer(draft_payload()))
    client, registry = client_for(runtime(generator, versions=versions))

    async def release():
        generator.gate.set()

    with client:
        first = client.post(f"{MOCKUPS}/jobs", json=body(versions)).json()
        assert generator.entered.wait(5)
        second = client.post(f"{MOCKUPS}/jobs", json=body(versions)).json()
        running = client.get(f"{MOCKUPS}/jobs/{first['job_id']}").json()
        client.portal.call(release)
        done = settle(client, registry, first)
    assert second["job_id"] == first["job_id"]
    assert running["status"] == "RUNNING" and running["stage"] == "GENERATING"
    assert running["attempt"] == 1
    assert done["status"] == "SUCCEEDED"
    assert len(generator.calls) == 1


def test_an_owner_cannot_run_more_than_four_generations():
    versions = DesignVersions(package())
    client, registry = client_for(runtime(ScriptedMockupGenerator(), versions=versions))

    async def fill():
        gate = asyncio.Event()

        async def waiting(progress):
            await gate.wait()
            return {}

        for index in range(4):
            registry.start(OWNER_ID, uuid4(), GenerationJobKind.MOCKUP, str(index), waiting)

    with client:
        client.portal.call(fill)
        refused = client.post(f"{MOCKUPS}/jobs", json=body(versions))
    assert refused.status_code == 429
    assert refused.json()["detail"] == {"code": "TOO_MANY_GENERATIONS"}


def test_every_refusal_of_a_mockup_job_has_its_code():
    versions = DesignVersions(package())
    plain = replace(
        package(),
        alternatives=tuple(
            replace(item, visual_language=None) if item.id == GUIDED_ID else item
            for item in package().alternatives
        ),
    )
    plain_versions = DesignVersions(plain)

    class Unreadable(MemoryMockupStore):
        async def spent_microusd(self, *, project_id=None, since=None):
            raise ProposalEvidenceError("GENERATION_EVIDENCE_READ_FAILED")

    budget = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
    local = SimpleNamespace(
        configuration=SimpleNamespace(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            max_output_tokens=16_384,
        )
    )
    hosted = ScriptedMockupGenerator()
    cases = [
        (
            runtime(hosted, versions=versions),
            body(versions, design_content_hash="f" * 64),
            409,
            "DESIGN_CONTEXT_CHANGED",
        ),
        (
            runtime(hosted, versions=versions),
            body(versions, alternative_id=uuid4()),
            422,
            "DESIGN_ALTERNATIVE_NOT_FOUND",
        ),
        (
            runtime(hosted, versions=plain_versions),
            body(plain_versions),
            422,
            "GENERATED_MOCKUP_REQUIRES_VISUAL_LANGUAGE",
        ),
        (
            runtime(hosted, versions=versions, real=False),
            body(versions),
            503,
            "REAL_MOCKUP_MODEL_NOT_CONFIGURED",
        ),
        (runtime(local, versions=versions), body(versions), 409, "GENERATED_MOCKUP_PATH_INACTIVE"),
        (
            runtime(hosted, versions=versions, requirements=requirements_version("en")),
            body(versions),
            409,
            "DESIGN_CONTEXT_CHANGED",
        ),
        (
            runtime(
                ScriptedMockupGenerator(budget=budget),
                MemoryMockupStore(project=10_000_000),
                versions,
            ),
            body(versions),
            402,
            "GENERATION_BUDGET_EXCEEDED",
        ),
        (
            runtime(
                ScriptedMockupGenerator(budget=budget),
                MemoryMockupStore(total=60_000_000),
                versions,
            ),
            body(versions),
            402,
            "GENERATION_BUDGET_EXCEEDED",
        ),
        (
            runtime(ScriptedMockupGenerator(budget=budget), Unreadable(), versions),
            body(versions),
            503,
            "GENERATION_BUDGET_UNAVAILABLE",
        ),
    ]
    for runtime_value, payload, status, code in cases:
        client, registry = client_for(runtime_value)
        with client:
            response = client.post(f"{MOCKUPS}/jobs", json=payload)
        assert response.status_code == status, code
        assert response.json()["detail"] == {"code": code}
        assert len(registry) == 0
    missing = client_for(runtime(hosted, versions=DesignVersions(package())), identity=STRANGER_ID)
    with missing[0] as client:
        response = client.post(f"{MOCKUPS}/jobs", json=body(versions))
    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "DESIGN_PACKAGE_NOT_FOUND"}


def test_a_budget_below_the_ceilings_lets_the_job_start():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(
        answer(draft_payload()), budget=GenerationBudget(1_500_000, 10_000_000, 60_000_000)
    )
    store = MemoryMockupStore(project=9_000_000, total=50_000_000)
    client, registry = client_for(runtime(generator, store, versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "SUCCEEDED"
    assert store.reads == [(PROJECT_ID, None), (None, None)]


def test_jobs_are_visible_only_to_their_owner_and_on_their_own_route():
    versions = DesignVersions(package())
    registry = GenerationJobRegistry()
    client, _registry = client_for(
        runtime(ScriptedMockupGenerator(answer(draft_payload())), versions=versions),
        registry=registry,
    )
    with client:
        done = generated(client, registry, versions)
        unknown = client.get(f"{MOCKUPS}/jobs/{uuid4()}")
        as_iteration = client.get(f"{BASE}/iterations/jobs/{done['job_id']}")
    stranger, _ = client_for(runtime(ScriptedMockupGenerator()), identity=STRANGER_ID)
    stranger.app.state.generation_jobs = registry
    with stranger:
        hidden = stranger.get(f"{MOCKUPS}/jobs/{done['job_id']}")
    for response in (unknown, as_iteration, hidden):
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "GENERATION_JOB_NOT_FOUND"}


def test_a_job_whose_answers_are_rejected_twice_reports_the_rejection():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(answer(BROKEN), answer(BROKEN))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "REJECTED"
    assert done["result"] is None
    assert done["attempt"] == 2
    failure_value = done["failure"]
    assert failure_value["code"] == "MOCKUP_QUALITY_REJECTED"
    assert failure_value["reasons"][0]["code"] == "PLACEHOLDER_TEXT"
    assert set(failure_value["reasons"][0]) == {"code", "screen_code", "detail"}


def test_a_job_whose_provider_fails_reports_the_failure():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(failure("AUTHENTICATION_FAILED", retryable=False))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        done = generated(client, registry, versions)
    assert done["status"] == "FAILED"
    assert done["failure"] == {"code": "AUTHENTICATION_FAILED", "reasons": []}


def test_the_newest_mockup_of_an_alternative_survives_a_new_version_of_the_design():
    versions = DesignVersions(package())
    store = MemoryMockupStore()
    generator = ScriptedMockupGenerator(answer(draft_payload()), answer(draft_payload(DASHBOARD)))
    client, registry = client_for(runtime(generator, store, versions))
    with client:
        assert client.get(MOCKUPS, params={"alternative_id": str(GUIDED_ID)}).json() is None
        guided = generated(client, registry, versions, GUIDED_ID)["result"]
        dashboard = generated(client, registry, versions, DASHBOARD_ID)["result"]
        latest = client.get(MOCKUPS, params={"alternative_id": str(GUIDED_ID)}).json()
        assert latest == guided
        first = versions.versions[0]
        applied = versions.apply(DesignPackagePayload.model_validate(guided["package"]).to_domain())
        kept = client.get(MOCKUPS, params={"alternative_id": str(DASHBOARD_ID)}).json()
        changed = replace(
            applied.package,
            alternatives=tuple(
                replace(item, title="Cruscotto rinnovato") if item.id == DASHBOARD_ID else item
                for item in applied.package.alternatives
            ),
        )
        versions.apply(changed)
        gone = client.get(MOCKUPS, params={"alternative_id": str(DASHBOARD_ID)}).json()
        unknown = client.get(MOCKUPS, params={"alternative_id": str(uuid4())}).json()
    assert set(kept) == RESULT_KEYS
    assert kept["design_version_id"] == str(first.id)
    assert kept["generation_id"] == dashboard["generation_id"]
    rebased = DesignPackagePayload.model_validate(kept["package"]).to_domain()
    assert rebased.owner_selected_alternative_id == DASHBOARD_ID
    assert rebased.generated_mockup.design_alternative_id == DASHBOARD_ID
    assert rebased.alternatives == applied.package.alternatives
    assert rebased.critiques == applied.package.critiques
    assert gone is None
    assert unknown is None


def test_the_document_is_rebuilt_from_the_mockup_and_is_free_of_scripts():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator(answer(draft_payload()))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        missing = client.get(
            f"{MOCKUPS}/document", params={"alternative_id": str(GUIDED_ID), "source": "latest"}
        )
        result = generated(client, registry, versions)["result"]
        latest = client.get(
            f"{MOCKUPS}/document", params={"alternative_id": str(GUIDED_ID), "source": "latest"}
        )
        second = client.get(
            f"{MOCKUPS}/document",
            params={
                "alternative_id": str(GUIDED_ID),
                "source": "latest",
                "entry_screen": "SCR-002",
            },
        )
        invalid = client.get(
            f"{MOCKUPS}/document",
            params={
                "alternative_id": str(GUIDED_ID),
                "source": "latest",
                "entry_screen": "SCR-009",
            },
        )
        not_applied = client.get(
            f"{MOCKUPS}/document", params={"alternative_id": str(GUIDED_ID), "source": "applied"}
        )
        versions.apply(DesignPackagePayload.model_validate(result["package"]).to_domain())
        applied = client.get(
            f"{MOCKUPS}/document", params={"alternative_id": str(GUIDED_ID), "source": "applied"}
        )
        other = client.get(
            f"{MOCKUPS}/document", params={"alternative_id": str(DASHBOARD_ID), "source": "applied"}
        )
    for response in (missing, not_applied, other):
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "GENERATED_MOCKUP_NOT_FOUND"}
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == {"code": "MOCKUP_ENTRY_SCREEN_INVALID"}
    document = latest.json()
    assert set(document) == {
        "html",
        "content_hash",
        "source",
        "alternative_id",
        "title",
        "entry_screen",
        "screens",
    }
    html = document["html"]
    assert document["content_hash"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    assert document["source"] == "latest"
    assert document["alternative_id"] == str(GUIDED_ID)
    assert document["title"] == "Biblioteca Sant'Ambrogio"
    assert document["entry_screen"] == "SCR-001"
    assert [screen["code"] for screen in document["screens"]] == [
        "SCR-001",
        "SCR-002",
        "SCR-003",
        "SCR-004",
    ]
    assert document["screens"][-1]["state"] == "SUCCESS"
    assert html.startswith('<!doctype html><html lang="it">')
    assert "Content-Security-Policy" in html
    assert "<script" not in html.lower()
    assert re.search(r'id="SCR-001"[^>]*data-entry>', html)
    assert html.count(" data-entry>") == 1
    assert second.json()["entry_screen"] == "SCR-002"
    assert re.search(r'id="SCR-002"[^>]*data-entry>', second.json()["html"])
    assert second.json()["html"].count(" data-entry>") == 1
    assert applied.status_code == 200
    assert applied.json()["source"] == "applied"
    assert applied.json()["html"] == html


def test_the_synchronous_declarative_endpoint_is_closed_on_the_generated_path():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator()
    client, _registry = client_for(runtime(generator, versions=versions))
    with client:
        response = client.post(MOCKUPS, json=body(versions))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "GENERATED_MOCKUP_PATH_ACTIVE"}
    assert generator.calls == []


def test_the_application_registers_the_routes_and_closes_the_jobs_on_shutdown():
    application = create_app(
        ApplicationSettings(api_prefix="/api/v1"),
        runtime=ApplicationRuntime(identity_service=object()),
    )
    registry = application.state.generation_jobs
    assert isinstance(registry, GenerationJobRegistry)
    application.dependency_overrides[current_user_dependency] = user
    versions = DesignVersions(package())
    with TestClient(application) as client:
        response = client.get(f"{MOCKUPS}/capabilities")
        assert response.json() == {
            "generated_mockups": False,
            "iterations": False,
            "model": None,
            "static_check": False,
            "paid": True,
        }
        unavailable = [
            client.post(f"{MOCKUPS}/jobs", json=body(versions)),
            client.get(f"{MOCKUPS}/document", params={"alternative_id": str(GUIDED_ID)}),
            client.get(f"{BASE}/iterations"),
            client.post(
                f"{BASE}/iterations/jobs",
                json={
                    "design_version_id": str(versions.versions[-1].id),
                    "design_content_hash": versions.versions[-1].content_hash,
                    "request": "Mostra la sede.",
                },
            ),
        ]
        missing = [
            client.get(f"{MOCKUPS}/jobs/{uuid4()}"),
            client.get(f"{BASE}/iterations/jobs/{uuid4()}"),
        ]
    for answer_value in unavailable:
        assert answer_value.status_code == 503
        assert answer_value.json()["detail"] == {"code": "DESIGN_QUERY_UNAVAILABLE"}
    for answer_value in missing:
        assert answer_value.json()["detail"] == {"code": "GENERATION_JOB_NOT_FOUND"}
    with pytest.raises(HTTPException) as closed:
        registry.start(OWNER_ID, PROJECT_ID, GenerationJobKind.MOCKUP, "after", None)
    assert closed.value.detail == {"code": "GENERATION_JOBS_UNAVAILABLE"}
