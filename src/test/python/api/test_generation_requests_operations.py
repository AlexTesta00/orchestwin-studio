from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.design_discussion import (
    DesignDiscussionApplication,
    DesignDiscussionCommandStatus,
    DesignDiscussionResult,
)
from orchestwin.api.design_loop import DesignLoopApplication
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC, SERVER_ERROR
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.evaluation.proposer_evaluator import TWIN_REVIEW_TASK
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.design import DesignProposalIssueCode
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.real_runtime import RealModelRuntimeError
from orchestwin.models.requirements import RequirementsProposalIssueCode
from orchestwin.projects.design_application import (
    DesignGenerationIssueCode,
    DesignGenerationResult,
    DesignGenerationStatus,
)
from orchestwin.projects.requirements_application import (
    RequirementsGenerationIssueCode,
    RequirementsGenerationResult,
    RequirementsGenerationStatus,
)
from orchestwin.twins.application import (
    GroundedSnapshotGenerationResult,
    PersonaProposalApplicationResult,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
)
from src.test.python.api import test_design_discussion_api as discussion_harness
from src.test.python.api import test_design_loop_api as loop_harness
from src.test.python.api.test_requirements_api import specification_version
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_discussion import BRUNO, discussion, discussion_round
from src.test.python.artifacts.test_design_package_extension import (
    extended_version,
    fixture_package,
)
from src.test.python.twins.test_user_modeling_persistence import (
    persona_version,
    snapshot_version,
    twin_version,
)

PREFIX = "/api/v1"
OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
DISCUSSION_ID = UUID("00000000-0000-4000-8000-000000000950")
NOW = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)
PROJECT_PATH = f"{PREFIX}/projects/{PROJECT}"
JOBS = f"{PROJECT_PATH}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
EVALUATION = {
    "design_version_id": str(design_fixtures.DESIGN_VERSION_ID),
    "design_content_hash": "a" * 64,
    "locale": "en-US",
    "mode": "TWIN_REVIEW",
}
OPENING = {
    "design_version_id": str(design_fixtures.DESIGN_VERSION_ID),
    "design_content_hash": "b" * 64,
    "locale": "it-IT",
    "owner_note": "Parlate del modulo di registrazione.",
}
ROUND = {"expected_round_count": 1, "owner_note": "Siate concreti."}
ROUTES = {
    "PERSONA_PROPOSAL": ("/user-modeling/personas/proposals", None),
    "USER_TWIN_GENERATION": ("/user-modeling/snapshots/generate", None),
    "REQUIREMENTS_PROPOSAL": ("/requirements/proposals", None),
    "DESIGN_PROPOSAL": ("/design/proposals", None),
    "DESIGN_REGENERATION": ("/design/regenerations", None),
    "DESIGN_EVALUATION": ("/design/evaluations", EVALUATION),
    "DISCUSSION_START": ("/design/discussions", OPENING),
    "DISCUSSION_ROUND": (f"/design/discussions/{DISCUSSION_ID}/rounds", ROUND),
}


def account() -> UserAccount:
    return UserAccount(
        id=OWNER,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def settings() -> ApplicationSettings:
    return ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None)


def application_for(runtime: ApplicationRuntime):
    application = create_app(
        settings(), runtime=runtime, auth_settings=AuthApiSettings(_env_file=None)
    )
    application.dependency_overrides[current_user_dependency] = account
    return application


class Scripted:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def __call__(self, *_, **arguments):
        self.calls.append(arguments)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def studio(scripted: Scripted, monkeypatch):
    monkeypatch.setattr(DesignLoopApplication, "evaluate", scripted)
    monkeypatch.setattr(DesignDiscussionApplication, "start", scripted)
    monkeypatch.setattr(DesignDiscussionApplication, "next_round", scripted)
    commands = SimpleNamespace(
        propose_personas=scripted,
        generate_grounded_snapshot=scripted,
        snapshot_context_is_current=scripted,
    )
    return application_for(
        ApplicationRuntime(
            identity_service=object(),
            user_modeling_services=SimpleNamespace(
                commands=commands,
                revisions=SimpleNamespace(),
                queries=SimpleNamespace(),
                gates=SimpleNamespace(),
            ),
            requirements_generation_service=SimpleNamespace(generate=scripted),
            design_generation_service=SimpleNamespace(generate=scripted, regenerate=scripted),
        )
    )


