"""Verify bootstrap lineage without executing Docker or granting capability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from orchestwin.web_execution.local_runners import _probe_metadata
from orchestwin.web_execution.phase_runner import (
    WebPhaseRunnerError,
    WebPhaseRunnerIdentity,
    load_phase_runner_identity,
)
from orchestwin.web_execution.runner_bootstrap_inputs import load_bootstrap_inputs

REPOSITORY = Path(__file__).parents[4]


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def save_manifest(path: Path, manifest: dict) -> None:
    manifest.pop("content_hash", None)
    manifest["content_hash"] = canonical_hash(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def observation(tmp_path: Path):
    """Synthetic integrity fixture only; never a real runner observation."""
    root = tmp_path / "repo"
    for name, body in load_bootstrap_inputs(REPOSITORY).sources:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    inputs = load_bootstrap_inputs(root)
    sources = dict(inputs.sources)
    output = tmp_path / "evidence"
    output.mkdir()
    artifacts = []
    runners = []
    observed = {
        "NODE": {
            "uid": 65532,
            "node_version": "v26.7.0",
            "npm_version": "11.0.0",
            "static_http": True,
        },
        "PHP": {
            "uid": 65532,
            "php_version": "8.4.24",
            "composer_version": "2.10.2",
            "php_lint_valid": True,
            "php_lint_invalid_rejected": True,
            "php_http": True,
        },
        "BROWSER": {
            "uid": 65532,
            "node_version": "v24.0.0",
            "npm_version": "11.0.0",
            "browser_binaries_present": True,
            "playwright_package_resolvable": True,
            "playwright_version": "1.62.1",
            "playwright_core_version": "1.62.1",
            "axe_version": "4.13.0",
            "chromium_version_output": "Google Chrome for Testing 151.0.7922.34",
            "package_lock_sha256": hashlib.sha256(
                sources["infra/web-runners/browser-locked/package-lock.json"]
            ).hexdigest(),
        },
    }
    for recipe in inputs.runners:
        for action in ("BUILD", "PROBE"):
            for stream in ("stdout", "stderr"):
                name = f"{action}_{recipe.kind}.{stream}.log"
                body = (
                    json.dumps(observed[recipe.kind]).encode()
                    if action == "PROBE" and stream == "stdout"
                    else b""
                )
                (output / name).write_bytes(body)
                artifacts.append(
                    {
                        "path": name,
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "size_bytes": len(body),
                    }
                )
        runners.append(
            {
                "kind": recipe.kind,
                "runner_id": recipe.runner_id,
                "runner_version": recipe.version,
                "recipe_content_hash": recipe.recipe_content_hash,
                "source_paths": list(recipe.source_paths),
                "base_image_references": list(recipe.base_image_references),
                "build_network": "default" if recipe.kind == "BROWSER" else "none",
                "local_tag": f"orchestwin/web-{recipe.kind.lower()}-runner:s12-{'a' * 32}",
                "image_id": "sha256:" + {"NODE": "a", "PHP": "b", "BROWSER": "c"}[recipe.kind] * 64,
                "image_id_kind": "LOCAL_CONFIG_DIGEST",
                "registry_manifest_digest": None,
                "probe": _probe_metadata(recipe.kind, observed[recipe.kind], recipe, sources),
                "cleanup_confirmed": True,
            }
        )
    environment = {"platform": "linux/amd64", "builder_driver": "docker"}
    manifest = {
        "schema_version": 2,
        "report_type": "LOCAL_RUNNER_BOOTSTRAP_NOT_FORMAL_EVIDENCE",
        "status": "IMAGES_BUILT_PROBES_RECORDED",
        "platform_commit": "d" * 40,
        "bootstrap_inputs_hash": inputs.content_hash,
        "environment": environment,
        "environment_hash": canonical_hash(environment),
        "level_d_validated": False,
        "formal_run_started": False,
        "browser_automation_verified": False,
        "runners": runners,
        "artifacts": artifacts,
        "recipes": [
            {"path": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
            for name, body in inputs.sources
        ],
    }
    path = output / "manifest.json"
    save_manifest(path, manifest)
    return root, path, manifest


@pytest.mark.parametrize("kind", ["NODE", "PHP", "BROWSER"])
def test_verified_identity_is_local_immutable_and_keeps_exact_lineage(tmp_path, kind) -> None:
    root, path, manifest = observation(tmp_path)
    result = load_phase_runner_identity(path, repo_root=root, kind=kind)
    selected = next(row for row in manifest["runners"] if row["kind"] == kind)
    assert result == WebPhaseRunnerIdentity(
        kind, selected["image_id"], manifest["content_hash"], selected["recipe_content_hash"]
    )
    assert "@" not in result.image_id
    with pytest.raises(FrozenInstanceError):
        result.image_id = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 1),
        ("schema_version", True),
        ("status", "FAILED"),
        ("report_type", "LOCAL_BROWSER_AUTOMATION_NOT_FORMAL_EVIDENCE"),
        ("level_d_validated", True),
        ("formal_run_started", True),
        ("browser_automation_verified", True),
        ("bootstrap_inputs_hash", "0" * 64),
        ("platform_commit", "latest"),
    ],
)
def test_invalid_bootstrap_claims_fail_closed(tmp_path, field, value) -> None:
    root, path, manifest = observation(tmp_path)
    manifest[field] = value
    save_manifest(path, manifest)
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


@pytest.mark.parametrize(
    "field,value",
    [
        ("image_id", "orchestwin/web-node-runner:latest"),
        ("image_id_kind", "REGISTRY_MANIFEST_DIGEST"),
        ("cleanup_confirmed", False),
        ("cleanup_confirmed", 1),
        ("runner_version", "99.0.0"),
        ("runner_id", "web.php"),
        ("base_image_references", []),
        ("source_paths", []),
        ("recipe_content_hash", "0" * 64),
        ("registry_manifest_digest", "0" * 64),
    ],
)
def test_mismatched_selected_runner_is_rejected(tmp_path, field, value) -> None:
    root, path, manifest = observation(tmp_path)
    manifest["runners"][0][field] = value
    save_manifest(path, manifest)
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


def test_unhashed_manifest_change_is_rejected(tmp_path) -> None:
    root, path, manifest = observation(tmp_path)
    manifest["runners"][0]["image_id"] = "sha256:" + "f" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


@pytest.mark.parametrize(
    "damage", ["changed", "missing", "traversal", "duplicate", "boolean-size", "redirect"]
)
def test_every_artifact_is_verified_before_return(tmp_path, monkeypatch, damage) -> None:
    root, path, manifest = observation(tmp_path)
    artifact = manifest["artifacts"][-1]
    log = path.parent / artifact["path"]
    if damage == "changed":
        log.write_bytes(b"tampered")
    elif damage == "missing":
        manifest["artifacts"].pop()
    elif damage == "traversal":
        artifact["path"] = "../outside.log"
    elif damage == "duplicate":
        manifest["artifacts"][-1] = dict(manifest["artifacts"][0])
    elif damage == "boolean-size":
        artifact["size_bytes"] = False
    else:
        original = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda candidate: candidate == log or original(candidate)
        )
    save_manifest(path, manifest)
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


def test_metadata_cannot_contradict_preserved_probe_stdout(tmp_path) -> None:
    root, path, manifest = observation(tmp_path)
    manifest["runners"][0]["probe"]["npm_version"] = "12.0.0"
    save_manifest(path, manifest)
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


@pytest.mark.parametrize(
    "field,value",
    [
        ("uid", 0),
        ("uid", 65532.0),
        ("node_version", "v99.0.0"),
        ("npm_version", "latest"),
        ("static_http", 1),
    ],
)
def test_rehashed_invalid_raw_probe_still_fails_closed(tmp_path, field, value) -> None:
    root, path, manifest = observation(tmp_path)
    probe_path = path.parent / "PROBE_NODE.stdout.log"
    probe = json.loads(probe_path.read_bytes())
    probe[field] = value
    body = json.dumps(probe).encode()
    probe_path.write_bytes(body)
    artifact = next(row for row in manifest["artifacts"] if row["path"] == probe_path.name)
    artifact.update(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body))
    manifest["runners"][0]["probe"] = probe
    save_manifest(path, manifest)
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


def test_current_recipe_bytes_must_match_recorded_bootstrap(tmp_path) -> None:
    root, path, _ = observation(tmp_path)
    (root / "infra/web-runners/bin/static-server.mjs").write_bytes(b"changed")
    with pytest.raises(WebPhaseRunnerError):
        load_phase_runner_identity(path, repo_root=root, kind="NODE")


@pytest.mark.parametrize(
    "kind,image",
    [("JVM", "sha256:" + "a" * 64), ("NODE", "runner:latest"), ("node", "sha256:" + "a" * 64)],
)
def test_identity_constructor_rejects_unsupported_kind_and_mutable_image(kind, image) -> None:
    with pytest.raises(WebPhaseRunnerError):
        WebPhaseRunnerIdentity(kind, image, "b" * 64, "c" * 64)
