from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.flows import code_run
from orchestwin.cli.flows.changes import git_command
from orchestwin.cli.folder import unpack
from orchestwin.cli.project import ProjectFolder

from .support.agents import ScriptedAgent
from .support.folders import partial_archive, valid_archive
from .support.processes import ScriptedProcesses
from .support.terminal import Run, link_folder, run_ut
from .support.transports import NoNetwork

LANGUAGES = ("en", "it")
FOLDER = "20260929-090000"
TOP = git_command("rev-parse", "--show-toplevel")
STATUS = git_command(*code_run.STATUS_ARGUMENTS)
LINE = (
    f"Read the file .orchestwin/code/{FOLDER}/prompt.md of this repository and carry out the "
    "work order it contains."
)
CREATED = "2026-09-29T16:48:37+00:00"
COMMIT = "4cc93522a99c8811847e2621283c2526f9ec9a4f"
NO_ORIGIN = {
    "commit": None,
    "test_run_id": None,
    "twin_id": None,
    "twin_name": None,
    "finding": None,
}
DONE_TASK = {
    "code": "TSK-001",
    "text": "Allineare il riepilogo al design.",
    "about": {"requirements": [], "screens": [], "criteria": []},
    "origin": {"kind": "OWNER", **NO_ORIGIN},
    "from_commit": None,
    "created_at": CREATED,
    "status": "DONE",
    "closed_at": CREATED,
    "note": "fatto",
}
OLD_TASK = {
    "code": "TSK-002",
    "text": "Sostituire il campo libero della percentuale con tre pulsanti.",
    "about": {"requirements": ["REQ-001"], "screens": ["SCR-001"]},
    "from_commit": COMMIT,
    "created_at": CREATED,
    "status": "OPEN",
}
TEST_TASK = {
    "code": "TSK-004",
    "text": "Mostrare un avviso accanto al campo del nome.",
    "about": {"requirements": ["REQ-003"], "screens": ["SCR-002"], "criteria": ["AC-002"]},
    "origin": {
        "kind": "TEST_RUN",
        **NO_ORIGIN,
        "test_run_id": "00000000-0000-4000-8000-00000000e001",
        "twin_id": "00000000-0000-4000-8000-0000000000b1",
        "twin_name": "Addetti all'accoglienza",
        "finding": "Con il nome vuoto non compare nessun messaggio.",
    },
    "from_commit": None,
    "created_at": CREATED,
    "status": "OPEN",
    "closed_at": None,
    "note": None,
}
OWNER_TASK = {
    "code": "TSK-006",
    "text": "Aggiungere la pagina delle informazioni, con più caffè.",
    "about": {"requirements": [], "screens": [], "criteria": []},
    "origin": {"kind": "OWNER", **NO_ORIGIN},
    "from_commit": None,
    "created_at": CREATED,
    "status": "OPEN",
    "closed_at": None,
    "note": None,
}
TASKS = [DONE_TASK, OLD_TASK, TEST_TASK, OWNER_TASK]
TASK_LINES = [
    "Carry out these tasks for the code. The owner of the project decided each of them.",
    "- TSK-002: Sostituire il campo libero della percentuale con tre pulsanti.",
    "  From: the decision on the commit 4cc9352",
    "  About: REQ-001, SCR-001",
    "- TSK-004: Mostrare un avviso accanto al campo del nome.",
    '  From: a finding of the twin "Addetti all\'accoglienza" on the acceptance tests: '
    '"Con il nome vuoto non compare nessun messaggio."',
    "  About: REQ-003, SCR-002, AC-002",
    "- TSK-006: Aggiungere la pagina delle informazioni, con più caffè.",
    "  From: written by the owner",
]
BUILD_LINE = (
    "Build the application as the approved requirements and design describe. If the "
    "repository already holds the application, bring it in line with them."
)


class Finder:
    def __init__(self) -> None:
        self.found: str | None = None
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, mode: int = 0, path: str | None = None) -> str | None:
        self.calls.append((name, path))
        return self.found


