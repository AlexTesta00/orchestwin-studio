from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import CliError
from orchestwin.cli.jobs import JobResult, generate, running_jobs

from .support.terminal import PROJECT_ID, Terminal, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

PROJECTS = f"{API}/projects/{PROJECT_ID}"
PROPOSALS = f"/projects/{PROJECT_ID}/requirements/proposals"
JOB = f"{PROJECTS}/generation-jobs/job-1"
CREATED = {"status": "CREATED", "version": {"version_number": 1}}


def job(
    status: str = "RUNNING",
    *,
    stage: str | None = "GENERATING",
    attempt: int = 1,
    response: object = None,
    failure: object = None,
    result: object = None,
    kind: str = "REQUEST",
) -> dict[str, object]:
    return {
        "job_id": "job-1",
        "kind": kind,
        "operation": "REQUIREMENTS_PROPOSAL",
        "status": status,
        "stage": stage,
        "attempt": attempt,
        "started_at": "2026-09-29T09:00:00+00:00",
        "finished_at": None,
        "alternative_id": None,
        "result": result,
        "failure": failure,
        "response": response,
    }


def prepared(
    tmp_path: Path, transport: ScriptedTransport, *, interactive: bool = False
) -> tuple[CommandContext, Terminal]:
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport, interactive=interactive)
    return command_context(bundle.environment), bundle


def run(context: CommandContext, **options: object) -> JobResult:
    return generate(
        context, context.client(), PROJECT_ID, PROPOSALS, label="Requirements", **options
    )


def test_an_answer_that_is_not_202_is_the_result(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=201, body=CREATED)
    context, bundle = prepared(tmp_path, transport)

    result = run(context)

    assert result == JobResult(201, CREATED, 0.0, None)
    assert transport.sent[0].header("prefer") == "respond-async"
    assert bundle.output == ""
    transport.assert_done()


