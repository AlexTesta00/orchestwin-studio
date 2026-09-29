from __future__ import annotations

import io
import sys
from datetime import UTC

import pytest

from orchestwin.cli import environment as module
from orchestwin.cli.environment import (
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
    stdin.detach()
    stdout.detach()
    stderr.detach()


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
