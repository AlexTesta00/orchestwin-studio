from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.client import payload
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.http import multipart

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

IMPORTS_PATH: Final = "/project-imports"
ARCHIVE_FIELD: Final = "archive"
NAME_FIELD: Final = "display_name"
ARCHIVE_TYPE: Final = "application/zip"


def import_project(
    client: StudioClient,
    archive: bytes,
    *,
    file_name: str,
    display_name: str | None = None,
) -> Mapping[str, object]:
    fields = {} if display_name is None else {NAME_FIELD: display_name}
    form = multipart(fields, {ARCHIVE_FIELD: (file_name, ARCHIVE_TYPE, archive)})
    reply = client.request("POST", IMPORTS_PATH, form=form)
    document = payload(reply)
    project = document.get("project") if isinstance(document, dict) else None
    if not isinstance(project, dict) or not isinstance(project.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document


def imported_project(document: Mapping[str, object]) -> Mapping[str, object]:
    project = document.get("project")
    return project if isinstance(project, Mapping) else {}


def imported_origin(document: Mapping[str, object]) -> Mapping[str, object]:
    origin = document.get("origin")
    return origin if isinstance(origin, Mapping) else {}


def approval_required(document: Mapping[str, object]) -> tuple[str, ...]:
    stages = document.get("approval_required")
    if not isinstance(stages, list | tuple):
        return ()
    return tuple(stage for stage in stages if isinstance(stage, str))
