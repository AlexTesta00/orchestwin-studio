from __future__ import annotations

import dataclasses
import io
import subprocess
import sys
from datetime import UTC
from pathlib import Path

import pytest

from orchestwin.cli import environment as module
from orchestwin.cli.environment import (
    Environment,
    ProcessResult,
    default_run_process,
    language_code,
    prepare_stream,
    real_environment,
    system_language,
    utc_now,
)
from orchestwin.cli.http import UrlTransport


class TerminalStream(io.TextIOWrapper):
    def isatty(self) -> bool:
        return True


def wrapped(encoding: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding)


def test_the_real_environment_reads_the_machine_once(monkeypatch: pytest.MonkeyPatch) -> None:
    stdin, stdout, stderr = wrapped("cp1252"), wrapped("cp1252"), wrapped("ascii")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setenv("ORCHESTWIN_LANG", "it")

    environment = real_environment()

    assert environment.stdin is stdin
    assert environment.stdout is stdout
    assert environment.stderr is stderr
    assert stdin.encoding == "utf-8"
    assert stdout.encoding == "utf-8"
    assert stdout.errors == "replace"
    assert stderr.errors == "replace"
    assert environment.interactive is False
    assert environment.platform == sys.platform
    assert environment.variables["ORCHESTWIN_LANG"] == "it"
    assert environment.now().tzinfo is UTC
    assert isinstance(environment.transport, UrlTransport)
    assert environment.home.is_absolute()
    assert environment.working_directory.is_absolute()
    assert environment.run_process is default_run_process
    stdin.detach()
    stdout.detach()
    stderr.detach()


def test_the_runner_of_processes_is_the_last_field_and_has_a_default() -> None:
    last = dataclasses.fields(Environment)[-1]

    assert last.name == "run_process"
    assert last.default is default_run_process


def test_a_process_runs_in_its_folder_and_is_read_as_utf8(tmp_path: Path) -> None:
    code = (
        "import os, sys\n"
        "sys.stdout.buffer.write((os.getcwd() + '|caff\\u00e8').encode('utf-8'))\n"
        "sys.stderr.buffer.write('attenzione'.encode('utf-8'))\n"
        "sys.exit(3)\n"
    )

    result = default_run_process([sys.executable, "-c", code], tmp_path, 60.0)

    assert result.status == 3
    folder, word = result.output.split("|")
    assert Path(folder).resolve() == tmp_path.resolve()
    assert word == "caffè"
    assert result.errors == "attenzione"


def test_bytes_that_are_not_utf8_are_replaced(tmp_path: Path) -> None:
    code = "import sys\nsys.stdout.buffer.write(b'caff\\xe8')\n"

    result = default_run_process([sys.executable, "-c", code], tmp_path, 60.0)

    assert result == ProcessResult(0, "caff�", "")


def test_a_missing_program_answers_127(tmp_path: Path) -> None:
    result = default_run_process(["orchestwin-no-such-program"], tmp_path, 5.0)

    assert result == ProcessResult(127, "", "orchestwin-no-such-program: not found")


def test_a_process_that_takes_too_long_answers_124(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def slow(arguments: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        seen.update(options)
        raise subprocess.TimeoutExpired(cmd=arguments, timeout=1.5)

    monkeypatch.setattr(module.subprocess, "run", slow)

    assert default_run_process(["git", "status"], tmp_path, 1.5) == ProcessResult(
        124, "", "timeout"
    )
    assert seen["timeout"] == 1.5
    assert seen["cwd"] == tmp_path
    assert seen["stdin"] == subprocess.DEVNULL
    assert "shell" not in seen


def test_a_program_that_cannot_start_answers_126(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(arguments: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        raise PermissionError("denied")

    monkeypatch.setattr(module.subprocess, "run", refused)

    result = default_run_process(["git", "status"], tmp_path, 5.0)

    assert (result.status, result.output) == (126, "")
    assert result.errors.startswith("git: ")


def test_an_output_terminal_keeps_its_encoding_and_replaces_what_it_cannot_write() -> None:
    stream = TerminalStream(io.BytesIO(), encoding="cp1252")

    prepare_stream(stream, output=True)

    assert stream.encoding == "cp1252"
    assert stream.errors == "replace"
    stream.detach()


def test_an_input_pipe_is_read_as_utf8_and_a_stream_without_reconfigure_is_left_alone() -> None:
    stream = wrapped("cp1252")
    prepare_stream(stream, output=False)
    plain_text = io.StringIO()
    prepare_stream(plain_text, output=True)

    assert stream.encoding == "utf-8"
    assert stream.errors == "strict"
    stream.detach()


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"LANG": "it_IT.UTF-8"}, "it_IT"),
        ({"LC_ALL": "C", "LANG": "en_US.UTF-8"}, "en_US"),
        ({"LC_ALL": "POSIX", "LC_MESSAGES": "it_CH@euro"}, "it_CH"),
        ({"LANGUAGE": "it:en"}, "it"),
        ({"LANG": "C.UTF-8"}, None),
        ({}, None),
    ],
)
def test_the_language_of_the_machine_comes_from_the_variables(
    variables: dict[str, str], expected: str | None
) -> None:
    assert system_language(variables, "linux") == expected
    assert system_language(variables, "darwin") == expected


def test_windows_asks_the_system_when_no_variable_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "_windows_language", lambda: "it_IT")

    assert system_language({}, "win32") == "it_IT"
    assert system_language({"LANG": "en_GB"}, "win32") == "en_GB"


def test_language_codes_leave_out_encoding_and_modifier() -> None:
    assert language_code("it_IT.UTF-8@euro") == "it_IT"
    assert language_code("  ") is None
    assert language_code("c") is None


def test_the_clock_is_aware_and_in_utc() -> None:
    assert utc_now().tzinfo is UTC
