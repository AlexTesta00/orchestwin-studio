from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import packages
from orchestwin.cli.errors import ApiFailure, CliError

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

HASH_HEADER: Final = "x-content-sha256"


def publish_and_pull(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
) -> FolderSummary:
    link = project.link()
    with context.console.progress(context.text("common.folder_publishing")):
        publication = packages.publish(client, link.project_id)
    number = publication["version"].get("version_number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ApiFailure("API_FAILURE", http_status=200)
    return _download(context, client, project, link.project_id, number)


def pull(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    version_number: int | None = None,
) -> FolderSummary:
    link = project.link()
    if version_number is None:
        latest = packages.latest(client, link.project_id)
        number = None if latest is None else latest.get("version_number")
        if not isinstance(number, int) or isinstance(number, bool):
            raise CliError("FOLDER_NOT_PUBLISHED")
        version_number = number
    return _download(context, client, project, link.project_id, version_number)


def _download(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    project_id: str,
    version_number: int,
) -> FolderSummary:
    target = project.knowledge
    with context.console.progress(context.text("common.folder_downloading")):
        reply = packages.archive(client, project_id, version_number)
        expected = reply.headers.get(HASH_HEADER, "").strip().lower()
        if not expected or hashlib.sha256(reply.content).hexdigest() != expected:
            raise knowledge.not_verified(
                target,
                "ARCHIVE_HASH_MISMATCH",
                f"{packages.packages_path(project_id)}/{version_number}/archive",
            )
        knowledge.unpack(reply.content, target)
    found = knowledge.summary(target)
    if found is None:
        raise knowledge.not_verified(target, "FOLDER_DOCUMENT_MISSING", knowledge.MANIFEST_NAME)
    return found
