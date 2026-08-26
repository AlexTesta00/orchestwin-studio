"""Application service for governed brownfield source-archive intake."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from orchestwin.projects.brownfield_intake import (
    BrownfieldIntakeSnapshot,
    BrownfieldIntakeVersion,
    create_source_archive_validation_evidence,
)
from orchestwin.projects.brownfield_persistence import (
    BrownfieldIntakeAppendStatus,
    BrownfieldIntakeUnitOfWorkFactory,
    PersistedBrownfieldIntakeVersion,
)
from orchestwin.projects.domain import Project, ProjectMode
from orchestwin.projects.execution_capabilities import (
    CapabilityNegotiationRequest,
    negotiate_execution_capability,
)
from orchestwin.sandbox.archive_extraction import (
    SourceArchiveExtractionStatus,
    extract_validated_source_archive,
)
from orchestwin.sandbox.archive_policy import (
    DEFAULT_SOURCE_ARCHIVE_POLICY,
    SourceArchivePolicy,
)
from orchestwin.sandbox.archive_store import (
    SourceArchiveStore,
    SourceArchiveStoreStatus,
)
from orchestwin.sandbox.archive_validation import (
    SourceArchiveValidationReport,
    validate_source_archive,
)
from orchestwin.sandbox.execution_profile_registry import ExecutionProfileRegistry
from orchestwin.sandbox.source_inventory import (
    SourceTreeInventoryBuildStatus,
    build_source_tree_inventory,
)


class BrownfieldSourceIntakeStatus(StrEnum):
    """Stable outcomes of one owner-requested source intake."""

    CREATED = "CREATED"
    REUSED = "REUSED"
    REJECTED = "REJECTED"


class BrownfieldSourceIntakeIssueCode(StrEnum):
    """Expected reasons a brownfield source intake cannot be completed."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_MODE_UNSUPPORTED = "PROJECT_MODE_UNSUPPORTED"
    ARCHIVE_REJECTED = "ARCHIVE_REJECTED"
    ARCHIVE_STORAGE_FAILED = "ARCHIVE_STORAGE_FAILED"
    ARCHIVE_EXTRACTION_FAILED = "ARCHIVE_EXTRACTION_FAILED"
    SOURCE_INVENTORY_FAILED = "SOURCE_INVENTORY_FAILED"
    WORKSPACE_CLEANUP_FAILED = "WORKSPACE_CLEANUP_FAILED"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"


class BrownfieldProjectQueryPort(Protocol):
    """Narrow owner-scoped project lookup used before filesystem side effects."""

    async def get_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        """Return one active owned project or no observable result."""
        ...


@dataclass(frozen=True, slots=True)
class BrownfieldSourceIntakeResult:
    """Inspectable application result without source content or host paths."""

    status: BrownfieldSourceIntakeStatus
    version: PersistedBrownfieldIntakeVersion | None
    issue: BrownfieldSourceIntakeIssueCode | None
    validation_report: SourceArchiveValidationReport | None
    archive_store_status: SourceArchiveStoreStatus | None
    extraction_status: SourceArchiveExtractionStatus | None
    inventory_status: SourceTreeInventoryBuildStatus | None
    persistence_status: BrownfieldIntakeAppendStatus | None
    failure_message: str | None

    def __post_init__(self) -> None:
        """Keep success, reuse, and rejection shapes unambiguous."""
        successful = self.status in {
            BrownfieldSourceIntakeStatus.CREATED,
            BrownfieldSourceIntakeStatus.REUSED,
        }
        if successful:
            if self.version is None or self.issue is not None or self.failure_message is not None:
                raise ValueError("successful brownfield intake result shape is invalid")
            if self.persistence_status not in {
                BrownfieldIntakeAppendStatus.APPENDED,
                BrownfieldIntakeAppendStatus.ALREADY_PRESENT,
            }:
                raise ValueError("successful brownfield intake requires persistence evidence")
        elif self.version is not None or self.issue is None or self.failure_message is None:
            raise ValueError("rejected brownfield intake result shape is invalid")

        if self.failure_message is not None and (
            not self.failure_message
            or self.failure_message != " ".join(self.failure_message.split())
        ):
            raise ValueError("brownfield intake failure message must be normalized")


