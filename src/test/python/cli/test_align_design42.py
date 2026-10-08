from __future__ import annotations

import copy
import json
import string
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.flows import align_design, code_run, design_delta
from orchestwin.cli.flows.changes import git_command
from orchestwin.cli.flows.design_delta import DeltaLine
from orchestwin.cli.http import UrlTransport
from orchestwin.cli.project import ProjectFolder

from .support import fake_studio
from .support.agents import ScriptedAgent
from .support.processes import FakeCommit, ScriptedProcesses, script_repository
from .support.terminal import START, Run, command_context, environment, run_ut
from .support.transports import NoNetwork
from .test_verify_command import (
    FIRST,
    SECOND,
    THIRD,
    Session,
    commit,
    folder_commit,
    no_writes,
    session,
)

LANGUAGES = ("en", "it")
WIDE = {"COLUMNS": "400"}
NAME = "Calcolo mancia"
FOLDER = "20260929-090000"
EARLIER = "20260928-120000"
MOMENT = "2026-09-29T09:00:00+00:00"
LINE = (
    f"Read the file .orchestwin/code/{FOLDER}/prompt.md of this repository and carry out the "
    "work order it contains."
)
CHANGED = " M src/app.js\x00?? src/summary.js\x00"
EXTRA_SCREENS = {
    "it": (
        "SCR-003",
        "Riepilogo della divisione",
        "DEFAULT",
        "Riepilogo",
        '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
        '<p class="lead">Ogni persona vede la sua quota, mancia compresa.</p>'
        '<a class="button" href="#SCR-001">Torna al calcolo</a></main>',
    ),
    "en": (
        "SCR-003",
        "Split summary",
        "DEFAULT",
        "Summary",
        '<main class="card" data-req="REQ-004"><h1>{heading}</h1>'
        '<p class="lead">Each person sees their share, tip included.</p>'
        '<a class="button" href="#SCR-001">Back to the calculation</a></main>',
    ),
}
NEW_LINES = {
    "en": [
        '+ screen SCR-003 "Split summary" added',
        '+ transition TRN-003 "Back to the calculation" added',
        '+ mockup of screen SCR-003 "Split summary" added',
    ],
    "it": [
        "+ schermata SCR-003 «Riepilogo della divisione» aggiunta",
        "+ passaggio TRN-003 «Torna al calcolo» aggiunto",
        "+ mockup della schermata SCR-003 «Riepilogo della divisione» aggiunto",
    ],
}
ORDER_LINES = {
    "en": [
        "- Screen SCR-003 «Split summary»: added",
        "- Transition TRN-003 «Back to the calculation»: added",
        "- Mockup of screen SCR-003 «Split summary»: added",
    ],
    "it": [
        "- Screen SCR-003 «Riepilogo della divisione»: added",
        "- Transition TRN-003 «Torna al calcolo»: added",
        "- Mockup of screen SCR-003 «Riepilogo della divisione»: added",
    ],
}
PEOPLE = {"en": "English", "it": "Italian"}
INTRODUCTION = (
    f'You are working in the repository of the project "{NAME}". The application was built '
    "from version 2 of its approved design (alternative DES-002); the owner has since approved "
    "design version 3. The folder `orchestwin/` of this repository is the knowledge folder of "
    "the project, version 1: `orchestwin/design/design.md` and `orchestwin/design/mockup.html` "
    "describe design version 3."
)
READ_FIRST = [
    "1. `orchestwin/design/design.md` and `orchestwin/design/mockup.html`: the approved design "
    "alternative DES-002 at version 3; the screens have SCR codes.",
    "2. `orchestwin/requirements/requirements.md`: the approved requirements (REQ codes) and "
    "acceptance criteria (AC codes).",
    "3. `orchestwin/state/state.md`: the commits already examined, the open tasks and the "
    "latest results of the acceptance tests.",
]
WORK = (
    "Bring the application in line with design version 3: change only what the differences "
    "above require and keep everything else as it is."
)
ONE_HAND = (
    "The repository has 1 commit after the point the Studio last examined: read the code as it "
    "is now."
)
FINISH = (
    "Say in a few lines: what you changed, file by file; which of the differences above you "
    "covered; how to start the application, so that the owner can verify the acceptance "
    "criteria with `ut test --url <address>` or `ut test --static <folder>`; what you left out "
    "and why."
)


