"""Tests for owner-scoped brownfield intake persistence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from test_brownfield_intake import CREATED_AT, OWNER_ID, PROJECT_ID, _snapshot

from orchestwin.projects.brownfield_intake import BrownfieldIntakeVersion
from orchestwin.projects.brownfield_persistence import (
    BrownfieldIntakeAppendStatus,
    InMemoryBrownfieldIntakeRepository,
    brownfield_intake_version_to_record,
    persisted_brownfield_intake_from_record,
)
from orchestwin.projects.domain import ProjectMode, create_project

INTAKE_ID = UUID("00000000-0000-4000-8000-000000007451")
FOREIGN_OWNER_ID = UUID("00000000-0000-4000-8000-000000007452")
GREENFIELD_ID = UUID("00000000-0000-4000-8000-000000007453")


def _project(project_id: UUID, *, mode: ProjectMode, owner_id: UUID = OWNER_ID):
    return create_project(
        project_id=project_id,
        owner_user_id=owner_id,
        display_name="Persistence fixture",
        mode=mode,
        created_at=CREATED_AT,
    )


def _version(
    *,
    version_number: int = 1,
    based_on_version_number: int | None = None,
    creator_id: UUID = OWNER_ID,
) -> BrownfieldIntakeVersion:
    snapshot = _snapshot()
    return BrownfieldIntakeVersion(
        id=INTAKE_ID,
        project_id=PROJECT_ID,
        version_number=version_number,
        based_on_version_number=based_on_version_number,
        snapshot=snapshot,
        content_hash=snapshot.content_hash,
        created_by_user_id=creator_id,
        created_at=CREATED_AT,
    )


def test_record_projection_round_trips_canonical_snapshot_metadata() -> None:
    """Validate projected columns against the complete canonical JSONB snapshot."""
    version = _version()
    record = brownfield_intake_version_to_record(version)
    persisted = persisted_brownfield_intake_from_record(record)

    assert persisted.id == version.id
    assert persisted.content_hash == version.content_hash
    assert persisted.archive_sha256 == version.snapshot.archive.sha256_digest
    assert persisted.inventory_content_hash == version.snapshot.inventory.content_hash
    assert persisted.snapshot == version.snapshot.to_snapshot()
    assert persisted.snapshot_json == version.snapshot.canonical_json()


def test_record_projection_rejects_tampered_jsonb_or_selected_profile_columns() -> None:
    """Do not trust database projections that contradict their immutable snapshot."""
    record = brownfield_intake_version_to_record(_version())
    record["archive_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="archive projection"):
        persisted_brownfield_intake_from_record(record)

    record = brownfield_intake_version_to_record(_version())
    record["selected_profile_id"] = "WEB_STATIC"
    with pytest.raises(ValueError, match="all-null or complete"):
        persisted_brownfield_intake_from_record(record)


def test_in_memory_repository_appends_and_reuses_exact_content() -> None:
    """Make retrying one exact intake idempotent without creating version drift."""
    repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={
            PROJECT_ID: _project(
                PROJECT_ID,
                mode=ProjectMode.BROWNFIELD_ASSESSMENT,
            )
        },
    )
    version = _version()

    first = asyncio.run(repository.append(version))
    repeated = asyncio.run(repository.append(replace(version, id=UUID(int=999))))
    history = asyncio.run(repository.history(project_id=PROJECT_ID))

    assert first.status is BrownfieldIntakeAppendStatus.APPENDED
    assert repeated.status is BrownfieldIntakeAppendStatus.ALREADY_PRESENT
    assert repeated.version == first.version
    assert len(history) == 1


def test_in_memory_repository_preserves_owner_and_project_mode_boundaries() -> None:
    """Keep missing and foreign projects indistinguishable and reject greenfield intake."""
    repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={
            PROJECT_ID: _project(
                PROJECT_ID,
                mode=ProjectMode.BROWNFIELD_ASSESSMENT,
            ),
            GREENFIELD_ID: _project(
                GREENFIELD_ID,
                mode=ProjectMode.GREENFIELD_GENERATION,
            ),
        },
    )

    foreign = asyncio.run(repository.append(_version(creator_id=FOREIGN_OWNER_ID)))
    greenfield_snapshot = replace(_snapshot(), project_id=GREENFIELD_ID)
    greenfield = BrownfieldIntakeVersion(
        id=UUID(int=1001),
        project_id=GREENFIELD_ID,
        version_number=1,
        based_on_version_number=None,
        snapshot=greenfield_snapshot,
        content_hash=greenfield_snapshot.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    wrong_mode = asyncio.run(repository.append(greenfield))

    assert foreign.status is BrownfieldIntakeAppendStatus.PROJECT_NOT_FOUND
    assert wrong_mode.status is BrownfieldIntakeAppendStatus.PROJECT_MODE_UNSUPPORTED


def test_in_memory_repository_rejects_non_linear_versions() -> None:
    """Require one exact append-only sequence per project."""
    repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={
            PROJECT_ID: _project(
                PROJECT_ID,
                mode=ProjectMode.BROWNFIELD_ASSESSMENT,
            )
        },
    )
    invalid = _version(version_number=2, based_on_version_number=1)

    result = asyncio.run(repository.append(invalid))

    assert result.status is BrownfieldIntakeAppendStatus.VERSION_CONFLICT
    assert asyncio.run(repository.current(project_id=PROJECT_ID)) is None


def test_persisted_version_rejects_noncanonical_snapshot_json() -> None:
    """Keep persisted snapshot values immutable rather than sharing mutable mappings."""
    persisted = persisted_brownfield_intake_from_record(
        brownfield_intake_version_to_record(_version())
    )

    with pytest.raises(ValueError, match="canonical"):
        replace(persisted, snapshot_json='{"z":1, "a":2}')
    assert persisted.created_at == datetime(2026, 8, 25, 9, 0, tzinfo=UTC)
