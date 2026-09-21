"""Build pinned browser tooling and verify a trusted offline infrastructure fixture.

This command does not execute generated projects, use owner gates, promote a
profile, or modify an earlier observation. Docker builds use the network; the
actual browser probe has no network or host mounts. All result flags are based
on the observed probe, not on image-build success.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import re
import struct
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from orchestwin.sandbox.host_process import run_bounded_host_process

BASE_COMMIT = "54d743626ea9e354417919c45362bc42d6f0aef3"
TOOL_ROOT = "infra/web-runners/browser-automation"
RECIPE_NAMES = ("Dockerfile", "package.json", "probe.cjs", "fixture.html", "seccomp.json")
PARENT_RECIPES = (
    "infra/web-runners/Dockerfile.node",
    "infra/web-runners/Dockerfile.browser",
    "infra/web-runners/bin/static-server.mjs",
)
VERSIONS = {"playwright": "1.62.1", "playwright-core": "1.62.1", "axe-core": "4.13.0"}
CHECKS = (
    "browser_launched",
    "local_navigation",
    "pointer_activation",
    "keyboard_activation",
    "external_request_blocked",
    "axe_executed",
    "axe_negative_control",
    "two_viewports_captured",
    "chromium_sandbox_requested",
    "chromium_no_sandbox_flag_absent",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_FILE = 2 * 1024 * 1024


class AutomationError(RuntimeError):
    """Stable public error code without credentials or arbitrary command output."""


def canonical_hash(value: object) -> str:
    """Use the same canonical content hash as the C59 manifest."""
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _object_pairs(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise AutomationError("DUPLICATE_JSON_KEY")
        data[key] = value
    return data


def _reject_constant(_value):
    raise AutomationError("NONFINITE_JSON_NUMBER")


def _json(data: bytes) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
    except (UnicodeError, ValueError):
        raise AutomationError("INVALID_JSON") from None


def _safe_path(path: Path) -> None:
    if ".." in path.parts:
        raise AutomationError("NONCANONICAL_PATH")
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise AutomationError("REDIRECTED_PATH")


def _read(path: Path, limit: int = _MAX_FILE) -> bytes:
    _safe_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise AutomationError("INPUT_MISSING_OR_TOO_LARGE")
    with path.open("rb") as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise AutomationError("INPUT_TOO_LARGE")
    return data


def verify_parent_manifest(path: Path, repo_root: Path) -> dict[str, Any]:
    """Verify the parent hash, every log, and the unchanged original recipes.

    These hashes establish local lineage/integrity, not an external attestation.
    """
    value = _json(_read(path))
    if not isinstance(value, dict) or "content_hash" not in value:
        raise AutomationError("PARENT_MANIFEST_SHAPE_INVALID")
    content = {key: item for key, item in value.items() if key != "content_hash"}
    if canonical_hash(content) != value["content_hash"]:
        raise AutomationError("PARENT_MANIFEST_HASH_MISMATCH")
    if (
        value.get("report_type") != "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE"
        or value.get("status") != "IMAGES_BUILT_PROBES_RECORDED"
        or value.get("platform_commit") != BASE_COMMIT
        or any(
            value.get(flag) is not False
            for flag in ("formal_run_started", "level_d_validated", "browser_automation_verified")
        )
    ):
        raise AutomationError("PARENT_MANIFEST_OUTSIDE_SUPPORTED_BASELINE")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16:
        raise AutomationError("PARENT_ARTIFACTS_INVALID")
    names = set()
    total = 0
    for item in artifacts:
        name = item.get("path", "") if isinstance(item, dict) else ""
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.(?:stdout|stderr)\.log", name):
            raise AutomationError("PARENT_ARTIFACT_PATH_INVALID")
        if name in names:
            raise AutomationError("PARENT_ARTIFACT_DUPLICATED")
        names.add(name)
        data = _read(path.parent / name, 8 * 1024 * 1024)
        total += len(data)
        if (
            type(item.get("size_bytes")) is not int
            or len(data) != item["size_bytes"]
            or hashlib.sha256(data).hexdigest() != item.get("sha256")
        ):
            raise AutomationError("PARENT_ARTIFACT_MISMATCH")
        if total > 64 * 1024 * 1024:
            raise AutomationError("PARENT_ARTIFACT_LIMIT_EXCEEDED")
    recipes = value.get("recipes")
    if not isinstance(recipes, list) or len(recipes) != len(PARENT_RECIPES):
        raise AutomationError("PARENT_RECIPES_INVALID")
    if {item.get("path") for item in recipes} != set(PARENT_RECIPES):
        raise AutomationError("PARENT_RECIPE_PATH_INVALID")
    for item in recipes:
        data = _read(repo_root / item["path"])
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise AutomationError("ORIGINAL_RECIPE_CHANGED")
    runners = value.get("runners")
    if not isinstance(runners, list) or len(runners) != 2:
        raise AutomationError("PARENT_RUNNERS_INVALID")
    if {item.get("kind") for item in runners} != {"NODE", "BROWSER"}:
        raise AutomationError("PARENT_RUNNERS_INVALID")
    for item in runners:
        if (
            not _IMAGE.fullmatch(item.get("image_id", ""))
            or item.get("image_id_kind") != "LOCAL_CONFIG_DIGEST"
        ):
            raise AutomationError("PARENT_IMAGE_IDENTITY_INVALID")
        probe = item.get("probe", {})
        flag = "static_http" if item["kind"] == "NODE" else "browser_binaries_present"
        if probe.get("uid") != 65532 or probe.get(flag) is not True:
            raise AutomationError("PARENT_PROBE_INVALID")
    return value


def validate_lock(lock: object) -> None:
    """Check the observed npm lock; npm ci verifies downloaded package integrity."""
    if not isinstance(lock, dict) or lock.get("lockfileVersion") != 3:
        raise AutomationError("DEPENDENCY_LOCK_INVALID")
    packages = lock.get("packages", {})
    required = {f"node_modules/{name}" for name in VERSIONS}
    allowed = {"", *required, "node_modules/fsevents"}
    if (
        not isinstance(packages, dict)
        or not required <= packages.keys()
        or not packages.keys() <= allowed
    ):
        raise AutomationError("DEPENDENCY_GRAPH_UNEXPECTED")
    if packages.get("", {}).get("dependencies") != {"axe-core": "4.13.0", "playwright": "1.62.1"}:
        raise AutomationError("DEPENDENCY_ROOT_MISMATCH")
    for name, package in packages.items():
        if not name:
            continue
        if not isinstance(package, dict):
            raise AutomationError("DEPENDENCY_METADATA_INVALID")
        short_name = name.removeprefix("node_modules/")
        version = VERSIONS.get(short_name, "2.3.2")
        expected_url = f"https://registry.npmjs.org/{short_name}/-/{short_name}-{version}.tgz"
        if package.get("version") != version or package.get("resolved") != expected_url:
            raise AutomationError("DEPENDENCY_VERSION_OR_SOURCE_MISMATCH")
        integrity = package.get("integrity", "")
        if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
            raise AutomationError("DEPENDENCY_INTEGRITY_INVALID")
        try:
            raw = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
        except (ValueError, binascii.Error):
            raise AutomationError("DEPENDENCY_INTEGRITY_INVALID") from None
        if len(raw) != 64:
            raise AutomationError("DEPENDENCY_INTEGRITY_INVALID")


def _decode_artifact(value: object) -> bytes:
    keys = {"encoding", "content", "size_bytes", "sha256"}
    if not isinstance(value, dict) or set(value) != keys or value["encoding"] != "base64":
        raise AutomationError("PROBE_ARTIFACT_INVALID")
    if (
        type(value["size_bytes"]) is not int
        or not 0 < value["size_bytes"] <= _MAX_FILE
        or not isinstance(value["content"], str)
        or len(value["content"]) > _MAX_FILE * 2
    ):
        raise AutomationError("PROBE_ARTIFACT_LIMIT")
    try:
        data = base64.b64decode(value["content"], validate=True)
    except (ValueError, binascii.Error):
        raise AutomationError("PROBE_ARTIFACT_ENCODING_INVALID") from None
    if len(data) != value["size_bytes"] or hashlib.sha256(data).hexdigest() != value["sha256"]:
        raise AutomationError("PROBE_ARTIFACT_HASH_MISMATCH")
    return data


def decode_probe(raw: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Require complete observed screenshots, DOM, interaction and axe evidence."""
    data = _json(raw)
    if (
        not isinstance(data, dict)
        or data.get("status") != "PASSED"
        or data.get("schema_version") != 1
        or data.get("uid") != 65532
        or data.get("probe_kind") != "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE"
    ):
        raise AutomationError("BROWSER_PROBE_NOT_PASSED")
    versions = data.get("versions", {})
    if (
        versions.get("playwright") != "1.62.1"
        or versions.get("axe_core") != "4.13.0"
        or not isinstance(versions.get("chromium"), str)
        or not versions["chromium"]
    ):
        raise AutomationError("BROWSER_TOOLCHAIN_MISMATCH")
    checks = data.get("checks", {})
    if set(checks) != set(CHECKS) or any(checks[name] is not True for name in CHECKS):
        raise AutomationError("BROWSER_CHECKS_INCOMPLETE")
    screens = data.get("screens", [])
    if not isinstance(screens, list) or len(screens) != 2:
        raise AutomationError("BROWSER_SCREENSHOTS_INCOMPLETE")
    artifacts = {}
    summaries = []
    for screen, expected in zip(screens, (("narrow", 390, 844), ("wide", 1280, 800)), strict=True):
        name, width, height = expected
        if (
            (screen.get("name"), screen.get("width"), screen.get("height")) != expected
            or screen.get("pointer") != "Activations: 1"
            or screen.get("keyboard") != "Activations: 2"
            or screen.get("blocked_requests") != 1
        ):
            raise AutomationError("BROWSER_INTERACTION_MISMATCH")
        png = _decode_artifact(screen.get("screenshot"))
        if (
            len(png) < 33
            or png[:8] != b"\x89PNG\r\n\x1a\n"
            or png[12:16] != b"IHDR"
            or struct.unpack(">II", png[16:24]) != (width, height)
        ):
            raise AutomationError("BROWSER_SCREENSHOT_INVALID")
        dom = _decode_artifact(screen.get("dom"))
        if "<html" not in dom.decode("utf-8").casefold():
            raise AutomationError("BROWSER_DOM_INVALID")
        axe = _decode_artifact(screen.get("axe"))
        axe_data = _json(axe)
        if axe_data.get("testEngine", {}).get("version") != "4.13.0" or not isinstance(
            axe_data.get("violations"), list
        ):
            raise AutomationError("AXE_REPORT_INVALID")
        artifacts[f"{name}.png"] = png
        artifacts[f"{name}.html"] = dom
        artifacts[f"{name}.axe.json"] = axe
        summaries.append(
            {
                "viewport": name,
                "width": width,
                "height": height,
                "axe_violation_rules": len(axe_data["violations"]),
            }
        )
    negative = _decode_artifact(data.get("negative_axe"))
    negative_data = _json(negative)
    if negative_data.get("testEngine", {}).get("version") != "4.13.0" or not any(
        item.get("id") == "button-name" for item in negative_data.get("violations", [])
    ):
        raise AutomationError("AXE_NEGATIVE_CONTROL_MISSING")
    lock = _decode_artifact(data.get("package_lock"))
    validate_lock(_json(lock))
    events = _decode_artifact(data.get("events"))
    event_list = _json(events)
    if not isinstance(event_list, list) or len(event_list) > 100:
        raise AutomationError("BROWSER_EVENTS_INVALID")
    artifacts.update(
        {
            "negative-control.axe.json": negative,
            "package-lock.observed.json": lock,
            "browser-events.json": events,
        }
    )
    return {
        "versions": versions,
        "checks": checks,
        "screens": summaries,
        "negative_control_is_a_fixture_not_a_user_finding": True,
    }, artifacts


