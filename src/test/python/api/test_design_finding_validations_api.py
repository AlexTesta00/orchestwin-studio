from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from orchestwin.api import design_loop
from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design_loop import DesignLoopApplication, FindingValidationRequest
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_finding_validation_persistence import (
    FindingValidationWriteResult,
    FindingValidationWriteStatus,
)
from orchestwin.artifacts.design_finding_validations import (
    MAX_FINDING_NOTE_LENGTH,
    FindingDecision,
    create_finding_validation,
    finding_validation_from_snapshot,
)
from orchestwin.config import ApplicationSettings
from src.test.python.api.test_training_api import _user
from src.test.python.artifacts import design_fixtures
from src.test.python.artifacts.test_design_evaluation import (
    NOW,
    TWIN_A,
    TWIN_B,
    evaluate,
    template,
)

OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
BASE_RUN = UUID("00000000-0000-4000-8000-000000000901")
HEAD_RUN = UUID("00000000-0000-4000-8000-000000000902")
PATH = f"/api/v1/projects/{PROJECT}/design/evaluations"


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
    runs: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def list(self, *, project_id, limit=50):
        items = [
            run
            for run in MemoryRuns.runs
            if run.project_id == project_id and run.owner_user_id == self.owner_user_id
        ]
        return tuple(sorted(items, key=lambda run: run.started_at, reverse=True)[:limit])


class MemoryValidations:
    findings: ClassVar[set] = set()
    items: ClassVar[list] = []

    def __init__(self, session, *, owner_user_id):
        self.owner_user_id = owner_user_id

    async def append(
        self, *, project_id, evaluation_run_id, twin_id, finding_id, decision, note, decided_at
    ):
        key = (evaluation_run_id, twin_id, finding_id)
        if (self.owner_user_id, project_id, key) not in MemoryValidations.findings:
            return FindingValidationWriteResult(FindingValidationWriteStatus.FINDING_NOT_FOUND)
        validation = create_finding_validation(
            evaluation_run_id=evaluation_run_id,
            twin_id=twin_id,
            finding_id=finding_id,
            sequence_number=1 + sum(item.key == key for item in MemoryValidations.items),
            project_id=project_id,
            owner_user_id=self.owner_user_id,
            decision=decision,
            note=note,
            decided_at=decided_at,
        )
        MemoryValidations.items.append(validation)
        return FindingValidationWriteResult(FindingValidationWriteStatus.WRITTEN, validation)

    async def current(self, *, project_id):
        latest = {}
        for item in MemoryValidations.items:
            if item.project_id == project_id and item.owner_user_id == self.owner_user_id:
                latest[item.key] = item
        return tuple(sorted(latest.values(), key=lambda item: item.decided_at))


def base_run():
    return evaluate(
        design_fixtures.design_version(),
        {
            TWIN_A: (
                template("UTF-001", "SCR-001 Guest name", "The guest name field lacks help text."),
                template("UTF-002", "SCR-001 Save", "The save button label is vague."),
            ),
            TWIN_B: (
                template("UTF-003", "SCR-002 status", "The confirmation hides the next step."),
            ),
        },
        run_id=BASE_RUN,
    )


def head_run():
    return evaluate(
        design_fixtures.design_version(),
        {
            TWIN_A: (
                template(
                    "UTF-001", "SCR-001 guest name", "The guest name field still lacks help text."
                ),
                template("UTF-004", "SCR-001 Dates", "The date fields need a format hint."),
            ),
            TWIN_B: (),
        },
        run_id=HEAD_RUN,
        clock=NOW + timedelta(minutes=10),
    )


def install(monkeypatch, runs):
    MemoryRuns.runs = list(runs)
    MemoryValidations.items = []
    MemoryValidations.findings = {
        (run.owner_user_id, run.project_id, (run.id, finding.twin_id, finding.finding_id))
        for run in runs
        for finding in run.findings
    }
    monkeypatch.setattr(design_loop, "SqlAlchemyDesignEvaluationRepository", MemoryRuns)
    monkeypatch.setattr(design_loop, "SqlAlchemyFindingValidationRepository", MemoryValidations)
    return SimpleNamespace(session_factory=FakeSession)


