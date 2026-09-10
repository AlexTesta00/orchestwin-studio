"""Persist completed owner-authorized User Twin evaluations."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from orchestwin.evaluation.authorized_persistence_application import (
    PersistedAuthorizedEvaluationError,
    PersistedAuthorizedEvaluationIssueCode,
    PersistedAuthorizedIndependentUserTwinEvaluationService,
)
from orchestwin.evaluation.persistence import (
    InMemorySyntheticEvaluationRepository,
    StoredSyntheticEvaluationRun,
    SyntheticEvaluationStoreResult,
    SyntheticEvaluationStoreStatus,
)

from .test_evaluation_persistence import _evaluation_run


class RecordingAuthorizedEvaluationService:
    def __init__(self, run) -> None:
        self.run = run
        self.calls = []

    async def evaluate(
        self,
        *,
        owner_user_id,
        artifact_bundle,
        targets,
        selected,
    ):
        self.calls.append(
            {
                "owner_user_id": owner_user_id,
                "artifact_bundle": artifact_bundle,
                "targets": tuple(targets),
                "selected": selected,
            }
        )
        return self.run


class BrokenFindingRepository:
    """Successful append result followed by inconsistent finding reads."""

    def __init__(self, run) -> None:
        self.run = run
        self.append_calls = []

    async def append(self, run):
        self.append_calls.append(run)
        return SyntheticEvaluationStoreResult(
            status=SyntheticEvaluationStoreStatus.CREATED,
            run=StoredSyntheticEvaluationRun.from_domain(run),
        )

    async def get_owned(self, *, run_id):
        assert run_id == self.run.id
        return StoredSyntheticEvaluationRun.from_domain(self.run)

    async def list_findings(self, *, run_id):
        assert run_id == self.run.id
        return ()


def _request_arguments(run):
    """Opaque delegate inputs; persistence must use the returned run."""
    return {
        "owner_user_id": run.owner_user_id,
        "artifact_bundle": SimpleNamespace(
            project_id=run.project_id,
            workflow_run_id=run.workflow_run_id,
        ),
        "targets": (),
        "selected": (),
    }


def test_authorized_run_and_findings_are_persisted_idempotently() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()

        delegate = RecordingAuthorizedEvaluationService(run)

        repository = InMemorySyntheticEvaluationRepository(
            owner_user_id=run.owner_user_id,
            workflow_run_projects={run.workflow_run_id: run.project_id},
        )

        service = PersistedAuthorizedIndependentUserTwinEvaluationService(
            evaluation_service=delegate,
            repository=repository,
        )

        first = await service.evaluate(**_request_arguments(run))

        second = await service.evaluate(**_request_arguments(run))

        assert first == run
        assert second == run

        assert len(delegate.calls) == 2

        stored = await repository.get_owned(run_id=run.id)

        assert stored == (StoredSyntheticEvaluationRun.from_domain(run))

        assert await repository.list_findings(run_id=run.id) == run.findings

    asyncio.run(scenario())


def test_missing_workflow_scope_is_a_typed_persistence_failure() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()

        delegate = RecordingAuthorizedEvaluationService(run)

        repository = InMemorySyntheticEvaluationRepository(
            owner_user_id=run.owner_user_id,
            workflow_run_projects={},
        )

        service = PersistedAuthorizedIndependentUserTwinEvaluationService(
            evaluation_service=delegate,
            repository=repository,
        )

        with pytest.raises(PersistedAuthorizedEvaluationError) as captured:
            await service.evaluate(**_request_arguments(run))

        assert captured.value.code is (
            PersistedAuthorizedEvaluationIssueCode.WORKFLOW_RUN_NOT_FOUND
        )

        assert await repository.get_owned(run_id=run.id) is None

        assert await repository.list_findings(run_id=run.id) == ()

    asyncio.run(scenario())


def test_persisted_findings_must_exactly_match_authorized_run() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()

        delegate = RecordingAuthorizedEvaluationService(run)

        repository = BrokenFindingRepository(run)

        service = PersistedAuthorizedIndependentUserTwinEvaluationService(
            evaluation_service=delegate,
            repository=repository,
        )

        with pytest.raises(PersistedAuthorizedEvaluationError) as captured:
            await service.evaluate(**_request_arguments(run))

        assert captured.value.code is (
            PersistedAuthorizedEvaluationIssueCode.STORAGE_INTEGRITY_MISMATCH
        )

        assert repository.append_calls == [run]

    asyncio.run(scenario())


def test_content_conflict_is_never_reported_as_success() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()

        conflicting = replace(
            run,
            owner_user_id=run.owner_user_id,
        )

        class ConflictRepository:
            async def append(self, candidate):
                assert candidate == conflicting
                return SyntheticEvaluationStoreResult(
                    status=(SyntheticEvaluationStoreStatus.CONTENT_CONFLICT),
                    run=None,
                )

            async def get_owned(self, *, run_id):
                raise AssertionError("conflict must stop before readback")

            async def list_findings(self, *, run_id):
                raise AssertionError("conflict must stop before readback")

        service = PersistedAuthorizedIndependentUserTwinEvaluationService(
            evaluation_service=(RecordingAuthorizedEvaluationService(conflicting)),
            repository=ConflictRepository(),
        )

        with pytest.raises(PersistedAuthorizedEvaluationError) as captured:
            await service.evaluate(**_request_arguments(conflicting))

        assert captured.value.code is (PersistedAuthorizedEvaluationIssueCode.CONTENT_CONFLICT)

    asyncio.run(scenario())
