from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import packages
from orchestwin.cli.errors import ApiFailure

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient

GREENFIELD: Final = "GREENFIELD_GENERATION"
STAGES: Final = ("brief", "team", "twins", "requirements", "design", "package")
APPROVED: Final = "APPROVED"
WAITING: Final = "WAITING"
TODO: Final = "TODO"
LATER: Final = "LATER"
READY: Final = "READY"
STAGE_CODES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "brief": "BRIEF",
        "team": "TEAM",
        "twins": "USER_TWINS",
        "requirements": "REQUIREMENTS",
        "design": "DESIGN",
        "package": "PACKAGE",
    }
)
STAGE_ACTIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "BRIEF": "APPROVE_BRIEF",
        "TEAM": "APPROVE_TEAM",
        "USER_TWINS": "CONFIRM_TWINS",
        "REQUIREMENTS": "APPROVE_REQUIREMENTS",
        "DESIGN": "APPROVE_DESIGN",
        "PACKAGE": "DOWNLOAD_FOLDER",
    }
)
NEXT_COMMANDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "DESCRIBE_IDEA": "ut init",
        "APPROVE_BRIEF": "ut init",
        "APPROVE_TEAM": "ut init",
        "CONFIRM_TWINS": "ut init",
        "APPROVE_REQUIREMENTS": "ut init",
        "APPROVE_DESIGN": "ut design",
        "DOWNLOAD_FOLDER": "ut package publish",
    }
)


@dataclass(frozen=True, slots=True)
class StepState:
    stage: str
    state: str
    version: int | None
    approved: bool


def list_projects(client: StudioClient) -> list[Mapping[str, object]]:
    document = client.get("/projects")
    if not isinstance(document, list):
        return []
    return [item for item in document if isinstance(item, dict)]


def get_project(client: StudioClient, project_id: str) -> Mapping[str, object]:
    document = client.get(f"/projects/{project_id}")
    if not isinstance(document, dict):
        raise ApiFailure("API_FAILURE", http_status=200)
    return document


def create_project(
    client: StudioClient,
    display_name: str,
    *,
    mode: str = GREENFIELD,
) -> Mapping[str, object]:
    document = client.post("/projects", {"display_name": display_name, "mode": mode})
    if not isinstance(document, dict) or not isinstance(document.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=201)
    return document


def step_states(client: StudioClient, project_id: str) -> tuple[StepState, ...]:
    base = f"/projects/{project_id}"
    brief = _read(client, f"{base}/brief-versions/current")
    brief_gate = _read(client, f"{base}/gates/project-brief/current")
    team = _read(client, f"{base}/team-proposals/current")
    team_gate = _read(client, f"{base}/gates/agent-team/current")
    readiness = _read(client, f"{base}/readiness")
    twins = _read(client, f"{base}/user-modeling/readiness")
    requirements = _read(client, f"{base}/requirements/readiness")
    design = _read(client, f"{base}/design/readiness")
    folder = latest_folder_version(client, project_id)
    requirements_version = _mapping(requirements.get("version"))
    design_version = _mapping(design.get("version"))
    team_approved = (
        bool(team)
        and bool(brief)
        and readiness.get("status") == "READY_FOR_MAIN_WORKFLOW"
        and team.get("brief_version_number") == brief.get("version_number")
        and team.get("brief_content_hash") == brief.get("content_hash")
        and approves(team_gate, team)
    )
    twins_approved = (
        twins.get("workflow_state") == "READY_FOR_REQUIREMENTS_DEFINITION"
        and twins.get("approved_current_snapshot") is True
    )
    requirements_approved = requirements.get(
        "status"
    ) == "READY_FOR_DESIGN_EXPLORATION" and approves(
        _mapping(requirements.get("gate")), requirements_version
    )
    design_approved = design.get("status") == "READY_FOR_ARCHITECTURE_PLANNING" and approves(
        _mapping(design.get("gate")), design_version
    )
    return arrange(
        (
            ("brief", version_number(brief), approves(brief_gate, brief)),
            ("team", version_number(team), team_approved),
            ("twins", _integer(twins.get("snapshot_version_number")), twins_approved),
            ("requirements", version_number(requirements_version), requirements_approved),
            ("design", version_number(design_version), design_approved),
            ("package", folder, design_approved),
        )
    )


def arrange(facts: Sequence[tuple[str, int | None, bool]]) -> tuple[StepState, ...]:
    current = next(
        (index for index, (_, _, approved) in enumerate(facts) if not approved),
        len(facts) - 1,
    )
    states: list[StepState] = []
    for index, (stage, version, approved) in enumerate(facts):
        if index < current:
            state = APPROVED
        elif index > current:
            state = LATER
        elif stage == "package":
            state = READY
        else:
            state = WAITING if version is not None else TODO
        states.append(StepState(stage=stage, state=state, version=version, approved=approved))
    return tuple(states)


def current_stage(steps: Sequence[StepState]) -> str:
    for step in steps:
        if step.state != APPROVED:
            return STAGE_CODES[step.stage]
    return STAGE_CODES["package"]


def approves(gate: Mapping[str, object], version: Mapping[str, object]) -> bool:
    artifact = gate.get("artifact")
    return (
        bool(version)
        and gate.get("status") == APPROVED
        and isinstance(artifact, Mapping)
        and artifact.get("artifact_id") is not None
        and artifact.get("artifact_id") == version.get("id")
        and artifact.get("content_hash") == version.get("content_hash")
    )


def latest_folder_version(client: StudioClient, project_id: str) -> int | None:
    try:
        latest = packages.latest(client, project_id)
    except ApiFailure as failure:
        if failure.http_status == 404 or failure.http_status >= 500:
            return None
        raise
    return None if latest is None else _integer(latest.get("version_number"))


def version_number(document: Mapping[str, object]) -> int | None:
    return _integer(document.get("version_number"))


def _read(client: StudioClient, path: str) -> Mapping[str, object]:
    return _mapping(client.get(path, optional=True))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
