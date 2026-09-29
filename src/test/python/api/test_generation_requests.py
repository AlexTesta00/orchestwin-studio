from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_jobs import (
    GENERATION_JOB_CANCELLED,
    GenerationJobKind,
    GenerationJobStatus,
    GenerationOperation,
)
from orchestwin.api.generation_requests import (
    PREFERENCE_APPLIED,
    RESPOND_ASYNC,
    SERVER_ERROR,
    generation_request,
    prefers_async,
    request_key,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.proposal_evidence import ProposalEvidenceError
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.real_runtime import RealModelRuntimeError
from orchestwin.workflow.repository import HumanGateStateConflict

PREFIX = "/api/v1"
OWNER = UUID("00000000-0000-4000-8000-000000000101")
STRANGER = UUID("00000000-0000-4000-8000-000000000102")
PROJECT = UUID("00000000-0000-4000-8000-000000000103")
OTHER_PROJECT = UUID("00000000-0000-4000-8000-000000000104")
NOW = datetime(2026, 9, 28, 10, 30, tzinfo=UTC)
PROBE = f"{PREFIX}/projects/{PROJECT}/probe"
JOBS = f"{PREFIX}/projects/{PROJECT}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
NOTE = {"text": "Rendi il riepilogo piu chiaro."}
JOB_KEYS = {
    "job_id",
    "kind",
    "operation",
    "status",
    "stage",
    "attempt",
    "started_at",
    "finished_at",
    "alternative_id",
    "result",
    "failure",
    "response",
}


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=40)


class Echo(BaseModel):
    owner: UUID
    text: str
    created_at: datetime
    confidence: float
    codes: tuple[str, ...]


class BrokenHandlerError(RuntimeError):
    pass


async def broken_handler(_request, error):
    raise LookupError("secret detail of a broken handler") from error


