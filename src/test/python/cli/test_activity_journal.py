from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.activity import MAX_BATCH_EVENTS, MAX_DURATION_MS, journal_rows
from orchestwin.cli import jobs
from orchestwin.cli.api import activity as activity_api
from orchestwin.cli.commands import activity as activity_command
from orchestwin.cli.commands import status as status_command
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import CliError
from orchestwin.cli.project import ProjectFolder

from .support.terminal import (
    PROJECT_ID,
    START,
    Run,
    command_context,
    link_folder,
    run_ut,
    store_session,
    terminal,
)
from .support.transports import API, ScriptedTransport, authentication, refresh_cookie
from .test_jobs import CREATED, JOB, PROPOSALS, job

EVENTS = f"{API}/projects/{PROJECT_ID}/activity/events"
REFUSAL = {"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}}


def moment(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def linked(tmp_path: Path, *, recording: bool = True) -> ProjectFolder:
    store_session(tmp_path)
    project = link_folder(tmp_path / "project")
    if recording:
        project.save_activity_session("SES-P01", moment(-60))
    return project


def generating(context: CommandContext, arguments: argparse.Namespace) -> int:
    client = context.client()
    jobs.generate(context, client, PROJECT_ID, PROPOSALS, label="Requirements")
    jobs.generate(context, client, PROJECT_ID, PROPOSALS, label="Requirements")
    context.console.write("generated")
    return 3


def expect_generations(transport: ScriptedTransport) -> ScriptedTransport:
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect("GET", JOB, body=job())
    transport.expect(
        "GET",
        JOB,
        body=job("SUCCEEDED", stage=None, response={"status_code": 201, "body": CREATED}),
    )
    transport.expect("POST", f"{API}{PROPOSALS}", status=402, body=REFUSAL)
    return transport


def run_status(tmp_path: Path, transport: ScriptedTransport) -> Run:
    return run_ut(["status"], tmp_path, transport=transport)


def test_one_batch_carries_the_start_the_waits_and_the_end_of_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", generating)
    project = linked(tmp_path)
    transport = expect_generations(ScriptedTransport())
    transport.expect(
        "POST", EVENTS, status=202, body={"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 4}
    )

    run = run_status(tmp_path, transport)

    sent = transport.requests("POST", EVENTS)
    body = sent[0].json()
    assert run.status == 3
    assert len(sent) == 1
    assert sent[0].timeout == activity_api.JOURNAL_TIMEOUT
    assert body == {
        "session_code": "SES-P01",
        "source": "UT",
        "events": [
            {"kind": "COMMAND_STARTED", "target": "status", "client_at": moment(0)},
            {
                "kind": "GENERATION_WAITED",
                "target": "status",
                "client_at": moment(6),
                "duration_ms": 6000,
                "status": "201",
            },
            {
                "kind": "GENERATION_WAITED",
                "target": "status",
                "client_at": moment(6),
                "duration_ms": 0,
                "status": "402",
            },
            {
                "kind": "COMMAND_FINISHED",
                "target": "status",
                "client_at": moment(6),
                "duration_ms": 6000,
                "status": "3",
            },
        ],
    }
    assert len(journal_rows(source="UT", events=body["events"], session_code="SES-P01")) == 4
    assert project.activity_session() is not None
    transport.assert_done()


def test_the_journal_changes_neither_the_status_nor_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", generating)
    plain_path, recorded_path = tmp_path / "plain", tmp_path / "recorded"
    linked(plain_path, recording=False)
    linked(recorded_path)
    plain = expect_generations(ScriptedTransport())
    recorded = expect_generations(ScriptedTransport())
    recorded.expect("POST", EVENTS, status=202, body={"recorded": 4})

    without = run_status(plain_path, plain)
    with_journal = run_status(recorded_path, recorded)

    assert (with_journal.status, with_journal.output, with_journal.errors) == (
        without.status,
        without.output,
        without.errors,
    )
    assert without.output.splitlines()[-1] == "generated"
    assert plain.requests("POST", EVENTS) == []
    plain.assert_done()
    recorded.assert_done()


def test_without_the_file_of_the_session_no_request_is_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", lambda context, arguments: 0)
    linked(tmp_path, recording=False)
    transport = ScriptedTransport()

    run = run_status(tmp_path, transport)

    assert run.status == 0
    assert transport.sent == []


@pytest.mark.parametrize("content", [b"{broken", b'{"schema_version": 1}', b"[]"])
def test_an_unreadable_file_of_the_session_adds_no_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    monkeypatch.setattr(status_command, "run", lambda context, arguments: 0)
    project = linked(tmp_path)
    (project.local / "activity-session.json").write_bytes(content)
    transport = ScriptedTransport()

    run = run_status(tmp_path, transport)

    assert run.status == 0
    assert transport.sent == []


def test_outside_a_linked_folder_no_request_is_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", lambda context, arguments: 0)
    store_session(tmp_path)
    transport = ScriptedTransport()

    run = run_status(tmp_path, transport)

    assert run.status == 0
    assert transport.sent == []


def test_login_is_never_recorded(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    transport.expect("GET", f"{API}/auth/mode", status=404, body={"detail": "Not Found"})
    transport.expect(
        "POST",
        f"{API}/auth/login",
        body=authentication(
            access_token="new-access-not-real", expires_at=START + timedelta(hours=1)
        ),
        headers={"Set-Cookie": refresh_cookie("new-refresh-not-real")},
    )

    run = run_ut(
        ["login", "--email", "person@example.test", "--password-stdin"],
        tmp_path,
        transport=transport,
        answers=["Test-password-not-real!"],
    )

    assert run.status == 0, run.errors
    assert [request.path for request in transport.sent] == [
        f"{API}/health",
        f"{API}/auth/mode",
        f"{API}/auth/login",
    ]


def test_logout_is_never_recorded(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("POST", f"{API}/auth/logout", status=204)

    run = run_ut(["logout"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert [request.path for request in transport.sent] == [f"{API}/auth/logout"]


def test_the_activity_command_is_never_recorded(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{PROJECT_ID}/activity",
        body={"kind": "orchestwin.project-activity", "events": []},
    )

    run = run_ut(["activity", "--json"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert len(transport.sent) == 1


@pytest.mark.parametrize(
    "answer",
    [
        {"unreachable": True},
        {"status": 500, "body": b"Internal Server Error"},
        {"status": 422, "body": {"detail": {"code": "ACTIVITY_INPUT_INVALID"}}},
        {"status": 409, "body": {"detail": {"code": "ACTIVITY_JOURNAL_FULL"}}},
        {"status": 404, "body": {"detail": {"code": "PROJECT_NOT_FOUND"}}},
    ],
)
def test_a_failed_sending_is_ignored_and_keeps_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: dict[str, object]
) -> None:
    monkeypatch.setattr(status_command, "run", generating)
    project = linked(tmp_path)
    plain_path = tmp_path / "plain"
    linked(plain_path, recording=False)
    transport = expect_generations(ScriptedTransport()).expect("POST", EVENTS, **answer)

    run = run_status(tmp_path, transport)
    without = run_status(plain_path, expect_generations(ScriptedTransport()))

    assert (run.status, run.output, run.errors) == (without.status, without.output, without.errors)
    assert len(transport.requests("POST", EVENTS)) == 1
    assert project.activity_session() is not None
    transport.assert_done()


def test_a_session_that_is_no_longer_active_removes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", lambda context, arguments: 0)
    project = linked(tmp_path)
    transport = ScriptedTransport().expect(
        "POST", EVENTS, status=409, body={"detail": {"code": "ACTIVITY_SESSION_NOT_ACTIVE"}}
    )

    run = run_status(tmp_path, transport)
    later = ScriptedTransport()
    again = run_status(tmp_path, later)

    assert run.status == again.status == 0
    assert run.output == run.errors == ""
    assert project.activity_session() is None
    assert not (project.local / "activity-session.json").exists()
    assert later.sent == []
    transport.assert_done()


def test_an_error_inside_the_journal_never_reaches_the_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*arguments: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(status_command, "run", lambda context, arguments: 4)
    monkeypatch.setattr(activity_command, "journal", broken)
    linked(tmp_path)
    transport = ScriptedTransport()

    run = run_status(tmp_path, transport)

    assert (run.status, run.output, run.errors) == (4, "", "")
    assert transport.sent == []


def test_a_failed_generation_is_recorded_as_a_wait_without_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lost(context: CommandContext, arguments: argparse.Namespace) -> int:
        jobs.generate(context, context.client(), PROJECT_ID, PROPOSALS, label="Requirements")
        return 0

    monkeypatch.setattr(status_command, "run", lost)
    linked(tmp_path)
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect("GET", JOB, status=404, body={"detail": {"code": "GENERATION_JOB_NOT_FOUND"}})
    transport.expect("POST", EVENTS, status=202, body={"recorded": 3})

    run = run_status(tmp_path, transport)

    events = transport.requests("POST", EVENTS)[0].json()["events"]
    assert run.status == 1
    assert [item["kind"] for item in events] == [
        "COMMAND_STARTED",
        "GENERATION_WAITED",
        "COMMAND_FINISHED",
    ]
    assert events[1] == {
        "kind": "GENERATION_WAITED",
        "target": "status",
        "client_at": moment(3),
        "duration_ms": 3000,
        "status": None,
    }
    assert events[2]["status"] == "1"
    assert len(journal_rows(source="UT", events=events, session_code="SES-P01")) == 3
    transport.assert_done()


def test_generate_collects_its_waits_in_the_context(tmp_path: Path) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect(
        "GET",
        JOB,
        body=job("SUCCEEDED", stage=None, response={"status_code": 201, "body": CREATED}),
    )
    transport.expect("POST", f"{API}{PROPOSALS}", status=202, body=job())
    transport.expect("GET", JOB, status=404, body={"detail": {"code": "GENERATION_JOB_NOT_FOUND"}})
    bundle = terminal(tmp_path, transport=transport)
    context = command_context(bundle.environment)

    result = jobs.generate(context, context.client(), PROJECT_ID, PROPOSALS, label="Requirements")
    with pytest.raises(CliError) as caught:
        jobs.generate(context, context.client(), PROJECT_ID, PROPOSALS, label="Requirements")

    assert result == jobs.JobResult(201, CREATED, 3.0, "job-1")
    assert caught.value.code == "GENERATION_LOST"
    assert context.generation_waits == [
        (START + timedelta(seconds=3), 3.0, 201),
        (START + timedelta(seconds=6), 3.0, None),
    ]
    transport.assert_done()


def test_a_context_without_the_list_still_generates(tmp_path: Path) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport().expect("POST", f"{API}{PROPOSALS}", status=201, body=CREATED)
    bundle = terminal(tmp_path, transport=transport)
    context = command_context(bundle.environment)
    del context.generation_waits

    result = jobs.generate(context, context.client(), PROJECT_ID, PROPOSALS, label="Requirements")

    assert result == jobs.JobResult(201, CREATED, 0.0, None)


def test_a_long_command_fits_one_batch_and_the_largest_duration() -> None:
    waits = [(START + timedelta(seconds=index), 2.5, 201) for index in range(60)]

    body = activity_command.journal(
        "SES-P01", "watch", START, START + timedelta(days=2), 172_800.0, 0, waits
    )

    events = body["events"]
    assert activity_command.MAX_BATCH_EVENTS == MAX_BATCH_EVENTS
    assert activity_command.MAX_DURATION_MS == MAX_DURATION_MS
    assert len(events) == MAX_BATCH_EVENTS
    assert events[-1]["duration_ms"] == MAX_DURATION_MS
    assert [item["duration_ms"] for item in events[1:-1]] == [2500] * (MAX_BATCH_EVENTS - 2)
    assert len(journal_rows(source="UT", events=events, session_code="SES-P01")) == 50
