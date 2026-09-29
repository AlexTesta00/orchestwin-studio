from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

from fastapi import HTTPException, Request

MAX_RUNNING_JOBS_PER_OWNER: Final = 4
MAX_KEPT_JOBS: Final = 200
FINISHED_JOB_RETENTION: Final = timedelta(hours=1)
SHUTDOWN_GRACE_SECONDS: Final = 10.0
TOO_MANY_GENERATIONS: Final = "TOO_MANY_GENERATIONS"
GENERATION_JOB_NOT_FOUND: Final = "GENERATION_JOB_NOT_FOUND"
GENERATION_JOBS_UNAVAILABLE: Final = "GENERATION_JOBS_UNAVAILABLE"
GENERATION_JOB_CANCELLED: Final = "GENERATION_JOB_CANCELLED"
GENERATION_JOB_FAILED: Final = "GENERATION_JOB_FAILED"
UNEXPECTED_ERROR: Final = "UNEXPECTED_ERROR"


class GenerationJobKind(StrEnum):
    MOCKUP = "MOCKUP"
    ITERATION = "ITERATION"
    REQUEST = "REQUEST"


class GenerationOperation(StrEnum):
    MOCKUP = "MOCKUP"
    ITERATION = "ITERATION"
    PERSONA_PROPOSAL = "PERSONA_PROPOSAL"
    USER_TWIN_GENERATION = "USER_TWIN_GENERATION"
    REQUIREMENTS_PROPOSAL = "REQUIREMENTS_PROPOSAL"
    REQUIREMENTS_CHANGE = "REQUIREMENTS_CHANGE"
    DESIGN_PROPOSAL = "DESIGN_PROPOSAL"
    DESIGN_REGENERATION = "DESIGN_REGENERATION"
    DESIGN_EVALUATION = "DESIGN_EVALUATION"
    DISCUSSION_START = "DISCUSSION_START"
    DISCUSSION_ROUND = "DISCUSSION_ROUND"
    CODE_CHANGE_REVIEW = "CODE_CHANGE_REVIEW"


class GenerationJobStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class GenerationJobStage(StrEnum):
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    RETRYING = "RETRYING"


