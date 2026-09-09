"""Execute declarative inspections of static source bytes in an observed browser image.

No build, install, host mounts, arbitrary URLs, shell commands or automatic gate
approvals. The caller supplies an independent authorization port; the validation
CLI admits only exact repository-owned fixtures. A gate resolver is not invented
by this low-level adapter and no public owner execution route is enabled here.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import struct
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.static_browser_jobs import (
    VIEWPORTS,
    StaticBrowserError,
    StaticBrowserJob,
    canonical_bytes,
    content_hash,
)
from orchestwin.web_execution.verified_browser_runner import (
    artifact_bytes,
    read_json,
    read_regular,
    verify_browser_runner,
)

HARNESS_PATH = "infra/web-runners/static-browser/inspect.cjs"


@dataclass(frozen=True, slots=True)
class BrowserExecutionAuthorization:
    """Receipt from a trusted resolver, not from an arbitrary submitted request."""

    job_content_hash: str
    kind: str
    reference: str


AuthorizationPort = Callable[[StaticBrowserJob], Awaitable[BrowserExecutionAuthorization | None]]


def decode_inspection(raw: bytes, job: StaticBrowserJob):
    """Verify the executed job and artifact bindings; keep failed assertions failed."""
    data = read_json(raw)
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or data.get("job_content_hash") != job.content_hash
        or data.get("transport_status") != "COMPLETED"
        or data.get("uid") != 65532
        or data.get("chromium_sandbox_requested") is not True
        or data.get("chromium_no_sandbox_flag_absent") is not True
        or data.get("versions", {}).get("playwright") != "1.62.1"
        or data.get("versions", {}).get("axe_core") != "4.13.0"
    ):
        raise StaticBrowserError("STATIC_BROWSER_RESULT_INVALID")
    screens = data.get("screens")
    if not isinstance(screens, list) or len(screens) != len(job.scenarios) * len(VIEWPORTS):
        raise StaticBrowserError("STATIC_BROWSER_SCREENS_INCOMPLETE")
    artifacts = {}
    summaries = []
    any_failed = False
    expected = [(scenario, viewport) for scenario in job.scenarios for viewport in VIEWPORTS]
    for screen, (scenario, (name, width, height)) in zip(screens, expected, strict=True):
        if (
            not isinstance(screen, dict)
            or screen.get("scenario_id") != scenario.scenario_id
            or screen.get("route") != scenario.route
            or screen.get("viewport") != name
            or (screen.get("width"), screen.get("height")) != (width, height)
            or type(screen.get("blocked_requests")) is not int
            or screen["blocked_requests"] < 0
        ):
            raise StaticBrowserError("STATIC_BROWSER_SCREEN_MISMATCH")
        actions = screen.get("actions")
        if not isinstance(actions, list) or len(actions) != len(scenario.actions):
            raise StaticBrowserError("STATIC_BROWSER_ACTIONS_INCOMPLETE")
        stopped = False
        for index, (observed, wanted) in enumerate(zip(actions, scenario.actions, strict=True)):
            if observed.get("index") != index or observed.get("kind") != wanted.kind:
                raise StaticBrowserError("STATIC_BROWSER_ACTION_MISMATCH")
            state = observed.get("status")
            if stopped:
                if state != "NOT_RUN":
                    raise StaticBrowserError("STATIC_BROWSER_STOPPING_INVALID")
            elif state == "FAILED":
                if not observed.get("failure_code"):
                    raise StaticBrowserError("STATIC_BROWSER_FAILURE_REASON_MISSING")
                stopped = True
            elif state == "PASSED":
                if wanted.kind == "expect_text" and observed.get("observed_text") != wanted.value:
                    raise StaticBrowserError("STATIC_BROWSER_FALSE_ASSERTION_PASS")
            else:
                raise StaticBrowserError("STATIC_BROWSER_ACTION_STATUS_INVALID")
        prefix = f"{scenario.scenario_id}.{name}"
        png = artifact_bytes(screen.get("screenshot"))
        if (
            len(png) < 33
            or png[:8] != b"\x89PNG\r\n\x1a\n"
            or png[12:16] != b"IHDR"
            or struct.unpack(">II", png[16:24]) != (width, height)
        ):
            raise StaticBrowserError("STATIC_BROWSER_SCREENSHOT_INVALID")
        dom = artifact_bytes(screen.get("dom"))
        if "<html" not in dom.decode("utf-8").casefold():
            raise StaticBrowserError("STATIC_BROWSER_DOM_INVALID")
        axe = artifact_bytes(screen.get("axe"))
        axe_data = read_json(axe)
        if (
            not isinstance(axe_data, dict)
            or axe_data.get("testEngine", {}).get("version") != "4.13.0"
            or not isinstance(axe_data.get("violations"), list)
        ):
            raise StaticBrowserError("STATIC_BROWSER_AXE_INVALID")
        events = artifact_bytes(screen.get("events"))
        events_data = read_json(events)
        if (
            not isinstance(events_data, list)
            or len(events_data) > 100
            or any(
                not isinstance(event, dict) or not isinstance(event.get("type"), str)
                for event in events_data
            )
        ):
            raise StaticBrowserError("STATIC_BROWSER_EVENTS_INVALID")
        failed = (
            stopped
            or screen["blocked_requests"] > 0
            or any(event["type"] == "pageerror" for event in events_data)
        )
        status = "FAILED" if failed else "PASSED"
        if screen.get("status") != status:
            raise StaticBrowserError("STATIC_BROWSER_STATUS_MISMATCH")
        any_failed |= failed
        for suffix, body in (
            ("png", png),
            ("html", dom),
            ("axe.json", axe),
            ("events.json", events),
        ):
            artifacts[f"{prefix}.{suffix}"] = body
        summaries.append(
            {
                "scenario_id": scenario.scenario_id,
                "viewport": name,
                "status": status,
                "actions": actions,
                "blocked_requests": screen["blocked_requests"],
                "page_error_count": sum(event["type"] == "pageerror" for event in events_data),
                "axe_violation_rules": len(axe_data["violations"]),
            }
        )
    status = "FAILED" if any_failed else "PASSED"
    if data.get("status") != status:
        raise StaticBrowserError("STATIC_BROWSER_AGGREGATE_MISMATCH")
    return {
        "assertion_status": status,
        "screens": summaries,
        "versions": data["versions"],
    }, artifacts


def container_arguments(docker, image_id, name, operation_id, seccomp_path, harness):
    """Send only trusted code in argv. Submitted sources travel through bounded stdin."""
    arguments = (
        *docker,
        "create",
        "--interactive",
        "--init",
        "--name",
        name,
        "--label",
        f"org.orchestwin.static-browser={operation_id}",
        "--pull=never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        f"seccomp={seccomp_path}",
        "--pids-limit",
        "256",
        "--memory",
        "1g",
        "--cpus",
        "2",
        "--user",
        "65532:65532",
        "--shm-size",
        "256m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777",
        "--env",
        "HOME=/tmp",
        "--entrypoint",
        "node",
        image_id,
        "-e",
        harness,
    )
    if len(subprocess.list2cmdline(arguments)) > 30000:
        raise StaticBrowserError("PORTABLE_COMMAND_LINE_LIMIT")
    return arguments


async def _run(argv, *, timeout=30, stdin_bytes=None):
    return await run_bounded_host_process(
        tuple(argv),
        timeout_seconds=timeout,
        maximum_output_bytes_per_stream=16 * 1024 * 1024,
        environment_overrides={},
        stdin_bytes=stdin_bytes,
    )


def _ok(value) -> bool:
    return value.status == "COMPLETED" and value.exit_code == 0


async def execute_static_browser_job(
    job: StaticBrowserJob,
    *,
    repo_root: Path,
    runner_manifest: Path,
    output_root: Path,
    authorize: AuthorizationPort | None = None,
    runner=None,
) -> dict[str, object]:
    """Execute one exact authorized job and preserve evidence even on failure."""
    if authorize is None:
        raise StaticBrowserError("STATIC_BROWSER_AUTHORIZATION_REQUIRED")
    authorization = await authorize(job)
    if (
        authorization is None
        or authorization.job_content_hash != job.content_hash
        or authorization.kind not in {"GATE_7", "PROFILE_VALIDATION"}
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", authorization.reference)
    ):
        raise StaticBrowserError("STATIC_BROWSER_AUTHORIZATION_MISMATCH")
    root = repo_root.resolve(strict=True)
    output = output_root.absolute()
    if (
        output.exists()
        or output == root
        or root in output.parents
        or ".." in output.parts
        or any(path.is_symlink() or path.is_junction() for path in (output, *output.parents))
    ):
        raise StaticBrowserError("OUTPUT_MUST_BE_NEW_SAFE_AND_EXTERNAL")
    observed_runner = verify_browser_runner(runner_manifest, root)
    if observed_runner.manifest_content_hash != job.runner_manifest_content_hash:
        raise StaticBrowserError("JOB_RUNNER_OBSERVATION_MISMATCH")
    harness = read_regular(root / HARNESS_PATH, 20000)
    if hashlib.sha256(harness).hexdigest() != job.harness_sha256:
        raise StaticBrowserError("JOB_HARNESS_MISMATCH")
    wire = job.wire_bytes()
    execute = _run if runner is None else runner
    manifest = {
        "schema_version": 1,
        "report_type": "STATIC_BROWSER_EXECUTION_NOT_FULL_PROFILE",
        "status": "IN_PROGRESS",
        "assertion_status": "NOT_OBSERVED",
        "job_content_hash": job.content_hash,
        "source": job.snapshot()["source"],
        "runner_observation_content_hash": observed_runner.manifest_content_hash,
        "runner_image_id": observed_runner.image_id,
        "image_id_kind": "LOCAL_CONFIG_DIGEST",
        "harness_sha256": job.harness_sha256,
        "authorization_kind": authorization.kind,
        "authorization_reference": authorization.reference,
        "level_d_validated": False,
        "browser_sandbox_kernel_audit": "NOT_PERFORMED",
        "cleanup_confirmed": None,
        "started_at": datetime.now(UTC).isoformat(),
        "artifacts": [],
    }

    def store(name, body):
        with (output / name).open("xb") as file:
            file.write(body)
        manifest["artifacts"].append(
            {
                "path": name,
                "sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
            }
        )

    async def command(argv, label, *, timeout=30, input_bytes=None, logs=False, required=True):
        result = await execute(tuple(argv), timeout=timeout, stdin_bytes=input_bytes)
        if logs:
            store(f"{label}.stdout.log", result.stdout)
            store(f"{label}.stderr.log", result.stderr)
        if required and not _ok(result):
            raise StaticBrowserError(f"{label}_FAILED")
        return result

    head = (
        (await command(("git", "-C", str(root), "rev-parse", "HEAD"), "GIT_HEAD"))
        .stdout.decode()
        .strip()
    )
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise StaticBrowserError("GIT_HEAD_INVALID")
    dirty = await command(("git", "-C", str(root), "status", "--porcelain"), "GIT_STATUS")
    if dirty.stdout.strip():
        raise StaticBrowserError("COMMIT_VERIFIED_CODE_FIRST")
    committed = await command(
        ("git", "-C", str(root), "show", f"HEAD:{HARNESS_PATH}"), "HARNESS_TRACKED"
    )
    if committed.stdout.replace(b"\r\n", b"\n") != harness.replace(b"\r\n", b"\n"):
        raise StaticBrowserError("HARNESS_NOT_COMMITTED")
    context = (await command(("docker", "context", "show"), "CONTEXT")).stdout.decode().strip()
    context_data = read_json(
        (await command(("docker", "context", "inspect", context), "CONTEXT_INSPECT")).stdout
    )
    if not context_data[0]["Endpoints"]["docker"]["Host"].startswith(("npipe://", "unix://")):
        raise StaticBrowserError("LOCAL_DOCKER_REQUIRED")
    docker = ("docker", "--context", context)
    image = read_json(
        (
            await command((*docker, "image", "inspect", observed_runner.image_id), "IMAGE_INSPECT")
        ).stdout
    )[0]
    if (
        image.get("Id") != observed_runner.image_id
        or image.get("Os") != "linux"
        or image.get("Architecture") != "amd64"
    ):
        raise StaticBrowserError("OBSERVED_IMAGE_NOT_AVAILABLE")
    # No fallback to tags, pulls or rebuilds when the recorded image is absent.
    operation = uuid4().hex
    name = f"orchestwin-static-browser-{operation}"
    args = container_arguments(
        docker,
        observed_runner.image_id,
        name,
        operation,
        output / "seccomp.json",
        harness.decode("utf-8"),
    )
    manifest["platform_commit"] = head
    output.mkdir(parents=True)
    store("runner-manifest.json", observed_runner.manifest_bytes)
    store("seccomp.json", observed_runner.seccomp_bytes)
    # Preserve exact submitted bytes locally, not in stdout or a command line.
    store("job.json", wire)
    attempted = False

    async def cleanup():
        inspected = await command(
            (*docker, "container", "inspect", name), "CLEANUP_INSPECT", required=False
        )
        if not _ok(inspected):
            return False
        labels = read_json(inspected.stdout)[0].get("Config", {}).get("Labels", {}) or {}
        if labels.get("org.orchestwin.static-browser") != operation:
            return False
        removed = await command((*docker, "rm", "--force", name), "CLEANUP_REMOVE", required=False)
        return _ok(removed)

    try:
        attempted = True
        await command(args, "CREATE", logs=True)
        result = await command(
            (*docker, "start", "--attach", "--interactive", name),
            "EXECUTE",
            timeout=120,
            input_bytes=wire,
            logs=True,
        )
        summary, artifacts = decode_inspection(result.stdout, job)
        for filename, body in artifacts.items():
            store(filename, body)
        manifest.update(summary)
    except BaseException as error:
        manifest["status"] = "FAILED"
        manifest["failure_code"] = (
            str(error) if isinstance(error, StaticBrowserError) else type(error).__name__
        )
        raise
    finally:
        if attempted:
            task = asyncio.create_task(cleanup())
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    manifest["status"] = "FAILED"
                    manifest["failure_code"] = "CANCELLED_DURING_CLEANUP"
                except Exception:
                    break
            try:
                manifest["cleanup_confirmed"] = task.result()
            except Exception:
                manifest["cleanup_confirmed"] = False
        if manifest["status"] == "IN_PROGRESS":
            manifest["status"] = "COMPLETED" if manifest["cleanup_confirmed"] else "FAILED"
            if manifest["status"] == "FAILED":
                manifest["failure_code"] = "CLEANUP_UNCONFIRMED"
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        manifest["content_hash"] = content_hash(manifest)
        with (output / "manifest.json").open("xb") as file:
            file.write(canonical_bytes(manifest) + b"\n")
    if manifest["status"] != "COMPLETED":
        raise StaticBrowserError("STATIC_BROWSER_EXECUTION_INCOMPLETE")
    return manifest
