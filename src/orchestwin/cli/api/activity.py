from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from orchestwin.cli.client import DEFAULT_TIMEOUT
from orchestwin.cli.errors import ApiFailure
from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

KIND: Final = "orchestwin.project-activity"
JOURNAL_TIMEOUT: Final = 10.0
SESSION_FIELDS: Final = ("code", "started_at")


def path(project_id: str, suffix: str = "") -> str:
    return f"/projects/{project_id}/activity{suffix}"


def request(
    client: StudioClient,
    method: str,
    route: str,
    *,
    body: Mapping[str, object] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Mapping[str, object]:
    reply = client.request(method, route, body=body, timeout=timeout)
    document = reply_body(reply)
    if reply.status >= 400:
        detail = document.get("detail") if isinstance(document, Mapping) else None
        code = detail.get("code") if isinstance(detail, Mapping) else detail
        raise ApiFailure(code if isinstance(code, str) else "API_FAILURE", http_status=reply.status)
    if not isinstance(document, Mapping):
        raise ApiFailure("API_FAILURE", http_status=reply.status)
    return document


def overview(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = request(client, "GET", path(project_id))
    if document.get("kind") != KIND:
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def active_code(client: StudioClient, project_id: str) -> str | None:
    document = request(client, "GET", path(project_id, "/session"))
    if document.get("active") is not True:
        return None
    return str(session_of(document)["code"])


def start(client: StudioClient, project_id: str, code: str) -> Mapping[str, object]:
    return session_of(
        request(client, "POST", path(project_id, "/sessions"), body={"session_code": code})
    )


def end(client: StudioClient, project_id: str, code: str) -> Mapping[str, object]:
    route = path(project_id, f"/sessions/{quote(code, safe='')}/end")
    return session_of(request(client, "POST", route))


def record(
    client: StudioClient, project_id: str, body: Mapping[str, object]
) -> Mapping[str, object]:
    return request(client, "POST", path(project_id, "/events"), body=body, timeout=JOURNAL_TIMEOUT)


def session_of(document: Mapping[str, object]) -> Mapping[str, object]:
    session = document.get("session")
    if not isinstance(session, Mapping) or not all(
        isinstance(session.get(name), str) and session.get(name) for name in SESSION_FIELDS
    ):
        raise ApiFailure("API_FAILURE", http_status=200)
    return session
