"""Tests for append-only owner-scoped final export metadata."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.artifacts.export_persistence import (
    InMemoryExportBundleRepository,
    StoredExportBundle,
    export_bundle_record_to_domain,
    export_bundle_to_record,
)

NOW = datetime(2026, 8, 31, 2, 0, tzinfo=UTC)
OWNER_ID = UUID("00000000-0000-4000-8000-000000026102")


def _bundle() -> StoredExportBundle:
    return StoredExportBundle(
        id=UUID("00000000-0000-4000-8000-000000026101"),
        project_id=UUID("00000000-0000-4000-8000-000000026103"),
        workflow_run_id=UUID("00000000-0000-4000-8000-000000026104"),
        owner_user_id=OWNER_ID,
        manifest_id=UUID("00000000-0000-4000-8000-000000026105"),
        manifest_hash="a" * 64,
        final_review_id=UUID("00000000-0000-4000-8000-000000026106"),
        final_review_hash="b" * 64,
        final_approval_gate_id=UUID("00000000-0000-4000-8000-000000026107"),
        final_approval_event_id=UUID("00000000-0000-4000-8000-000000026108"),
        archive_hash="c" * 64,
        archive_size_bytes=512,
        storage_ref="sha256/cc/archive.zip",
        created_at=NOW,
    )


def test_export_bundle_record_round_trip_preserves_projection() -> None:
    bundle = _bundle()

    assert export_bundle_record_to_domain(export_bundle_to_record(bundle)) == bundle


def test_export_bundle_repository_is_idempotent_and_owner_scoped() -> None:
    async def scenario() -> None:
        repository = InMemoryExportBundleRepository()
        bundle = _bundle()
        assert await repository.append(bundle) == bundle
        assert await repository.append(bundle) == bundle
        assert (
            await repository.get_owned(
                export_id=bundle.id,
                owner_user_id=OWNER_ID,
            )
            == bundle
        )
        assert (
            await repository.get_owned(
                export_id=bundle.id,
                owner_user_id=UUID("00000000-0000-4000-8000-000000026199"),
            )
            is None
        )

    asyncio.run(scenario())
