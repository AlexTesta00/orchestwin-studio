"""Reproducibility tests for the committed WSL2 CUDA training lock."""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ENVIRONMENT_ROOT = REPOSITORY_ROOT / "environments" / "training"
LOCKFILE = ENVIRONMENT_ROOT / "uv.lock"
PROJECT_FILE = ENVIRONMENT_ROOT / "pyproject.toml"

EXPECTED_LOCK_SHA256 = "fcd551c5c136ba0c6266d131b41a10ae48b13477dc7269f786a29f7db14d073b"
EXPECTED_PACKAGE_COUNT = 121
EXPECTED_RESOLUTION_MARKERS = (
    "sys_platform == 'win32'",
    "sys_platform == 'emscripten'",
    "sys_platform != 'emscripten' and sys_platform != 'win32'",
)
EXPECTED_DIRECT_REQUIREMENTS = {
    "trl": "==0.24.0",
    "unsloth": "==2026.8.22",
    "unsloth-zoo": "==2026.8.16",
}
EXPECTED_CRITICAL_PACKAGE_VERSIONS = {
    "accelerate": "1.14.0",
    "bitsandbytes": "0.50.2",
    "cuda-bindings": "13.3.1",
    "cuda-toolkit": "13.0.2",
    "datasets": "4.3.0",
    "peft": "0.20.0",
    "torch": "2.11.0",
    "torchao": "0.18.0",
    "torchvision": "0.26.0",
    "transformers": "5.5.0",
    "triton": "3.6.0",
    "trl": "0.24.0",
    "unsloth": "2026.8.22",
    "unsloth-zoo": "2026.8.16",
    "xformers": "0.0.35",
}
_SHA256_ARTIFACT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return tomllib.load(source)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_entries(lock: dict[str, Any]) -> list[dict[str, Any]]:
    entries = lock.get("package")
    assert isinstance(entries, list)
    assert all(isinstance(entry, dict) for entry in entries)
    return entries


def _package_versions(entries: list[dict[str, Any]]) -> dict[str, set[str]]:
    versions: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        name = entry.get("name")
        version = entry.get("version")
        assert isinstance(name, str)
        if version is not None:
            assert isinstance(version, str)
            versions[name].add(version)
    return dict(versions)


def _package_by_name(entries: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [entry for entry in entries if entry.get("name") == name]
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def test_committed_lock_has_observed_identity_and_python_scope() -> None:
    assert LOCKFILE.is_file()
    lock = _load_toml(LOCKFILE)
    entries = _package_entries(lock)

    assert _sha256(LOCKFILE) == EXPECTED_LOCK_SHA256
    assert lock["version"] == 1
    assert lock["revision"] == 3
    assert lock["requires-python"] == "==3.13.*"
    assert tuple(lock["resolution-markers"]) == EXPECTED_RESOLUTION_MARKERS
    assert len(entries) == EXPECTED_PACKAGE_COUNT


def test_committed_lock_preserves_observed_cuda_training_stack() -> None:
    entries = _package_entries(_load_toml(LOCKFILE))
    versions = _package_versions(entries)

    for name, expected_version in EXPECTED_CRITICAL_PACKAGE_VERSIONS.items():
        assert versions[name] == {expected_version}

    torch = _package_by_name(entries, "torch")
    torch_dependencies = {dependency["name"] for dependency in torch["dependencies"]}
    assert {"cuda-bindings", "cuda-toolkit", "triton"}.issubset(torch_dependencies)


def test_virtual_project_metadata_matches_the_exact_direct_pins() -> None:
    lock_entries = _package_entries(_load_toml(LOCKFILE))
    project = _load_toml(PROJECT_FILE)["project"]
    root_package = _package_by_name(lock_entries, "orchestwin-training-environment")

    assert project["dependencies"] == [
        f"{name}{specifier}" for name, specifier in EXPECTED_DIRECT_REQUIREMENTS.items()
    ]
    assert root_package["source"] == {"virtual": "."}
    assert {dependency["name"] for dependency in root_package["dependencies"]} == set(
        EXPECTED_DIRECT_REQUIREMENTS
    )

    locked_requirements = {
        requirement["name"]: requirement["specifier"]
        for requirement in root_package["metadata"]["requires-dist"]
    }
    assert locked_requirements == EXPECTED_DIRECT_REQUIREMENTS


def test_registry_artifacts_are_hash_pinned_without_vcs_sources() -> None:
    entries = _package_entries(_load_toml(LOCKFILE))

    for entry in entries:
        source = entry["source"]
        if entry["name"] == "orchestwin-training-environment":
            assert source == {"virtual": "."}
            continue

        assert source == {"registry": "https://pypi.org/simple"}
        assert not {"git", "url", "path", "editable"}.intersection(source)

        artifacts: list[dict[str, Any]] = []
        sdist = entry.get("sdist")
        if sdist is not None:
            assert isinstance(sdist, dict)
            artifacts.append(sdist)
        wheels = entry.get("wheels", [])
        assert isinstance(wheels, list)
        artifacts.extend(wheels)
        assert artifacts, entry["name"]

        for artifact in artifacts:
            assert isinstance(artifact, dict)
            assert isinstance(artifact.get("url"), str)
            artifact_hash = artifact.get("hash")
            assert isinstance(artifact_hash, str)
            assert _SHA256_ARTIFACT_PATTERN.fullmatch(artifact_hash) is not None
