from __future__ import annotations

import asyncio
import contextvars
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from orchestwin.api.generation_jobs import (
    GENERATION_JOB_CANCELLED,
    GENERATION_JOB_FAILED,
    GENERATION_JOBS_UNAVAILABLE,
    MAX_RUNNING_JOBS_PER_OWNER,
    TOO_MANY_GENERATIONS,
    GenerationJobFailure,
    GenerationJobKind,
    GenerationJobProgress,
    GenerationJobRegistry,
    GenerationJobResponse,
    GenerationJobStage,
    GenerationJobStatus,
    GenerationOperation,
    generation_jobs,
)

OWNER = uuid4()
OTHER = uuid4()
PROJECT = uuid4()
OTHER_PROJECT = uuid4()
START = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
MARKER: contextvars.ContextVar[str] = contextvars.ContextVar("marker", default="unset")


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


def run(coroutine):
    return asyncio.run(coroutine)


def finished(value):
    async def factory(progress):
        return value

    return factory


def gated(gate, value=None, *, stages=()):
    async def factory(progress):
        for stage, attempt in stages:
            progress.update(stage, attempt)
        await gate.wait()
        return value or {"status": "MOCKUP_GENERATED"}

    return factory


def raising(error):
    async def factory(progress):
        raise error

    return factory


def test_a_job_moves_from_running_to_succeeded_and_keeps_its_result():
    clock = Clock()

    async def scenario():
        registry = GenerationJobRegistry(clock=clock)
        gate = asyncio.Event()
        alternative = uuid4()
        job = registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.MOCKUP,
            "hash:alt",
            gated(gate, {"status": "MOCKUP_GENERATED"}, stages=[(GenerationJobStage.RETRYING, 2)]),
            alternative_id=alternative,
        )
        await asyncio.sleep(0)
        running = job.to_payload()
        clock.now = START + timedelta(minutes=3)
        gate.set()
        await registry.wait(job.job_id)
        return running, job.to_payload(), alternative

    running, done, alternative = run(scenario())
    assert running["status"] == "RUNNING"
    assert running["stage"] == "RETRYING"
    assert running["attempt"] == 2
    assert running["finished_at"] is None
    assert running["result"] is None and running["failure"] is None
    assert running["kind"] == "MOCKUP"
    assert running["alternative_id"] == str(alternative)
    assert running["started_at"] == START.isoformat()
    assert done["status"] == "SUCCEEDED"
    assert done["stage"] is None
    assert done["finished_at"] == (START + timedelta(minutes=3)).isoformat()
    assert done["result"] == {"status": "MOCKUP_GENERATED"}
    assert running["operation"] == done["operation"] == "MOCKUP"
    assert running["response"] is None and done["response"] is None
    assert set(done) == {
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


@pytest.mark.parametrize(
    "error, status, code, reasons",
    [
        (
            GenerationJobFailure(
                "MOCKUP_QUALITY_REJECTED",
                rejected=True,
                reasons=[{"code": "TABLE_TOO_SHORT", "screen_code": "SCR-002", "detail": "t"}],
            ),
            "REJECTED",
            "MOCKUP_QUALITY_REJECTED",
            [{"code": "TABLE_TOO_SHORT", "screen_code": "SCR-002", "detail": "t"}],
        ),
        (GenerationJobFailure("TIMEOUT"), "FAILED", "TIMEOUT", []),
        (
            RuntimeError("secret detail never shown"),
            "FAILED",
            GENERATION_JOB_FAILED,
            [{"code": "UNEXPECTED_ERROR", "screen_code": None, "detail": "RuntimeError"}],
        ),
    ],
)
def test_failures_are_reported_with_their_code_and_reasons(error, status, code, reasons):
    async def scenario():
        registry = GenerationJobRegistry()
        job = registry.start(OWNER, PROJECT, GenerationJobKind.ITERATION, "hash", raising(error))
        await registry.wait(job.job_id)
        return job.to_payload()

    payload = run(scenario())
    assert payload["status"] == status
    assert payload["failure"] == {"code": code, "reasons": reasons}
    assert payload["result"] is None
    assert "secret" not in str(payload)


def test_a_running_job_with_the_same_owner_project_kind_and_key_is_returned_again():
    async def scenario():
        registry = GenerationJobRegistry()
        gate = asyncio.Event()
        first = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", gated(gate))
        same = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", gated(gate))
        other_key = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "b", gated(gate))
        other_kind = registry.start(OWNER, PROJECT, GenerationJobKind.ITERATION, "a", gated(gate))
        gate.set()
        await registry.wait(first.job_id)
        after = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", finished({}))
        await registry.wait(after.job_id)
        await registry.close()
        return first, same, other_key, other_kind, after, len(registry)

    first, same, other_key, other_kind, after, count = run(scenario())
    assert same is first
    assert len({first.job_id, other_key.job_id, other_kind.job_id, after.job_id}) == 4
    assert count == 4


