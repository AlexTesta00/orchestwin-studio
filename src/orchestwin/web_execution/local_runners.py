"""Build pinned Node, PHP and locked browser recipes and record local probes.

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
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from orchestwin.sandbox.host_process import run_bounded_host_process
from orchestwin.web_execution.runner_bootstrap_inputs import load_bootstrap_inputs

_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_NODE_PROBE = r"""
import { mkdir, writeFile } from "node:fs/promises";
import { spawn, spawnSync } from "node:child_process";
const uid = process.getuid();
if (uid === 0) throw new Error("root is prohibited");
const npm = spawnSync("npm", ["--version"], { encoding: "utf8", timeout: 4000, maxBuffer: 65536 });
if (npm.status !== 0) throw new Error("npm version probe failed");
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
  console.log(JSON.stringify({ node_version: process.version, npm_version: npm.stdout.trim(), uid, static_http: ok }));
} finally {
  child.kill("SIGKILL");
}
"""
_BROWSER_PROBE = r"""
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
const uid = process.getuid();
if (uid === 0) throw new Error("root is prohibited");
const require = createRequire("/opt/orchestwin/browser-automation/package.json");
const playwright = require("playwright");
const executable = playwright.chromium.executablePath();
if (!existsSync(executable)) throw new Error("Chromium binaries missing");
const chromium = spawnSync(executable, ["--version"], { encoding: "utf8", timeout: 4000, maxBuffer: 65536 });
const npm = spawnSync("npm", ["--version"], { encoding: "utf8", timeout: 4000, maxBuffer: 65536 });
if (chromium.status !== 0 || npm.status !== 0) throw new Error("tool version probe failed");
console.log(JSON.stringify({ node_version: process.version, npm_version: npm.stdout.trim(), uid,
  browser_binaries_present: true, playwright_package_resolvable: true,
  playwright_version: require("playwright/package.json").version,
  playwright_core_version: require("playwright-core/package.json").version,
  axe_version: require("axe-core/package.json").version, chromium_version_output: chromium.stdout.trim(),
  package_lock_sha256: createHash("sha256").update(readFileSync("/opt/orchestwin/browser-automation/package-lock.json")).digest("hex") }));
"""
_PHP_PROBE = r"""
function runProbe(array $argv): array {
    $p = proc_open($argv, [0=>['pipe','r'],1=>['pipe','w'],2=>['pipe','w']], $pipes);
    if (!is_resource($p)) throw new RuntimeException('probe process failed');
    fclose($pipes[0]);
    $out = stream_get_contents($pipes[1]); fclose($pipes[1]);
    $err = stream_get_contents($pipes[2]); fclose($pipes[2]);
    return [proc_close($p), $out, $err];
}
$uid = posix_geteuid();
if ($uid === 0) throw new RuntimeException('root is prohibited');
$root = '/tmp/orchestwin-php-probe';
mkdir($root.'/valid', 0777, true); mkdir($root.'/invalid', 0777, true);
file_put_contents($root.'/valid/index.php', '<?php echo "orchestwin-php-probe";');
file_put_contents($root.'/invalid/broken.php', '<?php function (');
$composer = runProbe(['composer','--no-plugins','--no-scripts','--no-interaction','--no-ansi','--version']);
if ($composer[0] !== 0 || !preg_match('/Composer version (\d+\.\d+\.\d+)/', $composer[1], $version))
    throw new RuntimeException('Composer probe failed');
$valid = runProbe(['php','/opt/orchestwin/bin/php-lint.php',$root.'/valid']);
$invalid = runProbe(['php','/opt/orchestwin/bin/php-lint.php',$root.'/invalid']);
if ($valid[0] !== 0 || $invalid[0] === 0) throw new RuntimeException('PHP lint probe failed');
$server = proc_open(['php','-S','127.0.0.1:4173','-t',$root.'/valid'],
    [0=>['file','/dev/null','r'],1=>['file','/dev/null','w'],2=>['file','/dev/null','w']], $pipes);
