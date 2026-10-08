from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from orchestwin.artifacts.mockup_html import MOCKUP_HTML_FILE
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import code_order
from orchestwin.cli.flows.code_order import (
    Task,
    Work,
    approved_folder,
    chosen_tasks,
    facts_of,
    open_tasks,
    origin_text,
    tasks_of,
    work_for,
    work_order,
    work_text,
)
from orchestwin.cli.folder import unpack
from orchestwin.cli.project import ProjectFolder, ProjectLink
from orchestwin.knowledge import layout, state

from .support.folders import partial_archive, valid_archive
from .support.terminal import PROJECT_ID, START

COMMIT = "4cc93522a99c8811847e2621283c2526f9ec9a4f"
TEST_RUN = "00000000-0000-4000-8000-00000000e001"
TWIN = "00000000-0000-4000-8000-0000000000b1"
CREATED = "2026-09-29T16:48:37+00:00"
RECEPTION = "Addetti all'accoglienza"
VOLUNTEERS = "Organizzatori volontari"
EMPTY_ORIGIN = {
    "commit": None,
    "test_run_id": None,
    "twin_id": None,
    "twin_name": None,
    "finding": None,
}


def task(
    code: str,
    text: str,
    *,
    status: str = "OPEN",
    origin: dict[str, object] | None = None,
    from_commit: str | None = None,
    requirements: Sequence[str] = (),
    screens: Sequence[str] = (),
    criteria: Sequence[str] = (),
) -> dict[str, object]:
    closed = status != "OPEN"
    return {
        "code": code,
        "text": text,
        "about": {
            "requirements": list(requirements),
            "screens": list(screens),
            "criteria": list(criteria),
        },
        "origin": origin,
        "from_commit": from_commit,
        "created_at": CREATED,
        "status": status,
        "closed_at": CREATED if closed else None,
        "note": None,
    }


DONE_TASK = task(
    "TSK-001",
    "Allineare il riepilogo al design.",
    status="DONE",
    origin={"kind": "OWNER", **EMPTY_ORIGIN},
)
OLD_TASK = {
    "code": "TSK-002",
    "text": "Sostituire il campo libero della percentuale con tre pulsanti 5%, 10% e 15%.",
    "about": {"requirements": ["REQ-001", "REQ-002"], "screens": ["SCR-001"]},
    "from_commit": COMMIT,
    "created_at": CREATED,
    "status": "OPEN",
}
VERDICT_TASK = task(
    "TSK-003",
    "Impedire che il totale\nvada a capo.",
    origin={"kind": "CODE_CHANGE", **EMPTY_ORIGIN, "commit": COMMIT},
    from_commit=COMMIT,
    screens=["SCR-005"],
)
TEST_TASK = task(
    "TSK-004",
    "Mostrare un avviso accanto al campo del nome.",
    origin={
        "kind": "TEST_RUN",
        **EMPTY_ORIGIN,
        "test_run_id": TEST_RUN,
        "twin_id": TWIN,
        "twin_name": RECEPTION,
        "finding": "Con il nome vuoto non compare nessun messaggio.",
    },
    requirements=["REQ-003"],
    screens=["SCR-002"],
    criteria=["AC-002"],
)
COMMIT_TASK = task(
    "TSK-005",
    "Rendere più grande il pulsante Conferma.",
    origin={
        "kind": "CODE_CHANGE",
        **EMPTY_ORIGIN,
        "commit": COMMIT,
        "twin_id": TWIN,
        "twin_name": VOLUNTEERS,
        "finding": "Il pulsante è troppo piccolo per chi è in piedi.",
    },
    from_commit=COMMIT,
    requirements=["REQ-001"],
    screens=["SCR-001"],
)
OWNER_TASK = task(
    "TSK-006",
    "Aggiungere la pagina delle informazioni.",
    origin={"kind": "OWNER", **EMPTY_ORIGIN},
)
DROPPED_TASK = task(
    "TSK-007",
    "Tradurre l'applicazione in tedesco.",
    status="DROPPED",
    origin={"kind": "OWNER", **EMPTY_ORIGIN},
)
TASKS = [DONE_TASK, OLD_TASK, VERDICT_TASK, TEST_TASK, COMMIT_TASK, OWNER_TASK, DROPPED_TASK]
TASK_LINES = [
    "Carry out these tasks for the code. The owner of the project decided each of them.",
    "- TSK-002: Sostituire il campo libero della percentuale con tre pulsanti 5%, 10% e 15%.",
    "  From: the decision on the commit 4cc9352",
    "  About: REQ-001, REQ-002, SCR-001",
    "- TSK-003: Impedire che il totale vada a capo.",
    "  From: the decision on the commit 4cc9352",
    "  About: SCR-005",
    "- TSK-004: Mostrare un avviso accanto al campo del nome.",
    '  From: a finding of the twin "Addetti all\'accoglienza" on the acceptance tests: '
    '"Con il nome vuoto non compare nessun messaggio."',
    "  About: REQ-003, SCR-002, AC-002",
    "- TSK-005: Rendere più grande il pulsante Conferma.",
    '  From: a finding of the twin "Organizzatori volontari" on the commit 4cc9352: '
    '"Il pulsante è troppo piccolo per chi è in piedi."',
    "  About: REQ-001, SCR-001",
    "- TSK-006: Aggiungere la pagina delle informazioni.",
    "  From: written by the owner",
]


