from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from orchestwin.api import insight_applications as module
from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.insight_applications import (
    InsightApplicationRequest,
    InsightApplicationService,
    InsightBatchRequest,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_finding_validations import (
    FindingDecision,
    create_finding_validation,
    finding_source_id,
)
from orchestwin.artifacts.design_revision_application import DesignRevisionStatus
from orchestwin.config import ApplicationSettings
from orchestwin.projects.briefs import BriefField, create_project_brief
from orchestwin.projects.insight_applications import InsightSourceKind, InsightTarget
from orchestwin.projects.requirements import RequirementKind
from orchestwin.projects.requirements_primitives import RequirementSourceKind
from orchestwin.projects.requirements_revision_application import RequirementsRevisionStatus
from src.test.python.api.test_training_api import _user
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

    async def applied_sources(self, *, project_id, target, sources):
        wanted = frozenset(sources)
        return frozenset(
            (item.source_kind, item.source_id)
            for item in MemoryApplications.items
            if item.project_id == project_id
            and item.owner_user_id == self.owner_user_id
            and item.target is target
            and (item.source_kind, item.source_id) in wanted
        )


class MemoryValidations:
    items: ClassVar[list] = []
    reads: ClassVar[int] = 0

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def current(self, *, project_id):
        MemoryValidations.reads += 1
        return tuple(
            item
            for item in MemoryValidations.items
            if item.project_id == project_id and item.owner_user_id == self.owner_user_id
        )


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


def service(monkeypatch, *, brief=None, requirements=None, design=None, validations=()):
    MemoryApplications.items = []
    MemoryValidations.items = list(validations)
    MemoryValidations.reads = 0
    monkeypatch.setattr(module, "SqlAlchemyInsightApplicationRepository", MemoryApplications)
    monkeypatch.setattr(module, "SqlAlchemyFindingValidationRepository", MemoryValidations)
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


RUN_ID = UUID("00000000-0000-4000-8000-000000000901")


def owner_decision(decision, sequence_number=1):
    return create_finding_validation(
        evaluation_run_id=RUN_ID,
        twin_id=design_fixtures.twin_reference().twin_id,
        finding_id="UTF-001",
        sequence_number=sequence_number,
        project_id=design_fixtures.PROJECT_ID,
        owner_user_id=design_fixtures.OWNER_ID,
        decision=decision,
        note=None,
        decided_at=datetime(2026, 9, 27, 9, sequence_number, tzinfo=UTC),
    )


def finding_source():
    return finding_source_id(RUN_ID, design_fixtures.twin_reference().twin_id, "UTF-001")


def test_dismissed_synthetic_findings_are_refused_before_anything_is_created(monkeypatch):
    application, runtime, _ = service(
        monkeypatch,
        requirements=design_fixtures.requirements_version(),
        validations=(
            owner_decision(FindingDecision.OWNER_CONFIRMED),
            owner_decision(FindingDecision.OWNER_DISMISSED, 2),
        ),
    )
    with pytest.raises(HTTPException) as failure:
        apply(application, request(source_id=finding_source()))
    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "INSIGHT_SOURCE_DISMISSED"}
    assert runtime.requirements_revision_service.proposed == []
    assert MemoryApplications.items == []
    runtime.database_runtime = None
    with pytest.raises(HTTPException) as unavailable:
        apply(application, request(source_id=finding_source()))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == {"code": "DATABASE_UNAVAILABLE"}
    assert runtime.requirements_revision_service.proposed == []


def test_confirmed_findings_and_other_sources_are_still_applied(monkeypatch):
    confirmed, _, _ = service(
        monkeypatch,
        requirements=design_fixtures.requirements_version(),
        validations=(
            owner_decision(FindingDecision.OWNER_DISMISSED),
            owner_decision(FindingDecision.OWNER_CONFIRMED, 2),
        ),
    )
    assert apply(confirmed, request(source_id=finding_source())).source_id == finding_source()
    assert MemoryValidations.reads == 1
    dismissed, _, _ = service(
        monkeypatch,
        requirements=design_fixtures.requirements_version(),
        validations=(owner_decision(FindingDecision.OWNER_DISMISSED),),
    )
    for body in (
        request(source_id=f"run:{RUN_ID}:UTF-001"),
        request(source_id=finding_source_id(RUN_ID, UUID(int=5), "UTF-001")),
        request(source_kind=InsightSourceKind.DESIGN_CRITIQUE, source_id=finding_source()),
    ):
        assert apply(dismissed, body).source_id == body.source_id
    assert len(MemoryApplications.items) == 3
    assert MemoryValidations.reads == 1