def test_an_owner_runs_at_most_four_jobs_at_the_same_time():
    async def scenario():
        registry = GenerationJobRegistry()
        gate = asyncio.Event()
        jobs = [
            registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, str(index), gated(gate))
            for index in range(MAX_RUNNING_JOBS_PER_OWNER)
        ]
        with pytest.raises(HTTPException) as refused:
            registry.start(OWNER, OTHER_PROJECT, GenerationJobKind.ITERATION, "x", gated(gate))
        stranger = registry.start(OTHER, PROJECT, GenerationJobKind.MOCKUP, "0", gated(gate))
        gate.set()
        for job in (*jobs, stranger):
            await registry.wait(job.job_id)
        again = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "9", finished({}))
        await registry.wait(again.job_id)
        return refused.value, again

    refused, again = run(scenario())
    assert refused.status_code == 429
    assert refused.detail == {"code": TOO_MANY_GENERATIONS}
    assert again.status is GenerationJobStatus.SUCCEEDED


def test_a_job_is_visible_only_to_its_owner_project_and_kind():
    async def scenario():
        registry = GenerationJobRegistry()
        job = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", finished({}))
        await registry.wait(job.job_id)
        return registry, job

    registry, job = run(scenario())
    assert registry.get(OWNER, PROJECT, job.job_id) is job
    assert registry.get(OWNER, PROJECT, job.job_id, GenerationJobKind.MOCKUP) is job
    assert registry.get(OWNER, PROJECT, job.job_id, GenerationJobKind.ITERATION) is None
    assert registry.get(OTHER, PROJECT, job.job_id) is None
    assert registry.get(OWNER, OTHER_PROJECT, job.job_id) is None
    assert registry.get(OWNER, PROJECT, uuid4()) is None


def test_finished_jobs_expire_after_one_hour_and_the_registry_keeps_at_most_its_capacity():
    clock = Clock()

    async def scenario():
        registry = GenerationJobRegistry(clock=clock, capacity=3)
        old = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "old", finished({}))
        await registry.wait(old.job_id)
        clock.now = START + timedelta(minutes=30)
        kept = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "kept", finished({}))
        await registry.wait(kept.job_id)
        clock.now = START + timedelta(minutes=61)
        visible = (
            registry.get(OWNER, PROJECT, old.job_id),
            registry.get(OWNER, PROJECT, kept.job_id),
        )
        jobs = []
        for index in range(3):
            clock.now = START + timedelta(minutes=62 + index)
            job = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, str(index), finished({}))
            await registry.wait(job.job_id)
            jobs.append(job)
        return visible, jobs, registry

    (old, kept), jobs, registry = run(scenario())
    assert old is None
    assert kept is not None
    assert len(registry) == 3
    assert registry.get(OWNER, PROJECT, kept.job_id) is None
    assert all(registry.get(OWNER, PROJECT, job.job_id) is job for job in jobs)


def test_closing_the_registry_cancels_the_running_jobs_and_refuses_new_ones():
    async def scenario():
        registry = GenerationJobRegistry()
        gate = asyncio.Event()
        job = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", gated(gate))
        await asyncio.sleep(0)
        await registry.close()
        with pytest.raises(HTTPException) as refused:
            registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "b", finished({}))
        return job, refused.value

    job, refused = run(scenario())
    assert job.status is GenerationJobStatus.FAILED
    assert job.failure == {"code": GENERATION_JOB_CANCELLED, "reasons": []}
    assert job.task.cancelled()
    assert refused.status_code == 503
    assert refused.detail == {"code": GENERATION_JOBS_UNAVAILABLE}


def test_a_job_runs_outside_the_context_of_the_request_that_started_it():
    async def scenario():
        registry = GenerationJobRegistry()
        MARKER.set("request")

        async def factory(progress):
            return {"marker": MARKER.get()}

        job = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", factory)
        await registry.wait(job.job_id)
        return job.result

    assert run(scenario()) == {"marker": "unset"}


def test_progress_without_a_job_is_silent_and_a_finished_job_keeps_its_stage():
    GenerationJobProgress().update(GenerationJobStage.VALIDATING, 2)

    async def scenario():
        registry = GenerationJobRegistry()
        job = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", finished({}))
        await registry.wait(job.job_id)
        GenerationJobProgress(job).update(GenerationJobStage.RETRYING, 2)
        return job

    job = run(scenario())
    assert job.stage is None and job.attempt == 1
    assert run(GenerationJobRegistry().wait(uuid4())) is None


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (GenerationJobResponse(201, {"status": "CREATED"}), "SUCCEEDED"),
        (GenerationJobResponse(302, None), "SUCCEEDED"),
        (GenerationJobResponse(409, {"detail": {"code": "DESIGN_CONTEXT_CHANGED"}}), "FAILED"),
        (GenerationJobResponse(500, "Internal Server Error"), "FAILED"),
    ],
)
def test_a_request_job_carries_the_answer_and_its_status_follows_the_status_code(answer, status):
    clock = Clock()

    async def scenario():
        registry = GenerationJobRegistry(clock=clock)
        gate = asyncio.Event()

        async def factory(progress):
            await gate.wait()
            return answer

        job = registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.REQUEST,
            "DESIGN_EVALUATION:hash",
            factory,
            operation=GenerationOperation.DESIGN_EVALUATION,
        )
        await asyncio.sleep(0)
        running = job.to_payload()
        clock.now = START + timedelta(seconds=107)
        gate.set()
        await registry.wait(job.job_id)
        return running, job.to_payload()

    running, done = run(scenario())
    assert running["kind"] == "REQUEST"
    assert running["operation"] == "DESIGN_EVALUATION"
    assert (running["status"], running["stage"], running["attempt"]) == ("RUNNING", "GENERATING", 1)
    assert running["response"] is None
    assert done["status"] == status
    assert done["stage"] is None and done["attempt"] == 1
    assert done["finished_at"] == (START + timedelta(seconds=107)).isoformat()
    assert done["response"] == {"status_code": answer.status_code, "body": answer.body}
    assert done["result"] is None and done["failure"] is None
    assert done["alternative_id"] is None


