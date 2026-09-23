"""Prepare an owner execution using configured runners, without client-supplied digests.

Preparation still goes through the existing capability, source and Gate 7 service.
This endpoint proposes an operation; it never approves it or starts a container.
"""

from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from orchestwin.api import jvm_execution, web_execution
from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
from orchestwin.identity.domain import UserAccount
from orchestwin.jvm_execution.attempt_persistence import SqlAlchemyJvmExecutionAttemptRepository
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.attempt_persistence import SqlAlchemyWebExecutionAttemptRepository
from orchestwin.web_execution.attempts import WebExecutionAttemptTrigger
from orchestwin.web_execution.journeys import derive_static_journey
from orchestwin.web_execution.phase_runner import load_phase_runner_identity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.targets import web_scope_for
from orchestwin.workflow.jvm_execution import JvmExecutionPurpose
from orchestwin.workflow.web_execution import WebExecutionPurpose

Platform = Literal["web", "jvm"]


class PrepareExecutionLaunchBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_revision_id: UUID
    source_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    declared_routes: tuple[web_execution.WebBrowserRouteBody, ...] = Field(default=(), max_length=4)
    browser_interactions: tuple[web_execution.WebBrowserInteractionBody, ...] = Field(
        default=(), max_length=5
    )


def default_execution_command(platform, backend, revision, previous):
    """Derive exact settings from the trusted runtime; no guessed image or policy hash."""
    if not backend.config.enabled:
        raise ValueError("EXECUTION_RUNTIME_DISABLED")
    target = revision.target_selection.target
    trigger = (
        "INITIAL"
        if previous is None
        else (
            "MANUAL_RERUN"
            if previous.source_revision.content_hash == revision.content_hash
            else "REPAIR_RERUN"
        )
    )
    if platform == "jvm":
        scope = jvm_scope_for(target)
        scala = target is ExecutionTarget.JVM_SCALA
        image = backend.config.sbt_image_id if scala else backend.config.gradle_image_id
        factory = create_sbt_jvm_runner_contract if scala else create_gradle_jvm_runner_contract
        runner = factory(
            ContainerImageReference(f"orchestwin/jvm-{'sbt' if scala else 'gradle'}-runner@{image}")
        )
        return jvm_execution.JvmExecutionStartCommand(
            revision.id,
            scope.profile_id,
            scope.profile_version,
            runner.execution_policy.content_hash,
            runner.image.digest,
            JvmExecutionPurpose.OWNER_PROJECT,
            JvmExecutionAttemptTrigger(trigger),
            None,
            None if previous is None else tuple(JvmExecutionPhase),
        )
    scope = web_scope_for(target)
    identity = load_phase_runner_identity(
        backend.config.runner_manifest,
        repo_root=backend.config.repo_root,
        kind="PHP" if target is ExecutionTarget.WEB_PHP else "NODE",
    )
    browser = (
        None
        if target is ExecutionTarget.WEB_NODE_EXPRESS
        else load_phase_runner_identity(
            backend.config.runner_manifest, repo_root=backend.config.repo_root, kind="BROWSER"
        )
    )
    return web_execution.WebExecutionStartCommand(
        revision.id,
        scope.profile_id,
        scope.profile_version,
        backend.policy.content_hash,
        identity.image_id.removeprefix("sha256:"),
        None if browser is None else browser.image_id.removeprefix("sha256:"),
        WebExecutionPurpose.OWNER_PROJECT,
        WebExecutionAttemptTrigger(trigger),
        None,
        None if previous is None else tuple(WebExecutionPhase),
        (),
        (),
    )


async def approved_prototype(session, *, owner_user_id, project_id, revision):
    references = [ref for ref in revision.provenance_references if ref.kind.value == "ARCHITECTURE"]
    if len(references) != 1 or not references[0].reference_id.startswith("architecture:"):
        return None
    reference = references[0]
    architecture = await SqlAlchemyArchitecturePackageRepository(
        session, owner_user_id=owner_user_id
    ).get(
        project_id=project_id, version_id=UUID(reference.reference_id.removeprefix("architecture:"))
    )
    if architecture is None or architecture.content_hash != reference.content_hash:
        return None
    design_reference = architecture.package.grounding.design_package_reference
    design = await SqlAlchemyDesignPackageRepository(session, owner_user_id=owner_user_id).get(
        project_id=project_id, version_id=design_reference.artifact_id
    )
    if design is None or design.content_hash != design_reference.content_hash:
        return None
    return design.to_snapshot()["package"].get("prototype")


