"""Owner-scoped, Gate 7 approved Web repairs into immutable source revisions."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.api.web_execution import (
    WebApiCommandResult,
    WebApiCommandStatus,
    WebRepairProposalApplyCommand,
    WebRepairProposalCreateCommand,
)
from orchestwin.api.web_source_runtime import _safe_storage_root
from orchestwin.artifacts.web_change_sets import (
    WebSourceChange,
    WebSourceChangeOperation,
    WebSourceChangeValidationStatus,
    create_web_source_change_set,
    validate_web_source_change_set,
)
from orchestwin.artifacts.web_source_persistence import (
    SqlAlchemyWebSourceRevisionRepository,
    WebSourceRevisionAppendStatus,
)
from orchestwin.artifacts.web_source_plans import (
    DEFAULT_WEB_SOURCE_PLAN_POLICY,
    FileSystemWebSourceContentStore,
)
from orchestwin.artifacts.web_sources import (
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
)
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.web_execution.attempt_persistence import (
    WEB_EXECUTION_ATTEMPTS,
    SqlAlchemyWebExecutionAttemptRepository,
    web_execution_attempt_from_record,
)
from orchestwin.web_execution.attempts import WebExecutionAttempt
from orchestwin.web_execution.operation_governance import WebOperationError
from orchestwin.web_execution.repair_records import (
    web_repair_proposal_from_snapshot,
    web_repair_proposal_to_snapshot,
)
from orchestwin.web_execution.workspaces import _portable_path, _read_object
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.web_repair import (
    DEFAULT_WEB_REPAIR_POLICY,
    WebRepairApplicationStatus,
    WebRepairApprovalReference,
    WebRepairProposal,
    apply_web_repair_revision,
)

if TYPE_CHECKING:
    from orchestwin.web_execution.operation_persistence import SqlAlchemyWebOperationStore

_HASH = re.compile(r"^[0-9a-f]{64}$")


class _RepairRejected(Exception):
    def __init__(self, status: WebApiCommandStatus, code: str) -> None:
        self.status, self.code = status, code


def _reject(code: str, status: WebApiCommandStatus = WebApiCommandStatus.CONFLICT) -> None:
    raise _RepairRejected(status, code)


def _error_result(error: _RepairRejected | WebOperationError) -> WebApiCommandResult:
    if isinstance(error, _RepairRejected):
        status = error.status
    elif error.status_code == 404:
        status = WebApiCommandStatus.NOT_FOUND
    elif "APPROVAL" in error.code or "GATE" in error.code:
        status = WebApiCommandStatus.APPROVAL_REQUIRED
    else:
        status = WebApiCommandStatus.CONFLICT
    return WebApiCommandResult(status=status, snapshot=None, message=error.code)


class SqlAlchemyWebRepairApiService:
    """Propose, inspect and apply approved repairs without executing the new source."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        operation_store: SqlAlchemyWebOperationStore,
        content_root: Path,
    ) -> None:
        self._session_factory = session_factory
        self._operation_store = operation_store
        self._content_root = Path(content_root).absolute()
        self._content_store = FileSystemWebSourceContentStore(self._content_root)

    async def _attempt(self, *, owner_user_id: UUID, execution_id: UUID) -> WebExecutionAttempt:
        # Resolve the project only through an owner-scoped immutable attempt.
        # The current attempt and source are checked again under the project lock.
        statement = (
            select(WEB_EXECUTION_ATTEMPTS)
            .join(ProjectRecord, ProjectRecord.id == WEB_EXECUTION_ATTEMPTS.c.project_id)
            .where(
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
                WEB_EXECUTION_ATTEMPTS.c.created_by_user_id == owner_user_id,
                WEB_EXECUTION_ATTEMPTS.c.id == execution_id,
            )
        )
        async with self._session_factory() as session:
            row = (await session.execute(statement)).mappings().one_or_none()
            if row is None:
                _reject("WEB_REPAIR_EXECUTION_NOT_FOUND", WebApiCommandStatus.NOT_FOUND)
            try:
                return web_execution_attempt_from_record(row)
            except (KeyError, TypeError, ValueError):
                _reject("WEB_REPAIR_EXECUTION_INTEGRITY_FAILED")

    async def repair_proposals(
        self, *, owner_user_id: UUID, execution_id: UUID
    ) -> tuple[dict[str, JsonValue], ...]:
        try:
            attempt = await self._attempt(owner_user_id=owner_user_id, execution_id=execution_id)
            async with self._operation_store.scope(
                owner_user_id=owner_user_id, project_id=attempt.project_id
            ) as scope:
                snapshots = []
                for operation in await scope.history(kind="REPAIR"):
                    proposal = _proposal(operation, owner_user_id=owner_user_id)
                    if operation.payload["execution_id"] == str(execution_id):
                        _bind_attempt(operation, proposal, attempt)
                        snapshots.append(await _snapshot(scope, operation, proposal))
                return tuple(snapshots)
        except (_RepairRejected, WebOperationError) as error:
            result = _error_result(error)
            if result.status is WebApiCommandStatus.NOT_FOUND:
                return ()
            raise HTTPException(409, detail={"code": result.message}) from None

    async def create_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        command: WebRepairProposalCreateCommand,
    ) -> WebApiCommandResult:
        try:
            changes, contents = _changes(command)
            attempt = await self._attempt(owner_user_id=owner_user_id, execution_id=execution_id)
            async with self._operation_store.scope(
                owner_user_id=owner_user_id, project_id=attempt.project_id
            ) as scope:
                revisions, attempts, base = await _current(
                    scope.session, owner_user_id=owner_user_id, attempt=attempt
                )
                del revisions
                if base.content_hash != command.base_revision_content_hash:
                    _reject("WEB_REPAIR_STALE_BASE_REVISION")
                signature = next(
                    (
                        item
                        for item in attempt.report.failure_signatures()
                        if item.digest == command.failure_signature_digest
                    ),
                    None,
                )
                if signature is None:
                    _reject("WEB_REPAIR_FAILURE_SIGNATURE_MISMATCH")
                prior = tuple(
                    _proposal(operation, owner_user_id=owner_user_id)
                    for operation in await scope.history(kind="REPAIR")
                )
                attempt_number = 1 + sum(
                    item.failure_signature.digest == signature.digest for item in prior
                )
                occurrences = sum(
                    any(
                        item.digest == signature.digest
                        for item in entry.report.failure_signatures()
                    )
                    for entry in await attempts.history(project_id=attempt.project_id)
                )
                _check_limits(attempt_number, occurrences)
                provenance = (
                    WebSourceProvenanceReference(
                        kind=WebSourceProvenanceKind.FAILURE_SIGNATURE,
                        reference_id=f"failure-signature:{attempt.id}:{signature.digest}",
                        version_number=attempt.attempt_number,
                        content_hash=signature.digest,
                    ),
                )
                proposal = WebRepairProposal(
                    id=uuid4(),
                    project_id=base.project_id,
                    created_by_user_id=owner_user_id,
                    base_revision=base.reference,
                    failure_signature=signature,
                    change_set=create_web_source_change_set(
                        change_set_id=uuid4(),
                        project_id=base.project_id,
                        base_revision=base.reference,
                        changes=changes,
                        rationale=command.rationale,
                        provenance_references=(
                            f"web-execution:{attempt.id}:{attempt.content_hash}",
                        ),
                    ),
                    attempt_number=attempt_number,
                    identical_failure_occurrences=occurrences,
                    provenance_references=provenance,
                    created_at=datetime.now(UTC),
                )
                validation = validate_web_source_change_set(proposal.change_set, base_revision=base)
                if validation.status is WebSourceChangeValidationStatus.REJECTED:
                    _reject("WEB_REPAIR_CHANGE_SET_REJECTED", WebApiCommandStatus.INVALID)
                _projected_bounds(base, changes)
                # Persist verified content only after ownership, lineage, failure and limits pass.
                _safe_storage_root(self._content_root)
                for change in changes:
                    if change.operation is not WebSourceChangeOperation.DELETE:
                        _safe_storage_root(self._content_root / change.storage_key)
                        entry = self._content_store.store(
                            normalized_path=change.normalized_path,
                            content=contents[change.normalized_path],
                            media_type=change.media_type,
                        )
                        if entry != change.to_file_entry():
                            _reject("WEB_REPAIR_CONTENT_INTEGRITY_FAILED")
                payload = {
                    "schema_version": 1,
                    "execution_id": str(attempt.id),
                    "execution_content_hash": attempt.content_hash,
                    "proposal": web_repair_proposal_to_snapshot(proposal),
                }
                operation = await scope.propose(
                    source_revision_id=base.id, kind="REPAIR", payload=payload
                )
                verified = _proposal(operation, owner_user_id=owner_user_id)
                return WebApiCommandResult(
                    status=WebApiCommandStatus.REPAIR_PROPOSED,
                    snapshot=await _snapshot(scope, operation, verified),
                    message="Web repair proposed; exact Gate 7 approval is required before application.",
                )
        except (_RepairRejected, WebOperationError) as error:
            return _error_result(error)
        except (KeyError, TypeError, ValueError, UnicodeError):
            return WebApiCommandResult(
                status=WebApiCommandStatus.INVALID,
                snapshot=None,
                message="WEB_REPAIR_PROPOSAL_INVALID",
            )
        except OSError:
            raise HTTPException(503, detail={"code": "WEB_REPAIR_CONTENT_UNAVAILABLE"}) from None

    async def apply_repair_proposal(
        self,
        *,
        owner_user_id: UUID,
        execution_id: UUID,
        proposal_id: UUID,
        command: WebRepairProposalApplyCommand,
    ) -> WebApiCommandResult:
        try:
            attempt = await self._attempt(owner_user_id=owner_user_id, execution_id=execution_id)
            async with self._operation_store.scope(
                owner_user_id=owner_user_id, project_id=attempt.project_id
            ) as scope:
                operation = await scope.get(proposal_id)
                if operation is None or operation.kind != "REPAIR":
                    _reject("WEB_REPAIR_PROPOSAL_NOT_FOUND", WebApiCommandStatus.NOT_FOUND)
                proposal = _proposal(operation, owner_user_id=owner_user_id)
                _bind_attempt(operation, proposal, attempt)
                revisions, _, base = await _current(
                    scope.session, owner_user_id=owner_user_id, attempt=attempt
                )
                if (
                    base.reference != proposal.base_revision
                    or command.base_revision_content_hash != base.content_hash
                    or command.proposal_content_hash != operation.content_hash
                ):
                    _reject("WEB_REPAIR_PROPOSAL_OR_BASE_MISMATCH")
                _check_limits(proposal.attempt_number, proposal.identical_failure_occurrences)
                if command.approval_id is None:
                    _reject("WEB_REPAIR_GATE_7_REQUIRED", WebApiCommandStatus.APPROVAL_REQUIRED)
                gate = await scope.gate(operation)
                exact = GateArtifactReference(
                    project_id=attempt.project_id,
                    gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
                    artifact_id=operation.id,
                    version=1,
                    content_hash=operation.content_hash,
                )
                if (
                    gate is None
                    or gate.id != command.approval_id
                    or gate.project_id != attempt.project_id
                    or gate.owner_user_id != owner_user_id
                    or gate.gate_type is not HumanGateType.HIGH_IMPACT_OPERATION
                    or gate.status is not HumanGateStatus.APPROVED
                    or gate.artifact != exact
                ):
                    _reject("WEB_REPAIR_GATE_7_MISMATCH", WebApiCommandStatus.APPROVAL_REQUIRED)
                approval = WebRepairApprovalReference(
                    approval_id=gate.id,
                    project_id=proposal.project_id,
                    change_set_id=proposal.change_set.id,
                    change_set_content_hash=proposal.change_set.content_hash,
                    base_revision_content_hash=base.content_hash,
                    failure_signature_digest=proposal.failure_signature.digest,
                    approved_by_user_id=owner_user_id,
                )
                _safe_storage_root(self._content_root)
                for entry in _projected_bounds(base, proposal.change_set.changes):
                    _read_object(self._content_root, entry.to_snapshot())
                applied = apply_web_repair_revision(
                    proposal,
                    base_revision=base,
                    revision_id=uuid4(),
                    created_by_user_id=owner_user_id,
                    created_at=datetime.now(UTC),
                    content_store=self._content_store,
                    approval=approval,
                )
                if (
                    applied.status is not WebRepairApplicationStatus.APPLIED
                    or applied.revision is None
                ):
                    _reject(f"WEB_REPAIR_{applied.status.value}")
                # Claim and append share the locked transaction; append failure rolls the claim back.
                operation = await scope.claim(operation, expected_hash=operation.content_hash)
                stored = await revisions.append(applied.revision)
                if (
                    stored.status is not WebSourceRevisionAppendStatus.APPENDED
                    or stored.revision != applied.revision
                ):
                    _reject("WEB_REPAIR_SOURCE_APPEND_CONFLICT")
                result = {
                    "source_revision": applied.revision.to_snapshot(),
                    "required_rerun_phases": [
                        phase.value for phase in applied.required_rerun_phases
                    ],
                    "execution_performed": False,
                }
                operation = await scope.finish(operation, result=result, succeeded=True)
                snapshot = await _snapshot(scope, operation, proposal)
                snapshot.update(cast(dict[str, JsonValue], result))
                return WebApiCommandResult(
                    status=WebApiCommandStatus.REPAIR_APPLIED,
                    snapshot=snapshot,
                    message="Web repair stored as a new source revision; required execution remains pending.",
                )
        except (_RepairRejected, WebOperationError) as error:
            return _error_result(error)
        except (KeyError, TypeError, ValueError, OSError):
            return WebApiCommandResult(
                status=WebApiCommandStatus.CONFLICT,
                snapshot=None,
                message="WEB_REPAIR_EVIDENCE_OR_CONTENT_INVALID",
            )


