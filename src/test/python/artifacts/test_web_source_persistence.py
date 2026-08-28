"""Tests for append-only owner-scoped Web source revision persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.artifacts.web_source_persistence import (
    InMemoryWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
    web_source_revision_from_record,
    web_source_revision_to_record,
)
from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    create_web_source_revision,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000008501")
FOREIGN_PROJECT_ID = UUID("00000000-0000-4000-8000-000000008502")
OWNER_ID = UUID("00000000-0000-4000-8000-000000008503")
NOW = datetime(2026, 8, 26, 13, 0, tzinfo=UTC)


def revision(*, revision_id: UUID, version: int, based_on=None):
    digest = f"{version:x}" * 64
    return create_web_source_revision(
        revision_id=revision_id,
        project_id=PROJECT_ID,
        created_by_user_id=OWNER_ID,
        version_number=version,
        based_on=based_on,
        target=ExecutionTarget.WEB_STATIC,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS,
            backend=None,
        ),
        layout=WebProjectLayout.SINGLE_ROOT,
        origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
        files=(
            WebSourceFileEntry(
                normalized_path="index.html",
                sha256_digest=digest,
                size_bytes=version,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                media_type="text/html",
            ),
        ),
        provenance_references=(
            WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.SOURCE_PLAN,
                reference_id=f"source-plan:v{version}",
                version_number=version,
                content_hash="a" * 64,
            ),
        ),
        created_at=NOW,
    )


def test_record_round_trip_revalidates_all_projected_columns() -> None:
    original = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008504"),
        version=1,
    )

    restored = web_source_revision_from_record(web_source_revision_to_record(original))

    assert restored == original
    assert restored.content_hash == original.content_hash


def test_in_memory_repository_is_idempotent_and_linear() -> None:
    repository = InMemoryWebSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    first = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008505"),
        version=1,
    )
    second = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008506"),
        version=2,
        based_on=first.reference,
    )

    async def scenario() -> None:
        assert (await repository.append(first)).status is WebSourceRevisionAppendStatus.APPENDED
        assert (
            await repository.append(first)
        ).status is WebSourceRevisionAppendStatus.ALREADY_PRESENT
        assert (await repository.append(second)).status is WebSourceRevisionAppendStatus.APPENDED
        assert await repository.current(project_id=PROJECT_ID) == second
        assert await repository.history(project_id=PROJECT_ID) == (first, second)

    asyncio.run(scenario())


def test_in_memory_repository_hides_foreign_projects() -> None:
    repository = InMemoryWebSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({FOREIGN_PROJECT_ID}),
    )
    candidate = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008507"),
        version=1,
    )

    result = asyncio.run(repository.append(candidate))

    assert result.status is WebSourceRevisionAppendStatus.PROJECT_NOT_FOUND
    assert result.revision is None


def test_repository_rejects_a_non_next_version() -> None:
    repository = InMemoryWebSourceRevisionRepository(
        owner_user_id=OWNER_ID,
        project_ids=frozenset({PROJECT_ID}),
    )
    first = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008508"),
        version=1,
    )
    conflicting = revision(
        revision_id=UUID("00000000-0000-4000-8000-000000008509"),
        version=2,
        based_on=first.reference,
    )

    async def scenario() -> None:
        assert (await repository.append(conflicting)).status is (
            WebSourceRevisionAppendStatus.VERSION_CONFLICT
        )

    asyncio.run(scenario())
