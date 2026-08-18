"""API contract tests for User Modeling and Gate 3."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.user_modeling import (
    GateApiOutcome,
    GateApiResult,
    UserModelingApiDependencies,
    create_user_modeling_router,
)
from orchestwin.twins.application import (
    GroundedSnapshotGenerationResult,
    PersonaDecisionApplicationResult,
    PersonaOwnerDecision,
    PersonaProposalApplicationResult,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ProfileObservation,
)
from orchestwin.twins.revision_application import (
    ProfileRevisionApplicationResult,
    ProfileRevisionApplicationStatus,
    ProfileRevisionDecision,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateType,
    create_human_gate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
PERSONA_ID = UUID("00000000-0000-4000-8000-000000000020")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000030")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000040")
GATE_ID = UUID("00000000-0000-4000-8000-000000000050")
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000060")

CREATED_AT = datetime(
    2026,
    8,
    13,
    15,
    0,
    tzinfo=UTC,
)


async def owner_dependency() -> UUID:
    """Return the authenticated owner fixture."""
    return OWNER_ID


class FakeCommands:
    """Record User Modeling application commands."""

    def __init__(self) -> None:
        """Initialize captured calls."""
        self.proposal_calls: list[
            tuple[
                UUID,
                UUID,
            ]
        ] = []

        self.persona_decisions: list[
            tuple[
                UUID,
                UUID,
                UUID,
                PersonaOwnerDecision,
                str | None,
            ]
        ] = []

        self.snapshot_calls: list[
            tuple[
                UUID,
                UUID,
            ]
        ] = []

        self.proposal_result = PersonaProposalApplicationResult(
            status=(UserModelingApplicationStatus.CREATED)
        )

        self.persona_result = PersonaDecisionApplicationResult(
            status=(UserModelingApplicationStatus.NO_CHANGE)
        )

        self.snapshot_result = GroundedSnapshotGenerationResult(
            status=(UserModelingApplicationStatus.CREATED)
        )

    async def propose_personas(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersonaProposalApplicationResult:
        """Capture persona proposal command."""
        self.proposal_calls.append(
            (
                owner_user_id,
                project_id,
            )
        )

        return self.proposal_result

    async def decide_persona(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        persona_id: UUID,
        decision: PersonaOwnerDecision,
        reason: str | None = None,
    ) -> PersonaDecisionApplicationResult:
        """Capture persona decision command."""
        self.persona_decisions.append(
            (
                owner_user_id,
                project_id,
                persona_id,
                decision,
                reason,
            )
        )

        return self.persona_result

    async def generate_grounded_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GroundedSnapshotGenerationResult:
        """Capture User Twin generation command."""
        self.snapshot_calls.append(
            (
                owner_user_id,
                project_id,
            )
        )

        return self.snapshot_result


class FakeRevisions:
    """Record User Twin profile revision commands."""

    def __init__(self) -> None:
        """Initialize captured calls."""
        self.proposals: list[
            tuple[
                UUID,
                UUID,
                UUID,
                dict[
                    UserTwinField,
                    ProfileObservation,
                ],
            ]
        ] = []

        self.decisions: list[
            tuple[
                UUID,
                UUID,
                UUID,
                ProfileRevisionDecision,
                str | None,
            ]
        ] = []

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        twin_id: UUID,
        replacements: dict[
            UserTwinField,
            ProfileObservation,
        ],
    ) -> ProfileRevisionApplicationResult:
        """Capture a revision proposal."""
        self.proposals.append(
            (
                owner_user_id,
                project_id,
                twin_id,
                replacements,
            )
        )

        return ProfileRevisionApplicationResult(status=(ProfileRevisionApplicationStatus.CREATED))

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ProfileRevisionDecision,
        reason: str | None = None,
    ) -> ProfileRevisionApplicationResult:
        """Capture a diff decision."""
        self.decisions.append(
            (
                owner_user_id,
                project_id,
                diff_id,
                decision,
                reason,
            )
        )

        return ProfileRevisionApplicationResult(status=(ProfileRevisionApplicationStatus.APPLIED))


def gate_fixture() -> HumanGate:
    """Create one Gate 3 fixture."""
    return create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.USER_MODELING),
        artifact=(
            GateArtifactReference(
                project_id=PROJECT_ID,
                gate_type=(HumanGateType.USER_MODELING),
                artifact_id=SNAPSHOT_ID,
                version=1,
                content_hash="a" * 64,
            )
        ),
        created_at=CREATED_AT,
    )


class FakeGates:
    """Minimal Gate 3 API adapter fixture."""

    def __init__(self) -> None:
        """Create one deterministic gate."""
        self.gate = gate_fixture()

        self.submit_calls: list[
            tuple[
                UUID,
                UUID,
            ]
        ] = []

        self.decisions: list[
            tuple[
                UUID,
                UUID,
                HumanGateAction,
                str | None,
            ]
        ] = []

    async def submit(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GateApiResult:
        """Capture Gate 3 submission."""
        self.submit_calls.append(
            (
                owner_user_id,
                project_id,
            )
        )

        return GateApiResult(
            outcome=(GateApiOutcome.APPLIED),
            gate=self.gate,
        )

    async def decide(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> GateApiResult:
        """Capture Gate 3 owner action."""
        self.decisions.append(
            (
                owner_user_id,
                project_id,
                action,
                reason,
            )
        )

        return GateApiResult(
            outcome=(GateApiOutcome.APPLIED),
            gate=self.gate,
        )

    async def current_gate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> HumanGate | None:
        """Return current Gate 3."""
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None

        return self.gate

    async def gate_events(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple:
        """Return no events for the draft fixture."""
        del owner_user_id
        del project_id

        return ()


class FakeQueries:
    """Minimal owner-scoped User Modeling query adapter."""

    def __init__(self) -> None:
        """Create empty read state."""
        self.snapshot: UserModelingSnapshotVersion | None = None

    async def current_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Return the configured current snapshot."""
        del owner_user_id
        del project_id

        return self.snapshot

    async def snapshot_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[
        UserModelingSnapshotVersion,
        ...,
    ]:
        """Return current snapshot as history when present."""
        del owner_user_id
        del project_id

        if self.snapshot is None:
            return ()

        return (self.snapshot,)

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ):
        """Return no diff in the generic API fixture."""
        del owner_user_id
        del project_id
        del diff_id

        return None


