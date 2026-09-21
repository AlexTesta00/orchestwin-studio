"""Real, owner-authorized JVM fixture campaign with durable Gate 7 operations.

Each job is checkpointed before execution. Retries use the same operation ID;
an unresolved RUNNING claim is never automatically executed again.
"""

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import insert, select

from orchestwin.api.governed_jvm_context import JvmExecutionBackend, execution_command_snapshot
from orchestwin.api.governed_jvm_execution_runtime import SqlAlchemyGovernedJvmExecutionApiService
from orchestwin.api.jvm_execution import (
    JvmExecutionStartCommand,
    JvmRepairChangeCommand,
    JvmRepairProposalApplyCommand,
    JvmRepairProposalCreateCommand,
)
from orchestwin.api.jvm_repair_runtime import SqlAlchemyJvmRepairApiService
from orchestwin.artifacts.jvm_change_sets import JvmSourceChangeOperation
from orchestwin.artifacts.jvm_source_persistence import SqlAlchemyJvmSourceRevisionRepository
from orchestwin.artifacts.jvm_source_plans import FileSystemJvmSourceContentStore
from orchestwin.artifacts.jvm_sources import (
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.identity.persistence.models import UserRecord
from orchestwin.jvm_execution.attempt_persistence import SqlAlchemyJvmExecutionAttemptRepository
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.operation_governance import canonical_bytes, content_hash
from orchestwin.jvm_execution.operation_persistence import SqlAlchemyJvmOperationStore
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_loader import build_jvm_profile_catalog_loader
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.jvm_execution.validation_fixtures import CASES, fixture_bundle, fixture_bytes
from orchestwin.jvm_execution.workspaces import regular_path
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.gates import HumanGateAction
from orchestwin.workflow.jvm_execution import JvmExecutionPurpose
from orchestwin.workflow.persistence.models import HumanGateEventRecord

TARGETS = (ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA)


def write_once(path, value):
    regular_path(path)
    data = canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("JVM_CAMPAIGN_IMMUTABLE_RECEIPT_CONFLICT") from None


class JvmValidationCampaign:
    def __init__(self, sessions, *, config, output_root, owner_user_id, targets=TARGETS):
        if (
            not targets
            or any(target not in TARGETS for target in targets)
            or len(set(targets)) != len(targets)
        ):
            raise ValueError("JVM_CAMPAIGN_TARGETS_INVALID")
        self.targets = tuple(targets)
        self.sessions, self.config = sessions, config
        self.root, self.owner = Path(output_root).absolute(), owner_user_id
        regular_path(self.root)
        self.operations = SqlAlchemyJvmOperationStore(sessions)
        self.backend = JvmExecutionBackend(
            config=config, content_root=self.root / "sources", evidence_root=self.root / "evidence"
        )
        self.service = SqlAlchemyGovernedJvmExecutionApiService(
            sessions,
            operation_store=self.operations,
            backend=self.backend,
            catalog_loader=build_jvm_profile_catalog_loader(sessions),
        )
        self.repairs = SqlAlchemyJvmRepairApiService(
            sessions,
            operation_store=self.operations,
            content_root=self.backend.content_root,
            repo_root=config.repo_root,
        )

    async def prepare(self):
        manifest_path = self.root / "campaign.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_bytes())
            if manifest["owner_user_id"] != str(self.owner):
                raise ValueError("JVM_CAMPAIGN_OWNER_MISMATCH")
            for target in self.targets:
                if manifest["fixtures"][target.value] != fixture_bundle(
                    self.config.repo_root, target
                ):
                    raise ValueError("JVM_CAMPAIGN_FIXTURE_DRIFT")
            return manifest
        async with self.sessions() as session:
            if not await session.scalar(
                select(UserRecord.id).where(
                    UserRecord.id == self.owner, UserRecord.is_active.is_(True)
                )
            ):
                raise ValueError("JVM_CAMPAIGN_ACTIVE_OWNER_REQUIRED")
        manifest = {
            "schema_version": 1,
            "campaign_id": str(uuid4()),
            "owner_user_id": str(self.owner),
            "fixtures": {
                target.value: fixture_bundle(self.config.repo_root, target)
                for target in self.targets
            },
            "jobs": [
                {"target": target.value, "case": case} for target in self.targets for case in CASES
            ],
            "approval_scope": "OWNER_AUTHORIZED_JVM_PROFILE_VALIDATION_FIXTURES_ONLY",
            "level_d_validated": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        write_once(manifest_path, manifest)
        return manifest

    async def _source(self, manifest, target, case):
        path = self.root / target.value / case / "source.json"
        if path.exists():
            source = json.loads(path.read_bytes())
            async with self.sessions() as session:
                revisions = await SqlAlchemyJvmSourceRevisionRepository(
                    session, owner_user_id=self.owner
                ).history(project_id=UUID(source["project_id"]))
                found = next((item for item in revisions if str(item.id) == source["id"]), None)
                if found is None or found.to_snapshot() != source:
                    raise ValueError("JVM_CAMPAIGN_SOURCE_PERSISTENCE_MISMATCH")
                return found
        store = FileSystemJvmSourceContentStore(self.backend.content_root)
        source = create_jvm_source_revision(
            revision_id=uuid4(),
            project_id=uuid4(),
            created_by_user_id=self.owner,
            version_number=1,
            based_on=None,
            target=target,
            origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
            files=tuple(
                store.store(
                    normalized_path=name, content=data, media_type="application/octet-stream"
                )
                for name, data in fixture_bytes(self.config.repo_root, target, case).items()
            ),
            provenance_references=(
                JvmSourceProvenanceReference(
                    JvmSourceProvenanceKind.SOURCE_PLAN,
                    f"jvm-campaign:{manifest['campaign_id']}:{case}",
                    1,
                    content_hash(manifest),
                ),
            ),
            created_at=datetime.now(UTC),
        )
        async with self.sessions() as session, session.begin():
            await session.execute(
                insert(ProjectRecord).values(
                    id=source.project_id,
                    owner_user_id=self.owner,
                    display_name=f"JVM Level D {target.value} {case}",
                    mode="GREENFIELD_GENERATION",
                )
            )
            if (
                await SqlAlchemyJvmSourceRevisionRepository(
                    session, owner_user_id=self.owner
                ).append(source)
            ).status.value != "APPENDED":
                raise ValueError("JVM_CAMPAIGN_SOURCE_APPEND_FAILED")
        write_once(path, source.to_snapshot())
        return source

    def _command(self, source, *, trigger=JvmExecutionAttemptTrigger.PROFILE_VALIDATION):
        scala = source.target_selection.target is ExecutionTarget.JVM_SCALA
        family, image = (
            ("sbt", self.config.sbt_image_id) if scala else ("gradle", self.config.gradle_image_id)
        )
        runner = (create_sbt_jvm_runner_contract if scala else create_gradle_jvm_runner_contract)(
            ContainerImageReference(f"orchestwin/jvm-{family}-runner@{image}")
        )
        scope = jvm_scope_for(source.target_selection.target)
        return JvmExecutionStartCommand(
            source.id,
            scope.profile_id,
            scope.profile_version,
            runner.execution_policy.content_hash,
            runner.image.digest,
            JvmExecutionPurpose.PROFILE_VALIDATION,
            trigger,
            None,
            None
            if trigger is JvmExecutionAttemptTrigger.PROFILE_VALIDATION
            else tuple(JvmExecutionPhase),
        )

    async def _approve(self, operation):
        if operation["state"] == "PENDING" and operation["gate"]["status"] != "APPROVED":
            return await self.operations.decide(
                owner_user_id=self.owner,
                project_id=UUID(operation["project_id"]),
                operation_id=UUID(operation["id"]),
                expected_hash=operation["content_hash"],
                expected_event_sequence=operation["gate"]["event_sequence"],
                action=HumanGateAction.APPROVE,
                reason="Owner authorized the bounded JVM Level D fixture campaign.",
            )
        return operation

    async def execute(
        self, source, directory, *, trigger=JvmExecutionAttemptTrigger.PROFILE_VALIDATION
    ):
        command = self._command(source, trigger=trigger)
        prepared_path = directory / "prepared.json"
        if prepared_path.exists():
            prepared = json.loads(prepared_path.read_bytes())
            if prepared["payload"]["command"] != execution_command_snapshot(command):
                raise ValueError("JVM_CAMPAIGN_PREPARED_COMMAND_MISMATCH")
        else:
            result = await self.service.prepare_execution(
                owner_user_id=self.owner, project_id=source.project_id, command=command
            )
            if result.status.value != "EXECUTION_PREPARED":
                raise ValueError(result.message)
            prepared = result.snapshot
            write_once(prepared_path, prepared)
        current = await self.operations.get(
            owner_user_id=self.owner,
            project_id=source.project_id,
            operation_id=UUID(prepared["id"]),
        )
        approved = await self._approve(current)
        if not (directory / "approved.json").exists():
            write_once(directory / "approved.json", approved)
        result = await self.service.start_execution(
            owner_user_id=self.owner,
            project_id=source.project_id,
            command=replace(command, authorization_id=UUID(prepared["id"])),
        )
        if result.status.value != "EXECUTION_RECORDED":
            raise ValueError(result.message)
        write_once(directory / "attempt.json", result.snapshot)
        terminal = await self.operations.get(
            owner_user_id=self.owner,
            project_id=source.project_id,
            operation_id=UUID(prepared["id"]),
        )
        write_once(directory / "terminal.json", terminal)
        return result.snapshot

    async def repair(self, source, attempt, directory):
        prepared_path = directory / "prepared.json"
        if prepared_path.exists():
            proposal = json.loads(prepared_path.read_bytes())
        else:
            original = fixture_bytes(self.config.repo_root, source.target_selection.target)
            changes = tuple(
                JvmRepairChangeCommand(
                    JvmSourceChangeOperation.REPLACE,
                    item.normalized_path,
                    original[item.normalized_path].decode(),
                    "text/plain",
                )
                for item in source.files
                if original[item.normalized_path]
                != (self.backend.content_root / item.storage_key).read_bytes()
            )
            result = await self.repairs.create_repair_proposal(
                owner_user_id=self.owner,
                execution_id=UUID(attempt["id"]),
                command=JvmRepairProposalCreateCommand(
                    source.content_hash,
                    attempt["report"]["failure_signatures"][0]["signature"],
                    changes,
                    "Restore the reviewed fixture after the intentional compiler failure.",
                ),
            )
            if result.status.value != "REPAIR_PROPOSED":
                raise ValueError(result.message)
            proposal = result.snapshot
            write_once(prepared_path, proposal)
        current = await self.operations.get(
            owner_user_id=self.owner,
            project_id=source.project_id,
            operation_id=UUID(proposal["id"]),
        )
        if current["state"] != "COMPLETED":
            approved = await self._approve(current)
            write_once(directory / "approved.json", approved)
            result = await self.repairs.apply_repair_proposal(
                owner_user_id=self.owner,
                execution_id=UUID(attempt["id"]),
                proposal_id=UUID(proposal["id"]),
                command=JvmRepairProposalApplyCommand(
                    source.content_hash, proposal["content_hash"], UUID(proposal["gate"]["id"])
                ),
            )
            if result.status.value != "REPAIR_APPLIED":
                raise ValueError(result.message)
            current = await self.operations.get(
                owner_user_id=self.owner,
                project_id=source.project_id,
                operation_id=UUID(proposal["id"]),
            )
        write_once(directory / "terminal.json", current)
        async with self.sessions() as session:
            revision = await SqlAlchemyJvmSourceRevisionRepository(
                session, owner_user_id=self.owner
            ).current(project_id=source.project_id)
            if revision.to_snapshot() != current["result"]["source_revision"]:
                raise ValueError("JVM_CAMPAIGN_REPAIR_PERSISTENCE_MISMATCH")
            return revision

    async def run(self, *, owner_approved=False, progress=print):
        if owner_approved is not True:
            raise ValueError("JVM_CAMPAIGN_OWNER_APPROVAL_REQUIRED")
        manifest = await self.prepare()
        for target in self.targets:
            for case in CASES:
                source = await self._source(manifest, target, case)
                directory = self.root / target.value / case
                progress(f"{target.value} {case}: executing governed fixture")
                attempt = await self.execute(source, directory / "initial")
                if case == "positive":
                    if attempt["report"]["status"] != "PASSED":
                        raise ValueError("JVM_CAMPAIGN_POSITIVE_FAILED")
                    repeated = await self.execute(
                        source,
                        directory / "repeat",
                        trigger=JvmExecutionAttemptTrigger.MANUAL_RERUN,
                    )
                    if repeated["report"]["status"] != "PASSED":
                        raise ValueError("JVM_CAMPAIGN_REPRODUCIBILITY_FAILED")
                elif case == "compile_failure":
                    if attempt["report"]["status"] != "FAILED":
                        raise ValueError("JVM_CAMPAIGN_EXPECTED_COMPILER_FAILURE_MISSING")
                    repaired = await self.repair(source, attempt, directory / "repair")
                    rerun = await self.execute(
                        repaired,
                        directory / "rerun",
                        trigger=JvmExecutionAttemptTrigger.REPAIR_RERUN,
                    )
                    if rerun["report"]["status"] != "PASSED":
                        raise ValueError("JVM_CAMPAIGN_REPAIR_RERUN_FAILED")
                elif attempt["report"]["status"] != "FAILED":
                    raise ValueError("JVM_CAMPAIGN_EXPECTED_FAILURE_MISSING")
                progress(f"{target.value} {case}: evidence recorded")
        return manifest

    async def export_database(self, target):
        """Retain the authoritative SQL history of this campaign's five projects only."""
        if target not in self.targets:
            raise ValueError("JVM_CAMPAIGN_TARGET_NOT_PREPARED")
        manifest = await self.prepare()
        projects = []
        for case in CASES:
            source = await self._source(manifest, target, case)
            async with self.sessions() as session:
                sources = await SqlAlchemyJvmSourceRevisionRepository(
                    session, owner_user_id=self.owner
                ).history(project_id=source.project_id)
                attempts = await SqlAlchemyJvmExecutionAttemptRepository(
                    session, owner_user_id=self.owner
                ).history(project_id=source.project_id)
            operations = await self.operations.history(
                owner_user_id=self.owner, project_id=source.project_id
            )
            projects.append(
                {
                    "project_id": str(source.project_id),
                    "sources": [item.to_snapshot() for item in sources],
                    "attempts": [item.to_snapshot() for item in attempts],
                    "operations": list(operations),
                }
            )
        project_ids = [UUID(project["project_id"]) for project in projects]
        async with self.sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(HumanGateEventRecord.__table__)
                        .join(ProjectRecord, ProjectRecord.id == HumanGateEventRecord.project_id)
                        .where(
                            ProjectRecord.owner_user_id == self.owner,
                            HumanGateEventRecord.project_id.in_(project_ids),
                            HumanGateEventRecord.gate_type == "HIGH_IMPACT_OPERATION",
                        )
                        .order_by(
                            HumanGateEventRecord.gate_id, HumanGateEventRecord.sequence_number
                        )
                    )
                )
                .mappings()
                .all()
            )
        events = [
            {
                key: value.isoformat()
                if isinstance(value, datetime)
                else str(value)
                if isinstance(value, UUID)
                else value
                for key, value in row.items()
            }
            for row in rows
        ]
        return {
            "owner_id": str(self.owner),
            "target": target.value,
            "projects": projects,
            "gate_events": events,
        }
