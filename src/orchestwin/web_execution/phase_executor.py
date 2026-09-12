"""Execute validated Web phases against one immutable source revision.

This per-attempt adapter produces evidence. Browser evaluation is supplied through
an explicit port; profile promotion and API authorization remain separate concerns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestwin.sandbox.docker_runtime import HostProcessStatus
from orchestwin.sandbox.evidence import (
    SandboxCommandEvidence,
    SandboxCommandStatus,
    SandboxLogStream,
    SandboxRunStatus,
    create_sandbox_run_evidence,
)
from orchestwin.sandbox.execution_policy import validate_sandbox_plan
from orchestwin.web_execution.phase_health import probe_web_health
from orchestwin.web_execution.phase_runtime import LocalWebPhaseRuntime, WebPhaseRuntimeError
from orchestwin.web_execution.phase_workspace import prepare_phase_workspace
from orchestwin.web_execution.plans import (
    WebExecutionPhase,
    WebPhaseExecutionKind,
    create_structured_web_phase_plans,
)
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebFailureCategory,
    WebPhaseResult,
    WebPhaseResultStatus,
    create_web_no_op_phase_result,
    create_web_policy_blocked_phase_result,
    normalize_web_command_phase,
)
from orchestwin.web_execution.runtime_evidence import collect_web_artifacts
from orchestwin.web_execution.verified_browser_runner import read_regular


def _json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _reference(value, media_type="text/plain"):
    return WebEvidenceReference(
        value.storage_key, value.sha256_digest, value.size_bytes, media_type
    )


def _command_artifact_patterns(command):
    # Commands declare outputs relative to their working directory.
    return tuple(
        pattern if command.working_directory == "." else f"{command.working_directory}/{pattern}"
        for pattern in command.artifact_patterns
    )


class GovernedWebPhaseExecutor:
    """One governed attempt, with bounded runtime and idempotent finalization."""

    def __init__(
        self,
        *,
        contract,
        prepared_workspace,
        snapshot,
        lock_report,
        runner_identity,
        execution_policy,
        resources,
        workspaces_root: Path,
        evidence_store,
        docker_context: str,
        runtime_factory=None,
        controlled_network=None,
        browser_executor=None,
    ):
        self.contract = contract
        self.prepared = prepared_workspace
        self.snapshot, self.lock_report = snapshot, lock_report
        self.identity, self.policy, self.resources = runner_identity, execution_policy, resources
        self.root, self.store = Path(workspaces_root), evidence_store
        self.context = docker_context
        self.runtime_factory = runtime_factory or LocalWebPhaseRuntime
        self.network = controlled_network
        self.browser_executor = browser_executor
        self.run_id = uuid4()
        self.workspace = None
        self.runtime = None
        self._last_phase = -1
        self._failed = False
        self._final_result = None
        self._processes = {}
        self._runtime_observations = []
        self._health = []
        self._generated_artifacts = {}

    def _block(self, phase, code):
        return create_web_policy_blocked_phase_result(
            phase.phase,
            command_plan_hashes=tuple(plan.content_hash for plan in phase.command_plans),
            policy_issue_code=code,
            message=code.replace("_", " "),
        )

    def _verify(self, phase, contract):
        if contract != self.contract or phase != contract.execution_plan.phase(phase.phase):
            return "WEB_PHASE_CONTRACT_MISMATCH"
        expected = create_structured_web_phase_plans(
            self.snapshot, selection=contract.validation.selection, lock_report=self.lock_report
        )
        if expected != contract.execution_plan:
            return "WEB_PHASE_PLAN_NOT_CANONICAL"
        profile = create_sprint08_web_profile_registry().find(
            contract.validation.profile_id, contract.validation.profile_version
        )
        if profile is None:
            return "WEB_PHASE_PROFILE_UNAVAILABLE"
        checked = profile.create_contract(
            self.snapshot,
            selection=contract.validation.selection,
            lock_report=self.lock_report,
            source_revision_content_hash=contract.source_revision_content_hash,
            source_tree_hash=contract.source_tree_hash,
            runners=contract.runners,
        )
        if not contract.health_checks or contract.health_checks != checked.health_checks:
            return "WEB_HEALTH_CONTRACT_MISMATCH"
        if (
            self.identity.image_id != f"sha256:{contract.runners.execution_runner_image_digest}"
            or self.prepared.source_revision_content_hash != contract.source_revision_content_hash
            or self.prepared.source_tree_hash != contract.source_tree_hash
        ):
            return "WEB_PHASE_INPUT_IDENTITY_MISMATCH"
        kind = "PHP" if contract.validation.selection.target.value == "WEB_PHP" else "NODE"
        if self.identity.kind != kind:
            return "WEB_PHASE_RUNNER_KIND_MISMATCH"
        order = tuple(WebExecutionPhase)
        index = order.index(phase.phase)
        if self._final_result is not None or self._failed or index <= self._last_phase:
            return "WEB_PHASE_SESSION_ALREADY_FINISHED"
        if any(
            contract.execution_plan.phase(item).execution_kind is not WebPhaseExecutionKind.NO_OP
            for item in order[self._last_phase + 1 : index]
        ):
            return "WEB_PHASE_PREREQUISITE_MISSING"
        for plan in phase.command_plans:
            report = validate_sandbox_plan(plan, resources=self.resources, policy=self.policy)
            if not report.is_accepted:
                return "WEB_SANDBOX_POLICY_REJECTED"
            if (
                any(command.network_mode.value == "CONTROLLED" for command in plan.commands)
                and self.network is None
            ):
                return "WEB_CONTROLLED_NETWORK_UNAVAILABLE"
        return None

    def _metadata(self, phase, started, completed, **extra):
        return {
            "schema_version": 1,
            "attempt_runtime_id": str(self.run_id),
            "phase": phase.phase.value,
            "phase_plan": phase.to_snapshot(),
            "contract_hash": self.contract.content_hash,
            "source_revision_content_hash": self.contract.source_revision_content_hash,
            "source_tree_hash": self.contract.source_tree_hash,
            "image_id": self.identity.image_id,
            "image_id_kind": "LOCAL_CONFIG_DIGEST",
            "bootstrap_manifest_hash": self.identity.bootstrap_manifest_hash,
            "recipe_content_hash": self.identity.recipe_content_hash,
            "policy_hash": self.policy.content_hash,
            "resources": self.resources.to_snapshot(),
            "network_modes": sorted(
                {
                    command.network_mode.value
                    for plan in phase.command_plans
                    for command in plan.commands
                }
            )
            or ["DISABLED"],
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "level_d_validated": False,
            "generated_artifacts": [
                {"normalized_path": path, "reference": reference.to_snapshot()}
                for (path, _digest), reference in sorted(self._generated_artifacts.items())
            ],
            **extra,
        }

    def _artifact(self, name, content, media_type="application/json"):
        value = self.store.store_artifact(
            run_id=self.run_id,
            command_id="web.phase",
            normalized_path=name,
            content=content,
            media_type=media_type,
        )
        return _reference(value, media_type)

    def _runtime_failure_observation(self, error, *, command_id, plan_hash):
        typed = isinstance(error, WebPhaseRuntimeError)
        boundary = {
            "command_id": command_id,
            "command_plan_hash": plan_hash,
            "failure_code": str(error) if typed else "WEB_COMMAND_RUNTIME_ERROR",
            "error_type": type(error).__name__,
            "command_result_observed": typed and error.command_result is not None,
            "transport_observation": None,
        }
        if typed and error.result is not None:
            diagnostic = error.result
            transport = {"status": diagnostic.status.value, "exit_code": diagnostic.exit_code}
            for stream in ("stdout", "stderr"):
                reference = self.store.store_log(
                    run_id=self.run_id,
                    command_id=f"{command_id}.transport",
                    stream=SandboxLogStream(stream.upper()),
                    content=getattr(diagnostic, stream),
                )
                transport[f"{stream}_ref"] = _reference(reference).to_snapshot()
            boundary["transport_observation"] = transport
        return boundary

    def _result(
        self,
        phase,
        started,
        *,
        status=WebPhaseResultStatus.PASSED,
        code=None,
        stdout=b"",
        stderr=b"",
        artifacts=(),
        details=None,
        exit_codes=(),
        plan_hashes=(),
    ):
        completed = datetime.now(UTC)
        metadata = self._metadata(
            phase,
            started,
            completed,
            status=status.value,
            failure_code=code,
            observations=details or {},
        )
        manifest = self._artifact(f"phases/{phase.phase.value.lower()}.json", _json(metadata))
        out = self.store.store_log(
            run_id=self.run_id,
            command_id=phase.phase.value.lower(),
            stream=SandboxLogStream.STDOUT,
            content=stdout,
        )
        err = self.store.store_log(
            run_id=self.run_id,
            command_id=phase.phase.value.lower(),
            stream=SandboxLogStream.STDERR,
            content=stderr,
        )
        return WebPhaseResult(
            phase=phase.phase,
            status=status,
            command_plan_hashes=tuple(sorted(plan_hashes)),
            started_at=started,
            completed_at=completed,
            exit_codes=exit_codes,
            stdout_refs=(_reference(out),),
            stderr_refs=(_reference(err),),
            artifact_refs=tuple(sorted(set((manifest, *artifacts)))),
            findings=(),
            failure_category=(
                WebFailureCategory.RUNTIME
                if status is WebPhaseResultStatus.RUNTIME_ERROR
                else {
                    WebExecutionPhase.HEALTH_CHECK: WebFailureCategory.HEALTH_CHECK,
                    WebExecutionPhase.STATIC_CHECK: WebFailureCategory.STATIC_CHECK,
                    WebExecutionPhase.TEST: WebFailureCategory.TEST,
                }.get(phase.phase, WebFailureCategory.RUNTIME)
                if code
                else None
            ),
            failure_code=code,
            normalized_summary=(
                code.replace("_", " ") if code else f"Web {phase.phase.value.lower()} completed."
            ),
        )

    async def _get_runtime(self):
        if self.runtime is None:
            if self.workspace is None:
                raise WebPhaseRuntimeError("WEB_WORKSPACE_NOT_PREPARED")
            self.runtime = self.runtime_factory(
                image_id=self.identity.image_id,
                runner_kind=self.identity.kind,
                workspace=self.workspace.path,
                resources=self.resources,
                docker_context=self.context,
                controlled_network=self.network,
            )
        await self.runtime.open()
        return self.runtime

    async def execute(self, phase_plan, *, contract):
        issue = self._verify(phase_plan, contract)
        if issue:
            return self._block(phase_plan, issue)
        if phase_plan.execution_kind is WebPhaseExecutionKind.NO_OP:
            self._last_phase = tuple(WebExecutionPhase).index(phase_plan.phase)
            return create_web_no_op_phase_result(phase_plan)
        started = datetime.now(UTC)
        phase = phase_plan.phase
        try:
            if phase is WebExecutionPhase.VALIDATE:
                try:
                    self.workspace = prepare_phase_workspace(
                        self.prepared, self.snapshot, workspaces_root=self.root
                    )
                except (OSError, ValueError):
                    self._failed = True
                    return self._block(phase_plan, "WEB_SOURCE_WORKSPACE_INVALID")
                result = self._result(phase_plan, started, details={"source_bytes_verified": True})
            elif phase is WebExecutionPhase.BROWSER_EVIDENCE:
                if self.browser_executor is None:
                    self._failed = True
                    return self._block(phase_plan, "WEB_BROWSER_EVIDENCE_ADAPTER_UNAVAILABLE")
                result = await self.browser_executor.execute(
                    phase_plan, contract=contract, runtime=await self._get_runtime()
                )
                if result.phase is not phase:
                    raise WebPhaseRuntimeError("WEB_BROWSER_PHASE_MISMATCH")
            elif phase is WebExecutionPhase.COLLECT_ARTIFACTS:
                return await self.finalize()
            elif phase is WebExecutionPhase.RUN:
                await self._start_servers(phase_plan)
                result = self._result(
                    phase_plan,
                    started,
                    details={
                        "processes_started": list(self._processes),
                        "application_exit_observed": False,
                    },
                    plan_hashes=tuple(plan.content_hash for plan in phase_plan.command_plans),
                )
            elif phase is WebExecutionPhase.HEALTH_CHECK:
                results = await self._probe_health()
                healthy = (
                    len(results) == len(contract.health_checks)
                    and bool(results)
                    and all(item.status.value == "HEALTHY" for item in results)
                )
                result = self._result(
                    phase_plan,
                    started,
                    status=WebPhaseResultStatus.PASSED if healthy else WebPhaseResultStatus.FAILED,
                    code=None if healthy else "WEB_HEALTH_CHECK_FAILED",
                    details={"health_checks": [item.to_snapshot() for item in results]},
                )
            elif phase_plan.execution_kind is WebPhaseExecutionKind.COMMAND_PLANS:
                result = await self._commands(phase_plan)
            elif phase is WebExecutionPhase.STATIC_CHECK:
                # Exact static profile validation has already rejected frameworks/compiled sources.
                html = read_regular(self.workspace.path / "index.html", 1024 * 1024).decode("utf-8")
                valid = "<html" in html.casefold() and "<body" in html.casefold()
                result = self._result(
                    phase_plan,
                    started,
                    status=WebPhaseResultStatus.PASSED if valid else WebPhaseResultStatus.FAILED,
                    code=None if valid else "WEB_STATIC_DOCUMENT_INVALID",
                    details={"html_document_present": valid},
                )
            elif phase is WebExecutionPhase.TEST:
                await self._start_servers(contract.execution_plan.phase(WebExecutionPhase.RUN))
                health = await self._probe_health()
                await self._stop_servers()
                healthy = (
                    len(health) == len(contract.health_checks)
                    and bool(health)
                    and all(item.status.value == "HEALTHY" for item in health)
                )
                result = self._result(
                    phase_plan,
                    started,
                    status=WebPhaseResultStatus.PASSED if healthy else WebPhaseResultStatus.FAILED,
                    code=None if healthy else "WEB_STATIC_SMOKE_FAILED",
                    details={
                        "health_checks": [item.to_snapshot() for item in health],
                        "check_kind": "LOCAL_HTTP_SMOKE",
                    },
                )
            else:
                return self._block(phase_plan, "WEB_PHASE_ADAPTER_UNAVAILABLE")
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, WebPhaseRuntimeError) as error:
            observed = error.command_result if isinstance(error, WebPhaseRuntimeError) else None
            boundary = self._runtime_failure_observation(
                error,
                command_id=getattr(error, "command_id", phase.value.lower()),
                plan_hash=getattr(error, "plan_hash", None),
            )
            result = self._result(
                phase_plan,
                started,
                status=WebPhaseResultStatus.RUNTIME_ERROR,
                code="WEB_PHASE_RUNTIME_ERROR",
                stdout=observed.stdout if observed is not None else b"",
                stderr=observed.stderr if observed is not None else b"",
                details={"runtime_failures": [boundary]},
                exit_codes=(observed.exit_code,)
                if observed is not None and observed.exit_code is not None
                else (),
                plan_hashes=(error.plan_hash,)
                if isinstance(error, WebPhaseRuntimeError) and hasattr(error, "plan_hash")
                else (),
            )
        self._last_phase = tuple(WebExecutionPhase).index(phase)
        self._failed = result.is_failure
        return result

    async def _start_servers(self, phase):
        runtime = await self._get_runtime()
        for plan in phase.command_plans:
            if not validate_sandbox_plan(
                plan, resources=self.resources, policy=self.policy
            ).is_accepted:
                raise WebPhaseRuntimeError("WEB_RUNTIME_PLAN_POLICY_REJECTED")
            for command in plan.commands:
                started = datetime.now(UTC)
                try:
                    name = await runtime.start_command(command)
                except WebPhaseRuntimeError as error:
                    error.plan_hash = plan.content_hash
                    error.command_id = command.command_id
                    raise
                self._processes[name] = {
                    "command_plan_hash": plan.content_hash,
                    "command_id": command.command_id,
                    "started_at": started.isoformat(),
                }

    async def _probe_health(self):
        runtime = await self._get_runtime()
        results = []
        for spec in self.contract.health_checks:
            result = await probe_web_health(
                spec, invoke=runtime.invoke, runner_kind=self.identity.kind
            )
            results.append(result)
            if result.status.value != "HEALTHY":
                break
        self._health.extend(result.to_snapshot() for result in results)
        return results

    async def _stop_servers(self):
        if self.runtime is None or not self._processes:
            return
        failure = None
        try:
            observations = await self.runtime.stop_servers()
        except WebPhaseRuntimeError as error:
            observations = getattr(error, "observations", ())
            failure = error
        unexpected_exit = False
        for observed in observations:
            name = observed["container"]
            process = self._processes.pop(name)
            streams = {}
            for stream in ("stdout", "stderr"):
                log = self.store.store_log(
                    run_id=self.run_id,
                    command_id=process["command_id"],
                    stream=SandboxLogStream(stream.upper()),
                    content=observed[stream],
                )
                streams[f"{stream}_ref"] = _reference(log).to_snapshot()
            terminal_exit_observed = (
                observed["state"].get("Running") is False
                and type(observed["state"].get("ExitCode")) is int
            )
            self._runtime_observations.append(
                {
                    **process,
                    **streams,
                    "process_id": name,
                    "completed_at": datetime.now(UTC).isoformat(),
                    "exit_code": observed["state"]["ExitCode"] if terminal_exit_observed else None,
                    "application_exit_observed": terminal_exit_observed,
                    "terminated_by_controller": observed["terminated_by_controller"],
                }
            )
            unexpected_exit |= (
                not terminal_exit_observed
                or observed.get("transport_status", "COMPLETED") != "COMPLETED"
                or (
                    not observed["terminated_by_controller"]
                    or observed["state"].get("OOMKilled") is True
                )
            )
        if unexpected_exit:
            raise WebPhaseRuntimeError("WEB_SERVER_EXITED_BEFORE_CONTROLLER")
        if failure is not None:
            raise failure

    def _collect(self, patterns):
        collection = collect_web_artifacts(
            self.workspace.path, patterns=tuple(sorted(set(patterns)))
        )
        if collection.status.value != "COLLECTED":
            raise WebPhaseRuntimeError("WEB_ARTIFACT_COLLECTION_FAILED")
        refs = []
        for artifact in collection.artifacts:
            data = read_regular(self.workspace.path / artifact.normalized_path, 25 * 1024 * 1024)
            if (
                len(data) != artifact.size_bytes
                or hashlib.sha256(data).hexdigest() != artifact.sha256_digest
            ):
                raise WebPhaseRuntimeError("WEB_ARTIFACT_CHANGED_DURING_COLLECTION")
            reference = self._artifact(
                f"generated/{artifact.normalized_path}", data, artifact.media_type
            )
            refs.append(reference)
            self._generated_artifacts[(artifact.normalized_path, artifact.sha256_digest)] = (
                reference
            )
        return refs

    async def _commands(self, phase):
        from dataclasses import replace

        runtime = await self._get_runtime()
        runs = []
        runtime_failures = []
        for plan in phase.command_plans:
            start = datetime.now(UTC)
            commands = []
            for command in plan.commands:
                begun = datetime.now(UTC)
                runtime_failure = None
                try:
                    observed = await runtime.run_command(command)
                except (WebPhaseRuntimeError, OSError, ValueError) as error:
                    # Docker preflight/cleanup diagnostics are not command exits.
                    # Only run_command can attest that its application observation exists.
                    observed = (
                        error.command_result if isinstance(error, WebPhaseRuntimeError) else None
                    )
                    boundary = self._runtime_failure_observation(
                        error, command_id=command.command_id, plan_hash=plan.content_hash
                    )
                    runtime_failure = boundary["failure_code"]
                    runtime_failures.append(boundary)
                finished = datetime.now(UTC)
                stdout = self.store.store_log(
                    run_id=self.run_id,
                    command_id=command.command_id,
                    stream=SandboxLogStream.STDOUT,
                    content=b"" if observed is None else observed.stdout,
                )
                stderr = self.store.store_log(
                    run_id=self.run_id,
                    command_id=command.command_id,
                    stream=SandboxLogStream.STDERR,
                    content=b"" if observed is None else observed.stderr,
                )
                status = {
                    HostProcessStatus.TIMED_OUT: SandboxCommandStatus.TIMED_OUT,
                    HostProcessStatus.OUTPUT_LIMIT_EXCEEDED: SandboxCommandStatus.RESOURCE_LIMIT_EXCEEDED,
                }.get(
                    None if observed is None else observed.status,
                    SandboxCommandStatus.RUNTIME_ERROR,
                )
                if observed is not None and observed.status is HostProcessStatus.COMPLETED:
                    status = (
                        SandboxCommandStatus.SUCCEEDED
                        if observed.exit_code in command.expected_exit_codes
                        else SandboxCommandStatus.FAILED
                    )
                commands.append(
                    SandboxCommandEvidence(
                        command_id=command.command_id,
                        status=status,
                        started_at=begun,
                        finished_at=finished,
                        exit_code=None if observed is None else observed.exit_code,
                        stdout_log=stdout,
                        stderr_log=stderr,
                        artifacts=(),
                        output_parser_id=command.output_parser_id,
                        failure_message=None
                        if status is SandboxCommandStatus.SUCCEEDED
                        else (runtime_failure or f"Web command {status.value.lower()}."),
                    )
                )
                if status is not SandboxCommandStatus.SUCCEEDED or runtime_failure is not None:
                    break
            run = create_sandbox_run_evidence(
                run_id=uuid4(),
                plan=plan,
                image_reference=self.identity.image_id,
                runtime_reference="docker.web.phase.v1",
                started_at=start,
                finished_at=datetime.now(UTC),
                command_evidence=tuple(commands),
            )
            if (
                runtime_failure is not None
                and commands[-1].status is SandboxCommandStatus.SUCCEEDED
            ):
                # The application completed successfully; its enclosing runtime did not.
                run = replace(
                    run, status=SandboxRunStatus.RUNTIME_ERROR, failure_message=runtime_failure
                )
            runs.append(run)
            if run.status.value != "SUCCEEDED":
                break
        result = normalize_web_command_phase(phase, runs=tuple(runs))
        artifact_failure = None
        try:
            artifacts = self._collect(
                pattern
                for plan, run in zip(phase.command_plans[: len(runs)], runs, strict=True)
                for command in plan.commands[: len(run.command_evidence)]
                for pattern in _command_artifact_patterns(command)
            )
        except (OSError, ValueError, WebPhaseRuntimeError):
            artifacts = []
            artifact_failure = "WEB_ARTIFACT_COLLECTION_FAILED"
            if not result.is_failure:
                result = replace(
                    result,
                    status=WebPhaseResultStatus.RUNTIME_ERROR,
                    failure_category=WebFailureCategory.ARTIFACT_COLLECTION,
                    failure_code=artifact_failure,
                    normalized_summary="Web artifact collection failed.",
                )
        envelope = self._artifact(
            f"phases/{phase.phase.value.lower()}.json",
            _json(
                self._metadata(
                    phase,
                    result.started_at,
                    result.completed_at,
                    status=result.status.value,
                    artifact_failure=artifact_failure,
                    runtime_failures=runtime_failures,
                    sandbox_runs=[run.to_snapshot() for run in runs],
                )
            ),
        )
        return replace(
            result, artifact_refs=tuple(sorted(set((*result.artifact_refs, *artifacts, envelope))))
        )

    async def finalize(self):
        if self._final_result is not None:
            return self._final_result
        if self.workspace is None:
            return None
        phase = self.contract.execution_plan.phase(WebExecutionPhase.COLLECT_ARTIFACTS)
        started = datetime.now(UTC)
        code = None
        artifacts = []
        try:
            await self._stop_servers()
            patterns = tuple(
                pattern
                for item in self.contract.execution_plan.phases
                for plan in item.command_plans
                for command in plan.commands
                for pattern in _command_artifact_patterns(command)
            )
            artifacts = self._collect(patterns)
        except (OSError, ValueError, WebPhaseRuntimeError):
            code = "WEB_FINALIZATION_FAILED"
        finally:
            containers_removed = True
            if self.runtime is not None:
                try:
                    await self.runtime.close()
                except (OSError, WebPhaseRuntimeError):
                    code = "WEB_CONTAINER_CLEANUP_UNCONFIRMED"
                    containers_removed = False
            if containers_removed:
                try:
                    self.workspace.close()
                except (OSError, ValueError):
                    code = "WEB_WORKSPACE_CLEANUP_UNCONFIRMED"
        self._final_result = self._result(
            phase,
            started,
            status=WebPhaseResultStatus.RUNTIME_ERROR if code else WebPhaseResultStatus.PASSED,
            code=code,
            artifacts=tuple(sorted(set((*artifacts, *self._generated_artifacts.values())))),
            details={
                "processes": self._runtime_observations,
                "health_checks": self._health,
                "cleanup_confirmed": code is None,
            },
        )
        return self._final_result
