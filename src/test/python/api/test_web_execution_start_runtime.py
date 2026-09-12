"""Tests for the capability-honest Web execution start runtime guard."""

from __future__ import annotations

import asyncio
from uuid import UUID

from pydantic import JsonValue

from orchestwin.api.web_execution import WebApiCommandStatus, WebExecutionStartCommand
from orchestwin.api.web_execution_start_runtime import (
    CapabilityGuardWebExecutionStartApiService,
)
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.workflow.web_execution import WebExecutionPurpose

OWNER = UUID(int=96_001)
PROJECT = UUID(int=96_002)
REVISION = UUID(int=96_003)


class FakeWebSourceRevisionLookup:
    def __init__(self, snapshot: dict[str, JsonValue] | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def source_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        revision_id: UUID,
    ) -> dict[str, JsonValue] | None:
        self.calls.append((owner_user_id, project_id, revision_id))
        return self.snapshot


def _source_snapshot(
    target: ExecutionTarget = ExecutionTarget.WEB_STATIC,
) -> dict[str, JsonValue]:
    return {
        "id": str(REVISION),
        "project_id": str(PROJECT),
        "created_by_user_id": str(OWNER),
        "target_selection": {"target": target.value},
    }


def _command(
    *,
    profile_id: str = "web.static",
    purpose: WebExecutionPurpose = WebExecutionPurpose.OWNER_PROJECT,
) -> WebExecutionStartCommand:
    trigger = (
        WebExecutionAttemptTrigger.PROFILE_VALIDATION
        if purpose is WebExecutionPurpose.PROFILE_VALIDATION
        else WebExecutionAttemptTrigger.INITIAL
    )
    return WebExecutionStartCommand(
        source_revision_id=REVISION,
        profile_id=profile_id,
        profile_version="1.0.0",
        policy_content_hash="a" * 64,
        execution_runner_image_digest="b" * 64,
        browser_runner_image_digest="c" * 64,
        purpose=purpose,
        trigger=trigger,
        authorization_id=None,
        rerun_phases=None,
        declared_routes=(),
    )


def _service(
    snapshot: dict[str, JsonValue] | None,
) -> tuple[CapabilityGuardWebExecutionStartApiService, FakeWebSourceRevisionLookup]:
    source_lookup = FakeWebSourceRevisionLookup(snapshot)
    return (
        CapabilityGuardWebExecutionStartApiService(
            source_lookup=source_lookup,
            registry=create_sprint08_web_profile_registry(),
        ),
        source_lookup,
    )


def test_missing_owner_visible_source_is_not_found() -> None:
    service, source_lookup = _service(None)

    result = asyncio.run(
        service.start_execution(
            owner_user_id=OWNER,
            project_id=PROJECT,
            command=_command(),
        )
    )

    assert result.status is WebApiCommandStatus.NOT_FOUND
    assert result.snapshot is None
    assert result.message == "Web source revision was not found for this owner and project."
    assert source_lookup.calls == [(OWNER, PROJECT, REVISION)]


def test_owner_project_level_c_profile_is_capability_blocked() -> None:
    service, _ = _service(_source_snapshot())

    result = asyncio.run(
        service.start_execution(
            owner_user_id=OWNER,
            project_id=PROJECT,
            command=_command(),
        )
    )

    assert result.status is WebApiCommandStatus.CAPABILITY_BLOCKED
    assert result.snapshot is None
    assert (
        result.message
        == "Owner project execution remains blocked until this profile has Level D evidence."
    )


def test_source_target_must_match_selected_profile() -> None:
    service, _ = _service(_source_snapshot())

    result = asyncio.run(
        service.start_execution(
            owner_user_id=OWNER,
            project_id=PROJECT,
            command=_command(profile_id="web.vue"),
        )
    )

    assert result.status is WebApiCommandStatus.INVALID
    assert result.snapshot is None
    assert result.message == "Web source target does not match the selected execution profile."


def test_profile_validation_never_reports_false_execution_success() -> None:
    service, _ = _service(_source_snapshot())

    result = asyncio.run(
        service.start_execution(
            owner_user_id=OWNER,
            project_id=PROJECT,
            command=_command(purpose=WebExecutionPurpose.PROFILE_VALIDATION),
        )
    )

    assert result.status is WebApiCommandStatus.CONFLICT
    assert result.snapshot is None
    assert result.message == "Production Web execution start runtime is not configured yet."
