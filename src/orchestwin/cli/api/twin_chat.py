from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

QUESTION_LIMIT: Final = 1000
TURN_STATUS: Final = "TWIN_TURN_RECORDED"


def modeling_path(project_id: str) -> str:
    return f"/projects/{project_id}/user-modeling"


def conversation_path(project_id: str, twin_id: str) -> str:
    return f"/projects/{project_id}/user-twins/{twin_id}/conversation"


def readiness(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.get(f"{modeling_path(project_id)}/readiness")
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def approved(document: Mapping[str, object]) -> bool:
    return document.get("snapshot_exists") is True and (
        document.get("approved_current_snapshot") is True
    )


def current_snapshot(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{modeling_path(project_id)}/snapshots/current", optional=True)
    if document is None:
        return None
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def twin_versions(document: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    body = document.get("snapshot") if isinstance(document, Mapping) else None
    versions = body.get("twin_versions") if isinstance(body, Mapping) else None
    if not isinstance(versions, list):
        return []
    return [item for item in versions if isinstance(item, Mapping)]


def conversation(
    client: StudioClient, project_id: str, twin_id: str
) -> Mapping[str, object] | None:
    document = client.get(conversation_path(project_id, twin_id), optional=True)
    snapshot = document.get("snapshot") if isinstance(document, dict) else None
    return snapshot if isinstance(snapshot, dict) else None


def ask(
    client: StudioClient,
    project_id: str,
    twin_id: str,
    question: str,
    *,
    expected_turn_count: int,
) -> Mapping[str, object]:
    document = client.post(
        f"{conversation_path(project_id, twin_id)}/turns",
        {"question": question, "expected_turn_count": int(expected_turn_count)},
    )
    snapshot = document.get("snapshot") if isinstance(document, dict) else None
    if not isinstance(snapshot, dict):
        raise ApiFailure("API_FAILURE", http_status=201)
    return snapshot


def turns(
    snapshot: Mapping[str, object] | None, twin_version_id: str | None = None
) -> list[Mapping[str, object]]:
    if not isinstance(snapshot, Mapping):
        return []
    if twin_version_id is not None and str(snapshot.get("twin_version_id")) != twin_version_id:
        return []
    items = snapshot.get("turns")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def turn_reply(turn: Mapping[str, object]) -> str:
    value = turn.get("reply")
    return value if isinstance(value, str) else ""


def turn_question(turn: Mapping[str, object]) -> str:
    value = turn.get("question")
    return value if isinstance(value, str) else ""
