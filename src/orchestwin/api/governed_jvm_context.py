"""Trusted JVM preparation and per-attempt Docker composition; disabled by default."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.jvm_execution.detection import JvmDetectionSnapshot, JvmTextFile
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.launcher_cache import GRADLE_DISTRIBUTION_SHA256
from orchestwin.jvm_execution.phase_executor import GovernedJvmPhaseExecutor
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.source_policy import (
    SOURCE_POLICY_HASH,
    SOURCE_POLICY_SCOPE,
    read_source_objects,
    verify_source_policy,
)
from orchestwin.jvm_execution.workspaces import read_regular_file, regular_path
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.evidence_store import FileSystemSandboxEvidenceStore
from orchestwin.workflow.jvm_execution import (
    JvmExecutionRequest,
    LocalGovernedJvmExecutionService,
    _rerun_issue,
)


class GovernedJvmSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_GOVERNED_JVM_", env_file=".env", extra="ignore", frozen=True
    )
    enabled: bool = False
    repo_root: Path | None = None
    workspaces_root: Path | None = None
    distribution_path: Path | None = None
    dependency_network_manifest: Path | None = None
    dependency_network_manifest_hash: str | None = None
    gradle_image_id: str | None = None
    sbt_image_id: str | None = None
    docker_context: str = "desktop-linux"

    @model_validator(mode="after")
    def trusted_configuration(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", self.docker_context):
            raise ValueError("JVM_DOCKER_CONTEXT_INVALID")
        if self.enabled:
            for path in (
                self.repo_root,
                self.workspaces_root,
                self.distribution_path,
                self.dependency_network_manifest,
            ):
                if path is None or not path.is_absolute() or ".." in path.parts:
                    raise ValueError("JVM_TRUSTED_ABSOLUTE_PATH_REQUIRED")
            for image in (self.gradle_image_id, self.sbt_image_id):
                if image is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
                    raise ValueError("JVM_PINNED_LOCAL_IMAGE_REQUIRED")
            if self.dependency_network_manifest_hash is None or not re.fullmatch(
                r"[0-9a-f]{64}", self.dependency_network_manifest_hash
            ):
                raise ValueError("JVM_PINNED_NETWORK_RECEIPT_REQUIRED")
        return self


@dataclass(frozen=True)
class PreparedApiJvmExecution:
    revision: object
    command: object
    registry: object
    snapshot: object
    contract: object
    request: JvmExecutionRequest
    payload: dict


@dataclass
class JvmExecutionProgress:
    cleanup_confirmed: bool = False
    finalization_reference: object | None = None


class _Clock:
    def now(self):
        return datetime.now(UTC)


class _AttemptId:
    def __init__(self, value):
        self.value = value

    def new_id(self):
        return self.value


def execution_command_snapshot(command):
    return {
        "source_revision_id": str(command.source_revision_id),
        "profile_id": command.profile_id,
        "profile_version": command.profile_version,
        "policy_content_hash": command.policy_content_hash,
        "runner_image_digest": command.runner_image_digest,
        "purpose": command.purpose.value,
        "trigger": command.trigger.value,
        "rerun_phases": None
        if command.rerun_phases is None
        else [p.value for p in command.rerun_phases],
    }


class JvmExecutionBackend:
    def __init__(
        self, *, config, content_root, evidence_root, executor_factory=GovernedJvmPhaseExecutor
    ):
        self.config = config
        self.content_root, self.evidence_root = (
            Path(content_root).absolute(),
            Path(evidence_root).absolute(),
        )
        self.executor_factory = executor_factory

    def prepare(self, revision, *, command, registry, previous):
        if not self.config.enabled:
            raise ValueError("JVM_EXECUTION_RUNTIME_DISABLED")
        roots = (self.content_root, self.evidence_root, self.config.workspaces_root)
        for path in (
            *roots,
            self.config.repo_root,
            self.config.distribution_path,
            self.config.dependency_network_manifest,
        ):
            regular_path(path)
        if any(
            a == b or a in b.parents or b in a.parents
            for i, a in enumerate(roots)
            for b in roots[i + 1 :]
        ):
            raise ValueError("JVM_EXECUTION_STORAGE_ROOTS_OVERLAP")
        if command.source_revision_id != revision.id:
            raise ValueError("JVM_EXECUTION_SOURCE_MISMATCH")
        # No hidden widening: callers must approve all phases for fresh caches.
        if command.rerun_phases not in (None, tuple(JvmExecutionPhase)):
            raise ValueError("JVM_FRESH_CACHE_REQUIRES_ALL_PHASES")
        contents = read_source_objects(revision, self.content_root)
        declaration = verify_source_policy(revision, contents, repo_root=self.config.repo_root)
        text_files = []
        for path, content in sorted(contents.items()):
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            text_files.append(JvmTextFile(path, text, hashlib.sha256(content).hexdigest()))
        snapshot = JvmDetectionSnapshot(
            revision.source_tree_hash, tuple(sorted(contents)), tuple(text_files)
        )
        profile = registry.find(command.profile_id, command.profile_version)
        if profile is None or profile.scope.target != revision.target_selection.target:
            raise ValueError("JVM_EXECUTION_PROFILE_MISMATCH")
        scala = revision.target_selection.target.value == "JVM_SCALA"
        image = self.config.sbt_image_id if scala else self.config.gradle_image_id
        family = "sbt" if scala else "gradle"
        runner = (create_sbt_jvm_runner_contract if scala else create_gradle_jvm_runner_contract)(
            ContainerImageReference(f"orchestwin/jvm-{family}-runner@{image}")
        )
        runner = replace(
            runner,
            capability_status=profile.scope.capability_status,
            validation_evidence_refs=profile.scope.validation_evidence_refs,
        )
        if (
            command.runner_image_digest != runner.image.digest
            or command.policy_content_hash != runner.execution_policy.content_hash
        ):
            raise ValueError("JVM_EXECUTION_RUNNER_OR_POLICY_MISMATCH")
        contract = profile.create_contract(
            snapshot, declaration, source_revision=revision.reference, runner=runner
        )
        request = JvmExecutionRequest(
            project_id=revision.project_id,
            owner_user_id=revision.created_by_user_id,
            source_revision=revision.reference,
            snapshot=snapshot,
            declaration=declaration,
            profile_id=command.profile_id,
            profile_version=command.profile_version,
            runner=runner,
            policy_content_hash=command.policy_content_hash,
            purpose=command.purpose,
            trigger=command.trigger,
            authorization=None,
            rerun_phases=command.rerun_phases,
        )
        if _rerun_issue(request, current=previous):
            raise ValueError("JVM_EXECUTION_RERUN_INVALID")
        if previous is None and command.trigger.value != (
            "PROFILE_VALIDATION" if command.purpose.value == "PROFILE_VALIDATION" else "INITIAL"
        ):
            raise ValueError("JVM_EXECUTION_TRIGGER_INVALID")
        payload = {
            "schema_version": 1,
            "purpose": command.purpose.value,
            "command": execution_command_snapshot(command),
            "source_revision": revision.reference.to_snapshot(),
            "source_tree_hash": revision.source_tree_hash,
            "contract": contract.to_snapshot(),
            "source_policy_hash": SOURCE_POLICY_HASH,
            "source_policy_scope": SOURCE_POLICY_SCOPE,
            "runner_image_id": image,
            "image_id_kind": "LOCAL_CONFIG_DIGEST",
            "docker_context": self.config.docker_context,
            "distribution_sha256": None if scala else GRADLE_DISTRIBUTION_SHA256,
            "network_manifest_hash": self.config.dependency_network_manifest_hash,
            "previous_attempt": None
            if previous is None
            else {"id": str(previous.id), "content_hash": previous.content_hash},
            "effective_phases": [p.value for p in JvmExecutionPhase],
        }
        return PreparedApiJvmExecution(
            revision, command, registry, snapshot, contract, request, payload
        )

    async def execute(self, context, *, operation, authorization, attempts, progress):
        root = self.config.workspaces_root
        regular_path(root)
        root.mkdir(parents=True, exist_ok=True)
        executor = None
        input_path = None
        try:
            # This input directory is never mounted; only the executor's verified copy is.
            with tempfile.TemporaryDirectory(prefix="api-jvm-input-", dir=root) as name:
                input_path = Path(name)
                source = Path(name) / "source"
                source.mkdir()
                for path, content in read_source_objects(
                    context.revision, self.content_root
                ).items():
                    target = source / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                executor = self.executor_factory(
                    contract=context.contract,
                    source_revision=context.revision,
                    snapshot=context.snapshot,
                    source_path=source,
                    workspaces_root=root / "mutable",
                    evidence_store=FileSystemSandboxEvidenceStore(self.evidence_root),
                    docker_context=self.config.docker_context,
                    distribution_path=self.config.distribution_path,
                    dependency_network_manifest=self.config.dependency_network_manifest,
                    dependency_network_manifest_hash=self.config.dependency_network_manifest_hash,
                )
                service = LocalGovernedJvmExecutionService(
                    registry=context.registry,
                    attempts=attempts,
                    phase_executor=executor,
                    lifecycle=executor,
                    clock=_Clock(),
                    ids=_AttemptId(operation.id),
                )
                result = await service.execute(
                    replace(context.request, authorization=authorization)
                )
            progress.finalization_reference = executor.finalization_reference
            progress.cleanup_confirmed = progress.finalization_reference is not None
            return result
        except BaseException:
            # Leaving TemporaryDirectory must succeed before resources are considered released.
            progress.finalization_reference = (
                None if executor is None else executor.finalization_reference
            )
            progress.cleanup_confirmed = (
                executor is None or progress.finalization_reference is not None
            ) and (input_path is None or not input_path.exists())
            raise

    def verify_finalization(self, operation, snapshot, reference):
        from orchestwin.jvm_execution.evidence import JvmEvidenceReference

        ref = JvmEvidenceReference(**reference)
        if (
            ref.storage_key != f"sha256/{ref.sha256_digest[:2]}/{ref.sha256_digest}"
            or ref.media_type != "application/json"
        ):
            raise ValueError("JVM_FINALIZATION_REFERENCE_INVALID")
        data = read_regular_file(self.evidence_root / ref.storage_key, maximum_bytes=8192)
        if len(data) != ref.size_bytes or hashlib.sha256(data).hexdigest() != ref.sha256_digest:
            raise ValueError("JVM_FINALIZATION_REFERENCE_INVALID")
        receipt = json.loads(data)
        contract = operation.payload["contract"]
        if not (
            receipt["execution_attempt_id"] == str(operation.id) == snapshot["id"]
            and receipt["contract_hash"] == contract["content_hash"]
            and receipt["source_revision_content_hash"]
            == snapshot["source_revision"]["content_hash"]
            and receipt["execution_plan_content_hash"] == snapshot["execution_plan_content_hash"]
            and receipt["source_tree_hash"] == operation.payload["source_tree_hash"]
            and receipt["policy_hash"] == snapshot["policy_content_hash"]
            and receipt["image_id"] == operation.payload["runner_image_id"]
            and receipt["image_id_kind"] == "LOCAL_CONFIG_DIGEST"
            and receipt["dependency_network_disposition"] == "CALLER_OWNED_NOT_REMOVED"
            and receipt["containers_removed"] is True
            and receipt["workspace_removed"] is True
            and receipt["level_d_validated"] is False
        ):
            raise ValueError("JVM_FINALIZATION_BINDING_INVALID")
