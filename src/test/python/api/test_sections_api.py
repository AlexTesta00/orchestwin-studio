from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.sections import (
    TwinLearningProbe,
    TwinLearningSources,
    build_sections_service,
    create_sections_router,
)
from orchestwin.api.twin_learning import TwinLearningApplication
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.design_realignment_service import DesignRealignmentFailure
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.requirements_realignment_service import RequirementsRealignmentFailure
from orchestwin.projects.sections import (
    ProjectSections,
    Section,
    SectionAlignment,
    SectionBlock,
    SectionReason,
    SectionState,
)
from orchestwin.projects.sections_service import (
    SectionOutcome,
    SectionsAlignment,
    SectionsAlignmentStatus,
    SectionsFailure,
    SectionsService,
    SectionUpdate,
    SqlAlchemySectionReads,
)
from orchestwin.twins.realignment_service import UserModelingRealignmentFailure

OWNER_ID = UUID("00000000-0000-4000-8000-0000000006a1")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000006b1")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
SECTIONS = f"/api/v1/projects/{PROJECT_ID}/sections"
ALIGNMENT = f"{SECTIONS}/alignment"
UT = ProjectStage.USER_TWINS
RQ = ProjectStage.REQUIREMENTS
DS = ProjectStage.DESIGN
EXAMPLE = ProjectSections(
    first_pass_complete=True,
    sections=(
        Section(key=ProjectStage.BRIEF, state=SectionState.FINE, version_number=2),
        Section(key=ProjectStage.TEAM, state=SectionState.FINE, version_number=2),
        Section(
            key=UT,
            state=SectionState.TO_UPDATE,
            version_number=1,
            reasons=(SectionReason.PERSPECTIVES_CHANGED,),
        ),
        Section(
            key=RQ,
            state=SectionState.TO_UPDATE,
            version_number=3,
            reasons=(SectionReason.PERSPECTIVES_CHANGED, SectionReason.USER_TWINS_CHANGED),
        ),
        Section(
            key=DS,
            state=SectionState.TO_UPDATE,
            version_number=4,
            reasons=(SectionReason.REQUIREMENTS_CHANGED,),
        ),
        Section(
            key=ProjectStage.PACKAGE,
            state=SectionState.TO_UPDATE,
            version_number=6,
            reasons=(SectionReason.FOLDER_BEHIND,),
        ),
    ),
    alignment=SectionAlignment(available=True, sections=(UT, RQ, DS)),
)
EXAMPLE_JSON = {
    "first_pass_complete": True,
    "sections": [
        {
            "key": "BRIEF",
            "state": "FINE",
            "version_number": 2,
            "reasons": [],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "TEAM",
            "state": "FINE",
            "version_number": 2,
            "reasons": [],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "USER_TWINS",
            "state": "TO_UPDATE",
            "version_number": 1,
            "reasons": ["PERSPECTIVES_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "state": "TO_UPDATE",
            "version_number": 3,
            "reasons": ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "DESIGN",
            "state": "TO_UPDATE",
            "version_number": 4,
            "reasons": ["REQUIREMENTS_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "PACKAGE",
            "state": "TO_UPDATE",
            "version_number": 6,
            "reasons": ["FOLDER_BEHIND"],
            "blocked": None,
            "codes": [],
        },
    ],
    "alignment": {
        "available": True,
        "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"],
        "uncovered_codes": [],
    },
}


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeSectionsService:
    def __init__(
        self,
        *,
        sections: ProjectSections = EXAMPLE,
        alignment: SectionsAlignment | None = None,
        error: SectionsFailure | None = None,
    ) -> None:
        self.sections = sections
        self.alignment = alignment
        self.error = error
        self.calls: list[tuple[str, UUID, UUID]] = []

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> ProjectSections:
        self.calls.append(("current", owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.sections

    async def align(self, *, owner_user_id: UUID, project_id: UUID) -> SectionsAlignment:
        self.calls.append(("align", owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.alignment


def client(service: FakeSectionsService | None) -> TestClient:
    application = FastAPI()
    application.include_router(create_sections_router(), prefix="/api/v1")
    application.state.sections_service = service
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_the_sections_answer_exactly_the_payload_of_the_contract():
    service = FakeSectionsService()

    response = client(service).get(SECTIONS)

    assert response.status_code == 200
    assert response.json() == EXAMPLE_JSON
    assert service.calls == [("current", OWNER_ID, PROJECT_ID)]


def test_a_blocked_section_carries_its_obstacle_and_codes():
    blocked = ProjectSections(
        first_pass_complete=False,
        sections=(
            Section(
                key=DS,
                state=SectionState.TO_UPDATE,
                version_number=2,
                reasons=(SectionReason.REQUIREMENTS_CHANGED,),
                blocked=SectionBlock.REQUIREMENT_NO_LONGER_AVAILABLE,
                codes=("REQ-002",),
            ),
            Section(key=ProjectStage.PACKAGE, state=SectionState.NOT_STARTED),
        ),
        alignment=SectionAlignment(sections=(DS,)),
    )

    response = client(FakeSectionsService(sections=blocked)).get(SECTIONS)

    assert response.json() == {
        "first_pass_complete": False,
        "sections": [
            {
                "key": "DESIGN",
                "state": "TO_UPDATE",
                "version_number": 2,
                "reasons": ["REQUIREMENTS_CHANGED"],
                "blocked": "REQUIREMENT_NO_LONGER_AVAILABLE",
                "codes": ["REQ-002"],
            },
            {
                "key": "PACKAGE",
                "state": "NOT_STARTED",
                "version_number": None,
                "reasons": [],
                "blocked": None,
                "codes": [],
            },
        ],
        "alignment": {"available": False, "sections": ["DESIGN"], "uncovered_codes": []},
    }


def test_the_gesture_answers_the_results_and_the_sections_read_again():
    result = SectionsAlignment(
        status=SectionsAlignmentStatus.PARTIAL,
        results=(
            SectionUpdate(key=UT, outcome=SectionOutcome.ALIGNED, version_number=2),
            SectionUpdate(
                key=RQ,
                outcome=SectionOutcome.BLOCKED,
                issue="REQUIREMENT_NO_LONGER_AVAILABLE",
                codes=("REQ-001",),
            ),
            SectionUpdate(key=DS, outcome=SectionOutcome.SKIPPED),
        ),
        sections=EXAMPLE,
    )
    service = FakeSectionsService(alignment=result)

    response = client(service).post(ALIGNMENT)

    assert response.status_code == 200
    assert response.json() == {
        "status": "PARTIAL",
        "results": [
            {
                "key": "USER_TWINS",
                "outcome": "ALIGNED",
                "issue": None,
                "version_number": 2,
                "codes": [],
            },
            {
                "key": "REQUIREMENTS",
                "outcome": "BLOCKED",
                "issue": "REQUIREMENT_NO_LONGER_AVAILABLE",
                "version_number": None,
                "codes": ["REQ-001"],
            },
            {
                "key": "DESIGN",
                "outcome": "SKIPPED",
                "issue": None,
                "version_number": None,
                "codes": [],
            },
        ],
        "sections": EXAMPLE_JSON,
    }
    assert response.json() == result.to_snapshot()
    assert service.calls == [("align", OWNER_ID, PROJECT_ID)]


def test_a_gesture_with_nothing_to_align_answers_an_empty_list():
    result = SectionsAlignment(
        status=SectionsAlignmentStatus.NOTHING_TO_ALIGN, results=(), sections=EXAMPLE
    )

    response = client(FakeSectionsService(alignment=result)).post(ALIGNMENT)

    assert response.status_code == 200
    assert (response.json()["status"], response.json()["results"]) == ("NOTHING_TO_ALIGN", [])


def test_a_project_that_is_not_found_answers_404_on_both_routes():
    api = client(FakeSectionsService(error=SectionsFailure("PROJECT_NOT_FOUND")))

    for response in (api.get(SECTIONS), api.post(ALIGNMENT)):
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": "PROJECT_NOT_FOUND"}}


def test_another_refusal_of_the_service_answers_409_with_its_code():
    api = client(FakeSectionsService(error=SectionsFailure("SECTIONS_CHANGED")))

    response = api.post(ALIGNMENT)

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "SECTIONS_CHANGED"}}


def test_the_sections_are_unavailable_without_the_service():
    api = client(None)

    for response in (api.get(SECTIONS), api.post(ALIGNMENT)):
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "SECTIONS_SERVICE_UNAVAILABLE"}}


def test_the_project_identifier_in_the_path_must_be_a_uuid():
    service = FakeSectionsService()
    api = client(service)

    for response in (
        api.get("/api/v1/projects/project-a/sections"),
        api.post("/api/v1/projects/project-a/sections/alignment"),
    ):
        assert response.status_code == 422
    assert service.calls == []


def test_the_routes_are_documented_with_their_operation_ids():
    paths = client(FakeSectionsService()).app.openapi()["paths"]
    sections = paths["/api/v1/projects/{project_id}/sections"]
    alignment = paths["/api/v1/projects/{project_id}/sections/alignment"]

    assert sections["get"]["operationId"] == "getProjectSections"
    assert alignment["post"]["operationId"] == "alignProjectSections"
    assert sections["get"]["tags"] == alignment["post"]["tags"] == ["projects"]
    assert "200" in alignment["post"]["responses"]


class Overview:
    def __init__(self, document: dict[str, object]) -> None:
        self.document = document
        self.calls: list[tuple[UUID, UUID]] = []

    async def overview(self, *, owner_user_id: UUID, project_id: UUID) -> dict[str, object]:
        self.calls.append((owner_user_id, project_id))
        return self.document


def entry(*, pending: object = None, changes: int = 0, tests: int = 0) -> dict[str, object]:
    return {"pending_update": pending, "new_material": {"changes": changes, "tests": tests}}


@pytest.mark.parametrize(
    ("available", "twins", "expected"),
    [
        (True, [], False),
        (True, [entry(), entry()], False),
        (False, [entry(), entry(pending={"id": "update"})], True),
        (True, [entry(changes=2)], True),
        (True, [entry(tests=1)], True),
        (False, [entry(changes=2, tests=1)], False),
    ],
)
def test_the_twins_learned_something_when_a_proposal_waits_or_new_material_can_be_used(
    available, twins, expected
):
    overview = Overview(
        {"project_id": str(PROJECT_ID), "update_available": available, "twins": twins}
    )

    learned = asyncio.run(
        TwinLearningProbe(overview).learned(owner_user_id=OWNER_ID, project_id=PROJECT_ID)
    )

    assert learned is expected
    assert overview.calls == [(OWNER_ID, PROJECT_ID)]


def test_the_service_is_built_with_the_realignments_and_the_gates_of_each_step():
    database = SimpleNamespace(session_factory=object())
    user_modeling = SimpleNamespace(gates=object())
    twins, requirements, design = object(), object(), object()
    requirements_gate, design_gate = object(), object()
    evidence = object()

    service = build_sections_service(
        database_runtime=database,
        user_modeling_services=user_modeling,
        user_modeling_realignment_service=twins,
        requirements_realignment_service=requirements,
        requirements_gate_service=requirements_gate,
        design_realignment_service=design,
        design_gate_service=design_gate,
        proposal_evidence_store=evidence,
    )
    steps = service._steps

    assert isinstance(service, SectionsService)
    assert isinstance(service._reads, SqlAlchemySectionReads)
    assert [(step.realignment, step.gate, step.failure) for step in steps.values()] == [
        (twins, user_modeling.gates, UserModelingRealignmentFailure),
        (requirements, requirements_gate, RequirementsRealignmentFailure),
        (design, design_gate, DesignRealignmentFailure),
    ]
    assert list(steps) == [UT, RQ, DS]
    assert service._design_alignment is design
    application = service._twin_learning._application
    assert isinstance(application, TwinLearningApplication)
    assert application.runtime == TwinLearningSources(
        database_runtime=database,
        user_modeling_services=user_modeling,
        proposal_evidence_store=evidence,
    )
    assert application.update_available() is False


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def test_the_default_studio_registers_the_service_and_the_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(
        services_module, "create_database_runtime", lambda _settings: FakeDatabaseRuntime()
    )
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        api_prefix="/api/v1",
        debug=False,
        _env_file=None,
    )

    runtime = services_module.create_default_runtime(settings)
    application = create_app(
        settings, runtime=runtime, auth_settings=AuthApiSettings(_env_file=None)
    )
    service = runtime.sections_service
    paths = application.openapi()["paths"]

    assert isinstance(service, SectionsService)
    assert application.state.sections_service is service
    assert service._steps[UT].realignment is runtime.user_modeling_realignment_service
    assert service._steps[UT].gate is runtime.user_modeling_services.gates
    assert service._steps[RQ].realignment is runtime.requirements_realignment_service
    assert service._steps[RQ].gate is runtime.requirements_gate_service
    assert service._steps[DS].realignment is runtime.design_realignment_service
    assert service._steps[DS].gate is runtime.design_gate_service
    assert service._design_alignment is runtime.design_realignment_service
    assert "get" in paths["/api/v1/projects/{project_id}/sections"]
    assert "post" in paths["/api/v1/projects/{project_id}/sections/alignment"]
