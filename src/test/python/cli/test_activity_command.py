from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest

import orchestwin
from orchestwin.activity import project_activity
from orchestwin.cli import messages
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.project import ProjectFolder, json_bytes

from .support.fake_studio import FakeProject, FakeStudio, _activity_row
from .support.terminal import (
    PROJECT_ID,
    START,
    TEST_PASSWORD,
    Run,
    link_folder,
    run_ut,
    store_session,
)
from .support.transports import API, ScriptedTransport

ACTIVITY = f"{API}/projects/{PROJECT_ID}/activity"
SESSIONS = f"{ACTIVITY}/sessions"
EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
WIDE = {"COLUMNS": "240"}
LANGUAGES = ("en", "it")
STAGES = ("brief", "team", "twins", "requirements", "design", "package")
CSV_HEADER = (
    "number,at,source,section,kind,actor,code,version_number,duration_ms,outcome,purpose,role,"
    "session_code,target"
)


def said(key: str, language: str = "en", **values: object) -> str:
    return messages.text(key, language, **values)


def at(seconds: int) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def shown(seconds: int) -> str:
    return (START + timedelta(seconds=seconds)).strftime("%d/%m %H:%M")


def fact(seconds: int, section: str, kind: str, actor: str, **values: object) -> dict:
    return {"at": at(seconds), "section": section, "kind": kind, "actor": actor, **values}


def row(sequence: int, source: str, kind: str, received: int, **values: object) -> dict:
    client = values.pop("client", None)
    return {
        "sequence": sequence,
        "session_code": "SES-P01",
        "source": source,
        "kind": kind,
        "section": None,
        "target": values.pop("target", None),
        "client_at": None if client is None else at(client),
        "received_at": at(received),
        "duration_ms": values.pop("duration_ms", None),
        "status": values.pop("status", None),
    }


