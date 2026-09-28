from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID, uuid4

from orchestwin.knowledge.diagram_service import brief_system_name
from orchestwin.knowledge.twin_import import (
    ImportedTwin,
    PortableTwinDocument,
    TwinImportError,
    TwinImportIdentities,
    TwinImportTarget,
    import_issue,
    import_twin,
    parse_twin_document,
)
from orchestwin.knowledge.twin_import_sources import DEFAULT_CANDIDATE_LIMIT, TwinImportCandidate
from orchestwin.knowledge.twins import PortableTwin, portable_twin_documents
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    UserModelingApplicationIssueCode,
    UserModelingGovernancePort,
    UserModelingUnitOfWorkFactory,
    _governance_issue,
)
from orchestwin.twins.epistemics import ObservationValueKind
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfile,
    UserTwinProfileVersion,
)
from orchestwin.workflow.gates import HumanGate

_SOURCE_NAME_LOCALE: Final = "en"
_SUMMARY_GOAL_LIMIT: Final = 3


class TwinImportStatus(StrEnum):
    IMPORTED = "TWIN_IMPORTED"


@dataclass(frozen=True, slots=True)
class TwinImportResult:
    status: TwinImportStatus
    imported: ImportedTwin


@dataclass(frozen=True, slots=True)
class ImportableTwin:
    twin_id: UUID
    name: str
    version_number: int
    content_hash: str
    validation_status: str
    summary: str | None
    issue: str | None


@dataclass(frozen=True, slots=True)
class TwinImportSource:
    project_id: UUID
    project_name: str
    snapshot_version_number: int
    approved_at: datetime
    twins: tuple[ImportableTwin, ...]


