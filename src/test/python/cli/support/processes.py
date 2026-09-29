from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pytest

from orchestwin.cli.environment import MISSING_PROGRAM_STATUS, ProcessResult
from orchestwin.cli.flows.changes import (
    diff_arguments,
    git_command,
    kinds_arguments,
    log_arguments,
    numstat_arguments,
)

COMMIT_DATE = "2026-09-29T10:15:00+02:00"
AUTHOR = "Anna Rossi"


class ProcessCall(NamedTuple):
    arguments: tuple[str, ...]
    folder: Path


@dataclass(slots=True)
class ExpectedProcess:
    prefix: tuple[str, ...]
    status: int
    output: str
    errors: str
    repeat: bool
    interrupt: bool

    def matches(self, arguments: Sequence[str]) -> bool:
        return tuple(arguments[: len(self.prefix)]) == self.prefix


class ScriptedProcesses:
    def __init__(self) -> None:
        self.expected: list[ExpectedProcess] = []
        self.calls: list[ProcessCall] = []
        self.timeouts: list[float] = []

    def expect(
        self,
        prefix: Sequence[str],
        *,
        status: int = 0,
        output: str = "",
        errors: str = "",
        repeat: bool = False,
        interrupt: bool = False,
    ) -> ScriptedProcesses:
        self.expected.append(
            ExpectedProcess(
                prefix=tuple(str(item) for item in prefix),
                status=status,
                output=output,
                errors=errors,
                repeat=repeat,
                interrupt=interrupt,
            )
        )
        return self

    def __call__(
        self, arguments: Sequence[str], folder: Path, timeout_seconds: float
    ) -> ProcessResult:
        return self.run(arguments, folder, timeout_seconds)

    def run(self, arguments: Sequence[str], folder: Path, timeout_seconds: float) -> ProcessResult:
        call = ProcessCall(tuple(str(item) for item in arguments), Path(folder))
        self.calls.append(call)
        self.timeouts.append(timeout_seconds)
        found = [item for item in self.expected if item.matches(call.arguments)]
        if not found:
            pytest.fail(f"unexpected process: {' '.join(call.arguments)}")
        longest = max(len(item.prefix) for item in found)
        chosen = next(item for item in found if len(item.prefix) == longest)
        if not chosen.repeat:
            self.expected.remove(chosen)
        if chosen.interrupt:
            raise KeyboardInterrupt
        return ProcessResult(chosen.status, chosen.output, chosen.errors)

    def assert_done(self) -> None:
        waiting = [" ".join(item.prefix) for item in self.expected if not item.repeat]
        if waiting:
            pytest.fail(f"expected processes that never ran: {'; '.join(waiting)}")

    def arguments(self, *prefix: str) -> list[tuple[str, ...]]:
        return [call.arguments for call in self.calls if call.arguments[: len(prefix)] == prefix]


def no_processes(arguments: Sequence[str], folder: Path, timeout_seconds: float) -> ProcessResult:
    name = str(arguments[0]) if arguments else "program"
    return ProcessResult(MISSING_PROGRAM_STATUS, "", f"{name}: not found")


@dataclass(frozen=True, slots=True)
class FakeFile:
    path: str
    status: str = "M"
    added: int = 1
    removed: int = 0
    source: str | None = None
    binary: bool = False


@dataclass(frozen=True, slots=True)
class FakeCommit:
    hash: str
    message: str
    files: tuple[FakeFile, ...] = ()
    parent: str | None = None
    date: str = COMMIT_DATE
    author: str = AUTHOR
    diff: str = ""


def log_output(commits: Sequence[FakeCommit]) -> str:
    parts: list[str] = []
    for commit in commits:
        parts.append(
            f"{commit.hash}\x00{commit.parent or ''}\x00{commit.date}\x00{commit.author}\x00"
            f"{commit.message}\n\x00\x1e\x00"
        )
        entries = [_numstat_entry(item) for item in commit.files]
        if entries:
            parts.append("\n" + "\x00".join(entries) + "\x00")
    return "".join(parts)


def numstat_output(commit: FakeCommit) -> str:
    return "".join(f"{_numstat_entry(item)}\x00" for item in commit.files)


def kinds_output(commit: FakeCommit) -> str:
    parts: list[str] = []
    for item in commit.files:
        if item.source is not None:
            parts.append(f"{item.status}100\x00{item.source}\x00{item.path}\x00")
        else:
            parts.append(f"{item.status}\x00{item.path}\x00")
    return "".join(parts)


def script_repository(
    processes: ScriptedProcesses,
    root: Path,
    commits: Sequence[FakeCommit],
    *,
    since: str | None = None,
    head: str | None = None,
    status: str = "",
    branch: str = "main",
) -> ScriptedProcesses:
    newest = head if head is not None else (commits[-1].hash if commits else "")
    processes.expect(
        git_command("rev-parse", "--show-toplevel"), output=f"{root.as_posix()}\n", repeat=True
    )
    processes.expect(
        git_command("rev-parse", "--verify", "--quiet", "HEAD"),
        output=f"{newest}\n" if newest else "",
        status=0 if newest else 1,
        repeat=True,
    )
    processes.expect(git_command("status", "--porcelain", "-z"), output=status, repeat=True)
    processes.expect(
        git_command("rev-parse", "--abbrev-ref", "HEAD"), output=f"{branch}\n", repeat=True
    )
    script_commits(processes, commits, since=since)
    return processes


def script_commits(
    processes: ScriptedProcesses,
    commits: Sequence[FakeCommit],
    *,
    since: str | None = None,
    repeat: bool = True,
) -> ScriptedProcesses:
    processes.expect(git_command(*log_arguments(since)), output=log_output(commits), repeat=repeat)
    for commit in commits:
        processes.expect(
            git_command(*kinds_arguments(commit.hash)), output=kinds_output(commit), repeat=True
        )
        processes.expect(
            git_command(*numstat_arguments(commit.hash)),
            output=numstat_output(commit),
            repeat=True,
        )
        processes.expect(
            git_command(*diff_arguments(commit.hash), literal=True),
            output=commit.diff,
            repeat=True,
        )
    return processes


def _numstat_entry(item: FakeFile) -> str:
    added = "-" if item.binary else str(item.added)
    removed = "-" if item.binary else str(item.removed)
    if item.source is not None:
        return f"{added}\t{removed}\t\x00{item.source}\x00{item.path}"
    return f"{added}\t{removed}\t{item.path}"