def make_probe_arguments(docker, image_id, name, operation_id, seccomp_path):
    """No host bind mounts, sockets, external network, root or broad capabilities."""
    return (
        *docker,
        "create",
        "--init",
        "--name",
        name,
        "--label",
        f"org.orchestwin.browser-probe={operation_id}",
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
        image_id,
    )


async def _run(argv, timeout=30):
    return await run_bounded_host_process(
        tuple(argv),
        timeout_seconds=timeout,
        maximum_output_bytes_per_stream=8 * 1024 * 1024,
        environment_overrides={},
    )


def _successful(result) -> bool:
    return result.status == "COMPLETED" and result.exit_code == 0


def _recipe_files(root):
    files = {name: _read(root / TOOL_ROOT / name) for name in RECIPE_NAMES}
    original = _read(root / "infra/web-runners/Dockerfile.browser").decode("utf-8")
    derived = files["Dockerfile"].decode("utf-8")
    from_original = [line.strip() for line in original.splitlines() if line.startswith("FROM ")]
    from_derived = [line.strip() for line in derived.splitlines() if line.startswith("FROM ")]
    if (
        len(from_original) != 1
        or from_derived != from_original
        or not re.fullmatch(
            r"FROM mcr\.microsoft\.com/playwright:v1\.62\.1-noble@sha256:[0-9a-f]{64}",
            from_original[0],
        )
    ):
        raise AutomationError("BROWSER_BASE_CHANGED")
    return files


