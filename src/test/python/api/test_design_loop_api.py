from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID

import pytest
from fastapi import HTTPException

from orchestwin.api import design_loop
from orchestwin.api.design_loop import DesignEvaluationRequest, DesignLoopApplication
from orchestwin.artifacts.design_evaluation import DesignEvaluationRun
from orchestwin.evaluation.artifacts import EvaluationArtifactKind
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus
from src.test.python.artifacts import design_fixtures

CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="fake-design-evaluator",
    evaluator_version="1",
    model_config_ref="config-1",
    prompt_version_ref="prompt-1",
)


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


class MemoryRuns:
    runs: ClassVar[list[DesignEvaluationRun]] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def create(self, run):
        MemoryRuns.runs.append(run)
        return design_loop.DesignEvaluationWriteStatus.WRITTEN

    async def list(self, *, project_id, limit=50):
        items = [run for run in MemoryRuns.runs if run.project_id == project_id]
        return tuple(sorted(items, key=lambda run: run.started_at, reverse=True)[:limit])


class MemoryTwins:
    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def get(self, *, project_id, twin_id, version_number):
        reference = design_fixtures.twin_reference()
        if twin_id != reference.twin_id:
            return None
        return SimpleNamespace(
            twin_id=twin_id,
            version_number=version_number,
            content_hash=reference.content_hash,
            profile=SimpleNamespace(name=reference.name),
        )


class StubProfile:
    @staticmethod
    def from_version(version):
        snapshot = '{"name": "' + version.profile.name + '"}'
        return EvaluationUserTwinProfile(
            twin_id=version.twin_id,
            version_number=version.version_number,
            name=version.profile.name,
            lifecycle_status=next(iter(UserTwinLifecycleStatus)),
            content_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
            snapshot_json=snapshot,
        )


def template(finding_id, location, summary):
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        location=location,
        summary=summary,
        rationale="Simulated rationale.",
        criterion=SyntheticFindingCriterion.COMPREHENSIBILITY,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(f"artifact:{design_fixtures.PROTOTYPE_ID}:v1",),
        confidence=0.7,
        recommended_action="Explain the required format.",
        requires_human_validation=True,
    )


def application(monkeypatch, *, version=None, templates=None, evaluator=True, generation=None):
    MemoryRuns.runs = []
    current_version = version if version is not None else design_fixtures.design_version()
    monkeypatch.setattr(design_loop, "SqlAlchemyDesignEvaluationRepository", MemoryRuns)
    monkeypatch.setattr(design_loop, "SqlAlchemyUserTwinVersionRepository", MemoryTwins)
    monkeypatch.setattr(design_loop, "EvaluationUserTwinProfile", StubProfile)
    twin_id = design_fixtures.twin_reference().twin_id

    async def current(**kwargs):
        assert kwargs["owner_user_id"] == design_fixtures.OWNER_ID
        return current_version

    def create_evaluator(*, verified_content=None, **_):
        assert verified_content is not None
        return FakeUserTwinEvaluator(
            configuration=CONFIGURATION,
            templates_by_twin={twin_id: templates or ()},
            summaries_by_twin={twin_id: "Simulated summary."},
            clock=lambda: datetime.now(UTC),
        )

    runtime = SimpleNamespace(
        database_runtime=SimpleNamespace(session_factory=lambda: FakeSession()),
        design_query_service=SimpleNamespace(current=current),
        final_evaluator_runtime=SimpleNamespace(create_evaluator=create_evaluator)
        if evaluator
        else None,
        design_generation_service=generation,
    )
    body = DesignEvaluationRequest(
        design_version_id=current_version.id,
        design_content_hash=current_version.content_hash,
    )
    return DesignLoopApplication(runtime), body


def evaluate(app, body):
    return asyncio.run(
        app.evaluate(
            owner_user_id=design_fixtures.OWNER_ID,
            project_id=design_fixtures.PROJECT_ID,
            body=body,
        )
    )


