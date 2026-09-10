"""Tests for owner-scoped authorization before verified artifact content reads."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.artifact_content import MAX_SOURCE_BYTES
from orchestwin.evaluation.artifact_content_resolution import (
    ArtifactContentAuthorizationError,
    ArtifactContentAuthorizationIssueCode,
    OwnerScopedArtifactContentResolver,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    UserTwinEvaluationRequest,
    canonical_profile_snapshot,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

OWNER_ID = UUID("00000000-0000-4000-8000-000000083001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000083002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000083003")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000083004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000083005")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000083006")
TWIN_ID = UUID("00000000-0000-4000-8000-000000083007")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000083008")
NOW = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)


def _reference(
    content: bytes,
    *,
    artifact_id: UUID = ARTIFACT_ID,
    version_number: int = 1,
) -> EvaluationArtifactReference:
    digest = hashlib.sha256(content).hexdigest()
    return EvaluationArtifactReference(
        artifact_id=artifact_id,
        version_number=version_number,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(content),
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location="browser:final-dom",
    )


def _request(reference: EvaluationArtifactReference) -> UserTwinEvaluationRequest:
    profile_snapshot, profile_hash = canonical_profile_snapshot(
        {
            "name": "Approved reservation operator",
            "role": "Completes a web workflow using labelled controls",
            "basis": "Synthetic test profile",
        }
    )
    bundle = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=SCENARIO_ID,
            name="Owner-scoped artifact evaluation",
            task="Review the supplied interface artifact.",
            locale="en",
            expected_outcomes=("Only authorized artifact content is inspected.",),
        ),
        artifacts=(reference,),
        created_at=NOW,
    )
    return UserTwinEvaluationRequest(
        evaluation_run_id=EVALUATION_RUN_ID,
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        artifact_bundle=bundle,
        twin=EvaluationUserTwinProfile(
            twin_id=TWIN_ID,
            version_number=1,
            name="Approved reservation operator",
            lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
            content_hash=profile_hash,
            snapshot_json=profile_snapshot,
        ),
        evidence=(),
        requested_at=NOW,
    )


class RecordingOwnedArtifactSource:
    """Deterministic fake with separate authorization and byte-read phases."""

    def __init__(
        self,
        *,
        authorized_owner_id: UUID,
        authoritative_reference: EvaluationArtifactReference | None,
        content: bytes,
    ) -> None:
        self.authorized_owner_id = authorized_owner_id
        self.authoritative_reference = authoritative_reference
        self.content = content
        self.resolve_calls: list[tuple[UUID, UUID, UUID, UUID, int]] = []
        self.read_calls: list[tuple[str, int]] = []

    async def resolve_owned_artifact(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        self.resolve_calls.append(
            (
                owner_user_id,
                project_id,
                workflow_run_id,
                artifact_id,
                version_number,
            )
        )
        if owner_user_id != self.authorized_owner_id:
            return None
        return self.authoritative_reference

    def read_content(self, storage_key: str, maximum_bytes: int) -> bytes:
        self.read_calls.append((storage_key, maximum_bytes))
        return self.content


def test_resolver_authorizes_exact_scope_before_reading_content() -> None:
    async def scenario() -> None:
        content = b"<!doctype html><button>Confirm</button>"
        reference = _reference(content)
        request = _request(reference)
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
            authoritative_reference=reference,
            content=content,
        )
        resolver = OwnerScopedArtifactContentResolver(source)

        prepared = await resolver.prepare(
            owner_user_id=OWNER_ID,
            request=request,
            selected=((ARTIFACT_ID, 1),),
        )

        assert source.resolve_calls == [
            (
                OWNER_ID,
                PROJECT_ID,
                WORKFLOW_RUN_ID,
                ARTIFACT_ID,
                1,
            )
        ]
        assert source.read_calls == [(reference.storage_key, MAX_SOURCE_BYTES)]
        assert prepared.request.evidence[0].reference_id == (f"artifact:{ARTIFACT_ID}:v1")
        assert (
            prepared.content.to_snapshot()["items"][0]["artifact"]["sha256_digest"]
            == reference.sha256_digest
        )

    asyncio.run(scenario())


def test_resolver_rejects_another_owner_before_any_content_read() -> None:
    async def scenario() -> None:
        content = b"<!doctype html><button>Confirm</button>"
        reference = _reference(content)
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
            authoritative_reference=reference,
            content=content,
        )
        resolver = OwnerScopedArtifactContentResolver(source)

        with pytest.raises(ArtifactContentAuthorizationError) as captured:
            await resolver.prepare(
                owner_user_id=OTHER_OWNER_ID,
                request=_request(reference),
                selected=((ARTIFACT_ID, 1),),
            )

        assert captured.value.code is ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED
        assert source.read_calls == []

    asyncio.run(scenario())


def test_resolver_rejects_forged_bundle_metadata_before_content_read() -> None:
    async def scenario() -> None:
        caller_content = b"<!doctype html><button>Caller version</button>"
        authoritative_content = b"<!doctype html><button>Authoritative version</button>"
        caller_reference = _reference(caller_content)
        authoritative_reference = _reference(authoritative_content)

        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
            authoritative_reference=authoritative_reference,
            content=authoritative_content,
        )
        resolver = OwnerScopedArtifactContentResolver(source)

        with pytest.raises(ArtifactContentAuthorizationError) as captured:
            await resolver.prepare(
                owner_user_id=OWNER_ID,
                request=_request(caller_reference),
                selected=((ARTIFACT_ID, 1),),
            )

        assert (
            captured.value.code is ArtifactContentAuthorizationIssueCode.ARTIFACT_REFERENCE_MISMATCH
        )
        assert source.read_calls == []

    asyncio.run(scenario())
