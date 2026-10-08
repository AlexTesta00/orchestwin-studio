from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import code_run
from orchestwin.cli.flows.changes import git_command
from orchestwin.cli.flows.code_order import Task, Work
from orchestwin.cli.flows.code_run import (
    Changes,
    CodeSettings,
    Launch,
    agent_arguments,
    changed_files,
    chosen_settings,
    fingerprint,
    mcp_document,
    read_settings,
    run_folder,
    settings_from,
    start,
    write_run_files,
    write_settings,
)
from orchestwin.cli.folder import unpack
from orchestwin.cli.mcp.configs import snippet
from orchestwin.cli.project import ProjectFolder

from .support.agents import AgentCall, ScriptedAgent
from .support.folders import valid_archive
from .support.processes import ScriptedProcesses
from .support.terminal import START, Terminal, command_context, link_folder, terminal
from .support.transports import NoNetwork

TOP = git_command("rev-parse", "--show-toplevel")
STATUS = git_command(*code_run.STATUS_ARGUMENTS)
LINE = (
    "Read the file .orchestwin/code/20260929-090000/prompt.md of this repository and carry out "
    "the work order it contains."
)
OUTCOME_KEYS = [
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
    "kind",
    "design_from",
    "design_version_number",
]
LATEST_KEYS = [
    "schema_version",
    "folder",
    "started_at",
    "finished_at",
    "agent",
    "exit_status",
    "changed_files",
    "kind",
    "design_version_number",
]


def porcelain(*entries: str) -> str:
    return "".join(f"{entry}\0" for entry in entries)


def repository(
    root: Path,
    status: str = "",
    *,
    code: int = 0,
    errors: str = "",
    interrupt: bool = False,
) -> ScriptedProcesses:
    processes = ScriptedProcesses()
    processes.expect(TOP, output=f"{root.as_posix()}\n")
    processes.expect(STATUS, status=code, output=status, errors=errors, interrupt=interrupt)
    return processes


def linked(tmp_path: Path) -> ProjectFolder:
    project = link_folder(tmp_path / "project", language="it")
    unpack(valid_archive(), project.knowledge)
    return project


def context_of(
    tmp_path: Path,
    *,
    processes: ScriptedProcesses | None = None,
    agent: ScriptedAgent | None = None,
    variables: Mapping[str, str] | None = None,
    seconds: float = 0.0,
) -> tuple[CommandContext, Terminal]:
    clocks: list[Terminal] = []

    def timed(arguments: Sequence[str], folder: Path, values: Mapping[str, str]) -> int:
        clocks[0].clock.advance(seconds)
        return (agent or ScriptedAgent())(arguments, folder, values)

    bundle = terminal(
        tmp_path,
        transport=NoNetwork(),
        processes=processes,
        run_interactive=timed,
        variables=variables,
    )
    clocks.append(bundle)
    return command_context(bundle.environment), bundle


def launch_of(
    project: ProjectFolder,
    arguments: Sequence[str] = ("agent", "--go"),
    *,
    settings: CodeSettings | None = None,
    work: Work | None = None,
    spend: bool = False,
    kind: str = code_run.CODE_KIND,
    design_from: int | None = None,
    design_version_number: int | None = None,
) -> Launch:
    files = write_run_files(project, START, "order\n", spend=spend, python="python")
    return Launch(
        project=project,
        files=files,
        arguments=tuple(arguments),
        settings=CodeSettings(agent="custom", command=("agent",)) if settings is None else settings,
        work=Work() if work is None else work,
        spend=spend,
        kind=kind,
        design_from=design_from,
        design_version_number=design_version_number,
    )


def read(path: Path) -> dict[str, object]:
    return json.loads(path.read_bytes().decode("utf-8"))


def refusal(action) -> CliError:
    with pytest.raises(CliError) as caught:
        action()
    return caught.value