class GenerationJobFailure(Exception):
    def __init__(
        self,
        code: str,
        *,
        rejected: bool = False,
        reasons: Iterable[Mapping[str, object]] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.rejected = rejected
        self.reasons = tuple(dict(reason) for reason in reasons)

    def to_snapshot(self) -> dict[str, object]:
        return {"code": self.code, "reasons": [dict(reason) for reason in self.reasons]}


@dataclass(frozen=True, slots=True)
class GenerationJobResponse:
    status_code: int
    body: object = None

    @property
    def succeeded(self) -> bool:
        return self.status_code < 400

    def to_snapshot(self) -> dict[str, object]:
        return {"status_code": self.status_code, "body": self.body}


@dataclass(slots=True)
class GenerationJob:
    job_id: UUID
    owner_user_id: UUID
    project_id: UUID
    kind: GenerationJobKind
    operation: GenerationOperation
    key: str
    alternative_id: UUID | None
    started_at: datetime
    status: GenerationJobStatus = GenerationJobStatus.RUNNING
    stage: GenerationJobStage | None = GenerationJobStage.GENERATING
    attempt: int = 1
    finished_at: datetime | None = None
    result: dict[str, object] | None = None
    failure: dict[str, object] | None = None
    response: dict[str, object] | None = None
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.status is GenerationJobStatus.RUNNING

    def to_payload(self) -> dict[str, object]:
        return {
            "job_id": str(self.job_id),
            "kind": self.kind.value,
            "operation": self.operation.value,
            "status": self.status.value,
            "stage": None if self.stage is None else self.stage.value,
            "attempt": self.attempt,
            "started_at": self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "alternative_id": None if self.alternative_id is None else str(self.alternative_id),
            "result": self.result,
            "failure": self.failure,
            "response": self.response,
        }


class GenerationJobProgress:
    def __init__(self, job: GenerationJob | None = None) -> None:
        self._job = job

    def update(self, stage: GenerationJobStage, attempt: int | None = None) -> None:
        job = self._job
        if job is None or not job.running:
            return
        job.stage = GenerationJobStage(stage)
        if attempt is not None:
            job.attempt = attempt


JobFactory = Callable[[GenerationJobProgress], Awaitable[dict[str, object] | GenerationJobResponse]]


def _now() -> datetime:
    return datetime.now(UTC)


class GenerationJobRegistry:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _now,
        retention: timedelta = FINISHED_JOB_RETENTION,
        capacity: int = MAX_KEPT_JOBS,
        per_owner: int = MAX_RUNNING_JOBS_PER_OWNER,
    ) -> None:
        self._clock = clock
        self._retention = retention
        self._capacity = capacity
        self._per_owner = per_owner
        self._jobs: dict[UUID, GenerationJob] = {}
        self._closed = False

    def __len__(self) -> int:
        return len(self._jobs)

    def start(
        self,
        owner_user_id: UUID,
        project_id: UUID,
        kind: GenerationJobKind,
        key: str,
        coroutine_factory: JobFactory,
        *,
        alternative_id: UUID | None = None,
        operation: GenerationOperation | None = None,
    ) -> GenerationJob:
        kind = GenerationJobKind(kind)
        operation = GenerationOperation(kind.value if operation is None else operation)
        if self._closed:
            raise HTTPException(503, detail={"code": GENERATION_JOBS_UNAVAILABLE})
        self._prune(room=1)
        for job in self._jobs.values():
            if job.running and (job.owner_user_id, job.project_id, job.kind, job.key) == (
                owner_user_id,
                project_id,
                kind,
                key,
            ):
                return job
        running = sum(
            1 for job in self._jobs.values() if job.running and job.owner_user_id == owner_user_id
        )
        if running >= self._per_owner:
            raise HTTPException(429, detail={"code": TOO_MANY_GENERATIONS})
        job = GenerationJob(
            job_id=uuid4(),
            owner_user_id=owner_user_id,
            project_id=project_id,
            kind=kind,
            operation=operation,
            key=key,
            alternative_id=alternative_id,
            started_at=self._clock(),
        )
        self._jobs[job.job_id] = job
        job.task = asyncio.get_running_loop().create_task(
            self._run(job, coroutine_factory), context=contextvars.Context()
        )
        return job

    def get(
        self,
        owner_user_id: UUID,
        project_id: UUID,
        job_id: UUID,
        kind: GenerationJobKind | None = None,
    ) -> GenerationJob | None:
        self._prune()
        job = self._jobs.get(job_id)
        if (
            job is None
            or job.owner_user_id != owner_user_id
            or job.project_id != project_id
            or (kind is not None and job.kind is not GenerationJobKind(kind))
        ):
            return None
        return job

    def project_jobs(
        self,
        owner_user_id: UUID,
        project_id: UUID,
        status: GenerationJobStatus | None = None,
    ) -> tuple[GenerationJob, ...]:
        self._prune()
        wanted = None if status is None else GenerationJobStatus(status)
        return tuple(
            sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.owner_user_id == owner_user_id
                    and job.project_id == project_id
                    and (wanted is None or job.status is wanted)
                ),
                key=lambda job: job.started_at,
            )
        )

    async def wait(self, job_id: UUID) -> GenerationJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        task = job.task
        if task is not None and not task.done():
            await asyncio.wait({task})
        return job

    async def close(self) -> None:
        self._closed = True
        tasks = {
            job.task for job in self._jobs.values() if job.task is not None and not job.task.done()
        }
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=SHUTDOWN_GRACE_SECONDS)

    async def _run(self, job: GenerationJob, factory: JobFactory) -> None:
        try:
            result = await factory(GenerationJobProgress(job))
        except asyncio.CancelledError:
            self._finish(
                job, GenerationJobStatus.FAILED, failure=_failure(GENERATION_JOB_CANCELLED)
            )
            raise
        except GenerationJobFailure as failure:
            status = (
                GenerationJobStatus.REJECTED if failure.rejected else GenerationJobStatus.FAILED
            )
            self._finish(job, status, failure=failure.to_snapshot())
        except Exception as error:
            reason = {"code": UNEXPECTED_ERROR, "screen_code": None, "detail": type(error).__name__}
            self._finish(
                job, GenerationJobStatus.FAILED, failure=_failure(GENERATION_JOB_FAILED, reason)
            )
        else:
            if isinstance(result, GenerationJobResponse):
                status = (
                    GenerationJobStatus.SUCCEEDED
                    if result.succeeded
                    else GenerationJobStatus.FAILED
                )
                self._finish(job, status, response=result.to_snapshot())
            else:
                self._finish(job, GenerationJobStatus.SUCCEEDED, result=result)

    def _finish(
        self,
        job: GenerationJob,
        status: GenerationJobStatus,
        *,
        result: dict[str, object] | None = None,
        failure: dict[str, object] | None = None,
        response: dict[str, object] | None = None,
    ) -> None:
        job.status = status
        job.stage = None
        job.finished_at = self._clock()
        job.result = result
        job.failure = failure
        job.response = response

    def _prune(self, room: int = 0) -> None:
        now = self._clock()
        for job_id, job in list(self._jobs.items()):
            if (
                not job.running
                and job.finished_at is not None
                and now - job.finished_at > self._retention
            ):
                del self._jobs[job_id]
        excess = len(self._jobs) - self._capacity + room
        if excess > 0:
            finished = sorted(
                (job for job in self._jobs.values() if not job.running),
                key=lambda job: (job.finished_at or job.started_at, str(job.job_id)),
            )
            for job in finished[:excess]:
                del self._jobs[job.job_id]


def _failure(code: str, *reasons: Mapping[str, Any]) -> dict[str, object]:
    return {"code": code, "reasons": [dict(reason) for reason in reasons]}


def generation_jobs(request: Request) -> GenerationJobRegistry:
    registry = getattr(request.app.state, "generation_jobs", None)
    if not isinstance(registry, GenerationJobRegistry):
        raise HTTPException(503, detail={"code": GENERATION_JOBS_UNAVAILABLE})
    return registry


__all__ = [
    "FINISHED_JOB_RETENTION",
    "GENERATION_JOBS_UNAVAILABLE",
    "GENERATION_JOB_CANCELLED",
    "GENERATION_JOB_FAILED",
    "GENERATION_JOB_NOT_FOUND",
    "MAX_KEPT_JOBS",
    "MAX_RUNNING_JOBS_PER_OWNER",
    "TOO_MANY_GENERATIONS",
    "GenerationJob",
    "GenerationJobFailure",
    "GenerationJobKind",
    "GenerationJobProgress",
    "GenerationJobRegistry",
    "GenerationJobResponse",
    "GenerationJobStage",
    "GenerationJobStatus",
    "GenerationOperation",
    "generation_jobs",
]
