from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

READY: Final = "READY_FOR_DESIGN_EXPLORATION"
REQUIRED: Final = "REQUIREMENTS_REQUIRED"
PROPOSED: Final = "PROPOSED"
APPROVE: Final = "APPROVE"
REJECT: Final = "REJECT"
APPLIED: Final = "APPLIED"
UNCHANGED: Final = "REQUIREMENTS_UNCHANGED"
PRIORITIES: Final = ("MUST", "SHOULD", "COULD", "WONT_FOR_NOW")
KINDS: Final = ("FUNCTIONAL", "NON_FUNCTIONAL", "CONSTRAINT")
ARTIFACT_KINDS: Final = (
    "REQUIREMENT",
    "USER_STORY",
    "ACCEPTANCE_CRITERION",
    "SCENARIO",
    "RISK",
    "DEFINITION_OF_DONE",
)
ARTIFACT_KEYS: Final = {
    "REQUIREMENT": "requirement",
    "USER_STORY": "user_story",
    "ACCEPTANCE_CRITERION": "acceptance_criterion",
    "SCENARIO": "scenario",
    "RISK": "risk",
    "DEFINITION_OF_DONE": "definition_of_done",
}
OPERATIONS: Final = ("ADD", "REPLACE", "REMOVE")
MAX_REQUEST: Final = 2000


def requirements_path(project_id: str) -> str:
    return f"/projects/{project_id}/requirements"


def proposals_path(project_id: str) -> str:
    return f"{requirements_path(project_id)}/proposals"


def change_path(project_id: str) -> str:
    return f"{requirements_path(project_id)}/change-requests"


def change_body(request: str) -> dict[str, object]:
    return {"request": request}


def readiness(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.get(f"{requirements_path(project_id)}/readiness", optional=True)
    return document if isinstance(document, Mapping) else {}


def current(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{requirements_path(project_id)}/current", optional=True)
    return document if isinstance(document, Mapping) else None


def revisions(client: StudioClient, project_id: str) -> list[Mapping[str, object]]:
    document = client.get(f"{requirements_path(project_id)}/revisions", optional=True)
    if not isinstance(document, list):
        return []
    return [item for item in document if isinstance(item, Mapping)]


def pending_revision(
    items: list[Mapping[str, object]], version: Mapping[str, object]
) -> Mapping[str, object] | None:
    for item in reversed(items):
        if item.get("status") == PROPOSED and item.get("base_version_id") == version.get("id"):
            return item
    return None


def decide(
    client: StudioClient,
    project_id: str,
    diff_id: str,
    decision: str,
    reason: str | None = None,
) -> tuple[int, object]:
    body: dict[str, object] = {"decision": decision}
    if reason is not None:
        body["reason"] = reason
    return _send(
        client, "POST", f"{requirements_path(project_id)}/revisions/{diff_id}/decision", body
    )


def gate(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    document = client.get(f"{requirements_path(project_id)}/gate", optional=True)
    return document if isinstance(document, Mapping) else None


def submit_gate(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{requirements_path(project_id)}/gate/submit")


def decide_gate(
    client: StudioClient, project_id: str, action: str = "APPROVE"
) -> tuple[int, object]:
    return _send(
        client, "POST", f"{requirements_path(project_id)}/gate/decision", {"action": action}
    )


def specification(version: Mapping[str, object]) -> Mapping[str, object]:
    value = version.get("specification")
    return value if isinstance(value, Mapping) else {}


def entries(version: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = specification(version).get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def artifact(envelope: object) -> Mapping[str, object] | None:
    if not isinstance(envelope, Mapping):
        return None
    key = ARTIFACT_KEYS.get(str(envelope.get("kind")))
    value = envelope.get(key) if key is not None else None
    return value if isinstance(value, Mapping) else None


def operations(diff: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = diff.get("operations")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)