class LocalBrownfieldSourceIntakeService:
    """Validate, inventory, negotiate, and persist one exact source archive."""

    def __init__(
        self,
        *,
        projects: BrownfieldProjectQueryPort,
        archive_store: SourceArchiveStore,
        profile_registry: ExecutionProfileRegistry,
        uow_factory: BrownfieldIntakeUnitOfWorkFactory,
        workspace_root: Path,
        policy: SourceArchivePolicy = DEFAULT_SOURCE_ARCHIVE_POLICY,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
        workspace_cleaner: Callable[[Path], bool] | None = None,
    ) -> None:
        """Bind deterministic policy and explicit filesystem/persistence adapters."""
        self._projects = projects
        self._archive_store = archive_store
        self._profile_registry = profile_registry
        self._uow_factory = uow_factory
        self._workspace_root = Path(workspace_root)
        self._policy = policy
        self._uuid_factory = uuid_factory
        self._clock = clock or _utc_now
        self._workspace_cleaner = workspace_cleaner or _remove_workspace

    async def ingest(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        archive_path: Path,
        capability_request: CapabilityNegotiationRequest,
    ) -> BrownfieldSourceIntakeResult:
        """Create or idempotently reuse an immutable brownfield intake version."""
        project = await self._projects.get_owned(
            owner_user_id=owner_user_id,
            project_id=project_id,
        )
        if project is None:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.PROJECT_NOT_FOUND,
                "Brownfield project was not found.",
            )
        if project.mode is not ProjectMode.BROWNFIELD_ASSESSMENT:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.PROJECT_MODE_UNSUPPORTED,
                "Source archives can only be attached to brownfield projects.",
            )

        validation = validate_source_archive(Path(archive_path), policy=self._policy)
        if not validation.is_accepted:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.ARCHIVE_REJECTED,
                "Source archive failed complete preflight validation.",
                validation_report=validation,
            )

        stored = self._archive_store.store(
            Path(archive_path),
            validation_report=validation,
        )
        if not stored.is_available or stored.archive is None:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.ARCHIVE_STORAGE_FAILED,
                stored.failure_message or "Source archive could not be stored safely.",
                validation_report=validation,
                archive_store_status=stored.status,
            )

        extraction = extract_validated_source_archive(
            Path(archive_path),
            validation_report=validation,
            workspace_root=self._workspace_root,
            workspace_id=self._uuid_factory(),
            policy=self._policy,
        )
        if not extraction.is_extracted or extraction.workspace_path is None:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.ARCHIVE_EXTRACTION_FAILED,
                extraction.failure_message or "Source archive could not be extracted safely.",
                validation_report=validation,
                archive_store_status=stored.status,
                extraction_status=extraction.status,
            )

        workspace = extraction.workspace_path
        inventory_result = build_source_tree_inventory(
            workspace,
            validation_report=validation,
        )
        cleanup_completed = self._workspace_cleaner(workspace)
        if not cleanup_completed:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.WORKSPACE_CLEANUP_FAILED,
                "Brownfield intake workspace could not be removed completely.",
                validation_report=validation,
                archive_store_status=stored.status,
                extraction_status=extraction.status,
                inventory_status=inventory_result.status,
            )
        if not inventory_result.is_created or inventory_result.inventory is None:
            return _rejected(
                BrownfieldSourceIntakeIssueCode.SOURCE_INVENTORY_FAILED,
                inventory_result.failure_message
                or "Extracted source tree could not be inventoried safely.",
                validation_report=validation,
                archive_store_status=stored.status,
                extraction_status=extraction.status,
                inventory_status=inventory_result.status,
            )

        capability = negotiate_execution_capability(
            inventory_result.inventory,
            registry=self._profile_registry,
            request=capability_request,
        )
        snapshot = BrownfieldIntakeSnapshot(
            project_id=project_id,
            validation=create_source_archive_validation_evidence(
                validation,
                policy=self._policy,
            ),
            archive=stored.archive,
            inventory=inventory_result.inventory,
            capability=capability,
        )

        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.intakes.current(project_id=project_id)
            version_number = 1 if current is None else current.version_number + 1
            version = BrownfieldIntakeVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=version_number,
                based_on_version_number=(None if current is None else current.version_number),
                snapshot=snapshot,
                content_hash=snapshot.content_hash,
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            append_result = await unit.intakes.append(version)
            if append_result.status in {
                BrownfieldIntakeAppendStatus.APPENDED,
                BrownfieldIntakeAppendStatus.ALREADY_PRESENT,
            }:
                await unit.commit()
                return BrownfieldSourceIntakeResult(
                    status=(
                        BrownfieldSourceIntakeStatus.CREATED
                        if append_result.status is BrownfieldIntakeAppendStatus.APPENDED
                        else BrownfieldSourceIntakeStatus.REUSED
                    ),
                    version=append_result.version,
                    issue=None,
                    validation_report=validation,
                    archive_store_status=stored.status,
                    extraction_status=extraction.status,
                    inventory_status=inventory_result.status,
                    persistence_status=append_result.status,
                    failure_message=None,
                )

            await unit.rollback()
            return _rejected(
                _persistence_issue(append_result.status),
                "Brownfield intake could not be appended to the current project state.",
                validation_report=validation,
                archive_store_status=stored.status,
                extraction_status=extraction.status,
                inventory_status=inventory_result.status,
                persistence_status=append_result.status,
            )


def _persistence_issue(status: BrownfieldIntakeAppendStatus) -> BrownfieldSourceIntakeIssueCode:
    if status is BrownfieldIntakeAppendStatus.PROJECT_NOT_FOUND:
        return BrownfieldSourceIntakeIssueCode.PROJECT_NOT_FOUND
    if status is BrownfieldIntakeAppendStatus.PROJECT_MODE_UNSUPPORTED:
        return BrownfieldSourceIntakeIssueCode.PROJECT_MODE_UNSUPPORTED
    return BrownfieldSourceIntakeIssueCode.PERSISTENCE_CONFLICT


def _rejected(
    issue: BrownfieldSourceIntakeIssueCode,
    message: str,
    *,
    validation_report: SourceArchiveValidationReport | None = None,
    archive_store_status: SourceArchiveStoreStatus | None = None,
    extraction_status: SourceArchiveExtractionStatus | None = None,
    inventory_status: SourceTreeInventoryBuildStatus | None = None,
    persistence_status: BrownfieldIntakeAppendStatus | None = None,
) -> BrownfieldSourceIntakeResult:
    return BrownfieldSourceIntakeResult(
        status=BrownfieldSourceIntakeStatus.REJECTED,
        version=None,
        issue=issue,
        validation_report=validation_report,
        archive_store_status=archive_store_status,
        extraction_status=extraction_status,
        inventory_status=inventory_status,
        persistence_status=persistence_status,
        failure_message=" ".join(message.split()),
    )


def _remove_workspace(path: Path) -> bool:
    """Remove only the generated regular workspace and report completion."""
    try:
        if path.is_symlink():
            return False
        shutil.rmtree(path)
    except OSError:
        return False
    return not path.exists()


def _utc_now() -> datetime:
    return datetime.now(UTC)
