"""Owner-scoped persisted approval, claim and execution through real Jvm phases."""

from __future__ import annotations

import asyncio
import re

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from orchestwin.api.governed_jvm_context import JvmExecutionProgress, execution_command_snapshot
from orchestwin.api.jvm_execution import JvmApiCommandResult, JvmApiCommandStatus
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.jvm_execution.attempt_persistence import (
    JVM_EXECUTION_ATTEMPTS,
    SqlAlchemyJvmExecutionAttemptRepository,
    _owned_attempt_select,
    jvm_execution_attempt_from_record,
)
from orchestwin.jvm_execution.operation_governance import JvmOperationError, content_hash
from orchestwin.jvm_execution.operation_persistence import SqlAlchemyJvmOperationScope
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.workflow.jvm_execution import (
    JvmExecutionAuthorization,
    JvmExecutionAuthorizationKind,
    JvmExecutionPurpose,
    JvmExecutionServiceStatus,
)


def _reject(status, message):
    return JvmApiCommandResult(status, None, message)


class SqlAlchemyGovernedJvmExecutionApiService:
    def __init__(self, session_factory, *, operation_store, backend, catalog_loader):
        self.sessions = session_factory
        self.operations = operation_store
        self.backend = backend
        self.catalog_loader = catalog_loader

    async def _source_and_previous(self, scope, *, owner_user_id, project_id, command):
        revision = await SqlAlchemyJvmSourceRevisionRepository(
            scope.session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        if (
            revision is None
            or revision.id != command.source_revision_id
            or revision.created_by_user_id != owner_user_id
        ):
            raise JvmOperationError("JVM_EXECUTION_SOURCE_NOT_FOUND", 404)
        previous = await SqlAlchemyJvmExecutionAttemptRepository(
            scope.session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        return revision, previous

    async def _context(self, scope, *, owner_user_id, project_id, command, loaded):
        revision, previous = await self._source_and_previous(
            scope, owner_user_id=owner_user_id, project_id=project_id, command=command
        )
        profile = loaded.registry.find(command.profile_id, command.profile_version)
        if profile is None:
            return _reject(JvmApiCommandStatus.INVALID, "JVM_EXECUTION_PROFILE_NOT_FOUND")
        if (
            command.purpose is JvmExecutionPurpose.OWNER_PROJECT
            and profile.scope.capability_status is not ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        ):
            return _reject(
                JvmApiCommandStatus.CAPABILITY_BLOCKED,
                "Owner project execution remains blocked until this profile has Level D evidence.",
            )
        if (
            command.purpose is JvmExecutionPurpose.PROFILE_VALIDATION
            and revision.origin.value != "DETERMINISTIC_FIXTURE"
        ):
            # A client cannot turn a generated owner project into a validation fixture by changing purpose.
            parent = None if previous is None else await scope.get(previous.id)
            if (
                revision.origin.value != "REPAIR_CHANGE_SET"
                or parent is None
                or parent.kind != "EXECUTION"
                or parent.payload.get("purpose") != "PROFILE_VALIDATION"
            ):
                return _reject(
                    JvmApiCommandStatus.INVALID,
                    "JVM_PROFILE_VALIDATION_REQUIRES_DEVELOPMENT_FIXTURE",
                )
        try:
            return self.backend.prepare(
                revision, command=command, registry=loaded.registry, previous=previous
            )
        except (OSError, ValueError, TypeError):
            return _reject(
                JvmApiCommandStatus.INVALID
                if self.backend.config.enabled
                else JvmApiCommandStatus.CONFLICT,
                "JVM_EXECUTION_INPUT_OR_RUNTIME_INVALID",
            )

    async def prepare_execution(self, *, owner_user_id, project_id, command):
        if command.authorization_id is not None:
            return _reject(
                JvmApiCommandStatus.INVALID, "JVM_PREPARATION_MUST_NOT_REUSE_AUTHORIZATION"
            )
        try:
            loaded = await self.catalog_loader.load()
            async with self.operations.scope(
                owner_user_id=owner_user_id, project_id=project_id
            ) as scope:
                context = await self._context(
                    scope,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    command=command,
                    loaded=loaded,
                )
                if isinstance(context, JvmApiCommandResult):
                    return context
                operation = await scope.propose(
                    source_revision_id=context.revision.id,
                    kind="EXECUTION",
                    payload=context.payload,
                )
                snapshot = await scope.snapshot(operation)
            return JvmApiCommandResult(
                JvmApiCommandStatus.EXECUTION_PREPARED,
                snapshot,
                "Jvm execution plan prepared for an exact owner decision; no execution started.",
            )
        except JvmOperationError as error:
            return self._operation_error(error)
        except SQLAlchemyError:
            raise HTTPException(503, detail={"code": "JVM_EXECUTION_STORAGE_UNAVAILABLE"}) from None

    @staticmethod
    def _operation_error(error):
        return _reject(
            JvmApiCommandStatus.NOT_FOUND
            if error.status_code == 404
            else JvmApiCommandStatus.INVALID
            if error.status_code == 422
            else JvmApiCommandStatus.CONFLICT,
            error.code,
        )

    async def start_execution(self, *, owner_user_id, project_id, command):
        if command.authorization_id is None:
            return _reject(JvmApiCommandStatus.APPROVAL_REQUIRED, "JVM_EXECUTION_APPROVAL_REQUIRED")
        claimed = None
        progress = JvmExecutionProgress()
        try:
            loaded = await self._catalog_before_start(
                owner_user_id=owner_user_id, project_id=project_id, command=command
            )
            async with self.operations.scope(
                owner_user_id=owner_user_id, project_id=project_id
            ) as scope:
                operation = await scope.get(command.authorization_id)
                if operation is None:
                    return _reject(
                        JvmApiCommandStatus.NOT_FOUND, "JVM_EXECUTION_OPERATION_NOT_FOUND"
                    )
                if (
                    operation.kind != "EXECUTION"
                    or operation.source_revision_id != command.source_revision_id
                    or operation.payload.get("command") != execution_command_snapshot(command)
                ):
                    return _reject(
                        JvmApiCommandStatus.CONFLICT, "JVM_EXECUTION_APPROVAL_BINDING_MISMATCH"
                    )
                if operation.state == "COMPLETED":
                    snapshot = await self._stored_attempt(scope, operation)
                    if snapshot is None:
                        raise JvmOperationError("JVM_EXECUTION_RECORDED_ATTEMPT_MISSING", 409)
                    self._verify_recorded(operation, snapshot)
                    return JvmApiCommandResult(
                        JvmApiCommandStatus.EXECUTION_RECORDED,
                        snapshot,
                        "Previously recorded Jvm execution returned without starting another run.",
                    )
                if operation.state != "PENDING":
                    return _reject(
                        JvmApiCommandStatus.CONFLICT, "JVM_EXECUTION_OPERATION_ALREADY_CLAIMED"
                    )
                if loaded is None:
                    return _reject(
                        JvmApiCommandStatus.CONFLICT, "JVM_EXECUTION_OPERATION_STATE_CHANGED"
                    )
                context = await self._context(
                    scope,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    command=command,
                    loaded=loaded,
                )
                if isinstance(context, JvmApiCommandResult):
                    return context
                if operation.payload != context.payload:
                    return _reject(
                        JvmApiCommandStatus.CONFLICT, "JVM_EXECUTION_APPROVAL_BINDING_MISMATCH"
                    )
                claimed = await scope.claim(operation, expected_hash=operation.content_hash)
                # Construct authority only after the persisted exact Gate 7 decision has been verified.
                authorization = JvmExecutionAuthorization(
                    authorization_id=claimed.id,
                    kind=JvmExecutionAuthorizationKind.PROFILE_VALIDATION
                    if command.purpose is JvmExecutionPurpose.PROFILE_VALIDATION
                    else JvmExecutionAuthorizationKind.GATE_7,
                    project_id=project_id,
                    authorized_by_user_id=owner_user_id,
                    source_revision_content_hash=context.revision.content_hash,
                    profile_validation_content_hash=context.contract.validation.content_hash,
                    execution_plan_content_hash=context.contract.execution_plan.content_hash,
                    policy_content_hash=context.request.policy_content_hash,
                    runner_image_digest=context.contract.runner.image.digest,
                )
                if not authorization.matches(request=context.request, contract=context.contract):
                    raise JvmOperationError("JVM_EXECUTION_AUTHORIZATION_MISMATCH", 409)
        except asyncio.CancelledError:
            if claimed is not None:
                # COMMIT can succeed before cancellation reaches its awaiting
                # caller. Re-read the claim; a rolled-back PENDING stays intact.
                await self._finish_interrupted(
                    claimed, "JVM_EXECUTION_INTERRUPTED", execution_started=False
                )
            raise
        except JvmOperationError as error:
            return self._operation_error(error)
        except SQLAlchemyError:
            # An uncertain claim commit never permits execution in this request.
            raise HTTPException(
                503, detail={"code": "JVM_EXECUTION_CLAIM_PERSISTENCE_FAILED"}
            ) from None

        # The claim committed before any workspace/container creation. A retry cannot execute twice.
        try:
            async with self.sessions() as session, session.begin():
                attempts = SqlAlchemyJvmExecutionAttemptRepository(
                    session, owner_user_id=owner_user_id
                )
                result = await self.backend.execute(
                    context,
                    operation=claimed,
                    authorization=authorization,
                    attempts=attempts,
                    progress=progress,
                )
                if result.status is not JvmExecutionServiceStatus.RECORDED:
                    raise JvmOperationError("JVM_EXECUTION_ATTEMPT_NOT_RECORDED", 409)
                if not progress.cleanup_confirmed or progress.finalization_reference is None:
                    raise JvmOperationError("JVM_EXECUTION_CLEANUP_UNCONFIRMED", 409)
                terminal = self._recorded_result(claimed, result.attempt.to_snapshot())
                terminal["finalization_reference"] = progress.finalization_reference.to_snapshot()
                self.backend.verify_finalization(
                    claimed, result.attempt.to_snapshot(), terminal["finalization_reference"]
                )
                scope = SqlAlchemyJvmOperationScope(session, owner_user_id, project_id)
                current = await scope.get(claimed.id)
                await self._finish_current(scope, claimed, current, result=terminal, succeeded=True)
            return JvmApiCommandResult(
                JvmApiCommandStatus.EXECUTION_RECORDED,
                result.attempt.to_snapshot(),
                "Jvm execution attempt and terminal evidence were recorded.",
            )
        except asyncio.CancelledError:
            await self._finish_interrupted(
                claimed, "JVM_EXECUTION_INTERRUPTED", cleanup_confirmed=progress.cleanup_confirmed
            )
            raise
        except Exception as error:
            snapshot = await self._finish_interrupted(
                claimed,
                "JVM_EXECUTION_RUNTIME_OR_PERSISTENCE_FAILED",
                cleanup_confirmed=progress.cleanup_confirmed,
            )
            if snapshot is not None:
                return JvmApiCommandResult(
                    JvmApiCommandStatus.EXECUTION_RECORDED,
                    snapshot,
                    "Persisted Jvm execution and its terminal operation were reconciled.",
                )
            if isinstance(error, JvmOperationError):
                return self._operation_error(error)
            raise HTTPException(
                503, detail={"code": "JVM_EXECUTION_RUNTIME_OR_PERSISTENCE_FAILED"}
            ) from None

    async def _catalog_before_start(self, *, owner_user_id, project_id, command):
        # A quick owner-scoped read avoids loading capability data for missing,
        # rejected or completed requests. Release its connection before the
        # loader opens its own unit of work; claim rechecks all state afterwards.
        async with self.operations.scope(
            owner_user_id=owner_user_id, project_id=project_id
        ) as scope:
            operation = await scope.get(command.authorization_id)
            needed = (
                operation is not None
                and operation.state == "PENDING"
                and operation.kind == "EXECUTION"
                and operation.source_revision_id == command.source_revision_id
                and operation.payload.get("command") == execution_command_snapshot(command)
            )
        return await self.catalog_loader.load() if needed else None

    @staticmethod
    async def _stored_attempt(scope, operation):
        # Use the repository's authoritative ownership SQL and hydration in the
        # already-held session, including replay and interrupted-commit recovery.
        query = _owned_attempt_select(
            project_id=operation.project_id, owner_user_id=operation.owner_user_id
        ).where(JVM_EXECUTION_ATTEMPTS.c.id == operation.id)
        row = (await scope.session.execute(query)).mappings().one_or_none()
        try:
            return None if row is None else jvm_execution_attempt_from_record(row).to_snapshot()
        except (KeyError, TypeError, ValueError):
            raise JvmOperationError("JVM_EXECUTION_RECORDED_ATTEMPT_MISMATCH", 409) from None

    @staticmethod
    async def _finish_current(scope, operation, current, *, result, succeeded):
        if current is None or current.content_hash != operation.content_hash:
            raise JvmOperationError("JVM_EXECUTION_CLAIM_MISMATCH", 409)
        expected = "COMPLETED" if succeeded else "FAILED"
        if current.state == expected and current.result == result:
            return
        await scope.finish(current, result=result, succeeded=succeeded)

    @staticmethod
    def _recorded_result(operation, snapshot):
        try:
            payload, command = operation.payload, operation.payload["command"]
            contract = payload["contract"]
            previous = payload["previous_attempt"]
            checks = (
                snapshot["id"] == str(operation.id),
                snapshot["project_id"] == str(operation.project_id),
                snapshot["created_by_user_id"] == str(operation.owner_user_id),
                snapshot["source_revision"] == payload["source_revision"],
                snapshot["profile_id"] == command["profile_id"],
                snapshot["profile_version"] == command["profile_version"],
                snapshot["profile_validation_content_hash"]
                == contract["validation"]["content_hash"],
                snapshot["execution_plan_content_hash"] == content_hash(contract["execution_plan"]),
                snapshot["report"]["target_selection"] == contract["validation"]["selection"],
                snapshot["report"]["execution_plan_content_hash"]
                == snapshot["execution_plan_content_hash"],
                snapshot["runner_image_digest"] == command["runner_image_digest"],
                snapshot["runner_id"] == contract["runner"]["runner_id"],
                snapshot["runner_version"] == contract["runner"]["version"],
                snapshot["policy_content_hash"] == command["policy_content_hash"],
                snapshot["trigger"] == command["trigger"],
                snapshot["previous_attempt_id"] == (None if previous is None else previous["id"]),
                snapshot["report"]["status"] in {"PASSED", "FAILED", "INCOMPLETE"},
                re.fullmatch(r"[0-9a-f]{64}", snapshot["content_hash"]) is not None,
            )
            if not all(checks):
                raise ValueError
            return {
                "execution_id": snapshot["id"],
                "attempt_content_hash": snapshot["content_hash"],
                "report_status": snapshot["report"]["status"],
            }
        except (KeyError, TypeError, ValueError, AttributeError):
            raise JvmOperationError("JVM_EXECUTION_RECORDED_ATTEMPT_MISMATCH", 409) from None

    def _verify_recorded(self, operation, snapshot):
        try:
            expected = self._recorded_result(operation, snapshot)
            reference = operation.result["finalization_reference"]
            expected["finalization_reference"] = reference
            if expected != operation.result:
                raise ValueError
            self.backend.verify_finalization(operation, snapshot, reference)
        except (KeyError, TypeError, ValueError, OSError, AttributeError):
            raise JvmOperationError("JVM_EXECUTION_RECORDED_ATTEMPT_MISMATCH", 409) from None

    async def _reconcile(self, operation, code, *, execution_started, cleanup_confirmed):
        async with self.operations.scope(
            owner_user_id=operation.owner_user_id, project_id=operation.project_id
        ) as scope:
            current = await scope.get(operation.id)
            if current is None or current.content_hash != operation.content_hash:
                raise JvmOperationError("JVM_EXECUTION_CLAIM_MISMATCH", 409)
            if current.state == "PENDING":
                return None
            # A failed read is not evidence of absence. Let it abort this scope;
            # preserve RUNNING so an uncertain commit cannot be reported false.
            snapshot = await self._stored_attempt(scope, operation)
            if snapshot is not None:
                if current.state != "COMPLETED":
                    raise JvmOperationError("JVM_EXECUTION_ATOMIC_RESULT_MISMATCH", 409)
                self._verify_recorded(current, snapshot)
                return snapshot
            if current.state == "COMPLETED":
                raise JvmOperationError("JVM_EXECUTION_RECORDED_ATTEMPT_MISSING", 409)
            if execution_started and not cleanup_confirmed:
                # Preserve RUNNING for operator recovery; absence is not confirmed cleanup.
                return None
            result = {"failure_code": code, "attempt_recorded": False, "cleanup_confirmed": True}
            if not execution_started:
                result["execution_started"] = False
            await self._finish_current(scope, operation, current, result=result, succeeded=False)
            return None

    async def _finish_interrupted(
        self, operation, code, *, execution_started=True, cleanup_confirmed=False
    ):
        async def reconcile():
            async with asyncio.timeout(30):
                return await self._reconcile(
                    operation,
                    code,
                    execution_started=execution_started,
                    cleanup_confirmed=cleanup_confirmed,
                )

        task = asyncio.create_task(reconcile())
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result