@pytest.fixture(autouse=True)
def no_path_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(code_run, "which", lambda *_arguments, **_options: None)


def sayer(language: str) -> Callable[..., str]:
    def say(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    return say


def heading(language: str) -> list[str]:
    title = messages.text("align.design_heading", language, name=NAME)
    return [title, "=" * len(title)]


def changes_heading(language: str, start: int, end: int, count: int) -> list[str]:
    key = "align.design_changes_heading_one" if count == 1 else "align.design_changes_heading"
    title = messages.text(key, language, **{"from": start, "to": end, "count": count})
    return [title, "=" * len(title)]


def program(tmp_path: Path) -> Path:
    path = tmp_path / "tools" / "claude.exe"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(b"")
    return path


def ut(
    current: Session,
    *arguments: str,
    processes: ScriptedProcesses | None = None,
    answers: Sequence[str] = (),
    language: str = "en",
    agent: ScriptedAgent | None = None,
    claude: bool = True,
) -> Run:
    variables = {**WIDE, "ORCHESTWIN_CLAUDE": str(program(current.tmp_path))} if claude else WIDE
    return run_ut(
        ["--lang", language, "align", "--from-design", *arguments],
        current.tmp_path,
        transport=UrlTransport(),
        answers=answers,
        processes=processes,
        variables=variables,
        run_interactive=agent,
    )


def repository(
    current: Session,
    commits: Sequence[FakeCommit] = (),
    *,
    since: str | None = None,
    status: str = "",
    changed: str | None = None,
) -> ScriptedProcesses:
    processes = script_repository(
        ScriptedProcesses(), current.root, commits, since=since, status=status
    )
    if since is not None:
        processes.expect(
            git_command("rev-parse", "--verify", "--quiet", f"{since}^{{commit}}"),
            output=f"{since}\n",
            repeat=True,
        )
    if changed is not None:
        processes.expect(git_command(*code_run.STATUS_ARGUMENTS), output=changed)
    return processes


def code_folder(root: Path) -> Path:
    return root / ".orchestwin" / "code"


def runs(root: Path) -> list[str]:
    folder = code_folder(root)
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.iterdir() if path.is_dir())


def document(path: Path) -> dict[str, object]:
    return json.loads(path.read_bytes().decode("utf-8"))


