from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

import orchestwin
from orchestwin.cli import main as main_module
from orchestwin.cli import messages as messages_module
from orchestwin.cli.commands import COMMANDS
from orchestwin.cli.commands import status as status_command
from orchestwin.cli.console import Console
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.main import command_help_key, error_key, main
from orchestwin.cli.messages import MESSAGES

from .support.terminal import run_ut, terminal
from .support.transports import NoNetwork, ScriptedTransport

HEAVY = ("fastapi", "sqlalchemy", "pydantic", "jsonschema", "anthropic")
DEBUG_HINT = ". Launch the command again with --debug to see the details.\n"
SAMPLE_KEYS = frozenset(
    {
        "sample.errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS",
        "errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS",
        "sample.errors.FOLDER_NOT_VERIFIED",
        "errors.FOLDER_NOT_VERIFIED",
        "sample.errors.INPUT_CLOSED",
        "errors.INPUT_CLOSED",
    }
)


class BrokenStream(io.StringIO):
    def write(self, text: str) -> int:
        raise OSError("the stream is closed")


class Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("this error has no text")


def failing_run(error: BaseException):
    def run(context: CommandContext, arguments: argparse.Namespace) -> int:
        raise error

    return run


def with_sentences(monkeypatch: pytest.MonkeyPatch, sentences: dict[str, tuple[str, str]]) -> None:
    added = {key: {"it": it, "en": en} for key, (it, en) in sentences.items()}
    monkeypatch.setattr(messages_module, "MESSAGES", MappingProxyType({**MESSAGES, **added}))


def test_version(tmp_path: Path) -> None:
    run = run_ut(["--version"], tmp_path, transport=NoNetwork())

    assert run.status == 0
    assert run.output == f"ut {orchestwin.__version__}\n"
    assert run.errors == ""


def test_an_unknown_command_is_wrong_usage(tmp_path: Path) -> None:
    run = run_ut(["frobnicate"], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert "usage: ut" in run.errors
    assert "frobnicate" in run.errors
    assert run.output == ""


def test_an_unknown_language_is_wrong_usage(tmp_path: Path) -> None:
    run = run_ut(["--lang", "fr", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 2


def test_without_a_command_the_help_is_shown(tmp_path: Path) -> None:
    run = run_ut([], tmp_path, transport=NoNetwork())

    assert run.status == 2
    assert run.output.startswith("usage: ut")
    assert run.errors == "Choose a command, for example `ut status`.\n"


@pytest.mark.parametrize(
    ("arguments", "fragments"),
    [
        (
            ["--lang", "it", "--help"],
            ["mostra questo aiuto ed esce", "Accedi a uno Studio di OrchesTwin", "comandi"],
        ),
        (["--lang", "en", "status", "--help"], ["read only the folder, without asking the Studio"]),
        (["--lang", "en", "login", "-h"], ["read the password from the first line"]),
    ],
)
def test_the_help_speaks_the_language_of_the_command(
    tmp_path: Path, arguments: list[str], fragments: list[str]
) -> None:
    run = run_ut(arguments, tmp_path, transport=NoNetwork())

    assert run.status == 0
    for fragment in fragments:
        assert fragment in " ".join(run.output.split())


def test_the_language_of_the_machine_is_used_without_the_option(tmp_path: Path) -> None:
    run = run_ut(["status", "--offline"], tmp_path, transport=NoNetwork(), language="it_IT")

    assert run.status == 6
    assert run.errors.startswith("Questa cartella non è collegata")


def test_an_unexpected_error_hides_the_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(RuntimeError("boom")))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())

    assert run.status == 1
    assert run.errors == f"Unexpected error: RuntimeError: boom{DEBUG_HINT}"


def test_debug_shows_the_traceback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(RuntimeError("boom")))

    run = run_ut(["--debug", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 1
    assert "Traceback (most recent call last)" in run.errors
    assert run.errors.rstrip().endswith("RuntimeError: boom")


def test_ctrl_c_ends_with_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(KeyboardInterrupt()))

    run = run_ut(["--lang", "it", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 130
    assert run.errors == "Interrotto.\n"


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (CliError("BRAND_NEW"), 1, "Something went wrong (BRAND_NEW).\n"),
        (
            ApiFailure("brand_new", http_status=409),
            1,
            "The Studio answered with an error (status 409, brand_new).\n",
        ),
        (
            CliError("FOLDER_NOT_VERIFIED", values={"code": "FOLDER_TAMPERED", "path": "a.md"}),
            7,
            "The knowledge folder does not pass the verification (FOLDER_TAMPERED: a.md). "
            "Download it again with `ut package pull`.\n",
        ),
        (SystemExit(4), 4, ""),
        (SystemExit(None), 0, ""),
        (SystemExit("stopped by the command"), 1, "stopped by the command\n"),
    ],
)
def test_errors_become_messages_and_statuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    status: int,
    message: str,
) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(error))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())

    assert run.status == status
    assert run.errors == message


