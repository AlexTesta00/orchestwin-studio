from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.jobs import reply_body

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

AGENTS: Final = (
    "WORKFLOW_ORCHESTRATOR",
    "INTAKE_CLARIFICATION_AGENT",
    "TEAM_SELECTOR",
    "HUMAN_GATE_CONTROLLER",
    "ARTIFACT_MANAGER",
    "SANDBOX_CONTROLLER",
    "REQUIREMENTS_ANALYST",
    "UX_RESEARCHER_USER_MODELER",
    "UX_UI_DESIGNER",
    "SOFTWARE_ARCHITECT",
    "FRONTEND_ENGINEER",
    "BACKEND_ENGINEER",
    "MOBILE_ENGINEER",
    "QA_TEST_ENGINEER",
    "SECURITY_REVIEWER",
    "ACCESSIBILITY_REVIEWER",
    "INTEGRATION_ENGINEER",
)
DESIGNER: Final = "UX_UI_DESIGNER"
PERSPECTIVES: Final = ("UX", "ACCESSIBILITY", "SOFTWARE_ENGINEERING", "PRODUCT", "SECURITY")
ASPECTS: Final = ("WEB", "SERVICES", "MOBILE", "INTEGRATIONS")
STANDINGS: Final = ("ALWAYS", "REQUIRED", "OPTIONAL", "EXCLUDED", "CONTESTED")
REQUIRED: Final = "REQUIRED"
OPTIONAL: Final = "OPTIONAL"
EXCLUDED: Final = "EXCLUDED"
CONTESTED: Final = "CONTESTED"
UNIT_AGENTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "UX": ("UX_RESEARCHER_USER_MODELER", "UX_UI_DESIGNER"),
        "ACCESSIBILITY": ("ACCESSIBILITY_REVIEWER",),
        "SOFTWARE_ENGINEERING": ("SOFTWARE_ARCHITECT", "QA_TEST_ENGINEER"),
        "PRODUCT": ("REQUIREMENTS_ANALYST",),
        "SECURITY": ("SECURITY_REVIEWER",),
        "WEB": ("FRONTEND_ENGINEER",),
        "SERVICES": ("BACKEND_ENGINEER",),
        "MOBILE": ("MOBILE_ENGINEER",),
        "INTEGRATIONS": ("INTEGRATION_ENGINEER",),
    }
)
EDIT_ISSUES: Final = (
    "DUPLICATE_AGENT",
    "DUPLICATE_RATIONALE",
    "MANDATORY_AGENT_MISSING",
    "AGENT_NOT_SELECTABLE",
    "RATIONALE_REQUIRED",
    "UNUSED_RATIONALE",
)
READY: Final = "READY_FOR_MAIN_WORKFLOW"
PROPOSAL_REQUIRED: Final = "TEAM_PROPOSAL_REQUIRED"
APPROVAL_REQUIRED: Final = "TEAM_APPROVAL_REQUIRED"
BLOCKED: Final = "BLOCKED_BY_CONSTRAINTS"
UPDATED: Final = "UPDATED"
UNCHANGED: Final = "UNCHANGED"
REJECTED: Final = "REJECTED"


def project_path(project_id: str) -> str:
    return f"/projects/{project_id}"


def current(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    return _mapping(client.get(f"{project_path(project_id)}/team-proposals/current", optional=True))


def readiness(client: StudioClient, project_id: str) -> str | None:
    document = client.get(f"{project_path(project_id)}/readiness", optional=True)
    value = document.get("status") if isinstance(document, Mapping) else None
    return value if isinstance(value, str) else None


def gate(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    return _mapping(
        client.get(f"{project_path(project_id)}/gates/agent-team/current", optional=True)
    )


def propose(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{project_path(project_id)}/team-proposals")


def edit(client: StudioClient, project_id: str, selected: Sequence[str]) -> tuple[int, object]:
    body = {"selected_agent_ids": ordered(selected)}
    return _send(client, "PATCH", f"{project_path(project_id)}/team-proposals/current", body)


def owner_proposal(
    client: StudioClient, project_id: str, selected: Sequence[str]
) -> tuple[int, object]:
    body = {"selected_agent_ids": ordered(selected)}
    return _send(client, "POST", f"{project_path(project_id)}/team/owner-proposals", body)


def submit_gate(client: StudioClient, project_id: str) -> tuple[int, object]:
    return _send(client, "POST", f"{project_path(project_id)}/gates/agent-team/submit")


def decide_gate(
    client: StudioClient, project_id: str, action: str = "APPROVE"
) -> tuple[int, object]:
    return _send(
        client,
        "POST",
        f"{project_path(project_id)}/gates/agent-team/decisions",
        {"action": action},
    )


def ordered(agents: Iterable[str]) -> list[str]:
    unique = list(dict.fromkeys(agents))
    known = [agent for agent in AGENTS if agent in unique]
    return known + [agent for agent in unique if agent not in AGENTS]


def selected(team: Mapping[str, object]) -> list[str]:
    value = team.get("selected_agent_ids")
    if not isinstance(value, list):
        return []
    return ordered(str(agent) for agent in value if isinstance(agent, str))


def switched(chosen: Sequence[str], agent: str) -> list[str]:
    if agent in chosen:
        return [item for item in chosen if item != agent]
    return ordered([*chosen, agent])


def perspectives(team: Mapping[str, object]) -> list[Mapping[str, object]] | None:
    found = _units(team.get("perspectives"))
    return found or None


def aspects(perspective: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _units(perspective.get("aspects"))


def switchable(views: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        unit
        for perspective in views
        for unit in (perspective, *aspects(perspective))
        if unit.get("editable") is True and isinstance(unit.get("agent_id"), str)
    ]


def unit_of(agent: str) -> str | None:
    return next((key for key, agents in UNIT_AGENTS.items() if agent in agents), None)


def issues(document: object) -> list[Mapping[str, object]]:
    value = document.get("issues") if isinstance(document, Mapping) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def version(document: object) -> Mapping[str, object] | None:
    value = document.get("version") if isinstance(document, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _units(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        item for item in value if isinstance(item, Mapping) and isinstance(item.get("key"), str)
    ]


def _send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
