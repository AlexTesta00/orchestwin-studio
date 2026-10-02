from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import code_agents
from orchestwin.cli.flows.code_agents import (
    CLAUDE,
    CUSTOM,
    budget,
    budget_text,
    checked_words,
    claude_arguments,
    command_words,
    custom_arguments,
    find_claude,
    placeholder_values,
    prompt_line,
    search_path,
)
from orchestwin.cli.mcp.protocol import SERVER_NAME

PROMPT = ".orchestwin/code/20260929-090000/prompt.md"
LINE = (
    "Read the file .orchestwin/code/20260929-090000/prompt.md of this repository and carry out "
    "the work order it contains."
)
LIST_OPTIONS = ("--mcp-config", "--allowedTools")


class Finder:
    def __init__(self, found: str | None) -> None:
        self.found = found
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, mode: int = 0, path: str | None = None) -> str | None:
        self.calls.append((name, path))
        return self.found


def refusal(action) -> CliError:
    with pytest.raises(CliError) as caught:
        action()
    return caught.value


def test_the_prompt_line_is_one_ascii_sentence_without_quotes() -> None:
    line = prompt_line(PROMPT)

    assert line == LINE
    assert line.isascii()
    assert '"' not in line and "'" not in line
    assert line.count(".orchestwin/code/") == 1


def test_claude_in_a_conversation_gets_the_prompt_line_and_the_twins(tmp_path: Path) -> None:
    program = tmp_path / "bin" / "claude"
    mcp = tmp_path / "mcp.json"

    plain = claude_arguments(program, prompt_line=LINE, mcp_config=mcp)
    chosen = claude_arguments(program, prompt_line=LINE, mcp_config=mcp, model="opus")

    assert plain == [str(program), LINE, "--mcp-config", str(mcp)]
    assert chosen == [str(program), LINE, "--mcp-config", str(mcp), "--model", "opus"]


def test_claude_headless_gets_every_option_word_by_word(tmp_path: Path) -> None:
    program = tmp_path / "bin" / "claude"
    mcp = tmp_path / "mcp.json"

    words = claude_arguments(
        program, prompt_line=LINE, mcp_config=mcp, model="opus", headless=True, max_usd=2.5
    )
    bare = claude_arguments(program, prompt_line=LINE, mcp_config=mcp, headless=True)

    assert words == [
        str(program),
        "--print",
        LINE,
        "--mcp-config",
        str(mcp),
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "mcp__orchestwin-twins",
        "--model",
        "opus",
        "--max-budget-usd",
        "2.50",
    ]
    assert bare == [
        str(program),
        "--print",
        LINE,
        "--mcp-config",
        str(mcp),
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "mcp__orchestwin-twins",
    ]


@pytest.mark.parametrize("headless", [False, True])
def test_the_prompt_line_comes_before_every_option_that_takes_a_list(
    tmp_path: Path, headless: bool
) -> None:
    words = claude_arguments(
        tmp_path / "claude",
        prompt_line=LINE,
        mcp_config=tmp_path / "mcp.json",
        model="opus",
        headless=headless,
        max_usd=1.0 if headless else None,
    )

    position = words.index(LINE)
    assert all(position < words.index(option) for option in LIST_OPTIONS if option in words)
    assert words[position - 1] == ("--print" if headless else str(tmp_path / "claude"))


def test_the_budget_reaches_claude_only_when_it_works_alone(tmp_path: Path) -> None:
    words = claude_arguments(
        tmp_path / "claude", prompt_line=LINE, mcp_config=tmp_path / "mcp.json", max_usd=2.0
    )

    assert "--max-budget-usd" not in words


def test_the_twin_tools_follow_the_name_of_the_mcp_server() -> None:
    assert code_agents.TWIN_TOOLS == f"mcp__{SERVER_NAME}" == "mcp__orchestwin-twins"


@pytest.mark.parametrize(
    ("value", "expected", "text"),
    [
        ("2.5", 2.5, "2.50"),
        ("2.456", 2.46, "2.46"),
        (" 10 ", 10.0, "10.00"),
        ("0.01", 0.01, "0.01"),
    ],
)
def test_the_budget_is_an_amount_in_cents(value: str, expected: float, text: str) -> None:
    amount = budget(value, agent=CLAUDE, headless=True)

    assert amount == expected
    assert budget_text(amount) == text


@pytest.mark.parametrize("value", ["0", "-1", "0.001", "nan", "inf", "-inf", "abc", ""])
def test_the_budget_must_be_a_finite_amount_above_zero(value: str) -> None:
    error = refusal(lambda: budget(value, agent=CLAUDE, headless=True))

    assert (error.code, error.status) == ("CODE_MAX_USD_INVALID", 2)


@pytest.mark.parametrize(("agent", "headless"), [(CLAUDE, False), (CUSTOM, True), (CUSTOM, False)])
def test_the_budget_needs_headless_and_claude(agent: str, headless: bool) -> None:
    error = refusal(lambda: budget("2", agent=agent, headless=headless))

    assert (error.code, error.status) == ("CODE_BUDGET_NEEDS_HEADLESS", 2)
    assert budget(None, agent=agent, headless=headless) is None