def account(identifier: UUID) -> UserAccount:
    return UserAccount(
        id=identifier,
        email=NormalizedEmail(f"{identifier.hex[-6:]}@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class Identity:
    def __init__(self):
        self.tokens: dict[str, UUID] = {}

    def issue(self, token: str, owner: UUID = OWNER) -> dict[str, str]:
        self.tokens[token] = owner
        return {"Authorization": f"Bearer {token}"}

    async def current_user(self, token: str):
        owner = self.tokens.get(token)
        return None if owner is None else account(owner)


class Probe:
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.gate: asyncio.Event | None = None
        self.entered = threading.Event()
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def __call__(self, owner: UUID, project_id: UUID, body: Note):
        self.calls.append((owner, project_id, body.text))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome(owner, body)
        return self.outcome


def probe_router(probe: Probe) -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/probe")

    @router.post("/model", response_model=Echo, status_code=201)
    async def modelled(
        project_id: UUID,
        body: Note,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def call():
            return await probe(user.id, project_id, body)

        return await generation_request(
            request,
            GenerationOperation.DESIGN_EVALUATION,
            call,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    @router.post("/plain", status_code=201)
    async def plain(
        project_id: UUID,
        body: Note,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        async def call():
            return await probe(user.id, project_id, body)

        return await generation_request(
            request,
            GenerationOperation.DISCUSSION_START,
            call,
            owner_user_id=user.id,
            project_id=project_id,
            body=body,
        )

    return router


def studio(probe: Probe):
    identity = Identity()
    application = create_app(
        ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None),
        runtime=ApplicationRuntime(identity_service=identity),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    application.include_router(probe_router(probe), prefix=PREFIX)
    application.add_exception_handler(BrokenHandlerError, broken_handler)
    return application, identity


def echo(owner: UUID, body: Note) -> Echo:
    return Echo(
        owner=owner,
        text=body.text,
        created_at=NOW,
        confidence=1e-07,
        codes=("REQ-001", "REQ-002"),
    )


def listing(owner: UUID, body: Note) -> dict[str, object]:
    return {
        "owner": owner,
        "recorded_at": NOW,
        "items": ("uno", 2.5, None),
        "nested": {"text": body.text, "ratio": 0.1},
    }


def answered(response) -> dict[str, object]:
    if not response.content:
        return {"status_code": response.status_code, "body": None}
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status_code": response.status_code, "body": body}


def settle(client: TestClient, job: dict, headers: dict[str, str]) -> dict:
    client.portal.call(client.app.state.generation_jobs.wait, UUID(job["job_id"]))
    reading = client.get(f"{JOBS}/{job['job_id']}", headers=headers)
    assert reading.status_code == 200, reading.text
    return reading.json()


def release(client: TestClient, probe: Probe) -> None:
    client.portal.call(probe.gate.set)


def test_without_the_header_the_operation_answers_at_once_and_starts_no_job():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = identity.issue("token")
    with TestClient(application) as client:
        response = client.post(f"{PROBE}/model", json=NOTE, headers=headers)
        other = client.post(
            f"{PROBE}/model", json=NOTE, headers={**headers, "Prefer": "return=minimal"}
        )
    assert response.status_code == 201
    assert PREFERENCE_APPLIED.lower() not in response.headers
    assert response.json() == {
        "owner": str(OWNER),
        "text": NOTE["text"],
        "created_at": "2026-09-28T10:30:00Z",
        "confidence": 1e-07,
        "codes": ["REQ-001", "REQ-002"],
    }
    assert other.status_code == 201
    assert other.content == response.content
    assert len(application.state.generation_jobs) == 0


@pytest.mark.parametrize(
    ("route", "outcome"),
    [
        ("model", echo),
        ("plain", listing),
        ("plain", lambda owner, body: JSONResponse({"owner": str(owner)}, status_code=200)),
    ],
)
def test_the_job_carries_the_answer_that_the_synchronous_request_gives(route, outcome):
    probe = Probe(outcome)
    application, identity = studio(probe)
    headers = identity.issue("token")
    with TestClient(application) as client:
        synchronous = client.post(f"{PROBE}/{route}", json=NOTE, headers=headers)
        probe.entered.clear()
        probe.gate = asyncio.Event()
        started = client.post(f"{PROBE}/{route}", json=NOTE, headers={**headers, **ASYNC})
        assert probe.entered.wait(5)
        running = client.get(f"{JOBS}/{started.json()['job_id']}", headers=headers).json()
        release(client, probe)
        done = settle(client, started.json(), headers)
    assert started.status_code == 202
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    job = started.json()
    assert set(job) == JOB_KEYS
    assert job["kind"] == GenerationJobKind.REQUEST.value
    assert job["operation"] == (
        "DESIGN_EVALUATION" if route == "model" else GenerationOperation.DISCUSSION_START.value
    )
    for payload in (job, running):
        assert payload["status"] == "RUNNING"
        assert payload["stage"] == "GENERATING"
        assert payload["attempt"] == 1
        assert payload["finished_at"] is None
        assert payload["response"] is None
        assert payload["alternative_id"] is None
        assert payload["result"] is None and payload["failure"] is None
    assert done["job_id"] == job["job_id"]
    assert done["status"] == "SUCCEEDED"
    assert done["stage"] is None and done["attempt"] == 1
    assert done["finished_at"] is not None
    assert done["result"] is None and done["failure"] is None
    assert done["response"] == answered(synchronous)
    assert probe.calls == [(OWNER, PROJECT, NOTE["text"])] * 2


@pytest.mark.parametrize(
    "error",
    [
        HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"}),
        HTTPException(503, detail="design_generation_service_unavailable"),
        ProposalGenerationError("TIMEOUT"),
        ProposalGenerationError("CONTEXT_BUDGET_EXCEEDED"),
        ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),
        ProposalGenerationError("INVALID_PROVIDER_OUTPUT"),
        RealModelRuntimeError("REAL_MODEL_RUNTIME_UNAVAILABLE"),
        ProposalEvidenceError("GENERATION_EVIDENCE_WRITE_FAILED"),
        HumanGateStateConflict(),
        RequestValidationError(
            [{"type": "missing", "loc": ("body", "text"), "msg": "Field required", "input": {}}]
        ),
        RuntimeError("secret detail never shown"),
        BrokenHandlerError("secret detail never shown"),
    ],
    ids=lambda error: type(error).__name__ + ":" + str(getattr(error, "code", "")),
)
@pytest.mark.parametrize("route", ["model", "plain"])
def test_the_job_answers_every_error_like_the_application(route, error):
    probe = Probe(error)
    application, identity = studio(probe)
    headers = identity.issue("token")
    with TestClient(application, raise_server_exceptions=False) as client:
        synchronous = client.post(f"{PROBE}/{route}", json=NOTE, headers=headers)
        started = client.post(f"{PROBE}/{route}", json=NOTE, headers={**headers, **ASYNC})
        done = settle(client, started.json(), headers)
    expected = answered(synchronous)
    assert synchronous.status_code >= 400
    assert started.status_code == 202
    assert done["status"] == "FAILED"
    assert done["response"] == expected
    assert done["result"] is None and done["failure"] is None
    assert "secret" not in str(done)
    assert "Traceback" not in str(done)
    if type(error) in {RuntimeError, BrokenHandlerError}:
        assert expected == {"status_code": 500, "body": SERVER_ERROR}


def test_errors_found_before_the_job_starts_are_answered_at_once():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = identity.issue("token")
    invalid = {"text": "x" * 41}
    with TestClient(application) as client:
        refused_body = client.post(f"{PROBE}/model", json=invalid, headers=headers)
        refused_body_async = client.post(
            f"{PROBE}/model", json=invalid, headers={**headers, **ASYNC}
        )
        extra = client.post(f"{PROBE}/model", json={**NOTE, "x": 1}, headers={**headers, **ASYNC})
        anonymous = client.post(f"{PROBE}/model", json=NOTE)
        anonymous_async = client.post(f"{PROBE}/model", json=NOTE, headers=ASYNC)
        registry = application.state.generation_jobs

        async def fill():
            gate = asyncio.Event()

            async def waiting(progress):
                await gate.wait()
                return {}

            for index in range(4):
                registry.start(OWNER, uuid4(), GenerationJobKind.MOCKUP, str(index), waiting)
            return gate

        gate = client.portal.call(fill)
        crowded = client.post(f"{PROBE}/model", json=NOTE, headers={**headers, **ASYNC})
        synchronous = client.post(f"{PROBE}/model", json=NOTE, headers=headers)
        client.portal.call(gate.set)
        application.state.generation_jobs = None
        unavailable = client.post(f"{PROBE}/model", json=NOTE, headers={**headers, **ASYNC})
        without_registry = client.post(f"{PROBE}/model", json=NOTE, headers=headers)
        application.state.generation_jobs = registry
    assert refused_body.status_code == 422
    assert answered(refused_body_async) == answered(refused_body)
    assert refused_body.json()["detail"] == "invalid_request"
    assert extra.status_code == 422
    assert anonymous.status_code == 401
    assert answered(anonymous_async) == answered(anonymous)
    assert crowded.status_code == 429
    assert crowded.json() == {"detail": {"code": "TOO_MANY_GENERATIONS"}}
    assert synchronous.status_code == 201
    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": {"code": "GENERATION_JOBS_UNAVAILABLE"}}
    assert without_registry.status_code == 201
    assert [call[2] for call in probe.calls] == [NOTE["text"]] * 2
    assert registry.project_jobs(OWNER, PROJECT) == ()


def test_the_same_request_joins_the_running_job_and_another_body_starts_another():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = {**identity.issue("token"), **ASYNC}
    other_note = {"text": "Aggiungi il filtro per data."}
    with TestClient(application) as client:
        probe.gate = asyncio.Event()
        first = client.post(f"{PROBE}/model", json=NOTE, headers=headers).json()
        again = client.post(f"{PROBE}/model", json=NOTE, headers=headers).json()
        other = client.post(f"{PROBE}/model", json=other_note, headers=headers).json()
        plain = client.post(f"{PROBE}/plain", json=NOTE, headers=headers).json()
        release(client, probe)
        done = [settle(client, job, headers) for job in (first, other, plain)]
        probe.gate = None
        later = client.post(f"{PROBE}/model", json=NOTE, headers=headers).json()
        settle(client, later, headers)
    assert again["job_id"] == first["job_id"]
    assert len({first["job_id"], other["job_id"], plain["job_id"], later["job_id"]}) == 4
    assert [job["status"] for job in done] == ["SUCCEEDED"] * 3
    assert sorted(call[2] for call in probe.calls) == sorted(
        [NOTE["text"], other_note["text"], NOTE["text"], NOTE["text"]]
    )


def test_a_job_runs_with_the_identity_that_started_it_and_is_read_with_a_valid_token():
    probe = Probe(echo)
    application, identity = studio(probe)
    first = identity.issue("first")
    with TestClient(application) as client:
        probe.gate = asyncio.Event()
        started = client.post(f"{PROBE}/model", json=NOTE, headers={**first, **ASYNC}).json()
        assert probe.entered.wait(5)
        identity.tokens.pop("first")
        release(client, probe)
        client.portal.call(application.state.generation_jobs.wait, UUID(started["job_id"]))
        expired = client.get(f"{JOBS}/{started['job_id']}", headers=first)
        renewed = client.get(f"{JOBS}/{started['job_id']}", headers=identity.issue("second"))
        stranger = identity.issue("stranger", STRANGER)
        foreign = client.get(f"{JOBS}/{started['job_id']}", headers=stranger)
        foreign_list = client.get(JOBS, headers=stranger)
        other_project = client.get(
            f"{PREFIX}/projects/{OTHER_PROJECT}/generation-jobs/{started['job_id']}",
            headers=identity.issue("third"),
        )
        unknown = client.get(f"{JOBS}/{uuid4()}", headers=identity.issue("fourth"))
    assert expired.status_code == 401
    assert expired.json() == {"detail": "invalid_authentication"}
    assert renewed.status_code == 200
    assert renewed.json()["status"] == "SUCCEEDED"
    assert renewed.json()["response"]["body"]["owner"] == str(OWNER)
    assert probe.calls == [(OWNER, PROJECT, NOTE["text"])]
    for response in (foreign, other_project, unknown):
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "GENERATION_JOB_NOT_FOUND"}}
    assert foreign_list.json() == {"items": []}


def test_the_jobs_of_a_project_are_listed_oldest_first_with_every_kind():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = identity.issue("token")
    registry = application.state.generation_jobs
    alternative = uuid4()
    with TestClient(application) as client:
        gate = client.portal.call(asyncio.Event)

        async def waiting(progress):
            await gate.wait()
            return {"status": "MOCKUP_GENERATED"}

        async def background():
            mockup = registry.start(
                OWNER,
                PROJECT,
                GenerationJobKind.MOCKUP,
                "hash:alternative",
                waiting,
                alternative_id=alternative,
            )
            iteration = registry.start(
                OWNER, PROJECT, GenerationJobKind.ITERATION, "hash", waiting, alternative_id=None
            )
            registry.start(OWNER, OTHER_PROJECT, GenerationJobKind.MOCKUP, "elsewhere", waiting)
            registry.start(STRANGER, PROJECT, GenerationJobKind.MOCKUP, "stranger", waiting)
            return mockup, iteration

        mockup, iteration = client.portal.call(background)
        probe.outcome = HTTPException(409, detail={"code": "DESIGN_CONTEXT_CHANGED"})
        finished = client.post(f"{PROBE}/plain", json=NOTE, headers={**headers, **ASYNC}).json()
        client.portal.call(registry.wait, UUID(finished["job_id"]))
        probe.gate = asyncio.Event()
        probe.outcome = echo
        running_request = client.post(
            f"{PROBE}/model", json=NOTE, headers={**headers, **ASYNC}
        ).json()
        running = client.get(JOBS, params={"status": "RUNNING"}, headers=headers).json()
        everything = client.get(JOBS, headers=headers).json()
        failed = client.get(JOBS, params={"status": "FAILED"}, headers=headers).json()
        invalid = client.get(JOBS, params={"status": "WAITING"}, headers=headers)
        read_mockup = client.get(f"{JOBS}/{mockup.job_id}", headers=headers).json()
        release(client, probe)
        client.portal.call(gate.set)
        client.portal.call(registry.wait, UUID(running_request["job_id"]))
    assert [item["job_id"] for item in running["items"]] == [
        str(mockup.job_id),
        str(iteration.job_id),
        running_request["job_id"],
    ]
    assert [item["operation"] for item in running["items"]] == [
        "MOCKUP",
        "ITERATION",
        "DESIGN_EVALUATION",
    ]
    assert [item["kind"] for item in running["items"]] == ["MOCKUP", "ITERATION", "REQUEST"]
    assert all(set(item) == JOB_KEYS for item in everything["items"])
    assert [item["job_id"] for item in everything["items"]] == [
        str(mockup.job_id),
        str(iteration.job_id),
        finished["job_id"],
        running_request["job_id"],
    ]
    assert [item["job_id"] for item in failed["items"]] == [finished["job_id"]]
    assert failed["items"][0]["response"] == {
        "status_code": 409,
        "body": {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}},
    }
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid_request"
    assert read_mockup["kind"] == "MOCKUP"
    assert read_mockup["operation"] == "MOCKUP"
    assert read_mockup["alternative_id"] == str(alternative)
    assert read_mockup["response"] is None


def test_stopping_the_application_cancels_the_running_requests():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = {**identity.issue("token"), **ASYNC}
    registry = application.state.generation_jobs
    with TestClient(application) as client:
        probe.gate = asyncio.Event()
        started = client.post(f"{PROBE}/model", json=NOTE, headers=headers).json()
        assert probe.entered.wait(5)
    [job] = registry.project_jobs(OWNER, PROJECT)
    assert str(job.job_id) == started["job_id"]
    assert job.status is GenerationJobStatus.FAILED
    assert job.failure == {"code": GENERATION_JOB_CANCELLED, "reasons": []}
    assert job.response is None
    with pytest.raises(HTTPException) as closed:
        registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.REQUEST,
            "after",
            None,
            operation=GenerationOperation.DESIGN_PROPOSAL,
        )
    assert closed.value.detail == {"code": "GENERATION_JOBS_UNAVAILABLE"}