@pytest.fixture(autouse=True)
def finder(monkeypatch: pytest.MonkeyPatch) -> Finder:
    found = Finder()
    monkeypatch.setattr(code_run, "which", found)
    return found


@dataclass(frozen=True, slots=True)
class Bench:
    tmp_path: Path
    project: ProjectFolder
    claude: Path

    @property
    def root(self) -> Path:
        return self.project.root

    @property
    def code(self) -> Path:
        return self.root / ".orchestwin" / "code"

    def folder(self, name: str = FOLDER) -> Path:
        return self.code / name

    def runs(self) -> list[str]:
        if not self.code.is_dir():
            return []
        return sorted(path.name for path in self.code.iterdir() if path.is_dir())

    def prompt(self, name: str = FOLDER) -> str:
        return (self.folder(name) / "prompt.md").read_bytes().decode("utf-8")

    def document(self, *parts: str) -> dict[str, object]:
        return json.loads(self.root.joinpath(*parts).read_bytes().decode("utf-8"))

    def ut(
        self,
        *arguments: str,
        agent: ScriptedAgent | None = None,
        processes: ScriptedProcesses | None = None,
        answers: Sequence[str] = ("",),
        language: str = "en",
        variables: Mapping[str, str] | None = None,
        yes: bool = False,
        platform: str = "linux",
    ) -> Run:
        chosen = {"ORCHESTWIN_CLAUDE": str(self.claude)} if variables is None else variables
        options = ["--yes"] if yes else []
        return run_ut(
            ["--lang", language, *options, "code", *arguments],
            self.tmp_path,
            transport=NoNetwork(),
            answers=answers,
            variables=chosen,
            processes=processes,
            run_interactive=agent,
            platform=platform,
        )


