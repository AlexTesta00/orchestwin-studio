"""Owner-scoped authorization before verified evaluator artifact reads."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.artifact_content import (
    PreparedContentEvaluation,
    prepare_artifact_content,
)
from orchestwin.evaluation.artifacts import EvaluationArtifactReference
from orchestwin.evaluation.evaluator import UserTwinEvaluationRequest


class ArtifactContentAuthorizationIssueCode(StrEnum):
    """Stable failures emitted before evaluator artifact bytes are inspected."""

    ARTIFACT_NOT_AUTHORIZED = "ARTIFACT_NOT_AUTHORIZED"
    ARTIFACT_REFERENCE_MISMATCH = "ARTIFACT_REFERENCE_MISMATCH"


class ArtifactContentAuthorizationError(ValueError):
    """Typed fail-closed artifact authorization error."""

    def __init__(
        self,
        code: ArtifactContentAuthorizationIssueCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


class OwnerScopedArtifactContentSource(Protocol):
    """Authoritative owner-scoped artifact metadata and content source."""

    async def resolve_owned_artifact(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        """Resolve one exact artifact through its ownership boundary."""

    def read_content(
        self,
        storage_key: str,
        maximum_bytes: int,
    ) -> bytes:
        """Read immutable content after authorization has completed."""


class OwnerScopedArtifactContentResolver:
    """Authorize exact artifact references before any content byte is read."""

    def __init__(
        self,
        source: OwnerScopedArtifactContentSource,
    ) -> None:
        self._source = source

    async def prepare(
        self,
        *,
        owner_user_id: UUID,
        request: UserTwinEvaluationRequest,
        selected: tuple[tuple[UUID, int], ...],
    ) -> PreparedContentEvaluation:
        """Resolve ownership and exact metadata, then prepare verified content."""
        references_by_identity: dict[
            tuple[UUID, int],
            EvaluationArtifactReference,
        ] = {}

        for reference in request.artifact_bundle.artifacts:
            identity = (
                reference.artifact_id,
                reference.version_number,
            )
            if identity in references_by_identity:
                raise ArtifactContentAuthorizationError(
                    ArtifactContentAuthorizationIssueCode.ARTIFACT_REFERENCE_MISMATCH,
                    "evaluation artifact bundle contains an ambiguous identity",
                )
            references_by_identity[identity] = reference

        # Complete every authorization check before allowing the content
        # preparation layer to perform its first byte read.
        for artifact_id, version_number in selected:
            requested_reference = references_by_identity.get((artifact_id, version_number))

            if requested_reference is None:
                raise ArtifactContentAuthorizationError(
                    ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED,
                    "selected artifact is not available in the authorized bundle",
                )

            authoritative_reference = await self._source.resolve_owned_artifact(
                owner_user_id=owner_user_id,
                project_id=request.project_id,
                workflow_run_id=request.workflow_run_id,
                artifact_id=artifact_id,
                version_number=version_number,
            )

            if authoritative_reference is None:
                raise ArtifactContentAuthorizationError(
                    ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED,
                    "selected artifact is not authorized for this owner and scope",
                )

            if authoritative_reference != requested_reference:
                raise ArtifactContentAuthorizationError(
                    ArtifactContentAuthorizationIssueCode.ARTIFACT_REFERENCE_MISMATCH,
                    "bundle artifact metadata does not match the authoritative reference",
                )

        return prepare_artifact_content(
            request,
            selected=selected,
            read_content=self._source.read_content,
        )


__all__ = [
    "ArtifactContentAuthorizationError",
    "ArtifactContentAuthorizationIssueCode",
    "OwnerScopedArtifactContentResolver",
    "OwnerScopedArtifactContentSource",
]