def build_dependencies() -> tuple[
    UserModelingApiDependencies,
    FakeCommands,
    FakeRevisions,
    FakeGates,
    FakeQueries,
]:
    """Create deterministic User Modeling API dependencies."""
    commands = FakeCommands()
    revisions = FakeRevisions()
    gates = FakeGates()
    queries = FakeQueries()

    dependencies = UserModelingApiDependencies(
        commands=commands,
        revisions=revisions,
        gates=gates,
        queries=queries,
        owner_user_id_dependency=(owner_dependency),
    )

    return (
        dependencies,
        commands,
        revisions,
        gates,
        queries,
    )


def client_fixture() -> tuple[
    TestClient,
    FakeCommands,
    FakeRevisions,
    FakeGates,
    FakeQueries,
]:
    """Create one isolated FastAPI app with injected test services."""
    (
        dependencies,
        commands,
        revisions,
        gates,
        queries,
    ) = build_dependencies()

    app = FastAPI()

    app.include_router(create_user_modeling_router(dependencies))

    return (
        TestClient(app),
        commands,
        revisions,
        gates,
        queries,
    )


def project_path(
    suffix: str,
) -> str:
    """Return one project-scoped User Modeling URL."""
    return f"/projects/{PROJECT_ID}/user-modeling{suffix}"


