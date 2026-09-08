"""Persist initial Web source plans after an exact Architecture gate approval.

This service stores source bytes and metadata only. It does not run a model,
build, test, execute code, authorize Gate 7, or approve a formal case.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.web_execution import (
    WebApiCommandResult,
    WebApiCommandStatus,
    WebSourceRevisionCreateCommand,
)
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.web_source_persistence import (
    WEB_SOURCE_REVISIONS,
    SqlAlchemyWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
    web_source_revision_from_record,
)
from orchestwin.artifacts.web_source_plans import (
    FileSystemWebSourceContentStore,
    WebSourcePlanFile,
    create_web_source_plan,
    validate_web_source_plan,
)
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebTargetSelection,
    web_scope_for,
)
from orchestwin.web_execution.workspaces import (
    PreparedWebWorkspace,
    materialize_web_source_snapshot,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository

_ALLOWED_TARGETS = frozenset({"WEB_STATIC", "WEB_VUE", "WEB_NODE_EXPRESS", "WEB_VUE_NODE"})
_ALLOWED_LANGUAGES = frozenset(
    {None, WebImplementationLanguage.STATIC_ASSETS, WebImplementationLanguage.JAVASCRIPT}
)


def _rejected(status: WebApiCommandStatus, message: str) -> WebApiCommandResult:
    return WebApiCommandResult(status=status, snapshot=None, message=message)


def _owned_sources(*, owner_user_id: UUID, project_id: UUID):
    """Select immutable rows only through the active owner-scoped project."""
    return (
        select(WEB_SOURCE_REVISIONS)
        .join(ProjectRecord, ProjectRecord.id == WEB_SOURCE_REVISIONS.c.project_id)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
            WEB_SOURCE_REVISIONS.c.created_by_user_id == owner_user_id,
        )
    )


def _safe_storage_root(root: Path) -> None:
    """Reject redirected parents before using the existing content store."""
    for candidate in (root, *root.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise OSError("WEB_SOURCE_STORAGE_ROOT_UNSAFE")


def _snapshot(revision: WebSourceRevision) -> dict[str, JsonValue]:
    # The domain snapshot contains hashes and storage keys, not plaintext files.
    return cast(dict[str, JsonValue], revision.to_snapshot())


class SqlAlchemyWebSourceApiService:
    """Wire the three source endpoints without claiming execution capabilities."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        content_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._content_root = Path(content_root).absolute()
        self._content_store = FileSystemWebSourceContentStore(self._content_root)

    async def create_source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebSourceRevisionCreateCommand,
    ) -> WebApiCommandResult:
        """Create revision 1; later revisions must use the governed repair path."""
        if command.target.value not in _ALLOWED_TARGETS or any(
            language not in _ALLOWED_LANGUAGES
            for language in (command.frontend_language, command.backend_language)
        ):
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_STACK_OUTSIDE_SCOPE")
        try:
            selection = WebTargetSelection(
                target=command.target,
                language_configuration=WebLanguageConfiguration(
                    frontend=command.frontend_language,
                    backend=command.backend_language,
                ),
                layout=command.layout,
            )
            selection.validate_against(web_scope_for(selection.target))
            # Disallow Windows drives and alternate data stream syntax as well.
            if any(
                PureWindowsPath(item.normalized_path).drive or ":" in item.normalized_path
                for item in command.files
            ):
                raise ValueError("WINDOWS_PATH_NOT_PORTABLE")
            if len(command.provenance_references) != 1:
                raise ValueError("ONE_VERIFIABLE_ARCHITECTURE_REFERENCE_REQUIRED")
            references = tuple(
                WebSourceProvenanceReference(
                    kind=item.kind,
                    reference_id=item.reference_id,
                    version_number=item.version_number,
                    content_hash=item.content_hash,
                )
                for item in command.provenance_references
            )
            timestamp = datetime.now(UTC)
            plan = create_web_source_plan(
                plan_id=uuid4(),
                project_id=project_id,
                created_by_user_id=owner_user_id,
                target_selection=selection,
                files=tuple(
                    WebSourcePlanFile(
                        normalized_path=item.normalized_path,
                        content=item.content,
                        media_type=item.media_type,
                    )
                    for item in command.files
                ),
                rationale=command.rationale,
                provenance_references=references,
                created_at=timestamp,
            )
            validation = validate_web_source_plan(plan)
        except (TypeError, ValueError):
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_PLAN_INVALID")
        if not validation.is_accepted:
            return _rejected(WebApiCommandStatus.INVALID, "WEB_SOURCE_PLAN_REJECTED")

        async with self._session_factory() as session, session.begin():
            project = await session.scalar(
                select(ProjectRecord)
                .where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
                .with_for_update()
            )
            if project is None:
                return _rejected(WebApiCommandStatus.NOT_FOUND, "WEB_SOURCE_PROJECT_NOT_FOUND")
            if project.mode != ProjectMode.GREENFIELD_GENERATION.value:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_REQUIRES_GREENFIELD")
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).get_current_owned_for_update(project_id=project_id, owner_user_id=owner_user_id)
            gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )
            if architecture is None or gate is None:
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED,
                    "WEB_SOURCE_ARCHITECTURE_APPROVAL_REQUIRED",
                )
            exact = GateArtifactReference(
                project_id=project_id,
                gate_type=HumanGateType.ARCHITECTURE,
                artifact_id=architecture.id,
                version=architecture.version_number,
                content_hash=architecture.content_hash,
            )
            if (
                architecture.project_id != project_id
                or gate.project_id != project_id
                or gate.owner_user_id != owner_user_id
                or gate.gate_type is not HumanGateType.ARCHITECTURE
                or gate.status is not HumanGateStatus.APPROVED
                or gate.artifact != exact
            ):
                return _rejected(
                    WebApiCommandStatus.APPROVAL_REQUIRED, "WEB_SOURCE_ARCHITECTURE_NOT_APPROVED"
                )
            # The domain requires provenance IDs to begin with a letter. A prefixed
            # UUID is unambiguous and can be resolved to an exact persisted version.
            expected_reference = WebSourceProvenanceReference(
                kind=WebSourceProvenanceKind.ARCHITECTURE,
                reference_id=f"architecture:{architecture.id}",
                version_number=architecture.version_number,
                content_hash=architecture.content_hash,
            )
            if references != (expected_reference,):
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_PROVENANCE_MISMATCH")
            revisions = SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner_user_id)
            if await revisions.current(project_id=project_id) is not None:
                return _rejected(WebApiCommandStatus.CONFLICT, "WEB_SOURCE_INITIAL_REVISION_EXISTS")

            try:
                _safe_storage_root(self._content_root)
                entries = tuple(
                    self._content_store.store(
                        normalized_path=item.normalized_path,
                        content=item.content_bytes,
                        media_type=item.media_type,
                    )
                    for item in plan.files
                )
                revision = create_web_source_revision(
                    revision_id=uuid4(),
                    project_id=project_id,
                    created_by_user_id=owner_user_id,
                    version_number=1,
                    based_on=None,
                    target=selection.target,
                    language_configuration=selection.language_configuration,
                    layout=selection.layout,
                    origin=WebSourceOrigin.GENERATED_PLAN,
                    files=entries,
                    provenance_references=references,
                    created_at=datetime.now(UTC),
                )
            except (OSError, TypeError, ValueError):
                raise HTTPException(
                    503, detail={"code": "WEB_SOURCE_STORAGE_UNAVAILABLE"}
                ) from None
            stored = await revisions.append(revision)
            if (
                stored.status
                not in {
                    WebSourceRevisionAppendStatus.APPENDED,
                    WebSourceRevisionAppendStatus.ALREADY_PRESENT,
                }
                or stored.revision is None
            ):
                # Raising is necessary: the repository may have a failed INSERT.
                # The enclosing transaction rolls back; no failed result commits.
                raise HTTPException(409, detail={"code": "WEB_SOURCE_APPEND_CONFLICT"})
            return WebApiCommandResult(
                status=WebApiCommandStatus.SOURCE_REVISION_CREATED,
                snapshot=_snapshot(stored.revision),
                message="Web source revision stored; execution has not been performed.",
            )

    async def prepare_workspace(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> PreparedWebWorkspace | None:
        """Restore an owner-visible revision; preparation grants no execution authority."""
        snapshot = await self.source_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            revision_id=revision_id,
        )
        if snapshot is None:
            return None
        return materialize_web_source_snapshot(
            snapshot,
            content_root=self._content_root,
            workspaces_root=self._content_root.parent / "web-execution-workspaces",
        )

    async def source_revision_history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[dict[str, JsonValue], ...]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        _owned_sources(owner_user_id=owner_user_id, project_id=project_id).order_by(
                            WEB_SOURCE_REVISIONS.c.version_number
                        )
                    )
                )
                .mappings()
                .all()
            )
            return tuple(_snapshot(web_source_revision_from_record(row)) for row in rows)

    async def source_revision(
        self, *, owner_user_id: UUID, project_id: UUID, revision_id: UUID
    ) -> dict[str, JsonValue] | None:
        async with self._session_factory() as session:
            row = (
                (
                    await session.execute(
                        _owned_sources(owner_user_id=owner_user_id, project_id=project_id).where(
                            WEB_SOURCE_REVISIONS.c.id == revision_id
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else _snapshot(web_source_revision_from_record(row))
