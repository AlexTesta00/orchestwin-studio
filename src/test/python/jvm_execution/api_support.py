"""Pinned fixture sources for API tests; no Docker or database access on import."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestwin.api.governed_jvm_context import GovernedJvmSettings, JvmExecutionBackend
from orchestwin.api.jvm_execution import JvmExecutionStartCommand
from orchestwin.artifacts.jvm_source_plans import FileSystemJvmSourceContentStore
from orchestwin.artifacts.jvm_sources import (
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    create_jvm_source_revision,
)
from orchestwin.jvm_execution.attempts import JvmExecutionAttemptTrigger
from orchestwin.jvm_execution.gradle_runner import create_gradle_jvm_runner_contract
from orchestwin.jvm_execution.sbt_runner import create_sbt_jvm_runner_contract
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.workflow.jvm_execution import JvmExecutionPurpose

ROOT = Path(__file__).parents[4]
TARGETS = (ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA)


def fixture_context(tmp_path, target=ExecutionTarget.JVM_KOTLIN, *, configuration=None):
    config = configuration or GovernedJvmSettings(
        _env_file=None,
        enabled=True,
        repo_root=ROOT,
        workspaces_root=tmp_path / "workspaces",
        distribution_path=tmp_path / "distribution.zip",
        dependency_network_manifest=tmp_path / "network.json",
        dependency_network_manifest_hash="d" * 64,
        gradle_image_id="sha256:" + "b" * 64,
        sbt_image_id="sha256:" + "c" * 64,
    )
    backend = JvmExecutionBackend(
        config=config, content_root=tmp_path / "objects", evidence_root=tmp_path / "evidence"
    )
    fixture = (
        ROOT
        / "src/test/fixtures/jvm_execution"
        / {
            ExecutionTarget.JVM_JAVA: "jvm-java-greeting",
            ExecutionTarget.JVM_KOTLIN: "jvm-kotlin-calculator",
            ExecutionTarget.JVM_SCALA: "jvm-scala-greeting",
        }[target]
    )
    manifest = json.loads((fixture / "fixture.json").read_text())
    store = FileSystemJvmSourceContentStore(backend.content_root)
    revision = create_jvm_source_revision(
        revision_id=uuid4(),
        project_id=uuid4(),
        created_by_user_id=uuid4(),
        version_number=1,
        based_on=None,
        target=target,
        origin=JvmSourceOrigin.DETERMINISTIC_FIXTURE,
        files=tuple(
            store.store(
                normalized_path=path,
                content=(fixture / path).read_bytes(),
                media_type="application/octet-stream",
            )
            for path in manifest["source_paths"]
        ),
        provenance_references=(
            JvmSourceProvenanceReference(
                JvmSourceProvenanceKind.SOURCE_PLAN, "api.fixture", 1, "a" * 64
            ),
        ),
        created_at=datetime.now(UTC),
    )
    scala = target is ExecutionTarget.JVM_SCALA
    image = config.sbt_image_id if scala else config.gradle_image_id
    runner = (create_sbt_jvm_runner_contract if scala else create_gradle_jvm_runner_contract)(
        ContainerImageReference(f"orchestwin/jvm-{'sbt' if scala else 'gradle'}-runner@{image}")
    )
    scope = jvm_scope_for(target)
    command = JvmExecutionStartCommand(
        revision.id,
        scope.profile_id,
        scope.profile_version,
        runner.execution_policy.content_hash,
        runner.image.digest,
        JvmExecutionPurpose.PROFILE_VALIDATION,
        JvmExecutionAttemptTrigger.PROFILE_VALIDATION,
        None,
        None,
    )
    return backend, revision, command
