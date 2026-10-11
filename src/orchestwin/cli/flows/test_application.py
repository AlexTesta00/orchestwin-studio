from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.http import is_loopback

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.test_settings import TestSettings
    from orchestwin.cli.project import ProjectFolder

INDEX_PAGE: Final = "index.html"
WEB_SCHEMES: Final = ("http", "https")
UNSAFE_FOLDER: Final = re.compile(r"[\\:]+")


@dataclass(frozen=True, slots=True)
class Application:
    kind: str
    address: str
    location: str
    saved: Mapping[str, str]
    direct: bool

    @property
    def static(self) -> bool:
        return self.kind == tests_api.STATIC

    def document(self) -> dict[str, str]:
        return {"kind": self.kind, "address": self.address}


def chosen_application(
    context: CommandContext,
    project: ProjectFolder,
    requested: Mapping[str, object] | None,
    settings: TestSettings | None,
) -> Application:
    if requested is not None:
        return application_of(project, requested, base=context.directory)
    if settings is not None and settings.application is not None:
        return application_of(project, settings.application, base=project.root)
    raise CliError("TEST_APPLICATION_REQUIRED", status=USAGE_STATUS)


def application_of(
    project: ProjectFolder, value: Mapping[str, object], *, base: Path
) -> Application:
    kind = str(value.get("kind") or "").strip().upper()
    address = str(value.get("address") or "").strip()
    if kind == tests_api.URL:
        return url_application(address)
    if kind == tests_api.STATIC:
        return static_application(project, address, base=base)
    raise CliError("TEST_APPLICATION_REQUIRED", status=USAGE_STATUS)


def url_application(address: str) -> Application:
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if (
        parts is None
        or not host
        or parts.scheme.lower() not in WEB_SCHEMES
        or len(address) > tests_api.MAX_ADDRESS_LENGTH
        or any(character.isspace() for character in address)
    ):
        raise CliError("TEST_URL_INVALID", status=USAGE_STATUS, values={"address": address})
    return Application(
        kind=tests_api.URL,
        address=address,
        location=address,
        saved={"kind": tests_api.URL, "address": address},
        direct=is_loopback(host),
    )


def static_application(project: ProjectFolder, address: str, *, base: Path) -> Application:
    path = Path(address) if address else Path()
    folder = Path(os.path.abspath(path if path.is_absolute() else base / path))
    if not address or not folder.is_dir() or not (folder / INDEX_PAGE).is_file():
        raise CliError(
            "TEST_STATIC_INVALID", status=USAGE_STATUS, values={"folder": address or "-"}
        )
    root = Path(os.path.abspath(project.root))
    try:
        relative: PurePosixPath | None = PurePosixPath(folder.relative_to(root).as_posix())
    except ValueError:
        relative = None
    return Application(
        kind=tests_api.STATIC,
        address=static_address(folder, relative),
        location=str(folder),
        saved={
            "kind": tests_api.STATIC,
            "address": str(folder) if relative is None else relative.as_posix(),
        },
        direct=True,
    )


def static_address(folder: Path, relative: PurePosixPath | None) -> str:
    if relative is None:
        parts = [folder.name]
    else:
        parts = [part for part in relative.parts if part not in ("", ".")]
        if not parts:
            return "."
    cleaned = [UNSAFE_FOLDER.sub("-", part).strip() or "-" for part in parts]
    cleaned = ["-" if part in (".", "..") else part for part in cleaned]
    text = "/".join(cleaned)[: tests_api.MAX_ADDRESS_LENGTH].strip("/")
    return text or "-"