def create_execution_launch_router():
    router = APIRouter(tags=["execution-launch"])

    @router.get(
        "/projects/{project_id}/execution-launch/web/journey",
        operation_id="deriveWebExecutionJourney",
    )
    async def journey(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        service = getattr(request.app.state, "web_execution_start_api_service", None)
        if service is None or not hasattr(service, "sessions"):
            raise HTTPException(503, detail={"code": "CONFIGURED_EXECUTION_UNAVAILABLE"})
        try:
            async with service.sessions() as session:
                revision = await SqlAlchemyWebSourceRevisionRepository(
                    session, owner_user_id=user.id
                ).current(project_id=project_id)
                if revision is None:
                    raise HTTPException(404, detail={"code": "EXECUTION_SOURCE_NOT_FOUND"})
                if revision.target_selection.target is not ExecutionTarget.WEB_STATIC:
                    return {
                        "status": "NOT_DERIVABLE",
                        "reason": "JOURNEY_REQUIRES_STATIC_TARGET",
                        "source_revision_id": str(revision.id),
                    }
                prototype = await approved_prototype(
                    session, owner_user_id=user.id, project_id=project_id, revision=revision
                )
        except SQLAlchemyError:
            raise HTTPException(503, detail={"code": "EXECUTION_STORAGE_UNAVAILABLE"}) from None
        if not prototype or not prototype.get("screens"):
            return {
                "status": "NOT_DERIVABLE",
                "reason": "APPROVED_PROTOTYPE_UNAVAILABLE",
                "source_revision_id": str(revision.id),
            }
        return {
            **derive_static_journey(prototype),
            "source_revision_id": str(revision.id),
            "source_revision_content_hash": revision.content_hash,
        }

    @router.post(
        "/projects/{project_id}/execution-launch/{platform}/prepare",
        status_code=201,
        operation_id="prepareConfiguredExecution",
    )
    async def prepare(
        project_id: UUID,
        platform: Platform,
        body: PrepareExecutionLaunchBody,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        service = getattr(request.app.state, f"{platform}_execution_start_api_service", None)
        if service is None or not hasattr(service, "backend") or not hasattr(service, "sessions"):
            raise HTTPException(503, detail={"code": "CONFIGURED_EXECUTION_UNAVAILABLE"})
        sources = (
            SqlAlchemyJvmSourceRevisionRepository
            if platform == "jvm"
            else SqlAlchemyWebSourceRevisionRepository
        )
        attempts = (
            SqlAlchemyJvmExecutionAttemptRepository
            if platform == "jvm"
            else SqlAlchemyWebExecutionAttemptRepository
        )
        try:
            async with service.sessions() as session:
                revision = await sources(session, owner_user_id=user.id).current(
                    project_id=project_id
                )
                if revision is None or revision.id != body.source_revision_id:
                    raise HTTPException(404, detail={"code": "EXECUTION_SOURCE_NOT_FOUND"})
                if revision.content_hash != body.source_revision_content_hash:
                    raise HTTPException(409, detail={"code": "EXECUTION_SOURCE_CHANGED"})
                previous = await attempts(session, owner_user_id=user.id).current(
                    project_id=project_id
                )
            command = default_execution_command(platform, service.backend, revision, previous)
            if platform == "jvm" and (body.declared_routes or body.browser_interactions):
                raise HTTPException(422, detail={"code": "BROWSER_CHECKS_REQUIRE_WEB"})
            if platform == "web":
                if command.browser_runner_image_digest and not body.browser_interactions:
                    raise HTTPException(422, detail={"code": "BROWSER_INTERACTION_PLAN_REQUIRED"})
                command = replace(
                    command,
                    declared_routes=tuple(
                        web_execution.WebBrowserRouteCommand(
                            route_id=route.route_id, path=route.path
                        )
                        for route in body.declared_routes
                    ),
                    browser_interactions=tuple(
                        item.to_domain() for item in body.browser_interactions
                    ),
                )
            result = await service.prepare_execution(
                owner_user_id=user.id, project_id=project_id, command=command
            )
        except SQLAlchemyError:
            raise HTTPException(503, detail={"code": "EXECUTION_STORAGE_UNAVAILABLE"}) from None
        except (ValueError, OSError):
            raise HTTPException(
                503, detail={"code": "EXECUTION_RUNTIME_CONFIGURATION_INVALID"}
            ) from None
        commands = jvm_execution if platform == "jvm" else web_execution
        return commands._command_response(result)

    return router
