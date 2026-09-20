"""Owner-scoped persisted approval, claim and execution through real Web phases."""

from __future__ import annotations

import asyncio
import re

from fastapi import HTTPException

from orchestwin.api.governed_web_context import execution_command_snapshot
from orchestwin.api.web_execution import WebApiCommandResult, WebApiCommandStatus
from orchestwin.api.web_execution_read_runtime import SqlAlchemyWebExecutionReadApiService
from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.attempt_persistence import (
    WEB_EXECUTION_ATTEMPTS,
    SqlAlchemyWebExecutionAttemptRepository,
    _owned_attempt_select,
    web_execution_attempt_from_record,
)
from orchestwin.web_execution.operation_governance import WebOperationError
from orchestwin.workflow.web_execution import (
    WebExecutionAuthorization,
    WebExecutionAuthorizationKind,
    WebExecutionPurpose,
    WebExecutionServiceStatus,
)


def _reject(status, message):
    return WebApiCommandResult(status, None, message)


class SqlAlchemyGovernedWebExecutionApiService:
    def __init__(self, session_factory, *, operation_store, backend, catalog_loader):
        self.sessions = session_factory
        self.operations = operation_store
        self.backend = backend
        self.catalog_loader = catalog_loader
        self.reads = SqlAlchemyWebExecutionReadApiService(
            session_factory, evidence_root=backend.evidence_root
        )

    async def _source_and_previous(self, scope, *, owner_user_id, project_id, command):
        revision = await SqlAlchemyWebSourceRevisionRepository(
            scope.session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        if (
            revision is None
            or revision.id != command.source_revision_id
            or revision.created_by_user_id != owner_user_id
        ):
            raise WebOperationError("WEB_EXECUTION_SOURCE_NOT_FOUND", 404)
        previous = await SqlAlchemyWebExecutionAttemptRepository(
            scope.session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        return revision, previous

    async def _context(self, scope, *, owner_user_id, project_id, command, loaded):
        revision, previous = await self._source_and_previous(
            scope, owner_user_id=owner_user_id, project_id=project_id, command=command
        )
        profile = loaded.registry.find(command.profile_id, command.profile_version)
        if profile is None:
            return _reject(WebApiCommandStatus.INVALID, "WEB_EXECUTION_PROFILE_NOT_FOUND")
        if (
            command.purpose is WebExecutionPurpose.OWNER_PROJECT
            and profile.scope.capability_status is not ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        ):
            return _reject(
                WebApiCommandStatus.CAPABILITY_BLOCKED,
                "Owner project execution remains blocked until this profile has Level D evidence.",
            )
        if (
            command.purpose is WebExecutionPurpose.PROFILE_VALIDATION
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
                    WebApiCommandStatus.INVALID,
                    "WEB_PROFILE_VALIDATION_REQUIRES_DEVELOPMENT_FIXTURE",
                )
        try:
            return self.backend.prepare(
                revision, command=command, registry=loaded.registry, previous=previous
            )
        except (OSError, ValueError, TypeError):
            return _reject(
                WebApiCommandStatus.INVALID
                if self.backend.config.enabled
                else WebApiCommandStatus.CONFLICT,
                "WEB_EXECUTION_INPUT_OR_RUNTIME_INVALID",
            )

    async def prepare_execution(self, *, owner_user_id, project_id, command):
        if command.authorization_id is not None:
            return _reject(
                WebApiCommandStatus.INVALID, "WEB_PREPARATION_MUST_NOT_REUSE_AUTHORIZATION"
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
                if isinstance(context, WebApiCommandResult):
                    return context
                operation = await scope.propose(
                    source_revision_id=context.revision.id,
                    kind="EXECUTION",
                    payload=context.payload,
                )
                snapshot = await scope.snapshot(operation)
            return WebApiCommandResult(
                WebApiCommandStatus.EXECUTION_PREPARED,
                snapshot,
                "Web execution plan prepared for an exact owner decision; no execution started.",
            )
        except WebOperationError as error:
            return self._operation_error(error)

    @staticmethod
    def _operation_error(error):
        return _reject(
            WebApiCommandStatus.NOT_FOUND
            if error.status_code == 404
            else WebApiCommandStatus.INVALID
            if error.status_code == 422
            else WebApiCommandStatus.CONFLICT,
            error.code,
        )

    async def start_execution(self, *, owner_user_id, project_id, command):
        if command.authorization_id is None:
            return _reject(WebApiCommandStatus.APPROVAL_REQUIRED, "WEB_EXECUTION_APPROVAL_REQUIRED")
        claimed = None
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
                        WebApiCommandStatus.NOT_FOUND, "WEB_EXECUTION_OPERATION_NOT_FOUND"
                    )
                if (
                    operation.kind != "EXECUTION"
                    or operation.source_revision_id != command.source_revision_id
                    or operation.payload.get("command") != execution_command_snapshot(command)
                ):
                    return _reject(
                        WebApiCommandStatus.CONFLICT, "WEB_EXECUTION_APPROVAL_BINDING_MISMATCH"
                    )
                if operation.state == "COMPLETED":
                    snapshot = await self._stored_attempt(scope, operation)
                    if snapshot is None:
                        raise WebOperationError("WEB_EXECUTION_RECORDED_ATTEMPT_MISSING", 409)
                    recorded = self._recorded_result(operation, snapshot)
                    if operation.result != recorded:
                        raise WebOperationError("WEB_EXECUTION_RECORDED_ATTEMPT_MISMATCH", 409)
                    return WebApiCommandResult(
                        WebApiCommandStatus.EXECUTION_RECORDED,
                        snapshot,
                        "Previously recorded Web execution returned without starting another run.",
                    )
                if operation.state != "PENDING":
                    return _reject(
                        WebApiCommandStatus.CONFLICT, "WEB_EXECUTION_OPERATION_ALREADY_CLAIMED"
                    )
                if loaded is None:
                    return _reject(
                        WebApiCommandStatus.CONFLICT, "WEB_EXECUTION_OPERATION_STATE_CHANGED"
                    )
                context = await self._context(
                    scope,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    command=command,
                    loaded=loaded,
                )
                if isinstance(context, WebApiCommandResult):
                    return context
                if operation.payload != context.payload:
                    return _reject(
                        WebApiCommandStatus.CONFLICT, "WEB_EXECUTION_APPROVAL_BINDING_MISMATCH"
                    )
                claimed = await scope.claim(operation, expected_hash=operation.content_hash)
                # Construct authority only after the persisted exact Gate 7 decision has been verified.
                authorization = WebExecutionAuthorization(
                    authorization_id=claimed.id,
                    kind=WebExecutionAuthorizationKind.PROFILE_VALIDATION
                    if command.purpose is WebExecutionPurpose.PROFILE_VALIDATION
                    else WebExecutionAuthorizationKind.GATE_7,
                    project_id=project_id,
                    authorized_by_user_id=owner_user_id,
                    source_revision_content_hash=context.revision.content_hash,
                    profile_validation_content_hash=context.contract.validation.content_hash,
                    execution_plan_content_hash=context.contract.execution_plan.content_hash,
                    policy_content_hash=context.request.policy_content_hash,
                    execution_runner_image_digest=context.contract.runners.execution_runner_image_digest,
                    browser_runner_image_digest=context.contract.runners.browser_runner_image_digest,
                )
                if not authorization.matches(request=context.request, contract=context.contract):
                    raise WebOperationError("WEB_EXECUTION_AUTHORIZATION_MISMATCH", 409)
        except asyncio.CancelledError:
            if claimed is not None:
                # COMMIT can succeed before cancellation reaches its awaiting
                # caller. Re-read the claim; a rolled-back PENDING stays intact.
                await self._finish_interrupted(
                    claimed, "WEB_EXECUTION_INTERRUPTED", execution_started=False
                )
            raise
        except WebOperationError as error:
            return self._operation_error(error)

        # The claim committed before any workspace/container creation. A retry cannot execute twice.
        try:
            async with self.sessions() as session, session.begin():
                attempts = SqlAlchemyWebExecutionAttemptRepository(
                    session, owner_user_id=owner_user_id
                )
                result = await self.backend.execute(
                    context, operation=claimed, authorization=authorization, attempts=attempts
                )
                if result.status is not WebExecutionServiceStatus.RECORDED:
                    raise WebOperationError("WEB_EXECUTION_ATTEMPT_NOT_RECORDED", 409)
            await self._finish(
                claimed,
                result=self._recorded_result(claimed, result.attempt.to_snapshot()),
                succeeded=True,
            )
            return WebApiCommandResult(
                WebApiCommandStatus.EXECUTION_RECORDED,
                result.attempt.to_snapshot(),
                "Web execution attempt and terminal evidence were recorded.",
            )
        except asyncio.CancelledError:
            await self._finish_interrupted(claimed, "WEB_EXECUTION_INTERRUPTED")
            raise
        except Exception as error:
            snapshot = await self._finish_interrupted(
                claimed, "WEB_EXECUTION_RUNTIME_OR_PERSISTENCE_FAILED"
            )
            if snapshot is not None:
                return WebApiCommandResult(
                    WebApiCommandStatus.EXECUTION_RECORDED,
                    snapshot,
                    "Persisted Web execution and its terminal operation were reconciled.",
                )
            if isinstance(error, WebOperationError):
                return self._operation_error(error)
            raise HTTPException(
                503, detail={"code": "WEB_EXECUTION_RUNTIME_OR_PERSISTENCE_FAILED"}
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
        ).where(WEB_EXECUTION_ATTEMPTS.c.id == operation.id)
        row = (await scope.session.execute(query)).mappings().one_or_none()
        return None if row is None else web_execution_attempt_from_record(row).to_snapshot()

    async def _finish(self, operation, *, result, succeeded):
        async with self.operations.scope(
            owner_user_id=operation.owner_user_id, project_id=operation.project_id
        ) as scope:
            current = await scope.get(operation.id)
            if current is None:
                raise WebOperationError("WEB_EXECUTION_CLAIM_MISSING", 409)
            await self._finish_current(
                scope, operation, current, result=result, succeeded=succeeded
            )

    @staticmethod
    async def _finish_current(scope, operation, current, *, result, succeeded):
        if current.content_hash != operation.content_hash:
            raise WebOperationError("WEB_EXECUTION_CLAIM_MISMATCH", 409)
        expected = "COMPLETED" if succeeded else "FAILED"
        if current.state == expected and current.result == result:
            return
        await scope.finish(current, result=result, succeeded=succeeded)

    @staticmethod
    def _recorded_result(operation, snapshot):
        """Bind the hydrated owner-scoped attempt back to its exact approved input."""
        try:
            payload, command = operation.payload, operation.payload["command"]
            contract, report = payload["contract"], snapshot["report"]
            previous = payload["previous_attempt"]
            checks = (
                snapshot["id"] == str(operation.id),
                snapshot["project_id"] == str(operation.project_id),
                snapshot["created_by_user_id"] == str(operation.owner_user_id),
                snapshot["source_revision"] == payload["source_revision"],
                snapshot["profile_validation_content_hash"]
                == contract["validation"]["content_hash"],
                snapshot["execution_plan_content_hash"]
                == contract["execution_plan"]["content_hash"],
                snapshot["trigger"] == command["trigger"],
                snapshot["previous_attempt_id"] == (None if previous is None else previous["id"]),
                report["source_revision_content_hash"]
                == payload["source_revision"]["content_hash"],
                report["source_tree_hash"] == payload["source_tree_hash"],
                report["profile_id"] == command["profile_id"],
                report["profile_version"] == command["profile_version"],
                report["policy_content_hash"] == command["policy_content_hash"],
                report["runner_image_digest"] == command["execution_runner_image_digest"],
                report["status"] in {"PASSED", "FAILED", "INCOMPLETE"},
                isinstance(snapshot["content_hash"], str)
                and re.fullmatch(r"[0-9a-f]{64}", snapshot["content_hash"]) is not None,
            )
            if not all(checks):
                raise ValueError
            return {
                "execution_id": snapshot["id"],
                "attempt_content_hash": snapshot["content_hash"],
                "report_status": report["status"],
            }
        except (KeyError, TypeError, ValueError, AttributeError):
            raise WebOperationError("WEB_EXECUTION_RECORDED_ATTEMPT_MISMATCH", 409) from None

    async def _reconcile(self, operation, code, *, execution_started):
        async with self.operations.scope(
            owner_user_id=operation.owner_user_id, project_id=operation.project_id
        ) as scope:
            current = await scope.get(operation.id)
            if current is None or current.content_hash != operation.content_hash:
                raise WebOperationError("WEB_EXECUTION_CLAIM_MISMATCH", 409)
            if current.state == "PENDING":
                return None
            # A failed read is not evidence of absence. Let it abort this scope;
            # preserve RUNNING so an uncertain commit cannot be reported false.
            snapshot = await self._stored_attempt(scope, operation)
            if snapshot is not None:
                result = self._recorded_result(operation, snapshot)
                await self._finish_current(scope, operation, current, result=result, succeeded=True)
                return snapshot
            result = {"failure_code": code, "attempt_recorded": False}
            if not execution_started:
                result["execution_started"] = False
            await self._finish_current(scope, operation, current, result=result, succeeded=False)
            return None

    async def _finish_interrupted(self, operation, code, *, execution_started=True):
        async def reconcile():
            async with asyncio.timeout(30):
                return await self._reconcile(operation, code, execution_started=execution_started)

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
