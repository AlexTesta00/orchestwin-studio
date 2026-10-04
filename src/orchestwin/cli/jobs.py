from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.console import ProgressOutcome
from orchestwin.cli.errors import INTERRUPTED_STATUS, ApiFailure, CliError

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.http import Reply

POLL_SECONDS: Final = 3.0
ACCEPTED: Final = 202
FAILURE_STATUS: Final = 400
RUNNING: Final = "RUNNING"
CANCELLED: Final = "GENERATION_JOB_CANCELLED"
JOB_STATUS_CODES: Final = {"SUCCEEDED": 200, "REJECTED": 422, "FAILED": 502}
STAGE_KEYS: Final = {
    "GENERATING": "jobs.stage_generating",
    "VALIDATING": "jobs.stage_validating",
    "RETRYING": "jobs.stage_retrying",
}


@dataclass(frozen=True, slots=True)
class JobResult:
    status_code: int
    body: object
    seconds: float
    job_id: str | None


def generate(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    path: str,
    body: object | None = None,
    *,
    label: str,
    job_path: Callable[[str], str] | None = None,
    limit_seconds: float = 1800.0,
) -> JobResult:
    started = context.environment.monotonic()
    result: JobResult | None = None
    try:
        result = _generate(
            context,
            client,
            project_id,
            path,
            body,
            label=label,
            job_path=job_path,
            limit_seconds=limit_seconds,
            started=started,
        )
        return result
    finally:
        _waited(context, started, result)


def _waited(context: CommandContext, started: float, result: JobResult | None) -> None:
    with contextlib.suppress(Exception):
        environment = context.environment
        seconds = environment.monotonic() - started if result is None else result.seconds
        status = None if result is None else result.status_code
        context.generation_waits.append((environment.now(), seconds, status))


def _generate(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    path: str,
    body: object | None,
    *,
    label: str,
    job_path: Callable[[str], str] | None,
    limit_seconds: float,
    started: float,
) -> JobResult:
    environment = context.environment
    reply = client.request("POST", path, body=body, prefer_async=True)
    if reply.status != ACCEPTED:
        return JobResult(reply.status, reply_body(reply), environment.monotonic() - started, None)
    job = _job(reply.json(), reply.status)
    job_id = str(job["job_id"])
    address = (
        job_path(job_id)
        if job_path is not None
        else f"/projects/{project_id}/generation-jobs/{job_id}"
    )
    values = {"label": label, "job_id": job_id}
    try:
        with context.console.progress(label) as progress:
            while job.get("status") == RUNNING:
                if environment.monotonic() - started >= limit_seconds:
                    raise CliError("GENERATION_STILL_RUNNING", values=values)
                progress.update(stage_text(context, job))
                environment.sleep(POLL_SECONDS)
                answer = client.get(address, optional=True)
                if answer is None:
                    raise CliError("GENERATION_LOST", values=values)
                job = _job(answer, 200)
            if _cancelled(job):
                raise CliError("GENERATION_LOST", values=values)
            result = _result(job, job_id, environment.monotonic() - started)
            if result.status_code >= FAILURE_STATUS:
                progress.set_outcome(ProgressOutcome.NOT_COMPLETED)
    except KeyboardInterrupt:
        raise CliError("GENERATION_INTERRUPTED", status=INTERRUPTED_STATUS, values=values) from None
    return result


def running_jobs(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"/projects/{project_id}/generation-jobs?status={RUNNING}")
    items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def stage_text(context: CommandContext, job: Mapping[str, object]) -> str:
    detail = context.text(STAGE_KEYS.get(str(job.get("stage")), "jobs.stage_waiting"))
    attempt = job.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 1:
        return f"{detail}, {context.text('jobs.attempt', attempt=attempt)}"
    return detail


def reply_body(reply: Reply) -> object:
    if not reply.content.strip():
        return None
    try:
        return json.loads(reply.content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return reply.content.decode("utf-8", "replace")


def _job(document: object, http_status: int) -> dict[str, object]:
    if not isinstance(document, dict) or not isinstance(document.get("job_id"), str):
        raise ApiFailure("API_FAILURE", http_status=http_status)
    return document


def _cancelled(job: Mapping[str, object]) -> bool:
    failure = job.get("failure")
    return isinstance(failure, Mapping) and failure.get("code") == CANCELLED


def _result(job: Mapping[str, object], job_id: str, seconds: float) -> JobResult:
    response = job.get("response")
    if isinstance(response, Mapping):
        status_code = response.get("status_code")
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            return JobResult(status_code, response.get("body"), seconds, job_id)
    status_code = JOB_STATUS_CODES.get(str(job.get("status")), 502)
    return JobResult(status_code, dict(job), seconds, job_id)