if (!is_resource($server)) throw new RuntimeException('PHP server failed');
$ok = false;
try {
    $options = stream_context_create(['http'=>['timeout'=>0.3]]);
    for ($i=0; $i<30; $i++) {
        if (@file_get_contents('http://127.0.0.1:4173/', false, $options) === 'orchestwin-php-probe') { $ok=true; break; }
        usleep(100000);
    }
    if (!$ok) throw new RuntimeException('PHP HTTP probe failed');
    echo json_encode(['uid'=>$uid,'php_version'=>PHP_VERSION,'composer_version'=>$version[1],
        'php_lint_valid'=>true,'php_lint_invalid_rejected'=>true,'php_http'=>true], JSON_THROW_ON_ERROR);
} finally { proc_terminate($server, 9); proc_close($server); }
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


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _write_manifest(path: Path, result: dict[str, object]) -> dict[str, object]:
    payload = {**result, "content_hash": _hash(result)}
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def _observed_text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or value != value.strip()
        or any(ord(c) < 32 for c in value)
    ):
        raise RunnerBootstrapError("OBSERVED_METADATA_INVALID")
    return value


def _probe_metadata(kind, observed, recipe, sources):
    if (
        not isinstance(observed, dict)
        or type(observed.get("uid")) is not int
        or observed["uid"] != 65532
    ):
        raise RunnerBootstrapError("PROBE_USER_IDENTITY_INVALID")
    flags = {
        "NODE": ("static_http",),
        "PHP": ("php_lint_valid", "php_lint_invalid_rejected", "php_http"),
        "BROWSER": ("browser_binaries_present", "playwright_package_resolvable"),
    }[kind]
    if any(observed.get(flag) is not True for flag in flags):
        raise RunnerBootstrapError("RUNNER_FUNCTION_PROBE_FAILED")
    names = (
        ("php_version", "composer_version") if kind == "PHP" else ("node_version", "npm_version")
    )
    if kind == "BROWSER":
        names += (
            "playwright_version",
            "playwright_core_version",
            "axe_version",
            "chromium_version_output",
            "package_lock_sha256",
        )
    metadata = {"uid": 65532, **{flag: True for flag in flags}}
    metadata.update({name: _observed_text(observed.get(name)) for name in names})
    for name in names:
        if name.endswith("version") and not re.fullmatch(
            r"v?\d+\.\d+\.\d+(?:[.\w+-]*)?", metadata[name]
        ):
            raise RunnerBootstrapError("RUNNER_TOOL_VERSION_INVALID")
    if kind == "BROWSER":
        # Playwright's Chromium distribution may identify as Chrome for Testing.
        # Retain the observed product string and derive the numeric version here.
        version = re.fullmatch(
            r"(?:Chromium|Google Chrome for Testing) (\d+\.\d+\.\d+\.\d+)",
            metadata["chromium_version_output"],
        )
        if version is None:
            raise RunnerBootstrapError("RUNNER_BROWSER_VERSION_INVALID")
        metadata["chromium_version"] = version.group(1)
        lock_bytes = sources["infra/web-runners/browser-locked/package-lock.json"]
        packages = _json(lock_bytes)["packages"]
        for field, package in (
            ("playwright_version", "playwright"),
            ("playwright_core_version", "playwright-core"),
            ("axe_version", "axe-core"),
        ):
            if metadata[field] != packages[f"node_modules/{package}"]["version"]:
                raise RunnerBootstrapError("RUNNER_TOOL_VERSION_MISMATCH")
        if metadata["package_lock_sha256"] != hashlib.sha256(lock_bytes).hexdigest():
            raise RunnerBootstrapError("RUNNER_LOCK_IDENTITY_MISMATCH")
    else:
        for tool in ("node",) if kind == "NODE" else ("php", "composer"):
            versions = [
                match.group(1)
                for reference in recipe.base_image_references
                if (match := re.search(rf"/{tool}:(\d+\.\d+\.\d+)(?:[-@])", reference))
            ]
            if len(versions) != 1 or metadata[f"{tool}_version"].removeprefix("v") != versions[0]:
                raise RunnerBootstrapError("RUNNER_TOOL_VERSION_MISMATCH")
    return metadata


