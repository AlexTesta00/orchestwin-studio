"""Collect real browser evidence from an exact governed Web execution attempt."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from orchestwin.sandbox.evidence import SandboxLogStream
from orchestwin.web_execution.phase_browser_evidence import (
    WebPhaseBrowserEvidenceError,
    create_browser_job,
    decode_browser_evidence,
)
from orchestwin.web_execution.phase_browser_transport import DockerWebBrowserTransport
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebFailureCategory,
    WebPhaseResult,
    WebPhaseResultStatus,
    create_web_policy_blocked_phase_result,
)
from orchestwin.web_execution.static_browser_jobs import canonical_bytes
from orchestwin.web_execution.verified_browser_runner import read_regular

_SECCOMP_SHA256 = "c178b6b5777fbec3e392e49eb928a9a552db7ee8e90aa4da4d6788d78a2f7192"


def _reference(value, media_type="text/plain"):
    return WebEvidenceReference(
        value.storage_key, value.sha256_digest, value.size_bytes, media_type
    )


class GovernedWebBrowserExecutor:
    """Browser sidecar with no capability promotion or formal-run side effects."""

    def __init__(
        self, *, runner_identity, repo_root: Path, evidence_store, interactions=(), transport=None
    ):
        self.identity = runner_identity
        self.root = Path(repo_root)
        self.store = evidence_store
        self.interactions = interactions
        self.transport = transport or DockerWebBrowserTransport()

    async def execute(self, phase_plan, *, contract, runtime, execution_attempt_id):
        def blocked(code):
            return create_web_policy_blocked_phase_result(
                phase_plan.phase,
                command_plan_hashes=tuple(plan.content_hash for plan in phase_plan.command_plans),
                policy_issue_code=code,
                message=code.replace("_", " "),
            )

        request = contract.browser_evidence_request
        target = contract.validation.selection.target.value
        port = 8080 if target == "WEB_PHP" else 4173
        if (
            phase_plan.phase is not WebExecutionPhase.BROWSER_EVIDENCE
            or phase_plan != contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE)
            or request is None
            or not isinstance(execution_attempt_id, UUID)
            or getattr(runtime, "execution_attempt_id", None) != execution_attempt_id
            or getattr(runtime, "contract_content_hash", None) != contract.content_hash
            or getattr(runtime, "bootstrap_manifest_hash", None)
            != self.identity.bootstrap_manifest_hash
            or runtime.image_id != f"sha256:{contract.runners.execution_runner_image_digest}"
            or self.identity.kind != "BROWSER"
            or self.identity.image_id != f"sha256:{request.runner_image_digest}"
            or request.runner_image_digest != contract.runners.browser_runner_image_digest
            or request.source_revision_content_hash != contract.source_revision_content_hash
            or request.source_tree_hash != contract.source_tree_hash
            or request.base_url != f"http://127.0.0.1:{port}"
        ):
            return blocked("WEB_BROWSER_EXECUTION_BINDING_MISMATCH")
        try:
            harness = read_regular(self.root / "infra/web-runners/phase-browser/inspect.cjs", 30000)
            seccomp = read_regular(
                self.root / "infra/web-runners/browser-automation/seccomp.json", 2 * 1024 * 1024
            )
            if hashlib.sha256(seccomp).hexdigest() != _SECCOMP_SHA256:
                return blocked("WEB_BROWSER_SECCOMP_MISMATCH")
            job = create_browser_job(
                request,
                execution_attempt_id=execution_attempt_id,
                operation_id=uuid4().hex,
                harness_sha256=hashlib.sha256(harness).hexdigest(),
                interactions=self.interactions,
            )
        except (OSError, ValueError):
            return blocked("WEB_BROWSER_JOB_INVALID")

        started = datetime.now(UTC)
        observed = await self.transport.execute(
            job, runtime=runtime, image_id=self.identity.image_id, harness=harness, seccomp=seccomp
        )
        operations = []
        stdout_refs, stderr_refs, artifacts = [], [], []
        execution = None
        for label, result in observed.operations:
            streams = {}
            for stream, destination in (("stdout", stdout_refs), ("stderr", stderr_refs)):
                ref = _reference(
                    self.store.store_log(
                        run_id=execution_attempt_id,
                        command_id=f"browser.{label.lower()}",
                        stream=SandboxLogStream(stream.upper()),
                        content=getattr(result, stream),
                    )
                )
                streams[f"{stream}_ref"] = ref.to_snapshot()
                destination.append(ref)
            operations.append(
                {"label": label, "status": result.status, "exit_code": result.exit_code, **streams}
            )
            if label == "EXECUTE":
                execution = result

        decoded = None
        code = observed.failure_code
        status, category = WebPhaseResultStatus.RUNTIME_ERROR, WebFailureCategory.RUNTIME
        if execution is not None and execution.status == "TIMED_OUT":
            status, category = WebPhaseResultStatus.TIMED_OUT, WebFailureCategory.TIMEOUT
        elif observed.failure_code == "WEB_BROWSER_OOM_KILLED" or (
            execution is not None and execution.status == "OUTPUT_LIMIT_EXCEEDED"
        ):
            status, category = (
                WebPhaseResultStatus.RESOURCE_LIMIT_EXCEEDED,
                WebFailureCategory.RESOURCE_LIMIT,
            )
        # Preserve valid browser observations even when terminal verification or cleanup failed.
        if execution is not None and execution.status == "COMPLETED" and execution.stdout:
            try:
                decoded = decode_browser_evidence(
                    execution.stdout, job=job, store=self.store, run_id=execution_attempt_id
                )
                artifacts.extend(decoded.artifact_refs)
            except WebPhaseBrowserEvidenceError as error:
                code = code or str(error)
        if not observed.cleanup_confirmed:
            code = "WEB_BROWSER_CLEANUP_UNCONFIRMED"
        if code is None and (
            execution is None or decoded is None or observed.process_exit_code != 0
        ):
            code = "WEB_BROWSER_EVIDENCE_UNAVAILABLE"
        if code is None:
            status = WebPhaseResultStatus.FAILED if decoded.failed else WebPhaseResultStatus.PASSED
            category = WebFailureCategory.BROWSER if decoded.failed else None
            code = "WEB_BROWSER_CHECKS_FAILED" if decoded.failed else None

        def artifact(name, content):
            ref = _reference(
                self.store.store_artifact(
                    run_id=execution_attempt_id,
                    command_id="browser.evidence",
                    normalized_path=name,
                    content=canonical_bytes(content),
                    media_type="application/json",
                ),
                "application/json",
            )
            artifacts.append(ref)
            return ref

        artifact("browser/job.json", job)
        completed = datetime.now(UTC)
        manifest = {
            "report_type": "GOVERNED_WEB_BROWSER_PHASE",
            "schema_version": 1,
            "execution_attempt_id": str(execution_attempt_id),
            "source_revision_content_hash": contract.source_revision_content_hash,
            "source_tree_hash": contract.source_tree_hash,
            "contract_content_hash": contract.content_hash,
            "bootstrap_manifest_hash": self.identity.bootstrap_manifest_hash,
            "recipe_content_hash": self.identity.recipe_content_hash,
            "browser_image_id": self.identity.image_id,
            "harness_sha256": job["harness_sha256"],
            "seccomp_sha256": _SECCOMP_SHA256,
            "job": job,
            "operations": operations,
            "browser_evidence": None if decoded is None else decoded.metadata,
            "bundle": None if decoded is None else decoded.bundle.to_snapshot(),
            "status": status.value,
            "failure_code": code,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "cleanup_confirmed": observed.cleanup_confirmed,
            "container_id": observed.container_id,
            "network_container_id": observed.network_container_id,
            "process_exit_code": observed.process_exit_code,
            "formal_run_started": False,
            "level_d_validated": False,
        }
        artifact("browser/execution.json", manifest)
        return WebPhaseResult(
            phase=WebExecutionPhase.BROWSER_EVIDENCE,
            status=status,
            command_plan_hashes=(),
            started_at=started,
            completed_at=completed,
            exit_codes=() if observed.process_exit_code is None else (observed.process_exit_code,),
            stdout_refs=tuple(sorted(set(stdout_refs))),
            stderr_refs=tuple(sorted(set(stderr_refs))),
            artifact_refs=tuple(sorted(set(artifacts))),
            findings=() if decoded is None else decoded.findings,
            failure_category=category,
            failure_code=code,
            normalized_summary=code.replace("_", " ")
            if code
            else "Governed Web browser checks passed.",
        )
