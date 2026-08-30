"""Tests for append-only owner-scoped JVM source revision persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.artifacts.jvm_source_persistence import (
    InMemoryJvmSourceRevisionRepository,
    JvmSourceRevisionAppendStatus,
    jvm_source_revision_from_record,
    jvm_source_revision_to_record,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget

PROJECT_ID = UUID("00000000-0000-4000-8000-000000009501")
FOREIGN_PROJECT_ID = UUID("00000000-0000-4000-8000-000000009502")
OWNER_ID = UUID("00000000-0000-4000-8000-000000009503")
NOW = datetime(2026, 8, 28, 13, 0, tzinfo=UTC)


def revision(*, revision_id: UUID, version: int, based_on=None):
    digest = f"{version:x}" * 64
    return create_jvm_source_revision(
        revision_id=revision_id,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=version,
        based_on=based_on,
        target=ExecutionTarget.JVM_KOTLIN,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            JvmSourceFileEntry(
                normalized_path="src/main/kotlin/example/Main.kt",
                sha256_digest=digest,
                size_bytes=version,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/x-kotlin",
            ),
        ),
        provenance_references=(
            JvmSourceProvenanceReference(
                kind=JvmSourceProvenanceKind.SOURCE_PLAN,
                reference_id=f"source-plan:v{version}",
                version_number=version,
                content_hash="a" * 64,
            ),
        ),
        created_at=NOW,
    )


def test_record_round_trip_revalidates_all_projected_columns() -> None:
    original = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009504"),
        version=1,
    )

    restored = jvm_source_revision_from_record(jvm_source_revision_to_record(original))

    assert restored == original
    assert restored.content_hash == original.content_hash


def test_in_memory_repository_is_idempotent_and_linear() -> None:
    repository = InMemoryJvmSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    first = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009505"),
        version=1,
    )
    second = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009506"),
        version=2,
        based_on=first.reference,
    )

    async def scenario() -> None:
        assert (await repository.append(first)).status is JvmSourceRevisionAppendStatus.APPENDED
        assert (
            await repository.append(first)
        ).status is JvmSourceRevisionAppendStatus.ALREADY_PRESENT
        assert (await repository.append(second)).status is JvmSourceRevisionAppendStatus.APPENDED
        assert await repository.current(project_id=PROJECT_ID) == second
        assert await repository.history(project_id=PROJECT_ID) == (first, second)

    asyncio.run(scenario())


def test_in_memory_repository_hides_foreign_projects() -> None:
    repository = InMemoryJvmSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({FOREIGN_PROJECT_ID}),
    )
    candidate = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009507"),
        version=1,
    )

    result = asyncio.run(repository.append(candidate))

    assert result.status is JvmSourceRevisionAppendStatus.PROJECT_NOT_FOUND
    assert result.revision is None


def test_repository_rejects_a_non_next_version() -> None:
    repository = InMemoryJvmSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    first = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009508"),
        version=1,
    )
    conflicting = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000009509"),
        version=2,
        based_on=first.reference,
    )

    async def scenario() -> None:
        result = await repository.append(conflicting)
        assert result.status is JvmSourceRevisionAppendStatus.VERSION_CONFLICT

    asyncio.run(scenario())