def application(monkeypatch, *runs, database=True):
    sessions = install(monkeypatch, runs)
    return DesignLoopApplication(SimpleNamespace(database_runtime=sessions if database else None))


def record(app, run_id, twin_id, finding_id, decision, note=None, *, owner=OWNER, project=PROJECT):
    return asyncio.run(
        app.record_validation(
            owner_user_id=owner,
            project_id=project,
            run_id=run_id,
            body=FindingValidationRequest(
                twin_id=twin_id, finding_id=finding_id, decision=decision, note=note
            ),
        )
    )


def test_owner_decisions_are_appended_with_per_finding_sequence_numbers(monkeypatch):
    app = application(monkeypatch, base_run())
    first = record(
        app, BASE_RUN, TWIN_A, "UTF-001", FindingDecision.OWNER_DISMISSED, "  Not   for guests "
    )
    second = record(app, BASE_RUN, TWIN_A, "UTF-001", FindingDecision.OWNER_CONFIRMED)
    other = record(app, BASE_RUN, TWIN_B, "UTF-003", FindingDecision.OWNER_DISMISSED)
    assert [first.sequence_number, second.sequence_number, other.sequence_number] == [1, 2, 1]
    assert (first.note, second.note) == ("Not for guests", None)
    assert {first.owner_user_id, first.project_id} == {OWNER, PROJECT}
    assert first.decided_at.tzinfo is not None
    assert MemoryValidations.items == [first, second, other]
    current = asyncio.run(app.validations(owner_user_id=OWNER, project_id=PROJECT))
    assert set(current) == {second, other}
    assert asyncio.run(app.validations(owner_user_id=uuid4(), project_id=PROJECT)) == ()


@pytest.mark.parametrize(
    ("arguments", "keywords"),
    [
        ((BASE_RUN, TWIN_A, "UTF-009"), {}),
        ((BASE_RUN, TWIN_B, "UTF-001"), {}),
        ((HEAD_RUN, TWIN_A, "UTF-001"), {}),
        ((BASE_RUN, TWIN_A, "UTF-001"), {"owner": UUID(int=99)}),
        ((BASE_RUN, TWIN_A, "UTF-001"), {"project": UUID(int=98)}),
    ],
)
def test_unknown_or_foreign_findings_are_not_found(monkeypatch, arguments, keywords):
    app = application(monkeypatch, base_run())
    with pytest.raises(HTTPException) as failure:
        record(app, *arguments, FindingDecision.OWNER_DISMISSED, **keywords)
    assert failure.value.status_code == 404
    assert failure.value.detail == {"code": "DESIGN_FINDING_NOT_FOUND"}
    assert MemoryValidations.items == []


def test_invalid_notes_are_refused_before_any_database_access(monkeypatch):
    for database in (True, False):
        app = application(monkeypatch, base_run(), database=database)
        for note in ("   ", "x" * (MAX_FINDING_NOTE_LENGTH + 1)):
            with pytest.raises(HTTPException) as failure:
                record(app, BASE_RUN, TWIN_A, "UTF-001", FindingDecision.OWNER_CONFIRMED, note)
            assert failure.value.status_code == 422
            assert failure.value.detail == {"code": "FINDING_NOTE_INVALID"}
    assert MemoryValidations.items == []
    offline = application(monkeypatch, base_run(), database=False)
    for call in (
        lambda: record(offline, BASE_RUN, TWIN_A, "UTF-001", FindingDecision.OWNER_CONFIRMED),
        lambda: asyncio.run(offline.validations(owner_user_id=OWNER, project_id=PROJECT)),
    ):
        with pytest.raises(HTTPException) as failure:
            call()
        assert failure.value.status_code == 503
        assert failure.value.detail == {"code": "DATABASE_UNAVAILABLE"}


