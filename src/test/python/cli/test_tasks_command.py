from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.http import UrlTransport

from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.terminal import PROJECT_ID, TEST_PASSWORD, Run, link_folder, run_ut, store_session
from .support.transports import API, NoNetwork, ScriptedTransport

EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
WIDE = {"COLUMNS": "400"}
CELLS = re.compile(r"\s{2,}")
UNKNOWN_RUN = "00000000-0000-4000-8000-00000000ffff"
REQUIREMENT_FINDING = "On the page I still cannot find what requirement REQ-003 asks for."
PHONE_FINDING = "Criterion AC-001 should be tried on a phone too."
PHONE_TASK = "Repeat the path of criterion AC-001 on a small screen."


def progress(language: str = "en") -> list[str]:
    lines: list[str] = []
    for key in ("common.folder_publishing", "common.folder_downloading"):
        label = messages.text(key, language)
        lines.append(messages.text("common.progress_started", language, label=label))
        lines.append(messages.text("common.progress_done", language, label=label, elapsed="0 s"))
    return lines


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path
    language: str

    @property
    def root(self) -> Path:
        return self.tmp_path / "project"

    def ut(self, *arguments: str, answers: Sequence[str] = ()) -> Run:
        return run_ut(
            ["--lang", self.language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
            variables=WIDE,
        )

    def said(self, key: str, **values: object) -> str:
        return messages.text(key, self.language, **values)

    def requests(self, method: str, suffix: str) -> list[RecordedRequest]:
        return [
            item
            for item in self.studio.requests
            if item.method == method and item.path.endswith(suffix)
        ]

    def folder_tasks(self) -> list[dict[str, object]]:
        path = self.root / "orchestwin" / "state" / "state.json"
        return json.loads(path.read_text(encoding="utf-8"))["tasks"]

    def folder_version(self) -> int:
        path = self.root / "orchestwin" / "orchestwin.json"
        return json.loads(path.read_text(encoding="utf-8"))["package"]["version_number"]

    def heading(self, key: str) -> list[str]:
        text = self.said(key, name=NAME)
        return [text, "=" * len(text)]


@contextmanager
def session(tmp_path: Path, *, language: str = "en", publish: bool = True) -> Iterator[Session]:
    with FakeStudio(language=language, hosted=True, twins=2) as studio:
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
        current = Session(studio, project, tmp_path, language)
        if publish:
            published = current.ut("package", "publish")
            assert published.status == 0, published.errors
        yield current
        assert studio.errors == []


def rows(run: Run) -> list[list[str]]:
    lines = run.output.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("-------"))
    found: list[list[str]] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        found.append(CELLS.split(line.strip()))
    return found


@pytest.mark.parametrize("language", ["en", "it"])
def test_without_tasks_one_sentence_says_where_they_come_from(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path, language=language) as work:
        opened = work.ut("tasks")
        every = work.ut("tasks", "--all")

    assert (opened.status, every.status) == (0, 0)
    assert opened.output.splitlines() == [
        *work.heading("tasks.heading_open"),
        work.said("tasks.none"),
    ]
    assert every.output.splitlines() == [
        *work.heading("tasks.heading_all"),
        work.said("tasks.none_all"),
    ]
    assert "`ut test`" in work.said("tasks.none") and "`ut tasks add`" in work.said("tasks.none")


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_list_says_where_every_task_comes_from(tmp_path: Path, language: str) -> None:
    with session(tmp_path, language=language) as work:
        seeded = work.project.seed_tasks()
        work.project.set_task_status("TSK-004", "DONE", "written")
        opened = work.ut("tasks")
        every = work.ut("tasks", "--all")

    short = str(seeded[0]["origin"]["commit"])[:7]
    owner = str(seeded[1]["origin"]["twin_name"])
    assert opened.status == 0, opened.errors
    assert opened.output.splitlines()[:2] == work.heading("tasks.heading_open")
    assert rows(opened) == [
        [
            "TSK-001",
            work.said("tasks.status_open"),
            str(seeded[0]["text"]),
            work.said("tasks.origin_verdict", commit=short),
        ],
        [
            "TSK-002",
            work.said("tasks.status_open"),
            str(seeded[1]["text"]),
            work.said("tasks.origin_commit", twin=owner, commit=short),
        ],
        [
            "TSK-003",
            work.said("tasks.status_open"),
            str(seeded[2]["text"]),
            work.said("tasks.origin_test", twin=owner),
        ],
    ]
    assert opened.output.splitlines()[-2:] == ["", work.said("tasks.hint")]
    assert rows(every)[-1] == [
        "TSK-004",
        work.said("tasks.status_done"),
        str(seeded[3]["text"]),
        work.said("tasks.origin_owner"),
    ]


