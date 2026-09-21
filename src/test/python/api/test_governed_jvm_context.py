"""Approval payloads derive from verified bytes and operator pins, not client declarations."""

import hashlib
import json
from dataclasses import replace

import pytest

from orchestwin.jvm_execution.plans import JvmExecutionPhase
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.source_policy import (
    SOURCE_POLICY_HASH,
    read_source_objects,
    verify_source_policy,
)
from src.test.python.jvm_execution.api_support import ROOT, TARGETS, fixture_context


@pytest.mark.parametrize("target", TARGETS)
def test_three_pinned_fixture_contracts_prepare_without_execution(tmp_path, target):
    backend, revision, command = fixture_context(tmp_path, target)
    context = backend.prepare(
        revision, command=command, registry=create_sprint09_jvm_profile_registry(), previous=None
    )
    assert context.snapshot.inventory_content_hash == revision.source_tree_hash
    assert context.request.authorization is None
    assert context.payload["effective_phases"] == [phase.value for phase in JvmExecutionPhase]
    assert context.payload["source_policy_hash"] == SOURCE_POLICY_HASH
    assert context.payload["contract"]["validation"]["capability_status"] == "DESIGN_ONLY_LEVEL_C"
    assert str(tmp_path) not in json.dumps(context.payload)
    assert not backend.config.workspaces_root.exists()


@pytest.mark.parametrize("change", ["image", "policy", "partial", "source"])
def test_mismatched_inputs_rejected_before_allocation(tmp_path, change):
    backend, revision, command = fixture_context(tmp_path)
    if change == "image":
        command = replace(command, runner_image_digest="f" * 64)
    elif change == "policy":
        command = replace(command, policy_content_hash="f" * 64)
    elif change == "partial":
        command = replace(command, rerun_phases=(JvmExecutionPhase.TEST,))
    else:
        (backend.content_root / revision.files[0].storage_key).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        backend.prepare(
            revision,
            command=command,
            registry=create_sprint09_jvm_profile_registry(),
            previous=None,
        )
    assert not backend.config.workspaces_root.exists()


@pytest.mark.parametrize("target", TARGETS)
def test_source_policy_pins_build_configuration_but_allows_application_edits(tmp_path, target):
    backend, revision, _ = fixture_context(tmp_path, target)
    contents = read_source_objects(revision, backend.content_root)
    raw = (ROOT / "infra/jvm-runners/source-policy.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_POLICY_HASH
    pins = json.loads(raw)["profiles"][target.value]
    assert set(pins) == {path for path in contents if not path.startswith("src/")}
    source = next(path for path in contents if path.startswith("src/main/"))
    contents[source] += b"\n// Changed application\n"
    assert verify_source_policy(revision, contents, repo_root=ROOT).launcher_integrity_verified
    config = next(iter(pins))
    contents[config] += b"\n// Unreviewed build change\n"
    with pytest.raises(ValueError, match="BUILD_CONFIGURATION_NOT_SUPPORTED"):
        verify_source_policy(revision, contents, repo_root=ROOT)


def test_configuration_requires_explicit_operator_pins(tmp_path):
    from orchestwin.api.governed_jvm_context import GovernedJvmSettings

    assert not GovernedJvmSettings(_env_file=None).enabled
    with pytest.raises(ValueError, match="ABSOLUTE_PATH_REQUIRED"):
        GovernedJvmSettings(_env_file=None, enabled=True)
    backend, _, _ = fixture_context(tmp_path)
    values = backend.config.model_dump()
    for field, value in (
        ("gradle_image_id", "latest"),
        ("sbt_image_id", "sha256:short"),
        ("dependency_network_manifest_hash", "unpinned"),
    ):
        with pytest.raises(ValueError):
            GovernedJvmSettings(_env_file=None, **{**values, field: value})


@pytest.mark.parametrize("kind", ["case", "directory"])
def test_source_paths_are_checked_before_temporary_copy(tmp_path, kind):
    from types import SimpleNamespace

    backend, revision, _ = fixture_context(tmp_path)
    entry = revision.files[0]
    paths = {
        "case": ("src/main/kotlin/Main.kt", "src/main/kotlin/main.kt"),
        "directory": ("src/main/kotlin/a", "src/main/kotlin/a/Main.kt"),
    }[kind]
    source = SimpleNamespace(files=tuple(replace(entry, normalized_path=path) for path in paths))
    with pytest.raises(ValueError):
        read_source_objects(source, backend.content_root)
    assert not backend.config.workspaces_root.exists()
