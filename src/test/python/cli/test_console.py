from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.cli import console as module
from orchestwin.cli.console import (
    Choice,
    Console,
    ProgressOutcome,
    format_elapsed,
    plain,
    table_lines,
    terminal_width,
)
from orchestwin.cli.environment import Environment
from orchestwin.cli.errors import CliError

from .support.terminal import Terminal, terminal
from .support.transports import NoNetwork

OPTIONS = (
    Choice("approve", "Approve"),
    Choice("change", "Change a point"),
    Choice("leave", "Leave"),
)


class TerminalStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def console_for(
    tmp_path: Path,
    *,
    answers: tuple[str, ...] = (),
    secrets: tuple[str, ...] = (),
    language: str = "en",
    interactive: bool = False,
    variables: dict[str, str] | None = None,
) -> tuple[Console, Terminal]:
    bundle = terminal(
        tmp_path,
        transport=NoNetwork(),
        answers=answers,
        secrets=secrets,
        interactive=interactive,
        variables=variables,
    )
    return Console(bundle.environment, language=language, color=False), bundle


def with_stdout(environment: Environment, stream: io.TextIOBase, **changes: object) -> Environment:
    return replace(environment, stdout=stream, **changes)


def test_messages_go_to_the_right_stream(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, language="it")

    console.say("common.interrupted")
    console.write("testo del progetto")
    console.error("errors.INPUT_CLOSED")

    assert bundle.output == "Interrotto.\ntesto del progetto\n"
    assert "L'input si è chiuso" in bundle.errors


def test_ask_returns_the_answer_the_default_and_asks_again_when_required(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("  Ada  ", "", "", "Grace", ""))

    assert console.ask("login.email") == "Ada"
    assert console.ask("login.email") == "Grace"
    assert console.ask("login.email", default="person@example.test") == "person@example.test"
    assert bundle.output.count("An answer is needed to go on.") == 2
    assert "E-mail: [person@example.test] " in bundle.output


def test_ask_without_requirement_accepts_an_empty_answer(tmp_path: Path) -> None:
    console, _ = console_for(tmp_path, answers=("",))

    assert console.ask("login.email", required=False) == ""


def test_a_question_never_loops_forever(tmp_path: Path) -> None:
    console, _ = console_for(tmp_path, answers=("",) * 10)

    with pytest.raises(CliError) as caught:
        console.ask("login.email")

    assert caught.value.code == "ANSWER_NOT_VALID"
    assert caught.value.status == 1


def test_closed_input_while_a_question_is_open(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path)

    for question in (
        lambda: console.ask("login.email"),
        lambda: console.confirm("costs.confirm", default=True),
        lambda: console.choose("status.column_step", OPTIONS),
        lambda: console.ask_text("status.column_step"),
        lambda: console.secret("login.password"),
    ):
        with pytest.raises(CliError) as caught:
            question()
        assert caught.value.code == "INPUT_CLOSED"
        assert caught.value.status == 1
    assert bundle.secrets.prompts == ["Password: "]


def test_ask_text_reads_lines_until_an_empty_line(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("first line", "second line", "", "next"))

    assert console.ask_text("login.email") == "first line\nsecond line"
    assert "Write one or more lines; an empty line ends the text." in bundle.output


def test_read_line_gives_one_raw_line_without_prompt(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("  spaced  ",))

    assert console.read_line() == "  spaced  "
    with pytest.raises(CliError) as caught:
        console.read_line()
    assert caught.value.code == "INPUT_CLOSED"
    assert bundle.output == ""


def test_ask_text_keeps_what_was_written_when_the_input_ends(tmp_path: Path) -> None:
    console, _ = console_for(tmp_path, answers=("only line",))

    assert console.ask_text("login.email") == "only line"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("s", True),
        ("si", True),
        ("sì", True),
        ("SÌ", True),
        ("y", True),
        ("Yes", True),
        ("n", False),
        ("NO", False),
    ],
)
def test_confirm_accepts_both_languages(tmp_path: Path, answer: str, expected: bool) -> None:
    console, _ = console_for(tmp_path, answers=(answer,))

    assert console.confirm("costs.confirm", default=not expected) is expected


def test_confirm_uses_the_default_and_explains_a_wrong_answer(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("", "", "maybe", "n"), language="it")

    assert console.confirm("costs.confirm", default=True) is True
    assert console.confirm("costs.confirm", default=False) is False
    assert console.confirm("costs.confirm", default=True) is False
    assert "Vado avanti con questa spesa? [S/n] " in bundle.output
    assert "[s/N]" in bundle.output
    assert "Rispondi s per sì oppure n per no." in bundle.output


def test_choose_accepts_a_number_or_a_key(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("2", "LEAVE", "9", "zero", "1"))

    assert console.choose("status.column_step", OPTIONS).key == "change"
    assert console.choose("status.column_step", OPTIONS).key == "leave"
    assert console.choose("status.column_step", OPTIONS).key == "approve"
    assert "  1. Approve" in bundle.output
    assert "  3. Leave" in bundle.output
    assert bundle.output.count("Choose one of the numbers in the list.") == 2


