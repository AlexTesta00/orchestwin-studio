from __future__ import annotations

import contextlib
import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import INTERRUPTED_STATUS, USAGE_STATUS, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import code_agents
from orchestwin.cli.flows.code_agents import AGENTS, CLAUDE, CUSTOM
from orchestwin.cli.mcp.configs import server_arguments
from orchestwin.cli.mcp.protocol import SERVER_NAME
from orchestwin.cli.project import LOCAL_FOLDER, json_bytes, read_json, write_atomically

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.code_order import Work
    from orchestwin.cli.project import ProjectFolder

SETTINGS_NAME: Final = "code.json"
SCHEMA_VERSION: Final = 1
CODE_FOLDER: Final = "code"
PROMPT_NAME: Final = "prompt.md"
MCP_NAME: Final = "mcp.json"
OUTCOME_NAME: Final = "outcome.json"
LATEST_NAME: Final = "latest.json"
DESIGN_POINT_NAME: Final = "design.json"
IGNORE_NAME: Final = ".gitignore"
IGNORE_CONTENT: Final = b"*\n"
FOLDER_FORMAT: Final = "%Y%m%d-%H%M%S"
PYTHON_MODULE: Final = ("-m", "orchestwin.cli")
STATUS_ARGUMENTS: Final = ("status", "--porcelain", "-z", "--untracked-files=normal")
NO_REPOSITORY: Final = "NO_REPOSITORY"
CODE_KIND: Final = "code"
DESIGN_KIND: Final = "design"
CODE_RUN_REASON: Final = "CODE_RUN"
DESIGN_RUN_REASON: Final = "DESIGN_RUN"
NO_CODE_CHANGES_REASON: Final = "NO_CODE_CHANGES"


@dataclass(frozen=True, slots=True)
class CodeSettings:
    agent: str = CLAUDE
    command: tuple[str, ...] | None = None
    model: str | None = None
    headless: bool = False

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "agent": self.agent,
            "command": None if self.command is None else list(self.command),
            "model": self.model,
            "headless": self.headless,
        }


@dataclass(frozen=True, slots=True)
class RunFiles:
    folder: Path
    prompt: Path
    mcp: Path

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def relative_prompt(self) -> str:
        return f"{LOCAL_FOLDER}/{CODE_FOLDER}/{self.name}/{PROMPT_NAME}"


@dataclass(frozen=True, slots=True)
class Launch:
    project: ProjectFolder
    files: RunFiles
    arguments: tuple[str, ...]
    settings: CodeSettings
    work: Work
    spend: bool
    kind: str = CODE_KIND
    design_from: int | None = None
    design_version_number: int | None = None

    @property
    def program(self) -> str:
        return Path(self.arguments[0]).name if self.arguments else ""


@dataclass(frozen=True, slots=True)
class Outcome:
    started_at: datetime
    finished_at: datetime
    seconds: float
    agent: str
    program: str
    headless: bool
    model: str | None
    spend: bool
    tasks: tuple[str, ...]
    request: str | None
    exit_status: int
    changed_files: tuple[str, ...] | None
    kind: str = CODE_KIND
    design_from: int | None = None
    design_version_number: int | None = None

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "started_at": moment_text(self.started_at),
            "finished_at": moment_text(self.finished_at),
            "seconds": self.seconds,
            "agent": self.agent,
            "program": self.program,
            "headless": self.headless,
            "model": self.model,
            "spend": self.spend,
            "tasks": list(self.tasks),
            "request": self.request,
            "exit_status": self.exit_status,
            "changed_files": None if self.changed_files is None else list(self.changed_files),
            "kind": self.kind,
            "design_from": self.design_from,
            "design_version_number": self.design_version_number,
        }

    def latest(self, folder: str) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "folder": folder,
            "started_at": moment_text(self.started_at),
            "finished_at": moment_text(self.finished_at),
            "agent": self.agent,
            "exit_status": self.exit_status,
            "changed_files": None if self.changed_files is None else list(self.changed_files),
            "kind": self.kind,
            "design_version_number": self.design_version_number,
        }


@dataclass(frozen=True, slots=True)
class Changes:
    files: tuple[str, ...] | None
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class Finished:
    outcome: Outcome
    changes: Changes
    touched: bool


def settings_path(project: ProjectFolder) -> Path:
    return project.local / SETTINGS_NAME


def read_settings(project: ProjectFolder) -> CodeSettings | None:
    return settings_from(read_json(settings_path(project)))


def write_settings(project: ProjectFolder, settings: CodeSettings) -> Path:
    path = settings_path(project)
    write_atomically(path, json_bytes(settings.document()))
    return path


