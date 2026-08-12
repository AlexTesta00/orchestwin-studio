"""API contract tests for clarification, assumptions, and Gate 1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

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
from orchestwin.projects.brief_gate import (
    ProjectBriefGateDecisionResult,
    ProjectBriefGateDecisionStatus,
    ProjectBriefGateSubmissionResult,
    ProjectBriefGateSubmissionStatus,
    project_brief_artifact_reference,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.clarification import (
    CLARIFICATION_CATALOG_VERSION,
    ClarificationAnswer,
    clarification_question_for,
)
from orchestwin.projects.clarification_application import (
    BriefAssumptionCreationResult,
    BriefAssumptionCreationStatus,
    BriefAssumptionDecisionResult,
    BriefAssumptionDecisionStatus,
    ClarificationNextStep,
    ClarificationRoundAnswerResult,
    ClarificationRoundAnswerStatus,
    ClarificationRoundStartResult,
    ClarificationRoundStartStatus,
)
from orchestwin.projects.clarification_state import (
    BriefAssumptionSource,
    accept_brief_assumption,
    complete_clarification_round,
    create_brief_assumption,
    create_clarification_round,
)
from orchestwin.workflow.gates import (
    HumanGateAction,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
ROUND_ID = UUID("00000000-0000-4000-8000-000000000020")
ASSUMPTION_ID = UUID("00000000-0000-4000-8000-000000000030")
GATE_ID = UUID("00000000-0000-4000-8000-000000000040")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


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


def build_versions() -> tuple[
    ProjectBriefVersion,
    ProjectBriefVersion,
]:
    """Create source and clarified brief versions."""
    source_brief = create_project_brief(name="Project")
    clarified_brief = create_project_brief(
        name="Project",
        description="Clarified description",
        unknown_fields=[
            field
            for field in BriefField
            if field
            not in {
                BriefField.NAME,
                BriefField.DESCRIPTION,
            }
        ],
    )

    return (
        ProjectBriefVersion(
            id=UUID(int=100),
            project_id=PROJECT_ID,
            version_number=1,
            schema_version=(source_brief.SCHEMA_VERSION),
            brief=source_brief,
            content_hash=(source_brief.content_hash),
            created_by_user_id=USER_ID,
            created_at=NOW,
        ),
        ProjectBriefVersion(
            id=UUID(int=101),
            project_id=PROJECT_ID,
            version_number=2,
            schema_version=(clarified_brief.SCHEMA_VERSION),
            brief=clarified_brief,
            content_hash=(clarified_brief.content_hash),
            created_by_user_id=USER_ID,
            created_at=(NOW + timedelta(minutes=1)),
        ),
    )


class FakeIdentityService:
    """Identity service double used by bearer dependencies."""

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        if access_token != "valid-access-token":
            return None

        return build_user()


class FakeClarificationService:
    """Clarification application-service double."""

    def __init__(self) -> None:
        source_version, clarified_version = build_versions()
        self.source_version = source_version
        self.clarified_version = clarified_version
        self.round = create_clarification_round(
            round_id=ROUND_ID,
            project_id=PROJECT_ID,
            source_brief_version_number=1,
            round_number=1,
            catalog_version=(CLARIFICATION_CATALOG_VERSION),
            questions=[clarification_question_for(BriefField.DESCRIPTION)],
            created_by_user_id=USER_ID,
            created_at=NOW,
        )
        self.assumption = create_brief_assumption(
            assumption_id=ASSUMPTION_ID,
            project_id=PROJECT_ID,
            brief_version_number=1,
            field=BriefField.BUDGET,
            statement=("Approximately EUR 5,000."),
            source=(BriefAssumptionSource.OWNER_PROVIDED),
            created_by_user_id=USER_ID,
            created_at=NOW,
        )

    async def start_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRoundStartResult:
        """Return one deterministic started round."""
        del project_id
        del owner_user_id

        return ClarificationRoundStartResult(
            status=(ClarificationRoundStartStatus.STARTED),
            round_state=self.round,
        )

    async def answer_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        answers: tuple[
            ClarificationAnswer,
            ...,
        ],
    ) -> ClarificationRoundAnswerResult:
        """Return one deterministic clarified brief."""
        del project_id
        del owner_user_id
        del answers

        completed = complete_clarification_round(
            self.round,
            resulting_brief_version_number=2,
            answered_at=(NOW + timedelta(minutes=1)),
        )

        if round_id != self.round.id:
            return ClarificationRoundAnswerResult(
                status=(ClarificationRoundAnswerStatus.ROUND_NOT_FOUND)
            )

        return ClarificationRoundAnswerResult(
            status=(ClarificationRoundAnswerStatus.APPLIED),
            round_state=completed,
            version=self.clarified_version,
            next_step=(ClarificationNextStep.BRIEF_READY_FOR_APPROVAL),
        )

    async def current_round(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ):
        """Return the deterministic open round."""
        del project_id
        del owner_user_id

        return self.round

    async def round_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ):
        """Return one round of history."""
        del project_id
        del owner_user_id

        return (self.round,)

    async def create_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        field: BriefField,
        statement: str,
    ) -> BriefAssumptionCreationResult:
        """Return one deterministic assumption."""
        del project_id
        del owner_user_id
        del field
        del statement

        return BriefAssumptionCreationResult(
            status=(BriefAssumptionCreationStatus.CREATED),
            assumption=self.assumption,
        )

    async def assumptions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ):
        """Return one assumption."""
        del project_id
        del owner_user_id

        return (self.assumption,)

    async def accept_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str | None = None,
    ) -> BriefAssumptionDecisionResult:
        """Return one accepted assumption and new brief version."""
        del project_id
        del reason

        if assumption_id != self.assumption.id:
            return BriefAssumptionDecisionResult(
                status=(BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND)
            )

        accepted = accept_brief_assumption(
            self.assumption,
            decided_by_user_id=owner_user_id,
            decided_at=(NOW + timedelta(minutes=1)),
        )

        return BriefAssumptionDecisionResult(
            status=(BriefAssumptionDecisionStatus.ACCEPTED),
            assumption=accepted,
            version=self.clarified_version,
        )

    async def reject_assumption(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        reason: str,
    ) -> BriefAssumptionDecisionResult:
        """Return a focused not-found result when unused."""
        del project_id
        del owner_user_id
        del assumption_id
        del reason

        return BriefAssumptionDecisionResult(
            status=(BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND)
        )


class FakeProjectBriefGateService:
    """Project Brief gate service double."""

    def __init__(self) -> None:
        _, version = build_versions()
        draft = create_human_gate(
            gate_id=GATE_ID,
            project_id=PROJECT_ID,
            owner_user_id=USER_ID,
            gate_type=(HumanGateType.PROJECT_BRIEF),
            artifact=(project_brief_artifact_reference(version)),
            created_at=NOW,
        )
        submitted = transition_human_gate(
            draft,
            action=HumanGateAction.SUBMIT,
            actor_user_id=USER_ID,
            occurred_at=NOW,
            event_id=UUID(int=400),
        )

        assert submitted.status is (HumanGateTransitionStatus.APPLIED)
        assert submitted.event is not None

        self.gate = submitted.gate
        self.events = (submitted.event,)

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefGateSubmissionResult:
        """Return a deterministic Gate 1 submission."""
        del project_id
        del owner_user_id

        return ProjectBriefGateSubmissionResult(
            status=(ProjectBriefGateSubmissionStatus.SUBMITTED),
            gate=self.gate,
            events=self.events,
        )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> ProjectBriefGateDecisionResult:
        """Apply the supplied decision to the deterministic gate."""
        del project_id

        result = transition_human_gate(
            self.gate,
            action=action,
            actor_user_id=owner_user_id,
            occurred_at=(NOW + timedelta(minutes=1)),
            reason=reason,
            event_id=UUID(int=401),
        )

        if result.status is not HumanGateTransitionStatus.APPLIED or result.event is None:
            return ProjectBriefGateDecisionResult(
                status=(ProjectBriefGateDecisionStatus.REJECTED),
                gate=self.gate,
                issue=result.issue,
            )

        self.gate = result.gate
        self.events = (
            *self.events,
            result.event,
        )

        return ProjectBriefGateDecisionResult(
            status=(ProjectBriefGateDecisionStatus.APPLIED),
            gate=result.gate,
            event=result.event,
        )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ):
        """Return the deterministic current gate."""
        del project_id
        del owner_user_id

        return self.gate

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ):
        """Return deterministic event history."""
        del project_id
        del owner_user_id

        if gate_id != self.gate.id:
            return ()

        return self.events


def build_client() -> TestClient:
    """Create a client with explicit service doubles."""
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        api_prefix="/api/v1",
        cors_allowed_origins=("http://127.0.0.1:5173",),
        _env_file=None,
    )
    runtime = ApplicationRuntime(
        identity_service=FakeIdentityService(),
        clarification_service=(FakeClarificationService()),
        brief_gate_service=(FakeProjectBriefGateService()),
    )

    return TestClient(
        create_app(
            settings,
            runtime=runtime,
            auth_settings=AuthApiSettings(_env_file=None),
        )
    )


def authorization_header() -> dict[str, str]:
    """Return a valid bearer header."""
    return {"Authorization": ("Bearer valid-access-token")}


def test_clarification_routes_require_authentication() -> None:
    """Reject anonymous clarification access."""
    with build_client() as client:
        response = client.post(f"/api/v1/projects/{PROJECT_ID}/clarification-rounds")

    assert response.status_code == 401


def test_start_and_answer_clarification_round() -> None:
    """Expose a focused question and resulting brief version."""
    with build_client() as client:
        started = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/clarification-rounds"),
            headers=authorization_header(),
        )
        answered = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/clarification-rounds/{ROUND_ID}/answers"),
            headers=authorization_header(),
            json={
                "answers": [
                    {
                        "question_id": ("project-brief.description.v1"),
                        "kind": "text",
                        "text_value": ("Clarified description"),
                    }
                ]
            },
        )

    assert started.status_code == 201
    assert started.json()["round"]["questions"][0]["field"] == "description"

    assert answered.status_code == 201
    assert answered.json()["brief_version"]["version_number"] == 2
    assert answered.json()["next_step"] == "BRIEF_READY_FOR_APPROVAL"


def test_assumption_creation_and_acceptance_are_explicit() -> None:
    """Expose assumption provenance and resulting brief version."""
    with build_client() as client:
        created = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/brief-assumptions"),
            headers=authorization_header(),
            json={
                "field": "budget",
                "statement": ("Approximately EUR 5,000."),
            },
        )
        accepted = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/brief-assumptions/{ASSUMPTION_ID}/accept"),
            headers=authorization_header(),
            json={"reason": ("Confirmed by the owner.")},
        )

    assert created.status_code == 201
    assert created.json()["assumption"]["status"] == "PROPOSED"

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    assert accepted.json()["brief_version"]["version_number"] == 2


def test_project_brief_gate_can_be_submitted_and_approved() -> None:
    """Expose Gate 1 submission and explicit owner approval."""
    with build_client() as client:
        submitted = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/gates/project-brief/submit"),
            headers=authorization_header(),
        )
        approved = client.post(
            (f"/api/v1/projects/{PROJECT_ID}/gates/project-brief/decisions"),
            headers=authorization_header(),
            json={"action": "APPROVE"},
        )

    assert submitted.status_code == 201
    assert submitted.json()["gate"]["status"] == "PENDING_APPROVAL"

    assert approved.status_code == 200
    assert approved.json()["gate"]["status"] == "APPROVED"
