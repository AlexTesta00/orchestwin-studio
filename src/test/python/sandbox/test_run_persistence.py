"""Tests for owner-scoped immutable sandbox-run persistence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from test_project_runs import (
    FINISHED_AT,
    OWNER_ID,
    PROJECT_ID,
    RECORDED_AT,
    RUN_ID,
    STARTED_AT,
    _intake_reference,
    _project_run,
)

from orchestwin.projects.domain import ProjectMode, create_project
from orchestwin.sandbox.project_runs import ProjectSandboxRunEvidence
from orchestwin.sandbox.run_persistence import (
    InMemorySandboxRunRepository,
    SandboxRunStoreStatus,
    persisted_project_sandbox_run_from_records,
    project_sandbox_run_to_records,
)

FOREIGN_OWNER_ID = UUID("00000000-0000-4000-8000-000000007551")
SECOND_RUN_ID = UUID("00000000-0000-4000-8000-000000007552")


def _project(owner_id: UUID = OWNER_ID):
    return create_project(
        project_id=PROJECT_ID,
        owner_user_id=owner_id,
        display_name="Sandbox persistence fixture",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=STARTED_AT,
    )


def _repository(
    *,
    owner_id: UUID = OWNER_ID,
    with_intake: bool = True,
) -> InMemorySandboxRunRepository:
    return InMemorySandboxRunRepository(
        owner_user_id=owner_id,
        projects={PROJECT_ID: _project()},
        intake_references=(_intake_reference(),) if with_intake else (),
    )


def test_run_and_command_records_round_trip_exact_evidence_metadata() -> None:
    """Persist raw-log and artifact references without duplicating raw bytes."""
    run = _project_run()
    run_record, command_records = project_sandbox_run_to_records(run)
    persisted = persisted_project_sandbox_run_from_records(run_record, command_records)

    assert persisted.run_id == RUN_ID
    assert persisted.evidence_content_hash == run.content_hash
    assert persisted.intake_reference == _intake_reference()
    assert persisted.evidence_snapshot == run.to_snapshot()
    assert len(persisted.command_results) == 1
    assert persisted.command_results[0].stdout_log["stream"] == "STDOUT"
    assert "content" not in persisted.command_results[0].stdout_log


def test_persistence_projection_rejects_tampered_run_or_command_metadata() -> None:
    """Never trust relational projections that contradict immutable JSON evidence."""
    run_record, command_records = project_sandbox_run_to_records(_project_run())
    run_record["plan_content_hash"] = "f" * 64
    with pytest.raises(ValueError, match="run projection"):
        persisted_project_sandbox_run_from_records(run_record, command_records)

    run_record, command_records = project_sandbox_run_to_records(_project_run())
    tampered_command = dict(command_records[0])
    tampered_command["status"] = "FAILED"
    with pytest.raises(ValueError, match="failed command persistence shape"):
        persisted_project_sandbox_run_from_records(run_record, (tampered_command,))


def test_in_memory_repository_stores_and_reuses_one_exact_run() -> None:
    """Make retries idempotent while preserving one immutable evidence identity."""
    repository = _repository()
    run = _project_run()

    first = asyncio.run(repository.store(run))
    repeated = asyncio.run(repository.store(run))
    loaded = asyncio.run(repository.get(run_id=RUN_ID))

    assert first.status is SandboxRunStoreStatus.STORED
    assert repeated.status is SandboxRunStoreStatus.ALREADY_PRESENT
    assert loaded == first.run == repeated.run


def test_in_memory_repository_rejects_foreign_owner_and_unknown_intake() -> None:
    """Keep project ownership and exact source-intake context mandatory."""
    foreign_run = replace(_project_run(), owner_user_id=FOREIGN_OWNER_ID)
    foreign = asyncio.run(_repository().store(foreign_run))
    missing_context = asyncio.run(_repository(with_intake=False).store(_project_run()))

    assert foreign.status is SandboxRunStoreStatus.PROJECT_NOT_FOUND
    assert missing_context.status is SandboxRunStoreStatus.INTAKE_CONTEXT_NOT_FOUND


def test_in_memory_repository_rejects_run_id_reuse_with_different_content() -> None:
    """Prevent one runtime identifier from silently changing evidence."""
    repository = _repository()
    original = _project_run()
    changed = replace(original, recorded_at=RECORDED_AT + timedelta(seconds=1))

    assert asyncio.run(repository.store(original)).status is SandboxRunStoreStatus.STORED
    conflict = asyncio.run(repository.store(changed))

    assert conflict.status is SandboxRunStoreStatus.RUN_CONFLICT
    assert conflict.run is None


def test_history_is_owner_scoped_and_stably_ordered() -> None:
    """Expose project execution history without leaking foreign projects."""
    repository = _repository()
    first = _project_run()
    second_evidence = replace(
        first.evidence,
        run_id=SECOND_RUN_ID,
        started_at=STARTED_AT + timedelta(seconds=10),
        finished_at=FINISHED_AT + timedelta(seconds=10),
        command_evidence=(
            replace(
                first.evidence.command_evidence[0],
                started_at=STARTED_AT + timedelta(seconds=10),
                finished_at=FINISHED_AT + timedelta(seconds=10),
            ),
        ),
    )
    second = ProjectSandboxRunEvidence(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        evidence=second_evidence,
        brownfield_intake_reference=_intake_reference(),
        recorded_at=RECORDED_AT + timedelta(seconds=10),
    )

    asyncio.run(repository.store(second))
    asyncio.run(repository.store(first))
    history = asyncio.run(repository.history(project_id=PROJECT_ID))

    assert tuple(run.run_id for run in history) == (RUN_ID, SECOND_RUN_ID)
    assert asyncio.run(_repository(owner_id=FOREIGN_OWNER_ID).history(project_id=PROJECT_ID)) == ()