def test_the_application_serves_the_job_routes_and_lets_browsers_send_the_preference():
    probe = Probe(echo)
    application, identity = studio(probe)
    headers = identity.issue("token")
    origin = {"Origin": "http://127.0.0.1:5173"}
    paths = application.openapi()["paths"]
    with TestClient(application) as client:
        preflight = client.options(
            f"{PROBE}/model",
            headers={
                **origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization, content-type, prefer",
            },
        )
        started = client.post(f"{PROBE}/model", json=NOTE, headers={**headers, **ASYNC, **origin})
        settle(client, started.json(), headers)
    assert f"{PREFIX}/projects/{{project_id}}/generation-jobs" in paths
    assert f"{PREFIX}/projects/{{project_id}}/generation-jobs/{{job_id}}" in paths
    assert preflight.status_code == 200
    assert "prefer" in preflight.headers["access-control-allow-headers"].lower()
    assert PREFERENCE_APPLIED.lower() in started.headers["access-control-expose-headers"].lower()


def scope(*values: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(b"prefer", value.encode("latin-1")) for value in values],
        }
    )


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((), False),
        (("respond-async",), True),
        (("RESPOND-ASYNC",), True),
        ((" respond-async ",), True),
        (("return=minimal, respond-async",), True),
        (("respond-async; wait=10",), True),
        (("wait=10", "respond-async"), True),
        (("return=minimal",), False),
        (("respond-asynchronously",), False),
        (("return=respond-async",), False),
    ],
)
def test_the_preference_is_read_as_the_standard_writes_it(values, expected):
    assert prefers_async(scope(*values)) is expected