def files_under(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def section(text: str, title: str) -> list[str]:
    lines = text.split("\n")
    start = lines.index(title) + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return [line for line in lines[start:end] if line]


def mark_aligned(current: Session, hash_value: str = FIRST) -> None:
    studio, project = current.studio, current.project
    project.seed_change("Show the tip", commit=hash_value, reviewed=False)
    with studio._lock:
        record = next(item for item in project.code_changes if item["commit"] == hash_value)
        studio._decide(project, record, "ALIGNED", None, [], [])


def point(current: Session, version: int) -> None:
    code_run.write_design_point(
        ProjectFolder(current.root),
        version=version,
        folder=EARLIER,
        reason=code_run.CODE_RUN_REASON,
        moment=START,
    )


def new_design(current: Session, change: Callable[[dict[str, object]], dict[str, object]]) -> int:
    studio, project = current.studio, current.project
    with studio._lock:
        package = change(copy.deepcopy(project.designs[-1]["package"]))
        version = studio._append_design(project, package, project.account)
        studio._approve(project, "design")
    return int(version["version_number"])


def other_critique(package: dict[str, object]) -> dict[str, object]:
    critiques = package["critiques"]
    assert isinstance(critiques, list)
    critiques[0]["quote"] = "The summary at the end would help me check the bill."
    return package


def extra_screen(
    current: Session, monkeypatch: pytest.MonkeyPatch, language: str = "en"
) -> Callable[[dict[str, object]], dict[str, object]]:
    screens = fake_studio.SCREENS[language]
    monkeypatch.setitem(screens, "DES-002", (*screens["DES-002"], EXTRA_SCREENS[language]))

    def change(package: dict[str, object]) -> dict[str, object]:
        chosen = str(package["owner_selected_alternative_id"])
        assertions = list(package["owner_assertions"])
        return current.studio._mockup_package(current.project, package, chosen, assertions)

    return change


def delta_between(current: Session, start: int, end: int) -> design_delta.DesignDelta:
    with current.studio._lock:
        packages = {item["version_number"]: item["package"] for item in current.project.designs}
        return design_delta.compare(packages[start], packages[end])


def not_approved(current: Session) -> dict[str, object]:
    return {
        "status": "DESIGN_APPROVAL_REQUIRED",
        "version": current.project.current("design"),
        "gate": None,
        "has_package": True,
        "package_ready_for_gate": True,
        "approved_current_package": False,
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_new_screen_is_listed_and_the_dry_run_writes_the_work_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with session(tmp_path, language=language, link_language=language) as current:
        mark_aligned(current)
        new_design(current, extra_screen(current, monkeypatch, language))
        delta = delta_between(current, 2, 3)
        later = (commit(SECOND, "Show the summary", parent=FIRST), folder_commit(THIRD))
        processes = repository(current, later, since=FIRST)
        agent = ScriptedAgent()
        run = ut(current, "--dry-run", processes=processes, language=language, agent=agent)

    say = sayer(language)
    claude = program(tmp_path)
    folder = code_folder(tmp_path / "project") / FOLDER
    order = (folder / "prompt.md").read_bytes().decode("utf-8")
    publishing = say("common.folder_publishing")
    downloading = say("common.folder_downloading")
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert [line.subject for line in delta.lines] == ["SCREEN", "TRANSITION", "MOCKUP"]
    assert delta.other == 0
    assert run.output.splitlines() == [
        *heading(language),
        say("align.design_point_verify", version=2),
        say("align.design_current", version=3, code="DES-002"),
        "",
        *changes_heading(language, 2, 3, 3),
        *NEW_LINES[language],
        say("align.design_hand_commits_one", count=1),
        say("common.progress_started", label=publishing),
        say("common.progress_done", label=publishing, elapsed="0 s"),
        say("common.progress_started", label=downloading),
        say("common.progress_done", label=downloading, elapsed="0 s"),
        say("verify.folder_updated", version=1),
        "",
        say("code.agent_claude", program=str(claude)),
        say("code.mode_interactive"),
        say("code.order", path=str(folder / "prompt.md")),
        say("code.own_account"),
        say("code.words"),
        f"  {claude}",
        f"  {LINE}",
        "  --mcp-config",
        f"  {folder / 'mcp.json'}",
        say("code.dry_run", folder=str(folder)),
    ]
    assert order.startswith("# Work order from OrchesTwin Studio: the design changed\n\n")
    changed = section(order, "## What changed from design version 2 to version 3")
    assert order.split("\n")[2] == INTRODUCTION
    assert changed == ORDER_LINES[language]
    assert ORDER_LINES[language] == [f"- {design_delta.english(line)}" for line in delta.lines]
    assert section(order, "## Read first") == READ_FIRST
    assert section(order, "## What to do now") == [f"{WORK} {ONE_HAND}"]
    assert f"is written in {PEOPLE[language]}." in order
    assert "Its paid tools are switched off: do not call them." in order
    assert section(order, "## When you finish") == [FINISH]
    assert b"\r" not in order.encode("utf-8") and order.endswith("\n")
    assert agent.calls == []
    assert sorted(path.name for path in folder.iterdir()) == ["mcp.json", "prompt.md"]
    assert not (folder.parent / "latest.json").exists()
    assert not (folder.parent / "design.json").exists()
    assert no_writes(processes)


def test_a_run_that_ends_well_records_the_design_point_and_names_the_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path) as current:
        new_design(current, extra_screen(current, monkeypatch))
        point(current, 2)
        processes = repository(current, changed=CHANGED)
        agent = ScriptedAgent(writes={"src/summary.js": "export {};\n"})
        run = ut(current, processes=processes, answers=["y"], agent=agent)

    say = sayer("en")
    root = tmp_path / "project"
    folder = code_folder(root) / FOLDER
    outcome = document(folder / "outcome.json")
    content = (code_folder(root) / "design.json").read_bytes()
    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert lines[2] == say("align.design_point_run", version=2)
    assert lines[-8:] == [
        f"{say('align.design_confirm')} {say('common.yes_no_default_yes')} ",
        say("code.starting", program="claude.exe"),
        "",
        say("code.ended", elapsed="0 s"),
        say("code.changed", count=2),
        "- src/app.js",
        "- src/summary.js",
        say("align.design_next_steps", version=3),
    ]
    assert agent.calls[0].arguments == (
        str(program(tmp_path)),
        LINE,
        "--mcp-config",
        str(folder / "mcp.json"),
    )
    assert agent.calls[0].folder == root
    assert {
        key: outcome[key]
        for key in (
            "kind",
            "design_from",
            "design_version_number",
            "tasks",
            "request",
            "spend",
            "exit_status",
            "changed_files",
        )
    } == {
        "kind": "design",
        "design_from": 2,
        "design_version_number": 3,
        "tasks": [],
        "request": None,
        "spend": False,
        "exit_status": 0,
        "changed_files": ["src/app.js", "src/summary.js"],
    }
    assert document(code_folder(root) / "latest.json") == {
        "schema_version": 1,
        "folder": FOLDER,
        "started_at": MOMENT,
        "finished_at": MOMENT,
        "agent": "claude",
        "exit_status": 0,
        "changed_files": ["src/app.js", "src/summary.js"],
        "kind": "design",
        "design_version_number": 3,
    }
    assert json.loads(content.decode("utf-8")) == {
        "schema_version": 1,
        "design_version_number": 3,
        "recorded_at": MOMENT,
        "folder": FOLDER,
        "reason": "DESIGN_RUN",
    }
    assert b"\r" not in content
    assert code_run.design_point_version(ProjectFolder(root)) == 3
    assert no_writes(processes)
    processes.assert_done()


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_agent_that_fails_leaves_the_design_point_where_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with session(tmp_path) as current:
        new_design(current, extra_screen(current, monkeypatch))
        point(current, 2)
        processes = repository(current, changed="")
        run = ut(
            current,
            processes=processes,
            answers=[""],
            language=language,
            agent=ScriptedAgent(status=3),
        )

    say = sayer(language)
    root = tmp_path / "project"
    lines = run.output.splitlines()
    latest = document(code_folder(root) / "latest.json")
    assert run.status == 1
    assert run.errors == ""
    assert lines[-3:] == [
        say("code.ended_status", status=3, elapsed="0 s"),
        say("code.changed_none"),
        say("align.design_next_steps_failed", folder=str(code_folder(root) / FOLDER)),
    ]
    assert say("align.design_next_steps", version=3) not in lines
    assert (latest["kind"], latest["exit_status"], latest["design_version_number"]) == (
        "design",
        3,
        3,
    )
    assert document(code_folder(root) / "design.json") == {
        "schema_version": 1,
        "design_version_number": 2,
        "recorded_at": MOMENT,
        "folder": EARLIER,
        "reason": "CODE_RUN",
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_agent_starts_only_after_a_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with session(tmp_path) as current:
        new_design(current, extra_screen(current, monkeypatch))
        point(current, 2)
        agent = ScriptedAgent()
        run = ut(
            current, processes=repository(current), answers=["n"], language=language, agent=agent
        )

    root = tmp_path / "project"
    assert run.status == 5
    assert run.errors == messages.text("align.errors.SPENDING_REFUSED.AGENT", language) + "\n"
    assert agent.calls == []
    assert (code_folder(root) / FOLDER / "prompt.md").is_file()
    assert not (code_folder(root) / FOLDER / "outcome.json").exists()
    assert document(code_folder(root) / "design.json")["design_version_number"] == 2


@pytest.mark.parametrize("language", LANGUAGES)
def test_versions_that_differ_only_in_the_critiques_move_the_point_without_the_agent(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path) as current:
        new_design(current, other_critique)
        point(current, 2)
        processes = repository(current)
        agent = ScriptedAgent()
        run = ut(current, processes=processes, language=language, agent=agent)

    say = sayer(language)
    root = tmp_path / "project"
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert run.output.splitlines() == [
        *heading(language),
        say("align.design_point_run", version=2),
        say("align.design_current", version=3, code="DES-002"),
        "",
        *changes_heading(language, 2, 3, 0),
        say("align.design_other_changes_one"),
        say("align.design_no_code_changes", **{"from": 2, "to": 3}),
    ]
    assert document(code_folder(root) / "design.json") == {
        "schema_version": 1,
        "design_version_number": 3,
        "recorded_at": MOMENT,
        "folder": None,
        "reason": "NO_CODE_CHANGES",
    }
    assert runs(root) == []
    assert not (root / "orchestwin").exists()
    assert agent.calls == []
    assert no_writes(processes)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_code_aligned_with_the_current_design_has_nothing_to_do(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path) as current:
        mark_aligned(current)
        before = files_under(current.root)
        processes = repository(current)
        run = ut(current, processes=processes, language=language, agent=ScriptedAgent())
        after = files_under(current.root)

    say = sayer(language)
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert run.output.splitlines() == [
        *heading(language),
        say("align.design_point_verify", version=2),
        say("align.design_current", version=2, code="DES-002"),
        say("align.design_nothing", version=2),
    ]
    assert after == before
    assert not code_folder(tmp_path / "project").exists()
    assert no_writes(processes)


@pytest.mark.parametrize(
    ("recorded", "key", "start"),
    [
        (None, "align.design_point_verify", 2),
        (1, "align.design_point_verify", 2),
        (2, "align.design_point_run", 2),
        (3, "align.design_point_run", 3),
    ],
)
def test_the_point_of_the_last_run_wins_over_the_point_of_verify_when_it_is_not_lower(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded: int | None, key: str, start: int
) -> None:
    with session(tmp_path) as current:
        mark_aligned(current)
        new_design(current, other_critique)
        new_design(current, extra_screen(current, monkeypatch))
        if recorded is not None:
            point(current, recorded)
        delta = delta_between(current, start, 4)
        processes = repository(current, since=FIRST)
        run = ut(current, "--dry-run", processes=processes, agent=ScriptedAgent())

    say = sayer("en")
    lines = run.output.splitlines()
    order = (code_folder(tmp_path / "project") / FOLDER / "prompt.md").read_text(encoding="utf-8")
    assert run.status == 0, run.errors
    assert lines[2:7] == [
        say(key, version=start),
        say("align.design_current", version=4, code="DES-002"),
        "",
        *changes_heading("en", start, 4, len(delta.lines)),
    ]
    assert f"## What changed from design version {start} to version 4" in order
    assert f"from version {start} of its approved design (alternative DES-002)" in order
    assert "commits after the point the Studio last examined" not in order
    assert "1 commit after the point the Studio last examined" not in order


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_a_point_and_without_since_the_command_asks_for_one(
    tmp_path: Path, language: str
) -> None:
    with session(tmp_path) as current:
        run = ut(current, processes=repository(current), language=language)

    assert run.status == 2
    assert run.errors == messages.text("errors.ALIGN_DESIGN_NO_POINT", language) + "\n"
    assert run.output.splitlines() == heading(language)


@pytest.mark.parametrize("value", ["abc", "0", "2.5", "+3", chr(0xFF13), "3 4"])
def test_since_with_the_design_wants_a_whole_number_from_one(tmp_path: Path, value: str) -> None:
    run = run_ut(
        ["--lang", "en", "align", "--from-design", "--since", value],
        tmp_path,
        transport=NoNetwork(),
    )

    assert run.status == 2
    assert run.output == ""
    assert run.errors == (
        messages.text("errors.ALIGN_DESIGN_SINCE_INVALID", "en", value=value) + "\n"
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_design_waiting_for_approval_is_refused(tmp_path: Path, language: str) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next(
            "GET",
            "/projects/{project_id}/design/readiness",
            status=200,
            body=not_approved(current),
        )
        run = ut(current, "--since", "1", processes=repository(current), language=language)

    assert run.status == 1
    assert run.errors == (
        messages.text("errors.ALIGN_DESIGN_NOT_APPROVED", language, version=2) + "\n"
    )
    assert run.output.splitlines() == heading(language)


def test_changes_not_committed_stop_the_command_before_the_work_order(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        processes = repository(current, status=" M src/app.js\x00")
        run = ut(current, "--since", "1", processes=processes)

    say = sayer("en")
    assert run.status == 1
    assert run.errors == messages.text("errors.ALIGN_DESIGN_UNCOMMITTED", "en") + "\n"
    assert run.output.splitlines() == [
        *heading("en"),
        say("align.design_point_since", version=1),
        say("align.design_current", version=2, code="DES-002"),
    ]
    assert not code_folder(tmp_path / "project").exists()
    assert no_writes(processes)


def test_a_starting_version_the_studio_does_not_have_is_named(tmp_path: Path) -> None:
    with session(tmp_path) as current:
        current.studio.fail_next("GET", "/projects/{project_id}/design", status=200, body=[])
        run = ut(current, "--since", "1", processes=repository(current))

    assert run.status == 2
    assert run.errors == (
        messages.text("errors.ALIGN_DESIGN_VERSION_UNKNOWN", "en", version=1) + "\n"
    )
    assert not code_folder(tmp_path / "project").exists()


@pytest.mark.parametrize("language", LANGUAGES)
def test_options_that_do_not_go_together_are_refused(tmp_path: Path, language: str) -> None:
    def refused(*arguments: str) -> Run:
        return run_ut(["--lang", language, "align", *arguments], tmp_path, transport=NoNetwork())

    pending = refused("--pending", "--from-design")
    budget = refused("--max-agent-usd", "2")
    alone = refused("--pending", "--since", "1111111")

    assert (pending.status, budget.status, alone.status) == (2, 2, 2)
    assert pending.output == budget.output == alone.output == ""
    assert pending.errors == (
        messages.text("align.errors.ALIGN_PENDING_ALONE.FROM_DESIGN", language) + "\n"
    )
    assert budget.errors == messages.text("errors.ALIGN_BUDGET_NEEDS_DESIGN", language) + "\n"
    assert alone.errors == messages.text("align.errors.ALIGN_PENDING_ALONE", language) + "\n"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_help_names_the_alignment_from_the_design(tmp_path: Path, language: str) -> None:
    def compact(text: str) -> str:
        return "".join(text.split())

    run = run_ut(["--lang", language, "align", "--help"], tmp_path, transport=NoNetwork())

    say = sayer(language)
    assert run.status == 0
    assert compact(f"--from-design {say('align.option_from_design')}") in compact(run.output)
    assert compact(f"--max-agent-usd USD {say('align.option_max_agent_usd')}") in compact(
        run.output
    )
    assert compact(f"--since COMMIT {say('align.option_since')}") in compact(run.output)


@pytest.mark.parametrize(
    ("language", "usd"),
    [("en", "1.50"), ("it", "1,50")],
)
def test_headless_claude_saved_by_ut_code_gets_the_budget_of_the_run(
    tmp_path: Path, language: str, usd: str
) -> None:
    with session(tmp_path) as current:
        code_run.write_settings(
            ProjectFolder(current.root), code_run.CodeSettings(model="opus", headless=True)
        )
        run = ut(
            current,
            "--since",
            "1",
            "--max-agent-usd",
            "1.5",
            "--dry-run",
            processes=repository(current),
            language=language,
            agent=ScriptedAgent(),
        )

    say = sayer(language)
    lines = run.output.splitlines()
    folder = code_folder(tmp_path / "project") / FOLDER
    start = lines.index(say("code.agent_claude", program=str(program(tmp_path))))
    assert run.status == 0, run.errors
    assert lines[start : start + 6] == [
        say("code.agent_claude", program=str(program(tmp_path))),
        say("code.mode_headless_claude"),
        say("code.model", model="opus"),
        say("code.budget", usd=usd),
        say("code.order", path=str(folder / "prompt.md")),
        say("code.own_account"),
    ]
    assert lines[-3:-1] == ["  --max-budget-usd", "  1.50"]
    assert "  --print" in lines


@pytest.mark.parametrize("language", LANGUAGES)
def test_agent_problems_are_said_for_this_command(tmp_path: Path, language: str) -> None:
    with session(tmp_path) as current:
        budget = ut(
            current,
            "--since",
            "1",
            "--max-agent-usd",
            "2",
            processes=repository(current),
            language=language,
        )
        missing = ut(
            current, "--since", "1", processes=repository(current), language=language, claude=False
        )

    assert (budget.status, missing.status) == (2, 1)
    assert budget.errors == (
        messages.text("align.errors.CODE_BUDGET_NEEDS_HEADLESS", language) + "\n"
    )
    assert budget.output.splitlines() == heading(language)
    assert missing.errors == (
        messages.text("align.errors.CODE_AGENT_NOT_FOUND", language, variable="ORCHESTWIN_CLAUDE")
        + "\n"
    )
    assert runs(tmp_path / "project") == []


@pytest.mark.parametrize(
    ("line", "english", "italian"),
    [
        (
            DeltaLine("CHANGE", "SELECTION", "DES-002", "Rivista", None, (), "DES-001", "DES-002"),
            "~ chosen alternative: DES-002 instead of DES-001",
            "~ alternativa scelta: DES-002 al posto di DES-001",
        ),
        (
            DeltaLine(
                "CHANGE",
                "ALTERNATIVE",
                "DES-002",
                "Rivista",
                None,
                ("summary", "information_architecture"),
                None,
                None,
            ),
            '~ alternative DES-002 "Rivista" changed: summary, information architecture',
            "~ alternativa DES-002 «Rivista» cambiata: sintesi, architettura delle informazioni",
        ),
        (
            DeltaLine("ADD", "WORKFLOW", "WFL-003", "Divisione", None, (), None, None),
            '+ flow WFL-003 "Divisione" added',
            "+ flusso WFL-003 «Divisione» aggiunto",
        ),
        (
            DeltaLine("CHANGE", "VISUAL", None, None, None, ("palette", "tokens"), None, None),
            "~ visual language changed: colours, style tokens",
            "~ linguaggio visivo cambiato: colori, token di stile",
        ),
        (
            DeltaLine("REMOVE", "SCREEN", "SCR-004", "Storico", None, (), None, None),
            '- screen SCR-004 "Storico" removed',
            "- schermata SCR-004 «Storico» tolta",
        ),
        (
            DeltaLine("CHANGE", "SCREEN", "SCR-003", "Fa 15", None, ("title",), None, None),
            '~ screen SCR-003 "Fa 15" changed: title',
            "~ schermata SCR-003 «Fa 15» cambiata: titolo",
        ),
        (
            DeltaLine(
                "CHANGE",
                "ELEMENT",
                "ELM-004",
                "AC",
                "SCR-001",
                ("content", "accessible_name", "required"),
                None,
                None,
            ),
            '~ screen SCR-001: element ELM-004 "AC" changed: content, accessible name, required',
            "~ schermata SCR-001: elemento ELM-004 «AC» cambiato: contenuto, nome accessibile, "
            "obbligatorietà",
        ),
        (
            DeltaLine("REMOVE", "ELEMENT", "ELM-031", "%", "SCR-002", (), None, None),
            '- screen SCR-002: element ELM-031 "%" removed',
            "- schermata SCR-002: elemento ELM-031 «%» tolto",
        ),
        (
            DeltaLine("CHANGE", "TRANSITION", "TRN-002", "=", None, ("target",), None, None),
            '~ transition TRN-002 "=" changed: destination screen',
            "~ passaggio TRN-002 «=» cambiato: schermata di arrivo",
        ),
        (
            DeltaLine("CHANGE", "MOCKUP", "SCR-001", "Pronta", None, ("markup",), None, None),
            '~ mockup of screen SCR-001 "Pronta" redrawn',
            "~ mockup della schermata SCR-001 «Pronta» ridisegnato",
        ),
        (
            DeltaLine("REMOVE", "MOCKUP", "SCR-006", "Scientifica", None, (), None, None),
            '- mockup of screen SCR-006 "Scientifica" removed',
            "- mockup della schermata SCR-006 «Scientifica» tolto",
        ),
        (
            DeltaLine("CHANGE", "STYLES", None, None, None, (), None, None),
            "~ mockup styles changed",
            "~ stili del mockup cambiati",
        ),
    ],
)
def test_each_difference_is_said_in_one_line_for_people(
    tmp_path: Path, line: DeltaLine, english: str, italian: str
) -> None:
    said = {
        language: align_design.line_text(
            command_context(environment(tmp_path, transport=NoNetwork()), language=language), line
        )
        for language in LANGUAGES
    }

    assert said == {"en": english, "it": italian}


def test_the_texts_of_the_command_have_both_languages_and_the_same_placeholders() -> None:
    def placeholders(sentence: str) -> set[str]:
        return {name for _, name, _, _ in string.Formatter().parse(sentence) if name is not None}

    keys = [
        *(key for key in messages.FILES["align"] if key.startswith(("align.design", "align.opt"))),
        *(key for key in messages.FILES["align"] if key.startswith("align.errors.")),
        *(key for key in messages.FILES["errors"] if "ALIGN_DESIGN" in key or "_NEEDS_" in key),
    ]
    fields = [f"align.design_field_{name}" for name in design_delta.FIELDS]

    assert len(design_delta.FIELDS) == 21
    assert [key for key in fields if not messages.known(key)] == []
    for key in keys:
        entry = messages.MESSAGES[key]
        assert set(entry) == {"it", "en"}, key
        assert placeholders(entry["it"]) == placeholders(entry["en"]), key
        assert "login" not in entry["it"].lower(), key