DISCUSSION_ID = UUID("00000000-0000-4000-8000-000000000951")


def discussion_source(ordinal=1, code="PRP-001"):
    return f"discussion:{DISCUSSION_ID}:{ordinal}:{code}"


def test_twin_discussion_proposals_are_applied_like_every_other_source(monkeypatch):
    parsed = InsightApplicationRequest.model_validate(
        {
            "source_kind": "TWIN_DISCUSSION",
            "source_id": discussion_source(),
            "text": "Show the accepted date format next to the reservation dates.",
            "target": "REQUIREMENTS",
        }
    )
    assert parsed.source_kind is InsightSourceKind.TWIN_DISCUSSION
    assert parsed.source_twin_id is None
    application, runtime, _ = service(
        monkeypatch,
        requirements=design_fixtures.requirements_version(),
        design=design_fixtures.design_version(),
        validations=(owner_decision(FindingDecision.OWNER_DISMISSED),),
    )
    requirement = apply(application, parsed)
    added = runtime.requirements_revision_service.proposed[0][
        "proposed_specification"
    ].requirements[-1]
    assert added.code == requirement.target_code == "REQ-002"
    assert added.statement == "Show the accepted date format next to the reservation dates."
    assert added.sources[0].kind is RequirementSourceKind.OWNER_INPUT
    assert added.sources[0].locator == f"TWIN_DISCUSSION:{discussion_source()}"
    assert added.user_twin_references == ()
    assert requirement.source_kind is InsightSourceKind.TWIN_DISCUSSION
    assert requirement.to_snapshot()["source_id"] == discussion_source()
    concern = apply(
        application,
        request(
            source_kind=InsightSourceKind.TWIN_DISCUSSION,
            source_id=discussion_source(2, "PRP-003"),
            source_twin_id=None,
            text="Keep the search box at the top of the dashboard.",
            target=InsightTarget.DESIGN,
            mitigation="Move the search box above the tiles.",
        ),
    )
    proposed = runtime.design_revision_service.proposed[0]["proposed_package"]
    assert proposed.concerns[-1].code == concern.target_code == "DRK-002"
    assert proposed.concerns[-1].summary == "Keep the search box at the top of the dashboard."
    assert proposed.concerns[-1].mitigation == "Move the search box above the tiles."
    assert concern.target_version_number == 4
    assert MemoryApplications.items == [requirement, concern]
    assert MemoryValidations.reads == 0


def test_router_registers_the_batch_route_before_the_other_application_routes():
    router = module.create_insight_application_router()
    assert [(route.path, sorted(route.methods)) for route in router.routes] == [
        ("/projects/{project_id}/insight-applications/batch", ["POST"]),
        ("/projects/{project_id}/insight-applications", ["POST"]),
        ("/projects/{project_id}/insight-applications", ["GET"]),
    ]


def batch(application, *bodies):
    return asyncio.run(
        application.apply_batch(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=design_fixtures.PROJECT_ID,
            bodies=bodies,
        )
    )


def brief_item(source_id, text, field=None):
    return request(
        source_kind=InsightSourceKind.TWIN_CHAT_INSIGHT,
        source_id=source_id,
        text=text,
        target=InsightTarget.BRIEF,
        brief_field=field,
    )