FACTS = [
    fact(0, "BRIEF", "PROJECT_CREATED", "OWNER"),
    fact(10, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
    fact(40, "BRIEF", "BRIEF_QUESTION_ANSWERED", "OWNER", duration_ms=30_000, outcome="TEXT"),
    fact(60, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
    fact(110, "BRIEF", "BRIEF_QUESTION_ANSWERED", "OWNER", duration_ms=50_000, outcome="UNKNOWN"),
    fact(300, "BRIEF", "GATE_SUBMITTED", "OWNER", version_number=1),
    fact(365, "BRIEF", "GATE_APPROVED", "OWNER", version_number=1),
    fact(
        600,
        "TEAM",
        "GENERATION",
        "MODEL",
        duration_ms=65_000,
        outcome="SUCCEEDED",
        purpose="TEAM_PROPOSAL",
    ),
    fact(
        720,
        "TEAM",
        "GENERATION",
        "MODEL",
        duration_ms=5_000,
        outcome="TIMEOUT",
        purpose="TEAM_PROPOSAL",
        role="RETRIED",
    ),
    fact(780, "TEAM", "TEAM_VERSION_SAVED", "MODEL", version_number=1),
]
JOURNAL = [
    row(1, "STUDIO", "SESSION_STARTED", 0),
    row(2, "UT", "COMMAND_STARTED", 6, target="init", client=5),
    row(
        3,
        "UT",
        "COMMAND_FINISHED",
        901,
        target="init",
        client=900,
        duration_ms=895_000,
        status="0",
    ),
    row(4, "STUDIO", "SESSION_ENDED", 1200),
]


def document(*extra: dict) -> dict:
    return project_activity(project_id=PROJECT_ID, facts=[*FACTS, *extra], journal=JOURNAL)


def linked(tmp_path: Path) -> ProjectFolder:
    store_session(tmp_path)
    return link_folder(tmp_path / "project")


def cells(line: str) -> list[str]:
    return re.split(r" {2,}", line.strip())


def test_every_module_of_the_command_imports_alone_and_loads_only_the_command_line() -> None:
    source = Path(orchestwin.__file__).resolve().parents[1]
    paths = [str(source), os.environ.get("PYTHONPATH", "")]
    code = (
        "import sys\n"
        "import orchestwin.cli.views.activity\n"
        "import orchestwin.cli.api.activity\n"
        "import orchestwin.cli.commands.activity\n"
        "loaded = sorted({'.'.join(name.split('.')[:2]) for name in sys.modules "
        "if name.startswith('orchestwin.') or name.split('.')[0] in ('fastapi', 'sqlalchemy')})\n"
        "print(loaded, 'orchestwin.activity' in sys.modules)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)},
        check=True,
        timeout=120,
    )

    assert result.stdout.strip() == "['orchestwin.cli'] False"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_table_shows_one_row_per_section_then_the_dialogue_the_sessions_and_the_limits(
    tmp_path: Path, language: str
) -> None:
    linked(tmp_path)
    answer = document()
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=answer)

    run = run_ut(["--lang", language, "activity"], tmp_path, transport=transport, variables=WIDE)

    lines = run.output.splitlines()
    names = [said(f"common.stage_{stage}", language) for stage in STAGES]
    empty = ["-", "-", "-", "0", "0", "-", "0"]
    assert run.status == 0, run.errors
    assert cells(lines[0]) == [
        said("sections.column_section", language),
        *(
            said(f"activity.column_{name}", language)
            for name in ("first", "approved", "elapsed", "owner", "generations", "wait", "retries")
        ),
    ]
    assert [cells(line) for line in lines[2:8]] == [
        [names[0], shown(0), shown(365), "6 min 05 s", "5", "0", "-", "0"],
        [names[1], shown(600), "-", "-", "0", "2", "1 min 10 s", "1"],
        *([name, *empty] for name in names[2:]),
    ]
    assert lines[8:] == [
        said("activity.utc", language),
        said(
            "activity.brief_dialogue", language, questions=2, answered=2, unknown=1, average="40 s"
        ),
        said(
            "activity.session",
            language,
            code="SES-P01",
            started=shown(0),
            ended=shown(1200),
            events=4,
            sources="STUDIO, UT",
            discarded=0,
        ),
        said("activity.limits", language, codes=", ".join(answer["limits"])),
    ]
    assert "CLIENT_CLOCK_NOT_VERIFIED" in lines[-1]
    assert run.errors == ""
    transport.assert_done()


def test_without_questions_the_dialogue_line_is_left_out_and_an_open_session_says_so(
    tmp_path: Path,
) -> None:
    linked(tmp_path)
    answer = project_activity(project_id=PROJECT_ID, facts=FACTS[:1], journal=JOURNAL[:2])
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=answer)

    run = run_ut(["activity"], tmp_path, transport=transport, variables=WIDE)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[8:] == [
        said("activity.utc"),
        said(
            "activity.session_open",
            code="SES-P01",
            started=shown(0),
            events=2,
            sources="STUDIO, UT",
            discarded=0,
        ),
        said("activity.limits", codes=", ".join(answer["limits"])),
    ]


