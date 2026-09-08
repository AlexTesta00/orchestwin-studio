"""Build repository-owned Node/browser recipes and record local runner probes.

This opt-in operation creates Docker images and short-lived probe containers.
Builds may download pinned bases. Probes are network-isolated. Neither image
builds nor interpreter probes promote a profile to VALIDATED_LEVEL_D.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from orchestwin.sandbox.host_process import run_bounded_host_process

_BASE = re.compile(r"^FROM\s+[^\s]+@sha256:[0-9a-f]{64}\s*$", re.MULTILINE)
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_RECIPE_FILES = (
    "infra/web-runners/Dockerfile.node",
    "infra/web-runners/Dockerfile.browser",
    "infra/web-runners/bin/static-server.mjs",
)
_NODE_PROBE = r"""
import { mkdir, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
const uid = process.getuid();
if (uid === 0) throw new Error("root is prohibited");
await mkdir("/tmp/orchestwin-probe", { recursive: true });
await writeFile("/tmp/orchestwin-probe/index.html", "orchestwin-static-probe");
const child = spawn(process.execPath, ["/opt/orchestwin/bin/static-server.mjs",
  "--root", "/tmp/orchestwin-probe", "--port", "4173"], { stdio: "ignore" });
let ok = false;
try {
  for (let n = 0; n < 30; n++) {
    try {
      const response = await fetch("http://127.0.0.1:4173/", { signal: AbortSignal.timeout(500) });
      ok = response.status === 200 && await response.text() === "orchestwin-static-probe";
      if (ok) break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ok) throw new Error("static HTTP probe failed");
  console.log(JSON.stringify({ node_version: process.version, uid, static_http: ok }));
} finally {
  child.kill("SIGKILL");
}
"""
_BROWSER_PROBE = r"""
import { readdirSync } from "node:fs";
import { createRequire } from "node:module";
const uid = process.getuid();
if (uid === 0) throw new Error("root is prohibited");
const browser_binaries_present = readdirSync("/ms-playwright").some(name => name.startsWith("chromium"));
if (!browser_binaries_present) throw new Error("Chromium binaries missing");
let playwright_package_resolvable = false;
try { createRequire(import.meta.url).resolve("playwright"); playwright_package_resolvable = true; } catch {}
console.log(JSON.stringify({ node_version: process.version, uid,
  browser_binaries_present, playwright_package_resolvable }));
"""


class RunnerBootstrapError(RuntimeError):
    """Operator-safe error: never include raw Docker output or configuration."""


@dataclass(frozen=True, slots=True)
class CommandOutput:
    exit_code: int
    stdout: bytes
    stderr: bytes
    transport_status: str = "COMPLETED"


async def _run(argv: tuple[str, ...], *, timeout: int, limit: int) -> CommandOutput:
    result = await run_bounded_host_process(
        argv,
        timeout_seconds=timeout,
        maximum_output_bytes_per_stream=limit,
        environment_overrides={},
    )
    return CommandOutput(
        -1 if result.exit_code is None else result.exit_code,
        result.stdout,
        result.stderr,
        result.status,
    )


def _json(content: bytes):
    try:
        return json.loads(content)
    except (UnicodeError, ValueError):
        raise RunnerBootstrapError("COMMAND_RETURNED_INVALID_JSON") from None


def _write_manifest(path: Path, result: dict[str, object]) -> None:
    body = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = {**result, "content_hash": hashlib.sha256(body.encode()).hexdigest()}
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _recipe_bytes(root: Path) -> dict[str, bytes]:
    content = {}
    for relative in _RECIPE_FILES:
        path = root / relative
        if any(
            candidate.is_symlink() or candidate.is_junction() for candidate in (path, *path.parents)
        ):
            raise RunnerBootstrapError("RUNNER_RECIPE_REDIRECTED")
        content[relative] = path.read_bytes()
    for relative in _RECIPE_FILES[:2]:
        text = content[relative].decode("utf-8")
        from_lines = [
            line for line in text.splitlines() if line.strip().upper().startswith("FROM ")
        ]
        if len(from_lines) != 1 or _BASE.fullmatch(from_lines[0]) is None:
            raise RunnerBootstrapError("RUNNER_BASE_NOT_PINNED")
    return content


async def build_and_probe_local_web_runners(
    repo_root: Path,
    output_root: Path,
    *,
    runner=None,
) -> dict[str, object]:
    """Build two trusted recipes, probe observed images, preserve explicit limits."""
    root = Path(repo_root).resolve(strict=True)
    output = Path(output_root).absolute()
    if ".." in output.parts:
        raise RunnerBootstrapError("OUTPUT_PATH_NOT_CANONICAL")
    if output == root or root in output.parents:
        raise RunnerBootstrapError("OUTPUT_MUST_BE_OUTSIDE_REPOSITORY")
    if output.exists():
        raise RunnerBootstrapError("OUTPUT_ALREADY_EXISTS")
    if any(
        candidate.is_symlink() or candidate.is_junction() for candidate in (output, *output.parents)
    ):
        raise RunnerBootstrapError("OUTPUT_REDIRECTED")
    run = _run if runner is None else runner
    artifacts = []

    async def command(argv, label, *, timeout=30, log=False, required=True):
        observed = await run(tuple(argv), timeout=timeout, limit=8 * 1024 * 1024)
        if log:
            for stream in ("stdout", "stderr"):
                content = getattr(observed, stream)
                name = f"{label}.{stream}.log"
                (output / name).write_bytes(content)
                artifacts.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                    }
                )
        if required and (observed.exit_code != 0 or observed.transport_status != "COMPLETED"):
            raise RunnerBootstrapError(f"{label}_FAILED")
        return observed

    head = (
        (await command(("git", "-C", str(root), "rev-parse", "HEAD"), "GIT_HEAD"))
        .stdout.decode()
        .strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RunnerBootstrapError("GIT_HEAD_INVALID")
    dirty = await command(("git", "-C", str(root), "status", "--porcelain"), "GIT_STATUS")
    if dirty.stdout.strip():
        raise RunnerBootstrapError("WORKING_TREE_NOT_CLEAN_COMMIT_VERIFIED_CODE_FIRST")
    sources = _recipe_bytes(root)
    context = (await command(("docker", "context", "show"), "CONTEXT")).stdout.decode().strip()
    details = _json(
        (await command(("docker", "context", "inspect", context), "CONTEXT_INSPECT")).stdout
    )
    endpoint = details[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith(("npipe://", "unix://")):
        raise RunnerBootstrapError("LOCAL_DOCKER_CONTEXT_REQUIRED")
    docker = ("docker", "--context", context)
    info = _json(
        (
            await command(
                (*docker, "info", "--format", '{"os":"{{.OSType}}","arch":"{{.Architecture}}"}'),
                "DOCKER_INFO",
            )
        ).stdout
    )
    if info.get("os") != "linux" or info.get("arch") not in {"x86_64", "amd64"}:
        raise RunnerBootstrapError("LINUX_AMD64_ENGINE_REQUIRED")

    output.mkdir(parents=True)
    result = {
        "report_type": "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE",
        "status": "IN_PROGRESS",
        "platform_commit": head,
        "level_d_validated": False,
        "formal_run_started": False,
        "browser_automation_verified": False,
        "runners": [],
        "artifacts": artifacts,
        "recipes": [
            {"path": name, "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in sources.items()
        ],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="orchestwin-build-context-") as temporary:
            build_root = Path(temporary)
            for name, body in sources.items():
                path = build_root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            for kind, probe in (("node", _NODE_PROBE), ("browser", _BROWSER_PROBE)):
                tag = f"orchestwin/web-{kind}-runner:s12-{uuid4().hex}"
                await command(
                    (
                        *docker,
                        "build",
                        "--pull",
                        "--platform",
                        "linux/amd64",
                        "--file",
                        str(build_root / f"infra/web-runners/Dockerfile.{kind}"),
                        "--tag",
                        tag,
                        str(build_root),
                    ),
                    f"BUILD_{kind.upper()}",
                    timeout=900,
                    log=True,
                )
                images = _json(
                    (await command((*docker, "image", "inspect", tag), "IMAGE_INSPECT")).stdout
                )
                image = images[0]
                image_id = image.get("Id", "")
                if (
                    not _IMAGE_ID.fullmatch(image_id)
                    or image.get("Os") != "linux"
                    or image.get("Architecture") != "amd64"
                ):
                    raise RunnerBootstrapError("LOCAL_IMAGE_IDENTITY_INVALID")
                metadata = {
                    "kind": kind.upper(),
                    "local_tag": tag,
                    "image_id": image_id,
                    "image_id_kind": "LOCAL_CONFIG_DIGEST",
                    "registry_manifest_digest": None,
                }
                result["runners"].append(metadata)
                name = f"orchestwin-s12-probe-{uuid4().hex}"
                argv = (
                    *docker,
                    "run",
                    "--rm",
                    "--init",
                    "--name",
                    name,
                    "--pull=never",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges:true",
                    "--pids-limit",
                    "128",
                    "--memory",
                    "512m",
                    "--cpus",
                    "1",
                    "--user",
                    "65532:65532",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
                    image_id,
                    "node",
                    "--input-type=module",
                    "-e",
                    probe,
                )
                try:
                    observed = await command(argv, f"PROBE_{kind.upper()}", timeout=20, log=True)
                    observed_json = _json(observed.stdout)
                    if not isinstance(observed_json, dict) or observed_json.get("uid") != 65532:
                        raise RunnerBootstrapError("PROBE_USER_IDENTITY_INVALID")
                    if kind == "node" and observed_json.get("static_http") is not True:
                        raise RunnerBootstrapError("STATIC_HTTP_PROBE_FAILED")
                    if (
                        kind == "browser"
                        and observed_json.get("browser_binaries_present") is not True
                    ):
                        raise RunnerBootstrapError("BROWSER_BINARY_INVENTORY_FAILED")
                    metadata["probe"] = observed_json
                except BaseException:
                    # Only remove the specific probe container created by this operation.
                    cleanup = asyncio.create_task(
                        command(
                            (*docker, "rm", "--force", name),
                            "PROBE_CLEANUP",
                            required=False,
                        )
                    )
                    while not cleanup.done():
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            continue
                    metadata["cleanup_confirmed"] = cleanup.result().exit_code == 0
                    raise
        result["status"] = "IMAGES_BUILT_PROBES_RECORDED"
    except BaseException:
        result["status"] = "FAILED"
        _write_manifest(output / "manifest.json", result)
        raise
    _write_manifest(output / "manifest.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--build-runners",
        action="store_true",
        required=True,
        help="Authorize local image builds and pinned-base downloads.",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(build_and_probe_local_web_runners(args.repo_root, args.output_root))
    except (OSError, ValueError, KeyError, TypeError, IndexError, RunnerBootstrapError) as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": str(error)
                    if isinstance(error, RunnerBootstrapError)
                    else type(error).__name__,
                    "formal_run_started": False,
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
