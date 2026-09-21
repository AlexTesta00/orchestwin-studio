"""Import a successful local browser observation without rebuilding its image.

Local hashes bind bytes and lineage, not an external signature or a security audit.
A successful fixture does not grant permission to execute a generated project.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from orchestwin.web_execution.static_browser_jobs import StaticBrowserError, content_hash

CHECK_NAMES = frozenset(
    {
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
    }
)
MAX_LOG = 16 * 1024 * 1024


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise StaticBrowserError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value):
    raise StaticBrowserError("NONFINITE_JSON")


def read_json(data: bytes):
    try:
        return json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, StaticBrowserError):
            raise
        raise StaticBrowserError("INVALID_JSON") from None


def read_regular(path: Path, limit: int = MAX_LOG) -> bytes:
    path = Path(path).absolute()
    if ".." in path.parts or any(
        item.is_symlink() or item.is_junction() for item in (path, *path.parents)
    ):
        raise StaticBrowserError("REDIRECTED_PATH")
    if not path.is_file() or path.stat().st_size > limit:
        raise StaticBrowserError("FILE_MISSING_OR_TOO_LARGE")
    with path.open("rb") as file:
        data = file.read(limit + 1)
    if len(data) > limit:
        raise StaticBrowserError("FILE_TOO_LARGE")
    return data


def artifact_bytes(value: object, *, maximum: int = 2 * 1024 * 1024) -> bytes:
    if not isinstance(value, dict) or set(value) != {"encoding", "content", "sha256", "size_bytes"}:
        raise StaticBrowserError("ARTIFACT_ENVELOPE_INVALID")
    if (
        value["encoding"] != "base64"
        or type(value["size_bytes"]) is not int
        or not 0 < value["size_bytes"] <= maximum
        or not isinstance(value["content"], str)
        or len(value["content"]) > maximum * 2
    ):
        raise StaticBrowserError("ARTIFACT_SIZE_INVALID")
    try:
        data = base64.b64decode(value["content"], validate=True)
    except ValueError:
        raise StaticBrowserError("ARTIFACT_BASE64_INVALID") from None
    if len(data) != value["size_bytes"] or hashlib.sha256(data).hexdigest() != value["sha256"]:
        raise StaticBrowserError("ARTIFACT_HASH_MISMATCH")
    return data


@dataclass(frozen=True, slots=True)
class VerifiedBrowserRunner:
    manifest_content_hash: str
    image_id: str
    seccomp_bytes: bytes
    manifest_bytes: bytes
    platform_commit: str


def verify_browser_runner(manifest_path: Path, repo_root: Path) -> VerifiedBrowserRunner:
    """Verify all recorded files and that tool recipes still match the observation."""
    body = read_regular(manifest_path, 1024 * 1024)
    manifest = read_json(body)
    if not isinstance(manifest, dict):
        raise StaticBrowserError("BROWSER_MANIFEST_INVALID")
    digest = manifest.get("content_hash")
    if digest != content_hash(
        {key: item for key, item in manifest.items() if key != "content_hash"}
    ):
        raise StaticBrowserError("BROWSER_MANIFEST_HASH_MISMATCH")
    if (
        manifest.get("report_type") != "LOCAL_BROWSER_AUTOMATION_NOT_FORMAL_EVIDENCE"
        or manifest.get("schema_version") != 1
        or manifest.get("status") != "BROWSER_AUTOMATION_PROBE_PASSED"
        or manifest.get("browser_automation_verified") is not True
        or manifest.get("cleanup_confirmed") is not True
        or any(
            manifest.get(key) is not False
            for key in ("formal_run_started", "level_d_validated", "generated_projects_authorized")
        )
    ):
        raise StaticBrowserError("BROWSER_OBSERVATION_NOT_ELIGIBLE")
    runner = manifest.get("runner", {})
    if (
        not isinstance(runner, dict)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", runner.get("image_id", "")) is None
        or runner.get("image_id_kind") != "LOCAL_CONFIG_DIGEST"
    ):
        raise StaticBrowserError("BROWSER_IMAGE_IDENTITY_INVALID")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not 10 <= len(artifacts) <= 32:
        raise StaticBrowserError("BROWSER_ARTIFACTS_INVALID")
    blobs = {}
    total = 0
    for item in artifacts:
        name = item.get("path", "") if isinstance(item, dict) else ""
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", name) is None or name in blobs:
            raise StaticBrowserError("BROWSER_ARTIFACT_NAME_INVALID")
        data = read_regular(manifest_path.parent / name)
        total += len(data)
        if (
            total > 64 * 1024 * 1024
            or type(item.get("size_bytes")) is not int
            or (
                len(data) != item["size_bytes"]
                or hashlib.sha256(data).hexdigest() != item.get("sha256")
            )
        ):
            raise StaticBrowserError("BROWSER_ARTIFACT_MISMATCH")
        blobs[name] = data
    expected_names = {
        "parent-manifest.json",
        "seccomp.json",
        "BROWSER_PROBE.stdout.log",
        "narrow.png",
        "wide.png",
        "narrow.html",
        "wide.html",
        "narrow.axe.json",
        "wide.axe.json",
        "negative-control.axe.json",
        "package-lock.observed.json",
        "browser-events.json",
    }
    if not expected_names <= blobs.keys():
        raise StaticBrowserError("BROWSER_ARTIFACTS_INCOMPLETE")
    parent = read_json(blobs["parent-manifest.json"])
    if not isinstance(parent, dict) or parent.get("content_hash") != manifest.get(
        "parent_content_hash"
    ):
        raise StaticBrowserError("BROWSER_PARENT_MISMATCH")
    if (
        content_hash({key: item for key, item in parent.items() if key != "content_hash"})
        != parent["content_hash"]
    ):
        raise StaticBrowserError("BROWSER_PARENT_HASH_MISMATCH")
    observed = read_json(blobs["BROWSER_PROBE.stdout.log"])
    if (
        not isinstance(observed, dict)
        or observed.get("status") != "PASSED"
        or observed.get("probe_kind") != "TRUSTED_BROWSER_INFRASTRUCTURE_FIXTURE"
        or observed.get("uid") != 65532
        or set(observed.get("checks", {})) != CHECK_NAMES
        or any(value is not True for value in observed["checks"].values())
        or observed.get("versions", {}).get("playwright") != "1.62.1"
        or observed.get("versions", {}).get("axe_core") != "4.13.0"
        or manifest.get("probe", {}).get("checks") != observed["checks"]
        or manifest.get("probe", {}).get("versions") != observed["versions"]
    ):
        raise StaticBrowserError("BROWSER_RAW_OBSERVATION_MISMATCH")
    screens = observed.get("screens")
    if not isinstance(screens, list) or len(screens) != 2:
        raise StaticBrowserError("BROWSER_RAW_SCREENS_MISSING")
    for screen, name in zip(screens, ("narrow", "wide"), strict=True):
        if screen.get("name") != name:
            raise StaticBrowserError("BROWSER_RAW_SCREEN_MISMATCH")
        for field, extension in (("screenshot", "png"), ("dom", "html"), ("axe", "axe.json")):
            if artifact_bytes(screen.get(field)) != blobs[f"{name}.{extension}"]:
                raise StaticBrowserError("BROWSER_RAW_ARTIFACT_MISMATCH")
    for field, name in (
        ("negative_axe", "negative-control.axe.json"),
        ("package_lock", "package-lock.observed.json"),
        ("events", "browser-events.json"),
    ):
        if artifact_bytes(observed.get(field)) != blobs[name]:
            raise StaticBrowserError("BROWSER_RAW_ARTIFACT_MISMATCH")
    recipes = manifest.get("recipes")
    expected_recipes = {
        f"infra/web-runners/browser-automation/{name}"
        for name in ("Dockerfile", "package.json", "probe.cjs", "fixture.html", "seccomp.json")
    }
    if (
        not isinstance(recipes, list)
        or len(recipes) != 5
        or {item.get("path") for item in recipes if isinstance(item, dict)} != expected_recipes
    ):
        raise StaticBrowserError("BROWSER_RECIPES_INVALID")
    for item in recipes:
        data = read_regular(repo_root / item["path"], 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise StaticBrowserError("BROWSER_RECIPE_CHANGED")
        if item["path"].endswith("/seccomp.json") and data != blobs["seccomp.json"]:
            raise StaticBrowserError("BROWSER_SECCOMP_MISMATCH")
    return VerifiedBrowserRunner(
        digest, runner["image_id"], blobs["seccomp.json"], body, manifest["platform_commit"]
    )