def test_a_batch_brings_several_insights_into_one_brief_version(monkeypatch):
    brief = create_project_brief(
        description="A reservation desk.",
        risks=("Peak hours",),
        unknown_fields=(BriefField.GOALS,),
    )
    application, _, created = service(monkeypatch, brief=brief)
    applications, version_number = batch(
        application,
        brief_item("turn-1:0", "Guests arrive in groups."),
        brief_item("turn-1:1", "Show the queue length.", BriefField.GOALS),
        brief_item("turn-2:0", "  Staff   change shifts at noon. ", BriefField.RISKS),
    )
    assert len(created) == 1
    assert created[0].functional_requirements == ("Guests arrive in groups.",)
    assert created[0].goals == ("Show the queue length.",)
    assert created[0].risks == ("Peak hours", "Staff change shifts at noon.")
    assert created[0].unknown_fields == frozenset()
    assert version_number == 2
    assert MemoryApplications.items == list(applications)
    assert [item.source_id for item in applications] == ["turn-1:0", "turn-1:1", "turn-2:0"]
    assert [item.target_field for item in applications] == [
        BriefField.FUNCTIONAL_REQUIREMENTS,
        BriefField.GOALS,
        BriefField.RISKS,
    ]
    assert {
        (item.target, item.target_version_id, item.target_version_number) for item in applications
    } == {(InsightTarget.BRIEF, UUID(int=55), 2)}
    assert len({item.created_at for item in applications}) == 1


def test_a_text_already_in_its_field_is_not_appended_twice(monkeypatch):
    brief = create_project_brief(description="A reservation desk.", risks=("Peak hours",))
    application, _, created = service(monkeypatch, brief=brief)
    applications, _ = batch(
        application,
        brief_item("turn-1:0", "Peak   hours", BriefField.RISKS),
        brief_item("turn-1:1", "Late check-in.", BriefField.RISKS),
        brief_item("turn-2:0", "Late check-in.", BriefField.RISKS),
        brief_item("turn-2:1", "Late check-in."),
    )
    assert created[0].risks == ("Peak hours", "Late check-in.")
    assert created[0].functional_requirements == ("Late check-in.",)
    assert len(applications) == 4
    assert MemoryApplications.items == list(applications)


def test_a_batch_refuses_other_targets_and_more_than_twenty_items(monkeypatch):
    application, runtime, created = service(
        monkeypatch,
        brief=create_project_brief(description="A reservation desk."),
        design=design_fixtures.design_version(),
    )
    with pytest.raises(HTTPException) as failure:
        batch(application, brief_item("turn-1:0", "One."), request(target=InsightTarget.DESIGN))
    assert failure.value.status_code == 422
    assert failure.value.detail == {"code": "INSIGHT_BATCH_TARGET_NOT_BRIEF"}
    items = [brief_item(f"turn-{index}:0", f"Insight {index}.") for index in range(21)]
    for invalid in (items, []):
        with pytest.raises(ValidationError):
            InsightBatchRequest(items=invalid)
    assert len(InsightBatchRequest(items=items[:20]).items) == 20
    assert created == []
    assert runtime.design_revision_service.proposed == []
    assert MemoryApplications.items == []


def test_an_already_applied_or_repeated_source_refuses_the_whole_batch(monkeypatch):
    application, _, created = service(
        monkeypatch,
        brief=create_project_brief(description="A reservation desk."),
        requirements=design_fixtures.requirements_version(),
    )
    batch(application, brief_item("turn-1:0", "Guests arrive in groups."))
    apply(
        application,
        request(
            source_kind=InsightSourceKind.TWIN_CHAT_INSIGHT,
            source_id="turn-5:0",
            text="Keep the reservation dates visible.",
        ),
    )
    recorded = list(MemoryApplications.items)
    created.clear()
    for bodies, sources in (
        (
            (brief_item("turn-2:0", "Show the queue."), brief_item("turn-1:0", "Groups.")),
            ["turn-1:0"],
        ),
        ((brief_item("turn-3:0", "One."), brief_item("turn-3:0", "Two.")), ["turn-3:0"]),
    ):
        with pytest.raises(HTTPException) as failure:
            batch(application, *bodies)
        assert failure.value.status_code == 409
        assert failure.value.detail == {"code": "INSIGHT_ALREADY_APPLIED", "sources": sources}
    assert created == []
    assert MemoryApplications.items == recorded
    applications, _ = batch(application, brief_item("turn-5:0", "Keep the dates visible."))
    assert [item.target for item in applications] == [InsightTarget.BRIEF]


