"""Tests for owner-scoped JVM attempt persistence and snapshot verification."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from orchestwin.jvm_execution.attempt_persistence import (
    InMemoryJvmExecutionAttemptRepository,
    JvmExecutionAttemptAppendStatus,
    jvm_execution_attempt_from_record,
    jvm_execution_attempt_to_record,
)
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger

from .attempt_support import OWNER_ID, PROJECT_ID, execution_attempt


def test_record_round_trip_preserves_nested_evidence() -> None:
    attempt = execution_attempt()
    record = jvm_execution_attempt_to_record(attempt)

    restored = jvm_execution_attempt_from_record(record)

    assert restored == attempt
    assert restored.content_hash == attempt.content_hash


def test_record_tampering_is_rejected() -> None:
    record = jvm_execution_attempt_to_record(execution_attempt())
    record["runner_image_digest"] = "0" * 64

    with pytest.raises(ValueError, match="runner_image_digest"):
        jvm_execution_attempt_from_record(record)


def test_in_memory_repository_enforces_owner_lineage_and_idempotency() -> None:
    async def scenario() -> None:
        repository = InMemoryJvmExecutionAttemptRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        first = execution_attempt()
        appended = await repository.append(first)
        duplicate = await repository.append(first)
        second = execution_attempt(
            attempt_id=UUID("91000000-0000-4000-8000-000000000005"),
            attempt_number=2,
            previous_attempt_id=first.id,
            trigger=JvmExecutionAttemptTrigger.REPAIR_RERUN,
        )
        rerun = await repository.append(second)

        assert appended.status is JvmExecutionAttemptAppendStatus.APPENDED
        assert duplicate.status is JvmExecutionAttemptAppendStatus.ALREADY_PRESENT
        assert rerun.status is JvmExecutionAttemptAppendStatus.APPENDED
        assert await repository.current(project_id=PROJECT_ID) == second
        assert await repository.history(project_id=PROJECT_ID) == (first, second)

    asyncio.run(scenario())


def test_in_memory_repository_hides_foreign_or_unknown_projects() -> None:
    async def scenario() -> None:
        repository = InMemoryJvmExecutionAttemptRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        foreign = execution_attempt(created_by_user_id=UUID("91000000-0000-4000-8000-000000000099"))

        result = await repository.append(foreign)

        assert result.status is JvmExecutionAttemptAppendStatus.PROJECT_NOT_FOUND
        assert (
            await repository.current(project_id=UUID("91000000-0000-4000-8000-000000000098"))
            is None
        )

    asyncio.run(scenario())
