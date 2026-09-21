"""Database-backed fixture journeys through the existing governed Web services.

Seeding creates only initial repository-owned fixtures. Repairs and executions
always use Unit7 services; approvals require explicit operator inputs. Harvesting
reads immutable database records and historical approval events, never inferring
successful execution from a command response or a campaign-state file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.web_execution import (
    WebApiCommandResult,
    WebExecutionStartCommand,
    WebRepairProposalApplyCommand,
    WebRepairProposalCreateCommand,
)
from orchestwin.artifacts.web_source_persistence import (
    SqlAlchemyWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_source_plans import FileSystemWebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    create_web_source_revision,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from orchestwin.web_execution.operation_governance import (
    WebGovernedOperation,
    WebOperationKind,
    WebOperationState,
)
from orchestwin.web_execution.validation_fixtures import RepositoryValidationFixture
from orchestwin.web_execution.validation_harvest import HarvestAttempt
from orchestwin.web_execution.workspaces import _read_object
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateEventKind,
    HumanGateStatus,
)
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from orchestwin.workflow.web_execution import WebExecutionPurpose

if TYPE_CHECKING:
    from orchestwin.api.web_execution import (
        WebBrowserEvidenceApiService,
        WebExecutionStartApiService,
        WebRepairApiService,
    )
    from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore


class WebValidationGovernanceError(ValueError):
    """Safe validation-journey rejection without database or filesystem details."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WebValidationGovernanceError("WEB_VALIDATION_" + code)