def test_a_dismissed_source_refuses_the_whole_batch(monkeypatch):
    application, _, created = service(
        monkeypatch,
        brief=create_project_brief(description="A reservation desk."),
        validations=(owner_decision(FindingDecision.OWNER_DISMISSED),),
    )
    with pytest.raises(HTTPException) as failure:
        batch(
            application,
            brief_item("turn-1:0", "Guests arrive in groups."),
            request(source_id=finding_source(), target=InsightTarget.BRIEF),
        )
    assert failure.value.status_code == 409
    assert failure.value.detail == {
        "code": "INSIGHT_SOURCE_DISMISSED",
        "sources": [finding_source()],
    }
    assert MemoryValidations.reads == 1
    assert created == []
    assert MemoryApplications.items == []


def test_a_batch_writes_nothing_without_a_brief_or_a_new_brief_version(monkeypatch):
    application, _, _ = service(monkeypatch)
    with pytest.raises(HTTPException) as missing:
        batch(application, brief_item("turn-1:0", "One."))
    assert missing.value.status_code == 404
    assert missing.value.detail == {"code": "PROJECT_BRIEF_NOT_FOUND"}
    application, runtime, _ = service(
        monkeypatch, brief=create_project_brief(description="A reservation desk.")
    )

    async def refused(**kwargs):
        return SimpleNamespace(version=None)

    runtime.project_service.create_brief_version = refused
    with pytest.raises(HTTPException) as failure:
        batch(application, brief_item("turn-1:0", "One."), brief_item("turn-1:1", "Two."))
    assert failure.value.status_code == 409
    assert failure.value.detail == {"code": "BRIEF_VERSION_NOT_CREATED"}
    assert MemoryApplications.items == []


def test_the_batch_route_answers_with_the_applications_and_the_brief_version(monkeypatch):
    _, runtime, created = service(
        monkeypatch, brief=create_project_brief(description="A reservation desk.")
    )
    app = create_app(
        ApplicationSettings(api_prefix="/api/v1"),
        runtime=ApplicationRuntime(
            database_runtime=runtime.database_runtime, project_service=runtime.project_service
        ),
    )
    app.dependency_overrides[current_user_dependency] = lambda: replace(
        _user(), id=design_fixtures.OWNER_ID
    )
    http = TestClient(app)
    path = f"/api/v1/projects/{design_fixtures.PROJECT_ID}/insight-applications/batch"
    item = {
        "source_kind": "TWIN_CHAT_INSIGHT",
        "source_id": "turn-1:0",
        "text": "Guests arrive in groups.",
        "target": "BRIEF",
        "brief_field": "risks",
    }
    answered = http.post(
        path, json={"items": [item, {**item, "source_id": "turn-1:1", "text": "Show the queue."}]}
    )
    assert answered.status_code == 201
    payload = answered.json()
    assert payload["brief_version_number"] == 2
    assert [entry["source_id"] for entry in payload["applications"]] == ["turn-1:0", "turn-1:1"]
    assert {entry["target_field"] for entry in payload["applications"]} == {"risks"}
    assert payload["applications"][0] == MemoryApplications.items[0].to_snapshot()
    assert created[0].risks == ("Guests arrive in groups.", "Show the queue.")
    repeated = http.post(path, json={"items": [item]})
    assert repeated.status_code == 409
    assert repeated.json() == {
        "detail": {"code": "INSIGHT_ALREADY_APPLIED", "sources": ["turn-1:0"]}
    }
    for items in ([], [{**item, "source_id": f"turn-{index}:9"} for index in range(21)]):
        assert http.post(path, json={"items": items}).status_code == 422
    design = http.post(
        path, json={"items": [{**item, "source_id": "turn-9:0", "target": "DESIGN"}]}
    )
    assert design.status_code == 422
    assert design.json() == {"detail": {"code": "INSIGHT_BATCH_TARGET_NOT_BRIEF"}}
    assert len(created) == 1
    assert len(MemoryApplications.items) == 2
