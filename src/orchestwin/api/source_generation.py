"""Owner-scoped real inference feeding the existing governed source services."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from orchestwin.api import jvm_execution as jvm_commands
from orchestwin.api import jvm_repair_runtime as jvm_repair
from orchestwin.api import web_execution as web_commands
from orchestwin.api import web_repair_runtime as web_repair
from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.jvm_sources import JvmSourceProvenanceKind
from orchestwin.artifacts.web_source_persistence import SqlAlchemyWebSourceRevisionRepository
from orchestwin.artifacts.web_sources import WebSourceProvenanceKind
from orchestwin.identity.domain import UserAccount
from orchestwin.jvm_execution.policy import policy_for
from orchestwin.jvm_execution.source_policy import pinned_build_files
from orchestwin.jvm_execution.workspaces import read_regular_file
from orchestwin.models.proposal_evidence import current_proposal_evidence, evidence_application
from orchestwin.models.proposal_generation import wire_value
from orchestwin.models.repair_diagnostics import failure_log_context
from orchestwin.models.source_context import compact_implementation_references
from orchestwin.models.source_proposals import MAX_CONTEXT_BYTES, file_entry
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_primitives import canonical_json
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
    web_scope_for,
)
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository

Platform = Literal["web", "jvm"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceGenerationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target: ExecutionTarget
    architecture_version_id: UUID
    architecture_content_hash: Digest
    frontend_language: WebImplementationLanguage | None = None
    backend_language: WebImplementationLanguage | None = None
    layout: WebProjectLayout = WebProjectLayout.SINGLE_ROOT


class RepairGenerationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_revision_content_hash: Digest
    failure_signature_digest: Digest


def _require(condition, code, status=409):
    if not condition:
        raise HTTPException(status, detail={"code": code})


def _signatures(attempt, platform):
    return (
        attempt.report.failure_signatures()
        if platform == "web"
        else attempt.report.failure_signatures
    )


def _signature_digest(signature, platform):
    return signature.digest if platform == "web" else signature.signature


def _selection(platform, body):
    if platform == "jvm":
        _require(
            body.target.value in {"JVM_JAVA", "JVM_KOTLIN", "JVM_SCALA"},
            "SOURCE_TARGET_OUTSIDE_SCOPE",
            422,
        )
        _require(
            body.frontend_language is None
            and body.backend_language is None
            and body.layout is WebProjectLayout.SINGLE_ROOT,
            "JVM_WEB_OPTIONS_FORBIDDEN",
            422,
        )
        return policy_for(body.target).selection
    _require(
        body.target.value in {"WEB_STATIC", "WEB_VUE", "WEB_NODE_EXPRESS", "WEB_VUE_NODE"},
        "SOURCE_TARGET_OUTSIDE_SCOPE",
        422,
    )
    try:
        selection = WebTargetSelection(
            body.target,
            WebLanguageConfiguration(body.frontend_language, body.backend_language),
            body.layout,
        )
        selection.validate_against(web_scope_for(body.target))
    except ValueError:
        raise HTTPException(422, detail={"code": "SOURCE_TARGET_CONFIGURATION_INVALID"}) from None
    return selection


def _build_context(fixed):
    # Hashes cover every pinned byte; only build definitions are useful model input.
    included = {"build.gradle.kts", "settings.gradle.kts", "build.sbt", "project/build.properties"}
    return {
        "build_recipe_view": "PINNED_BUILD_DEFINITIONS_V1",
        "build_recipes": {
            path: content.decode("utf-8")
            for path, content in sorted(fixed.items())
            if path in included
        },
        "build_recipe_metadata_only": sorted(set(fixed) - included),
    }


def _bounded_context(context):
    _require(
        len(canonical_json(wire_value(context)).encode("utf-8")) <= MAX_CONTEXT_BYTES,
        "SOURCE_CONTEXT_LIMIT_EXCEEDED",
        422,
    )
    return context


def _artifact_view(version, kind):
    """Explicit implementation view; the reference still identifies the whole version."""
    snapshot = version.to_snapshot()
    reference = {
        key: snapshot[key] for key in ("id", "project_id", "version_number", "content_hash")
    }
    if kind == "requirements":
        content = snapshot["specification"]
        omitted = []
    else:
        package = snapshot["package"]
        keys = (
            ("architecture", "test_plan", "open_questions")
            if kind == "architecture"
            else (
                "owner_selected_alternative_id",
                "recommended_alternative_id",
                "alternatives",
                "prototype",
                "concerns",
                "open_questions",
            )
        )
        content = {key: package[key] for key in keys}
        omitted = sorted(set(package) - set(keys))
        if kind == "design":
            selected = (
                package["owner_selected_alternative_id"] or package["recommended_alternative_id"]
            )
            content["alternatives"] = [
                item for item in package["alternatives"] if item["id"] == selected
            ]
            _require(len(content["alternatives"]) == 1, "SOURCE_DESIGN_SELECTION_UNAVAILABLE")
            content["metadata_only_alternative_ids"] = [
                item["id"] for item in package["alternatives"] if item["id"] != selected
            ]
    return {
        "reference": reference,
        "view": "SOURCE_IMPLEMENTATION_V1",
        "content": content,
        "omitted_package_fields": omitted,
    }


async def _grounded_artifact_views(session, *, owner_user_id, project_id, architecture):
    """Load the immutable inputs referenced by this architecture, not today's latest versions."""
    grounding = architecture.package.grounding
    inputs = {"architecture": _artifact_view(architecture, "architecture")}
    for name, repo, reference in (
        (
            "requirements",
            SqlAlchemyRequirementsSpecificationRepository,
            grounding.requirements_reference,
        ),
        ("design", SqlAlchemyDesignPackageRepository, grounding.design_package_reference),
    ):
        version = await repo(session, owner_user_id=owner_user_id).get(
            project_id=project_id, version_id=reference.artifact_id
        )
        _require(
            version is not None
            and version.version_number == reference.version_number
            and version.content_hash == reference.content_hash,
            "SOURCE_GROUNDING_UNAVAILABLE",
        )
        inputs[name] = _artifact_view(version, name)
    return inputs


