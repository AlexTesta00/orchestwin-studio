from __future__ import annotations

import contextlib
import getpass
import io
import locale
import os
import signal
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, TextIO

from orchestwin.cli.errors import CliError
from orchestwin.cli.http import Transport, UrlTransport

LANGUAGE_VARIABLES: Final = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")
NEUTRAL_LOCALES: Final = frozenset({"c", "posix"})
MISSING_PROGRAM_STATUS: Final = 127
TIMEOUT_STATUS: Final = 124
NOT_STARTED_STATUS: Final = 126


class RunningProcess(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True, slots=True)
class ProcessResult:
    status: int
    output: str
    errors: str


def default_run_process(
    arguments: Sequence[str], folder: Path, timeout_seconds: float
) -> ProcessResult:
    command = [str(argument) for argument in arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=folder,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return ProcessResult(MISSING_PROGRAM_STATUS, "", f"{command[0]}: not found")
    except subprocess.TimeoutExpired:
        return ProcessResult(TIMEOUT_STATUS, "", "timeout")
    except OSError as error:
        return ProcessResult(NOT_STARTED_STATUS, "", f"{command[0]}: {error}")
    return ProcessResult(completed.returncode, completed.stdout or "", completed.stderr or "")


def default_start_process(
    arguments: Sequence[str], folder: Path, variables: Mapping[str, str]
) -> RunningProcess:
    command = [str(argument) for argument in arguments]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        return subprocess.Popen(
            command,
            cwd=folder,
            env=dict(variables),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except FileNotFoundError:
        raise CliError(
            "BROWSER_NOT_STARTED",
            status=1,
            values={"program": _program_name(command), "detail": "program not found"},
        ) from None
    except OSError as error:
        raise CliError(
            "BROWSER_NOT_STARTED",
            status=1,
            values={
                "program": _program_name(command),
                "detail": error.strerror or type(error).__name__,
            },
        ) from None


def _program_name(command: Sequence[str]) -> str:
    return Path(command[0]).name if command else "program"


def default_run_interactive(
    arguments: Sequence[str], folder: Path, variables: Mapping[str, str]
) -> int:
    command = [str(argument) for argument in arguments]
    try:
        process = subprocess.Popen(command, cwd=folder, env=dict(variables))
    except FileNotFoundError:
        raise CliError(
            "CODE_AGENT_NOT_STARTED",
            status=1,
            values={"program": _program_name(command), "detail": "program not found"},
        ) from None
    except OSError as error:
        raise CliError(
            "CODE_AGENT_NOT_STARTED",
            status=1,
            values={
                "program": _program_name(command),
                "detail": error.strerror or type(error).__name__,
            },
        ) from None
    try:
        with interrupts_left_to_the_program():
            return process.wait()
    except KeyboardInterrupt:
        with interrupts_left_to_the_program():
            process.wait()
        raise


@contextlib.contextmanager
def interrupts_left_to_the_program() -> Iterator[None]:
    try:
        previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (ValueError, OSError):
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, signal.default_int_handler if previous is None else previous)


@dataclass(frozen=True, slots=True)
class Environment:
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    variables: Mapping[str, str]
    home: Path
    working_directory: Path
    platform: str
    interactive: bool
    now: Callable[[], datetime]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    read_secret: Callable[[str], str]
    open_browser: Callable[[str], bool]
    transport: Transport
    system_language: str | None
    run_process: Callable[[Sequence[str], Path, float], ProcessResult] = default_run_process
    start_process: Callable[[Sequence[str], Path, Mapping[str, str]], RunningProcess] = (
        default_start_process
    )
    run_interactive: Callable[[Sequence[str], Path, Mapping[str, str]], int] = (
        default_run_interactive
    )


def real_environment() -> Environment:
    stdin = sys.stdin if sys.stdin is not None else io.StringIO()
    stdout = sys.stdout if sys.stdout is not None else io.StringIO()
    stderr = sys.stderr if sys.stderr is not None else io.StringIO()
    interactive = is_terminal(stdin) and is_terminal(stdout)
    prepare_stream(stdin, output=False)
    prepare_stream(stdout, output=True)
    prepare_stream(stderr, output=True)
    variables = dict(os.environ)
    return Environment(
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        variables=variables,
        home=_home(),
        working_directory=Path.cwd(),
        platform=sys.platform,
        interactive=interactive,
        now=utc_now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        read_secret=getpass.getpass,
        open_browser=webbrowser.open,
        transport=UrlTransport(),
        system_language=system_language(variables, sys.platform),
        run_process=default_run_process,
        start_process=default_start_process,
        run_interactive=default_run_interactive,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def is_terminal(stream: object) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def prepare_stream(stream: object, *, output: bool) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    changes: dict[str, str] = {}
    if output:
        changes["errors"] = "replace"
    if not is_terminal(stream):
        changes["encoding"] = "utf-8"
    if changes:
        with contextlib.suppress(OSError, ValueError, io.UnsupportedOperation):
            reconfigure(**changes)


def system_language(variables: Mapping[str, str], platform: str) -> str | None:
    for name in LANGUAGE_VARIABLES:
        code = language_code(variables.get(name, ""))
        if code is not None:
            return code
    if platform == "win32":
        return _windows_language()
    return None


def language_code(value: str) -> str | None:
    first = value.split(":", 1)[0].strip()
    code = first.split(".", 1)[0].split("@", 1)[0].strip()
    if not code or code.lower() in NEUTRAL_LOCALES:
        return None
    return code


def _windows_language() -> str | None:
    try:
        import ctypes

        identifier = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
    except (AttributeError, OSError, ValueError, TypeError):
        return None
    return locale.windows_locale.get(identifier)


def _home() -> Path:
    try:
        return Path.home()
    except RuntimeError:
        return Path.cwd()
