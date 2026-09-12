"""Verify local runner bootstrap lineage before accepting a phase image identity.

Hashes establish local integrity, not permission, profile capability, or an
external attestation. The execution runtime must inspect the exact image ID
before use; this loader never queries Docker, pulls an image, or rebuilds one.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from orchestwin.web_execution.local_runners import RunnerBootstrapError, _probe_metadata
from orchestwin.web_execution.runner_bootstrap_inputs import load_bootstrap_inputs
from orchestwin.web_execution.verified_browser_runner import read_json, read_regular

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_LOG_BYTES = 8 * 1024 * 1024
_LOG_NAMES = frozenset(
    f"{action}_{kind}.{stream}.log"
    for kind in ("NODE", "PHP", "BROWSER")
    for action in ("BUILD", "PROBE")
    for stream in ("stdout", "stderr")
)


class WebPhaseRunnerError(ValueError):
    """Safe loader failure without raw log contents or host configuration."""


@dataclass(frozen=True, slots=True)
class WebPhaseRunnerIdentity:
    """Exact local config digest and the immutable bootstrap lineage selecting it."""

    kind: str
    image_id: str
    bootstrap_manifest_hash: str
    recipe_content_hash: str

    def __post_init__(self) -> None:
        if self.kind not in {"NODE", "PHP"}:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_KIND_INVALID")
        if not isinstance(self.image_id, str) or _IMAGE_ID.fullmatch(self.image_id) is None:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_IMAGE_ID_INVALID")
        for value in (self.bootstrap_manifest_hash, self.recipe_content_hash):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_DIGEST_INVALID")


def load_phase_runner_identity(
    manifest_path: Path, *, repo_root: Path, kind: str
) -> WebPhaseRunnerIdentity:
    """Verify all bootstrap artifacts and recipes, then select only Node or PHP."""
    if kind not in {"NODE", "PHP"}:
        raise WebPhaseRunnerError("WEB_PHASE_RUNNER_KIND_INVALID")
    try:
        path = Path(manifest_path).absolute()
        manifest = read_json(read_regular(path, 1024 * 1024))
        if not isinstance(manifest, dict):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_MANIFEST_INVALID")
        digest = manifest.get("content_hash")
        content = {key: value for key, value in manifest.items() if key != "content_hash"}
        if (
            not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or _hash(content) != digest
        ):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_MANIFEST_HASH_MISMATCH")
        if (
            type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 2
            or manifest.get("report_type") != "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE"
            or manifest.get("status") != "IMAGES_BUILT_PROBES_RECORDED"
            or any(
                manifest.get(flag) is not False
                for flag in (
                    "level_d_validated",
                    "formal_run_started",
                    "browser_automation_verified",
                )
            )
            or not isinstance(manifest.get("platform_commit"), str)
            or re.fullmatch(r"[0-9a-f]{40}", manifest["platform_commit"]) is None
        ):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_BOOTSTRAP_NOT_ELIGIBLE")
        environment = manifest.get("environment")
        if (
            not isinstance(environment, dict)
            or environment.get("platform") != "linux/amd64"
            or environment.get("builder_driver") != "docker"
            or manifest.get("environment_hash") != _hash(environment)
        ):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ENVIRONMENT_MISMATCH")
        inputs = load_bootstrap_inputs(repo_root)
        sources = dict(inputs.sources)
        expected_recipes = [
            {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
            for name, body in inputs.sources
        ]
        if manifest.get("bootstrap_inputs_hash") != inputs.content_hash or _hash(
            manifest.get("recipes")
        ) != _hash(expected_recipes):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_RECIPE_MISMATCH")
        probes = _verify_artifacts(path.parent, manifest.get("artifacts"))
        runners = manifest.get("runners")
        if not isinstance(runners, list) or len(runners) != len(inputs.runners):
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_SET_INVALID")
        by_kind = {}
        for runner in runners:
            if not isinstance(runner, dict) or runner.get("kind") not in {"NODE", "PHP", "BROWSER"}:
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_SET_INVALID")
            if runner["kind"] in by_kind:
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_SET_INVALID")
            by_kind[runner["kind"]] = runner
        for recipe in inputs.runners:
            runner = by_kind[recipe.kind]
            expected = {
                "kind": recipe.kind,
                "runner_id": recipe.runner_id,
                "runner_version": recipe.version,
                "recipe_content_hash": recipe.recipe_content_hash,
                "source_paths": list(recipe.source_paths),
                "base_image_references": list(recipe.base_image_references),
                "build_network": "default" if recipe.kind == "BROWSER" else "none",
                "image_id_kind": "LOCAL_CONFIG_DIGEST",
                "registry_manifest_digest": None,
                "cleanup_confirmed": True,
            }
            if not expected.keys() <= runner.keys() or _hash(
                {field: runner[field] for field in expected}
            ) != _hash(expected):
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_IDENTITY_MISMATCH")
            image_id = runner.get("image_id")
            if not isinstance(image_id, str) or _IMAGE_ID.fullmatch(image_id) is None:
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_IMAGE_ID_INVALID")
            observed = _probe_metadata(recipe.kind, probes[recipe.kind], recipe, sources)
            if _hash(runner.get("probe")) != _hash(observed):
                raise WebPhaseRunnerError("WEB_PHASE_RUNNER_PROBE_MISMATCH")
        selected = by_kind[kind]
        return WebPhaseRunnerIdentity(
            kind=kind,
            image_id=selected["image_id"],
            bootstrap_manifest_hash=digest,
            recipe_content_hash=selected["recipe_content_hash"],
        )
    except WebPhaseRunnerError:
        raise
    except (OSError, ValueError, TypeError, KeyError, RunnerBootstrapError):
        raise WebPhaseRunnerError("WEB_PHASE_RUNNER_MANIFEST_INVALID") from None


def _verify_artifacts(root: Path, artifacts: object) -> dict[str, object]:
    if not isinstance(artifacts, list) or len(artifacts) != len(_LOG_NAMES):
        raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACTS_INCOMPLETE")
    seen = set()
    probes = {}
    total = 0
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "size_bytes"}:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACT_INVALID")
        name = artifact["path"]
        size = artifact["size_bytes"]
        if not isinstance(name, str) or name not in _LOG_NAMES or name in seen:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACT_PATH_INVALID")
        if type(size) is not int or not 0 <= size <= _MAX_LOG_BYTES:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACT_SIZE_INVALID")
        seen.add(name)
        total += size
        if total > len(_LOG_NAMES) * _MAX_LOG_BYTES:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACT_BUDGET_EXCEEDED")
        body = read_regular(root / name, _MAX_LOG_BYTES)
        if len(body) != size or hashlib.sha256(body).hexdigest() != artifact["sha256"]:
            raise WebPhaseRunnerError("WEB_PHASE_RUNNER_ARTIFACT_MISMATCH")
        if name.startswith("PROBE_") and name.endswith(".stdout.log"):
            probes[name.removeprefix("PROBE_").removesuffix(".stdout.log")] = read_json(body)
    return probes


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()
