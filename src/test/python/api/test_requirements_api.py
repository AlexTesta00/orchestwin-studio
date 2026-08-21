from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.requirements import (
    RequirementsSpecificationPayload,
    create_requirements_router,
)
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_application import (
    RequirementsGenerationResult,
    RequirementsGenerationStatus,
)
from orchestwin.projects.requirements_gate import (
    RequirementsGateDecisionResult,
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionResult,
    RequirementsGateSubmissionStatus,
    RequirementsReadinessResult,
    RequirementsWorkflowReadiness,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_revision_application import (
    RequirementsRevisionDecision,
    RequirementsRevisionResult,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_revisions import (
    approve_requirements_diff,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000020")
STORY_ID = UUID("00000000-0000-4000-8000-000000000030")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000040")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000050")
DOD_ID = UUID("00000000-0000-4000-8000-000000000060")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000070")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000080")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000090")
GATE_ID = UUID("00000000-0000-4000-8000-0000000000a0")
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def user() -> UserAccount:
    """Create one authenticated owner fixture."""
    return UserAccount(
        id=USER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=2,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def specification_version() -> RequirementsSpecificationVersion:
    """Create one complete requirements version fixture."""
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source,),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=USER_ID,
        created_at=NOW,
    )


def approved_gate(version: RequirementsSpecificationVersion) -> tuple[HumanGate, HumanGateEvent]:
    """Create an approved Gate 4 and return its approval event."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=USER_ID,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=HumanGateType.REQUIREMENTS,
            artifact_id=version.id,
            version=version.version_number,
            content_hash=version.content_hash,
        ),
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=USER_ID,
        occurred_at=NOW + timedelta(minutes=1),
        event_id=UUID(int=201),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=USER_ID,
        occurred_at=NOW + timedelta(minutes=2),
        event_id=UUID(int=202),
    )

    assert approved.event is not None

    return approved.gate, approved.event


class FakeGenerationService:
    """Return one created specification."""

    def __init__(self, version: RequirementsSpecificationVersion) -> None:
        self.version = version
        self.calls: list[tuple[UUID, UUID]] = []

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> RequirementsGenerationResult:
        self.calls.append((owner_user_id, project_id))

        return RequirementsGenerationResult(
            status=RequirementsGenerationStatus.CREATED,
            version=self.version,
        )


class FakeQueryService:
    """Return configurable versions and diffs."""

    def __init__(self, version: RequirementsSpecificationVersion) -> None:
        self.version: RequirementsSpecificationVersion | None = version
        self.diffs = []

    async def current(self, *, owner_user_id: UUID, project_id: UUID):
        del owner_user_id, project_id
        return self.version

    async def history(self, *, owner_user_id: UUID, project_id: UUID):
        del owner_user_id, project_id
        return () if self.version is None else (self.version,)

    async def get_diff(self, *, owner_user_id: UUID, project_id: UUID, diff_id: UUID):
        del owner_user_id, project_id
        return next((diff for diff in self.diffs if diff.id == diff_id), None)

    async def diff_history(self, *, owner_user_id: UUID, project_id: UUID):
        del owner_user_id, project_id
        return tuple(self.diffs)


class FakeRevisionService:
    """Capture specification replacements and decisions."""

    def __init__(self, base: RequirementsSpecificationVersion) -> None:
        proposed = replace(
            base.specification,
            requirements=(
                replace(
                    base.specification.requirements[0],
                    title="Create guest reservations",
                ),
            ),
        )
        proposal = propose_requirements_diff(
            base_version=base,
            proposed_specification=proposed,
            diff_id=DIFF_ID,
            created_by_user_id=USER_ID,
            created_at=NOW + timedelta(minutes=3),
        )

        assert proposal.diff is not None

        self.diff = proposal.diff
        self.proposed = None
        self.decisions = []

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_specification,
    ) -> RequirementsRevisionResult:
        del owner_user_id, project_id
        self.proposed = proposed_specification

        return RequirementsRevisionResult(
            status=RequirementsRevisionStatus.CREATED,
            diff=self.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: RequirementsRevisionDecision,
        reason: str | None = None,
    ) -> RequirementsRevisionResult:
        del project_id
        self.decisions.append((diff_id, decision, reason))
        domain = approve_requirements_diff(
            self.diff,
            actor_user_id=owner_user_id,
            occurred_at=NOW + timedelta(minutes=4),
            applied_specification_version_id=UUID(int=203),
            reason=reason,
        )

        return RequirementsRevisionResult(
            status=RequirementsRevisionStatus.APPLIED,
            diff=domain.diff,
        )


class FakeGateService:
    """Return an approved Gate 4 fixture."""

    def __init__(self, version: RequirementsSpecificationVersion) -> None:
        self.version = version
        self.gate, self.event = approved_gate(version)
        self.decisions = []

    async def submit(self, *, project_id: UUID, owner_user_id: UUID):
        del project_id, owner_user_id
        return RequirementsGateSubmissionResult(
            status=RequirementsGateSubmissionStatus.ALREADY_APPROVED,
            gate=self.gate,
        )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ):
        del project_id, owner_user_id
        self.decisions.append((action, reason))
        return RequirementsGateDecisionResult(
            status=RequirementsGateDecisionStatus.APPLIED,
            gate=self.gate,
            event=self.event,
        )

    async def readiness(self, *, project_id: UUID, owner_user_id: UUID):
        del project_id, owner_user_id
        return RequirementsReadinessResult(
            status=RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION,
            version=self.version,
            gate=self.gate,
        )

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID):
        del project_id, owner_user_id
        return self.gate

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ):
        del project_id, owner_user_id, gate_id
        return (self.event,)


def client_fixture():
    """Create an isolated API app and its service doubles."""
    version = specification_version()
    generation = FakeGenerationService(version)
    queries = FakeQueryService(version)
    revisions = FakeRevisionService(version)
    gates = FakeGateService(version)
    app = FastAPI()
    app.state.requirements_generation_service = generation
    app.state.requirements_query_service = queries
    app.state.requirements_revision_service = revisions
    app.state.requirements_gate_service = gates
    app.include_router(create_requirements_router())
    app.dependency_overrides[current_user_dependency] = user

    return TestClient(app), generation, queries, revisions, gates


def path(suffix: str = "") -> str:
    """Return one project-scoped requirements path."""
    return f"/projects/{PROJECT_ID}/requirements{suffix}"


def test_generation_and_current_version_are_owner_scoped() -> None:
    """Expose generation and current immutable version endpoints."""
    client, generation, _queries, _revisions, _gates = client_fixture()

    generated = client.post(path("/proposals"))
    current = client.get(path("/current"))

    assert generated.status_code == 201
    assert generated.json()["version"]["id"] == str(VERSION_ID)
    assert current.status_code == 200
    assert current.json()["version_number"] == 1
    assert generation.calls == [(USER_ID, PROJECT_ID)]


def test_traceability_and_coverage_are_derived_from_current_version() -> None:
    """Expose typed graph and uncovered-item reporting."""
    client, _generation, _queries, _revisions, _gates = client_fixture()

    traceability = client.get(path("/traceability"))
    coverage = client.get(path("/coverage"))

    assert traceability.status_code == 200
    assert traceability.json()["nodes"]
    assert traceability.json()["links"]
    assert coverage.status_code == 200
    assert coverage.json()["has_full_acceptance_coverage"] is True


def test_revision_endpoint_accepts_a_complete_typed_specification() -> None:
    """Forward an owner replacement through domain validation."""
    client, _generation, _queries, revisions, _gates = client_fixture()
    version = specification_version()
    proposed = replace(
        version.specification,
        requirements=(
            replace(
                version.specification.requirements[0],
                title="Create guest reservations",
            ),
        ),
    )
    payload = RequirementsSpecificationPayload.from_domain(proposed).model_dump(mode="json")

    response = client.post(
        path("/revisions"),
        json={"specification": payload},
    )

    assert response.status_code == 201
    assert response.json()["diff"]["status"] == "PROPOSED"
    assert revisions.proposed == proposed


def test_revision_decision_preserves_owner_reason() -> None:
    """Forward one explicit owner diff decision."""
    client, _generation, _queries, revisions, _gates = client_fixture()

    response = client.post(
        path(f"/revisions/{DIFF_ID}/decision"),
        json={
            "decision": "APPROVE",
            "reason": "Reviewed with the product owner.",
        },
    )

    assert response.status_code == 200
    assert revisions.decisions == [
        (
            DIFF_ID,
            RequirementsRevisionDecision.APPROVE,
            "Reviewed with the product owner.",
        )
    ]


def test_gate_and_readiness_endpoints_expose_exact_approval() -> None:
    """Expose Gate 4 state, audit events, and design readiness."""
    client, _generation, _queries, _revisions, _gates = client_fixture()

    gate = client.get(path("/gate"))
    events = client.get(path("/gate/events"))
    readiness = client.get(path("/readiness"))

    assert gate.status_code == 200
    assert gate.json()["gate_type"] == "REQUIREMENTS"
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert readiness.status_code == 200
    assert readiness.json()["approved_current_specification"] is True
    assert readiness.json()["status"] == "READY_FOR_DESIGN_EXPLORATION"


def test_missing_current_version_returns_non_disclosing_404() -> None:
    """Do not distinguish missing and foreign project state."""
    client, _generation, queries, _revisions, _gates = client_fixture()
    queries.version = None

    response = client.get(path("/current"))

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "REQUIREMENTS_SPECIFICATION_NOT_FOUND",
        }
    }


def test_router_freezes_the_sprint_five_http_surface() -> None:
    """Expose every planned Requirements and Gate 4 endpoint."""
    router = create_requirements_router()
    paths = {route.path for route in router.routes if hasattr(route, "path")}
    prefix = "/projects/{project_id}/requirements"

    assert {
        f"{prefix}/proposals",
        f"{prefix}/current",
        prefix,
        f"{prefix}/revisions",
        f"{prefix}/revisions/{{diff_id}}",
        f"{prefix}/revisions/{{diff_id}}/decision",
        f"{prefix}/traceability",
        f"{prefix}/coverage",
        f"{prefix}/gate/submit",
        f"{prefix}/gate/decision",
        f"{prefix}/gate",
        f"{prefix}/gate/events",
        f"{prefix}/readiness",
    }.issubset(paths)