async def _repair_grounding(session, *, owner_user_id, project_id, base):
    references = [ref for ref in base.provenance_references if ref.kind.value == "ARCHITECTURE"]
    if not references:
        # Imported sources may have no architecture. Do not invent approved requirements.
        return {"status": "SOURCE_ONLY_NO_ARCHITECTURE_REFERENCE"}
    _require(len(references) == 1, "REPAIR_ARCHITECTURE_REFERENCE_AMBIGUOUS")
    reference = references[0]
    _require(
        reference.reference_id.startswith("architecture:"), "REPAIR_ARCHITECTURE_REFERENCE_INVALID"
    )
    architecture = await SqlAlchemyArchitecturePackageRepository(
        session, owner_user_id=owner_user_id
    ).get(
        project_id=project_id, version_id=UUID(reference.reference_id.removeprefix("architecture:"))
    )
    _require(
        architecture is not None
        and architecture.version_number == reference.version_number
        and architecture.content_hash == reference.content_hash,
        "REPAIR_ARCHITECTURE_UNAVAILABLE",
    )
    return {
        "status": "EXACT_SOURCE_ARCHITECTURE",
        **await _grounded_artifact_views(
            session, owner_user_id=owner_user_id, project_id=project_id, architecture=architecture
        ),
    }


class ModelSourceApplication:
    def __init__(self, runtime):
        _require(runtime.real_model_runtime is not None, "REAL_SOURCE_MODEL_NOT_CONFIGURED", 503)
        _require(
            runtime.database_runtime is not None and runtime.proposal_evidence_store is not None,
            "SOURCE_EVIDENCE_STORE_NOT_CONFIGURED",
            503,
        )
        self.runtime = runtime
        self.sessions = runtime.database_runtime.session_factory
        self.adapter = runtime.real_model_runtime.sources
        self._proposal_evidence_store = runtime.proposal_evidence_store

    def _fixed_files(self, platform, target):
        if platform == "web":
            return {}
        repo = self.runtime.jvm_source_api_service.repo
        _require(repo is not None, "JVM_SOURCE_RECIPE_NOT_CONFIGURED", 503)
        return pinned_build_files(target, repo_root=repo)

    async def source_context(self, *, owner_user_id, project_id, platform, body):
        selection = _selection(platform, body)
        repository = (
            SqlAlchemyWebSourceRevisionRepository
            if platform == "web"
            else SqlAlchemyJvmSourceRevisionRepository
        )
        async with self.sessions() as session, session.begin():
            project = await session.scalar(
                select(ProjectRecord).where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
            )
            _require(project is not None, "SOURCE_PROJECT_NOT_FOUND", 404)
            _require(project.mode == "GREENFIELD_GENERATION", "SOURCE_REQUIRES_GREENFIELD")
            _require(
                await repository(session, owner_user_id=owner_user_id).current(
                    project_id=project_id
                )
                is None,
                "SOURCE_INITIAL_REVISION_EXISTS",
            )
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id)
            _require(architecture is not None, "SOURCE_ARCHITECTURE_APPROVAL_REQUIRED")
            _require(
                architecture.id == body.architecture_version_id
                and architecture.content_hash == body.architecture_content_hash,
                "SOURCE_ARCHITECTURE_STALE",
            )
            gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )
            exact = GateArtifactReference(
                project_id,
                HumanGateType.ARCHITECTURE,
                architecture.id,
                architecture.version_number,
                architecture.content_hash,
            )
            _require(
                gate is not None
                and gate.artifact == exact
                and gate.status is HumanGateStatus.APPROVED,
                "SOURCE_ARCHITECTURE_APPROVAL_REQUIRED",
            )
            context = {
                "project_id": str(project_id),
                "target_selection": selection.to_snapshot(),
                **await _grounded_artifact_views(
                    session,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    architecture=architecture,
                ),
                "provenance_references": [
                    {
                        "kind": "ARCHITECTURE",
                        "reference_id": f"architecture:{architecture.id}",
                        "version_number": architecture.version_number,
                        "content_hash": architecture.content_hash,
                    }
                ],
            }
        fixed = self._fixed_files(platform, body.target)
        context["fixed_files"] = [
            file_entry(path, content, "application/octet-stream")
            for path, content in sorted(fixed.items())
        ]
        context.update(_build_context(fixed))
        return _bounded_context(compact_implementation_references(context))

    async def repair_context(self, *, owner_user_id, project_id, platform, execution_id, body):
        module = web_repair if platform == "web" else jvm_repair
        service = getattr(self.runtime, platform + "_repair_api_service")
        try:
            attempt = await service._attempt(owner_user_id=owner_user_id, execution_id=execution_id)
            _require(attempt.project_id == project_id, "REPAIR_EXECUTION_NOT_FOUND", 404)
            async with service._operation_store.scope(
                owner_user_id=owner_user_id, project_id=project_id
            ) as scope:
                _, attempts, base = await module._current(
                    scope.session, owner_user_id=owner_user_id, attempt=attempt
                )
                _require(base.content_hash == body.base_revision_content_hash, "REPAIR_STALE_BASE")
                signature = next(
                    (
                        item
                        for item in _signatures(attempt, platform)
                        if _signature_digest(item, platform) == body.failure_signature_digest
                    ),
                    None,
                )
                _require(signature is not None, "REPAIR_FAILURE_NOT_RECORDED")
                prior = [
                    module._proposal(operation, owner_user_id=owner_user_id)
                    for operation in await scope.history(kind="REPAIR")
                ]
                number = 1 + sum(
                    _signature_digest(item.failure_signature, platform)
                    == body.failure_signature_digest
                    for item in prior
                )
                occurrences = sum(
                    any(
                        _signature_digest(item, platform) == body.failure_signature_digest
                        for item in _signatures(entry, platform)
                    )
                    for entry in await attempts.history(project_id=project_id)
                )
                module._check_limits(number, occurrences)
                grounding = await _repair_grounding(
                    scope.session, owner_user_id=owner_user_id, project_id=project_id, base=base
                )
            fixed = self._fixed_files(platform, base.target_selection.target)
            entries = [item.to_snapshot() for item in base.files]
            selected = [item for item in entries if item["normalized_path"] not in fixed]
            _require(
                sum(item["size_bytes"] for item in selected) <= MAX_CONTEXT_BYTES,
                "REPAIR_SOURCE_CONTEXT_LIMIT",
                422,
            )
            contents = []
            for entry in selected:
                digest = entry["sha256_digest"]
                _require(
                    entry["storage_key"] == f"sha256/{digest[:2]}/{digest}",
                    "REPAIR_SOURCE_OBJECT_INVALID",
                )
                raw = read_regular_file(
                    service._content_root / entry["storage_key"], maximum_bytes=entry["size_bytes"]
                )
                _require(
                    file_entry(entry["normalized_path"], raw, entry["media_type"]) == entry,
                    "REPAIR_SOURCE_OBJECT_INVALID",
                )
                contents.append(
                    {
                        "normalized_path": entry["normalized_path"],
                        "content": raw.decode("utf-8"),
                        "media_type": entry["media_type"],
                    }
                )
            failed_phase = next(
                phase for phase in attempt.report.phase_results if phase.phase == signature.phase
            )
            execution_service = getattr(self.runtime, platform + "_execution_start_api_service")
            backend = getattr(execution_service, "backend", None)
            diagnostics = failure_log_context(failed_phase, getattr(backend, "evidence_root", None))
            return _bounded_context(
                {
                    "project_id": str(project_id),
                    "target_selection": base.target_selection.to_snapshot(),
                    "execution_id": str(attempt.id),
                    "execution_content_hash": attempt.content_hash,
                    "base_revision": base.reference.to_snapshot(),
                    "base_files": entries,
                    "source_files": contents,
                    "approved_context": grounding,
                    "failure_signature": signature.to_snapshot(),
                    "failure_log_evidence": diagnostics,
                    "recorded_failure": next(
                        {
                            "phase": phase.phase.value,
                            "status": phase.status.value,
                            "failure_code": phase.failure_code,
                            "normalized_summary": phase.normalized_summary,
                            "findings": [finding.to_snapshot() for finding in phase.findings],
                        }
                        for phase in attempt.report.phase_results
                        if phase.phase == signature.phase
                    ),
                    "fixed_files": [
                        file_entry(path, data, "application/octet-stream")
                        for path, data in sorted(fixed.items())
                    ],
                    **_build_context(fixed),
                }
            )
        except module._RepairRejected as error:
            raise HTTPException(
                404 if error.status.value == "NOT_FOUND" else 409, detail={"code": error.code}
            ) from None
        except (OSError, UnicodeError, ValueError):
            raise HTTPException(409, detail={"code": "REPAIR_SOURCE_CONTEXT_UNAVAILABLE"}) from None

    @evidence_application
    async def generate_source(self, *, owner_user_id, project_id, platform, body):
        context = await self.source_context(
            owner_user_id=owner_user_id, project_id=project_id, platform=platform, body=body
        )
        proposal = await self.adapter.propose_files(task=platform + "-source", context=context)
        output = proposal.output
        commands = web_commands if platform == "web" else jvm_commands
        prefix = "Web" if platform == "web" else "Jvm"
        provenance = WebSourceProvenanceKind if platform == "web" else JvmSourceProvenanceKind
        kwargs = {
            "target": body.target,
            "rationale": output.rationale,
            "files": tuple(
                getattr(commands, prefix + "SourcePlanFileCommand")(**item.model_dump())
                for item in output.files
            ),
            "provenance_references": tuple(
                getattr(commands, prefix + "SourceProvenanceCommand")(
                    **{**ref, "kind": provenance.ARCHITECTURE}
                )
                for ref in context["provenance_references"]
            ),
        }
        if platform == "web":
            kwargs.update(
                frontend_language=body.frontend_language,
                backend_language=body.backend_language,
                layout=body.layout,
            )
        result = await getattr(
            self.runtime, platform + "_source_api_service"
        ).create_source_revision(
            owner_user_id=owner_user_id,
            project_id=project_id,
            command=getattr(commands, prefix + "SourceRevisionCreateCommand")(**kwargs),
        )
        return self._with_generation(result)

    @evidence_application
    async def generate_repair(self, *, owner_user_id, project_id, platform, execution_id, body):
        context = await self.repair_context(
            owner_user_id=owner_user_id,
            project_id=project_id,
            platform=platform,
            execution_id=execution_id,
            body=body,
        )
        proposal = await self.adapter.propose(task=platform + "-repair", context=context)
        commands = web_commands if platform == "web" else jvm_commands
        prefix = "Web" if platform == "web" else "Jvm"
        operation = (
            web_repair.WebSourceChangeOperation
            if platform == "web"
            else jvm_repair.JvmSourceChangeOperation
        )
        kwargs = {
            "base_revision_content_hash": body.base_revision_content_hash,
            "failure_signature_digest"
            if platform == "web"
            else "failure_signature": body.failure_signature_digest,
            "rationale": proposal.output.rationale,
            "changes": tuple(
                getattr(commands, prefix + "RepairChangeCommand")(
                    **{**item.model_dump(), "operation": operation(item.operation)}
                )
                for item in proposal.output.changes
            ),
        }
        result = await getattr(
            self.runtime, platform + "_repair_api_service"
        ).create_repair_proposal(
            owner_user_id=owner_user_id,
            execution_id=execution_id,
            command=getattr(commands, prefix + "RepairProposalCreateCommand")(**kwargs),
        )
        return self._with_generation(result)

    @staticmethod
    def _with_generation(result):
        from dataclasses import replace

        scope = current_proposal_evidence()
        if scope is not None and scope.request is not None and result.snapshot is not None:
            result = replace(
                result,
                snapshot={**result.snapshot, "model_generation_id": str(scope.request.request_id)},
            )
        return result