@pytest.mark.parametrize(
    ("language", "sentence", "model"),
    [
        ("en", "from the decision on commit {commit}", "verdict"),
        ("it", "dalla decisione sul commit {commit}", "verdetto"),
    ],
)
def test_a_task_recorded_with_a_decision_is_not_called_the_verdict_of_the_model(
    tmp_path: Path, language: str, sentence: str, model: str
) -> None:
    with session(tmp_path, language=language) as work:
        seeded = work.project.seed_tasks()
        run = work.ut("tasks")

    origin = seeded[0]["origin"]
    assert run.status == 0, run.errors
    assert (origin["kind"], origin["twin_id"], origin["finding"]) == ("CODE_CHANGE", None, None)
    assert rows(run)[0] == [
        "TSK-001",
        work.said("tasks.status_open"),
        str(seeded[0]["text"]),
        sentence.format(commit=str(origin["commit"])[:7]),
    ]
    assert model not in run.output.lower()


def test_json_prints_the_tasks_as_the_studio_answers_and_nothing_else(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.project.seed_tasks()
        work.project.set_task_status("TSK-002", "DROPPED", "not needed")
        opened = work.ut("tasks", "--json")
        every = work.ut("tasks", "--all", "--json")
        stored = work.project.tasks()

    assert (opened.status, every.status) == (0, 0)
    assert (opened.errors, every.errors) == ("", "")
    assert json.loads(opened.output) == {
        "tasks": [task for task in stored if task["status"] == "OPEN"]
    }
    assert json.loads(every.output) == {"tasks": stored}
    assert opened.output.startswith('{\n  "tasks": [')


def unreachable(tmp_path: Path, project_id: str, *arguments: str) -> Run:
    path = f"{API}/projects/{project_id}/code-tasks?status="
    wanted = f"{path}all" if "--all" in arguments else f"{path}open"
    transport = ScriptedTransport()
    for _ in range(3):
        transport.expect("GET", wanted, unreachable=True)
    run = run_ut(["tasks", *arguments], tmp_path, transport=transport, variables=WIDE)
    transport.assert_done()
    return run


def test_offline_the_tasks_are_read_from_the_folder(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.project.seed_tasks()
        work.project.set_task_status("TSK-004", "DONE")
        assert work.ut("package", "publish").status == 0
        address = work.studio.address
        stored = work.project.tasks()
    opened = unreachable(tmp_path, work.project.id)
    every = unreachable(tmp_path, work.project.id, "--all")
    as_json = unreachable(tmp_path, work.project.id, "--json")
    (tmp_path / "config" / "sessions.json").unlink()
    signed_out = run_ut(["tasks"], tmp_path, transport=NoNetwork(), variables=WIDE)

    sentence = work.said("tasks.offline_unreachable", path="orchestwin/", studio=address)
    assert opened.status == 0, opened.errors
    assert opened.output.splitlines()[2] == sentence
    assert [row[0] for row in rows(opened)] == ["TSK-001", "TSK-002", "TSK-003"]
    assert [row[0] for row in rows(every)] == ["TSK-001", "TSK-002", "TSK-003", "TSK-004"]
    assert json.loads(as_json.output) == {"tasks": stored[:3]}
    assert as_json.errors == sentence + "\n"
    assert signed_out.status == 0
    assert signed_out.output.splitlines()[2] == work.said(
        "tasks.offline_not_signed_in", path="orchestwin/", studio=address
    )


def test_offline_without_the_tasks_of_the_folder_the_error_stays(tmp_path: Path) -> None:
    with session(tmp_path, publish=False) as work:
        address = work.studio.address
    refused = unreachable(tmp_path, work.project.id)
    (tmp_path / "config" / "sessions.json").unlink()
    signed_out = run_ut(["tasks"], tmp_path, transport=NoNetwork())

    assert refused.status == 4
    assert (
        refused.errors == messages.text("errors.STUDIO_UNREACHABLE", "en", address=address) + "\n"
    )
    assert signed_out.status == 3
    assert signed_out.errors == messages.text("errors.NOT_SIGNED_IN", "en", studio=address) + "\n"


def test_a_studio_without_the_route_of_the_tasks_leaves_them_to_the_folder(
    tmp_path: Path,
) -> None:
    store_session(tmp_path)
    project = link_folder(tmp_path / "project")
    state = project.knowledge / "state"
    state.mkdir(parents=True)
    task = {
        "code": "TSK-001",
        "text": "Show the message.",
        "about": {"requirements": [], "screens": []},
        "from_commit": "4f2a9c1e7b3d5a8f0c6e2b9d1a7f3c5e8b0d2a46",
        "created_at": "2026-09-28T11:40:00+00:00",
        "status": "OPEN",
    }
    (state / "state.json").write_text(json.dumps({"tasks": [task]}), encoding="utf-8")
    transport = ScriptedTransport().expect(
        "GET",
        f"{API}/projects/{PROJECT_ID}/code-tasks?status=open",
        status=404,
        body={"detail": "Not Found"},
    )

    run = run_ut(["tasks"], tmp_path, transport=transport, variables=WIDE)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[2] == messages.text(
        "tasks.offline_missing", "en", path="orchestwin/", studio="http://127.0.0.1:8000"
    )
    assert rows(run) == [
        ["TSK-001", "open", "Show the message.", "from the decision on commit 4f2a9c1"]
    ]
    transport.assert_done()


@pytest.mark.parametrize("language", ["en", "it"])
def test_add_writes_a_task_and_the_folder_holds_it(tmp_path: Path, language: str) -> None:
    with session(tmp_path, language=language) as work:
        run = work.ut("tasks", "add", "Write", " the help", "text of the page.")
        stored = work.project.tasks()
        folder = work.folder_tasks()
        version = work.folder_version()

    assert run.status == 0, run.errors
    assert run.output.splitlines() == [
        work.said("tasks.added", task="TSK-001", text="Write the help text of the page."),
        *progress(language),
        work.said("tasks.folder_updated", path="orchestwin/", version=version),
    ]
    assert [(task["code"], task["text"], task["origin"]["kind"]) for task in stored] == [
        ("TSK-001", "Write the help text of the page.", "OWNER")
    ]
    assert folder == stored
    assert version == 2


def test_add_refuses_an_empty_or_too_long_text_before_any_request(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        empty = work.ut("tasks", "add", "  ")
        long = work.ut("tasks", "add", "x" * 301)
        posts = work.requests("POST", "/code-tasks")

    assert (empty.status, long.status) == (2, 2)
    assert empty.errors == work.said("tasks.errors.TASKS_TEXT_EMPTY") + "\n"
    assert long.errors == work.said("tasks.errors.TASKS_TEXT_TOO_LONG", limit=300) + "\n"
    assert posts == []


def test_done_drop_and_reopen_change_the_status_and_publish_the_folder(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        seeded = work.project.seed_tasks()
        done = work.ut(
            "tasks", "done", "tsk-001", "TSK-002,TSK-001", "--note", " fixed  in 3f2a1c9 "
        )
        dropped = work.ut("tasks", "drop", "TSK-003")
        reopened = work.ut("tasks", "reopen", "TSK-001")
        stored = {task["code"]: task for task in work.project.tasks()}
        folder = {task["code"]: task for task in work.folder_tasks()}
        bodies = [json.loads(item.body) for item in work.requests("POST", "/status")]

    assert (done.status, dropped.status, reopened.status) == (0, 0, 0)
    assert done.output.splitlines()[:3] == [
        work.said("tasks.changed_done", count=2),
        f"- TSK-001: {seeded[0]['text']}",
        f"- TSK-002: {seeded[1]['text']}",
    ]
    assert done.output.splitlines()[-1] == work.said(
        "tasks.folder_updated", path="orchestwin/", version=2
    )
    assert dropped.output.splitlines()[0] == work.said("tasks.changed_dropped", count=1)
    assert reopened.output.splitlines()[0] == work.said("tasks.changed_reopened", count=1)
    assert bodies == [
        {"status": "DONE", "note": "fixed in 3f2a1c9"},
        {"status": "DONE", "note": "fixed in 3f2a1c9"},
        {"status": "DROPPED", "note": None},
        {"status": "OPEN", "note": None},
    ]
    assert [(code, task["status"], task["note"]) for code, task in stored.items()] == [
        ("TSK-001", "OPEN", None),
        ("TSK-002", "DONE", "fixed in 3f2a1c9"),
        ("TSK-003", "DROPPED", None),
        ("TSK-004", "OPEN", None),
    ]
    assert stored["TSK-001"]["closed_at"] is None
    assert stored["TSK-003"]["closed_at"] is not None
    assert folder == stored


def test_several_codes_name_the_one_that_fails_and_end_with_1(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.project.seed_tasks()
        run = work.ut("tasks", "done", "TSK-001", "TSK-009", "TSK-002")
        statuses = [task["status"] for task in work.project.tasks()]
        version = work.folder_version()

    assert run.status == 1
    assert run.errors == work.said("tasks.not_found", task="TSK-009") + "\n"
    assert run.output.splitlines()[0] == work.said("tasks.changed_done", count=2)
    assert statuses == ["DONE", "DONE", "OPEN", "OPEN"]
    assert version == 2


@pytest.mark.parametrize(
    ("arguments", "value"),
    [
        (["done", "TSK-1"], "TSK-1"),
        (["drop", "TSK-001", "abc"], "abc"),
        (["reopen", "TSK-0000001"], "TSK-0000001"),
        (["done", ","], "-"),
    ],
)
def test_a_text_that_is_not_a_code_is_refused_before_any_request(
    tmp_path: Path, arguments: list[str], value: str
) -> None:
    with session(tmp_path) as work:
        work.project.seed_tasks()
        run = work.ut("tasks", *arguments)
        posts = work.requests("POST", "/status")

    assert run.status == 2
    assert run.errors == work.said("tasks.errors.TASKS_CODE_INVALID", value=value) + "\n"
    assert posts == []


def test_a_note_that_is_too_long_is_refused_before_any_request(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        run = work.ut("tasks", "drop", "TSK-001", "--note", "n" * 301)
        posts = work.requests("POST", "/status")

    assert run.status == 2
    assert run.errors == work.said("tasks.errors.TASKS_NOTE_TOO_LONG", limit=300) + "\n"
    assert posts == []


def test_from_test_turns_the_chosen_findings_into_tasks_and_offers_the_rest_again(
    tmp_path: Path,
) -> None:
    with session(tmp_path) as work:
        seeded = work.project.seed_test_run()
        first = work.ut("tasks", "from-test", answers=["2"])
        again = work.ut("tasks", "from-test", answers=[""])
        stored = work.project.tasks()
        folder = work.folder_tasks()
        posts = [json.loads(item.body) for item in work.requests("POST", "/code-tasks")]

    waiter = seeded["critiques"][1]
    date = messages.text("tasks.test_heading", "en", date="2026-09-29 08:00 UTC")
    assert first.status == 0, first.errors
    lines = first.output.splitlines()
    assert lines[:2] == [date, "=" * len(date)]
    assert lines[2].startswith("  1. Pizzeria owner, medium importance: Criterion AC-001")
    assert f"     {work.said('tasks.choice_task', text=PHONE_TASK)}" in lines
    assert lines[lines.index(work.said("tasks.choose_question") + " ") + 1 :] == [
        work.said("tasks.created", count=1),
        f"- TSK-001: {PHONE_TASK}",
        work.said("tasks.created_next"),
        *progress(),
        work.said("tasks.folder_updated", path="orchestwin/", version=2),
    ]
    assert posts == [
        {
            "tasks": [
                {
                    "text": None,
                    "source": {
                        "kind": "TEST_RUN",
                        "test_run_id": seeded["id"],
                        "twin_id": waiter["twin_id"],
                        "finding": 0,
                    },
                }
            ]
        }
    ]
    assert stored[0]["origin"]["finding"] == PHONE_FINDING
    assert stored[0]["about"]["criteria"] == ["AC-001"]
    assert folder == stored
    assert again.status == 0, again.errors
    assert "(already the open task TSK-001)" in again.output
    assert again.output.count("  1. ") == 1 and "  2. " not in again.output
    assert again.output.splitlines()[-1] == work.said("tasks.created_none")


def test_from_test_without_a_reviewed_run_says_so(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        nothing = work.ut("tasks", "from-test")
        work.project.seed_test_run(reviewed=False)
        unreviewed = work.ut("tasks", "from-test")
        posts = work.requests("POST", "/code-tasks")

    assert (nothing.status, unreviewed.status) == (0, 0)
    assert nothing.output == work.said("tasks.test_none_reviewed") + "\n"
    assert unreviewed.output == work.said("tasks.test_none_reviewed") + "\n"
    assert posts == []


def test_from_test_with_a_named_run(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        older = work.project.seed_test_run()
        newer = work.project.seed_test_run(reviewed=False)
        named = work.ut("tasks", "from-test", "--run", str(older["id"]).upper(), answers=["1"])
        unreviewed = work.ut("tasks", "from-test", "--run", str(newer["id"]))
        unknown = work.ut("tasks", "from-test", "--run", UNKNOWN_RUN)
        invalid = work.ut("tasks", "from-test", "--run", "last")
        stored = work.project.tasks()

    assert named.status == 0, named.errors
    assert [task["origin"]["test_run_id"] for task in stored] == [older["id"]]
    assert unreviewed.status == 0
    assert unreviewed.output == work.said("tasks.test_not_reviewed", run=newer["id"]) + "\n"
    assert unknown.status == 1
    assert unknown.errors == work.said("tasks.errors.TEST_RUN_NOT_FOUND", run=UNKNOWN_RUN) + "\n"
    assert invalid.status == 2
    assert invalid.errors == work.said("tasks.errors.TASKS_RUN_INVALID", value="last") + "\n"


def test_from_commit_takes_the_newest_reviewed_waiting_commit(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        reviewed = work.project.seed_change()
        work.project.seed_change("Round the tip", reviewed=False)
        run = work.ut("tasks", "from-commit", answers=["a"])
        stored = work.project.tasks()

    short = str(reviewed["commit"])[:7]
    heading = work.said("tasks.commit_heading", commit=short, line="Add the split of the bill")
    assert run.status == 0, run.errors
    assert run.output.splitlines()[:2] == [heading, "=" * len(heading)]
    assert work.said("tasks.created", count=3) in run.output.splitlines()
    assert [(task["origin"]["kind"], task["origin"]["commit"]) for task in stored] == [
        ("CODE_CHANGE", reviewed["commit"])
    ] * 3
    assert stored[0]["origin"]["finding"] == REQUIREMENT_FINDING
    assert stored[0]["text"] == "Show on the page what requirement REQ-003 asks for."


def test_from_commit_names_a_commit_and_says_what_it_cannot_use(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        nothing = work.ut("tasks", "from-commit")
        reviewed = work.project.seed_change()
        waiting = work.project.seed_change("Round the tip", reviewed=False)
        named = work.ut("tasks", "from-commit", str(reviewed["commit"])[:9].upper(), answers=[""])
        unreviewed = work.ut("tasks", "from-commit", str(waiting["commit"]))
        unknown = work.ut("tasks", "from-commit", "abcdef0")
        invalid = work.ut("tasks", "from-commit", "HEAD")
        posts = work.requests("POST", "/code-tasks")

    assert nothing.status == 0
    assert nothing.output == work.said("tasks.commit_none_reviewed") + "\n"
    assert named.status == 0, named.errors
    assert named.output.splitlines()[-1] == work.said("tasks.created_none")
    assert unreviewed.status == 0
    assert unreviewed.output == (
        work.said("tasks.commit_not_reviewed", commit=str(waiting["commit"])[:7]) + "\n"
    )
    assert unknown.status == 1
    assert unknown.errors == (
        work.said("tasks.errors.CODE_CHANGE_NOT_FOUND", commit="abcdef0") + "\n"
    )
    assert invalid.status == 2
    assert invalid.errors == work.said("tasks.errors.TASKS_COMMIT_INVALID", value="HEAD") + "\n"
    assert posts == []


def test_a_closed_input_at_the_question_creates_nothing(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.project.seed_change()
        run = work.ut("tasks", "from-commit")
        posts = work.requests("POST", "/code-tasks")

    assert run.status == 1
    assert run.errors == messages.text("errors.INPUT_CLOSED", "en") + "\n"
    assert posts == []


def test_the_refusals_of_the_studio_are_said_in_words(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        change = work.project.seed_change()
        work.studio.fail_next(
            "POST",
            "/projects/{project_id}/code-tasks",
            status=422,
            body={"detail": {"code": "TASK_SOURCE_INVALID", "index": 0}},
        )
        moved = work.ut("tasks", "from-commit", answers=["1"])
        work.studio.fail_next(
            "GET",
            "/projects/{project_id}/code-changes/{commit}",
            status=409,
            body={"detail": {"code": "CODE_CHANGE_AMBIGUOUS"}},
        )
        ambiguous = work.ut("tasks", "from-commit", str(change["commit"])[:7])
        stored = work.project.tasks()

    assert moved.status == 1
    assert moved.errors == work.said("tasks.errors.TASK_SOURCE_INVALID") + "\n"
    assert ambiguous.status == 1
    assert ambiguous.errors == work.said("tasks.errors.CODE_CHANGE_AMBIGUOUS") + "\n"
    assert stored == []


def test_when_every_finding_is_already_a_task_nothing_is_asked(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.project.seed_change()
        first = work.ut("tasks", "from-commit", answers=["a"])
        again = work.ut("tasks", "from-commit")
        posts = work.requests("POST", "/code-tasks")

    assert (first.status, again.status) == (0, 0)
    assert again.output.splitlines()[-1] == work.said("tasks.choice_all_tasks")
    assert work.said("tasks.choose_question") not in again.output
    assert len(posts) == 1


def test_a_review_without_findings_creates_nothing(tmp_path: Path) -> None:
    store_session(tmp_path)
    link_folder(tmp_path / "project")
    overview = {
        "project_id": PROJECT_ID,
        "latest_run": None,
        "latest_review": {
            "run_id": UNKNOWN_RUN,
            "finished_at": "2026-09-29T10:01:12+00:00",
            "reviewed_at": "2026-09-29T10:02:00+00:00",
            "critiques": [{"twin_id": UNKNOWN_RUN, "twin_name": "Pizzeria owner", "findings": []}],
        },
    }
    transport = ScriptedTransport().expect(
        "GET", f"{API}/projects/{PROJECT_ID}/acceptance-tests", body=overview
    )

    run = run_ut(["tasks", "from-test"], tmp_path, transport=transport)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-1] == messages.text("tasks.no_findings", "en")
    transport.assert_done()


def test_a_folder_the_studio_does_not_publish_is_one_sentence(tmp_path: Path) -> None:
    with session(tmp_path) as work:
        work.studio.fail_next(
            "POST",
            "/projects/{project_id}/knowledge-packages",
            status=409,
            body={"detail": {"code": "KNOWLEDGE_PACKAGE_VERSION_CONFLICT"}},
        )
        run = work.ut("tasks", "add", "Write the help text of the page.")
        stored = work.project.tasks()

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-1] == work.said(
        "tasks.folder_not_updated", code="KNOWLEDGE_PACKAGE_VERSION_CONFLICT"
    )
    assert len(stored) == 1


@pytest.mark.parametrize(
    ("arguments", "keys"),
    [
        (["tasks", "--help"], ["tasks.option_all", "tasks.option_json", "tasks.help_from_test"]),
        (["tasks", "add", "--help"], ["tasks.option_text"]),
        (["tasks", "done", "--help"], ["tasks.option_codes", "tasks.option_note"]),
        (["tasks", "drop", "--help"], ["tasks.option_codes", "tasks.option_note"]),
        (["tasks", "reopen", "--help"], ["tasks.option_codes"]),
        (["tasks", "from-test", "--help"], ["tasks.option_run"]),
        (["tasks", "from-commit", "--help"], ["tasks.option_commit"]),
    ],
)
@pytest.mark.parametrize("language", ["en", "it"])
def test_every_sub_command_has_its_help(
    tmp_path: Path, arguments: list[str], keys: list[str], language: str
) -> None:
    run = run_ut(["--lang", language, *arguments], tmp_path, transport=NoNetwork(), variables=WIDE)

    words = " ".join(run.output.split())
    assert run.status == 0
    for key in keys:
        assert " ".join(messages.text(key, language).split()) in words


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_hint_names_the_code_with_the_word_of_the_usage(tmp_path: Path, language: str) -> None:
    run = run_ut(
        ["--lang", language, "tasks", "done", "--help"],
        tmp_path,
        transport=NoNetwork(),
        variables=WIDE,
    )

    usage = run.output.splitlines()[0]
    assert run.status == 0
    assert usage.startswith("usage: ut tasks done ")
    assert usage.endswith(" CODE [CODE ...]")
    assert "`ut tasks done CODE`" in messages.text("tasks.hint", language)


def test_the_command_needs_a_linked_folder(tmp_path: Path) -> None:
    run = run_ut(["tasks"], tmp_path, transport=NoNetwork())

    assert run.status == 6


def test_from_test_speaks_italian(tmp_path: Path) -> None:
    with session(tmp_path, language="it") as work:
        work.project.seed_test_run()
        run = work.ut("tasks", "from-test", answers=["1"])

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[0] == work.said("tasks.test_heading", date="2026-09-29 08:00 UTC")
    assert lines[2].startswith("  1. Titolare della pizzeria, importanza media: ")
    assert work.said("tasks.created", count=1) in lines
    assert lines[-1] == work.said("tasks.folder_updated", path="orchestwin/", version=2)