def test_the_key_of_a_request_is_its_operation_its_resource_and_the_hash_of_its_body():
    first = Note(text="Primo")
    same = Note.model_validate({"text": "Primo"})
    other = Note(text="Secondo")
    discussion = {"project_id": str(PROJECT), "discussion_id": "d-1"}
    key = request_key(GenerationOperation.DISCUSSION_ROUND, discussion, first)
    assert key == request_key(GenerationOperation.DISCUSSION_ROUND, discussion, same)
    assert key.startswith("DISCUSSION_ROUND:discussion_id=d-1:")
    assert len(key.rsplit(":", 1)[1]) == 64
    assert key != request_key(GenerationOperation.DISCUSSION_ROUND, discussion, other)
    assert key != request_key(
        GenerationOperation.DISCUSSION_ROUND, {**discussion, "discussion_id": "d-2"}, first
    )
    assert key != request_key(GenerationOperation.DISCUSSION_START, discussion, first)
    bodyless = request_key(GenerationOperation.DESIGN_PROPOSAL, {"project_id": str(PROJECT)})
    assert bodyless == request_key(
        GenerationOperation.DESIGN_PROPOSAL, {"project_id": str(OTHER_PROJECT)}
    )
    assert bodyless.startswith("DESIGN_PROPOSAL:") and bodyless.count(":") == 1