def complete_order(language: str, paid_tools: str, work: Sequence[str]) -> str:
    lines = [
        "# Work order from OrchesTwin Studio",
        "",
        'You are working in the repository of the project "Calcolo mancia". Its design was '
        "approved in OrchesTwin Studio and the application is developed here, outside the "
        "Studio. The folder `orchestwin/` of this repository is the knowledge folder of the "
        "project, version 1: it is the source of truth for what to build and for whom.",
        "",
        "## Read first",
        "1. `orchestwin/ORCHESTWIN.md`: the index of the folder and the state of the development.",
        "2. `orchestwin/requirements/requirements.md`: the approved requirements (REQ codes) and "
        "acceptance criteria (AC codes).",
        "3. `orchestwin/design/design.md` and `orchestwin/design/mockup.html`: the approved "
        "design alternative DES-002 and its mockup; the screens have SCR codes.",
        "4. `orchestwin/twins/twins.md`: the user twins, synthetic representatives of the user "
        "groups; `orchestwin/twins/feedback/feedback.md`: what they said about the design, the "
        "commits and the tests, and what they learned during the development.",
        "5. `orchestwin/state/state.md`: the commits already examined, the open tasks and the "
        "latest results of the acceptance tests.",
        "",
        "## What to do now",
        *work,
        "",
        "## Rules",
        "- The application is for the people described by the twins: every text that a person "
        f"reads in the application is written in {language}.",
        "- Follow the approved design (screens, flows, labels) and the requirements. Where you "
        "have to depart from them, do it and say so at the end with the reason: the owner "
        "realigns the design with `ut verify`.",
        "- Never edit `orchestwin/` and `.orchestwin/`: OrchesTwin Studio writes them.",
        "- Do not commit and do not push: the owner reviews your changes and commits them.",
        "- The MCP server `orchestwin-twins` answers from the knowledge folder: the twins, the "
        f"requirements, the design, the feedback, the tasks and the test results. {paid_tools}",
        "- Start no paid service and add no dependency that the work does not need.",
        "",
        "## When you finish",
        "Say in a few lines: what you changed, file by file; which tasks you consider done, by "
        "their TSK code; how to start the application, so that the owner can verify the "
        "acceptance criteria with `ut test --url <address>` or `ut test --static <folder>`; what "
        "you left out and why.",
    ]
    return "\n".join(lines) + "\n"


FREE = "Its paid tools are switched off: do not call them."
PAID = (
    "Its paid tools (asking a twin, reviewing the changes, running the acceptance tests) spend "
    "on the owner's Studio: use them only when the work needs them."
)


def linked(
    tmp_path: Path,
    *,
    language: str | None = "it",
    archive: bytes | None = None,
    knowledge_folder: str = "orchestwin",
) -> ProjectFolder:
    link = ProjectLink(
        studio="http://127.0.0.1:8000",
        api_prefix="/api/v1",
        project_id=PROJECT_ID,
        project_name="Calcolo mancia",
        mode="DESIGN_ONLY",
        language=language,
        created_at=START.isoformat(timespec="seconds"),
        knowledge_folder=knowledge_folder,
    )
    project = ProjectFolder.create(tmp_path / "project", link)
    unpack(valid_archive() if archive is None else archive, project.knowledge)
    return project


def edit_json(path: Path, change: Callable[[dict], None]) -> None:
    document = json.loads(path.read_bytes().decode("utf-8"))
    change(document)
    path.write_bytes(json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))


def write_tasks(project: ProjectFolder, tasks: Sequence[dict[str, object]]) -> None:
    def change(document: dict) -> None:
        document["tasks"] = list(tasks)

    edit_json(project.knowledge / "state" / "state.json", change)


