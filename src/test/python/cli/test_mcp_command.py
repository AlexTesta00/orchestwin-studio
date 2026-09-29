from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from orchestwin.cli.mcp import configs

from .support.terminal import Run, link_folder, run_ut
from .support.transports import NoNetwork

FREE = (
    "Without --spend the paid tools ask_twin and review_changes answer with an error; to allow "
    "them, add --spend."
)
SPEND = (
    "With --spend the agents can use ask_twin and review_changes: each call is a spending of the "
    "model."
)
NOT_LINKED = (
    "This folder is not linked to a project of the Studio, so the MCP server has no knowledge "
    "folder to offer. Start it from the folder of the project, or with --project-dir, or create "
    "the project with `ut init`.\n"
)


def config(
    tmp_path: Path,
    editor: str,
    *,
    spend: bool = False,
    language: str = "en",
    before: tuple[str, ...] = (),
    working_directory: Path | None = None,
) -> Run:
    arguments = ["--lang", language, *before, "mcp", "--config", editor]
    if spend:
        arguments.append("--spend")
    return run_ut(arguments, tmp_path, transport=NoNetwork(), working_directory=working_directory)


def snippet(run: Run) -> dict[str, object]:
    lines = run.output.splitlines()
    start = lines.index("{")
    return json.loads("\n".join(lines[start:]))


def root_of(tmp_path: Path) -> str:
    return Path(os.path.abspath(tmp_path / "project")).as_posix()


def arguments_of(tmp_path: Path, *, spend: bool = False) -> list[str]:
    arguments = ["--project-dir", root_of(tmp_path), "mcp"]
    return [*arguments, "--spend"] if spend else arguments


def claude_line(tmp_path: Path, *, spend: bool = False) -> str:
    folder = configs.shell_word(root_of(tmp_path), "linux")
    line = f"claude mcp add orchestwin-twins -- ut --project-dir {folder} mcp"
    return f"{line} --spend" if spend else line


def entry_of(tmp_path: Path, *, spend: bool = False) -> dict[str, object]:
    return {"command": "ut", "args": arguments_of(tmp_path, spend=spend), "cwd": root_of(tmp_path)}


def test_the_configuration_for_claude_code_gives_the_command_and_the_file(
    tmp_path: Path,
) -> None:
    link_folder(tmp_path / "project")

    run = config(tmp_path, "claude-code")

    lines = run.output.splitlines()
    assert run.status == 0
    assert run.errors == ""
    assert lines[:4] == [
        FREE,
        "To add the server to Claude Code, launch this command from the folder of the project:",
        claude_line(tmp_path),
        "Or write this in the file .mcp.json of the folder of the project:",
    ]
    assert snippet(run) == {"mcpServers": {"orchestwin-twins": entry_of(tmp_path)}}


@pytest.mark.parametrize(
    ("editor", "sentence", "expected"),
    [
        (
            "cursor",
            "Write this in the file .cursor/mcp.json of the folder of the project:",
            lambda entry: {"mcpServers": {"orchestwin-twins": entry}},
        ),
        (
            "vscode",
            "Write this in the file .vscode/mcp.json of the folder of the project:",
            lambda entry: {"servers": {"orchestwin-twins": {"type": "stdio", **entry}}},
        ),
    ],
)
def test_the_configuration_for_cursor_and_vscode_is_the_file_to_write(
    tmp_path: Path, editor: str, sentence: str, expected: object
) -> None:
    link_folder(tmp_path / "project")

    run = config(tmp_path, editor)

    assert run.status == 0
    assert run.output.splitlines()[:2] == [FREE, sentence]
    assert snippet(run) == expected(entry_of(tmp_path))


@pytest.mark.parametrize("editor", configs.EDITORS)
def test_the_folder_of_the_project_is_absolute_with_forward_slashes(
    tmp_path: Path, editor: str
) -> None:
    link_folder(tmp_path / "project")

    document = snippet(config(tmp_path, editor))

    entry = next(iter(next(iter(document.values())).values()))
    folder = Path(os.path.abspath(tmp_path / "project"))
    assert entry["args"][0] == "--project-dir"
    assert entry["args"][2:] == ["mcp"]
    for written in (entry["args"][1], entry["cwd"]):
        assert "\\" not in written
        assert Path(written).is_absolute()
        assert Path(written) == folder


