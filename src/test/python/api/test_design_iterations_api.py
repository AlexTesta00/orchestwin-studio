from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from orchestwin.api.design import DesignPackagePayload
from orchestwin.api.design_iterations import (
    DesignIterationApplication,
    IterationRequest,
    iteration_items,
    merged_assertions,
    normalized_iteration,
)
from orchestwin.models.generated_mockup_drafts import GeneratedIterationDraft
from orchestwin.models.generated_mockup_instructions import DESIGN_ITERATION, ITERATION_SENTENCE
from orchestwin.models.proposal_generation import ProposalGenerationError
from src.test.python.api.test_generated_mockup_api import BASE, MOCKUPS, client_for, generated
from src.test.python.models.test_generated_mockup_support import (
    GUIDED_ID,
    OWNER_ID,
    PROJECT_ID,
    DesignVersions,
    MemoryMockupStore,
    ScriptedMockupGenerator,
    answer,
    applied_package,
    draft_payload,
    failure,
    iteration_payload,
    package,
    runtime,
    with_markup,
)
from src.test.python.models.test_hosted_transient_retry import anthropic_generator, overloaded

ITERATIONS = f"{BASE}/iterations"
BROKEN = with_markup(iteration_payload(), "<h1>", "<h1>Lorem ipsum ")
KEPT = "Il registro dei prestiti resta la prima schermata."
REQUEST = "Nel riepilogo finale   mostra anche la sede di ritiro della tessera."


def request_body(versions, **changes):
    current = versions.versions[-1]
    return {
        "design_version_id": str(current.id),
        "design_content_hash": current.content_hash,
        "request": REQUEST,
        "assertions": ["Il tono resta caldo e rassicurante.", KEPT],
        **changes,
    }


def settle(client, registry, job):
    client.portal.call(registry.wait, UUID(job["job_id"]))
    return client.get(f"{ITERATIONS}/jobs/{job['job_id']}").json()


def iterate(client, registry, versions, **changes):
    started = client.post(f"{ITERATIONS}/jobs", json=request_body(versions, **changes))
    assert started.status_code == 202, started.json()
    return started.json(), settle(client, registry, started.json())


def applied_versions(assertions=(KEPT,)):
    return DesignVersions(package(), applied_package(assertions=assertions))


def test_an_iteration_changes_the_applied_mockup_and_keeps_the_assertions():
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(iteration_payload()))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        started, done = iterate(client, registry, versions)
    assert started["kind"] == "ITERATION"
    assert started["alternative_id"] == str(GUIDED_ID)
    assert done["status"] == "SUCCEEDED"
    result = done["result"]
    assert result["changes"] == iteration_payload()["changes"]
    assert result["design_version_id"] == str(versions.versions[-1].id)
    proposed = DesignPackagePayload.model_validate(result["package"]).to_domain()
    assert proposed.owner_assertions == (KEPT, "Il tono resta caldo e rassicurante.")
    assert proposed.generated_mockup.design_alternative_id == GUIDED_ID
    assert proposed.owner_selected_alternative_id == GUIDED_ID
    [call] = generator.calls
    context = call["context"]
    current = versions.versions[-1].package.generated_mockup.mockup
    assert call["output_type"] is GeneratedIterationDraft
    assert context["purpose"] == DESIGN_ITERATION
    assert context["owner_request"] == " ".join(REQUEST.split())
    assert context["assertions"] == [KEPT, "Il tono resta caldo e rassicurante."]
    assert context["current_mockup"]["css"] == current.styles
    assert [screen["markup"] for screen in context["current_mockup"]["screens"]] == [
        screen.markup for screen in current.screens
    ]
    assert context["alternative"]["id"] == str(GUIDED_ID)
    assert ITERATION_SENTENCE in call["instruction"]
    assert call["retry_schema_errors"] is False


def test_an_iteration_requires_an_applied_generated_mockup():
    versions = DesignVersions(package())
    generator = ScriptedMockupGenerator()
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        response = client.post(f"{ITERATIONS}/jobs", json=request_body(versions))
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "GENERATED_MOCKUP_REQUIRED"}
    assert len(registry) == 0 and generator.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"request": ""},
        {"request": "   "},
        {"request": "x" * 1001},
        {"request": "Cambia\u0000il titolo"},
        {"assertions": [f"Asserzione {index}" for index in range(6)]},
        {"assertions": ["y" * 301]},
        {"assertions": [""]},
    ],
)
def test_an_invalid_request_is_refused(changes):
    versions = applied_versions()
    client, registry = client_for(runtime(ScriptedMockupGenerator(), versions=versions))
    with client:
        response = client.post(f"{ITERATIONS}/jobs", json=request_body(versions, **changes))
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "ITERATION_REQUEST_INVALID"}
    assert len(registry) == 0


def test_the_assertions_of_the_package_and_the_new_ones_stay_within_twenty():
    many = tuple(f"Asserzione numero {index} del progetto." for index in range(18))
    versions = applied_versions(assertions=many)
    client, _registry = client_for(runtime(ScriptedMockupGenerator(), versions=versions))
    with client:
        refused = client.post(
            f"{ITERATIONS}/jobs",
            json=request_body(versions, assertions=["Nuova uno.", "Nuova due.", "Nuova tre."]),
        )
        accepted = client.post(
            f"{ITERATIONS}/jobs",
            json=request_body(versions, assertions=["Nuova uno.", "Nuova due.", many[0]]),
        )
    assert refused.status_code == 422
    assert accepted.status_code == 202