def test_every_job_names_its_operation_and_a_request_job_needs_one():
    async def scenario():
        registry = GenerationJobRegistry()
        mockup = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "a", finished({}))
        iteration = registry.start(OWNER, PROJECT, GenerationJobKind.ITERATION, "a", finished({}))
        with pytest.raises(ValueError):
            registry.start(OWNER, PROJECT, GenerationJobKind.REQUEST, "a", finished({}))
        with pytest.raises(ValueError):
            registry.start(
                OWNER, PROJECT, GenerationJobKind.REQUEST, "a", finished({}), operation="UNKNOWN"
            )
        for job in (mockup, iteration):
            await registry.wait(job.job_id)
        return mockup, iteration, len(registry)

    mockup, iteration, count = run(scenario())
    assert mockup.operation is GenerationOperation.MOCKUP
    assert iteration.operation is GenerationOperation.ITERATION
    assert count == 2


def test_a_twin_update_is_a_request_operation_of_its_own():
    assert GenerationOperation("TWIN_UPDATE") is GenerationOperation.TWIN_UPDATE
    assert list(GenerationOperation)[-1] is GenerationOperation.TWIN_UPDATE

    async def scenario():
        registry = GenerationJobRegistry()
        job = registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.REQUEST,
            "TWIN_UPDATE:twin_id=twin:hash",
            finished(GenerationJobResponse(201, {"status": "PROPOSED"})),
            operation=GenerationOperation.TWIN_UPDATE,
        )
        await registry.wait(job.job_id)
        return job.to_payload()

    payload = run(scenario())
    assert (payload["kind"], payload["operation"], payload["status"]) == (
        "REQUEST",
        "TWIN_UPDATE",
        "SUCCEEDED",
    )
    assert payload["response"] == {"status_code": 201, "body": {"status": "PROPOSED"}}


def test_the_jobs_of_a_project_are_listed_oldest_first_and_filtered_by_status():
    clock = Clock()

    async def scenario():
        registry = GenerationJobRegistry(clock=clock, per_owner=8)
        gate = asyncio.Event()
        clock.now = START + timedelta(minutes=5)
        late = registry.start(OWNER, PROJECT, GenerationJobKind.MOCKUP, "late", gated(gate))
        clock.now = START
        early = registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.REQUEST,
            "early",
            gated(gate),
            operation=GenerationOperation.REQUIREMENTS_PROPOSAL,
        )
        tied = registry.start(OWNER, PROJECT, GenerationJobKind.ITERATION, "tied", gated(gate))
        done = registry.start(
            OWNER,
            PROJECT,
            GenerationJobKind.REQUEST,
            "done",
            finished(GenerationJobResponse(422, {"detail": "invalid_request"})),
            operation=GenerationOperation.DISCUSSION_ROUND,
        )
        registry.start(OWNER, OTHER_PROJECT, GenerationJobKind.MOCKUP, "other", gated(gate))
        registry.start(OTHER, PROJECT, GenerationJobKind.MOCKUP, "stranger", gated(gate))
        await registry.wait(done.job_id)
        listed = {
            "running": registry.project_jobs(OWNER, PROJECT, GenerationJobStatus.RUNNING),
            "all": registry.project_jobs(OWNER, PROJECT),
            "failed": registry.project_jobs(OWNER, PROJECT, "FAILED"),
            "stranger": registry.project_jobs(OTHER, OTHER_PROJECT),
        }
        clock.now = START + timedelta(hours=2)
        listed["expired"] = registry.project_jobs(OWNER, PROJECT)
        gate.set()
        await registry.close()
        return listed, (early, tied, done, late)

    listed, (early, tied, done, late) = run(scenario())
    assert listed["running"] == (early, tied, late)
    assert listed["all"] == (early, tied, done, late)
    assert listed["failed"] == (done,)
    assert listed["stranger"] == ()
    assert listed["expired"] == (early, tied, late)


def test_the_registry_is_read_from_the_application_state():
    registry = GenerationJobRegistry()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(generation_jobs=registry)))
    assert generation_jobs(request) is registry
    with pytest.raises(HTTPException) as missing:
        generation_jobs(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
    assert missing.value.status_code == 503