def settings_from(document: object) -> CodeSettings | None:
    if not isinstance(document, Mapping) or document.get("schema_version") != SCHEMA_VERSION:
        return None
    agent = document.get("agent")
    command = document.get("command")
    model = document.get("model")
    headless = document.get("headless", False)
    if (
        agent not in AGENTS
        or not (command is None or _words(command))
        or not (model is None or isinstance(model, str))
        or not isinstance(headless, bool)
    ):
        return None
    return CodeSettings(
        agent=str(agent),
        command=None if command is None else tuple(command),
        model=(model.strip() or None) if isinstance(model, str) else None,
        headless=headless,
    )


def chosen_settings(
    saved: CodeSettings | None,
    *,
    agent: str | None,
    command: str | None,
    model: str | None,
    headless: bool,
    platform: str,
) -> CodeSettings:
    earlier = CodeSettings() if saved is None else saved
    if command is not None and agent == CLAUDE:
        raise CliError("CODE_COMMAND_NEEDS_CUSTOM", status=USAGE_STATUS)
    chosen = agent or (CUSTOM if command is not None else earlier.agent)
    words = (
        earlier.command
        if command is None
        else code_agents.command_words(command, platform=platform)
    )
    if chosen == CUSTOM:
        if words is None:
            raise CliError("CODE_COMMAND_REQUIRED", status=USAGE_STATUS)
        words = code_agents.checked_words(words)
    return CodeSettings(
        agent=chosen,
        command=words,
        model=earlier.model if model is None else (model.strip() or None),
        headless=bool(headless),
    )


def claude_program(context: CommandContext) -> Path:
    environment = context.environment
    return code_agents.find_claude(
        environment.variables, base=environment.working_directory, which=which
    )


def code_folder(project: ProjectFolder) -> Path:
    return project.local / CODE_FOLDER


def ensure_code_folder(project: ProjectFolder) -> Path:
    code = code_folder(project)
    code.mkdir(parents=True, exist_ok=True)
    ignore = code / IGNORE_NAME
    if not ignore.exists():
        write_atomically(ignore, IGNORE_CONTENT)
    return code


def run_folder(project: ProjectFolder, moment: datetime) -> Path:
    code = ensure_code_folder(project)
    stem = moment.astimezone(UTC).strftime(FOLDER_FORMAT)
    candidate = code / stem
    number = 1
    while True:
        try:
            candidate.mkdir()
        except FileExistsError:
            number += 1
            candidate = code / f"{stem}-{number}"
            continue
        return candidate


def mcp_document(root: Path, *, spend: bool, python: str) -> dict[str, object]:
    return {
        "mcpServers": {
            SERVER_NAME: {
                "command": python,
                "args": [*PYTHON_MODULE, *server_arguments(root, spend=spend)],
                "cwd": root.as_posix(),
            }
        }
    }


def write_run_files(
    project: ProjectFolder, moment: datetime, order: str, *, spend: bool, python: str
) -> RunFiles:
    folder = run_folder(project, moment)
    files = RunFiles(folder=folder, prompt=folder / PROMPT_NAME, mcp=folder / MCP_NAME)
    write_atomically(files.prompt, order.encode("utf-8"))
    write_atomically(files.mcp, json_bytes(mcp_document(project.root, spend=spend, python=python)))
    return files


def agent_arguments(
    project: ProjectFolder,
    settings: CodeSettings,
    files: RunFiles,
    *,
    program: Path | None,
    max_usd: float | None,
) -> tuple[str, ...]:
    line = code_agents.prompt_line(files.relative_prompt)
    if settings.agent == CLAUDE:
        if program is None:
            raise ValueError("Claude Code needs the path of its program")
        return tuple(
            code_agents.claude_arguments(
                program,
                prompt_line=line,
                mcp_config=files.mcp,
                model=settings.model,
                headless=settings.headless,
                max_usd=max_usd,
            )
        )
    values = code_agents.placeholder_values(
        prompt_file=files.prompt, prompt_line=line, mcp_config=files.mcp, project=project.root
    )
    return tuple(code_agents.custom_arguments(settings.command or (), values))