def test_persona_proposal_endpoint_uses_authenticated_owner() -> None:
    """Forward project and owner identity to C09."""
    (
        client,
        commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.post(project_path("/personas/proposals"))

    assert response.status_code == 200

    assert response.json() == {
        "status": "CREATED",
        "issue": None,
        "candidate_issue": None,
        "proposal_issue": None,
        "versions": [],
    }

    assert commands.proposal_calls == [
        (
            OWNER_ID,
            PROJECT_ID,
        )
    ]


def test_persona_decision_endpoint_preserves_reason() -> None:
    """Expose explicit owner confirmation through typed input."""
    (
        client,
        commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.post(
        project_path(f"/personas/{PERSONA_ID}/decision"),
        json={
            "decision": "CONFIRM",
            "reason": ("This target user is in project scope."),
        },
    )

    assert response.status_code == 200

    assert commands.persona_decisions == [
        (
            OWNER_ID,
            PROJECT_ID,
            PERSONA_ID,
            PersonaOwnerDecision.CONFIRM,
            ("This target user is in project scope."),
        )
    ]


def test_application_not_found_maps_to_http_404() -> None:
    """Do not expose missing or foreign projects as successful commands."""
    (
        client,
        commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    commands.proposal_result = PersonaProposalApplicationResult(
        status=(UserModelingApplicationStatus.REJECTED),
        issue=(UserModelingApplicationIssueCode.PROJECT_NOT_FOUND),
    )

    response = client.post(project_path("/personas/proposals"))

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": ("PROJECT_NOT_FOUND")}}


def test_state_conflict_maps_to_http_409() -> None:
    """Represent stale/governance blockers as conflicts."""
    (
        client,
        commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    commands.snapshot_result = GroundedSnapshotGenerationResult(
        status=(UserModelingApplicationStatus.REJECTED),
        issue=(UserModelingApplicationIssueCode.PERSONA_CONFIRMATION_REQUIRED),
    )

    response = client.post(project_path("/snapshots/generate"))

    assert response.status_code == 409

    assert response.json() == {"detail": {"code": ("PERSONA_CONFIRMATION_REQUIRED")}}


def test_profile_revision_endpoint_preserves_epistemic_metadata() -> None:
    """Do not flatten provenance/status/confidence at the HTTP boundary."""
    (
        client,
        _commands,
        revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.post(
        project_path(f"/twins/{TWIN_ID}/revisions"),
        json={
            "replacements": [
                {
                    "field": "goals",
                    "value": {
                        "kind": "ITEMS",
                        "text": None,
                        "items": [
                            "Reduce booking errors",
                        ],
                        "reason": None,
                    },
                    "epistemic_status": ("USER_PROVIDED"),
                    "confidence": 1.0,
                    "provenance": [
                        {
                            "source_kind": ("OWNER_INPUT"),
                            "source_id": str(OWNER_ID),
                            "source_version": 1,
                            "content_hash": None,
                            "locator": ("user_twin.goals"),
                            "summary": ("Owner supplied this revision."),
                        }
                    ],
                    "human_validation": ("NOT_REQUIRED"),
                    "rationale": None,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert len(revisions.proposals) == 1

    (
        owner_id,
        project_id,
        twin_id,
        replacements,
    ) = revisions.proposals[0]

    assert owner_id == OWNER_ID
    assert project_id == PROJECT_ID
    assert twin_id == TWIN_ID

    observation = replacements[UserTwinField.GOALS]

    assert observation.epistemic_status is EpistemicStatus.USER_PROVIDED
    assert observation.confidence.value == 1.0

    reference = observation.provenance.references[0]

    assert reference.source_kind is (EvidenceSourceKind.OWNER_INPUT)
    assert observation.human_validation is HumanValidationRequirement.NOT_REQUIRED


def test_duplicate_profile_replacement_fields_are_rejected() -> None:
    """Keep one unambiguous operation per User Twin field."""
    (
        client,
        _commands,
        revisions,
        _gates,
        _queries,
    ) = client_fixture()

    replacement = {
        "field": "goals",
        "value": {
            "kind": "ITEMS",
            "text": None,
            "items": [
                "Goal",
            ],
            "reason": None,
        },
        "epistemic_status": ("USER_PROVIDED"),
        "confidence": 1.0,
        "provenance": [
            {
                "source_kind": ("OWNER_INPUT"),
                "source_id": str(OWNER_ID),
            }
        ],
        "human_validation": ("NOT_REQUIRED"),
        "rationale": None,
    }

    response = client.post(
        project_path(f"/twins/{TWIN_ID}/revisions"),
        json={
            "replacements": [
                replacement,
                replacement,
            ]
        },
    )

    assert response.status_code == 422
    assert revisions.proposals == []


def test_gate_three_submission_is_project_and_owner_scoped() -> None:
    """Expose Gate 3 submission through the dedicated endpoint."""
    (
        client,
        _commands,
        _revisions,
        gates,
        _queries,
    ) = client_fixture()

    response = client.post(project_path("/gate/submit"))

    assert response.status_code == 200

    body = response.json()

    assert body["outcome"] == "APPLIED"

    assert body["gate"]["gate_type"] == "USER_MODELING"

    assert gates.submit_calls == [
        (
            OWNER_ID,
            PROJECT_ID,
        )
    ]


def test_gate_three_decision_does_not_accept_submit_action() -> None:
    """Keep Gate 3 submission separate from owner decisions."""
    (
        client,
        _commands,
        _revisions,
        gates,
        _queries,
    ) = client_fixture()

    response = client.post(
        project_path("/gate/decision"),
        json={
            "action": "SUBMIT",
            "reason": None,
        },
    )

    assert response.status_code == 422
    assert gates.decisions == []


def test_gate_three_decision_preserves_owner_reason() -> None:
    """Forward revision/rejection rationale without losing it."""
    (
        client,
        _commands,
        _revisions,
        gates,
        _queries,
    ) = client_fixture()

    response = client.post(
        project_path("/gate/decision"),
        json={
            "action": ("REQUEST_REVISION"),
            "reason": ("Update the goals before approval."),
        },
    )

    assert response.status_code == 200

    assert gates.decisions == [
        (
            OWNER_ID,
            PROJECT_ID,
            (HumanGateAction.REQUEST_REVISION),
            ("Update the goals before approval."),
        )
    ]


def test_current_snapshot_returns_404_when_not_created() -> None:
    """Represent absent User Modeling state explicitly."""
    (
        client,
        _commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.get(project_path("/snapshots/current"))

    assert response.status_code == 404

    assert response.json() == {"detail": {"code": ("USER_MODELING_SNAPSHOT_NOT_FOUND")}}


def test_empty_snapshot_history_is_a_valid_collection() -> None:
    """Return an empty immutable history instead of 404."""
    (
        client,
        _commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.get(project_path("/snapshots"))

    assert response.status_code == 200
    assert response.json() == []


def test_readiness_without_snapshot_requires_user_modeling() -> None:
    """Expose the stage blocker before User Modeling exists."""
    (
        client,
        _commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.get(project_path("/readiness"))

    assert response.status_code == 200

    body = response.json()

    assert body["snapshot_exists"] is False

    assert body["approved_current_snapshot"] is False

    assert body["workflow_state"] == "USER_MODELING_REQUIRED"

    assert body["twins"] == []


def test_missing_profile_diff_returns_404() -> None:
    """Do not leak nonexistent or foreign diff state."""
    (
        client,
        _commands,
        _revisions,
        _gates,
        _queries,
    ) = client_fixture()

    response = client.get(project_path(f"/revisions/{DIFF_ID}"))

    assert response.status_code == 404

    assert response.json() == {"detail": {"code": ("PROFILE_DIFF_NOT_FOUND")}}


def test_router_exposes_expected_user_modeling_contract() -> None:
    """Freeze the S04-C12 HTTP surface."""
    (
        dependencies,
        _commands,
        _revisions,
        _gates,
        _queries,
    ) = build_dependencies()

    router = create_user_modeling_router(dependencies)

    paths = {
        route.path
        for route in router.routes
        if hasattr(
            route,
            "path",
        )
    }

    prefix = "/projects/{project_id}/user-modeling"

    assert {
        f"{prefix}/personas/proposals",
        (f"{prefix}/personas/{{persona_id}}/decision"),
        f"{prefix}/snapshots/generate",
        f"{prefix}/snapshots/current",
        f"{prefix}/snapshots",
        (f"{prefix}/twins/{{twin_id}}/revisions"),
        (f"{prefix}/revisions/{{diff_id}}/decision"),
        (f"{prefix}/revisions/{{diff_id}}"),
        f"{prefix}/gate/submit",
        f"{prefix}/gate/decision",
        f"{prefix}/gate",
        f"{prefix}/gate/events",
        f"{prefix}/readiness",
    }.issubset(paths)