def test_the_settings_keep_the_keys_of_the_contract_and_read_back(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    settings = CodeSettings(
        agent="custom", command=("agent", "{prompt_file}"), model="opus", headless=True
    )

    path = write_settings(project, settings)
    content = path.read_bytes()

    assert path == project.root / ".orchestwin" / "code.json"
    assert list(read(path)) == ["schema_version", "agent", "command", "model", "headless"]
    assert read(path) == {
        "schema_version": 1,
        "agent": "custom",
        "command": ["agent", "{prompt_file}"],
        "model": "opus",
        "headless": True,
    }
    assert b"\r\n" not in content and content.endswith(b"}\n")
    assert read_settings(project) == settings
    assert read_settings(link_folder(tmp_path / "other")) is None


@pytest.mark.parametrize(
    "document",
    [
        None,
        [],
        {"schema_version": 2, "agent": "claude"},
        {"schema_version": 1, "agent": "other"},
        {"schema_version": 1, "agent": "custom", "command": "agent {prompt_file}"},
        {"schema_version": 1, "agent": "custom", "command": ["agent", 3]},
        {"schema_version": 1, "agent": "claude", "model": 5},
        {"schema_version": 1, "agent": "claude", "headless": "yes"},
    ],
)
def test_settings_that_do_not_read_are_left_aside(document: object) -> None:
    assert settings_from(document) is None


def test_settings_with_missing_keys_take_the_defaults() -> None:
    assert settings_from({"schema_version": 1, "agent": "claude"}) == CodeSettings()
    assert settings_from({"schema_version": 1, "agent": "claude", "model": "  "}) == CodeSettings()


def test_the_agent_is_the_option_else_the_saved_one_else_claude() -> None:
    saved = CodeSettings(agent="custom", command=("agent",), model="opus", headless=True)

    def chosen(earlier: CodeSettings | None, agent: str | None) -> CodeSettings:
        return chosen_settings(
            earlier, agent=agent, command=None, model=None, headless=False, platform="linux"
        )

    assert chosen(None, None) == CodeSettings()
    assert chosen(saved, None) == CodeSettings(agent="custom", command=("agent",), model="opus")
    assert chosen(saved, "claude") == CodeSettings(agent="claude", command=("agent",), model="opus")


def test_a_command_makes_the_agent_custom_and_replaces_the_saved_one() -> None:
    saved = CodeSettings(agent="claude", command=("old",))

    chosen = chosen_settings(
        saved,
        agent=None,
        command=r"new --file {prompt_file} C:\work",
        model=None,
        headless=True,
        platform="win32",
    )

    assert chosen == CodeSettings(
        agent="custom", command=("new", "--file", "{prompt_file}", r"C:\work"), headless=True
    )


def test_the_command_is_refused_with_the_agent_claude() -> None:
    error = refusal(
        lambda: chosen_settings(
            None, agent="claude", command="agent", model=None, headless=False, platform="linux"
        )
    )

    assert (error.code, error.status) == ("CODE_COMMAND_NEEDS_CUSTOM", 2)


@pytest.mark.parametrize(
    ("saved", "code"),
    [
        (None, "CODE_COMMAND_REQUIRED"),
        (CodeSettings(agent="claude"), "CODE_COMMAND_REQUIRED"),
        (CodeSettings(agent="custom", command=("agent", "{model}")), "CODE_COMMAND_INVALID"),
        (CodeSettings(agent="custom", command=("",)), "CODE_COMMAND_INVALID"),
    ],
)
def test_the_custom_agent_needs_a_command_that_ut_can_use(
    saved: CodeSettings | None, code: str
) -> None:
    error = refusal(
        lambda: chosen_settings(
            saved, agent="custom", command=None, model=None, headless=False, platform="linux"
        )
    )

    assert (error.code, error.status) == (code, 2)


def test_the_model_is_kept_until_an_empty_name_clears_it() -> None:
    saved = CodeSettings(model="opus", headless=True)

    def chosen(model: str | None) -> CodeSettings:
        return chosen_settings(
            saved, agent=None, command=None, model=model, headless=False, platform="linux"
        )

    assert chosen(None) == CodeSettings(model="opus")
    assert chosen(" sonnet ").model == "sonnet"
    assert chosen("  ").model is None


def test_run_folders_are_named_by_the_utc_start_and_never_reused(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    code = project.root / ".orchestwin" / "code"
    moment = datetime(2026, 9, 29, 11, 0, 5, tzinfo=timezone(timedelta(hours=2)))

    first = run_folder(project, moment)
    written = (code / ".gitignore").read_bytes()
    (code / ".gitignore").write_bytes(b"kept\n")
    second = run_folder(project, moment)
    third = run_folder(project, moment)

    assert [first.name, second.name, third.name] == [
        "20260929-090005",
        "20260929-090005-2",
        "20260929-090005-3",
    ]
    assert all(folder.is_dir() and folder.parent == code for folder in (first, second, third))
    assert written == b"*\n"
    assert (code / ".gitignore").read_bytes() == b"kept\n"


def test_the_mcp_configuration_is_the_server_of_ut_mcp_started_by_the_python_of_ut(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"

    free = mcp_document(root, spend=False, python="python-of-ut")
    paid = mcp_document(root, spend=True, python="python-of-ut")
    described = snippet("claude-code", root, spend=True)["mcpServers"]["orchestwin-twins"]

    assert free == {
        "mcpServers": {
            "orchestwin-twins": {
                "command": "python-of-ut",
                "args": ["-m", "orchestwin.cli", "--project-dir", root.as_posix(), "mcp"],
                "cwd": root.as_posix(),
            }
        }
    }
    assert list(free["mcpServers"]["orchestwin-twins"]) == ["command", "args", "cwd"]
    assert paid["mcpServers"]["orchestwin-twins"]["args"] == [
        "-m",
        "orchestwin.cli",
        *described["args"],
    ]
    assert paid["mcpServers"]["orchestwin-twins"]["args"][-1] == "--spend"


def test_the_files_of_a_run_are_utf8_with_newlines_and_the_ignore_file(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")

    files = write_run_files(
        project, START, "# Ordine\nPiù caffè\n", spend=True, python=sys.executable
    )

    assert files.folder == project.root / ".orchestwin" / "code" / "20260929-090000"
    assert files.prompt.read_bytes() == "# Ordine\nPiù caffè\n".encode()
    assert read(files.mcp) == mcp_document(project.root, spend=True, python=sys.executable)
    assert b"\r\n" not in files.mcp.read_bytes()
    assert files.relative_prompt == ".orchestwin/code/20260929-090000/prompt.md"
    assert (files.folder.parent / ".gitignore").read_bytes() == b"*\n"


def test_the_arguments_of_claude_and_of_a_custom_command(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    files = write_run_files(project, START, "order\n", spend=False, python="python")
    custom = CodeSettings(
        agent="custom",
        command=("agent", "--order={prompt_file}", "{prompt_line}", "{mcp_config}", "{project}"),
    )

    claude = agent_arguments(
        project, CodeSettings(model="opus"), files, program=tmp_path / "claude", max_usd=None
    )
    own = agent_arguments(project, custom, files, program=None, max_usd=None)

    assert claude == (
        str(tmp_path / "claude"),
        LINE,
        "--mcp-config",
        str(files.mcp),
        "--model",
        "opus",
    )
    assert own == ("agent", f"--order={files.prompt}", LINE, str(files.mcp), str(project.root))
    with pytest.raises(ValueError):
        agent_arguments(project, CodeSettings(), files, program=None, max_usd=None)


def test_claude_is_looked_for_with_the_finder_of_the_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str | None]] = []

    def finder(name: str, mode: int = 0, path: str | None = None) -> str | None:
        seen.append((name, path))
        return str(tmp_path / "claude")

    monkeypatch.setattr(code_run, "which", finder)
    context, _ = context_of(tmp_path, variables={"PATH": "somewhere"})

    assert code_run.claude_program(context) == tmp_path / "claude"
    assert seen == [("claude", "somewhere")]


def test_the_changed_files_leave_out_the_local_folder_and_the_knowledge_folder(
    tmp_path: Path,
) -> None:
    project = link_folder(tmp_path / "project")
    processes = repository(
        project.root,
        porcelain(
            " M src/app.js",
            "?? .orchestwin/",
            "R  src/new.js",
            "src/old.js",
            " M orchestwin/ORCHESTWIN.md",
            "?? orchestwin/state/",
            "?? orchestwin-notes.md",
            "?? docs/",
        ),
    )
    context, _ = context_of(tmp_path, processes=processes)

    found = changed_files(context, project)

    assert found == Changes(files=("src/app.js", "src/new.js", "orchestwin-notes.md", "docs/"))
    assert [call.folder for call in processes.calls] == [project.root, project.root]
    processes.assert_done()


def test_a_project_in_a_subfolder_leaves_out_only_its_own_folders(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    project = link_folder(repository_root / "app")
    processes = repository(
        repository_root,
        porcelain(
            " M app/.orchestwin/code.json",
            " M .orchestwin/notes.json",
            " M app/src/app.js",
            "?? app/orchestwin/",
            " M orchestwin/notes.md",
        ),
    )
    context, _ = context_of(tmp_path, processes=processes)

    found = changed_files(context, project)

    assert found.files == (".orchestwin/notes.json", "app/src/app.js", "orchestwin/notes.md")


def test_a_knowledge_folder_with_another_name_is_left_out_by_its_name(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    project.update_link(knowledge_folder="conoscenza")
    processes = repository(
        project.root,
        porcelain("?? conoscenza/", " M orchestwin/ORCHESTWIN.md", " M src/app.js"),
    )
    context, _ = context_of(tmp_path, processes=processes)

    found = changed_files(context, project)

    assert found == Changes(files=("orchestwin/ORCHESTWIN.md", "src/app.js"))


def test_a_link_that_cannot_be_read_leaves_out_only_the_local_folder(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    (project.local / "project.json").write_bytes(b"{}\n")
    processes = repository(
        project.root,
        porcelain("?? .orchestwin/", " M orchestwin/ORCHESTWIN.md", " M src/app.js"),
    )
    context, _ = context_of(tmp_path, processes=processes)

    found = changed_files(context, project)

    assert found == Changes(files=("orchestwin/ORCHESTWIN.md", "src/app.js"))


def test_without_git_or_outside_a_repository_the_list_is_null(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    outside = ScriptedProcesses().expect(TOP, status=128, errors="fatal: not a git repository")
    missing, _ = context_of(tmp_path)
    elsewhere, _ = context_of(tmp_path, processes=outside)

    assert changed_files(missing, project) == Changes(files=None, problem="NO_REPOSITORY")
    assert changed_files(elsewhere, project) == Changes(files=None, problem="NO_REPOSITORY")


def test_a_failure_of_git_is_named(tmp_path: Path) -> None:
    project = link_folder(tmp_path / "project")
    processes = repository(project.root, code=128, errors="fatal: index file corrupt\nmore")
    context, _ = context_of(tmp_path, processes=processes)

    assert changed_files(context, project) == Changes(
        files=None, problem="fatal: index file corrupt"
    )


def test_the_fingerprint_follows_the_content_of_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "orchestwin"
    missing = fingerprint(folder)
    (folder / "design").mkdir(parents=True)
    (folder / "design" / "design.md").write_bytes(b"one")
    first = fingerprint(folder)
    same = fingerprint(folder)
    (folder / "design" / "design.md").write_bytes(b"two")
    changed = fingerprint(folder)
    (folder / "design" / "design.md").write_bytes(b"one")
    back = fingerprint(folder)
    (folder / "notes.md").write_bytes(b"")
    added = fingerprint(folder)

    assert missing is None
    assert first == same == back
    assert len({first, changed, added}) == 3


def test_the_agent_starts_in_the_root_with_the_variables_and_its_outcome_is_written(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    agent = ScriptedAgent(status=0, writes={"src/app.js": "export {};\n"})
    processes = repository(project.root, porcelain("?? src/"))
    context, bundle = context_of(
        tmp_path, processes=processes, agent=agent, variables={"A": "1"}, seconds=75.5
    )
    work = Work(tasks=(Task(code="TSK-004", text="Avviso"),), request="Azzera i campi")
    launch = launch_of(project, work=work, spend=True)

    finished = start(context, launch)
    outcome = read(launch.files.folder / "outcome.json")
    latest = read(launch.files.folder.parent / "latest.json")

    assert agent.calls == [
        AgentCall(
            ("agent", "--go"),
            project.root,
            {"ORCHESTWIN_CONFIG_DIR": str(tmp_path / "config"), "A": "1"},
        )
    ]
    assert (project.root / "src" / "app.js").is_file()
    assert finished.changes == Changes(files=("src/",))
    assert finished.touched is False
    assert list(outcome) == OUTCOME_KEYS
    assert outcome == {
        "schema_version": 1,
        "started_at": "2026-09-29T09:00:00+00:00",
        "finished_at": "2026-09-29T09:01:15+00:00",
        "seconds": 75.5,
        "agent": "custom",
        "program": "agent",
        "headless": False,
        "model": None,
        "spend": True,
        "tasks": ["TSK-004"],
        "request": "Azzera i campi",
        "exit_status": 0,
        "changed_files": ["src/"],
        "kind": "code",
        "design_from": None,
        "design_version_number": None,
    }
    assert list(latest) == LATEST_KEYS
    assert latest == {
        "schema_version": 1,
        "folder": "20260929-090000",
        "started_at": "2026-09-29T09:00:00+00:00",
        "finished_at": "2026-09-29T09:01:15+00:00",
        "agent": "custom",
        "exit_status": 0,
        "changed_files": ["src/"],
        "kind": "code",
        "design_version_number": None,
    }
    assert finished.outcome.document() == outcome
    assert bundle.clock.slept == 0
    assert not (launch.files.folder.parent / "design.json").exists()


def test_a_run_that_follows_the_design_records_its_kind_and_the_two_versions(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    context, _ = context_of(tmp_path, agent=ScriptedAgent(status=0))
    launch = launch_of(project, kind="design", design_from=3, design_version_number=5)

    finished = start(context, launch)
    outcome = read(launch.files.folder / "outcome.json")
    latest = read(launch.files.folder.parent / "latest.json")

    assert list(outcome) == OUTCOME_KEYS
    assert (outcome["kind"], outcome["design_from"], outcome["design_version_number"]) == (
        "design",
        3,
        5,
    )
    assert finished.outcome.document() == outcome
    assert list(latest) == LATEST_KEYS
    assert (latest["kind"], latest["design_version_number"]) == ("design", 5)
    assert not (launch.files.folder.parent / "design.json").exists()


def test_an_interrupted_run_that_follows_the_design_keeps_its_kind(tmp_path: Path) -> None:
    project = linked(tmp_path)
    context, _ = context_of(tmp_path, agent=ScriptedAgent(interrupt=True))
    launch = launch_of(project, kind="design", design_from=2, design_version_number=4)

    with pytest.raises(KeyboardInterrupt):
        start(context, launch)
    outcome = read(launch.files.folder / "outcome.json")
    latest = read(launch.files.folder.parent / "latest.json")

    assert (outcome["kind"], outcome["design_from"], outcome["design_version_number"]) == (
        "design",
        2,
        4,
    )
    assert (latest["kind"], latest["design_version_number"], latest["exit_status"]) == (
        "design",
        4,
        130,
    )


def test_the_outcome_names_the_program_and_the_model_of_claude(tmp_path: Path) -> None:
    project = linked(tmp_path)
    program = tmp_path / "bin" / "claude.exe"
    context, _ = context_of(tmp_path, agent=ScriptedAgent(status=3))
    settings = CodeSettings(agent="claude", model="opus", headless=True)
    launch = launch_of(project, (str(program), "--print", LINE), settings=settings)

    finished = start(context, launch)

    assert finished.outcome.program == "claude.exe"
    assert finished.outcome.model == "opus"
    assert finished.outcome.headless is True
    assert finished.outcome.exit_status == 3
    assert finished.changes == Changes(files=None, problem="NO_REPOSITORY")
    assert read(launch.files.folder / "outcome.json")["changed_files"] is None


def test_a_custom_agent_records_no_model(tmp_path: Path) -> None:
    project = linked(tmp_path)
    context, _ = context_of(tmp_path)
    settings = CodeSettings(agent="custom", command=("agent",), model="opus")

    finished = start(context, launch_of(project, settings=settings))

    assert finished.outcome.model is None


def test_an_interrupted_agent_leaves_its_outcome_and_the_interrupt_goes_on(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    processes = ScriptedProcesses()
    context, _ = context_of(
        tmp_path, processes=processes, agent=ScriptedAgent(interrupt=True), seconds=4.0
    )
    launch = launch_of(project)

    with pytest.raises(KeyboardInterrupt):
        start(context, launch)
    outcome = read(launch.files.folder / "outcome.json")
    latest = read(launch.files.folder.parent / "latest.json")

    assert (outcome["exit_status"], outcome["changed_files"], outcome["seconds"]) == (
        130,
        None,
        4.0,
    )
    assert (latest["exit_status"], latest["changed_files"]) == (130, None)
    assert processes.calls == []


def test_an_interrupt_while_git_reads_the_changes_keeps_the_status_of_the_agent(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    processes = repository(project.root, interrupt=True)
    context, _ = context_of(tmp_path, processes=processes, agent=ScriptedAgent(status=2))
    launch = launch_of(project)

    with pytest.raises(KeyboardInterrupt):
        start(context, launch)

    outcome = read(launch.files.folder / "outcome.json")
    assert (outcome["exit_status"], outcome["changed_files"]) == (2, None)


def test_the_knowledge_folder_touched_by_the_agent_is_noticed(tmp_path: Path) -> None:
    project = linked(tmp_path)
    agent = ScriptedAgent(writes={"orchestwin/ORCHESTWIN.md": "# Edited by the agent\n"})
    context, _ = context_of(tmp_path, agent=agent)

    finished = start(context, launch_of(project))

    assert finished.touched is True


def test_an_edit_of_the_knowledge_folder_is_noticed_but_not_listed(tmp_path: Path) -> None:
    project = linked(tmp_path)
    agent = ScriptedAgent(
        writes={"orchestwin/ORCHESTWIN.md": "# Edited by the agent\n", "src/app.js": "export {};\n"}
    )
    processes = repository(project.root, porcelain(" M orchestwin/ORCHESTWIN.md", "?? src/"))
    context, _ = context_of(tmp_path, processes=processes, agent=agent)
    launch = launch_of(project)

    finished = start(context, launch)

    assert finished.touched is True
    assert finished.changes == Changes(files=("src/",))
    assert read(launch.files.folder / "outcome.json")["changed_files"] == ["src/"]
    processes.assert_done()


def test_a_knowledge_folder_left_uncommitted_before_the_agent_is_neither_listed_nor_noticed(
    tmp_path: Path,
) -> None:
    project = linked(tmp_path)
    agent = ScriptedAgent(writes={"src/app.js": "export {};\n"})
    processes = repository(project.root, porcelain("?? orchestwin/", "?? src/"))
    context, _ = context_of(tmp_path, processes=processes, agent=agent)

    finished = start(context, launch_of(project))

    assert finished.touched is False
    assert finished.changes == Changes(files=("src/",))
    processes.assert_done()
