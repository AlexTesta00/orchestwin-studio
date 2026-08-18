"""API contract tests for the agent catalog, team proposals, and Gate 2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    all_agent_catalog_entries,
)
from orchestwin.agents.proposals import (
    TeamProposalApplicationResult,
    TeamProposalApplicationStatus,
    TeamProposalRevisionKind,
    TeamProposalVersion,
)
from orchestwin.agents.selection_rules import (
    determine_team_constraints,
)
from orchestwin.agents.team_gate import (
    AgentTeamGateDecisionResult,
    AgentTeamGateDecisionStatus,
    AgentTeamGateSubmissionResult,
    AgentTeamGateSubmissionStatus,
    OwnerAgentRationale,
    ProjectWorkflowReadiness,
    TeamEditResult,
    TeamEditStatus,
    agent_team_artifact_reference,
    agent_team_gate_is_currently_approved,
)
from orchestwin.api.app import create_app
from orchestwin.api.auth import (
    AuthApiSettings,
)
from orchestwin.api.services import (
    ApplicationRuntime,
)
from orchestwin.config import (
    ApplicationSettings,
    RuntimeEnvironment,
)
from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalRequest,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
INITIAL_PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000030")
EDITED_PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000031")
GATE_ID = UUID("00000000-0000-4000-8000-000000000040")
SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000041")
APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000042")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)

_AGENT_ORDER = tuple(entry.agent_id for entry in all_agent_catalog_entries())


def build_user() -> UserAccount:
    """Create the authenticated API user."""
    return UserAccount(
        id=USER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


async def build_initial_team_version() -> TeamProposalVersion:
    """Create one deterministic generated team-proposal version."""
    provided_fields = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
    }
    brief = create_project_brief(
        name="Agent Team API project",
        description=("A Vue web application with a FastAPI backend."),
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
        ],
        unknown_fields=[field for field in BriefField if field not in provided_fields],
    )
    brief_version = ProjectBriefVersion(
        id=BRIEF_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )
    generation = await FakeDeterministicTeamProposalAdapter().propose(
        TeamProposalRequest(
            project_mode=(ProjectMode.GREENFIELD_GENERATION),
            brief_version=brief_version,
            constraints=constraints,
        )
    )

    assert generation.proposal is not None

    return TeamProposalVersion(
        id=INITIAL_PROPOSAL_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=generation.proposal,
        revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED),
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


@dataclass(slots=True)
class FakeTeamState:
    """Shared mutable state for API service doubles."""

    current_version: TeamProposalVersion
    history: list[TeamProposalVersion]
    generated: bool = False
    gate: HumanGate | None = None
    events: list[HumanGateEvent] | None = None

    def __post_init__(self) -> None:
        """Initialize mutable event storage explicitly."""
        if self.events is None:
            self.events = []


class FakeIdentityService:
    """Identity service double used by bearer dependencies."""

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        """Return the authenticated fixture user."""
        if access_token != "valid-access-token":
            return None

        return build_user()


class FakeTeamProposalService:
    """Versioned team-proposal application-service double."""

    def __init__(
        self,
        state: FakeTeamState,
    ) -> None:
        self._state = state

    async def generate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalApplicationResult:
        """Return the deterministic generated proposal."""
        del project_id
        del owner_user_id

        status_value = (
            TeamProposalApplicationStatus.UNCHANGED
            if self._state.generated
            else TeamProposalApplicationStatus.CREATED
        )
        self._state.generated = True

        return TeamProposalApplicationResult(
            status=status_value,
            version=(self._state.current_version),
        )

    async def current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> TeamProposalVersion | None:
        """Return the shared current proposal."""
        del project_id
        del owner_user_id

        return self._state.current_version

    async def history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[
        TeamProposalVersion,
        ...,
    ]:
        """Return the shared immutable proposal history."""
        del project_id
        del owner_user_id

        return tuple(self._state.history)


class FakeAgentTeamApprovalService:
    """Owner editing, Gate 2, and readiness service double."""

    def __init__(
        self,
        state: FakeTeamState,
    ) -> None:
        self._state = state

    async def edit_current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        selected_agent_ids,
        owner_rationales=(),
    ) -> TeamEditResult:
        """Create one deterministic owner-edited proposal."""
        del project_id

        selected = set(selected_agent_ids)
        current = self._state.current_version
        current_members = {member.agent_id: member for member in current.proposal.members}
        rationales = {rationale.agent_id: rationale for rationale in owner_rationales}

        if selected == set(current.proposal.selected_agent_ids):
            return TeamEditResult(
                status=TeamEditStatus.UNCHANGED,
                version=current,
            )

        members: list[ProposedTeamMember] = []

        for agent_id in _AGENT_ORDER:
            if agent_id not in selected:
                continue

            existing = current_members.get(agent_id)

            if existing is not None:
                members.append(existing)
                continue

            rationale: OwnerAgentRationale = rationales[agent_id]
            members.append(
                ProposedTeamMember(
                    agent_id=agent_id,
                    source=(TeamProposalMemberSource.OWNER_ADDED),
                    justifications=(
                        TeamProposalJustification(
                            kind=(TeamProposalJustificationKind.OWNER_RATIONALE),
                            code=("OWNER_SELECTED_ROLE"),
                            statement=(rationale.statement),
                        ),
                    ),
                )
            )

        edited_proposal = replace(
            current.proposal,
            members=tuple(members),
        )
        edited_version = TeamProposalVersion(
            id=EDITED_PROPOSAL_ID,
            project_id=PROJECT_ID,
            version_number=(current.version_number + 1),
            proposal=edited_proposal,
            revision_kind=(TeamProposalRevisionKind.OWNER_EDITED),
            based_on_version_number=(current.version_number),
            created_by_user_id=(owner_user_id),
            created_at=(NOW + timedelta(minutes=1)),
        )
        self._state.current_version = edited_version
        self._state.history.append(edited_version)

        return TeamEditResult(
            status=TeamEditStatus.UPDATED,
            version=edited_version,
        )

    async def submit_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> AgentTeamGateSubmissionResult:
        """Submit the shared current proposal to Gate 2."""
        if (
            self._state.gate is not None
            and self._state.gate.artifact
            == agent_team_artifact_reference(self._state.current_version)
        ):
            existing_status = (
                AgentTeamGateSubmissionStatus.ALREADY_APPROVED
                if self._state.gate.status is HumanGateStatus.APPROVED
                else AgentTeamGateSubmissionStatus.ALREADY_PENDING
            )

            return AgentTeamGateSubmissionResult(
                status=existing_status,
                gate=self._state.gate,
            )

        draft = create_human_gate(
            gate_id=GATE_ID,
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_type=(HumanGateType.AGENT_TEAM),
            artifact=(agent_team_artifact_reference(self._state.current_version)),
            created_at=(NOW + timedelta(minutes=2)),
        )
        submitted = transition_human_gate(
            draft,
            action=HumanGateAction.SUBMIT,
            actor_user_id=owner_user_id,
            occurred_at=(NOW + timedelta(minutes=2)),
            event_id=SUBMIT_EVENT_ID,
        )

        assert submitted.status is (HumanGateTransitionStatus.APPLIED)
        assert submitted.event is not None

        self._state.gate = submitted.gate
        assert self._state.events is not None
        self._state.events.append(submitted.event)

        return AgentTeamGateSubmissionResult(
            status=(AgentTeamGateSubmissionStatus.SUBMITTED),
            gate=submitted.gate,
            events=(submitted.event,),
        )

    async def decide_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> AgentTeamGateDecisionResult:
        """Apply one deterministic Gate 2 decision."""
        del project_id

        if self._state.gate is None:
            return AgentTeamGateDecisionResult(status=(AgentTeamGateDecisionStatus.GATE_NOT_FOUND))

        transition = transition_human_gate(
            self._state.gate,
            action=action,
            actor_user_id=owner_user_id,
            occurred_at=(NOW + timedelta(minutes=3)),
            reason=reason,
            event_id=APPROVE_EVENT_ID,
        )

        if transition.status is not HumanGateTransitionStatus.APPLIED or transition.event is None:
            return AgentTeamGateDecisionResult(
                status=(AgentTeamGateDecisionStatus.REJECTED),
                gate=self._state.gate,
                issue=transition.issue,
            )

        self._state.gate = transition.gate
        assert self._state.events is not None
        self._state.events.append(transition.event)

        return AgentTeamGateDecisionResult(
            status=(AgentTeamGateDecisionStatus.APPLIED),
            gate=transition.gate,
            event=transition.event,
        )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectWorkflowReadiness:
        """Return readiness derived from the shared Gate 2 state."""
        del project_id
        del owner_user_id

        if agent_team_gate_is_currently_approved(
            self._state.gate,
            self._state.current_version,
        ):
            return ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW

        return ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the shared current Gate 2."""
        del project_id
        del owner_user_id

        return self._state.gate

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Return ordered Gate 2 events."""
        del project_id
        del owner_user_id

        if self._state.gate is None or self._state.gate.id != gate_id or self._state.events is None:
            return ()

        return tuple(self._state.events)


def build_client(
    *,
    include_team_services: bool = True,
) -> tuple[
    TestClient,
    FakeTeamState,
]:
    """Create a client with explicit deterministic service doubles."""
    initial = asyncio.run(build_initial_team_version())
    state = FakeTeamState(
        current_version=initial,
        history=[
            initial,
        ],
    )
    runtime = ApplicationRuntime(
        identity_service=(FakeIdentityService()),
        team_proposal_service=(FakeTeamProposalService(state) if include_team_services else None),
        agent_team_service=(FakeAgentTeamApprovalService(state) if include_team_services else None),
    )
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        api_prefix="/api/v1",
        cors_allowed_origins=("http://127.0.0.1:5173",),
        _env_file=None,
    )

    return (
        TestClient(
            create_app(
                settings,
                runtime=runtime,
                auth_settings=AuthApiSettings(_env_file=None),
            )
        ),
        state,
    )


def authorization_header() -> dict[str, str]:
    """Return a valid bearer header."""
    return {"Authorization": ("Bearer valid-access-token")}


def test_agent_catalog_requires_authentication() -> None:
    """Reject anonymous access to the fixed agent catalog."""
    client, _ = build_client()

    with client:
        response = client.get("/api/v1/agent-catalog")

    assert response.status_code == 401


def test_agent_catalog_exposes_versioned_fixed_roles() -> None:
    """Expose all fixed roles with version and fingerprint."""
    client, _ = build_client()

    with client:
        response = client.get(
            "/api/v1/agent-catalog",
            headers=authorization_header(),
        )

    assert response.status_code == 200

    payload = response.json()

    assert payload["catalog_version"] == AGENT_CATALOG_VERSION
    assert payload["content_hash"] == AGENT_CATALOG_CONTENT_HASH
    assert len(payload["agents"]) == 17
    assert payload["agents"][0]["agent_id"] == "WORKFLOW_ORCHESTRATOR"
    assert payload["agents"][0]["selection_policy"] == "ALWAYS_PRESENT"


def test_generate_and_read_versioned_team_proposal() -> None:
    """Expose generation, current version, and immutable history."""
    client, _ = build_client()

    with client:
        generated = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/team-proposals"),
            headers=authorization_header(),
        )
        current = client.get(
            (f"/api/v1/projects/{PROJECT_ID}/team-proposals/current"),
            headers=authorization_header(),
        )
        history = client.get(
            (f"/api/v1/projects/{PROJECT_ID}/team-proposals"),
            headers=authorization_header(),
        )

    assert generated.status_code == 201
    assert generated.json()["status"] == "CREATED"
    assert generated.json()["version"]["version_number"] == 1
    assert generated.json()["version"]["provider_kind"] == "FAKE_DETERMINISTIC"
    assert generated.json()["version"]["role_constraints"]

    assert current.status_code == 200
    assert current.json()["content_hash"] == generated.json()["version"]["content_hash"]

    assert history.status_code == 200
    assert len(history.json()) == 1


def test_owner_adds_optional_agent_in_new_version() -> None:
    """Expose owner rationale and immutable edited lineage."""
    client, state = build_client()
    initial_agent_ids = [
        agent_id.value for agent_id in state.current_version.proposal.selected_agent_ids
    ]

    with client:
        response = client.patch(
            (f"/api/v1/projects/{PROJECT_ID}/team-proposals/current"),
            headers=authorization_header(),
            json={
                "selected_agent_ids": [
                    *initial_agent_ids,
                    "MOBILE_ENGINEER",
                ],
                "owner_rationales": [
                    {
                        "agent_id": ("MOBILE_ENGINEER"),
                        "statement": ("The owner wants an optional mobile companion."),
                    }
                ],
            },
        )

    assert response.status_code == 201

    payload = response.json()

    assert payload["status"] == "UPDATED"
    assert payload["version"]["version_number"] == 2
    assert payload["version"]["revision_kind"] == "OWNER_EDITED"
    assert payload["version"]["based_on_version_number"] == 1

    mobile = next(
        member
        for member in payload["version"]["members"]
        if member["agent_id"] == "MOBILE_ENGINEER"
    )

    assert mobile["source"] == "OWNER_ADDED"
    assert mobile["justifications"][0]["kind"] == "OWNER_RATIONALE"


def test_gate_two_approval_exposes_readiness_and_events() -> None:
    """Submit, approve, audit, and derive workflow readiness."""
    client, _ = build_client()

    with client:
        submitted = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/gates/agent-team/submit"),
            headers=authorization_header(),
        )
        gate_id = submitted.json()["gate"]["id"]
        current = client.get(
            (f"/api/v1/projects/{PROJECT_ID}/gates/agent-team/current"),
            headers=authorization_header(),
        )
        approved = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/gates/agent-team/decisions"),
            headers=authorization_header(),
            json={"action": "APPROVE"},
        )
        events = client.get(
            (f"/api/v1/projects/{PROJECT_ID}/gates/agent-team/{gate_id}/events"),
            headers=authorization_header(),
        )
        readiness = client.get(
            (f"/api/v1/projects/{PROJECT_ID}/readiness"),
            headers=authorization_header(),
        )

    assert submitted.status_code == 201
    assert submitted.json()["gate"]["status"] == "PENDING_APPROVAL"

    assert current.status_code == 200
    assert current.json()["id"] == gate_id

    assert approved.status_code == 200
    assert approved.json()["gate"]["status"] == "APPROVED"

    assert events.status_code == 200
    assert [event["kind"] for event in events.json()] == [
        "SUBMIT",
        "APPROVE",
    ]

    assert readiness.status_code == 200
    assert readiness.json()["status"] == "READY_FOR_MAIN_WORKFLOW"


def test_team_routes_return_service_unavailable_without_runtime() -> None:
    """Expose missing runtime composition without hidden exceptions."""
    client, _ = build_client(include_team_services=False)

    with client:
        response = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/team-proposals"),
            headers=authorization_header(),
        )

    assert response.status_code == 503
    assert response.json() == {"detail": ("team_proposal_service_unavailable")}
