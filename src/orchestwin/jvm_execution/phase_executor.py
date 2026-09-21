"""Per-attempt JVM workflow adapter with verified sources and retained evidence.

Authorization belongs to the workflow. This adapter accepts only full execution
scopes because every attempt starts with new source, launcher and dependency caches.
Evidence storage must live outside the temporary workspace tree.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.jvm_execution.dependency_network import verify_dependency_network
from orchestwin.jvm_execution.evidence import (
    JvmEvidenceReference,
    JvmFailureCategory,
    JvmPhaseResult,
    JvmPhaseResultStatus,
    normalize_jvm_message,
)
from orchestwin.jvm_execution.gradle_evidence import parse_gradle_and_junit_evidence
from orchestwin.jvm_execution.phase_runtime import LocalJvmPhaseRuntime
from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.runtime_artifacts import (
    JvmArtifactKind,
    collect_jvm_artifact_inventory,
)
from orchestwin.jvm_execution.sbt_evidence import parse_sbt_and_scala_test_evidence
from orchestwin.jvm_execution.targets import JvmBuildSystem
from orchestwin.jvm_execution.workspaces import (
    prepare_jvm_phase_workspace,
    require_jvm_workspace_owner,
)
from orchestwin.sandbox.docker_runtime import HostProcessStatus
from orchestwin.sandbox.evidence import SandboxLogStream

_CATEGORY = dict(
    zip(
        JvmExecutionPhase,
        (
            JvmFailureCategory.VALIDATION,
            JvmFailureCategory.DEPENDENCY_INSTALL,
            JvmFailureCategory.STATIC_CHECK,
            JvmFailureCategory.BUILD,
            JvmFailureCategory.TEST,
            JvmFailureCategory.RUNTIME,
            JvmFailureCategory.ARTIFACT_COLLECTION,
        ),
        strict=True,
    )
)


def _json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _reference(value, media_type="text/plain"):
    return JvmEvidenceReference(
        value.storage_key, value.sha256_digest, value.size_bytes, media_type
    )


class _CaptureStore:
    def __init__(self, store):
        self.store = store
        self.junit = []

    def store_artifact(self, **arguments):
        path = arguments["normalized_path"]
        if path.endswith(".xml") and (
            "/test-results/" in f"/{path}" or "/test-reports/" in f"/{path}"
        ):
            self.junit.append(arguments["content"])
        return self.store.store_artifact(**arguments)


class GovernedJvmPhaseExecutor:
    """Supply both phase_executor and lifecycle to LocalGovernedJvmExecutionService."""

    def __init__(
        self,
        *,
        contract,
        source_revision,
        snapshot,
        source_path,
        workspaces_root,
        evidence_store,
        docker_context,
        distribution_path=None,
        dependency_network_manifest=None,
        dependency_network_manifest_hash=None,
        runtime_factory=LocalJvmPhaseRuntime,
    ):
        if (
            source_revision.reference != contract.source_revision
            or source_revision.target_selection != contract.validation.selection
        ):
            raise ValueError("JVM_EXECUTOR_SOURCE_BINDING_MISMATCH")
        if snapshot.inventory_content_hash != contract.validation.inventory_content_hash:
            raise ValueError("JVM_EXECUTOR_SNAPSHOT_BINDING_MISMATCH")
        self.contract, self.revision, self.snapshot = contract, source_revision, snapshot
        self.source_path, self.root, self.store = source_path, workspaces_root, evidence_store
        self.context, self.distribution = docker_context, distribution_path
        self.manifest, self.manifest_hash = (
            dependency_network_manifest,
            dependency_network_manifest_hash,
        )
        self.runtime_factory = runtime_factory
        self.attempt_id = self.workspace = self.runtime = None
        self.finalization_reference = None
        self._next = 0
        self._failed = self._busy = self._finalized = False

    def bind_attempt(self, attempt_id: UUID, *, contract, phases_to_execute):
        if (
            self.attempt_id is not None
            or not isinstance(attempt_id, UUID)
            or contract != self.contract
        ):
            raise ValueError("JVM_EXECUTOR_ATTEMPT_BINDING_INVALID")
        if phases_to_execute != tuple(JvmExecutionPhase):
            raise ValueError("JVM_EXECUTOR_FRESH_CACHE_REQUIRES_ALL_PHASES")
        require_jvm_workspace_owner()
        self.attempt_id = attempt_id

    def _artifact(self, name, payload):
        return _reference(
            self.store.store_artifact(
                run_id=self.attempt_id,
                command_id="jvm.phase",
                normalized_path=name,
                content=_json(payload),
                media_type="application/json",
            ),
            "application/json",
        )

    def _identity(self):
        return {
            "schema_version": 1,
            "execution_attempt_id": str(self.attempt_id),
            "contract_hash": self.contract.content_hash,
            "source_revision_content_hash": self.revision.content_hash,
            "source_tree_hash": self.revision.source_tree_hash,
            "execution_plan_content_hash": self.contract.execution_plan.content_hash,
            "policy_hash": self.contract.runner.execution_policy.content_hash,
            "image_id": f"sha256:{self.contract.runner.image.digest}",
            "image_id_kind": "LOCAL_CONFIG_DIGEST",
            "level_d_validated": False,
        }

    async def execute(self, phase_plan, *, contract):
        if (
            self.attempt_id is None
            or self._busy
            or self._failed
            or self._finalized
            or self._next >= len(JvmExecutionPhase)
            or phase_plan.phase is not tuple(JvmExecutionPhase)[self._next]
            or contract != self.contract
            or phase_plan != contract.execution_plan.phase(phase_plan.phase)
        ):
            raise ValueError("JVM_EXECUTOR_PHASE_BINDING_INVALID")
        self._busy = True
        try:
            if self.workspace is None:
                self.workspace = prepare_jvm_phase_workspace(
                    revision=self.revision,
                    snapshot=self.snapshot,
                    source_path=self.source_path,
                    workspaces_root=self.root,
                    attempt_id=self.attempt_id,
                    distribution_path=self.distribution,
                )
                self.runtime = self.runtime_factory(
                    attempt_id=self.attempt_id,
                    execution_plan=contract.execution_plan,
                    runner_contract=contract.runner,
                    workspace=self.workspace.path,
                    docker_context=self.context,
                    dependency_network_manifest=self.manifest,
                    dependency_network_manifest_hash=self.manifest_hash,
                )
            network = None
            if phase_plan.phase is JvmExecutionPhase.SETUP:
                if self.manifest is None:
                    raise ValueError("JVM_EXECUTOR_CONTROLLED_NETWORK_REQUIRED")
                network = await verify_dependency_network(
                    self.manifest,
                    expected_content_hash=self.manifest_hash,
                    docker_context=self.context,
                )
            self.workspace.configure(network)
            observed = await self.runtime.run_phase(phase_plan.phase)
            if (
                observed.attempt_id != self.attempt_id
                or observed.phase is not phase_plan.phase
                or observed.command_plan_hash != phase_plan.command_plan.content_hash
                or observed.image_id != f"sha256:{contract.runner.image.digest}"
                or observed.cleanup_confirmed is not True
                or type(observed.oom_killed) is not bool
                or (
                    observed.process.status is HostProcessStatus.COMPLETED
                    and observed.container_exit_code != observed.process.exit_code
                )
                or observed.network_id != (network.network_id if network else "none")
                or observed.dependency_network_manifest_hash
                != (self.manifest_hash if network else None)
            ):
                raise ValueError("JVM_EXECUTOR_OBSERVATION_BINDING_MISMATCH")
            result = self._result(phase_plan, observed)
            self._failed = result.is_failure
            self._next += 1
            return result
        except BaseException as error:
            self._failed = True
            process = getattr(error, "command_result", None)
            logs = self._logs(phase_plan, process) if process is not None else ()
            self._artifact(
                f"{phase_plan.phase.value.lower()}-interrupted.json",
                {
                    **self._identity(),
                    "phase": phase_plan.phase.value,
                    "command_plan_hash": phase_plan.command_plan.content_hash,
                    "exception_type": type(error).__name__,
                    "logs": [reference.to_snapshot() for reference in logs],
                    "phase_result_recorded": False,
                },
            )
            raise
        finally:
            self._busy = False

    def _logs(self, plan, process):
        return tuple(
            _reference(
                self.store.store_log(
                    run_id=self.attempt_id,
                    command_id=plan.command_plan.commands[0].command_id,
                    stream=stream,
                    content=content,
                )
            )
            for stream, content in (
                (SandboxLogStream.STDOUT, process.stdout),
                (SandboxLogStream.STDERR, process.stderr),
            )
        )

    def _result(self, plan, observed):
        process, phase = observed.process, plan.phase
        stdout, stderr = self._logs(plan, process)
        status, category, code = JvmPhaseResultStatus.PASSED, None, None
        if process.status is HostProcessStatus.TIMED_OUT:
            status, category, code = (
                JvmPhaseResultStatus.TIMED_OUT,
                JvmFailureCategory.TIMEOUT,
                "JVM_COMMAND_TIMEOUT",
            )
        elif observed.oom_killed or process.status is HostProcessStatus.OUTPUT_LIMIT_EXCEEDED:
            status, category, code = (
                JvmPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
                JvmFailureCategory.RESOURCE_LIMIT,
                "JVM_OOM_KILLED" if observed.oom_killed else "JVM_OUTPUT_LIMIT_EXCEEDED",
            )
        elif process.status is not HostProcessStatus.COMPLETED:
            status, category, code = (
                JvmPhaseResultStatus.RUNTIME_ERROR,
                JvmFailureCategory.RUNTIME,
                "JVM_TRANSPORT_FAILED",
            )
        elif process.exit_code != 0:
            status, category, code = (
                JvmPhaseResultStatus.FAILED,
                _CATEGORY[phase],
                "JVM_COMMAND_FAILED",
            )
        references, findings, inventory, parsed = [], (), None, None
        capture = _CaptureStore(self.store)
        evidence_error = None
        try:
            if phase in {
                JvmExecutionPhase.BUILD,
                JvmExecutionPhase.TEST,
                JvmExecutionPhase.COLLECT_ARTIFACTS,
            }:
                inventory = collect_jvm_artifact_inventory(
                    self.contract,
                    workspace_path=self.workspace.path,
                    run_id=self.attempt_id,
                    command_id=plan.command_plan.commands[0].command_id,
                    evidence_store=capture,
                )
                references.extend(
                    _reference(item.reference, item.reference.media_type)
                    for item in inventory.artifacts
                )
                if phase is JvmExecutionPhase.BUILD and not any(
                    item.kind is JvmArtifactKind.APPLICATION_JAR for item in inventory.artifacts
                ):
                    raise ValueError("JVM_APPLICATION_JAR_MISSING")
        except (OSError, ValueError) as error:
            evidence_error = type(error).__name__
            if category is None:
                status, category, code = (
                    JvmPhaseResultStatus.RUNTIME_ERROR,
                    JvmFailureCategory.ARTIFACT_COLLECTION,
                    "JVM_PHASE_EVIDENCE_INVALID",
                )
        # Parse actual logs even when a failed build produced no artifacts.
        try:
            parser = (
                parse_gradle_and_junit_evidence
                if self.revision.target_selection.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL
                else parse_sbt_and_scala_test_evidence
            )
            parsed = parser(
                process.stdout.decode("utf-8", errors="replace")
                + "\n"
                + process.stderr.decode("utf-8", errors="replace"),
                junit_xml_documents=tuple(capture.junit) if phase is JvmExecutionPhase.TEST else (),
            )
            findings = parsed.findings
            if parsed.build_failed and category is None:
                status, category, code = (
                    JvmPhaseResultStatus.FAILED,
                    _CATEGORY[phase],
                    "JVM_TOOL_REPORTED_FAILURE",
                )
            if (
                phase is JvmExecutionPhase.TEST
                and parsed.test_summary.total == parsed.test_summary.skipped
            ):
                raise ValueError("JVM_EXECUTED_TEST_CASES_MISSING")
        except (OSError, ValueError) as error:
            evidence_error = type(error).__name__
            if category is None:
                status, category, code = (
                    JvmPhaseResultStatus.RUNTIME_ERROR,
                    JvmFailureCategory.ARTIFACT_COLLECTION,
                    "JVM_PHASE_EVIDENCE_INVALID",
                )
        summary = (
            f"JVM {phase.value} completed."
            if code is None
            else f"JVM {phase.value} failed: {code}."
        )
        if status is JvmPhaseResultStatus.FAILED and parsed is not None:
            failure_cases = [case for case in parsed.test_summary.cases if case.message is not None]
            blocking = [
                finding for finding in findings if not finding.code.endswith(("_WARNING", "_W"))
            ]
            blocking.sort(key=lambda finding: (finding.code.startswith("GRADLE_"), finding.code))
            if failure_cases:
                code = "JVM_TEST_CASE_FAILED"
                summary = normalize_jvm_message(failure_cases[0].message)
            elif blocking:
                code = blocking[0].code
                summary = normalize_jvm_message(blocking[0].message)
        metadata = self._artifact(
            f"{phase.value.lower()}-execution.json",
            {
                **self._identity(),
                "phase_plan": plan.to_snapshot(),
                "container_id": observed.container_id,
                "network_id": observed.network_id,
                "network_manifest_hash": observed.dependency_network_manifest_hash,
                "transport_status": process.status.value,
                "container_exit_code": observed.container_exit_code,
                "oom_killed": observed.oom_killed,
                "container_cleanup_confirmed": observed.cleanup_confirmed,
                "started_at": observed.started_at.isoformat(),
                "completed_at": observed.completed_at.isoformat(),
                "resources": self.contract.runner.resources.to_snapshot(),
                "stdout": stdout.to_snapshot(),
                "stderr": stderr.to_snapshot(),
                "artifacts": None if inventory is None else inventory.to_snapshot(),
                "parsed_evidence": None if parsed is None else parsed.to_snapshot(),
                "evidence_error_type": evidence_error,
                "launcher_seed": None
                if self.workspace.seed_receipt is None
                else {
                    **dataclasses.asdict(self.workspace.seed_receipt),
                    "attempt_id": str(self.attempt_id),
                },
            },
        )
        references.append(metadata)
        return JvmPhaseResult(
            phase=phase,
            status=status,
            command_plan_hash=plan.command_plan.content_hash,
            started_at=observed.started_at,
            completed_at=observed.completed_at,
            exit_codes=() if process.exit_code is None else (process.exit_code,),
            stdout_refs=(stdout,),
            stderr_refs=(stderr,),
            artifact_refs=tuple(sorted(set(references))),
            findings=findings,
            failure_category=category,
            failure_code=code,
            normalized_summary=summary,
        )

    async def finalize(self):
        if self._busy or self.attempt_id is None:
            raise ValueError("JVM_EXECUTOR_FINALIZATION_INVALID")
        if self._finalized:
            return
        # Never delete a mounted workspace if the transport cannot confirm cleanup.
        if self.runtime is not None:
            await self.runtime.close()
        if self.workspace is not None:
            self.workspace.close()
        self.finalization_reference = self._artifact(
            "finalization.json",
            {
                **self._identity(),
                "containers_removed": True,
                "workspace_removed": True,
                "dependency_network_disposition": "CALLER_OWNED_NOT_REMOVED",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        self._finalized = True