def answered(response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status_code": response.status_code, "body": body}


def evaluation(monkeypatch):
    app, body = loop_harness.application(
        monkeypatch,
        templates=(
            loop_harness.template(
                "UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."
            ),
        ),
    )
    return loop_harness.evaluate(app, body)


CREATED = UserModelingApplicationStatus.CREATED
REJECTED = UserModelingApplicationStatus.REJECTED
CASES = [
    (
        "PERSONA_PROPOSAL",
        lambda _: PersonaProposalApplicationResult(status=CREATED, versions=(persona_version(),)),
    ),
    (
        "PERSONA_PROPOSAL",
        lambda _: PersonaProposalApplicationResult(
            status=REJECTED, issue=UserModelingApplicationIssueCode.PROJECT_NOT_FOUND
        ),
    ),
    ("PERSONA_PROPOSAL", lambda _: ProposalGenerationError("TIMEOUT")),
    (
        "USER_TWIN_GENERATION",
        lambda _: GroundedSnapshotGenerationResult(
            status=CREATED, snapshot_version=snapshot_version(), twin_versions=(twin_version(),)
        ),
    ),
    (
        "USER_TWIN_GENERATION",
        lambda _: GroundedSnapshotGenerationResult(
            status=REJECTED, issue=UserModelingApplicationIssueCode.PERSONA_CONFIRMATION_REQUIRED
        ),
    ),
    ("USER_TWIN_GENERATION", lambda _: ProposalGenerationError("GENERATION_BUDGET_EXCEEDED")),
    (
        "REQUIREMENTS_PROPOSAL",
        lambda _: RequirementsGenerationResult(
            status=RequirementsGenerationStatus.CREATED, version=specification_version()
        ),
    ),
    (
        "REQUIREMENTS_PROPOSAL",
        lambda _: RequirementsGenerationResult(
            status=RequirementsGenerationStatus.REJECTED,
            issue=RequirementsGenerationIssueCode.CONTEXT_CHANGED,
        ),
    ),
    ("REQUIREMENTS_PROPOSAL", lambda _: RealModelRuntimeError("REAL_MODEL_RUNTIME_UNAVAILABLE")),
    (
        "DESIGN_PROPOSAL",
        lambda _: DesignGenerationResult(
            status=DesignGenerationStatus.CREATED, version=extended_version(fixture_package())
        ),
    ),
    (
        "DESIGN_PROPOSAL",
        lambda _: DesignGenerationResult(
            status=DesignGenerationStatus.REJECTED,
            issue=DesignGenerationIssueCode.PROJECT_NOT_FOUND,
        ),
    ),
    ("DESIGN_PROPOSAL", lambda _: ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED")),
    (
        "DESIGN_REGENERATION",
        lambda _: DesignGenerationResult(
            status=DesignGenerationStatus.CREATED, version=design_fixtures.design_version()
        ),
    ),
    (
        "DESIGN_REGENERATION",
        lambda _: DesignGenerationResult(
            status=DesignGenerationStatus.REJECTED,
            issue=DesignGenerationIssueCode.CONTEXT_CHANGED,
        ),
    ),
    ("DESIGN_REGENERATION", lambda _: ProposalGenerationError("INVALID_PROVIDER_OUTPUT")),
    ("DESIGN_REGENERATION", lambda _: RuntimeError("unexpected secret detail")),
    ("DESIGN_EVALUATION", evaluation),
    (
        "DESIGN_EVALUATION",
        lambda _: HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"}),
    ),
    ("DESIGN_EVALUATION", lambda _: ProposalGenerationError("CONTEXT_BUDGET_EXCEEDED")),
    (
        "DISCUSSION_START",
        lambda _: DesignDiscussionResult(
            status=DesignDiscussionCommandStatus.STARTED, discussion=discussion()
        ),
    ),
    (
        "DISCUSSION_START",
        lambda _: HTTPException(409, detail={"code": "DESIGN_DISCUSSION_OPEN"}),
    ),
    ("DISCUSSION_START", lambda _: ProposalGenerationError("INVALID_TWIN_DISCUSSION_OUTPUT")),
    (
        "DISCUSSION_ROUND",
        lambda _: DesignDiscussionResult(
            status=DesignDiscussionCommandStatus.ROUND_RECORDED,
            discussion=discussion(
                rounds=(discussion_round(), discussion_round(2, replies=(BRUNO,)))
            ),
        ),
    ),
    (
        "DISCUSSION_ROUND",
        lambda _: HTTPException(404, detail={"code": "DESIGN_DISCUSSION_NOT_FOUND"}),
    ),
    (
        "DISCUSSION_ROUND",
        lambda _: HTTPException(422, detail={"code": "DISCUSSION_NOTE_INVALID"}),
    ),
]


@pytest.mark.parametrize(("operation", "outcome"), CASES, ids=[case[0] for case in CASES])
def test_every_operation_answers_the_same_with_and_without_the_preference(
    operation, outcome, monkeypatch
):
    scripted = Scripted(outcome(monkeypatch))
    application = studio(scripted, monkeypatch)
    path, body = ROUTES[operation]
    with TestClient(application, raise_server_exceptions=False) as client:
        synchronous = client.post(f"{PROJECT_PATH}{path}", json=body)
        started = client.post(f"{PROJECT_PATH}{path}", json=body, headers=ASYNC)
        assert started.status_code == 202, started.text
        job_id = started.json()["job_id"]
        client.portal.call(application.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()
    expected = answered(synchronous)
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert (job["kind"], job["operation"]) == ("REQUEST", operation)
    assert job["response"] == expected
    assert job["status"] == ("SUCCEEDED" if synchronous.status_code < 400 else "FAILED")
    assert (job["result"], job["failure"], job["alternative_id"], job["stage"]) == (
        None,
        None,
        None,
        None,
    )
    assert len(scripted.calls) == 2
    assert scripted.calls[0] == scripted.calls[1]
    assert (scripted.calls[0]["owner_user_id"], scripted.calls[0]["project_id"]) == (
        OWNER,
        PROJECT,
    )
    if type(scripted.outcome) is RuntimeError:
        assert expected == {"status_code": 500, "body": SERVER_ERROR}
        assert "secret" not in str(job)


REASONED_REFUSALS = [
    (
        "DESIGN_PROPOSAL",
        DesignGenerationResult(
            status=DesignGenerationStatus.REJECTED,
            issue=DesignGenerationIssueCode.PROPOSAL_REJECTED,
            proposal_issue=DesignProposalIssueCode.UX_DESIGNER_REQUIRED,
        ),
        "UX_DESIGNER_REQUIRED",
    ),
    (
        "REQUIREMENTS_PROPOSAL",
        RequirementsGenerationResult(
            status=RequirementsGenerationStatus.REJECTED,
            issue=RequirementsGenerationIssueCode.PROPOSAL_REJECTED,
            proposal_issue=RequirementsProposalIssueCode.REQUIREMENTS_ANALYST_REQUIRED,
        ),
        "REQUIREMENTS_ANALYST_REQUIRED",
    ),
]


@pytest.mark.parametrize(
    ("operation", "outcome", "reason"),
    REASONED_REFUSALS,
    ids=[case[0] for case in REASONED_REFUSALS],
)
def test_a_refused_proposal_gives_its_reason_with_and_without_the_preference(
    operation, outcome, reason, monkeypatch
):
    application = studio(Scripted(outcome), monkeypatch)
    path = f"{PROJECT_PATH}{ROUTES[operation][0]}"
    with TestClient(application) as client:
        synchronous = client.post(path)
        started = client.post(path, headers=ASYNC)
        job_id = started.json()["job_id"]
        client.portal.call(application.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()
    refusal = {
        "status_code": 409,
        "body": {"detail": {"code": "PROPOSAL_REJECTED", "proposal_issue": reason}},
    }
    assert answered(synchronous) == refusal
    assert (job["operation"], job["status"], job["response"]) == (operation, "FAILED", refusal)


@pytest.mark.parametrize(
    ("operation", "invalid"),
    [
        ("DESIGN_EVALUATION", {**EVALUATION, "design_content_hash": "short"}),
        ("DISCUSSION_START", {**OPENING, "locale": "?"}),
        ("DISCUSSION_ROUND", {**ROUND, "expected_round_count": 0}),
    ],
)
def test_an_invalid_body_is_refused_at_once_with_or_without_the_preference(
    operation, invalid, monkeypatch
):
    scripted = Scripted(None)
    application = studio(scripted, monkeypatch)
    path, _ = ROUTES[operation]
    with TestClient(application) as client:
        synchronous = client.post(f"{PROJECT_PATH}{path}", json=invalid)
        refused = client.post(f"{PROJECT_PATH}{path}", json=invalid, headers=ASYNC)
        listed = client.get(JOBS).json()
    assert synchronous.status_code == 422
    assert answered(refused) == answered(synchronous)
    assert listed == {"items": []}
    assert scripted.calls == []


def in_process(application, requests):
    async def scenario():
        answers = []
        registry = application.state.generation_jobs
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=application), base_url="http://studio"
        ) as client:
            for path, body, headers in requests:
                answer = await client.post(f"{PROJECT_PATH}{path}", json=body, headers=headers)
                if answer.status_code == 202:
                    job_id = answer.json()["job_id"]
                    await registry.wait(UUID(job_id))
                    answer = await client.get(f"{JOBS}/{job_id}")
                answers.append(answer)
        await registry.close()
        return answers

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    ("outcome", "status_code", "results"),
    [
        (loop_harness.review(), 201, [{"status": "DESIGN_EVALUATION_RECORDED", "issue": None}]),
        (
            ProposalGenerationError("AUTHENTICATION_FAILED"),
            502,
            [{"status": "FAILED", "code": "AUTHENTICATION_FAILED"}],
        ),
    ],
)
def test_a_twin_review_run_as_a_job_records_the_evidence_of_the_synchronous_review(
    outcome, status_code, results, monkeypatch
):
    app, body, generator, evidence = loop_harness.reviewing(monkeypatch, outcome, outcome)
    runtime = app.runtime
    application = application_for(
        ApplicationRuntime(
            identity_service=object(),
            database_runtime=runtime.database_runtime,
            design_query_service=runtime.design_query_service,
            final_evaluator_runtime=runtime.final_evaluator_runtime,
            proposal_evidence_store=evidence,
            real_model_runtime=runtime.real_model_runtime,
        )
    )
    payload = body.model_dump(mode="json")
    synchronous, job = in_process(
        application,
        [("/design/evaluations", payload, {}), ("/design/evaluations", payload, ASYNC)],
    )
    job = job.json()
    assert synchronous.status_code == status_code
    assert job["operation"] == "DESIGN_EVALUATION"
    assert job["response"]["status_code"] == status_code
    assert [call["task"] for call in generator.calls] == [TWIN_REVIEW_TASK] * 2
    kinds = evidence.kinds()
    assert [kind for index, kind in kinds if index == 0] == [
        kind for index, kind in kinds if index == 1
    ]
    assert [payload for _, kind, payload in evidence.events if kind == "APPLICATION_RESULT"] == (
        results * 2
    )
    if status_code == 201:
        first, second = loop_harness.MemoryRuns.runs
        assert synchronous.json() == first.to_snapshot()
        assert job["response"]["body"] == second.to_snapshot()
    else:
        assert job["response"] == answered(synchronous)
        assert loop_harness.MemoryRuns.runs == []


def test_a_discussion_started_as_a_job_records_the_evidence_of_a_synchronous_start(monkeypatch):
    version = discussion_harness.two_twin_version()
    outcomes = (
        discussion_harness.statement("The form is long."),
        discussion_harness.statement("The form is fine.", stance="SUPPORT", proposals=()),
        discussion_harness.synthesis(),
    )
    body = {
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "locale": "en-US",
    }
    observed = []
    for headers in ({}, ASYNC):
        app, _, generator, evidence = discussion_harness.discussing(
            monkeypatch, *outcomes, version=version
        )
        runtime = app.runtime
        application = application_for(
            ApplicationRuntime(
                identity_service=object(),
                database_runtime=runtime.database_runtime,
                design_query_service=runtime.design_query_service,
                proposal_evidence_store=evidence,
                real_model_runtime=runtime.real_model_runtime,
            )
        )
        [answer] = in_process(application, [("/design/discussions", body, headers)])
        [stored] = discussion_harness.MemoryDiscussions.items.values()
        observed.append((answer.json(), stored, evidence, generator))
    (synchronous, first, first_evidence, first_generator) = observed[0]
    (job, second, second_evidence, second_generator) = observed[1]
    assert synchronous == first.to_snapshot()
    assert job["operation"] == "DISCUSSION_START"
    assert job["response"] == {"status_code": 201, "body": second.to_snapshot()}
    assert first_evidence.kinds() == second_evidence.kinds()
    assert (
        [payload["status"] for payload in second_evidence.payloads("APPLICATION_RESULT")]
        == [payload["status"] for payload in first_evidence.payloads("APPLICATION_RESULT")]
        == [
            "TWIN_STATEMENT_RECORDED",
            "TWIN_STATEMENT_RECORDED",
            "DESIGN_DISCUSSION_STARTED",
        ]
    )
    assert [item.model_generation_id for item in second.rounds[0].statements] + [
        second.rounds[0].synthesis.model_generation_id
    ] == second_evidence.generations
    assert [call["context"]["purpose"] for call in second_generator.calls] == [
        call["context"]["purpose"] for call in first_generator.calls
    ]
