"""Project-scoped immutable sandbox run evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.projects.brownfield_intake import BrownfieldIntakeReference
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_sha256,
)
from orchestwin.sandbox.evidence import SandboxRunEvidence

PROJECT_SANDBOX_RUN_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class ProjectSandboxRunEvidence:
    """One terminal sandbox run bound to an owner, project, and optional intake."""

    project_id: UUID
    owner_user_id: UUID
    evidence: SandboxRunEvidence
    brownfield_intake_reference: BrownfieldIntakeReference | None
    recorded_at: datetime
    schema_version: int = PROJECT_SANDBOX_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Protect project context, exact brownfield binding, and chronology."""
        if self.schema_version != PROJECT_SANDBOX_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported project sandbox run schema version")
        if (
            self.brownfield_intake_reference is not None
            and self.brownfield_intake_reference.project_id != self.project_id
        ):
            raise ValueError("sandbox run intake reference belongs to another project")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("sandbox run recording timestamp must be timezone-aware")
        if self.recorded_at < self.evidence.finished_at:
            raise ValueError("sandbox run cannot be recorded before execution finished")

    @property
    def run_id(self) -> UUID:
        """Expose the immutable runtime-generated identifier."""
        return self.evidence.run_id

    def to_snapshot(self) -> dict[str, object]:
        """Return deterministic metadata while raw bytes remain content-addressed."""
        return {
            "schema_version": self.schema_version,
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "brownfield_intake_reference": (
                None
                if self.brownfield_intake_reference is None
                else self.brownfield_intake_reference.to_snapshot()
            ),
            "evidence": self.evidence.to_snapshot(),
            "recorded_at": self.recorded_at.isoformat(),
        }

    def canonical_json(self) -> str:
        """Serialize the complete evidence envelope deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the exact immutable identity of the persisted evidence envelope."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class ProjectSandboxRunReference:
    """Exact run identity used by API, workflow, and later approval artifacts."""

    run_id: UUID
    project_id: UUID
    content_hash: str

    def __post_init__(self) -> None:
        validate_sha256(
            self.content_hash,
            label="project sandbox run content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return stable reference metadata."""
        return {
            "run_id": str(self.run_id),
            "project_id": str(self.project_id),
            "content_hash": self.content_hash,
        }


def project_sandbox_run_reference(
    run: ProjectSandboxRunEvidence,
) -> ProjectSandboxRunReference:
    """Create the exact reference for one immutable project run envelope."""
    return ProjectSandboxRunReference(
        run_id=run.run_id,
        project_id=run.project_id,
        content_hash=run.content_hash,
    )
