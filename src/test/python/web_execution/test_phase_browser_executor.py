"""Fail closed before browser transport when attempt, route or runner binding is wrong."""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from orchestwin.sandbox.host_process import BoundedHostProcessResult
from orchestwin.web_execution.phase_browser_executor import GovernedWebBrowserExecutor
from orchestwin.web_execution.phase_browser_transport import WebBrowserTransportResult
from orchestwin.web_execution.phase_runner import WebPhaseRunnerIdentity
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.static_browser_jobs import canonical_bytes

from .test_phase_browser_evidence import envelope, events, report
from .test_phase_executor import setup_executor


@pytest.mark.parametrize("invalid", ["attempt", "runtime", "image", "url", "phase"])
def test_invalid_browser_binding_cannot_start_transport(tmp_path, invalid):
    _, contract, store, _ = setup_executor(tmp_path)
    attempt = uuid4()
    identity = WebPhaseRunnerIdentity("BROWSER", "sha256:" + "c" * 64, "d" * 64, "e" * 64)
    runtime = SimpleNamespace(
        execution_attempt_id=attempt,
        contract_content_hash=contract.content_hash,
        image_id="sha256:" + "b" * 64,
        bootstrap_manifest_hash="d" * 64,
    )
    phase = contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE)
    if invalid == "attempt":
        attempt = None
    elif invalid == "runtime":
        runtime.execution_attempt_id = uuid4()
    elif invalid == "image":
        identity = replace(identity, image_id="sha256:" + "f" * 64)
    elif invalid == "url":
        contract = replace(
            contract,
            browser_evidence_request=replace(
                contract.browser_evidence_request, base_url="http://127.0.0.1:9999"
            ),
        )
        runtime.contract_content_hash = contract.content_hash
    else:
        phase = contract.execution_plan.phase(WebExecutionPhase.RUN)

    class ForbiddenTransport:
        async def execute(self, *args, **kwargs):
            pytest.fail("invalid binding reached Docker")

    adapter = GovernedWebBrowserExecutor(
        runner_identity=identity,
        repo_root=Path(__file__).parents[4],
        evidence_store=store,
        transport=ForbiddenTransport(),
    )
    result = asyncio.run(
        adapter.execute(phase, contract=contract, runtime=runtime, execution_attempt_id=attempt)
    )
    assert result.status.value == "POLICY_BLOCKED"
    assert not result.exit_codes


@pytest.mark.parametrize("changed", ["harness", "seccomp"])
def test_browser_uses_only_the_exact_bytes_bound_to_approval(tmp_path, monkeypatch, changed):
    from orchestwin.web_execution import phase_browser_executor as module

    _, contract, store, _ = setup_executor(tmp_path)
    attempt = uuid4()
    root = Path(__file__).parents[4]
    identity = WebPhaseRunnerIdentity("BROWSER", "sha256:" + "c" * 64, "d" * 64, "e" * 64)
    runtime = SimpleNamespace(
        execution_attempt_id=attempt,
        contract_content_hash=contract.content_hash,
        image_id="sha256:" + "b" * 64,
        bootstrap_manifest_hash="d" * 64,
    )
    harness_path = root / "infra/web-runners/phase-browser/inspect.cjs"
    seccomp_path = root / "infra/web-runners/browser-automation/seccomp.json"
    approved_harness = hashlib.sha256(harness_path.read_bytes()).hexdigest()
    approved_seccomp = hashlib.sha256(seccomp_path.read_bytes()).hexdigest()

    class ForbiddenTransport:
        async def execute(self, *args, **kwargs):
            pytest.fail("changed approved browser inputs reached Docker")

    adapter = GovernedWebBrowserExecutor(
        runner_identity=identity,
        repo_root=root,
        evidence_store=store,
        transport=ForbiddenTransport(),
        expected_harness_sha256=approved_harness,
        expected_seccomp_sha256=approved_seccomp if changed == "harness" else "f" * 64,
    )
    if changed == "harness":
        original_read = module.read_regular

        def changed_after_approval(path, limit):
            content = original_read(path, limit)
            return content + b"\n// changed after approval\n" if path == harness_path else content

        monkeypatch.setattr(module, "read_regular", changed_after_approval)
    result = asyncio.run(
        adapter.execute(
            contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE),
            contract=contract,
            runtime=runtime,
            execution_attempt_id=attempt,
        )
    )
    assert result.status.value == "POLICY_BLOCKED"
    assert result.failure_code == (
        "WEB_BROWSER_HARNESS_MISMATCH" if changed == "harness" else "WEB_BROWSER_SECCOMP_MISMATCH"
    )
    assert not result.exit_codes and not result.stdout_refs and not result.stderr_refs