def folder_language(project: ProjectFolder, language: str | None) -> None:
    def change(document: dict) -> None:
        document["project"]["language"] = language

    edit_json(project.knowledge / "orchestwin.json", change)


def order_of(
    project: ProjectFolder,
    work: Work,
    *,
    language: str = "en",
    spend: bool = False,
) -> str:
    facts = facts_of(project, approved_folder(project), language=language)
    return work_order(facts, work, spend=spend)


def section(order: str, heading: str) -> list[str]:
    lines = order.split("\n")
    start = lines.index(heading) + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return [line for line in lines[start:end] if line]


def test_the_work_order_of_a_complete_folder_follows_the_template(tmp_path: Path) -> None:
    project = linked(tmp_path, language="it")
    write_tasks(project, TASKS)
    work = work_for(open_tasks(project), (), None)

    order = order_of(project, work, language="en")

    assert order == complete_order("Italian", FREE, TASK_LINES)
    assert "\r" not in order
    assert "verdict" not in order
    assert work.every is True
    assert work.codes == ("TSK-002", "TSK-003", "TSK-004", "TSK-005", "TSK-006")


def test_without_open_tasks_the_order_builds_the_application(tmp_path: Path) -> None:
    project = linked(tmp_path, language="it")
    write_tasks(project, [DONE_TASK, DROPPED_TASK])
    folder_language(project, "en")

    order = order_of(project, work_for(open_tasks(project), (), None), language="it", spend=True)

    assert order == complete_order(
        "English",
        PAID,
        [
            "Build the application as the approved requirements and design describe. If the "
            "repository already holds the application, bring it in line with them."
        ],
    )


