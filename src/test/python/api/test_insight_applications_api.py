from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from orchestwin.api import insight_applications as module
from orchestwin.api.insight_applications import (
    InsightApplicationRequest,
    InsightApplicationService,
)
from orchestwin.artifacts.design_revision_application import DesignRevisionStatus
from orchestwin.projects.briefs import BriefField, create_project_brief
from orchestwin.projects.insight_applications import InsightSourceKind, InsightTarget
from orchestwin.projects.requirements import RequirementKind
from orchestwin.projects.requirements_primitives import RequirementSourceKind
from orchestwin.projects.requirements_revision_application import RequirementsRevisionStatus
from src.test.python.artifacts import design_fixtures


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class FakeSession:
    def begin(self):
        return FakeTransaction()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


class MemoryApplications:
    items: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def create(self, application):
        MemoryApplications.items.append(application)
        return module.InsightApplicationWriteStatus.WRITTEN

    async def list(self, *, project_id, limit=200):
        return tuple(item for item in MemoryApplications.items if item.project_id == project_id)


class Revisions:
    def __init__(self, status, version_number):
        self.status = status
        self.version_number = version_number
        self.proposed = []

    async def propose_revision(self, **kwargs):
        self.proposed.append(kwargs)
        return SimpleNamespace(status=self.status, diff=SimpleNamespace(id=uuid4()), issue=None)

    async def decide_revision(self, **kwargs):
        return SimpleNamespace(
            version=SimpleNamespace(id=UUID(int=77), version_number=self.version_number),
            issue=None,
        )


def service(monkeypatch, *, brief=None, requirements=None, design=None):
    MemoryApplications.items = []
    monkeypatch.setattr(module, "SqlAlchemyInsightApplicationRepository", MemoryApplications)
    created = []

    async def current_brief(**kwargs):
        return None if brief is None else SimpleNamespace(brief=brief)

    async def create_brief_version(**kwargs):
        created.append(kwargs["brief"])
        return SimpleNamespace(version=SimpleNamespace(id=UUID(int=55), version_number=2))

    async def current_requirements(**kwargs):
        return requirements

    async def current_design(**kwargs):
        return design

    runtime = SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=lambda: FakeSession()),
        project_service=SimpleNamespace(
            current_brief=current_brief, create_brief_version=create_brief_version
        ),
        requirements_query_service=SimpleNamespace(current=current_requirements),
        requirements_revision_service=Revisions(RequirementsRevisionStatus.CREATED, 3),
        design_query_service=SimpleNamespace(current=current_design),
        design_revision_service=Revisions(DesignRevisionStatus.CREATED, 4),
    )
    return InsightApplicationService(runtime), runtime, created


def request(**overrides):
    values = {
        "source_kind": InsightSourceKind.SYNTHETIC_FINDING,
        "source_id": "run:1:UTF-001",
        "source_twin_id": design_fixtures.twin_reference().twin_id,
        "text": "Show the accepted date format next to the reservation dates.",
        "target": InsightTarget.REQUIREMENTS,
    }
    values.update(overrides)
    return InsightApplicationRequest(**values)


def apply(application, body):
    return asyncio.run(
        application.apply(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=design_fixtures.PROJECT_ID,
            body=body,
        )
    )


def test_brief_target_extends_a_list_field_in_a_new_brief_version(monkeypatch):
    brief = create_project_brief(description="A reservation desk.", risks=("Peak hours",))
    application, _, created = service(monkeypatch, brief=brief)
    result = apply(
        application,
        request(
            target=InsightTarget.BRIEF,
            brief_field=BriefField.RISKS,
            source_kind=InsightSourceKind.TWIN_CHAT_INSIGHT,
        ),
    )
    assert created[0].risks == (
        "Peak hours",
        "Show the accepted date format next to the reservation dates.",
    )
    assert result.target_field is BriefField.RISKS
    assert result.target_version_number == 2
    assert MemoryApplications.items == [result]
    with pytest.raises(HTTPException) as failure:
        apply(application, request(target=InsightTarget.BRIEF, brief_field=BriefField.NAME))
    assert failure.value.detail["code"] == "BRIEF_FIELD_NOT_A_LIST"
    with pytest.raises(HTTPException) as duplicate:
        apply(
            application,
            request(target=InsightTarget.BRIEF, brief_field=BriefField.RISKS, text="Peak hours"),
        )
    assert duplicate.value.detail["code"] == "INSIGHT_ALREADY_APPLIED"


