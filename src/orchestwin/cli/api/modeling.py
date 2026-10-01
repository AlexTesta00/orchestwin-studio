from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

READY: Final = "READY_FOR_REQUIREMENTS_DEFINITION"
PENDING: Final = "PENDING_CONFIRMATION"
CONFIRMED: Final = "CONFIRMED"
REJECTED: Final = "REJECTED"
CONFIRM: Final = "CONFIRM"
REJECT: Final = "REJECT"
TEXT: Final = "TEXT"
ITEMS: Final = "ITEMS"
MAX_REASON: Final = 2000


def modeling_path(project_id: str) -> str:
    return f"/projects/{project_id}/user-modeling"


def proposals_path(project_id: str) -> str:
    return f"{modeling_path(project_id)}/personas/proposals"


def generation_path(project_id: str) -> str:
    return f"{modeling_path(project_id)}/snapshots/generate"


def readiness(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.get(f"{modeling_path(project_id)}/readiness", optional=True)
    return document if isinstance(document, Mapping) else {}


def personas(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"{modeling_path(project_id)}/personas", optional=True)
    if not isinstance(document, list):
        return []
    return [item for item in document if isinstance(item, Mapping)]


def decide(
    client: StudioClient,
    project_id: str,
    persona_id: str,
    decision: str,
    reason: str | None = None,
) -> tuple[int, object]:
    body: dict[str, object] = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    return _send(
        client, "POST", f"{modeling_path(project_id)}/personas/{persona_id}/decision", body
    )


def snapshot(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{modeling_path(project_id)}/snapshots/current", optional=True)
    return document if isinstance(document, Mapping) else None


def gate(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{modeling_path(project_id)}/gate", optional=True)
    return document if isinstance(document, Mapping) else None


def submit_gate(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{modeling_path(project_id)}/gate/submit")


def decide_gate(
    client: StudioClient, project_id: str, action: str = "APPROVE"
) -> tuple[int, object]:
    return _send(client, "POST", f"{modeling_path(project_id)}/gate/decision", {"action": action})


def approved(document: Mapping[str, object]) -> bool:
    return (
        document.get("workflow_state") == READY
        and document.get("approved_current_snapshot") is True
    )


def current_snapshot(document: Mapping[str, object]) -> bool:
    return (
        document.get("snapshot_exists") is True
        and document.get("context_current") is not False
        and document.get("archetypes_current") is not False
    )


def archetypes(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"{modeling_path(project_id)}/archetypes")
    return (
        [item for item in document if isinstance(item, Mapping)]
        if isinstance(document, list)
        else []
    )


def create_archetype(client: StudioClient, project_id: str, body: Mapping[str, object]) -> object:
    return client.post(f"{modeling_path(project_id)}/archetypes", dict(body))


def edit_archetype(
    client: StudioClient, project_id: str, persona_id: str, body: Mapping[str, object]
) -> object:
    return client.patch(f"{modeling_path(project_id)}/archetypes/{persona_id}", dict(body))


def archive_archetype(
    client: StudioClient, project_id: str, persona_id: str, version: int
) -> object:
    from orchestwin.cli.client import payload

    return payload(
        client.request(
            "DELETE",
            f"{modeling_path(project_id)}/archetypes/{persona_id}",
            body={"based_on_version_number": version},
        )
    )


def profile(version: Mapping[str, object]) -> Mapping[str, object]:
    value = version.get("profile")
    return value if isinstance(value, Mapping) else {}


def confirmation(version: Mapping[str, object]) -> str | None:
    value = profile(version).get("confirmation_status")
    return value if isinstance(value, str) else None


def name(version: Mapping[str, object]) -> str:
    value = profile(version).get("name")
    return value if isinstance(value, str) else ""


def observation(version: Mapping[str, object], key: str) -> str | list[str] | None:
    items = profile(version).get("observations")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, Mapping) or item.get("observation_key") != key:
            continue
        value = item.get("value")
        if not isinstance(value, Mapping):
            return None
        if value.get("kind") == TEXT and isinstance(value.get("text"), str):
            return str(value["text"])
        if value.get("kind") == ITEMS and isinstance(value.get("items"), list):
            return [str(entry) for entry in value["items"] if isinstance(entry, str)]
        return None
    return None


def twins(version: Mapping[str, object]) -> list[Mapping[str, object]]:
    body = version.get("snapshot")
    value = body.get("twin_versions") if isinstance(body, Mapping) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)