def typical(key: str, day: int, elapsed: int) -> dict[str, object]:
    first = START + timedelta(days=day)
    approved = first + timedelta(seconds=elapsed)
    return {
        "key": key,
        "first_event_at": first.isoformat(),
        "last_event_at": approved.isoformat(),
        "first_approved_at": approved.isoformat(),
        "approved_at": approved.isoformat(),
        "elapsed_seconds": float(elapsed),
        "owner_actions": 16,
        "gate": {"submissions": 2, "approvals": 1, "revision_requests": 1, "rejections": 0},
        "generations": {
            "count": 6,
            "succeeded": 4,
            "failed": 2,
            "retries": 2,
            "wait_seconds": 891.0,
        },
        "journal": {
            "opened": 3,
            "dwell_seconds": 640.5,
            "details_opened": 4,
            "why_opened": 1,
            "mockups_opened": 2,
        },
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_at_100_columns_a_typical_project_keeps_every_word_and_date_whole(
    tmp_path: Path, language: str
) -> None:
    linked(tmp_path)
    keys = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
    elapsed = (98_700, 891) * 3
    answer = {
        **document(),
        "sections": [
            typical(key, day, seconds)
            for day, (key, seconds) in enumerate(zip(keys, elapsed, strict=True))
        ],
    }
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=answer)

    run = run_ut(
        ["--lang", language, "activity"],
        tmp_path,
        transport=transport,
        variables={"COLUMNS": "100"},
    )

    lines = run.output.splitlines()
    table = lines[: lines.index(said("activity.utc", language))]
    names = [said(f"common.stage_{stage}", language) for stage in STAGES]
    moments = [START + timedelta(days=day) for day in range(6)]
    assert run.status == 0, run.errors
    assert len(table) == 8
    assert max(len(line) for line in table) <= 100
    assert cells(table[0]) == [
        said("sections.column_section", language),
        *(
            said(f"activity.column_{name}", language)
            for name in ("first", "approved", "elapsed", "owner", "generations", "wait", "retries")
        ),
    ]
    assert [cells(line) for line in table[2:]] == [
        [
            name,
            moment.strftime("%d/%m %H:%M"),
            (moment + timedelta(seconds=seconds)).strftime("%d/%m %H:%M"),
            "27 h 25 min" if seconds == 98_700 else "14 min 51 s",
            "16",
            "6",
            "14 min 51 s",
            "2",
        ]
        for name, moment, seconds in zip(names, moments, elapsed, strict=True)
    ]