def _service(request: Request):
    return ModelSourceApplication(request.app.state.application_runtime)


def _response(result):
    code = {
        "SOURCE_REVISION_CREATED": 201,
        "REPAIR_PROPOSED": 201,
        "NOT_FOUND": 404,
        "INVALID": 422,
        "APPROVAL_REQUIRED": 409,
    }.get(result.status.value, 409)
    return JSONResponse(status_code=code, content=wire_value(result))


def create_source_generation_router():
    router = APIRouter(tags=["source-generation"])

    @router.post("/projects/{project_id}/source-generations/{platform}")
    async def source(
        project_id: UUID,
        platform: Platform,
        body: SourceGenerationBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ModelSourceApplication, Depends(_service)],
    ):
        return _response(
            await service.generate_source(
                owner_user_id=user.id, project_id=project_id, platform=platform, body=body
            )
        )

    @router.post("/projects/{project_id}/repair-generations/{platform}/{execution_id}")
    async def repair(
        project_id: UUID,
        platform: Platform,
        execution_id: UUID,
        body: RepairGenerationBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ModelSourceApplication, Depends(_service)],
    ):
        return _response(
            await service.generate_repair(
                owner_user_id=user.id,
                project_id=project_id,
                platform=platform,
                execution_id=execution_id,
                body=body,
            )
        )

    return router
