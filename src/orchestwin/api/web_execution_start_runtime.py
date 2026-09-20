"""Capability-honest preflight for Web execution start requests."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from orchestwin.api.web_execution import (
    WebApiCommandResult,
    WebApiCommandStatus,
    WebExecutionStartCommand,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.profile_registry import WebExecutionProfileRegistry
from orchestwin.workflow.web_execution import WebExecutionPurpose


class WebSourceRevisionLookup(Protocol):
    """Resolve one source revision already scoped to an owner and project."""

    async def source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> dict[str, JsonValue] | None: ...


class CapabilityGuardWebExecutionStartApiService:
    """Reject unsupported starts without fabricating executable capability."""

    def __init__(
        self,
        *,
        source_lookup: WebSourceRevisionLookup,
        registry: WebExecutionProfileRegistry,
    ) -> None:
        self._source_lookup = source_lookup
        self._registry = registry

    async def start_execution(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WebExecutionStartCommand,
    ) -> WebApiCommandResult:
        source = await self._source_lookup.source_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            revision_id=command.source_revision_id,
        )
        if source is None:
            return _rejected(
                WebApiCommandStatus.NOT_FOUND,
                "Web source revision was not found for this owner and project.",
            )

        profile = self._registry.find(command.profile_id, command.profile_version)
        if profile is None:
            return _rejected(
                WebApiCommandStatus.INVALID,
                "Requested Web execution profile was not found.",
            )

        source_target = _source_target(source)
        if source_target is None:
            return _rejected(
                WebApiCommandStatus.INVALID,
                "Stored Web source revision has no valid target selection.",
            )
        if source_target != profile.scope.target.value:
            return _rejected(
                WebApiCommandStatus.INVALID,
                "Web source target does not match the selected execution profile.",
            )

        if (
            command.purpose is WebExecutionPurpose.OWNER_PROJECT
            and profile.scope.capability_status is not ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        ):
            return _rejected(
                WebApiCommandStatus.CAPABILITY_BLOCKED,
                "Owner project execution remains blocked until this profile has Level D evidence.",
            )

        return _rejected(
            WebApiCommandStatus.CONFLICT,
            "Production Web execution start runtime is not configured yet.",
        )


def _source_target(snapshot: dict[str, JsonValue]) -> str | None:
    selection = snapshot.get("target_selection")
    if not isinstance(selection, dict):
        return None
    target = selection.get("target")
    return target if isinstance(target, str) else None


def _rejected(status: WebApiCommandStatus, message: str) -> WebApiCommandResult:
    return WebApiCommandResult(status=status, snapshot=None, message=message)
