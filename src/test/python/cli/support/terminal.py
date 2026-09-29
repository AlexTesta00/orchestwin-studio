from __future__ import annotations

import io
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestwin.cli.console import Console
from orchestwin.cli.context import CommandContext
from orchestwin.cli.environment import Environment, ProcessResult
from orchestwin.cli.http import Transport
from orchestwin.cli.main import main
from orchestwin.cli.project import ProjectFolder, ProjectLink
from orchestwin.cli.session import (
    DEFAULT_STUDIO,
    SessionStore,
    StudioAddress,
    StudioSession,
)

from .processes import no_processes
from .transports import NoNetwork

Runner = Callable[[Sequence[str], Path, float], ProcessResult]

START = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
MONOTONIC_ORIGIN = 1000.0
CONFIG_VARIABLE = "ORCHESTWIN_CONFIG_DIR"
TEST_EMAIL = "person@example.test"
TEST_PASSWORD = "Test-password-not-real!"
TEST_ACCESS_TOKEN = "test-access-not-real"
TEST_REFRESH_TOKEN = "test-refresh-not-real"
PROJECT_ID = "3f7c2a58-0000-4000-8000-000000000001"
PROJECT_NAME = "Calcolo mancia"


@dataclass(frozen=True, slots=True)
class Run:
    status: int
    output: str
    errors: str
    opened: tuple[str, ...]
    slept: float


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.start = start
        self.elapsed = 0.0
        self.slept = 0.0

    def now(self) -> datetime:
        return self.start + timedelta(seconds=self.elapsed)

    def monotonic(self) -> float:
        return MONOTONIC_ORIGIN + self.elapsed

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.elapsed += seconds
            self.slept += seconds

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds


class Browser:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def open(self, address: str) -> bool:
        self.opened.append(address)
        return True


class Secrets:
    def __init__(self, values: Sequence[str]) -> None:
        self._values = deque(values)
        self.prompts: list[str] = []

    def read(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self._values:
            raise EOFError
        return self._values.popleft()


@dataclass(frozen=True, slots=True)
class Terminal:
    environment: Environment
    clock: FakeClock
    browser: Browser
    secrets: Secrets

    @property
    def output(self) -> str:
        return self.environment.stdout.getvalue()

    @property
    def errors(self) -> str:
        return self.environment.stderr.getvalue()


def terminal(
    tmp_path: Path,
    *,
    transport: Transport,
    answers: Sequence[str] = (),
    secrets: Sequence[str] = (),
    variables: Mapping[str, str] | None = None,
    platform: str = "linux",
    interactive: bool = False,
    language: str | None = "en",
    start: datetime | None = None,
    working_directory: Path | None = None,
    processes: Runner | None = None,
) -> Terminal:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    directory = tmp_path / "project" if working_directory is None else working_directory
    directory.mkdir(parents=True, exist_ok=True)
    clock = FakeClock(START if start is None else start)
    browser = Browser()
    keeper = Secrets(secrets)
    environment = Environment(
        stdin=io.StringIO("".join(f"{answer}\n" for answer in answers)),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        variables={CONFIG_VARIABLE: str(tmp_path / "config"), **(variables or {})},
        home=home,
        working_directory=directory,
        platform=platform,
        interactive=interactive,
        now=clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        read_secret=keeper.read,
        open_browser=browser.open,
        transport=transport,
        system_language=language,
        run_process=no_processes if processes is None else processes,
    )
    return Terminal(environment=environment, clock=clock, browser=browser, secrets=keeper)


def environment(
    tmp_path: Path,
    *,
    transport: Transport,
    answers: Sequence[str] = (),
    secrets: Sequence[str] = (),
    variables: Mapping[str, str] | None = None,
    platform: str = "linux",
    interactive: bool = False,
    language: str | None = "en",
    start: datetime | None = None,
    processes: Runner | None = None,
) -> Environment:
    return terminal(
        tmp_path,
        transport=transport,
        answers=answers,
        secrets=secrets,
        variables=variables,
        platform=platform,
        interactive=interactive,
        language=language,
        start=start,
        processes=processes,
    ).environment


def run_ut(
    arguments: Sequence[str],
    tmp_path: Path,
    *,
    transport: Transport,
    answers: Sequence[str] = (),
    secrets: Sequence[str] = (),
    variables: Mapping[str, str] | None = None,
    working_directory: Path | None = None,
    platform: str = "linux",
    language: str | None = "en",
    interactive: bool = False,
    start: datetime | None = None,
    processes: Runner | None = None,
) -> Run:
    bundle = terminal(
        tmp_path,
        transport=transport,
        answers=answers,
        secrets=secrets,
        variables=variables,
        platform=platform,
        interactive=interactive,
        language=language,
        start=start,
        working_directory=working_directory,
        processes=processes,
    )
    status = main(list(arguments), environment=bundle.environment)
    return Run(
        status=status,
        output=bundle.output,
        errors=bundle.errors,
        opened=tuple(bundle.browser.opened),
        slept=bundle.clock.slept,
    )


def command_context(
    environment: Environment,
    *,
    language: str = "en",
    assume_yes: bool = False,
    debug: bool = False,
) -> CommandContext:
    console = Console(environment, language=language, color=False)
    return CommandContext(
        environment,
        console,
        language=language,
        assume_yes=assume_yes,
        debug=debug,
    )


def store_session(
    tmp_path: Path,
    *,
    studio: str = DEFAULT_STUDIO,
    email: str = TEST_EMAIL,
    access_token: str | None = TEST_ACCESS_TOKEN,
    refresh_token: str | None = TEST_REFRESH_TOKEN,
    expires_at: datetime | None = None,
    make_default: bool = True,
) -> StudioSession:
    address = StudioAddress.parse(studio)
    session = StudioSession(
        email=email,
        refresh_token=refresh_token,
        access_token=access_token,
        access_expires_at=START + timedelta(minutes=15) if expires_at is None else expires_at,
        saved_at=START,
        api_prefix=address.api_prefix,
    )
    store = SessionStore(environment(tmp_path, transport=NoNetwork()))
    store.save(address, session, make_default=make_default)
    return session


def read_session(tmp_path: Path, studio: str = DEFAULT_STUDIO) -> StudioSession | None:
    store = SessionStore(environment(tmp_path, transport=NoNetwork()))
    return store.read(StudioAddress.parse(studio))


def link_folder(
    directory: Path,
    *,
    project_id: str = PROJECT_ID,
    name: str = PROJECT_NAME,
    studio: str = DEFAULT_STUDIO,
    mode: str = "DESIGN_ONLY",
    language: str | None = None,
) -> ProjectFolder:
    link = ProjectLink(
        studio=studio,
        api_prefix="/api/v1",
        project_id=project_id,
        project_name=name,
        mode=mode,
        language=language,
        created_at=START.isoformat(timespec="seconds"),
    )
    return ProjectFolder.create(directory, link)
