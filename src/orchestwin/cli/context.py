from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from orchestwin.cli.client import StudioClient
from orchestwin.cli.errors import CliError
from orchestwin.cli.project import ProjectFolder
from orchestwin.cli.session import DEFAULT_STUDIO, SessionStore, StudioAddress

if TYPE_CHECKING:
    from datetime import datetime

    from orchestwin.cli.console import Console
    from orchestwin.cli.environment import Environment


class CommandContext:
    def __init__(
        self,
        environment: Environment,
        console: Console,
        *,
        language: str,
        assume_yes: bool = False,
        debug: bool = False,
        directory: Path | None = None,
        sessions: SessionStore | None = None,
    ) -> None:
        self.environment = environment
        self.console = console
        self.language = language
        self.assume_yes = assume_yes
        self.debug = debug
        self.directory = environment.working_directory if directory is None else directory
        self.sessions = SessionStore(environment) if sessions is None else sessions
        self.generation_waits: list[tuple[datetime, float, int | None]] = []

    def project(self, *, required: bool = True) -> ProjectFolder | None:
        found = ProjectFolder.find(self.directory)
        if found is None and required:
            raise CliError("PROJECT_NOT_LINKED")
        return found

    def studio(self) -> StudioAddress:
        project = self.project(required=False)
        if project is not None:
            link = project.link()
            return replace(StudioAddress.parse(link.studio), api_prefix=link.api_prefix)
        default = self.sessions.default_studio()
        return StudioAddress.parse(DEFAULT_STUDIO) if default is None else default

    def client(self, studio: StudioAddress | None = None) -> StudioClient:
        address = self.studio() if studio is None else studio
        return StudioClient(address, self.environment, self.sessions)

    def text(self, key: str, /, **values: object) -> str:
        return self.console.text(key, **values)
