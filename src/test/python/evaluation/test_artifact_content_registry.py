"""Tests for owner/project/workflow-scoped evaluator artifact metadata."""

from __future__ import annotations

import asyncio
import hashlib
from uuid import UUID

from orchestwin.evaluation.artifact_content import MAX_SOURCE_BYTES
from orchestwin.evaluation.artifact_content_registry import (
    ArtifactContentRegistryStoreStatus,
    AuthorizedEvaluationArtifactRecord,
    InMemoryAuthorizedEvaluationArtifactRegistry,
    RegistryBackedArtifactContentSource,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000086001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000086002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000086003")
OTHER_PROJECT_ID = UUID("00000000-0000-4000-8000-000000086004")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000086005")
OTHER_WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000086006")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000086007")


def _reference(
    content: bytes,
) -> EvaluationArtifactReference:
    digest = hashlib.sha256(content).hexdigest()

    return EvaluationArtifactReference(
        artifact_id=ARTIFACT_ID,
        version_number=1,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(content),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location="browser:formal-run/final-dom",
    )


def _record(
    reference: EvaluationArtifactReference,
) -> AuthorizedEvaluationArtifactRecord:
    return AuthorizedEvaluationArtifactRecord(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        reference=reference,
    )


def test_registry_requires_exact_owner_project_workflow_scope() -> None:
    async def scenario() -> None:
        reference = _reference(b"<!doctype html><button>Confirm</button>")

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        status = await registry.append(_record(reference))

        assert status is ArtifactContentRegistryStoreStatus.CREATED

        exact = await registry.resolve_owned(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        assert exact == reference

        wrong_owner = await registry.resolve_owned(
            owner_user_id=OTHER_OWNER_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        wrong_project = await registry.resolve_owned(
            owner_user_id=OWNER_ID,
            project_id=OTHER_PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        wrong_workflow = await registry.resolve_owned(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            workflow_run_id=OTHER_WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        assert wrong_owner is None
        assert wrong_project is None
        assert wrong_workflow is None

    asyncio.run(scenario())


def test_registry_is_idempotent_and_rejects_identity_conflicts() -> None:
    async def scenario() -> None:
        original = _reference(b"<!doctype html><button>Original</button>")

        conflicting = _reference(b"<!doctype html><button>Conflicting</button>")

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        created = await registry.append(_record(original))

        repeated = await registry.append(_record(original))

        conflict = await registry.append(_record(conflicting))

        assert created is ArtifactContentRegistryStoreStatus.CREATED
        assert repeated is ArtifactContentRegistryStoreStatus.ALREADY_PRESENT
        assert conflict is ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT

        resolved = await registry.resolve_owned(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        # A conflicting registration must never replace the first
        # authoritative identity.
        assert resolved == original

    asyncio.run(scenario())


def test_registry_backed_source_implements_resolver_content_port() -> None:
    async def scenario() -> None:
        content = b"<!doctype html><button>Confirm</button>"
        reference = _reference(content)

        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        assert (
            await registry.append(_record(reference)) is ArtifactContentRegistryStoreStatus.CREATED
        )

        read_calls: list[tuple[str, int]] = []

        def reader(
            storage_key: str,
            maximum_bytes: int,
        ) -> bytes:
            read_calls.append(
                (
                    storage_key,
                    maximum_bytes,
                )
            )
            return content

        source = RegistryBackedArtifactContentSource(
            registry=registry,
            read_content=reader,
        )

        resolved = await source.resolve_owned_artifact(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_id=ARTIFACT_ID,
            version_number=1,
        )

        assert resolved == reference
        assert read_calls == []

        observed = source.read_content(
            reference.storage_key,
            MAX_SOURCE_BYTES,
        )

        assert observed == content
        assert read_calls == [
            (
                reference.storage_key,
                MAX_SOURCE_BYTES,
            )
        ]

    asyncio.run(scenario())