def start(context: CommandContext, launch: Launch) -> Finished:
    environment = context.environment
    before = fingerprint(launch.project.knowledge)
    started_at = environment.now()
    started = environment.monotonic()
    status: int | None = None
    try:
        status = int(
            environment.run_interactive(
                launch.arguments, launch.project.root, environment.variables
            )
        )
        finished_at = environment.now()
        seconds = _seconds(environment.monotonic() - started)
        changes = changed_files(context, launch.project)
    except KeyboardInterrupt:
        stopped = outcome_of(
            launch,
            started_at=started_at,
            finished_at=environment.now(),
            seconds=_seconds(environment.monotonic() - started),
            exit_status=INTERRUPTED_STATUS if status is None else status,
            changed_files=None,
        )
        with contextlib.suppress(OSError):
            write_outcome(launch.files, stopped)
        raise
    outcome = outcome_of(
        launch,
        started_at=started_at,
        finished_at=finished_at,
        seconds=seconds,
        exit_status=status,
        changed_files=changes.files,
    )
    write_outcome(launch.files, outcome)
    touched = fingerprint(launch.project.knowledge) != before
    return Finished(outcome=outcome, changes=changes, touched=touched)


def outcome_of(
    launch: Launch,
    *,
    started_at: datetime,
    finished_at: datetime,
    seconds: float,
    exit_status: int,
    changed_files: Sequence[str] | None,
) -> Outcome:
    settings = launch.settings
    return Outcome(
        started_at=started_at,
        finished_at=finished_at,
        seconds=seconds,
        agent=settings.agent,
        program=launch.program,
        headless=settings.headless,
        model=settings.model if settings.agent == CLAUDE else None,
        spend=launch.spend,
        tasks=launch.work.codes,
        request=launch.work.request,
        exit_status=exit_status,
        changed_files=None if changed_files is None else tuple(changed_files),
        kind=launch.kind,
        design_from=launch.design_from,
        design_version_number=launch.design_version_number,
    )


def write_outcome(files: RunFiles, outcome: Outcome) -> None:
    write_atomically(files.folder / OUTCOME_NAME, json_bytes(outcome.document()))
    write_atomically(files.folder.parent / LATEST_NAME, json_bytes(outcome.latest(files.name)))


def write_design_point(
    project: ProjectFolder, *, version: int, folder: str | None, reason: str, moment: datetime
) -> Path:
    path = ensure_code_folder(project) / DESIGN_POINT_NAME
    document = {
        "schema_version": SCHEMA_VERSION,
        "design_version_number": version,
        "recorded_at": moment_text(moment),
        "folder": folder,
        "reason": reason,
    }
    write_atomically(path, json_bytes(document))
    return path


def read_design_point(project: ProjectFolder) -> Mapping[str, object] | None:
    document = read_json(code_folder(project) / DESIGN_POINT_NAME)
    if (
        not isinstance(document, Mapping)
        or _version(document.get("schema_version")) != SCHEMA_VERSION
        or _version(document.get("design_version_number")) is None
    ):
        return None
    return document


def design_point_version(project: ProjectFolder) -> int | None:
    found = read_design_point(project)
    return None if found is None else _version(found.get("design_version_number"))


def aligned_design_version(project: ProjectFolder, verified: int | None) -> int | None:
    found = [
        version
        for version in (design_point_version(project), _version(verified))
        if version is not None
    ]
    return max(found) if found else None


def changed_files(context: CommandContext, project: ProjectFolder) -> Changes:
    try:
        root = git.repository_root(context, project.root)
        if root is None:
            return Changes(files=None, problem=NO_REPOSITORY)
        result = git.run_git(context, root, *STATUS_ARGUMENTS)
    except CliError:
        return Changes(files=None, problem=NO_REPOSITORY)
    if result.status != 0:
        return Changes(files=None, problem=str(git.failed(result).values.get("detail") or ""))
    ignored = local_prefixes(project, root)
    paths = tuple(path for path in git.status_paths(result.output) if not path.startswith(ignored))
    return Changes(files=paths)


def local_prefixes(project: ProjectFolder, root: Path) -> tuple[str, ...]:
    try:
        relative = project.root.resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        relative = "."
    base = "" if relative in ("", ".") else f"{relative}/"
    local = f"{base}{LOCAL_FOLDER}/"
    try:
        folder = project.link().knowledge_folder
    except CliError:
        return (local,)
    return (local, f"{base}{folder}/")


def fingerprint(folder: Path) -> str | None:
    if not folder.is_dir():
        return None
    digest = hashlib.sha256()
    for directory, children, names in os.walk(folder):
        children.sort()
        for name in sorted(names):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            digest.update(path.relative_to(folder).as_posix().encode("utf-8") + b"\0")
            try:
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            except OSError:
                digest.update(b"\0")
    return digest.hexdigest()


def moment_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _seconds(value: float) -> float:
    return float(round(max(value, 0.0), 2))


def _version(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _words(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