def test_dismissed_findings_are_left_out_of_the_comparison(monkeypatch):
    app = application(monkeypatch, base_run(), head_run())
    before = asyncio.run(app.comparison(owner_user_id=OWNER, project_id=PROJECT))
    assert before.to_snapshot()["counts"] == {
        "base": 3,
        "head": 2,
        "resolved": 2,
        "persisting": 1,
        "introduced": 1,
        "dismissed": 0,
    }
    record(app, HEAD_RUN, TWIN_A, "UTF-004", FindingDecision.OWNER_DISMISSED)
    record(app, BASE_RUN, TWIN_B, "UTF-003", FindingDecision.OWNER_DISMISSED)
    record(app, BASE_RUN, TWIN_A, "UTF-002", FindingDecision.OWNER_DISMISSED)
    record(app, BASE_RUN, TWIN_A, "UTF-002", FindingDecision.OWNER_CONFIRMED)
    dismissed = asyncio.run(app._dismissed(owner_user_id=OWNER, project_id=PROJECT))
    assert dismissed == {(HEAD_RUN, TWIN_A, "UTF-004"), (BASE_RUN, TWIN_B, "UTF-003")}
    after = asyncio.run(app.comparison(owner_user_id=OWNER, project_id=PROJECT))
    assert after.to_snapshot()["counts"] == {
        "base": 2,
        "head": 1,
        "resolved": 1,
        "persisting": 1,
        "introduced": 0,
        "dismissed": 2,
    }
    assert [item.finding_id for item in after.resolved] == ["UTF-002"]
    assert [(old.finding_id, new.finding_id) for old, new in after.persisting] == [
        ("UTF-001", "UTF-001")
    ]
    assert asyncio.run(app._dismissed(owner_user_id=uuid4(), project_id=PROJECT)) == frozenset()


def client(monkeypatch, *runs, database=True):
    sessions = install(monkeypatch, runs)
    app = create_app(
        ApplicationSettings(api_prefix="/api/v1"),
        runtime=ApplicationRuntime(database_runtime=sessions if database else None),
    )
    app.dependency_overrides[current_user_dependency] = lambda: replace(_user(), id=OWNER)
    return TestClient(app)


def test_routes_return_created_snapshots_and_coded_errors(monkeypatch):
    http = client(monkeypatch, base_run())
    body = {
        "twin_id": str(TWIN_A),
        "finding_id": "UTF-001",
        "decision": "OWNER_DISMISSED",
        "note": " Out of scope ",
    }
    created = http.post(f"{PATH}/{BASE_RUN}/validations", json=body)
    assert created.status_code == 201
    snapshot = created.json()
    assert set(snapshot) == {
        "evaluation_run_id",
        "twin_id",
        "finding_id",
        "sequence_number",
        "project_id",
        "owner_user_id",
        "decision",
        "note",
        "decided_at",
        "content_hash",
    }
    assert (snapshot["note"], snapshot["sequence_number"]) == ("Out of scope", 1)
    assert finding_validation_from_snapshot(snapshot) == MemoryValidations.items[0]
    listed = http.get(f"{PATH}/validations")
    assert (listed.status_code, listed.json()) == (200, [snapshot])
    missing = http.post(f"{PATH}/{uuid4()}/validations", json=body)
    assert (missing.status_code, missing.json()) == (
        404,
        {"detail": {"code": "DESIGN_FINDING_NOT_FOUND"}},
    )
    blank = http.post(f"{PATH}/{BASE_RUN}/validations", json={**body, "note": "  "})
    assert (blank.status_code, blank.json()) == (
        422,
        {"detail": {"code": "FINDING_NOTE_INVALID"}},
    )
    for changed in (
        {"reviewer": "someone"},
        {"decision": "USER_VALIDATED"},
        {"finding_id": "UTF-1"},
        {"twin_id": "twin"},
    ):
        refused = http.post(f"{PATH}/{BASE_RUN}/validations", json={**body, **changed})
        assert refused.status_code == 422
    assert len(MemoryValidations.items) == 1
    offline = client(monkeypatch, base_run(), database=False).get(f"{PATH}/validations")
    assert (offline.status_code, offline.json()) == (
        503,
        {"detail": {"code": "DATABASE_UNAVAILABLE"}},
    )