def test_files_the_folder_does_not_have_leave_the_list_and_the_numbers_stay_in_order(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    for name in ("ORCHESTWIN.md", "design/mockup.html", "twins/twins.md"):
        (project.knowledge / name).unlink()

    lines = section(order_of(project, Work()), "## Read first")

    assert lines == [
        "1. `orchestwin/requirements/requirements.md`: the approved requirements (REQ codes) "
        "and acceptance criteria (AC codes).",
        "2. `orchestwin/design/design.md`: the approved design alternative DES-002; the screens "
        "have SCR codes.",
        "3. `orchestwin/twins/feedback/feedback.md`: what the user twins said about the design, "
        "the commits and the tests, and what they learned during the development.",
        "4. `orchestwin/state/state.md`: the commits already examined, the open tasks and the "
        "latest results of the acceptance tests.",
    ]


def test_a_folder_with_the_mockup_and_the_twins_only_names_what_it_has(tmp_path: Path) -> None:
    project = linked(tmp_path)
    for name in ("design/design.md", "twins/feedback/feedback.md", "state/state.md"):
        (project.knowledge / name).unlink()

    lines = section(order_of(project, Work()), "## Read first")

    assert lines[2:] == [
        "3. `orchestwin/design/mockup.html`: the mockup of the approved design alternative "
        "DES-002; the screens have SCR codes.",
        "4. `orchestwin/twins/twins.md`: the user twins, synthetic representatives of the user "
        "groups.",
    ]


def test_a_folder_without_any_of_the_texts_has_no_list(tmp_path: Path) -> None:
    project = linked(tmp_path)
    for name in code_order.READ_FIRST:
        (project.knowledge / name).unlink()

    order = order_of(project, Work())

    assert "## Read first" not in order
    assert "## What to do now\nBuild the application" in order


def test_the_alternative_comes_from_the_state_then_from_the_design(tmp_path: Path) -> None:
    project = linked(tmp_path)

    def forget_state(document: dict) -> None:
        document["reference"]["design"]["alternative_code"] = None

    def forget_design(document: dict) -> None:
        document["package"]["owner_selected_alternative_id"] = None

    edit_json(project.knowledge / "state" / "state.json", forget_state)
    from_design = section(order_of(project, Work()), "## Read first")[2]
    edit_json(project.knowledge / "design" / "design.json", forget_design)
    unknown = section(order_of(project, Work()), "## Read first")[2]

    assert "the approved design alternative DES-002 and its mockup" in from_design
    assert unknown == (
        "3. `orchestwin/design/design.md` and `orchestwin/design/mockup.html`: the approved "
        "design alternative and its mockup; the screens have SCR codes."
    )


def test_a_knowledge_folder_with_another_name_is_named_everywhere(tmp_path: Path) -> None:
    project = linked(tmp_path, knowledge_folder="conoscenza")

    order = order_of(project, Work())

    assert "The folder `conoscenza/` of this repository" in order
    assert "1. `conoscenza/ORCHESTWIN.md`: the index" in order
    assert "- Never edit `conoscenza/` and `.orchestwin/`" in order
    assert "`orchestwin/" not in order


@pytest.mark.parametrize(
    ("folder", "link", "command", "expected"),
    [
        ("it", None, "en", "Italian"),
        ("it", "en", "en", "Italian"),
        ("en", "it", "it", "English"),
        (None, "it", "en", "Italian"),
        (None, "it-IT", "en", "Italian"),
        (None, "en", "it", "English"),
        ("  ", "it", "en", "Italian"),
        (None, None, "it", "Italian"),
        (None, None, "en", "English"),
        (None, "  ", "it", "Italian"),
    ],
)
def test_the_language_of_the_application_comes_from_the_folder_then_the_link_then_the_command(
    tmp_path: Path, folder: str | None, link: str | None, command: str, expected: str
) -> None:
    project = linked(tmp_path, language=link)
    folder_language(project, folder)

    order = order_of(project, Work(), language=command)

    assert f"is written in {expected}." in order


@pytest.mark.parametrize(
    ("folder", "link", "command", "expected"),
    [
        ("it", None, "en", "it"),
        ("en", "it", "it", "en"),
        (None, "it", "en", "it"),
        (None, None, "en", "en"),
    ],
)
def test_the_language_of_the_project_is_read_from_the_folder_first(
    tmp_path: Path, folder: str | None, link: str | None, command: str, expected: str
) -> None:
    project = linked(tmp_path, language=link)
    folder_language(project, folder)
    broken = linked(tmp_path / "broken", language=link)
    (broken.knowledge / "orchestwin.json").write_text("{", encoding="utf-8")

    assert code_order.project_language(project, command) == expected
    assert code_order.project_language(broken, command) == (link or command)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (OLD_TASK, "the decision on the commit 4cc9352"),
        (VERDICT_TASK, "the decision on the commit 4cc9352"),
        (
            TEST_TASK,
            'a finding of the twin "Addetti all\'accoglienza" on the acceptance tests: '
            '"Con il nome vuoto non compare nessun messaggio."',
        ),
        (
            COMMIT_TASK,
            'a finding of the twin "Organizzatori volontari" on the commit 4cc9352: '
            '"Il pulsante è troppo piccolo per chi è in piedi."',
        ),
        (OWNER_TASK, "written by the owner"),
        ({**OLD_TASK, "from_commit": None}, "the decision on a commit"),
        (
            {**TEST_TASK, "origin": {**TEST_TASK["origin"], "twin_name": None, "finding": None}},
            "a finding of a twin on the acceptance tests",
        ),
        (
            {**COMMIT_TASK, "origin": {**COMMIT_TASK["origin"], "commit": None}},
            'a finding of the twin "Organizzatori volontari" on the commit 4cc9352: '
            '"Il pulsante è troppo piccolo per chi è in piedi."',
        ),
        (
            {**OLD_TASK, "origin": {"kind": "SOMETHING_NEW"}},
            "the decision on the commit 4cc9352",
        ),
    ],
)
def test_each_origin_of_a_task_is_said_in_words(item: dict[str, object], expected: str) -> None:
    (found,) = tasks_of({"tasks": [item]})

    assert origin_text(found) == expected


def test_the_request_is_quoted_line_by_line_after_the_tasks() -> None:
    work = Work(
        tasks=(Task(code="TSK-006", text="Aggiungere la pagina delle informazioni."),),
        request="Aggiungi un pulsante per azzerare i campi.\n\nPoi   rilancia i test.",
    )

    assert work_text(work).split("\n") == [
        "Carry out these tasks for the code. The owner of the project decided each of them.",
        "- TSK-006: Aggiungere la pagina delle informazioni.",
        "  From: the decision on a commit",
        "",
        "The owner asks:",
        "> Aggiungi un pulsante per azzerare i campi.",
        ">",
        "> Poi   rilancia i test.",
    ]