def test_the_most_specific_sentence_of_an_error_is_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "known", SAMPLE_KEYS.__contains__)
    rewritten = CliError("FOLDER_NOT_VERIFIED", values={"reason": "LINE_ENDINGS"})
    tampered = CliError("FOLDER_NOT_VERIFIED", values={"reason": "OTHER"})
    closed = CliError("INPUT_CLOSED")

    assert error_key(rewritten, "sample") == "sample.errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS"
    assert error_key(rewritten, "plain") == "errors.FOLDER_NOT_VERIFIED.LINE_ENDINGS"
    assert error_key(tampered, "sample") == "sample.errors.FOLDER_NOT_VERIFIED"
    assert error_key(tampered, "plain") == "errors.FOLDER_NOT_VERIFIED"
    assert error_key(closed, "sample") == "sample.errors.INPUT_CLOSED"
    assert error_key(closed, "plain") == "errors.INPUT_CLOSED"
    assert error_key(CliError("BRAND_NEW"), "sample") is None


def test_a_command_can_give_its_own_sentence_to_any_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_sentences(
        monkeypatch,
        {
            "status.errors.SAMPLE_CODE": ("Frase del comando.", "Sentence of the command."),
            "errors.SAMPLE_CODE": ("Frase comune.", "Shared sentence."),
        },
    )
    monkeypatch.setattr(status_command, "run", failing_run(CliError("SAMPLE_CODE", status=4)))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())

    assert run.status == 4
    assert run.errors == "Sentence of the command.\n"


def test_an_error_may_carry_values_called_key_and_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_sentences(
        monkeypatch,
        {
            "errors.SAMPLE_VALUES": (
                "Chiave {key}, lingua {language}.",
                "Key {key}, language {language}.",
            )
        },
    )
    error = CliError("SAMPLE_VALUES", status=3, values={"key": "brief", "language": "fr"})
    monkeypatch.setattr(status_command, "run", failing_run(error))

    run = run_ut(["--lang", "it", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 3
    assert run.errors == "Chiave brief, lingua fr.\n"


def test_a_sentence_that_cannot_be_formatted_is_never_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_sentences(
        monkeypatch, {"errors.SAMPLE_FAILURE": ("Totale: {count:d}.", "Total: {count:d}.")}
    )
    error = CliError("SAMPLE_FAILURE", status=5, values={"count": None})
    monkeypatch.setattr(status_command, "run", failing_run(error))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())

    assert run.status == 5
    assert run.errors.startswith("Unexpected error: TypeError: ")
    assert run.errors.endswith(DEBUG_HINT)
    assert run.errors.count("\n") == 1


def test_debug_shows_why_the_sentence_could_not_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with_sentences(
        monkeypatch, {"errors.SAMPLE_FAILURE": ("Totale: {count:d}.", "Total: {count:d}.")}
    )
    error = CliError("SAMPLE_FAILURE", status=5, values={"count": None})
    monkeypatch.setattr(status_command, "run", failing_run(error))

    run = run_ut(["--lang", "it", "--debug", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 5
    assert run.errors.startswith("Errore inatteso: TypeError: ")
    assert "Traceback (most recent call last)" in run.errors
    assert "CliError: SAMPLE_FAILURE" in run.errors
    assert run.errors.rstrip().splitlines()[-1].startswith("TypeError: ")


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (
            CliError("INPUT_CLOSED"),
            1,
            f"Unexpected error: RuntimeError: the console cannot write{DEBUG_HINT}",
        ),
        (
            RuntimeError("boom"),
            1,
            f"Unexpected error: RuntimeError: boom{DEBUG_HINT}",
        ),
        (KeyboardInterrupt(), 130, "Interrupted.\n"),
    ],
)
def test_a_console_that_cannot_write_is_replaced_by_a_plain_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    status: int,
    message: str,
) -> None:
    def broken(console: Console, key: str, /, **values: object) -> None:
        raise RuntimeError("the console cannot write")

    monkeypatch.setattr(Console, "error", broken)
    monkeypatch.setattr(status_command, "run", failing_run(error))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())

    assert run.status == status
    assert run.errors == message