def test_json_prints_the_document_of_the_studio(tmp_path: Path) -> None:
    linked(tmp_path)
    answer = document()
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=answer)

    run = run_ut(["activity", "--json"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert json.loads(run.output) == answer
    assert len(transport.sent) == 1


def test_csv_writes_every_event_in_utf8_with_lf_and_neutralizes_formulas(tmp_path: Path) -> None:
    linked(tmp_path)
    tricky = fact(
        800,
        "DESIGN",
        "GENERATION",
        "MODEL",
        code="-EVD-001",
        duration_ms=1_000,
        outcome="@SUM(A1)",
        purpose="=HYPERLINK(1)",
        role="+RETRIED",
    )
    accented = fact(810, "DESIGN", "GENERATION", "MODEL", purpose="Caffè  al   banco")
    answer = document(tricky, accented)
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=answer)
    target = tmp_path / "project" / "out" / "activity.csv"

    run = run_ut(["activity", "--csv", "out/activity.csv"], tmp_path, transport=transport)

    content = target.read_bytes()
    table = list(csv.reader(io.StringIO(content.decode("utf-8"))))
    by_number = {line[0]: line for line in table[1:]}
    tricky_line = next(line for line in table[1:] if line[10] == "'=HYPERLINK(1)")
    assert run.status == 0, run.errors
    assert run.output == (
        said("activity.csv_written", count=len(answer["events"]), path=str(target)) + "\n"
    )
    assert b"\r" not in content
    assert content.decode("utf-8").splitlines()[0] == CSV_HEADER
    assert len(table) == len(answer["events"]) + 1
    assert tricky_line[6] == "'-EVD-001"
    assert tricky_line[9] == "'@SUM(A1)"
    assert tricky_line[11] == "'+RETRIED"
    assert tricky_line[8] == "1000"
    assert any(line[10] == "Caffè al banco" for line in table[1:])
    assert by_number["1"][1:6] == [at(0), "SERVER", "BRIEF", "PROJECT_CREATED", "OWNER"]
    assert [line[2] for line in table[1:]].count("UT") == 2
    assert all(line[12] == "" for line in table[1:] if line[2] == "SERVER")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (422, "ACTIVITY_RECORDS_INVALID"),
        (503, "ACTIVITY_SERVICE_UNAVAILABLE"),
        (404, "PROJECT_NOT_FOUND"),
    ],
)
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_document_that_cannot_be_read_is_explained(
    tmp_path: Path, status: int, code: str, language: str
) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect(
        "GET", ACTIVITY, status=status, body={"detail": {"code": code}}
    )

    run = run_ut(["--lang", language, "activity", "--json"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == said(f"activity.errors.{code}", language) + "\n"


def test_an_answer_that_is_not_the_document_is_a_failure_of_the_studio(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect("GET", ACTIVITY, body={"kind": "orchestwin.other"})

    run = run_ut(["activity"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == said("errors.API_FAILURE", http_status=200, code="API_FAILURE") + "\n"


def test_a_csv_that_cannot_be_written_is_an_error(tmp_path: Path) -> None:
    linked(tmp_path)
    (tmp_path / "project" / "taken").mkdir()
    transport = ScriptedTransport().expect("GET", ACTIVITY, body=document())

    run = run_ut(["activity", "--csv", "taken"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == (
        said("activity.errors.ACTIVITY_CSV_NOT_WRITTEN", path=str(tmp_path / "project" / "taken"))
        + "\n"
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["activity", "start"],
        ["activity", "stop", "SES-P01"],
        ["activity", "start", "SES-P01", "--json"],
        ["activity", "stop", "--csv", "out.csv"],
        ["activity", "--json", "--csv", "out.csv"],
    ],
)
@pytest.mark.parametrize("language", LANGUAGES)
def test_options_that_do_not_go_together_are_refused_before_any_request(
    tmp_path: Path, arguments: list[str], language: str
) -> None:
    linked(tmp_path)
    transport = ScriptedTransport()

    run = run_ut(["--lang", language, *arguments], tmp_path, transport=transport)

    assert run.status == 2
    assert run.output == ""
    assert run.errors == said("activity.errors.ACTIVITY_OPTIONS_INVALID", language) + "\n"
    assert transport.sent == []


def test_an_unknown_action_is_wrong_usage(tmp_path: Path) -> None:
    linked(tmp_path)
    transport = ScriptedTransport()

    run = run_ut(["activity", "SES-P01"], tmp_path, transport=transport)

    assert run.status == 2
    assert "usage: ut activity" in run.errors
    assert transport.sent == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_start_writes_the_local_file_of_the_session(tmp_path: Path, language: str) -> None:
    project = linked(tmp_path)
    session = {"code": "SES-P01", "started_at": at(0)}
    transport = ScriptedTransport().expect(
        "POST",
        SESSIONS,
        status=201,
        body={"status": "ACTIVITY_SESSION_STARTED", "session": session},
    )

    run = run_ut(
        ["--lang", language, "activity", "start", "SES-P01"], tmp_path, transport=transport
    )

    path = tmp_path / "project" / ".orchestwin" / "activity-session.json"
    assert run.status == 0, run.errors
    assert run.output == said("activity.started", language, code="SES-P01") + "\n"
    assert transport.sent[0].json() == {"session_code": "SES-P01"}
    assert path.read_bytes() == json_bytes(
        {"schema_version": 1, "session_code": "SES-P01", "started_at": at(0)}
    )
    assert project.activity_session() == {
        "schema_version": 1,
        "session_code": "SES-P01",
        "started_at": at(0),
    }
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "code", "key"),
    [
        (409, "ACTIVITY_SESSION_ACTIVE", "activity.errors.ACTIVITY_SESSION_ACTIVE"),
        (409, "ACTIVITY_SESSION_CODE_USED", "activity.errors.ACTIVITY_SESSION_CODE_USED"),
        (422, "ACTIVITY_INPUT_INVALID", "activity.errors.ACTIVITY_INPUT_INVALID"),
        (503, "ACTIVITY_SERVICE_UNAVAILABLE", "activity.errors.ACTIVITY_SERVICE_UNAVAILABLE"),
        (404, "PROJECT_NOT_FOUND", "activity.errors.PROJECT_NOT_FOUND"),
    ],
)
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refused_start_writes_nothing_and_says_why(
    tmp_path: Path, status: int, code: str, key: str, language: str
) -> None:
    project = linked(tmp_path)
    transport = ScriptedTransport().expect(
        "POST", SESSIONS, status=status, body={"detail": {"code": code}}
    )

    run = run_ut(
        ["--lang", language, "activity", "start", "SES-P01"], tmp_path, transport=transport
    )

    assert run.status == 1
    assert run.output == ""
    assert run.errors == said(key, language) + "\n"
    assert project.activity_session() is None
    assert not (project.local / "activity-session.json").exists()


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_ends_the_session_of_the_file_and_removes_it(tmp_path: Path, language: str) -> None:
    project = linked(tmp_path)
    project.save_activity_session("SES-P01", at(0))
    transport = ScriptedTransport().expect(
        "POST",
        f"{SESSIONS}/SES-P01/end",
        body={
            "status": "ACTIVITY_SESSION_ENDED",
            "session": {"code": "SES-P01", "started_at": at(0), "ended_at": at(60)},
        },
    )

    run = run_ut(["--lang", language, "activity", "stop"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output == said("activity.stopped", language, code="SES-P01") + "\n"
    assert project.activity_session() is None
    assert len(transport.sent) == 1
    transport.assert_done()


def test_stop_without_the_file_reads_the_active_session_from_the_studio(tmp_path: Path) -> None:
    linked(tmp_path)
    session = {"code": "SES-W07", "started_at": at(0)}
    transport = ScriptedTransport()
    transport.expect("GET", f"{ACTIVITY}/session", body={"active": True, "session": session})
    transport.expect(
        "POST",
        f"{SESSIONS}/SES-W07/end",
        body={"status": "ACTIVITY_SESSION_ENDED", "session": {**session, "ended_at": at(5)}},
    )

    run = run_ut(["activity", "stop"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output == said("activity.stopped", code="SES-W07") + "\n"
    transport.assert_done()


@pytest.mark.parametrize("language", LANGUAGES)
def test_stop_without_an_active_session_is_an_error(tmp_path: Path, language: str) -> None:
    linked(tmp_path)
    transport = ScriptedTransport().expect(
        "GET", f"{ACTIVITY}/session", body={"active": False, "session": None}
    )

    run = run_ut(["--lang", language, "activity", "stop"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.errors == said("activity.errors.ACTIVITY_SESSION_NOT_ACTIVE", language) + "\n"
    assert len(transport.sent) == 1


def test_stop_of_a_session_ended_elsewhere_removes_the_stale_file(tmp_path: Path) -> None:
    project = linked(tmp_path)
    project.save_activity_session("SES-P01", at(0))
    transport = ScriptedTransport().expect(
        "POST",
        f"{SESSIONS}/SES-P01/end",
        status=409,
        body={"detail": {"code": "ACTIVITY_SESSION_NOT_ACTIVE"}},
    )

    run = run_ut(["activity", "stop"], tmp_path, transport=transport)

    assert run.status == 1
    assert run.errors == said("activity.errors.ACTIVITY_SESSION_NOT_ACTIVE") + "\n"
    assert project.activity_session() is None


def test_stop_keeps_the_file_when_the_studio_does_not_answer(tmp_path: Path) -> None:
    project = linked(tmp_path)
    project.save_activity_session("SES-P01", at(0))
    transport = ScriptedTransport().expect("POST", f"{SESSIONS}/SES-P01/end", unreachable=True)

    run = run_ut(["activity", "stop"], tmp_path, transport=transport)

    assert run.status == 4
    assert project.activity_session() is not None


def test_the_local_file_of_the_session_is_read_strictly_and_removed_quietly(
    tmp_path: Path,
) -> None:
    project = link_folder(tmp_path / "project")
    path = project.save_activity_session("SES-P01", at(0))

    assert path == tmp_path / "project" / ".orchestwin" / "activity-session.json"
    assert project.activity_session() == json.loads(path.read_text(encoding="utf-8"))
    for content in (
        b"{",
        b"[]",
        b'{"schema_version": 2, "session_code": "SES-P01", "started_at": "x"}',
        b'{"schema_version": 1, "session_code": "", "started_at": "x"}',
        b'{"schema_version": 1, "session_code": "SES-P01"}',
    ):
        path.write_bytes(content)
        assert project.activity_session() is None
    project.forget_activity_session()
    project.forget_activity_session()
    assert not path.exists()
    assert sorted(item.name for item in project.local.iterdir()) == [".gitignore", "project.json"]


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path

    @property
    def folder(self) -> ProjectFolder:
        return ProjectFolder(self.tmp_path / "project")

    def ut(self, *arguments: str, language: str = "en") -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            variables=WIDE,
        )


@contextmanager
def session(tmp_path: Path, *, language: str = "en") -> Iterator[Session]:
    with FakeStudio(language=language, twins=2) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through="design")
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(tmp_path / "project", project_id=project.id, name=NAME, studio=studio.address)
        yield Session(studio=studio, project=project, tmp_path=tmp_path)
        assert studio.errors == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_study_session_with_the_fake_studio_records_the_commands_between_start_and_stop(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as current:
        started = current.ut("activity", "start", "SES-P01", language=language)
        saved = current.folder.activity_session()
        again = current.ut("activity", "start", "SES-P02", language=language)
        listed = current.ut("sections", "--json", language=language)
        table = current.ut("activity", language=language)
        printed = current.ut("activity", "--json", language=language)
        stopped = current.ut("activity", "stop", language=language)
        after = current.ut("sections", "--json", language=language)
        reused = current.ut("activity", "start", "SES-P01", language=language)
        journal = [dict(item) for item in current.project.activity_journal]
        left = current.folder.activity_session()

    answer = json.loads(printed.output)
    sessions = answer["sessions"]
    assert started.status == 0, started.errors
    assert started.output == said("activity.started", language, code="SES-P01") + "\n"
    assert saved is not None and saved["started_at"] == journal[0]["received_at"]
    assert again.status == 1
    assert again.errors == said("activity.errors.ACTIVITY_SESSION_ACTIVE", language) + "\n"
    assert listed.status == after.status == 0
    assert [(item["source"], item["kind"], item["target"]) for item in journal] == [
        ("STUDIO", "SESSION_STARTED", None),
        ("UT", "COMMAND_STARTED", "sections"),
        ("UT", "COMMAND_FINISHED", "sections"),
        ("STUDIO", "SESSION_ENDED", None),
    ]
    assert journal[2]["status"] == "0"
    assert all("--json" not in json.dumps(item) for item in journal)
    assert table.status == 0, table.errors
    for stage in STAGES:
        assert said(f"common.stage_{stage}", language) in table.output
    assert said("activity.limits", language, codes=", ".join(answer["limits"])) in table.output
    assert answer["kind"] == "orchestwin.project-activity"
    assert answer["project_id"] == current.project.id
    assert [item["code"] for item in sessions] == ["SES-P01"]
    assert sessions[0]["ended_at"] is None
    assert sessions[0]["sources"] == ["STUDIO", "UT"]
    assert [item["first_approved_at"] is not None for item in answer["sections"]] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert stopped.status == 0, stopped.errors
    assert stopped.output == said("activity.stopped", language, code="SES-P01") + "\n"
    assert left is None
    assert reused.status == 1
    assert reused.errors == said("activity.errors.ACTIVITY_SESSION_CODE_USED", language) + "\n"


def test_a_session_ended_in_the_web_removes_the_file_at_the_next_command(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        started = current.ut("activity", "start", "SES-P01")
        saved = current.folder.activity_session()
        with current.studio._lock:
            current.studio._activity_append(
                current.project, [_activity_row("SES-P01", "SESSION_ENDED")]
            )
        listed = current.ut("sections", "--json")
        left = current.folder.activity_session()
        kinds = [item["kind"] for item in current.project.activity_journal]

    assert started.status == 0, started.errors
    assert saved is not None
    assert listed.status == 0, listed.errors
    assert listed.errors == ""
    assert left is None
    assert kinds == ["SESSION_STARTED", "SESSION_ENDED"]