async def build_and_probe_local_web_runners(
    repo_root: Path,
    output_root: Path,
    *,
    runner=None,
) -> dict[str, object]:
    """Build committed trusted recipes; record tool probes without profile promotion."""
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
    try:
        inputs = load_bootstrap_inputs(root)
    except ValueError as error:
        code = str(error)
        if code == "BOOTSTRAP_DOCKERFILE_BASE_NOT_PINNED":
            code = "RUNNER_BASE_NOT_PINNED"
        raise RunnerBootstrapError(code) from None
    sources = dict(inputs.sources)
    for path, content in sources.items():
        committed = await command(("git", "-C", str(root), "show", f"{head}:{path}"), "GIT_RECIPE")
        if committed.stdout != content:
            raise RunnerBootstrapError("RECIPE_BYTES_DO_NOT_MATCH_COMMITTED_TREE")
    context = (await command(("docker", "context", "show"), "CONTEXT")).stdout.decode().strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", context):
        raise RunnerBootstrapError("DOCKER_CONTEXT_NAME_INVALID")
    details = _json(
        (await command(("docker", "context", "inspect", context), "CONTEXT_INSPECT")).stdout
    )
    endpoint = details[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith(("npipe://", "unix://")):
        raise RunnerBootstrapError("LOCAL_DOCKER_CONTEXT_REQUIRED")
    docker = ("docker", "--context", context)
    builder = (
        await command((*docker, "buildx", "inspect", context), "BUILDER_INSPECT")
    ).stdout.decode()
    if re.findall(r"^Driver:\s*(\S+)\s*$", builder, re.MULTILINE) != ["docker"] or re.findall(
        r"^Endpoint:\s*(\S+)\s*$", builder, re.MULTILINE
    ) != [context]:
        raise RunnerBootstrapError("LOCAL_CONTEXT_DOCKER_BUILDER_REQUIRED")
    info = _json(
        (
            await command(
                (
                    *docker,
                    "info",
                    "--format",
                    '{"os":{{json .OSType}},"arch":{{json .Architecture}},'
                    '"kernel_version":{{json .KernelVersion}},'
                    '"operating_system":{{json .OperatingSystem}}}',
                ),
                "DOCKER_INFO",
            )
        ).stdout
    )
    if info.get("os") != "linux" or info.get("arch") not in {"x86_64", "amd64"}:
        raise RunnerBootstrapError("LINUX_AMD64_ENGINE_REQUIRED")
    version = _json(
        (
            await command(
                (
                    *docker,
                    "version",
                    "--format",
                    '{"client_version":{{json .Client.Version}},"server_version":{{json .Server.Version}}}',
                ),
                "DOCKER_VERSION",
            )
        ).stdout
    )
    environment = {
        "docker_context": context,
        "builder_driver": "docker",
        "platform": "linux/amd64",
        **{
            key: _observed_text(info.get(key))
            for key in ("os", "arch", "kernel_version", "operating_system")
        },
        **{key: _observed_text(version.get(key)) for key in ("client_version", "server_version")},
    }

    output.mkdir(parents=True)
    result = {
        "schema_version": 2,
        "report_type": "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE",
        "status": "IN_PROGRESS",
        "started_at": datetime.now(UTC).isoformat(),
        "platform_commit": head,
        "bootstrap_inputs_hash": inputs.content_hash,
        "environment": environment,
        "environment_hash": _hash(environment),
        "probe_policy": {
            "network": "none",
            "read_only": True,
            "uid": 65532,
            "gid": 65532,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "memory_bytes": 512 * 1024 * 1024,
            "cpus": 1,
            "pids_limit": 128,
            "tmpfs": "/tmp:rw,noexec,nosuid,size=64m,mode=1777",
            "host_mounts": False,
            "timeout_seconds": 20,
            "maximum_output_bytes_per_stream": 8 * 1024 * 1024,
        },
        "level_d_validated": False,
        "formal_run_started": False,
        "browser_automation_verified": False,
        "runners": [],
        "artifacts": artifacts,
        "recipes": [
            {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
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
            for recipe in inputs.runners:
                kind = recipe.kind.lower()
                build_network = "default" if recipe.kind == "BROWSER" else "none"
                tag = f"orchestwin/web-{kind}-runner:s12-{uuid4().hex}"
                await command(
                    (
                        *docker,
                        "build",
                        "--builder",
                        context,
                        "--pull",
                        "--platform",
                        "linux/amd64",
                        "--network",
                        build_network,
                        "--file",
                        str(build_root / recipe.dockerfile_path),
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
                    "runner_id": recipe.runner_id,
                    "runner_version": recipe.version,
                    "recipe_content_hash": recipe.recipe_content_hash,
                    "source_paths": list(recipe.source_paths),
                    "base_image_references": list(recipe.base_image_references),
                    "build_network": build_network,
                    "local_tag": tag,
                    "image_id": image_id,
                    "image_id_kind": "LOCAL_CONFIG_DIGEST",
                    "registry_manifest_digest": None,
                }
                result["runners"].append(metadata)
                name = f"orchestwin-s12-probe-{uuid4().hex}"
                probe_command = {
                    "NODE": ("node", "--input-type=module", "-e", _NODE_PROBE),
                    "PHP": ("php", "-r", _PHP_PROBE),
                    "BROWSER": ("node", "--input-type=module", "-e", _BROWSER_PROBE),
                }[recipe.kind]
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
                    "--env",
                    "HOME=/tmp",
                    "--env",
                    "COMPOSER_HOME=/tmp/orchestwin-composer",
                    image_id,
                    *probe_command,
                )
                try:
                    observed = await command(argv, f"PROBE_{kind.upper()}", timeout=20, log=True)
                    metadata["probe"] = _probe_metadata(
                        recipe.kind, _json(observed.stdout), recipe, sources
                    )
                finally:
                    # Only remove the specific probe container created by this operation.
                    cleanup = asyncio.create_task(
                        command(
                            (*docker, "rm", "--force", name),
                            "PROBE_CLEANUP",
                            required=False,
                        )
                    )
                    cancelled_during_cleanup = False
                    while not cleanup.done():
                        try:
                            await asyncio.shield(cleanup)
                        except asyncio.CancelledError:
                            cancelled_during_cleanup = True
                    cleanup_result = cleanup.result()
                    metadata["cleanup_confirmed"] = (
                        cleanup_result.transport_status == "COMPLETED"
                        and (
                            cleanup_result.exit_code == 0
                            or cleanup_result.stderr.decode(errors="replace").strip()
                            == f"Error response from daemon: No such container: {name}"
                        )
                    )
                    if not metadata["cleanup_confirmed"]:
                        raise RunnerBootstrapError("PROBE_CLEANUP_NOT_CONFIRMED")
                    if cancelled_during_cleanup:
                        raise asyncio.CancelledError
        final_head = await command(("git", "-C", str(root), "rev-parse", "HEAD"), "GIT_HEAD")
        final_status = await command(
            ("git", "-C", str(root), "status", "--porcelain"), "GIT_STATUS"
        )
        if final_head.stdout.decode().strip() != head or final_status.stdout.strip():
            raise RunnerBootstrapError("WORKING_TREE_CHANGED_DURING_BOOTSTRAP")
        result["status"] = "IMAGES_BUILT_PROBES_RECORDED"
    except BaseException:
        result["status"] = "FAILED"
        result["finished_at"] = datetime.now(UTC).isoformat()
        _write_manifest(output / "manifest.json", result)
        raise
    result["finished_at"] = datetime.now(UTC).isoformat()
    return _write_manifest(output / "manifest.json", result)


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
