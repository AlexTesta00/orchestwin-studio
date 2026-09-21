"""Native Studio loads explicit JVM settings without starting a runner or model."""

import json

import pytest

from scripts import studio_runtime


def test_source_recipes_available_without_enabling_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_runtime, "ROOT", tmp_path)
    monkeypatch.setattr(studio_runtime.os, "environ", {})
    studio_runtime.configure_jvm()
    assert studio_runtime.os.environ == {"ORCHESTWIN_GOVERNED_JVM_REPO_ROOT": str(tmp_path)}


def test_explicit_pinned_configuration_applies_on_next_start(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_runtime.os, "environ", {})
    config = {
        "enabled": True,
        "repo_root": str(tmp_path),
        "workspaces_root": str(tmp_path / "work"),
        "distribution_path": str(tmp_path / "gradle.zip"),
        "dependency_network_manifest": str(tmp_path / "network.json"),
        "dependency_network_manifest_hash": "c" * 64,
        "gradle_image_id": "sha256:" + "a" * 64,
        "sbt_image_id": "sha256:" + "b" * 64,
    }
    path = tmp_path / "jvm.json"
    path.write_text(json.dumps(config))
    studio_runtime.configure_jvm(path)
    assert studio_runtime.os.environ["ORCHESTWIN_GOVERNED_JVM_ENABLED"] == "true"
    assert (
        studio_runtime.os.environ["ORCHESTWIN_GOVERNED_JVM_GRADLE_IMAGE_ID"]
        == config["gradle_image_id"]
    )
    assert studio_runtime.os.environ["ORCHESTWIN_GOVERNED_JVM_DOCKER_CONTEXT"] == "desktop-linux"


def test_missing_or_unrecognized_configuration_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="NOT_FOUND"):
        studio_runtime.configure_jvm(tmp_path / "missing.json")
    path = tmp_path / "invalid.json"
    path.write_text('{"arbitrary_environment_override": "value"}')
    with pytest.raises(ValueError, match="INVALID"):
        studio_runtime.configure_jvm(path)


def test_enabled_configuration_requires_immutable_image_ids(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"enabled": true, "gradle_image_id": "latest"}')
    with pytest.raises(ValueError):
        studio_runtime.configure_jvm(path)
