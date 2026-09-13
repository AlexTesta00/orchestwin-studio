"""Create initial JVM sources after an exact Architecture approval; never execute."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from orchestwin.api.jvm_execution import JvmApiCommandResult, JvmApiCommandStatus
from orchestwin.artifacts.architecture_persistence import SqlAlchemyArchitecturePackageRepository
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.jvm_source_plans import (
    FileSystemJvmSourceContentStore,
    JvmSourcePlanFile,
    create_jvm_source_plan,
    validate_jvm_source_plan,
)
from orchestwin.artifacts.jvm_sources import (
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution.policy import policy_for
from orchestwin.jvm_execution.source_policy import (
    pinned_build_files,
    read_source_objects,
    verify_source_policy,
)
from orchestwin.jvm_execution.workspaces import portable_path
from orchestwin.models.source_publication import bind_source_publication
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository


def _reject(code, status=JvmApiCommandStatus.CONFLICT):
    return JvmApiCommandResult(status, None, code)


class SqlAlchemyJvmSourceApiService:
    def __init__(self, session_factory, *, content_root, repo_root):
        self.sessions = session_factory
        self.root, self.repo = (
            Path(content_root).absolute(),
            None if repo_root is None else Path(repo_root).absolute(),
        )

    async def create_source_revision(self, *, owner_user_id, project_id, command):
        if self.repo is None:
            raise HTTPException(503, detail={"code": "JVM_SOURCE_RECIPE_NOT_CONFIGURED"})
        try:
            references = tuple(
                JvmSourceProvenanceReference(
                    item.kind, item.reference_id, item.version_number, item.content_hash
                )
                for item in command.provenance_references
            )
            if (
                len(references) != 1
                or references[0].kind is not JvmSourceProvenanceKind.ARCHITECTURE
            ):
                raise ValueError("One exact architecture reference required")
            plan = create_jvm_source_plan(
                plan_id=uuid4(),
                project_id=project_id,
                created_by_user_id=owner_user_id,
                target_selection=policy_for(command.target).selection,
                files=tuple(
                    JvmSourcePlanFile(
                        portable_path(item.normalized_path), item.content, item.media_type
                    )
                    for item in command.files
                ),
                rationale=command.rationale,
                provenance_references=references,
                created_at=datetime.now(UTC),
            )
            if not validate_jvm_source_plan(plan).is_accepted:
                raise ValueError("Invalid source plan")
            contents = pinned_build_files(command.target, repo_root=self.repo)
            for item in plan.files:
                data = item.content_bytes
                if item.normalized_path in contents and contents[item.normalized_path] != data:
                    raise ValueError("Build configuration is outside the reviewed recipes")
                contents[item.normalized_path] = data
            verify_source_policy(
                SimpleNamespace(target_selection=plan.target_selection),
                contents,
                repo_root=self.repo,
            )
        except (TypeError, ValueError, KeyError):
            return _reject("JVM_SOURCE_PLAN_INVALID", JvmApiCommandStatus.INVALID)
        except OSError:
            raise HTTPException(503, detail={"code": "JVM_SOURCE_RECIPE_UNAVAILABLE"}) from None
        async with self.sessions() as session, session.begin():
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
                return _reject("JVM_SOURCE_PROJECT_NOT_FOUND", JvmApiCommandStatus.NOT_FOUND)
            if project.mode != "GREENFIELD_GENERATION":
                return _reject("JVM_SOURCE_REQUIRES_GREENFIELD")
            architecture = await SqlAlchemyArchitecturePackageRepository(
                session, owner_user_id=owner_user_id
            ).get_current_owned_for_update(project_id=project_id, owner_user_id=owner_user_id)
            gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )
            if architecture is None or gate is None:
                return _reject(
                    "JVM_SOURCE_ARCHITECTURE_APPROVAL_REQUIRED",
                    JvmApiCommandStatus.APPROVAL_REQUIRED,
                )
            exact = GateArtifactReference(
                project_id,
                HumanGateType.ARCHITECTURE,
                architecture.id,
                architecture.version_number,
                architecture.content_hash,
            )
            if gate.artifact != exact or gate.status is not HumanGateStatus.APPROVED:
                return _reject(
                    "JVM_SOURCE_ARCHITECTURE_NOT_APPROVED", JvmApiCommandStatus.APPROVAL_REQUIRED
                )
            expected = JvmSourceProvenanceReference(
                JvmSourceProvenanceKind.ARCHITECTURE,
                f"architecture:{architecture.id}",
                architecture.version_number,
                architecture.content_hash,
            )
            if references != (expected,):
                return _reject("JVM_SOURCE_PROVENANCE_MISMATCH")
            revisions = SqlAlchemyJvmSourceRevisionRepository(session, owner_user_id=owner_user_id)
            if await revisions.current(project_id=project_id) is not None:
                return _reject("JVM_SOURCE_INITIAL_REVISION_EXISTS")
            store = FileSystemJvmSourceContentStore(self.root)
            revision = create_jvm_source_revision(
                revision_id=uuid4(),
                project_id=project_id,
                created_by_user_id=owner_user_id,
                version_number=1,
                based_on=None,
                target=command.target,
                origin=JvmSourceOrigin.GENERATED_PLAN,
                files=tuple(
                    store.store(
                        normalized_path=path, content=data, media_type="application/octet-stream"
                    )
                    for path, data in contents.items()
                ),
                provenance_references=references,
                created_at=datetime.now(UTC),
            )
            read_source_objects(revision, self.root)
            stored = await revisions.append(revision)
            if stored.status.value != "APPENDED":
                raise HTTPException(409, detail={"code": "JVM_SOURCE_APPEND_CONFLICT"})
            await bind_source_publication(session, "JVM_SOURCE", revision)
            return JvmApiCommandResult(
                JvmApiCommandStatus.SOURCE_REVISION_CREATED,
                revision.to_snapshot(),
                "JVM source stored with verified build recipes; execution remains subject to Gate 7.",
            )