class ValidationGovernance:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        operation_store: SqlAlchemyWebOperationStore,
        execution_service: WebExecutionStartApiService,
        repair_service: WebRepairApiService,
        read_service: WebBrowserEvidenceApiService,
        content_root: Path,
    ):
        self.sessions = sessions
        self.operation_store = operation_store
        self.execution_service = execution_service
        self.repair_service = repair_service
        self.read_service = read_service
        self.content_root = Path(content_root).absolute()
        self._content_store = FileSystemWebSourceContentStore(self.content_root)

    @staticmethod
    async def _active_owner(session, owner_user_id: UUID, *, lock=False) -> None:
        _require(isinstance(owner_user_id, UUID), "OWNER_UNAVAILABLE")
        statement = sa.select(UserRecord.id).where(
            UserRecord.id == owner_user_id, UserRecord.is_active.is_(True)
        )
        if lock:
            # Serialize concurrent seed requests by the existing owner before a
            # not-yet-created project can be locked. No owner is ever inserted.
            statement = statement.with_for_update()
        _require(await session.scalar(statement) is not None, "OWNER_UNAVAILABLE")

    async def _check_owner(self, owner_user_id: UUID) -> None:
        async with self.sessions() as session:
            await self._active_owner(session, owner_user_id)

    async def seed_fixture(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        source_id: UUID,
        created_at: datetime,
        fixture: RepositoryValidationFixture,
        defective: bool = False,
    ) -> WebSourceRevision:
        _require(
            isinstance(project_id, UUID)
            and isinstance(source_id, UUID)
            and isinstance(created_at, datetime)
            and created_at.utcoffset() is not None
            and isinstance(fixture, RepositoryValidationFixture)
            and isinstance(defective, bool),
            "FIXTURE_INPUT_INVALID",
        )
        created_at = created_at.astimezone(UTC)
        files = fixture.source_files(defective=defective)
        _require(
            0 < len(files) <= 1000
            and all(
                isinstance(item.content, bytes) and len(item.content) <= 1024 * 1024
                for item in files
            )
            and sum(len(item.content) for item in files) <= 20 * 1024 * 1024,
            "FIXTURE_CONTENT_LIMIT",
        )
        display_name = f"Web validation {fixture.fixture_id} {source_id}"
        _require(len(display_name) <= 120, "FIXTURE_ID_INVALID")
        try:
            provenance = WebSourceProvenanceReference(
                WebSourceProvenanceKind.SOURCE_PLAN,
                "web.leveld." + fixture.fixture_id.replace("-", "."),
                1,
                fixture.fixture_bundle_hash,
            )
            async with self.sessions() as session, session.begin():
                await self._active_owner(session, owner_user_id, lock=True)
                project = await session.scalar(
                    sa.select(ProjectRecord).where(ProjectRecord.id == project_id).with_for_update()
                )
                if project is None:
                    project = ProjectRecord(
                        id=project_id,
                        owner_user_id=owner_user_id,
                        display_name=display_name,
                        mode=ProjectMode.GREENFIELD_GENERATION.value,
                        current_brief_version=0,
                        archived_at=None,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                    session.add(project)
                    await session.flush()
                else:
                    _require(
                        project.owner_user_id == owner_user_id
                        and project.archived_at is None
                        and project.display_name == display_name
                        and project.mode == ProjectMode.GREENFIELD_GENERATION.value
                        and project.current_brief_version == 0
                        and project.created_at == created_at,
                        "FIXTURE_PROJECT_CONFLICT",
                    )
                revision = create_web_source_revision(
                    revision_id=source_id,
                    project_id=project_id,
                    created_by_user_id=owner_user_id,
                    version_number=1,
                    based_on=None,
                    target=fixture.selection.target,
                    language_configuration=fixture.selection.language_configuration,
                    layout=fixture.selection.layout,
                    origin=WebSourceOrigin.DETERMINISTIC_FIXTURE,
                    files=tuple(
                        self._content_store.store(
                            normalized_path=item.path,
                            content=item.content,
                            media_type=item.media_type,
                        )
                        for item in sorted(files, key=lambda item: item.path)
                    ),
                    provenance_references=(provenance,),
                    created_at=created_at,
                )
                _require(
                    revision.source_tree_hash == fixture.source_tree_hash(defective=defective),
                    "FIXTURE_SOURCE_MISMATCH",
                )
                repository = SqlAlchemyWebSourceRevisionRepository(
                    session, owner_user_id=owner_user_id
                )
                history = await repository.history(project_id=project_id)
                if history:
                    # Later revisions may be genuine governed repairs. Re-seeding
                    # may return only the identical immutable initial revision.
                    _require(history[0] == revision, "FIXTURE_SOURCE_CONFLICT")
                    return history[0]
                result = await repository.append(revision)
                _require(
                    result.status
                    in {
                        WebSourceRevisionAppendStatus.APPENDED,
                        WebSourceRevisionAppendStatus.ALREADY_PRESENT,
                    }
                    and result.revision == revision,
                    "FIXTURE_SOURCE_CONFLICT",
                )
                return result.revision
        except WebValidationGovernanceError:
            raise
        except (IntegrityError, OSError, TypeError, ValueError):
            raise WebValidationGovernanceError(
                "WEB_VALIDATION_FIXTURE_PERSISTENCE_FAILED"
            ) from None

    async def source_history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[WebSourceRevision, ...]:
        async with self.sessions() as session:
            await self._active_owner(session, owner_user_id)
            return await SqlAlchemyWebSourceRevisionRepository(
                session, owner_user_id=owner_user_id
            ).history(project_id=project_id)

    async def operation_history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[WebGovernedOperation, ...]:
        async with self.operation_store.scope(
            owner_user_id=owner_user_id, project_id=project_id
        ) as scope:
            await self._active_owner(scope.session, owner_user_id)
            return await scope.history()

    async def prepare_execution(
        self, *, owner_user_id: UUID, project_id: UUID, command: WebExecutionStartCommand
    ) -> WebApiCommandResult:
        _require(command.purpose is WebExecutionPurpose.PROFILE_VALIDATION, "PURPOSE_INVALID")
        await self._check_owner(owner_user_id)
        return await self.execution_service.prepare_execution(
            owner_user_id=owner_user_id, project_id=project_id, command=command
        )

    async def start_execution(
        self, *, owner_user_id: UUID, project_id: UUID, command: WebExecutionStartCommand
    ) -> WebApiCommandResult:
        _require(command.purpose is WebExecutionPurpose.PROFILE_VALIDATION, "PURPOSE_INVALID")
        await self._check_owner(owner_user_id)
        return await self.execution_service.start_execution(
            owner_user_id=owner_user_id, project_id=project_id, command=command
        )

    async def approve(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        operation_id: UUID,
        expected_hash: str,
        expected_event_sequence: int,
    ) -> dict:
        async with self.operation_store.scope(
            owner_user_id=owner_user_id, project_id=project_id
        ) as scope:
            await self._active_owner(scope.session, owner_user_id)
            operation = await scope.get(operation_id)
            _require(operation is not None, "OPERATION_MISSING")
            decided = await scope.decide(
                operation,
                expected_hash=expected_hash,
                expected_event_sequence=expected_event_sequence,
                action=HumanGateAction.APPROVE,
            )
            return await scope.snapshot(decided)

    async def create_repair_proposal(
        self, *, owner_user_id: UUID, execution_id: UUID, command: WebRepairProposalCreateCommand
    ) -> WebApiCommandResult:
        await self._check_owner(owner_user_id)
        return await self.repair_service.create_repair_proposal(
            owner_user_id=owner_user_id, execution_id=execution_id, command=command
        )

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: WebRepairProposalApplyCommand,
    ) -> WebApiCommandResult:
        await self._check_owner(owner_user_id)
        return await self.repair_service.apply_repair_proposal(
            owner_user_id=owner_user_id,
            execution_id=execution_id,
            proposal_id=proposal_id,
            command=command,
        )

    @staticmethod
    async def _operation_proof(scope, operation_id, kind):
        operation = await scope.get(operation_id)
        _require(operation is not None and operation.kind is kind, "OPERATION_MISSING")
        _require(
            operation.state is WebOperationState.COMPLETED and operation.started_at is not None,
            "OPERATION_INCOMPLETE",
        )
        gate = await scope.gate(operation)
        events = await SqlAlchemyHumanGateRepository(scope.session).list_events_owned(
            owner_user_id=operation.owner_user_id, project_id=operation.project_id, gate_id=gate.id
        )
        _require(
            gate.artifact == operation.artifact
            and gate.id == operation.gate_id
            and gate.project_id == operation.project_id
            and gate.owner_user_id == operation.owner_user_id
            and len(events) == gate.event_sequence
            and bool(events),
            "APPROVAL_HISTORY_INVALID",
        )
        previous_status, previous_at = HumanGateStatus.DRAFT, gate.created_at
        effective = None
        for number, event in enumerate(events, 1):
            system_event = event.kind is HumanGateEventKind.ARTIFACT_SUPERSEDED
            artifact_valid = (
                event.artifact.project_id == gate.project_id
                and event.artifact.gate_type is gate.gate_type
                and event.artifact != gate.artifact
                and event.resulting_status is HumanGateStatus.STALE
                if system_event
                else event.artifact == gate.artifact
            )
            _require(
                event.sequence_number == number
                and event.gate_id == gate.id
                and artifact_valid
                and event.previous_status is previous_status
                and previous_at <= event.occurred_at <= gate.updated_at
                and (
                    (system_event and event.actor_user_id is None)
                    or (not system_event and event.actor_user_id == operation.owner_user_id)
                ),
                "APPROVAL_HISTORY_INVALID",
            )
            previous_status, previous_at = event.resulting_status, event.occurred_at
            if event.occurred_at <= operation.started_at:
                effective = event
        _require(
            previous_status is gate.status and previous_at == gate.updated_at,
            "APPROVAL_HISTORY_INVALID",
        )
        _require(
            effective is not None
            and effective.kind is HumanGateEventKind.APPROVE
            and effective.resulting_status is HumanGateStatus.APPROVED,
            "APPROVAL_NOT_EFFECTIVE_AT_CLAIM",
        )
        return operation, gate, effective

    async def harvest_repair(
        self, *, owner_user_id: UUID, project_id: UUID, operation_id: UUID
    ) -> tuple[WebGovernedOperation, HumanGate, HumanGateEvent]:
        async with self.operation_store.scope(
            owner_user_id=owner_user_id, project_id=project_id
        ) as scope:
            await self._active_owner(scope.session, owner_user_id)
            proof = await self._operation_proof(scope, operation_id, WebOperationKind.REPAIR)
            _require(
                proof[0].owner_user_id == owner_user_id and proof[0].project_id == project_id,
                "OPERATION_SCOPE_MISMATCH",
            )
            return proof

    async def harvest_attempt(
        self, *, owner_user_id: UUID, project_id: UUID, attempt_id: UUID
    ) -> HarvestAttempt:
        async with self.operation_store.scope(
            owner_user_id=owner_user_id, project_id=project_id
        ) as scope:
            await self._active_owner(scope.session, owner_user_id)
            operation, gate, approval = await self._operation_proof(
                scope, attempt_id, WebOperationKind.EXECUTION
            )
            attempts = await SqlAlchemyWebExecutionAttemptRepository(
                scope.session, owner_user_id=owner_user_id
            ).history(project_id=project_id)
            attempt = next((item for item in attempts if item.id == attempt_id), None)
            _require(attempt is not None, "ATTEMPT_MISSING")
            sources = await SqlAlchemyWebSourceRevisionRepository(
                scope.session, owner_user_id=owner_user_id
            ).history(project_id=project_id)
            source = next(
                (item for item in sources if item.id == operation.source_revision_id), None
            )
            _require(
                source is not None
                and source.reference == attempt.source_revision
                and operation.id == attempt.id
                and operation.project_id == attempt.project_id == project_id
                and operation.owner_user_id
                == attempt.created_by_user_id
                == source.created_by_user_id
                == owner_user_id
                and operation.started_at
                <= attempt.started_at
                <= attempt.completed_at
                <= operation.finished_at
                and operation.result
                == {
                    "execution_id": str(attempt.id),
                    "attempt_content_hash": attempt.content_hash,
                    "report_status": attempt.report.status.value,
                },
                "ATTEMPT_BINDING_MISMATCH",
            )
            try:
                for entry in source.files:
                    _read_object(self.content_root, entry.to_snapshot())
            except (OSError, ValueError):
                raise WebValidationGovernanceError("WEB_VALIDATION_SOURCE_OBJECT_INVALID") from None
        # The evidence reader opens its own session: release the operation lock
        # first, including for deployments using a connection pool of size one.
        browser = await self.read_service.browser_evidence(
            owner_user_id=owner_user_id, execution_id=attempt_id
        )
        return HarvestAttempt(source, attempt, operation, gate, approval, browser)