def test_an_error_without_text_is_still_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(Unprintable()))

    run = run_ut(["status"], tmp_path, transport=NoNetwork())
    debug = run_ut(["--debug", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 1
    assert run.errors == f"Unexpected error: Unprintable: Unprintable{DEBUG_HINT}"
    assert debug.status == 1
    assert "Traceback (most recent call last)" in debug.errors


def test_a_failure_before_the_command_runs_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(parser: argparse.ArgumentParser) -> None:
        raise RuntimeError("the options cannot be built")

    monkeypatch.setattr(status_command, "configure", broken)

    run = run_ut(["--lang", "it", "--debug", "status"], tmp_path, transport=NoNetwork())

    assert run.status == 1
    assert run.errors.startswith(
        "Errore inatteso: RuntimeError: the options cannot be built. Rilancia il comando con "
        "--debug per vedere i dettagli.\n"
    )
    assert "Traceback (most recent call last)" in run.errors


def test_a_machine_that_cannot_be_read_is_reported_on_the_real_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> None:
        raise OSError("no terminal")

    stream = io.StringIO()
    monkeypatch.setattr(main_module, "real_environment", broken)
    monkeypatch.setattr(sys, "stderr", stream)

    assert main(["status"]) == 1
    assert stream.getvalue() == f"Unexpected error: OSError: no terminal{DEBUG_HINT}"


def test_a_stub_is_not_available_yet(tmp_path: Path) -> None:
    stubs = [module.NAME for module in COMMANDS if module.NAME not in {"login", "logout", "status"}]
    for name in stubs:
        if command_help_key(name) != "common.not_available":
            continue
        run = run_ut([name], tmp_path, transport=NoNetwork())
        assert run.status == 1
        assert run.output == "This command is not available yet in this version of ut.\n"
    assert command_help_key("status") == "status.help"
    assert command_help_key("nothing") == "common.not_available"


def test_global_options_reach_the_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[bool, bool, str, Path]] = []

    def record(context: CommandContext, arguments: argparse.Namespace) -> int:
        seen.append((context.assume_yes, context.debug, context.language, context.directory))
        return 0

    monkeypatch.setattr(status_command, "run", record)

    run = run_ut(
        ["--yes", "--no-color", "--lang=it", "--project-dir", "elsewhere", "status"],
        tmp_path,
        transport=NoNetwork(),
    )

    assert run.status == 0
    assert seen == [(True, False, "it", tmp_path / "project" / "elsewhere")]


def test_main_never_raises_when_even_the_error_cannot_be_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status_command, "run", failing_run(RuntimeError("boom")))
    bundle = terminal(tmp_path, transport=NoNetwork())
    broken = replace(bundle.environment, stderr=BrokenStream())

    assert main(["status"], environment=broken) == 1


def test_the_arguments_of_the_process_are_read_without_an_argument_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["ut", "--version"])
    bundle = terminal(tmp_path, transport=ScriptedTransport())

    assert main(environment=bundle.environment) == 0
    assert bundle.output == f"ut {orchestwin.__version__}\n"


def test_importing_the_command_line_loads_no_heavy_module() -> None:
    source = Path(orchestwin.__file__).resolve().parents[1]
    paths = [str(source), os.environ.get("PYTHONPATH", "")]
    code = (
        "import sys\n"
        "import orchestwin.cli.main\n"
        f"heavy = {HEAVY!r}\n"
        "loaded = sorted(name for name in sys.modules if name.split('.')[0] in heavy "
        "or name.startswith('orchestwin.knowledge'))\n"
        "print(loaded)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)},
        check=True,
        timeout=120,
    )

    assert result.stdout.strip() == "[]"


def test_the_sections_command_is_registered_after_status_and_loads_only_the_command_line() -> None:
    source = Path(orchestwin.__file__).resolve().parents[1]
    paths = [str(source), os.environ.get("PYTHONPATH", "")]
    code = (
        "import sys\n"
        "import orchestwin.cli.main\n"
        "from orchestwin.cli.commands import sections\n"
        "from orchestwin.cli.api import sections as api\n"
        "loaded = sorted({'.'.join(name.split('.')[:2]) for name in sys.modules "
        "if name.startswith('orchestwin.') or name.split('.')[0] in ('fastapi', 'sqlalchemy')})\n"
        "print(loaded)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)},
        check=True,
        timeout=120,
    )
    names = [module.NAME for module in COMMANDS]

    assert result.stdout.strip() == "['orchestwin.cli']"
    assert names[names.index("status") + 1] == "sections"
    assert command_help_key("sections") == "sections.help"