def test_choose_needs_options(tmp_path: Path) -> None:
    console, _ = console_for(tmp_path)

    with pytest.raises(ValueError, match="option"):
        console.choose("status.column_step", ())


def test_secret_asks_again_on_an_empty_value(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, secrets=("", "Test-password-not-real!"))

    assert console.secret("login.password") == "Test-password-not-real!"
    assert bundle.secrets.prompts == ["Password: ", "Password: "]
    assert "Test-password-not-real!" not in bundle.output


def test_a_prompt_ends_its_line_when_the_input_is_not_a_terminal(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("Ada",))

    console.ask("login.email")
    console.say("common.interrupted")

    assert bundle.output == "E-mail: \nInterrupted.\n"


def test_an_interactive_prompt_leaves_the_line_to_the_terminal(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, answers=("Ada",), interactive=True)

    console.ask("login.email")

    assert bundle.output == "E-mail: "


WRITTEN = "".join(
    (
        "Passo ",
        chr(0x00B7),
        " fatto ",
        chr(0x2192),
        " ",
        chr(0x2713),
        " ",
        chr(0x2026),
        " ",
        chr(0x201C),
        "virgolette",
        chr(0x201D),
        " ",
        chr(0x00E8),
        " ",
        chr(0x6F22),
    )
)
CP1252_EXPECTED = "".join(
    (
        "Passo ",
        chr(0x00B7),
        " fatto -> ok ",
        chr(0x2026),
        " ",
        chr(0x201C),
        "virgolette",
        chr(0x201D),
        " ",
        chr(0x00E8),
        " ?",
    )
)
ASCII_EXPECTED = 'Passo - fatto -> ok ... "virgolette" e ?'


@pytest.mark.parametrize(
    ("encoding", "expected"),
    [("cp1252", CP1252_EXPECTED), ("ascii", ASCII_EXPECTED)],
)
def test_characters_the_stream_cannot_write_get_a_plain_equivalent(
    tmp_path: Path, encoding: str, expected: str
) -> None:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding=encoding, newline="\n")
    console, bundle = console_for(tmp_path)
    console.environment = with_stdout(bundle.environment, stream)

    console.write(WRITTEN)
    stream.flush()

    assert buffer.getvalue().decode(encoding) == f"{expected}\n"
    stream.detach()


def test_plain_leaves_encodable_text_and_unknown_encodings_alone() -> None:
    assert plain("caffè", "utf-8") == "caffè"
    assert plain("caffè", "no-such-encoding") == "caffè"


def test_tables_fit_the_width_and_wrap_long_cells() -> None:
    rows = [["Brief", "approved", "2"], ["Requirements", "waiting for your approval " * 3, "-"]]

    lines = table_lines(["Step", "State", "Version"], rows, 40)

    assert all(len(line) <= 40 for line in lines)
    assert lines[0].split() == ["Step", "State", "Version"]
    assert set(lines[1].replace(" ", "")) == {"-"}
    assert len(lines) > 4
    joined = " ".join(" ".join(line.split()) for line in lines[3:])
    assert "waiting for your approval" in joined


def test_a_short_table_keeps_one_line_per_row() -> None:
    lines = table_lines(["Step", "State"], [["Brief", "approved"], ["Team"]], 80)

    assert lines == ["Step   State", "-----  --------", "Brief  approved", "Team"]


def test_the_table_uses_the_width_of_the_terminal(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, variables={"COLUMNS": "30"})

    console.table(["Step", "State"], [["Requirements", "waiting for your approval now"]])

    assert all(len(line) <= 30 for line in bundle.output.splitlines())
    assert console.width == 30


def test_the_width_is_eighty_when_unknown(tmp_path: Path) -> None:
    _, bundle = console_for(tmp_path, variables={"COLUMNS": "abc"})

    assert terminal_width(bundle.environment) == 80


def test_items_are_listed_and_wrapped(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, variables={"COLUMNS": "20"})

    console.items(["short", "a longer line that must wrap"])

    lines = bundle.output.splitlines()
    assert lines[0] == "- short"
    assert lines[1].startswith("- a longer")
    assert all(line.startswith(("- ", "  ")) for line in lines)


def test_no_colour_when_the_output_is_not_a_terminal(tmp_path: Path) -> None:
    _, bundle = console_for(tmp_path)

    console = Console(bundle.environment, language="en", color=True)
    console.heading("Calcolo mancia")

    assert console.color is False
    assert "\x1b[" not in bundle.output
    assert bundle.output == "Calcolo mancia\n==============\n"


def test_colour_on_a_terminal_unless_refused(tmp_path: Path) -> None:
    _, bundle = console_for(tmp_path)
    stream = TerminalStream()
    environment = with_stdout(bundle.environment, stream)

    coloured = Console(environment, language="en", color=True)
    coloured.heading("Calcolo mancia")

    assert coloured.color is True
    assert stream.getvalue().startswith("\x1b[1mCalcolo mancia\x1b[0m\n")
    assert Console(environment, language="en", color=False).color is False
    for value in ("1", ""):
        no_color = replace(environment, variables={**environment.variables, "NO_COLOR": value})
        assert Console(no_color, language="en", color=True).color is False