def test_evaluation_runs_every_grounded_twin_and_persists_the_run(monkeypatch):
    app, body = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."),
        ),
    )
    run = evaluate(app, body)
    assert isinstance(run, DesignEvaluationRun)
    assert run.design_version_id == body.design_version_id
    assert [response.twin_id for response in run.responses] == [
        design_fixtures.twin_reference().twin_id
    ]
    assert [finding.finding_id for finding in run.findings] == ["UTF-001"]
    assert run.bundle.artifacts[1].kind is EvaluationArtifactKind.DOM_SNAPSHOT
    assert MemoryRuns.runs == [run]
    listed = asyncio.run(
        app.runs(owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID)
    )
    assert listed == (run,)
    snapshot = run.to_snapshot()
    assert snapshot["responses"][0]["findings"][0]["recommended_action"] == (
        "Explain the required format."
    )


@pytest.mark.parametrize(
    ("kwargs", "body_change", "status", "code"),
    [
        ({}, {"design_content_hash": "f" * 64}, 409, "DESIGN_CONTEXT_CHANGED"),
        ({"evaluator": False}, {}, 503, "DESIGN_EVALUATOR_NOT_CONFIGURED"),
    ],
)
def test_evaluation_rejects_stale_context_and_missing_evaluator(
    monkeypatch, kwargs, body_change, status, code
):
    app, body = application(monkeypatch, **kwargs)
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body.model_copy(update=body_change) if body_change else body)
    assert failure.value.status_code == status
    assert failure.value.detail["code"] == code


def test_evaluation_requires_a_selected_prototype(monkeypatch):
    version = design_fixtures.design_version()
    bare = design_fixtures.design_version(
        package=replace(version.package, owner_selected_alternative_id=None, prototype=None)
    )
    app, body = application(monkeypatch, version=bare)
    with pytest.raises(HTTPException) as failure:
        evaluate(app, body)
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "DESIGN_PROTOTYPE_REQUIRED"


def test_comparison_needs_two_runs_and_then_reports_resolved_findings(monkeypatch):
    app, body = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 Guest name", "The guest name lacks a format hint."),
            template("UTF-002", "SCR-002 Status", "The confirmation hides the next step."),
        ),
    )
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            app.comparison(
                owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
            )
        )
    assert failure.value.detail["code"] == "DESIGN_EVALUATION_COMPARISON_UNAVAILABLE"
    first = evaluate(app, body)
    second_app, _ = application(
        monkeypatch,
        templates=(
            template("UTF-001", "SCR-001 guest name", "The guest name lacks a format hint."),
        ),
    )
    MemoryRuns.runs = [first]
    second = evaluate(second_app, body)
    comparison = asyncio.run(
        second_app.comparison(
            owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
        )
    )
    assert comparison.base_run_id == first.id
    assert comparison.head_run_id == second.id
    assert comparison.to_snapshot()["counts"] == {
        "base": 2,
        "head": 1,
        "resolved": 1,
        "persisting": 1,
        "introduced": 0,
    }


def test_regeneration_delegates_to_the_generation_service(monkeypatch):
    calls = []

    async def regenerate(**kwargs):
        calls.append(kwargs)
        return "result"

    app, _ = application(monkeypatch, generation=SimpleNamespace(regenerate=regenerate))
    result = asyncio.run(
        app.regenerate(
            owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
        )
    )
    assert result == "result"
    assert calls == [
        {"owner_user_id": design_fixtures.OWNER_ID, "project_id": design_fixtures.PROJECT_ID}
    ]
    missing, _ = application(monkeypatch)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            missing.regenerate(
                owner_user_id=design_fixtures.OWNER_ID, project_id=design_fixtures.PROJECT_ID
            )
        )
    assert failure.value.status_code == 503


def test_router_registers_the_loop_routes():
    router = design_loop.create_design_loop_router()
    paths = sorted(route.path for route in router.routes)
    assert paths == [
        "/projects/{project_id}/design/evaluations",
        "/projects/{project_id}/design/evaluations",
        "/projects/{project_id}/design/evaluations/comparison",
        "/projects/{project_id}/design/regenerations",
    ]
    assert UUID(int=0) is not None