@pytest.mark.parametrize("case", ["passed", "console", "malformed", "timeout", "cleanup", "oom"])
def test_browser_phase_derives_failure_and_keeps_actual_transport_bytes(tmp_path, case):
    _, contract, store, _ = setup_executor(tmp_path)
    attempt = uuid4()
    identity = WebPhaseRunnerIdentity("BROWSER", "sha256:" + "c" * 64, "d" * 64, "e" * 64)
    runtime = SimpleNamespace(
        execution_attempt_id=attempt,
        contract_content_hash=contract.content_hash,
        image_id="sha256:" + "b" * 64,
        bootstrap_manifest_hash="d" * 64,
    )

    class Transport:
        async def execute(self, job, **kwargs):
            body = report(job)
            if case == "console":
                observed_events = events()
                observed_events["console_messages"].append(
                    {"level": "ERROR", "message": "development failure", "location": None}
                )
                body["screens"][0]["events"] = envelope(canonical_bytes(observed_events))
            self.raw = b'{"partial":' if case in {"malformed", "timeout"} else canonical_bytes(body)
            observed = BoundedHostProcessResult(
                stdout=self.raw,
                stderr=b"",
                failure_message=None,
                status="TIMED_OUT" if case == "timeout" else "COMPLETED",
                exit_code=None if case == "timeout" else 137 if case == "oom" else 0,
            )
            return WebBrowserTransportResult(
                (("EXECUTE", observed),),
                None if case == "timeout" else 137 if case == "oom" else 0,
                case != "cleanup",
                "WEB_BROWSER_TRANSPORT_LIMIT_OR_FAILURE"
                if case == "timeout"
                else "WEB_BROWSER_OOM_KILLED"
                if case == "oom"
                else "WEB_BROWSER_CLEANUP_UNCONFIRMED"
                if case == "cleanup"
                else None,
                "d" * 64,
                "e" * 64,
            )

    transport = Transport()
    root = Path(__file__).parents[4]
    adapter = GovernedWebBrowserExecutor(
        runner_identity=identity,
        repo_root=root,
        evidence_store=store,
        transport=transport,
        expected_harness_sha256=hashlib.sha256(
            (root / "infra/web-runners/phase-browser/inspect.cjs").read_bytes()
        ).hexdigest(),
        expected_seccomp_sha256=hashlib.sha256(
            (root / "infra/web-runners/browser-automation/seccomp.json").read_bytes()
        ).hexdigest(),
    )
    result = asyncio.run(
        adapter.execute(
            contract.execution_plan.phase(WebExecutionPhase.BROWSER_EVIDENCE),
            contract=contract,
            runtime=runtime,
            execution_attempt_id=attempt,
        )
    )
    assert (
        result.status.value
        == {
            "passed": "PASSED",
            "console": "FAILED",
            "malformed": "RUNTIME_ERROR",
            "timeout": "TIMED_OUT",
            "cleanup": "RUNTIME_ERROR",
            "oom": "RESOURCE_LIMIT_EXCEEDED",
        }[case]
    )
    assert result.exit_codes == (() if case == "timeout" else (137,) if case == "oom" else (0,))
    assert any(store.read(ref.storage_key) == transport.raw for ref in result.stdout_refs)
    manifests = [
        json.loads(store.read(ref.storage_key))
        for ref in result.artifact_refs
        if ref.media_type == "application/json"
    ]
    metadata = next(
        item
        for item in manifests
        if isinstance(item, dict) and item.get("report_type") == "GOVERNED_WEB_BROWSER_PHASE"
    )
    assert metadata["execution_attempt_id"] == str(attempt)
    if case in {"console", "cleanup"}:
        assert metadata["bundle"]["status"] == "COLLECTED"
        assert metadata["browser_evidence"]["screens"][0]["artifacts"]["screenshot"]