def test_with_spend_the_server_is_started_with_spend(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = config(tmp_path, "claude-code", spend=True)
    cursor = config(tmp_path, "cursor", spend=True)
    vscode = config(tmp_path, "vscode", spend=True)

    assert run.output.splitlines()[0] == SPEND
    assert run.output.splitlines()[2] == claude_line(tmp_path, spend=True)
    assert snippet(run)["mcpServers"]["orchestwin-twins"] == entry_of(tmp_path, spend=True)
    assert snippet(cursor)["mcpServers"]["orchestwin-twins"] == entry_of(tmp_path, spend=True)
    assert snippet(vscode)["servers"]["orchestwin-twins"]["args"] == arguments_of(
        tmp_path, spend=True
    )


def test_the_configuration_speaks_the_language_of_the_command(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = config(tmp_path, "claude-code", language="it")

    assert run.output.splitlines()[:4] == [
        "Senza --spend gli strumenti a pagamento ask_twin e review_changes rispondono con un "
        "errore; per permetterli aggiungi --spend.",
        "Per aggiungere il server a Claude Code lancia questo comando dalla cartella del progetto:",
        claude_line(tmp_path),
        "Oppure scrivi questo nel file .mcp.json della cartella del progetto:",
    ]


def test_the_folder_of_the_project_is_found_from_another_folder(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    run = config(
        tmp_path,
        "cursor",
        before=("--project-dir", str(tmp_path / "project" / "src")),
        working_directory=elsewhere,
    )

    assert run.status == 0
    assert snippet(run)["mcpServers"]["orchestwin-twins"] == entry_of(tmp_path)


@pytest.mark.parametrize(
    ("value", "platform", "expected"),
    [
        ("--project-dir", "linux", "--project-dir"),
        ("--project-dir", "win32", "--project-dir"),
        ("tip.calc/v1_2", "darwin", "tip.calc/v1_2"),
        ("tip.calc/v1_2", "win32", "tip.calc/v1_2"),
        ("Nicolò", "win32", "Nicolò"),
        ("my project", "linux", "'my project'"),
        ("my project", "win32", '"my project"'),
        ("a$b", "linux", "'a$b'"),
        ("O'Brien", "darwin", "'O'\"'\"'Brien'"),
        ("Ada & Co", "win32", '"Ada & Co"'),
        ("a,b", "win32", '"a,b"'),
    ],
)
def test_a_word_of_the_command_line_is_quoted_only_when_the_shell_needs_it(
    value: str, platform: str, expected: str
) -> None:
    assert configs.shell_word(value, platform) == expected


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_a_folder_with_spaces_reaches_ut_as_one_argument(tmp_path: Path, platform: str) -> None:
    folder = Path(os.path.abspath(tmp_path / "my project"))

    line = configs.claude_command(folder, spend=True, platform=platform)

    assert shlex.split(line) == [
        "claude",
        "mcp",
        "add",
        "orchestwin-twins",
        "--",
        "ut",
        "--project-dir",
        folder.as_posix(),
        "mcp",
        "--spend",
    ]


def test_the_configuration_needs_a_linked_folder(tmp_path: Path) -> None:
    run = config(tmp_path, "cursor")

    assert run.status == 6
    assert run.output == ""
    assert run.errors == NOT_LINKED


def test_an_unknown_editor_is_wrong_usage(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = config(tmp_path, "emacs")

    assert run.status == 2
    assert run.output == ""
    assert "emacs" in run.errors


def test_an_unknown_option_is_wrong_usage(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")

    run = run_ut(["mcp", "--free"], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.output == ""


@pytest.mark.parametrize(
    ("language", "fragments"),
    [
        (
            "it",
            [
                "permette agli agenti gli strumenti a pagamento ask_twin e review_changes",
                "invece di avviare il server mostra la configurazione da copiare nell'editor",
                "Avvia il server MCP orchestwin-twins",
            ],
        ),
        (
            "en",
            [
                "allow the agents the paid tools ask_twin and review_changes",
                "instead of starting the server, show the configuration to copy into the editor",
                "Start the MCP server orchestwin-twins",
            ],
        ),
    ],
)
def test_the_help_of_the_command_speaks_the_language_of_the_command(
    tmp_path: Path, language: str, fragments: list[str]
) -> None:
    run = run_ut(["--lang", language, "mcp", "--help"], tmp_path, transport=NoNetwork())

    text = " ".join(run.output.split())
    assert run.status == 0
    for fragment in fragments:
        assert fragment in text


def test_the_command_is_listed_in_the_help_of_ut(tmp_path: Path) -> None:
    run = run_ut(["--lang", "en", "--help"], tmp_path, transport=NoNetwork())

    text = " ".join(run.output.split())
    assert "mcp Start the MCP server orchestwin-twins, which gives the agents of the editor" in (
        text
    )


def test_the_snippets_are_built_for_each_editor(tmp_path: Path) -> None:
    root = Path(os.path.abspath(tmp_path))

    assert configs.server_arguments(root, spend=False) == ["--project-dir", root.as_posix(), "mcp"]
    assert configs.server_arguments(root, spend=True) == [
        "--project-dir",
        root.as_posix(),
        "mcp",
        "--spend",
    ]
    assert configs.snippet("cursor", root, spend=False) == configs.snippet(
        "claude-code", root, spend=False
    )
    with pytest.raises(ValueError):
        configs.snippet("emacs", root, spend=False)