def test_requirements_target_adds_a_traced_requirement_through_an_approved_revision(
    monkeypatch,
):
    application, runtime, _ = service(
        monkeypatch, requirements=design_fixtures.requirements_version()
    )
    result = apply(application, request(requirement_kind=RequirementKind.NON_FUNCTIONAL))
    proposed = runtime.requirements_revision_service.proposed[0]["proposed_specification"]
    added = proposed.requirements[-1]
    assert added.code == result.target_code == "REQ-002"
    assert added.statement == "Show the accepted date format next to the reservation dates."
    assert added.kind is RequirementKind.NON_FUNCTIONAL
    assert added.sources[0].kind is RequirementSourceKind.USER_TWIN
    assert added.sources[0].locator == "SYNTHETIC_FINDING:run:1:UTF-001"
    assert [reference.twin_id for reference in added.user_twin_references] == [
        design_fixtures.twin_reference().twin_id
    ]
    assert result.target_version_number == 3
    with pytest.raises(HTTPException) as failure:
        apply(
            application,
            request(
                text=design_fixtures.requirements_version().specification.requirements[0].statement
            ),
        )
    assert failure.value.detail["code"] == "INSIGHT_ALREADY_APPLIED"


def test_design_target_records_a_concern_on_the_selected_alternative(monkeypatch):
    version = design_fixtures.design_version()
    application, runtime, _ = service(monkeypatch, design=version)
    result = apply(
        application,
        request(
            target=InsightTarget.DESIGN,
            mitigation="Add the format hint under the field.",
            source_kind=InsightSourceKind.DESIGN_CRITIQUE,
        ),
    )
    proposed = runtime.design_revision_service.proposed[0]["proposed_package"]
    concern = proposed.concerns[-1]
    assert concern.code == result.target_code == "DRK-002"
    assert concern.summary == "Show the accepted date format next to the reservation dates."
    assert concern.mitigation == "Add the format hint under the field."
    assert concern.design_alternative_ids == (version.package.owner_selected_alternative_id,)
    assert result.target_version_number == 4
    listed = asyncio.run(
        application.applications(
            owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
        )
    )
    assert listed == (result,)


def test_missing_artifacts_and_rejected_revisions_are_reported(monkeypatch):
    application, runtime, _ = service(monkeypatch)
    for target, code in (
        (InsightTarget.BRIEF, "PROJECT_BRIEF_NOT_FOUND"),
        (InsightTarget.REQUIREMENTS, "REQUIREMENTS_NOT_FOUND"),
        (InsightTarget.DESIGN, "DESIGN_PACKAGE_NOT_FOUND"),
    ):
        with pytest.raises(HTTPException) as failure:
            apply(application, request(target=target, brief_field=BriefField.GOALS))
        assert failure.value.status_code == 404
        assert failure.value.detail["code"] == code
    rejected, runtime, _ = service(monkeypatch, design=design_fixtures.design_version())
    runtime.design_revision_service.status = DesignRevisionStatus.REJECTED
    with pytest.raises(HTTPException) as failure:
        apply(rejected, request(target=InsightTarget.DESIGN))
    assert failure.value.detail["code"] == "DESIGN_REVISION_REJECTED"


def test_router_registers_the_application_routes():
    router = module.create_insight_application_router()
    assert sorted(route.path for route in router.routes) == [
        "/projects/{project_id}/insight-applications",
        "/projects/{project_id}/insight-applications",
    ]