def test_normalization_and_merging_of_the_request():
    body = IterationRequest(
        design_version_id=uuid4(),
        design_content_hash="a" * 64,
        request="  Mostra   la sede ",
        assertions=["Uno.", " Uno. ", "Due."],
    )
    assert normalized_iteration(body) == ("Mostra la sede", ("Uno.", "Due."))
    base = applied_package(assertions=("Due.",))
    assert merged_assertions(base, ("Uno.", "Due.")) == ("Due.", "Uno.")


def test_the_list_of_the_iterations_follows_their_evidence_and_the_design_versions():
    versions = applied_versions()
    store = MemoryMockupStore()
    generator = ScriptedMockupGenerator(
        answer(iteration_payload(), cost=400_000),
        answer(BROKEN, cost=100_000),
        answer(BROKEN, cost=200_000),
        failure("AUTHENTICATION_FAILED", retryable=False),
        answer(BROKEN, cost=300_000),
        answer(iteration_payload(), cost=500_000),
    )
    client, registry = client_for(runtime(generator, store, versions))
    with client:
        assert client.get(ITERATIONS).json() == {"items": []}
        _started, first = iterate(client, registry, versions, request="Prima richiesta.")
        _started, rejected = iterate(client, registry, versions, request="Seconda richiesta.")
        _started, failed = iterate(client, registry, versions, request="Terza richiesta.")
        _started, retried = iterate(client, registry, versions, request="Quarta richiesta.")
        listed = client.get(ITERATIONS).json()["items"]
        versions.apply(DesignPackagePayload.model_validate(first["result"]["package"]).to_domain())
        after = client.get(ITERATIONS).json()["items"]
    assert [first["status"], rejected["status"], failed["status"], retried["status"]] == [
        "SUCCEEDED",
        "REJECTED",
        "FAILED",
        "SUCCEEDED",
    ]
    assert [item["request"] for item in listed] == [
        "Quarta richiesta.",
        "Terza richiesta.",
        "Seconda richiesta.",
        "Prima richiesta.",
    ]
    assert [item["status"] for item in listed] == ["PROPOSED", "FAILED", "REJECTED", "PROPOSED"]
    assert [item["cost_microusd"] for item in listed] == [800_000, 0, 300_000, 400_000]
    newest = listed[0]
    assert set(newest) == {
        "generation_id",
        "requested_at",
        "request",
        "assertions",
        "changes",
        "status",
        "base_design_version_number",
        "applied_design_version_number",
        "cost_microusd",
    }
    assert newest["generation_id"] == retried["result"]["generation_id"]
    assert newest["assertions"] == ["Il tono resta caldo e rassicurante."]
    assert newest["changes"] == iteration_payload()["changes"]
    assert newest["base_design_version_number"] == 2
    assert newest["applied_design_version_number"] is None
    assert listed[2]["changes"] == []
    applied = next(item for item in after if item["request"] == "Prima richiesta.")
    assert applied["status"] == "APPLIED"
    assert applied["applied_design_version_number"] == 3


def test_iteration_jobs_are_read_on_their_own_route():
    versions = applied_versions()
    generator = ScriptedMockupGenerator(answer(iteration_payload()), answer(draft_payload()))
    client, registry = client_for(runtime(generator, versions=versions))
    with client:
        started, _done = iterate(client, registry, versions)
        as_mockup = client.get(f"{MOCKUPS}/jobs/{started['job_id']}")
        mockup = generated(client, registry, versions)
        as_iteration = client.get(f"{ITERATIONS}/jobs/{mockup['job_id']}")
    for response in (as_mockup, as_iteration):
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "GENERATION_JOB_NOT_FOUND"}


def test_an_overloaded_provider_gets_at_most_two_generations_for_one_iteration():
    generator, client, pauses = anthropic_generator(*(overloaded() for _ in range(4)))
    store = MemoryMockupStore()
    versions = applied_versions()
    app = DesignIterationApplication(runtime(generator, store, versions))
    body = IterationRequest.model_validate(request_body(versions))
    with pytest.raises(ProposalGenerationError) as failed:
        asyncio.run(
            app.generate_iteration(owner_user_id=OWNER_ID, project_id=PROJECT_ID, body=body)
        )
    assert failed.value.code == "PROVIDER_UNAVAILABLE"
    assert len(client.messages.calls) == 2 and pauses.calls == []
    assert [store.payload(item, "APPLICATION_RESULT") for item in store.order] == [
        {"status": "PROVIDER_UNAVAILABLE", "role": "MOCKUP_ATTEMPT"},
        {"status": "FAILED", "code": "PROVIDER_UNAVAILABLE"},
    ]
    assert all(store.context(item)["purpose"] == DESIGN_ITERATION for item in store.order)


def test_generations_still_running_are_not_listed():
    records = [
        {
            "generation_id": "b",
            "recorded_at": "2026-09-29T09:00:02+00:00",
            "context": {"command_id": "c1", "design_version_id": "v"},
            "events": {"PROVIDER_RESULT": {}},
        },
        {
            "generation_id": "a",
            "recorded_at": "2026-09-29T09:00:01+00:00",
            "context": {"command_id": "c2", "design_version_id": "v"},
            "events": {"APPLICATION_RESULT": {"status": "RATE_LIMITED", "role": "MOCKUP_ATTEMPT"}},
        },
    ]
    assert iteration_items(records, ()) == []