def test_open_tasks_leave_out_the_closed_and_the_broken_ones(tmp_path: Path) -> None:
    project = linked(tmp_path)
    write_tasks(
        project,
        [
            *TASKS,
            {**OWNER_TASK, "code": None},
            {**OWNER_TASK, "code": "TSK-009", "text": "   "},
            "not a task",
        ],
    )

    found = open_tasks(project)

    assert [item.code for item in found] == ["TSK-002", "TSK-003", "TSK-004", "TSK-005", "TSK-006"]
    assert found[0] == Task(
        code="TSK-002",
        text=OLD_TASK["text"],
        origin=None,
        from_commit=COMMIT,
        requirements=("REQ-001", "REQ-002"),
        screens=("SCR-001",),
        criteria=(),
    )
    assert tasks_of(None) == ()
    assert tasks_of({"tasks": "none"}) == ()


def test_a_folder_without_the_state_document_has_no_tasks(tmp_path: Path) -> None:
    project = linked(tmp_path)
    (project.knowledge / "state" / "state.json").unlink()

    assert open_tasks(project) == ()


def test_the_tasks_named_are_chosen_in_any_case_and_in_the_order_of_the_folder() -> None:
    found = tasks_of({"tasks": TASKS})

    chosen = chosen_tasks(found, ["tsk-006", "TSK-004", "TSK-006"])

    assert [item.code for item in chosen] == ["TSK-004", "TSK-006"]


def test_a_code_that_is_not_an_open_task_is_refused() -> None:
    found = tasks_of({"tasks": TASKS})

    with pytest.raises(CliError) as caught:
        chosen_tasks(found, ["TSK-004", "tsk-001", "TSK-999", "TSK-001", "nothing"])

    assert (caught.value.code, caught.value.status) == ("CODE_TASK_UNKNOWN", 2)
    assert caught.value.values == {"codes": "TSK-001, TSK-999, NOTHING"}


@pytest.mark.parametrize(
    ("codes", "asked", "tasks", "expected_codes", "expected_request", "every"),
    [
        (("TSK-005",), None, TASKS, ("TSK-005",), None, False),
        ((), None, TASKS, ("TSK-002", "TSK-003", "TSK-004", "TSK-005", "TSK-006"), None, True),
        ((), "Azzera i campi", TASKS, (), "Azzera i campi", False),
        (
            ("TSK-004", "TSK-002"),
            " Azzera i campi ",
            TASKS,
            ("TSK-002", "TSK-004"),
            "Azzera i campi",
            False,
        ),
        ((), None, [DONE_TASK], (), None, False),
        (("", " "), "   ", [DONE_TASK], (), None, False),
    ],
)
def test_the_work_comes_from_the_tasks_named_the_request_or_every_open_task(
    codes: tuple[str, ...],
    asked: str | None,
    tasks: list[dict[str, object]],
    expected_codes: tuple[str, ...],
    expected_request: str | None,
    every: bool,
) -> None:
    work = work_for(tasks_of({"tasks": tasks}), codes, asked)

    assert (work.codes, work.request, work.every) == (expected_codes, expected_request, every)


def test_the_design_must_be_approved_in_the_local_folder(tmp_path: Path) -> None:
    missing = linked(tmp_path / "missing")
    shutil.rmtree(missing.knowledge)
    partial = linked(tmp_path / "partial", archive=partial_archive(through="requirements"))
    pending = linked(tmp_path / "pending")

    def reopen(document: dict) -> None:
        document["stages"]["design"]["gate"]["status"] = "PENDING"

    edit_json(pending.knowledge / "orchestwin.json", reopen)

    for project in (missing, partial, pending):
        with pytest.raises(CliError) as caught:
            approved_folder(project)
        assert (caught.value.code, caught.value.status) == ("CODE_DESIGN_REQUIRED", 1)
    assert approved_folder(linked(tmp_path / "approved")).project_name == "Calcolo mancia"


def test_the_copied_names_equal_the_ones_of_the_knowledge_folder() -> None:
    assert code_order.STATE_DOCUMENT == state.STATE_DOCUMENT
    assert code_order.STATE_TEXT == state.STATE_TEXT
    assert code_order.TASK_STATUSES == state.TASK_STATUSES
    assert code_order.TASK_ORIGINS == state.TASK_ORIGINS
    assert code_order.INDEX_TEXT == layout.KNOWLEDGE_INDEX
    assert layout.stage_text("requirements") == code_order.REQUIREMENTS_TEXT
    assert layout.stage_text("design") == code_order.DESIGN_TEXT
    assert layout.stage_document("design") == code_order.DESIGN_DOCUMENT
    assert code_order.MOCKUP_FILE == MOCKUP_HTML_FILE
    assert layout.stage_text("twins") == code_order.TWINS_TEXT
    assert code_order.FEEDBACK_TEXT == layout.FEEDBACK_TEXT