def test_claude_is_found_through_the_variable_before_the_path(tmp_path: Path) -> None:
    program = tmp_path / "tools" / "claude.exe"
    program.parent.mkdir()
    program.write_bytes(b"")
    finder = Finder(str(tmp_path / "elsewhere" / "claude"))

    found = find_claude({"ORCHESTWIN_CLAUDE": str(program)}, base=tmp_path, which=finder)

    assert found == program
    assert finder.calls == []


def test_a_relative_variable_is_read_from_the_working_folder(tmp_path: Path) -> None:
    program = tmp_path / "tools" / "claude"
    program.parent.mkdir()
    program.write_bytes(b"")

    found = find_claude({"ORCHESTWIN_CLAUDE": "tools/claude"}, base=tmp_path, which=Finder(None))

    assert found == program


def test_a_variable_that_names_no_file_leaves_the_search_to_the_path(tmp_path: Path) -> None:
    expected = tmp_path / "bin" / "claude"
    finder = Finder(str(expected))
    search = str(tmp_path / "bin")

    found = find_claude(
        {"ORCHESTWIN_CLAUDE": str(tmp_path / "missing"), "PATH": search},
        base=tmp_path,
        which=finder,
    )

    assert found == expected
    assert finder.calls == [("claude", search)]


def test_claude_not_found_names_the_variable(tmp_path: Path) -> None:
    finder = Finder(None)

    error = refusal(lambda: find_claude({"PATH": "nowhere"}, base=tmp_path, which=finder))

    assert (error.code, error.status) == ("CODE_AGENT_NOT_FOUND", 1)
    assert error.values == {"variable": "ORCHESTWIN_CLAUDE"}
    assert finder.calls == [("claude", "nowhere")]


def test_the_search_uses_the_path_of_the_variables_and_never_the_one_of_the_machine(
    tmp_path: Path,
) -> None:
    assert search_path({"PATH": "first", "Path": "second"}) == "first"
    assert search_path({"Path": "second"}) == "second"
    assert search_path({}) == ""
    error = refusal(lambda: find_claude({}, base=tmp_path))
    assert error.code == "CODE_AGENT_NOT_FOUND"


def test_a_custom_command_follows_the_quoting_of_the_platform() -> None:
    posix = command_words("aider --message-file {prompt_file} 'two words'", platform="linux")
    windows = command_words(
        r'"C:\Program Files\Tool\tool.exe" --read {prompt_file} C:\work\notes.txt ""',
        platform="win32",
    )

    assert posix == ("aider", "--message-file", "{prompt_file}", "two words")
    assert windows == (
        r"C:\Program Files\Tool\tool.exe",
        "--read",
        "{prompt_file}",
        r"C:\work\notes.txt",
        "",
    )


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_quotes_that_do_not_close_are_refused(platform: str) -> None:
    error = refusal(lambda: command_words('agent "{prompt_file}', platform=platform))

    assert (error.code, error.status) == ("CODE_COMMAND_INVALID", 2)
    assert error.values == {"reason": "QUOTES"}


@pytest.mark.parametrize(("text", "platform"), [("", "linux"), ("   ", "win32"), ('""', "win32")])
def test_an_empty_command_is_refused(text: str, platform: str) -> None:
    error = refusal(lambda: command_words(text, platform=platform))

    assert (error.code, error.status) == ("CODE_COMMAND_INVALID", 2)
    assert error.values == {"reason": "EMPTY"}


@pytest.mark.parametrize(
    ("text", "placeholder"),
    [
        ("agent --model {model}", "{model}"),
        ("agent {Prompt_File}", "{Prompt_File}"),
        ("agent --in={prompt_file} --out={output}", "{output}"),
    ],
)
def test_a_placeholder_that_ut_does_not_know_is_refused(text: str, placeholder: str) -> None:
    error = refusal(lambda: command_words(text, platform="linux"))

    assert (error.code, error.status) == ("CODE_COMMAND_INVALID", 2)
    assert error.values == {"reason": "PLACEHOLDER", "placeholder": placeholder}


def test_a_saved_command_is_checked_again() -> None:
    assert checked_words(["agent", "{project}"]) == ("agent", "{project}")
    assert refusal(lambda: checked_words([])).values == {"reason": "EMPTY"}
    assert refusal(lambda: checked_words(["agent", "{x}"])).values == {
        "reason": "PLACEHOLDER",
        "placeholder": "{x}",
    }


def test_every_placeholder_is_filled_inside_the_words_and_other_braces_stay(
    tmp_path: Path,
) -> None:
    values = placeholder_values(
        prompt_file=tmp_path / "prompt.md",
        prompt_line=LINE,
        mcp_config=tmp_path / "mcp.json",
        project=tmp_path,
    )
    words = command_words(
        "agent --file={prompt_file} {prompt_line} --mcp {mcp_config} --cwd {project} {} "
        "'{\"a\": 1}'",
        platform="linux",
    )

    filled = custom_arguments(words, values)

    assert filled == [
        "agent",
        f"--file={tmp_path / 'prompt.md'}",
        LINE,
        "--mcp",
        str(tmp_path / "mcp.json"),
        "--cwd",
        str(tmp_path),
        "{}",
        '{"a": 1}',
    ]
    assert values == {
        "prompt_file": str(tmp_path / "prompt.md"),
        "prompt_line": LINE,
        "mcp_config": str(tmp_path / "mcp.json"),
        "project": str(tmp_path),
    }