def test_a_202_is_followed_until_the_job_ends(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect("GET", JOB, body=job(stage="VALIDATING", attempt=2))
    transport.expect(
        "GET",
        JOB,
        body=job("SUCCEEDED", stage=None, response={"status_code": 201, "body": CREATED}),
    )
    context, bundle = prepared(tmp_path, transport)

    result = run(context)

    assert result == JobResult(201, CREATED, 6.0, "job-1")
    assert bundle.clock.slept == 6.0
    assert len(transport.requests("POST")) == 1
    assert bundle.output.splitlines() == ["Requirements...", "Requirements: done in 6 s."]
    transport.assert_done()


def test_a_failure_inside_the_job_is_returned_not_raised(tmp_path: Path) -> None:
    refusal = {"detail": {"code": "TIMEOUT", "stage": "MODEL_PROPOSAL"}}
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect(
        "GET", JOB, body=job("FAILED", stage=None, response={"status_code": 503, "body": refusal})
    )
    context, bundle = prepared(tmp_path, transport)

    result = run(context)

    assert (result.status_code, result.body, result.job_id) == (503, refusal, "job-1")
    assert len(transport.requests("POST")) == 1
    assert bundle.output.splitlines() == [
        "Requirements...",
        "Requirements: not completed after 3 s.",
    ]


def test_a_refusal_before_the_job_starts_is_returned(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST",
        f"{API}{PROPOSALS}",
        status=402,
        body={"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}},
    )
    context, _ = prepared(tmp_path, transport)

    result = run(context)

    assert result.status_code == 402
    assert result.body == {"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}}
    assert result.job_id is None


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (404, {"detail": {"code": "GENERATION_JOB_NOT_FOUND"}}),
        (
            200,
            job(
                "FAILED",
                stage=None,
                failure={"code": "GENERATION_JOB_CANCELLED", "reasons": []},
            ),
        ),
    ],
)
def test_a_lost_job_is_reported_and_never_started_again(
    tmp_path: Path, status: int, body: object
) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect("GET", JOB, status=status, body=body)
    context, bundle = prepared(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        run(context)

    assert caught.value.code == "GENERATION_LOST"
    assert caught.value.values["label"] == "Requirements"
    assert len(transport.requests("POST")) == 1
    assert bundle.output.splitlines()[-1] == "Requirements: not completed after 3 s."
    transport.assert_done()


def test_the_command_stops_waiting_after_the_limit(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    for _ in range(3):
        transport.expect("GET", JOB, body=job())
    context, bundle = prepared(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        run(context, limit_seconds=7.0)

    assert caught.value.code == "GENERATION_STILL_RUNNING"
    assert caught.value.status == 1
    assert caught.value.values == {"label": "Requirements", "job_id": "job-1"}
    assert bundle.clock.slept == 9.0
    assert len(transport.requests("POST")) == 1
    assert bundle.output.splitlines()[-1] == "Requirements: not completed after 9 s."
    transport.assert_done()


def test_ctrl_c_while_waiting_leaves_the_job_running(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    store_session(tmp_path)
    bundle = terminal(tmp_path, transport=transport)

    def interrupt(seconds: float) -> None:
        raise KeyboardInterrupt

    context = command_context(replace(bundle.environment, sleep=interrupt))

    with pytest.raises(CliError) as caught:
        run(context)

    assert caught.value.code == "GENERATION_INTERRUPTED"
    assert caught.value.status == 130
    assert len(transport.sent) == 1
    assert bundle.output.splitlines() == [
        "Requirements...",
        "Requirements: interrupted after 0 s.",
    ]
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "code", "ending"),
    [
        ("SUCCEEDED", 200, "Mockup DES-001: done in 3 s."),
        ("REJECTED", 422, "Mockup DES-001: not completed after 3 s."),
        ("FAILED", 502, "Mockup DES-001: not completed after 3 s."),
    ],
)
def test_a_job_with_its_own_route_returns_its_body(
    tmp_path: Path, status: str, code: int, ending: str
) -> None:
    mockups = f"/projects/{PROJECT_ID}/design/mockups/jobs"
    final = job(status, stage=None, kind="MOCKUP", result={"status": "APPLIED"})
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{mockups}", status=202, body=job(kind="MOCKUP"))
    transport.expect("GET", f"{API}{mockups}/job-1", body=final)
    context, bundle = prepared(tmp_path, transport)

    result = generate(
        context,
        context.client(),
        PROJECT_ID,
        mockups,
        {"alternative_id": "a"},
        label="Mockup DES-001",
        job_path=lambda job_id: f"{mockups}/{job_id}",
    )

    assert result.status_code == code
    assert result.body == final
    assert transport.sent[0].json() == {"alternative_id": "a"}
    assert bundle.output.splitlines() == ["Mockup DES-001...", ending]


def test_the_progress_names_the_stage_on_a_terminal(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{API}{PROPOSALS}", status=202, body=job(stage="VALIDATING", attempt=2)
    )
    transport.expect("GET", JOB, body=job("SUCCEEDED", stage=None, response={"status_code": 201}))
    context, bundle = prepared(tmp_path, transport, interactive=True)

    run(context)

    assert "Requirements - the Studio is checking the result, attempt 2 - 0 s" in bundle.output
    assert bundle.output.endswith("Requirements: done in 3 s.\n")


def test_a_long_job_prints_a_line_every_minute_when_not_on_a_terminal(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    for _ in range(20):
        transport.expect("GET", JOB, body=job())
    transport.expect("GET", JOB, body=job("SUCCEEDED", stage=None, response={"status_code": 201}))
    context, bundle = prepared(tmp_path, transport)

    run(context)

    assert bundle.output.splitlines() == [
        "Requirements...",
        "Requirements: the model is working (1 min 00 s so far)",
        "Requirements: done in 1 min 03 s.",
    ]


def test_running_jobs_lists_what_the_studio_is_still_generating(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{PROJECTS}/generation-jobs?status=RUNNING", body={"items": [job()]})
    context, _ = prepared(tmp_path, transport)

    assert running_jobs(context.client(), PROJECT_ID) == [job()]