class TwinImportProjectService(Protocol):
    async def current_brief(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> ProjectBriefVersion | None: ...


class TwinImportSnapshotQueries(Protocol):
    async def current_snapshot(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> UserModelingSnapshotVersion | None: ...


class TwinImportGateQueries(Protocol):
    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None: ...


class TwinImportCandidateQueries(Protocol):
    async def list(
        self,
        *,
        owner_user_id: UUID,
        exclude_project_id: UUID,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> tuple[TwinImportCandidate, ...]: ...


@dataclass(frozen=True, slots=True)
class _ApprovedSource:
    project_name: str
    snapshot: UserModelingSnapshotVersion
    gate: HumanGate
    documents: tuple[PortableTwin, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _governance_code(context: GovernedUserModelingContext | None) -> str | None:
    issue = _governance_issue(context)
    if issue is None:
        return None
    if issue is UserModelingApplicationIssueCode.TEAM_PROPOSAL_REQUIRED:
        return UserModelingApplicationIssueCode.TEAM_APPROVAL_REQUIRED.value
    return issue.value


def _target(context: GovernedUserModelingContext) -> TwinImportTarget:
    return TwinImportTarget(
        project_id=context.project_id,
        project_brief_reference=context.brief_reference,
        agent_team_reference=context.team_reference,
        catalog_version=context.catalog_version,
        catalog_content_hash=context.catalog_content_hash,
    )


def _parsed(document: object) -> PortableTwinDocument:
    return parse_twin_document(document)


def _issue(
    document: object,
    *,
    blocker: str | None,
    target: TwinImportTarget | None,
    current: UserModelingSnapshotVersion | None,
) -> str | None:
    try:
        parsed = _parsed(document)
    except TwinImportError as error:
        return error.code
    if target is None:
        return blocker
    return import_issue(parsed, target=target, current=current)


def _context_of_use(profile: UserTwinProfile) -> str | None:
    observation = profile.observation_for(UserTwinField.CONTEXT_OF_USE)
    if observation is None or observation.value.kind is not ObservationValueKind.TEXT:
        return None
    return observation.value.text


def _goals(profile: UserTwinProfile) -> str | None:
    observation = profile.observation_for(UserTwinField.GOALS)
    if observation is None or observation.value.kind is not ObservationValueKind.ITEMS:
        return None
    return "; ".join(observation.value.items[:_SUMMARY_GOAL_LIMIT])


def _summary(version: UserTwinProfileVersion) -> str | None:
    profile = version.profile
    name = profile.name.strip().casefold()
    return next(
        (
            text
            for text in (_context_of_use(profile), _goals(profile))
            if text is not None and text.strip() and text.strip().casefold() != name
        ),
        None,
    )


def _importable(version: UserTwinProfileVersion, issue: str | None) -> ImportableTwin:
    return ImportableTwin(
        twin_id=version.twin_id,
        name=version.profile.name,
        version_number=version.version_number,
        content_hash=version.content_hash,
        validation_status=version.profile.validation_status.value,
        summary=_summary(version),
        issue=issue,
    )


def _appended(status: VersionAppendStatus) -> None:
    if status is not VersionAppendStatus.APPENDED:
        raise TwinImportError("PERSISTENCE_REJECTED")


class TwinImportService:
    def __init__(
        self,
        *,
        governance: UserModelingGovernancePort,
        uow_factory: UserModelingUnitOfWorkFactory,
        project_service: TwinImportProjectService,
        user_modeling_queries: TwinImportSnapshotQueries,
        user_modeling_gates: TwinImportGateQueries,
        candidates: TwinImportCandidateQueries | None = None,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._governance = governance
        self._uow_factory = uow_factory
        self._project_service = project_service
        self._user_modeling_queries = user_modeling_queries
        self._user_modeling_gates = user_modeling_gates
        self._candidate_query = candidates
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def sources(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[TwinImportCandidate, ...]:
        if self._candidate_query is None:
            raise TwinImportError("TWIN_IMPORT_SOURCES_UNAVAILABLE")
        await self._owned_context(owner_user_id=owner_user_id, project_id=project_id)
        return await self._candidate_query.list(
            owner_user_id=owner_user_id, exclude_project_id=project_id
        )

    async def source(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        source_project_id: UUID,
    ) -> TwinImportSource:
        context = await self._owned_context(owner_user_id=owner_user_id, project_id=project_id)
        source = await self._approved_source(
            owner_user_id=owner_user_id, source_project_id=source_project_id
        )
        blocker = _governance_code(context)
        target = None if blocker is not None else _target(context)
        current = (
            None
            if target is None
            else await self._user_modeling_queries.current_snapshot(
                owner_user_id=owner_user_id, project_id=project_id
            )
        )
        return TwinImportSource(
            project_id=source_project_id,
            project_name=source.project_name,
            snapshot_version_number=source.snapshot.version_number,
            approved_at=source.gate.updated_at,
            twins=tuple(
                _importable(
                    version,
                    _issue(portable.document, blocker=blocker, target=target, current=current),
                )
                for version, portable in zip(
                    source.snapshot.snapshot.twin_versions, source.documents, strict=True
                )
            ),
        )

    async def import_from_project(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        source_project_id: UUID,
        twin_id: UUID,
    ) -> TwinImportResult:
        source = await self._approved_source(
            owner_user_id=owner_user_id, source_project_id=source_project_id
        )
        document = next(
            (
                portable.document
                for portable in source.documents
                if portable.twin["twin_id"] == str(twin_id)
            ),
            None,
        )
        if document is None:
            raise TwinImportError("SOURCE_TWIN_NOT_FOUND")
        return await self.import_document(
            owner_user_id=owner_user_id, project_id=project_id, document=document
        )

    async def import_document(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        document: object,
    ) -> TwinImportResult:
        parsed = _parsed(document)
        context = await self._governance.load_current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        blocker = _governance_code(context)
        if blocker is not None:
            raise TwinImportError(blocker)
        target = _target(context)
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current = await uow.snapshots.current(project_id=project_id)
            imported = import_twin(
                parsed,
                target=target,
                current=current,
                identities=self._identities(),
                created_by_user_id=owner_user_id,
                created_at=self._clock(),
            )
            _appended(await uow.personas.append(imported.persona_version))
            _appended(await uow.twins.append(imported.twin_version))
            latest = await uow.snapshots.current(project_id=project_id)
            if latest is None or latest.id != current.id:
                raise TwinImportError("CONTEXT_CHANGED")
            _appended(await uow.snapshots.append(imported.snapshot_version))
            await uow.commit()
        return TwinImportResult(status=TwinImportStatus.IMPORTED, imported=imported)

    async def _owned_context(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> GovernedUserModelingContext:
        context = await self._governance.load_current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if context is None:
            raise TwinImportError("PROJECT_NOT_FOUND")
        return context

    def _identities(self) -> TwinImportIdentities:
        return TwinImportIdentities(
            persona_id=self._uuid_factory(),
            persona_version_id=self._uuid_factory(),
            twin_id=self._uuid_factory(),
            twin_version_id=self._uuid_factory(),
            snapshot_version_id=self._uuid_factory(),
        )

    async def _approved_source(
        self,
        *,
        owner_user_id: UUID,
        source_project_id: UUID,
    ) -> _ApprovedSource:
        brief = await self._project_service.current_brief(
            project_id=source_project_id, owner_user_id=owner_user_id
        )
        if brief is None:
            raise TwinImportError("SOURCE_PROJECT_NOT_FOUND")
        snapshot = await self._user_modeling_queries.current_snapshot(
            owner_user_id=owner_user_id, project_id=source_project_id
        )
        gate = (
            None
            if snapshot is None
            else await self._user_modeling_gates.current_gate(
                project_id=source_project_id, owner_user_id=owner_user_id
            )
        )
        if (
            snapshot is None
            or gate is None
            or not user_modeling_gate_is_currently_approved(gate, snapshot)
        ):
            raise TwinImportError("SOURCE_TWINS_NOT_APPROVED")
        project_name = brief_system_name(brief, _SOURCE_NAME_LOCALE)
        return _ApprovedSource(
            project_name=project_name,
            snapshot=snapshot,
            gate=gate,
            documents=portable_twin_documents(
                project_id=source_project_id,
                project_name=project_name,
                modeling=snapshot,
                modeling_gate=gate,
            ),
        )


__all__ = [
    "ImportableTwin",
    "TwinImportCandidateQueries",
    "TwinImportGateQueries",
    "TwinImportProjectService",
    "TwinImportResult",
    "TwinImportService",
    "TwinImportSnapshotQueries",
    "TwinImportSource",
    "TwinImportStatus",
]
