from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.http import Reply


def packages_path(project_id: str) -> str:
    return f"/projects/{project_id}/knowledge-packages"


def publish(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.post(packages_path(project_id))
    if not isinstance(document, dict) or not isinstance(document.get("version"), dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def history(
    client: StudioClient,
    project_id: str,
    *,
    limit: int | None = None,
) -> list[Mapping[str, object]]:
    path = packages_path(project_id)
    if limit is not None:
        path = f"{path}?limit={int(limit)}"
    document = client.get(path)
    versions = document.get("versions") if isinstance(document, dict) else None
    if not isinstance(versions, list):
        return []
    return [item for item in versions if isinstance(item, dict)]


def latest(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    versions = history(client, project_id, limit=1)
    return versions[0] if versions else None


def archive(client: StudioClient, project_id: str, version_number: int) -> Reply:
    return client.download(f"{packages_path(project_id)}/{int(version_number)}/archive")