async def _current(session, *, owner_user_id: UUID, attempt: WebExecutionAttempt):
    revisions = SqlAlchemyWebSourceRevisionRepository(session, owner_user_id=owner_user_id)
    attempts = SqlAlchemyWebExecutionAttemptRepository(session, owner_user_id=owner_user_id)
    base = await revisions.current(project_id=attempt.project_id)
    latest = await attempts.current(project_id=attempt.project_id)
    if base is None or latest is None:
        _reject("WEB_REPAIR_BASE_NOT_FOUND", WebApiCommandStatus.NOT_FOUND)
    if latest.id != attempt.id or latest.content_hash != attempt.content_hash:
        _reject("WEB_REPAIR_STALE_EXECUTION")
    if base.reference != attempt.source_revision:
        _reject("WEB_REPAIR_STALE_BASE_REVISION")
    return revisions, attempts, base


def _proposal(operation, *, owner_user_id: UUID) -> WebRepairProposal:
    try:
        payload = operation.payload
        if (
            operation.kind != "REPAIR"
            or set(payload)
            != {"schema_version", "execution_id", "execution_content_hash", "proposal"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or str(UUID(payload["execution_id"])) != payload["execution_id"]
            or not _HASH.fullmatch(payload["execution_content_hash"])
        ):
            raise ValueError("Invalid Web repair operation payload")
        proposal = web_repair_proposal_from_snapshot(payload["proposal"])
        if (
            proposal.project_id != operation.project_id
            or operation.owner_user_id != owner_user_id
            or proposal.created_by_user_id != owner_user_id
            or proposal.base_revision.revision_id != operation.source_revision_id
        ):
            raise ValueError("Web repair proposal operation binding mismatch")
        return proposal
    except (AttributeError, KeyError, TypeError, ValueError):
        _reject("WEB_REPAIR_PROPOSAL_INTEGRITY_FAILED")


def _bind_attempt(operation, proposal: WebRepairProposal, attempt: WebExecutionAttempt) -> None:
    if (
        operation.payload["execution_id"] != str(attempt.id)
        or operation.payload["execution_content_hash"] != attempt.content_hash
        or proposal.base_revision != attempt.source_revision
        or proposal.failure_signature not in attempt.report.failure_signatures()
    ):
        _reject("WEB_REPAIR_EXECUTION_BINDING_MISMATCH")


async def _snapshot(scope, operation, proposal: WebRepairProposal) -> dict[str, JsonValue]:
    result = await scope.snapshot(operation)
    result["proposal_content_hash"] = operation.content_hash
    result["domain_proposal_content_hash"] = web_repair_proposal_to_snapshot(proposal)[
        "content_hash"
    ]
    return cast(dict[str, JsonValue], result)


def _check_limits(attempt_number: int, occurrences: int) -> None:
    policy = DEFAULT_WEB_REPAIR_POLICY
    if (
        not 1 <= attempt_number <= policy.maximum_attempts_per_failure_signature
        or not 1 <= occurrences <= policy.maximum_identical_failure_occurrences
    ):
        _reject("WEB_REPAIR_PAUSED_NEEDS_HUMAN")


def _changes(command: WebRepairProposalCreateCommand):
    if (
        not 1 <= len(command.changes) <= 128
        or not isinstance(command.rationale, str)
        or not 1 <= len(command.rationale) <= 1000
        or command.rationale != " ".join(command.rationale.split())
        or not _HASH.fullmatch(command.base_revision_content_hash)
        or not _HASH.fullmatch(command.failure_signature_digest)
    ):
        _reject("WEB_REPAIR_COMMAND_INVALID", WebApiCommandStatus.INVALID)
    policy = DEFAULT_WEB_SOURCE_PLAN_POLICY
    changes, contents = [], {}
    for item in command.changes:
        path = _portable_path(item.normalized_path)
        if item.operation is WebSourceChangeOperation.DELETE:
            if item.content is not None or item.media_type is not None:
                _reject("WEB_REPAIR_DELETE_CONTENT_INVALID", WebApiCommandStatus.INVALID)
            changes.append(WebSourceChange(path, item.operation, None, None, None, None))
            continue
        if (
            not isinstance(item.operation, WebSourceChangeOperation)
            or not isinstance(item.content, str)
            or "\x00" in item.content
            or len(item.content) > policy.maximum_file_size_bytes
            or item.media_type not in policy.allowed_media_types
        ):
            _reject("WEB_REPAIR_CONTENT_INVALID", WebApiCommandStatus.INVALID)
        content = item.content.encode("utf-8")
        if len(content) > policy.maximum_file_size_bytes:
            _reject("WEB_REPAIR_CONTENT_LIMIT_EXCEEDED", WebApiCommandStatus.INVALID)
        digest = hashlib.sha256(content).hexdigest()
        changes.append(
            WebSourceChange(
                path,
                item.operation,
                digest,
                len(content),
                f"sha256/{digest[:2]}/{digest}",
                item.media_type,
            )
        )
        contents[path] = content
    if sum(len(content) for content in contents.values()) > policy.maximum_total_size_bytes:
        _reject("WEB_REPAIR_CONTENT_LIMIT_EXCEEDED", WebApiCommandStatus.INVALID)
    return tuple(changes), contents


def _projected_bounds(base: WebSourceRevision, changes: tuple[WebSourceChange, ...]):
    projected = {entry.normalized_path: entry for entry in base.files}
    for change in changes:
        if change.operation is WebSourceChangeOperation.DELETE:
            projected.pop(change.normalized_path, None)
        else:
            projected[change.normalized_path] = change.to_file_entry()
    policy = DEFAULT_WEB_SOURCE_PLAN_POLICY
    paths = {path.casefold() for path in projected}
    if (
        not 1 <= len(projected) <= policy.maximum_files
        or any(entry.size_bytes > policy.maximum_file_size_bytes for entry in projected.values())
        or sum(entry.size_bytes for entry in projected.values()) > policy.maximum_total_size_bytes
        or len(paths) != len(projected)
        or any(
            "/".join(path.split("/")[:index]) in paths
            for path in paths
            for index in range(1, len(path.split("/")))
        )
    ):
        _reject("WEB_REPAIR_PROJECTED_SOURCE_INVALID", WebApiCommandStatus.INVALID)
    return tuple(projected.values())
