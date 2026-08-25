"""Tests for project-scoped immutable sandbox run evidence."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.sandbox.evidence import (
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogReference,
    SandboxLogStream,
    SandboxRunEvidence,
    SandboxRunStatus,
)
from orchestwin.sandbox.project_runs import (
    ProjectSandboxRunEvidence,
    project_sandbox_run_reference,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000007501")
OWNER_ID = UUID("00000000-0000-4000-8000-000000007502")
RUN_ID = UUID("00000000-0000-4000-8000-000000007503")
INTAKE_ID = UUID("00000000-0000-4000-8000-000000007504")
STARTED_AT = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
FINISHED_AT = STARTED_AT + timedelta(seconds=5)
RECORDED_AT = FINISHED_AT + timedelta(seconds=1)


def _log(stream: SandboxLogStream) -> SandboxLogReference:
    digest = "a" * 64 if stream is SandboxLogStream.STDOUT else "b" * 64
    return SandboxLogReference(
        stream=stream,
        sha256_digest=digest,
        size_bytes=4,
        storage_key=f"sha256/{digest[:2]}/{digest}",
    )


def _evidence() -> SandboxRunEvidence:
    command = SandboxCommandEvidence(
        command_id="quality.tests",
        status=SandboxCommandStatus.SUCCEEDED,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        exit_code=0,
        stdout_log=_log(SandboxLogStream.STDOUT),
        stderr_log=_log(SandboxLogStream.STDERR),
        artifacts=(),
        output_parser_id="pytest.v1",
        failure_message=None,
    )
    return SandboxRunEvidence(
        run_id=RUN_ID,
        plan_id="quality.plan",
        plan_content_hash="c" * 64,
        profile_id="builtin.web.static",
        profile_version="1.0.0",
        image_reference="example/web@sha256:" + "d" * 64,
        runtime_reference="fake.container.v1",
        status=SandboxRunStatus.SUCCEEDED,
        started_at=STARTED_AT,
        finished_at=FINISHED_AT,
        planned_command_ids=("quality.tests",),
        command_evidence=(command,),
        failure_message=None,
    )


def _intake_reference(project_id: UUID = PROJECT_ID) -> BrownfieldIntakeReference:
    return BrownfieldIntakeReference(
        intake_id=INTAKE_ID,
        project_id=project_id,
        version_number=2,
        content_hash="e" * 64,
    )


def _project_run() -> ProjectSandboxRunEvidence:
    return ProjectSandboxRunEvidence(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        evidence=_evidence(),
        brownfield_intake_reference=_intake_reference(),
        recorded_at=RECORDED_AT,
    )


def test_project_run_binds_exact_raw_evidence_and_brownfield_context() -> None:
    """Keep execution evidence linked to the project snapshot that authorized it."""
    run = _project_run()
    snapshot = run.to_snapshot()

    assert run.run_id == RUN_ID
    assert snapshot["project_id"] == str(PROJECT_ID)
    assert snapshot["brownfield_intake_reference"] == _intake_reference().to_snapshot()
    assert snapshot["evidence"] == _evidence().to_snapshot()
    stdout = snapshot["evidence"]["command_evidence"][0]["stdout_log"]
    assert "content" not in stdout
    assert len(run.content_hash) == 64


def test_project_run_reference_targets_the_exact_envelope_hash() -> None:
    """Support stale checks without duplicating the complete run snapshot."""
    run = _project_run()
    reference = project_sandbox_run_reference(run)

    assert reference.run_id == RUN_ID
    assert reference.project_id == PROJECT_ID
    assert reference.content_hash == run.content_hash


def test_project_run_rejects_foreign_intake_and_invalid_recording_time() -> None:
    """Prevent cross-project context links and impossible evidence chronology."""
    run = _project_run()

    with pytest.raises(ValueError, match="another project"):
        replace(
            run,
            brownfield_intake_reference=_intake_reference(UUID(int=999)),
        )

    with pytest.raises(ValueError, match="before execution finished"):
        replace(run, recorded_at=STARTED_AT)

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(run, recorded_at=RECORDED_AT.replace(tzinfo=None))


def test_project_run_is_immutable_and_hash_changes_with_context() -> None:
    """Make owner, project, and intake changes visible in the evidence identity."""
    run = _project_run()

    with pytest.raises(FrozenInstanceError):
        run.recorded_at = RECORDED_AT  # type: ignore[misc]

    assert replace(run, brownfield_intake_reference=None).content_hash != run.content_hash
    assert replace(run, owner_user_id=UUID(int=1000)).content_hash != run.content_hash