def test_colour_on_windows_needs_the_virtual_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, bundle = console_for(tmp_path)
    environment = with_stdout(bundle.environment, TerminalStream(), platform="win32")

    monkeypatch.setattr(module, "enable_virtual_terminal", lambda stream: False)
    assert Console(environment, language="en", color=True).color is False
    monkeypatch.setattr(module, "enable_virtual_terminal", lambda stream: True)
    assert Console(environment, language="en", color=True).color is True


def test_the_virtual_terminal_is_off_for_a_stream_without_console() -> None:
    assert module.enable_virtual_terminal(io.StringIO()) is False


def test_progress_prints_a_line_at_start_every_minute_and_at_the_end(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path)

    with console.progress("Requirements") as progress:
        bundle.clock.advance(30)
        progress.update("the model is working")
        bundle.clock.advance(31)
        progress.update("the model is working")
        bundle.clock.advance(59)
        progress.update("")
        bundle.clock.advance(1)
        progress.update("")

    assert bundle.output.splitlines() == [
        "Requirements...",
        "Requirements: the model is working (1 min 01 s so far)",
        "Requirements: still running (2 min 01 s so far)",
        "Requirements: done in 2 min 01 s.",
    ]


@pytest.mark.parametrize(
    ("language", "raised", "ending"),
    [
        ("it", RuntimeError("boom"), "Mockup: non completato dopo 5 s."),
        ("en", CliError("GENERATION_LOST"), "Mockup: not completed after 5 s."),
        ("it", KeyboardInterrupt(), "Mockup: interrotto dopo 5 s."),
        ("en", KeyboardInterrupt(), "Mockup: interrupted after 5 s."),
    ],
)
def test_leaving_a_progress_because_of_an_exception_never_says_done(
    tmp_path: Path, language: str, raised: BaseException, ending: str
) -> None:
    console, bundle = console_for(tmp_path, language=language)

    with pytest.raises(type(raised)), console.progress("Mockup") as progress:
        bundle.clock.advance(5)
        raise raised

    assert bundle.output.splitlines()[-1] == ending
    assert progress.outcome is not ProgressOutcome.DONE


@pytest.mark.parametrize(
    ("outcome", "ending"),
    [
        (ProgressOutcome.NOT_COMPLETED, "Mockup: not completed after 2 s."),
        ("INTERRUPTED", "Mockup: interrupted after 2 s."),
        (ProgressOutcome.DONE, "Mockup: done in 2 s."),
    ],
)
def test_a_progress_can_be_closed_with_an_outcome(
    tmp_path: Path, outcome: ProgressOutcome | str, ending: str
) -> None:
    console, bundle = console_for(tmp_path)

    with console.progress("Mockup") as progress:
        assert progress.outcome is ProgressOutcome.DONE
        bundle.clock.advance(2)
        progress.set_outcome(outcome)

    assert bundle.output.splitlines() == ["Mockup...", ending]
    assert progress.outcome == outcome


def test_an_outcome_chosen_before_an_exception_is_kept(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path)

    with pytest.raises(RuntimeError), console.progress("Mockup") as progress:
        progress.set_outcome(ProgressOutcome.INTERRUPTED)
        raise RuntimeError("boom")

    assert bundle.output.splitlines()[-1] == "Mockup: interrupted after 0 s."


def test_an_unknown_outcome_is_refused(tmp_path: Path) -> None:
    console, _ = console_for(tmp_path)

    with console.progress("Mockup") as progress, pytest.raises(ValueError, match="FINISHED"):
        progress.set_outcome("FINISHED")

    assert progress.outcome is ProgressOutcome.DONE


def test_a_progress_on_a_terminal_ends_with_its_outcome(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, interactive=True)

    with console.progress("Mockup") as progress:
        bundle.clock.advance(4)
        progress.update("the model is working")
        progress.set_outcome(ProgressOutcome.NOT_COMPLETED)

    assert bundle.output.endswith("\rMockup: not completed after 4 s.\n")
    assert "done" not in bundle.output


def test_progress_rewrites_one_line_on_a_terminal(tmp_path: Path) -> None:
    console, bundle = console_for(tmp_path, interactive=True)

    with console.progress("Mockup") as progress:
        bundle.clock.advance(3)
        progress.update("the Studio is checking the result")

    output = bundle.output
    assert output.startswith("\rMockup - 0 s")
    assert "\rMockup - the Studio is checking the result - 3 s" in output
    assert output.endswith("Mockup: done in 3 s.\n")
    assert output.count("\n") == 1


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 s"), (59.9, "59 s"), (61, "1 min 01 s"), (3600, "1 h 00 min"), (-3, "0 s")],
)
def test_elapsed_time_is_short(seconds: float, expected: str) -> None:
    assert format_elapsed(seconds) == expected
