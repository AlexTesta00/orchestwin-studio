"""Connect frozen SQL plans to the previously observed static browser executor."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.static_browser_executor import (
    HARNESS_PATH,
    decode_inspection,
    execute_static_browser_job,
)
from orchestwin.web_execution.static_browser_jobs import (
    canonical_bytes,
    content_hash,
    job_from_revision,
)
from orchestwin.web_execution.static_inspections import Inspection, InspectionError, InspectionPlan
from orchestwin.web_execution.verified_browser_runner import (
    VerifiedBrowserRunner,
    read_json,
    read_regular,
    verify_browser_runner,
)


@dataclass(frozen=True, slots=True)
class InspectorBinding:
    platform_commit: str
    runner: VerifiedBrowserRunner
    harness_sha256: str


class PersistedStaticBrowserBackend:
    def __init__(
        self, *, repo_root: Path, runner_manifest: Path, evidence_root: Path, content_root: Path
    ) -> None:
        self.repo_root = Path(repo_root).absolute()
        self.runner_manifest = Path(runner_manifest).absolute()
        self.evidence_root = Path(evidence_root).absolute()
        self.content_root = Path(content_root).absolute()
        for path in (self.repo_root, self.evidence_root, self.runner_manifest, self.content_root):
            if ".." in path.parts or any(
                part.is_symlink() or part.is_junction() for part in (path, *path.parents)
            ):
                raise InspectionError("STATIC_INSPECTION_PATH_UNSAFE", 503)
        if self.evidence_root == self.repo_root or self.repo_root in self.evidence_root.parents:
            raise InspectionError("STATIC_INSPECTION_EVIDENCE_MUST_BE_EXTERNAL", 503)

    async def binding(self) -> InspectorBinding:
        async def git(*arguments):
            result = await run_bounded_host_process(
                ("git", "-C", str(self.repo_root), *arguments),
                timeout_seconds=15,
                maximum_output_bytes_per_stream=1024 * 1024,
                environment_overrides={},
            )
            if result.status != "COMPLETED" or result.exit_code != 0:
                raise InspectionError("STATIC_INSPECTION_GIT_UNAVAILABLE", 503)
            return result.stdout

        head = (await git("rev-parse", "HEAD")).decode().strip()
        if re.fullmatch(r"[0-9a-f]{40}", head) is None:
            raise InspectionError("STATIC_INSPECTION_COMMIT_INVALID", 503)
        if (await git("status", "--porcelain")).strip():
            raise InspectionError("STATIC_INSPECTION_REQUIRES_CLEAN_COMMIT")
        runner = verify_browser_runner(self.runner_manifest, self.repo_root)
        harness = read_regular(self.repo_root / HARNESS_PATH, 20000)
        committed = await git("show", f"HEAD:{HARNESS_PATH}")
        if committed.replace(b"\r\n", b"\n") != harness.replace(b"\r\n", b"\n"):
            raise InspectionError("STATIC_INSPECTION_HARNESS_NOT_COMMITTED")
        return InspectorBinding(head, runner, hashlib.sha256(harness).hexdigest())

    def _content(self, key: str) -> bytes | None:
        if re.fullmatch(r"sha256/[0-9a-f]{2}/[0-9a-f]{64}", key) is None:
            raise InspectionError("STATIC_INSPECTION_SOURCE_ADDRESS_INVALID")
        return read_regular(self.content_root / key, 1024 * 1024)

    async def plan(self, context, scenarios) -> InspectionPlan:
        from uuid import UUID

        binding = await self.binding()
        job = job_from_revision(
            context.revision,
            owner_user_id=UUID(str(context.revision["created_by_user_id"])),
            project_id=context.architecture.project_id,
            read_content=self._content,
            scenarios=scenarios,
            runner_manifest_content_hash=binding.runner.manifest_content_hash,
            harness_sha256=binding.harness_sha256,
        )
        return InspectionPlan(
            job, context.architecture, binding.platform_commit, binding.runner.image_id
        )

    async def check_binding(self, plan: InspectionPlan) -> None:
        observed = await self.binding()
        if (
            observed.platform_commit != plan.platform_commit
            or observed.runner.manifest_content_hash != plan.job.runner_manifest_content_hash
            or observed.runner.image_id != plan.runner_image_id
            or observed.harness_sha256 != plan.job.harness_sha256
        ):
            raise InspectionError("STATIC_INSPECTION_RUNTIME_CHANGED_REPLAN_REQUIRED")

    async def execute(self, inspection: Inspection, authorize) -> None:
        await execute_static_browser_job(
            inspection.plan.job,
            repo_root=self.repo_root,
            runner_manifest=self.runner_manifest,
            output_root=self.evidence_root / inspection.id.hex,
            authorize=authorize,
        )

    def result(self, inspection: Inspection) -> dict[str, object]:
        return verify_inspection_result(self.evidence_root / inspection.id.hex, inspection)


def verify_inspection_result(directory: Path, inspection: Inspection) -> dict[str, object]:
    """Verify terminal evidence and raw decoder output before committing a result.

    No Docker call is made here; this is also the explicit crash-recovery path.
    """
    body = read_regular(directory / "manifest.json", 1024 * 1024)
    report = read_json(body)
    if not isinstance(report, dict):
        raise InspectionError("STATIC_INSPECTION_RESULT_INVALID")
    digest = report.get("content_hash")
    if digest != content_hash(
        {key: value for key, value in report.items() if key != "content_hash"}
    ):
        raise InspectionError("STATIC_INSPECTION_RESULT_HASH_MISMATCH")
    plan = inspection.plan
    expected = {
        "schema_version": 1,
        "report_type": "STATIC_BROWSER_EXECUTION_NOT_FULL_PROFILE",
        "job_content_hash": plan.job.content_hash,
        "source": plan.job.snapshot()["source"],
        "runner_observation_content_hash": plan.job.runner_manifest_content_hash,
        "runner_image_id": plan.runner_image_id,
        "image_id_kind": "LOCAL_CONFIG_DIGEST",
        "harness_sha256": plan.job.harness_sha256,
        "platform_commit": plan.platform_commit,
        "authorization_kind": "GATE_7",
        "authorization_reference": f"gate:{inspection.gate_id}",
        "level_d_validated": False,
    }
    if (
        any(report.get(name) != value for name, value in expected.items())
        or report.get("level_d_validated") is not False
    ):
        raise InspectionError("STATIC_INSPECTION_RESULT_BINDING_MISMATCH")
    if report.get("status") not in {"COMPLETED", "FAILED"}:
        raise InspectionError("STATIC_INSPECTION_RESULT_NOT_TERMINAL")
    try:
        started = datetime.fromisoformat(report["started_at"])
        finished = datetime.fromisoformat(report["finished_at"])
        if (
            started.utcoffset() is None
            or finished.utcoffset() is None
            or (
                inspection.started_at is None
                or started < inspection.started_at
                or finished < started
            )
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise InspectionError("STATIC_INSPECTION_RESULT_TIMESTAMPS_INVALID") from None
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or not 3 <= len(artifacts) <= 64:
        raise InspectionError("STATIC_INSPECTION_RESULT_ARTIFACTS_INVALID")
    contents = {}
    total = 0
    for artifact in artifacts:
        name = artifact.get("path", "") if isinstance(artifact, dict) else ""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", name) is None or name in contents:
            raise InspectionError("STATIC_INSPECTION_RESULT_PATH_INVALID")
        value = read_regular(directory / name, 16 * 1024 * 1024)
        total += len(value)
        if (
            type(artifact.get("size_bytes")) is not int
            or artifact["size_bytes"] != len(value)
            or artifact.get("sha256") != hashlib.sha256(value).hexdigest()
            or total > 64 * 1024 * 1024
        ):
            raise InspectionError("STATIC_INSPECTION_RESULT_ARTIFACT_MISMATCH")
        contents[name] = value
    if contents.get("job.json") != plan.job.wire_bytes():
        raise InspectionError("STATIC_INSPECTION_RESULT_JOB_MISMATCH")
    observation = read_json(contents.get("runner-manifest.json", b"{}"))
    if (
        observation.get("content_hash") != plan.job.runner_manifest_content_hash
        or content_hash({key: value for key, value in observation.items() if key != "content_hash"})
        != plan.job.runner_manifest_content_hash
    ):
        raise InspectionError("STATIC_INSPECTION_RESULT_RUNNER_MISMATCH")
    seccomp = next(
        (item for item in observation.get("artifacts", []) if item.get("path") == "seccomp.json"),
        None,
    )
    if seccomp is None or hashlib.sha256(
        contents.get("seccomp.json", b"")
    ).hexdigest() != seccomp.get("sha256"):
        raise InspectionError("STATIC_INSPECTION_RESULT_SECCOMP_MISMATCH")
    result = {
        "execution_status": report["status"],
        "assertion_status": "NOT_OBSERVED",
        "manifest_content_hash": digest,
        "cleanup_confirmed": report.get("cleanup_confirmed"),
        "level_d_validated": False,
        "full_profile_execution": False,
        "artifacts": artifacts,
    }
    if report["status"] == "COMPLETED":
        if report.get("cleanup_confirmed") is not True:
            raise InspectionError("STATIC_INSPECTION_CLEANUP_NOT_CONFIRMED")
        summary, decoded = decode_inspection(contents.get("EXECUTE.stdout.log", b""), plan.job)
        if any(report.get(key) != value for key, value in summary.items()) or any(
            contents.get(name) != value for name, value in decoded.items()
        ):
            raise InspectionError("STATIC_INSPECTION_RAW_RESULT_MISMATCH")
        result.update(summary)
    else:
        code = report.get("failure_code", "STATIC_BROWSER_EXECUTION_FAILED")
        result["failure_code"] = (
            code
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", str(code))
            else "STATIC_BROWSER_EXECUTION_FAILED"
        )
    # Verify the summary itself is serializable without nonfinite numbers.
    canonical_bytes(result)
    return result
