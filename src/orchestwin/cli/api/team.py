from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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
PLATFORM_AGENTS: Final = frozenset(AGENTS[:6])
DESIGNER: Final = "UX_UI_DESIGNER"
REASON_CODES: Final = (
    "CATALOG_ALWAYS_PRESENT",
    "CATALOG_MODE_INCOMPATIBLE",
    "CORE_REQUIREMENTS_DISCIPLINE",
    "CORE_USER_CENTERED_DESIGN",
    "CORE_ARCHITECTURE_DISCIPLINE",
    "CORE_QUALITY_DISCIPLINE",
    "CORE_ACCESSIBILITY_DISCIPLINE",
    "BROWNFIELD_INTEGRATION",
    "USER_INTERFACE_SIGNAL",
    "WEB_DELIVERY_SIGNAL",
    "BACKEND_DELIVERY_SIGNAL",
    "MOBILE_DELIVERY_SIGNAL",
    "EXTERNAL_INTEGRATION_SIGNAL",
    "SECURITY_SENSITIVITY_SIGNAL",
    "ACCESSIBILITY_REQUIREMENT_SIGNAL",
    "EXPLICIT_SCOPE_EXCLUSION",
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
MANDATORY: Final = "MANDATORY"
OPTIONAL: Final = "OPTIONAL"
EXCLUDED_KINDS: Final = frozenset({"IMPOSSIBLE", "CONFLICT"})
UPDATED: Final = "UPDATED"
UNCHANGED: Final = "UNCHANGED"
REJECTED: Final = "REJECTED"
MAX_RATIONALE: Final = 2000


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


def edit(
    client: StudioClient,
    project_id: str,
    selected: Sequence[str],
    rationales: Mapping[str, str],
) -> tuple[int, object]:
    body = {
        "selected_agent_ids": ordered(selected),
        "owner_rationales": [
            {"agent_id": agent, "statement": rationales[agent]} for agent in ordered(rationales)
        ],
    }
    return _send(client, "PATCH", f"{project_path(project_id)}/team-proposals/current", body)


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


def constraints(team: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    value = team.get("role_constraints")
    if not isinstance(value, list):
        return {}
    return {
        str(item["agent_id"]): item
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    }


def members(team: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    value = team.get("members")
    if not isinstance(value, list):
        return {}
    return {
        str(item["agent_id"]): item
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("agent_id"), str)
    }


def kind(team: Mapping[str, object], agent: str) -> str | None:
    value = constraints(team).get(agent, {}).get("kind")
    return value if isinstance(value, str) else None


def reason_codes(constraint: Mapping[str, object]) -> list[str]:
    value = constraint.get("reasons")
    if not isinstance(value, list):
        return []
    return [
        str(item["code"])
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("code"), str)
    ]


def issues(document: object) -> list[Mapping[str, object]]:
    value = document.get("issues") if isinstance(document, Mapping) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def version(document: object) -> Mapping[str, object] | None:
    value = document.get("version") if isinstance(document, Mapping) else None
    return value if isinstance(value, Mapping) else None


def _send(
    client: StudioClient, method: str, path: str, body: object | None = None
) -> tuple[int, object]:
    reply = client.request(method, path, body=body)
    return reply.status, reply_body(reply)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
