"""Owner/project/workflow-scoped registry for evaluator artifact metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.evaluation.artifacts import EvaluationArtifactReference


class ArtifactContentRegistryStoreStatus(StrEnum):
    """Stable outcomes when registering authoritative artifact metadata."""

    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class AuthorizedEvaluationArtifactRecord:
    """One exact evaluator artifact identity inside an ownership scope."""

    owner_user_id: UUID
    project_id: UUID
    workflow_run_id: UUID
    reference: EvaluationArtifactReference

    @property
    def identity_key(
        self,
    ) -> tuple[UUID, UUID, UUID, UUID, int]:
        """Return the complete authorization identity."""
        return (
            self.owner_user_id,
            self.project_id,
            self.workflow_run_id,
            self.reference.artifact_id,
            self.reference.version_number,
        )


class AuthorizedEvaluationArtifactRegistry(Protocol):
    """Owner-scoped authoritative artifact-metadata boundary."""

    async def append(
        self,
        record: AuthorizedEvaluationArtifactRecord,
    ) -> ArtifactContentRegistryStoreStatus:
        """Register one immutable scoped artifact identity."""

    async def resolve_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        """Resolve exactly one artifact identity inside its owner scope."""


class InMemoryAuthorizedEvaluationArtifactRegistry:
    """Deterministic immutable registry used by ordinary tests."""

    def __init__(self) -> None:
        self._records: dict[
            tuple[UUID, UUID, UUID, UUID, int],
            AuthorizedEvaluationArtifactRecord,
        ] = {}

    async def append(
        self,
        record: AuthorizedEvaluationArtifactRecord,
    ) -> ArtifactContentRegistryStoreStatus:
        """Create once; exact repetition is idempotent, conflicts fail closed."""
        key = record.identity_key
        existing = self._records.get(key)

        if existing is None:
            self._records[key] = record
            return ArtifactContentRegistryStoreStatus.CREATED

        if existing == record:
            return ArtifactContentRegistryStoreStatus.ALREADY_PRESENT

        return ArtifactContentRegistryStoreStatus.CONTENT_CONFLICT

    async def resolve_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        """Return metadata only for the exact supplied authorization scope."""
        record = self._records.get(
            (
                owner_user_id,
                project_id,
                workflow_run_id,
                artifact_id,
                version_number,
            )
        )

        return None if record is None else record.reference


@dataclass(frozen=True, slots=True)
class RegistryBackedArtifactContentSource:
    """Bridge registry authorization to a separate content-addressed reader."""

    registry: AuthorizedEvaluationArtifactRegistry
    read_content_port: Callable[[str, int], bytes]

    def __init__(
        self,
        *,
        registry: AuthorizedEvaluationArtifactRegistry,
        read_content: Callable[[str, int], bytes],
    ) -> None:
        object.__setattr__(self, "registry", registry)
        object.__setattr__(self, "read_content_port", read_content)

    async def resolve_owned_artifact(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        """Resolve metadata through the complete ownership boundary."""
        return await self.registry.resolve_owned(
            owner_user_id=owner_user_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            artifact_id=artifact_id,
            version_number=version_number,
        )

    def read_content(
        self,
        storage_key: str,
        maximum_bytes: int,
    ) -> bytes:
        """Delegate the post-authorization immutable byte read."""
        return self.read_content_port(
            storage_key,
            maximum_bytes,
        )


__all__ = [
    "ArtifactContentRegistryStoreStatus",
    "AuthorizedEvaluationArtifactRecord",
    "AuthorizedEvaluationArtifactRegistry",
    "InMemoryAuthorizedEvaluationArtifactRegistry",
    "RegistryBackedArtifactContentSource",
]