def bench(
    tmp_path: Path,
    *,
    language: str | None = "it",
    tasks: Sequence[Mapping[str, object]] | None = TASKS,
    archive: bytes | None = None,
) -> Bench:
    project = link_folder(tmp_path / "project", language=language)
    unpack(valid_archive() if archive is None else archive, project.knowledge)
    if tasks is not None:
        path = project.knowledge / "state" / "state.json"
        document = json.loads(path.read_bytes().decode("utf-8"))
        document["tasks"] = list(tasks)
        path.write_bytes(json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
    claude = tmp_path / "tools" / "claude.exe"
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_bytes(b"")
    return Bench(tmp_path=tmp_path, project=project, claude=claude)


def repository(root: Path, *entries: str, errors: str = "", code: int = 0) -> ScriptedProcesses:
    processes = ScriptedProcesses()
    processes.expect(TOP, output=f"{root.as_posix()}\n")
    processes.expect(
        STATUS, status=code, output="".join(f"{entry}\0" for entry in entries), errors=errors
    )
    return processes


def sayer(language: str) -> Callable[..., str]:
    def say(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    return say


def section(text: str, heading: str) -> list[str]:
    lines = text.split("\n")
    start = lines.index(heading) + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return [line for line in lines[start:end] if line]


def heading(language: str) -> list[str]:
    title = sayer(language)("code.heading", name="Calcolo mancia")
    return [title, "=" * len(title)]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_run_hands_the_terminal_to_claude_and_reports_the_changes(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path, language="it")
    agent = ScriptedAgent(writes={"src/app.js": "export {};\n"})
    processes = repository(work.root, " M index.html", "?? src/", "?? .orchestwin/")
    say = sayer(language)

    run = work.ut(agent=agent, processes=processes, language=language)

    folder = work.folder()
    prompt = folder / "prompt.md"
    mcp = folder / "mcp.json"
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert run.output.splitlines() == [
        *heading(language),
        say("code.agent_claude", program=str(work.claude)),
        say("code.mode_interactive"),
        say("code.work_all_tasks", codes="TSK-002, TSK-004, TSK-006"),
        say("code.order", path=str(prompt)),
        say("code.own_account"),
        f"{say('code.confirm')} {say('common.yes_no_default_yes')} ",
        say("code.starting", program="claude.exe"),
        "",
        say("code.ended", elapsed="0 s"),
        say("code.changed", count=2),
        "- index.html",
        "- src/",
        say("code.next_steps"),
    ]
    assert agent.calls[0].arguments == (str(work.claude), LINE, "--mcp-config", str(mcp))
    assert agent.calls[0].folder == work.root
    assert agent.calls[0].variables == {
        "ORCHESTWIN_CONFIG_DIR": str(tmp_path / "config"),
        "ORCHESTWIN_CLAUDE": str(work.claude),
    }
    processes.assert_done()


def test_the_files_of_a_run_hold_the_work_order_the_twins_and_the_outcome(tmp_path: Path) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent(writes={"src/app.js": "export {};\n"})
    processes = repository(work.root, "?? src/")

    run = work.ut(agent=agent, processes=processes)

    folder = work.folder()
    content = (folder / "prompt.md").read_bytes()
    order = content.decode("utf-8")
    assert run.status == 0, run.errors
    assert work.runs() == [FOLDER]
    assert sorted(path.name for path in folder.iterdir()) == [
        "mcp.json",
        "outcome.json",
        "prompt.md",
    ]
    assert b"\r" not in content and content.endswith(b"\n")
    assert "più caffè".encode() in content
    assert order.startswith(
        "# Work order from OrchesTwin Studio\n\n"
        'You are working in the repository of the project "Calcolo mancia".'
    )
    assert section(order, "## What to do now") == TASK_LINES
    assert "is written in Italian." in order
    assert "Its paid tools are switched off: do not call them." in order
    assert work.document(".orchestwin", "code", FOLDER, "mcp.json") == {
        "mcpServers": {
            "orchestwin-twins": {
                "command": sys.executable,
                "args": ["-m", "orchestwin.cli", "--project-dir", work.root.as_posix(), "mcp"],
                "cwd": work.root.as_posix(),
            }
        }
    }
    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert list(outcome) == [
        "schema_version",
        "started_at",
        "finished_at",
        "seconds",
        "agent",
        "program",
        "headless",
        "model",
        "spend",
        "tasks",
        "request",
        "exit_status",
        "changed_files",
    ]
    assert outcome == {
        "schema_version": 1,
        "started_at": "2026-09-29T09:00:00+00:00",
        "finished_at": "2026-09-29T09:00:00+00:00",
        "seconds": 0.0,
        "agent": "claude",
        "program": "claude.exe",
        "headless": False,
        "model": None,
        "spend": False,
        "tasks": ["TSK-002", "TSK-004", "TSK-006"],
        "request": None,
        "exit_status": 0,
        "changed_files": ["src/"],
    }
    latest = work.document(".orchestwin", "code", "latest.json")
    assert list(latest) == [
        "schema_version",
        "folder",
        "started_at",
        "finished_at",
        "agent",
        "exit_status",
        "changed_files",
    ]
    assert latest == {
        "schema_version": 1,
        "folder": FOLDER,
        "started_at": "2026-09-29T09:00:00+00:00",
        "finished_at": "2026-09-29T09:00:00+00:00",
        "agent": "claude",
        "exit_status": 0,
        "changed_files": ["src/"],
    }
    assert (work.code / ".gitignore").read_bytes() == b"*\n"
    assert work.document(".orchestwin", "code.json") == {
        "schema_version": 1,
        "agent": "claude",
        "command": None,
        "model": None,
        "headless": False,
    }


@pytest.mark.parametrize(
    ("arguments", "tasks", "work_key", "codes", "expected"),
    [
        (
            ["--task", "tsk-006,TSK-004"],
            TASKS,
            "code.work_tasks",
            "TSK-004, TSK-006",
            TASK_LINES[:1] + TASK_LINES[4:],
        ),
        ([], TASKS, "code.work_all_tasks", "TSK-002, TSK-004, TSK-006", TASK_LINES),
        (
            ["Aggiungi", "un pulsante per azzerare i campi"],
            TASKS,
            "code.work_request",
            None,
            ["The owner asks:", "> Aggiungi un pulsante per azzerare i campi"],
        ),
        (
            ["--task", "TSK-002 TSK-006", "Azzera i campi"],
            TASKS,
            "code.work_tasks_request",
            "TSK-002, TSK-006",
            [
                *TASK_LINES[:4],
                *TASK_LINES[7:],
                "The owner asks:",
                "> Azzera i campi",
            ],
        ),
        ([], [DONE_TASK], "code.work_build", None, [BUILD_LINE]),
        ([], None, "code.work_build", None, [BUILD_LINE]),
    ],
)
@pytest.mark.parametrize("language", LANGUAGES)
def test_the_work_is_said_in_one_line_and_written_in_the_work_order(
    tmp_path: Path,
    arguments: list[str],
    tasks: list[dict[str, object]] | None,
    work_key: str,
    codes: str | None,
    expected: list[str],
    language: str,
) -> None:
    work = bench(tmp_path, tasks=tasks)
    say = sayer(language)

    run = work.ut(*arguments, "--dry-run", language=language)

    line = say(work_key) if codes is None else say(work_key, codes=codes)
    assert run.status == 0, run.errors
    assert run.output.splitlines()[4] == line
    assert section(work.prompt(), "## What to do now") == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_dry_run_writes_the_files_prints_the_words_and_starts_nothing(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()
    say = sayer(language)

    run = work.ut("--dry-run", "Azzera i campi", agent=agent, answers=(), language=language)

    folder = work.folder()
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert run.output.splitlines() == [
        *heading(language),
        say("code.agent_claude", program=str(work.claude)),
        say("code.mode_interactive"),
        say("code.work_request"),
        say("code.order", path=str(folder / "prompt.md")),
        say("code.own_account"),
        say("code.words"),
        f"  {work.claude}",
        f"  {LINE}",
        "  --mcp-config",
        f"  {folder / 'mcp.json'}",
        say("code.dry_run", folder=str(folder)),
    ]
    assert agent.calls == []
    assert sorted(path.name for path in folder.iterdir()) == ["mcp.json", "prompt.md"]
    assert not (work.code / "latest.json").exists()
    assert (work.root / ".orchestwin" / "code.json").is_file()


@pytest.mark.parametrize("language", LANGUAGES)
def test_headless_claude_gets_the_model_and_the_budget(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()
    say = sayer(language)

    run = work.ut(
        "--headless",
        "--model",
        "opus",
        "--max-agent-usd",
        "2.5",
        "--task",
        "TSK-004",
        agent=agent,
        language=language,
    )

    folder = work.folder()
    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[2:8] == [
        say("code.agent_claude", program=str(work.claude)),
        say("code.mode_headless_claude"),
        say("code.model", model="opus"),
        say("code.budget", usd="2,50" if language == "it" else "2.50"),
        say("code.work_tasks", codes="TSK-004"),
        say("code.order", path=str(folder / "prompt.md")),
    ]
    assert agent.calls[0].arguments == (
        str(work.claude),
        "--print",
        LINE,
        "--mcp-config",
        str(folder / "mcp.json"),
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "mcp__orchestwin-twins",
        "--model",
        "opus",
        "--max-budget-usd",
        "2.50",
    )
    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert (outcome["headless"], outcome["model"], outcome["tasks"]) == (True, "opus", ["TSK-004"])


@pytest.mark.parametrize(
    ("language", "sentence"),
    [
        ("en", "The most the agent may spend in this run: 0.50 USD, on your Claude Code account."),
        (
            "it",
            "Spesa massima dell'agente in questa esecuzione: 0,50 USD, sul tuo account di "
            "Claude Code.",
        ),
    ],
)
def test_the_budget_is_written_as_the_language_writes_amounts_and_claude_gets_a_point(
    tmp_path: Path, language: str, sentence: str
) -> None:
    work = bench(tmp_path)

    run = work.ut("--headless", "--max-agent-usd", "0.5", "--dry-run", language=language)

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[4] == sentence
    assert lines[-3:-1] == ["  --max-budget-usd", "  0.50"]


def test_claude_is_found_through_the_path_when_the_variable_is_missing(
    tmp_path: Path, finder: Finder
) -> None:
    work = bench(tmp_path)
    finder.found = str(tmp_path / "bin" / "claude")
    agent = ScriptedAgent()

    run = work.ut(agent=agent, variables={"PATH": str(tmp_path / "bin")})

    assert run.status == 0, run.errors
    assert agent.calls[0].arguments[0] == str(tmp_path / "bin" / "claude")
    assert finder.calls == [("claude", str(tmp_path / "bin"))]


def test_the_variable_wins_over_the_path(tmp_path: Path, finder: Finder) -> None:
    work = bench(tmp_path)
    finder.found = str(tmp_path / "bin" / "claude")
    agent = ScriptedAgent()

    run = work.ut(agent=agent)

    assert run.status == 0, run.errors
    assert agent.calls[0].arguments[0] == str(work.claude)
    assert finder.calls == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_claude_not_found_names_the_variable_and_the_custom_agent(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)

    run = work.ut(variables={}, language=language)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == (
        sayer(language)("code.errors.CODE_AGENT_NOT_FOUND", variable="ORCHESTWIN_CLAUDE") + "\n"
    )
    assert "`--agent custom --command`" in run.errors
    assert work.runs() == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_custom_command_gets_every_placeholder_filled(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()
    say = sayer(language)
    command = "agent --order {prompt_file} --say {prompt_line} --mcp={mcp_config} --in {project}"

    run = work.ut(
        "--agent", "custom", "--command", command, agent=agent, language=language, yes=True
    )

    folder = work.folder()
    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert lines[2] == say("code.agent_custom", program="agent")
    assert lines[3] == say("code.mode_interactive")
    assert say("code.starting", program="agent") in lines
    assert agent.calls[0].arguments == (
        "agent",
        "--order",
        str(folder / "prompt.md"),
        "--say",
        LINE,
        f"--mcp={folder / 'mcp.json'}",
        "--in",
        str(work.root),
    )
    assert work.document(".orchestwin", "code.json")["command"] == [
        "agent",
        "--order",
        "{prompt_file}",
        "--say",
        "{prompt_line}",
        "--mcp={mcp_config}",
        "--in",
        "{project}",
    ]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_custom_command_on_windows_keeps_its_backslashes(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()

    run = work.ut(
        "--command",
        r'"C:\Program Files\Agent\agent.exe" --read {prompt_file}',
        "--headless",
        agent=agent,
        platform="win32",
        language=language,
    )

    lines = run.output.splitlines()
    assert run.status == 0, run.errors
    assert agent.calls[0].arguments == (
        r"C:\Program Files\Agent\agent.exe",
        "--read",
        str(work.folder() / "prompt.md"),
    )
    assert lines[2] == messages.text(
        "code.agent_custom", language, program=r"C:\Program Files\Agent\agent.exe"
    )
    assert lines[3] == messages.text("code.mode_headless", language)
    assert work.document(".orchestwin", "code.json")["command"] == [
        r"C:\Program Files\Agent\agent.exe",
        "--read",
        "{prompt_file}",
    ]


def test_the_saved_settings_are_used_by_the_next_runs(tmp_path: Path) -> None:
    work = bench(tmp_path)

    first = work.ut("--agent", "custom", "--command", "agent {prompt_file}", "--dry-run")
    second = work.ut("--dry-run")
    after_custom = work.document(".orchestwin", "code.json")
    third = work.ut("--agent", "claude", "--model", "opus", "--headless", "--dry-run")
    after_claude = work.document(".orchestwin", "code.json")
    fourth = work.ut("--dry-run")
    fifth = work.ut("--model", "", "--dry-run")
    last = work.document(".orchestwin", "code.json")

    assert [run.status for run in (first, second, third, fourth, fifth)] == [0, 0, 0, 0, 0]
    assert second.output.splitlines()[-3:-1] == [
        "  agent",
        f"  {work.folder(FOLDER + '-2') / 'prompt.md'}",
    ]
    assert after_custom == {
        "schema_version": 1,
        "agent": "custom",
        "command": ["agent", "{prompt_file}"],
        "model": None,
        "headless": False,
    }
    assert after_claude == {
        "schema_version": 1,
        "agent": "claude",
        "command": ["agent", "{prompt_file}"],
        "model": "opus",
        "headless": True,
    }
    assert "  --print" not in fourth.output.splitlines()
    assert fourth.output.splitlines()[-3:-1] == ["  --model", "  opus"]
    assert "  --model" not in fifth.output.splitlines()
    assert last["model"] is None
    assert work.runs() == [FOLDER, *(f"{FOLDER}-{number}" for number in range(2, 6))]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    ("arguments", "status", "key", "values"),
    [
        (["--agent", "custom"], 2, "code.errors.CODE_COMMAND_REQUIRED", {}),
        (["--command", "   "], 2, "code.errors.CODE_COMMAND_INVALID.EMPTY", {}),
        (["--command", 'agent "{prompt_file}'], 2, "code.errors.CODE_COMMAND_INVALID.QUOTES", {}),
        (
            ["--command", "agent --model {model}"],
            2,
            "code.errors.CODE_COMMAND_INVALID.PLACEHOLDER",
            {"placeholder": "{model}"},
        ),
        (
            ["--agent", "claude", "--command", "agent"],
            2,
            "code.errors.CODE_COMMAND_NEEDS_CUSTOM",
            {},
        ),
        (["--max-agent-usd", "2"], 2, "code.errors.CODE_BUDGET_NEEDS_HEADLESS", {}),
        (
            ["--command", "agent", "--headless", "--max-agent-usd", "2"],
            2,
            "code.errors.CODE_BUDGET_NEEDS_HEADLESS",
            {},
        ),
        (["--headless", "--max-agent-usd", "0"], 2, "code.errors.CODE_MAX_USD_INVALID", {}),
        (["--headless", "--max-agent-usd", "nan"], 2, "code.errors.CODE_MAX_USD_INVALID", {}),
        (["--headless", "--max-agent-usd", "-3"], 2, "code.errors.CODE_MAX_USD_INVALID", {}),
        (
            ["--task", "TSK-001,tsk-404"],
            2,
            "code.errors.CODE_TASK_UNKNOWN",
            {"codes": "TSK-001, TSK-404"},
        ),
    ],
)
def test_options_that_cannot_be_used_are_refused_before_anything_starts(
    tmp_path: Path,
    arguments: list[str],
    status: int,
    key: str,
    values: dict[str, str],
    language: str,
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()

    run = work.ut(*arguments, agent=agent, language=language)

    assert run.status == status
    assert run.output == ""
    assert run.errors == messages.text(key, language, **values) + "\n"
    assert agent.calls == []
    assert work.runs() == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_design_must_be_approved_in_the_local_folder(tmp_path: Path, language: str) -> None:
    partial = bench(
        tmp_path / "partial", tasks=None, archive=partial_archive(through="requirements")
    )
    empty = Bench(
        tmp_path=tmp_path / "empty",
        project=link_folder(tmp_path / "empty" / "project"),
        claude=partial.claude,
    )
    expected = messages.text("code.errors.CODE_DESIGN_REQUIRED", language) + "\n"

    runs = [place.ut(language=language) for place in (partial, empty)]

    assert [(run.status, run.output, run.errors) for run in runs] == [(1, "", expected)] * 2
    assert partial.runs() == [] and empty.runs() == []
    assert not (partial.root / ".orchestwin" / "code.json").exists()


def test_a_folder_that_is_not_linked_is_refused(tmp_path: Path) -> None:
    run = run_ut(["code"], tmp_path, transport=NoNetwork(), working_directory=tmp_path / "away")

    assert run.status == 6
    assert "not linked" in run.errors


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(
    ("answers", "status", "key"),
    [
        (["n"], 5, "code.errors.SPENDING_REFUSED"),
        ([], 1, "code.errors.INPUT_CLOSED"),
    ],
)
def test_the_agent_starts_only_after_a_yes(
    tmp_path: Path, language: str, answers: list[str], status: int, key: str
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()

    run = work.ut(agent=agent, answers=answers, language=language)

    assert run.status == status
    assert run.errors == messages.text(key, language) + "\n"
    assert agent.calls == []
    assert (work.folder() / "prompt.md").is_file()
    assert not (work.folder() / "outcome.json").exists()


def test_yes_starts_the_agent_without_the_question(tmp_path: Path) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()

    run = work.ut(agent=agent, answers=(), yes=True)

    assert run.status == 0, run.errors
    assert len(agent.calls) == 1
    assert not any(line.startswith("Start the agent now?") for line in run.output.splitlines())


@pytest.mark.parametrize("language", LANGUAGES)
def test_spend_gives_the_agent_the_paid_tools_and_says_so(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)

    run = work.ut("--spend", "--dry-run", language=language)

    mcp = work.document(".orchestwin", "code", FOLDER, "mcp.json")
    assert run.status == 0, run.errors
    assert sayer(language)("code.own_account_spend") in run.output.splitlines()
    assert mcp["mcpServers"]["orchestwin-twins"]["args"][-1] == "--spend"
    assert (
        "Its paid tools (asking a twin, reviewing the changes, running the acceptance tests) "
        "spend on the owner's Studio: use them only when the work needs them." in work.prompt()
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_without_git_the_changes_cannot_be_listed(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    say = sayer(language)

    run = work.ut(agent=ScriptedAgent(), language=language)

    assert run.status == 0, run.errors
    assert run.output.splitlines()[-3:] == [
        say("code.ended", elapsed="0 s"),
        say("code.changes_no_git"),
        say("code.next_steps"),
    ]
    assert work.document(".orchestwin", "code", "latest.json")["changed_files"] is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_failure_of_git_and_a_clean_tree_are_said(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    say = sayer(language)
    broken = repository(work.root, code=128, errors="fatal: index file corrupt")
    clean = repository(work.root)

    failed = work.ut(agent=ScriptedAgent(), processes=broken, language=language)
    nothing = work.ut(agent=ScriptedAgent(), processes=clean, language=language)

    assert say("code.changes_failed", detail="fatal: index file corrupt") in failed.output
    assert say("code.changed_none") in nothing.output.splitlines()
    assert work.document(".orchestwin", "code", "latest.json")["changed_files"] == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_knowledge_folder_touched_by_the_agent_gets_a_warning(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent(
        writes={"orchestwin/ORCHESTWIN.md": "# Edited\n", "src/app.js": "export {};\n"}
    )
    processes = repository(work.root, " M orchestwin/ORCHESTWIN.md", "?? src/")
    say = sayer(language)

    run = work.ut(agent=agent, processes=processes, language=language)

    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert run.status == 0, run.errors
    assert run.output.splitlines()[-5:] == [
        say("code.ended", elapsed="0 s"),
        say("code.changed", count=1),
        "- src/",
        say("code.knowledge_touched", folder="orchestwin"),
        say("code.next_steps"),
    ]
    assert outcome["changed_files"] == ["src/"]
    processes.assert_done()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_knowledge_folder_published_by_ut_is_not_a_change_of_the_agent(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent(writes={"index.html": "<p>Mancia</p>\n"})
    processes = repository(work.root, " M index.html", "?? orchestwin/", "?? .orchestwin/")
    say = sayer(language)

    run = work.ut(agent=agent, processes=processes, language=language)

    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert run.status == 0, run.errors
    assert run.output.splitlines()[-4:] == [
        say("code.ended", elapsed="0 s"),
        say("code.changed", count=1),
        "- index.html",
        say("code.next_steps"),
    ]
    assert say("code.knowledge_touched", folder="orchestwin") not in run.output
    assert outcome["changed_files"] == ["index.html"]
    processes.assert_done()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_long_list_of_changes_is_cut_and_the_outcome_keeps_them_all(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)
    names = [f"src/file{number:02d}.js" for number in range(45)]
    processes = repository(work.root, *(f"?? {name}" for name in names))

    run = work.ut(agent=ScriptedAgent(), processes=processes, language=language)

    lines = run.output.splitlines()
    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert run.status == 0, run.errors
    assert lines[-43] == messages.text("code.changed", language, count=45)
    assert lines[-42:-2] == [f"- {name}" for name in names[:40]]
    assert lines[-2] == messages.text(
        "code.changed_more", language, count=5, path=str(work.folder() / "outcome.json")
    )
    assert outcome["changed_files"] == names


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_agent_that_fails_ends_the_command_with_one(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)
    say = sayer(language)

    run = work.ut(agent=ScriptedAgent(status=3), language=language)

    lines = run.output.splitlines()
    assert run.status == 1
    assert say("code.ended_status", status=3, elapsed="0 s") in lines
    assert lines[-1] == say("code.next_steps_failed", folder=str(work.folder()))
    assert say("code.next_steps") not in lines
    assert work.document(".orchestwin", "code", "latest.json")["exit_status"] == 3


@pytest.mark.parametrize("language", LANGUAGES)
def test_after_a_failure_the_changed_files_stay_listed_and_the_run_folder_is_named(
    tmp_path: Path, language: str
) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent(status=2, writes={"src/app.js": "export {};\n"})
    processes = repository(work.root, " M index.html", "?? src/")
    say = sayer(language)

    run = work.ut(agent=agent, processes=processes, language=language)

    folder = work.folder()
    assert run.status == 1
    assert run.errors == ""
    assert run.output.splitlines()[-5:] == [
        say("code.ended_status", status=2, elapsed="0 s"),
        say("code.changed", count=2),
        "- index.html",
        "- src/",
        say("code.next_steps_failed", folder=str(folder)),
    ]
    assert sorted(path.name for path in folder.iterdir()) == [
        "mcp.json",
        "outcome.json",
        "prompt.md",
    ]
    processes.assert_done()


def test_ctrl_c_during_the_agent_ends_with_130_after_the_outcome(tmp_path: Path) -> None:
    work = bench(tmp_path)

    run = work.ut(agent=ScriptedAgent(interrupt=True), language="it")

    outcome = work.document(".orchestwin", "code", FOLDER, "outcome.json")
    assert run.status == 130
    assert run.errors == "Interrotto.\n"
    assert (outcome["exit_status"], outcome["changed_files"]) == (130, None)
    assert work.document(".orchestwin", "code", "latest.json")["exit_status"] == 130


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_agent_that_cannot_start_is_named(tmp_path: Path, language: str) -> None:
    work = bench(tmp_path)

    run = work.ut(language=language)

    assert run.status == 1
    assert run.errors == (
        messages.text(
            "code.errors.CODE_AGENT_NOT_STARTED",
            language,
            program="claude.exe",
            detail="no agent runs in the tests",
        )
        + "\n"
    )
    assert not (work.folder() / "outcome.json").exists()


def test_the_command_never_asks_the_studio_and_works_signed_out(tmp_path: Path) -> None:
    work = bench(tmp_path)
    agent = ScriptedAgent()

    run = work.ut(agent=agent, yes=True)

    assert run.status == 0, run.errors
    assert not (tmp_path / "config" / "sessions.json").exists()


def test_the_help_lists_the_two_new_commands(tmp_path: Path) -> None:
    run = run_ut(["--lang", "en", "--help"], tmp_path, transport=NoNetwork())
    words = " ".join(run.output.split())

    assert run.status == 0
    assert "tasks Show and change the tasks for the code" in words
    assert "code Hand the development to an external coding agent" in words


def test_every_sentence_of_the_command_is_used() -> None:
    flows = Path(code_run.__file__).parent
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            flows / "code_run.py",
            flows / "code_order.py",
            flows / "code_agents.py",
            flows.parent / "commands" / "code.py",
            flows.parent / "environment.py",
        )
    )
    built_elsewhere = {"code.help", "code.errors.INPUT_CLOSED"}
    keys = [key for key in messages.FILES["code"] if key not in built_elsewhere]
    words = [part for key in keys if key.startswith("code.errors.") for part in key.split(".")[2:]]

    assert [
        key for key in keys if not key.startswith("code.errors.") and f'"{key}"' not in sources
    ] == []
    assert [word for word in words if f'"{word}"' not in sources] == []