async def verify_browser_automation(
    repo_root: Path, parent_manifest: Path, output_root: Path, *, runner=None
) -> dict[str, Any]:
    """Opt-in real build/probe operation; fake transports are supplied only by tests."""
    root = repo_root.resolve(strict=True)
    output = output_root.absolute()
    _safe_path(output)
    if output == root or root in output.parents or output.exists():
        raise AutomationError("OUTPUT_MUST_BE_NEW_AND_OUTSIDE_REPOSITORY")
    parent = verify_parent_manifest(parent_manifest.absolute(), root)
    parent_bytes = _read(parent_manifest)
    if _json(parent_bytes) != parent:
        raise AutomationError("PARENT_CHANGED_DURING_VERIFICATION")
    sources = _recipe_files(root)
    execute = _run if runner is None else runner
    manifest = {
        "report_type": "LOCAL_BROWSER_AUTOMATION_NOT_FORMAL_EVIDENCE",
        "schema_version": 1,
        "status": "IN_PROGRESS",
        "started_at": datetime.now(UTC).isoformat(),
        "formal_run_started": False,
        "level_d_validated": False,
        "browser_automation_verified": False,
        "generated_projects_authorized": False,
        "browser_sandbox_kernel_audit": "NOT_PERFORMED",
        "parent_content_hash": parent["content_hash"],
        "parent_platform_commit": BASE_COMMIT,
        "parent_image_ids": {item["kind"]: item["image_id"] for item in parent["runners"]},
        "artifacts": [],
        "cleanup_confirmed": None,
        "recipes": [
            {"path": f"{TOOL_ROOT}/{name}", "sha256": hashlib.sha256(body).hexdigest()}
            for name, body in sources.items()
        ],
    }

    def store(name, body):
        with (output / name).open("xb") as file:
            file.write(body)
        manifest["artifacts"].append(
            {"path": name, "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        )

    async def command(argv, label, *, timeout=30, logs=False, required=True):
        print(f"[{label}]", flush=True)
        observed = await execute(tuple(argv), timeout=timeout)
        if logs:
            store(f"{label}.stdout.log", observed.stdout)
            store(f"{label}.stderr.log", observed.stderr)
        if required and not _successful(observed):
            raise AutomationError(f"{label}_FAILED")
        return observed

    head = (
        (await command(("git", "-C", str(root), "rev-parse", "HEAD"), "GIT_HEAD"))
        .stdout.decode()
        .strip()
    )
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise AutomationError("GIT_HEAD_INVALID")
    if (
        await command(("git", "-C", str(root), "status", "--porcelain"), "GIT_STATUS")
    ).stdout.strip():
        raise AutomationError("COMMIT_VERIFIED_CODE_FIRST")
    await command(
        ("git", "-C", str(root), "merge-base", "--is-ancestor", BASE_COMMIT, head), "BASE_ANCESTRY"
    )
    for name, body in sources.items():
        committed = await command(
            ("git", "-C", str(root), "show", f"HEAD:{TOOL_ROOT}/{name}"), "RECIPE_TRACKED"
        )
        if committed.stdout.replace(b"\r\n", b"\n") != body.replace(b"\r\n", b"\n"):
            raise AutomationError("RECIPE_NOT_COMMITTED")
    context = (await command(("docker", "context", "show"), "CONTEXT")).stdout.decode().strip()
    details = _json(
        (await command(("docker", "context", "inspect", context), "CONTEXT_INSPECT")).stdout
    )
    if not details[0]["Endpoints"]["docker"]["Host"].startswith(("npipe://", "unix://")):
        raise AutomationError("LOCAL_DOCKER_CONTEXT_REQUIRED")
    docker = ("docker", "--context", context)
    info = _json(
        (
            await command(
                (*docker, "info", "--format", '{"os":"{{.OSType}}","arch":"{{.Architecture}}"}'),
                "ENGINE",
            )
        ).stdout
    )
    if info.get("os") != "linux" or info.get("arch") not in {"amd64", "x86_64"}:
        raise AutomationError("LINUX_AMD64_ENGINE_REQUIRED")
    manifest["platform_commit"] = head
    output.mkdir(parents=True)
    store("parent-manifest.json", parent_bytes)
    operation_id = uuid4().hex
    name = f"orchestwin-browser-probe-{operation_id}"
    tag = f"orchestwin/web-browser-automation:s12-{operation_id}"
    container_attempted = False

    async def cleanup():
        # Delete only the uniquely named container carrying our operation label.
        inspected = await command(
            (*docker, "container", "inspect", name), "CLEANUP_INSPECT", required=False
        )
        if not _successful(inspected):
            return False
        labels = _json(inspected.stdout)[0].get("Config", {}).get("Labels", {}) or {}
        if labels.get("org.orchestwin.browser-probe") != operation_id:
            return False
        removed = await command((*docker, "rm", "--force", name), "CLEANUP_REMOVE", required=False)
        return _successful(removed)

    try:
        with tempfile.TemporaryDirectory(prefix="orchestwin-browser-build-") as temp:
            context_root = Path(temp)
            # Exactly five trusted files. No repository, dotenv, Docker socket or training.
            for file_name, body in sources.items():
                (context_root / file_name).write_bytes(body)
            await command(
                (
                    *docker,
                    "build",
                    "--pull",
                    "--platform",
                    "linux/amd64",
                    "--tag",
                    tag,
                    "--file",
                    str(context_root / "Dockerfile"),
                    str(context_root),
                ),
                "BUILD_AUTOMATION",
                timeout=900,
                logs=True,
            )
            image = _json(
                (await command((*docker, "image", "inspect", tag), "IMAGE_INSPECT")).stdout
            )[0]
            image_id = image.get("Id", "")
            if (
                not _IMAGE.fullmatch(image_id)
                or image.get("Os") != "linux"
                or image.get("Architecture") != "amd64"
            ):
                raise AutomationError("AUTOMATION_IMAGE_INVALID")
            manifest["runner"] = {
                "local_tag": tag,
                "image_id": image_id,
                "image_id_kind": "LOCAL_CONFIG_DIGEST",
                "registry_manifest_digest": None,
            }
            # Store the seccomp policy in the evidence directory too, before creating the container.
            store("seccomp.json", sources["seccomp.json"])
            container_attempted = True
            await command(
                make_probe_arguments(docker, image_id, name, operation_id, output / "seccomp.json"),
                "CREATE_PROBE",
                logs=True,
            )
            probe = await command(
                (*docker, "start", "--attach", name), "BROWSER_PROBE", timeout=100, logs=True
            )
            summary, files = decode_probe(probe.stdout)
            for artifact_name, body in files.items():
                store(artifact_name, body)
            manifest["probe"] = summary
    except BaseException as error:
        manifest["status"] = "FAILED"
        manifest["failure_code"] = (
            str(error) if isinstance(error, AutomationError) else type(error).__name__
        )
        raise
    finally:
        if container_attempted:
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
            if manifest["cleanup_confirmed"] is True:
                manifest["status"] = "BROWSER_AUTOMATION_PROBE_PASSED"
                manifest["browser_automation_verified"] = True
            else:
                manifest["status"] = "FAILED"
                manifest["failure_code"] = "PROBE_CLEANUP_UNCONFIRMED"
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        manifest["content_hash"] = canonical_hash(manifest)
        with (output / "manifest.json").open("x", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if manifest["status"] != "BROWSER_AUTOMATION_PROBE_PASSED":
        raise AutomationError(manifest.get("failure_code", "PROBE_FAILED"))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--parent-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--build-browser-runner",
        action="store_true",
        required=True,
        help="Authorize the image build, npm downloads and trusted browser probe.",
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(
            verify_browser_automation(args.repo_root, args.parent_manifest, args.output_root)
        )
    except (AutomationError, OSError, ValueError, TypeError, KeyError, IndexError) as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": str(error)
                    if isinstance(error, AutomationError)
                    else type(error).__name__,
                    "formal_run_started": False,
                }
            )
        )
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
