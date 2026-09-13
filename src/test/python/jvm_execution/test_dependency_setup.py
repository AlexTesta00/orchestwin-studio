"""Pure JVM SETUP configuration tests, without Docker or execution attestations."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from orchestwin.jvm_execution.dependency_setup import (
    JVM_SETUP_POLICY_HASH,
    ControlledJvmNetwork,
    JvmDependencySetupConfiguration,
    jvm_setup_policy_snapshot,
    setup_configuration,
)
from orchestwin.jvm_execution.policy import policy_for
from orchestwin.sandbox.execution_profiles import ExecutionTarget

_ATTEMPT = UUID("11111111-1111-4111-8111-111111111111")
_OTHER_ATTEMPT = UUID("22222222-2222-4222-8222-222222222222")
_TARGETS = (ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA)


def _network() -> ControlledJvmNetwork:
    return ControlledJvmNetwork(
        name="owjvmdep-123456781234123412341234567890ab-internal",
        network_id="a" * 64,
        policy_hash=JVM_SETUP_POLICY_HASH,
    )


def _environment(configuration: JvmDependencySetupConfiguration) -> dict[str, str]:
    return {variable.key: variable.value for variable in configuration.environment_variables}


def _gradle_properties(configuration: JvmDependencySetupConfiguration) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in configuration.file_payloads[0][1].decode().splitlines()
    )


def _sbt_properties(configuration: JvmDependencySetupConfiguration) -> dict[str, str]:
    options = _environment(configuration)["SBT_OPTS"].split(" ")
    assert all(option.startswith("-D") for option in options)
    return dict(option[2:].split("=", 1) for option in options)


def test_setup_policy_binds_every_exact_profile_and_the_closed_network_boundary() -> None:
    snapshot = jvm_setup_policy_snapshot()
    assert snapshot["profile_policies"] == [policy_for(target).to_snapshot() for target in _TARGETS]
    assert snapshot["network"] == {
        "allowed_connect_authorities": ["repo.maven.apache.org:443"],
        "controlled_phase": "SETUP",
        "post_setup_mode": "DISABLED",
        "tls_interception": False,
        "proxy_host": "owjvmdep-proxy",
        "proxy_port": 3128,
    }
    assert snapshot["cache"] == {
        "scope": "EXECUTION_ATTEMPT",
        "root_template": "/workspace/.orchestwin/jvm/{attempt_id_hex}",
        "host_cache_allowed": False,
        "shared_across_attempts": False,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode()).hexdigest() == JVM_SETUP_POLICY_HASH


def test_policy_snapshots_are_fresh_and_do_not_mutate_the_canonical_binding() -> None:
    snapshot = jvm_setup_policy_snapshot()
    snapshot["profile_policies"][0]["build_tool_version"] = "unapproved"
    snapshot["network"]["allowed_connect_authorities"].append("attacker.example:443")

    assert jvm_setup_policy_snapshot() != snapshot
    assert _network().policy_hash == JVM_SETUP_POLICY_HASH
    mutated = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="closed SETUP policy"):
        replace(_network(), policy_hash=hashlib.sha256(mutated.encode()).hexdigest())


def test_network_binding_is_frozen_and_its_snapshot_round_trips() -> None:
    network = _network()
    assert ControlledJvmNetwork(**network.to_snapshot()) == network
    with pytest.raises(FrozenInstanceError):
        network.proxy_host = "attacker.example"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "bridge"),
        ("name", "owjvmdep-123456781234123412341234567890AB-internal"),
        ("name", "owjvmdep-123456781234123412341234567890ab-egress"),
        ("name", "owjvmdep-123456781234123412341234567890ab-internal\n"),
        ("name", "owjvmdep-123456781234123412341234567890ab-internal --privileged"),
        ("name", None),
        ("network_id", "a" * 12),
        ("network_id", "A" * 64),
        ("network_id", "a" * 64 + "\n"),
        ("network_id", 1),
        ("policy_hash", "f" * 64),
        ("policy_hash", "sha256:" + JVM_SETUP_POLICY_HASH),
        ("policy_hash", None),
        ("proxy_host", "127.0.0.1"),
        ("proxy_host", "owjvmdep-proxy.attacker.example"),
        ("proxy_host", "owjvmdep-proxy\n-Dhttp.nonProxyHosts=*"),
        ("proxy_host", "owjvmdep-proxy; id"),
        ("proxy_host", None),
        ("proxy_port", 443),
        ("proxy_port", "3128"),
        ("proxy_port", 3128.0),
        ("proxy_port", True),
        ("proxy_port", "3128 -Dhttp.nonProxyHosts=*"),
    ],
)
def test_network_rejects_noncanonical_or_injected_bindings(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(_network(), **{field: value})


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("controlled", [False, True])
def test_configuration_is_immutable_canonical_and_confined_to_its_attempt(
    target: ExecutionTarget, controlled: bool
) -> None:
    network = _network() if controlled else None
    configuration = setup_configuration(target, _ATTEMPT, network)

    assert configuration == setup_configuration(target, _ATTEMPT, network)
    assert configuration.network == network
    assert configuration.cache_root == f"/workspace/.orchestwin/jvm/{_ATTEMPT.hex}"
    keys = tuple(variable.key for variable in configuration.environment_variables)
    assert keys == tuple(sorted(set(keys)))
    assert all(not variable.is_secret for variable in configuration.environment_variables)
    paths = tuple(path for path, _ in configuration.file_payloads)
    assert paths == tuple(sorted(set(paths)))
    for path, payload in configuration.file_payloads:
        relative = PurePosixPath(path)
        assert not relative.is_absolute()
        assert relative.is_relative_to(f".orchestwin/jvm/{_ATTEMPT.hex}")
        assert ".." not in relative.parts
        assert "\\" not in path
        assert payload.endswith(b"\n")
        assert b"\r" not in payload and b"\x00" not in payload
    with pytest.raises(FrozenInstanceError):
        configuration.cache_root = "/tmp/shared"


@pytest.mark.parametrize("target", _TARGETS)
def test_different_attempts_never_share_runtime_files_or_cache_directories(
    target: ExecutionTarget,
) -> None:
    original = setup_configuration(target, _ATTEMPT, _network())
    other = setup_configuration(target, _OTHER_ATTEMPT, _network())

    assert original.cache_root != other.cache_root
    assert {path for path, _ in original.file_payloads}.isdisjoint(
        path for path, _ in other.file_payloads
    )
    assert _ATTEMPT.hex not in repr(other)
    assert _OTHER_ATTEMPT.hex not in repr(original)
    assert replace(original, attempt_id=_OTHER_ATTEMPT) == other


@pytest.mark.parametrize("target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN])
def test_gradle_setup_uses_only_owned_cache_and_explicit_nonbypassed_proxy(
    target: ExecutionTarget,
) -> None:
    configuration = setup_configuration(target, _ATTEMPT, _network())
    root = configuration.cache_root
    assert _environment(configuration) == {
        "GRADLE_USER_HOME": f"{root}/gradle",
        "HOME": f"{root}/home",
    }
    assert (
        configuration.file_payloads[0][0]
        == f".orchestwin/jvm/{_ATTEMPT.hex}/gradle/gradle.properties"
    )
    assert _gradle_properties(configuration) == {
        "org.gradle.daemon": "false",
        "org.gradle.java.installations.auto-download": "false",
        "org.gradle.jvmargs": f"-Duser.home={root}/home",
        "systemProp.java.net.useSystemProxies": "false",
        "systemProp.http.proxyHost": "owjvmdep-proxy",
        "systemProp.http.proxyPort": "3128",
        "systemProp.https.proxyHost": "owjvmdep-proxy",
        "systemProp.https.proxyPort": "3128",
        "systemProp.http.nonProxyHosts": "",
    }


def test_sbt_setup_separates_all_caches_and_overrides_build_repositories() -> None:
    configuration = setup_configuration(ExecutionTarget.JVM_SCALA, _ATTEMPT, _network())
    root = configuration.cache_root
    assert _environment(configuration)["HOME"] == f"{root}/home"
    properties = _sbt_properties(configuration)
    assert properties == {
        "user.home": f"{root}/home",
        "sbt.boot.directory": f"{root}/sbt/boot",
        "sbt.global.base": f"{root}/sbt/global",
        "sbt.ivy.home": f"{root}/ivy",
        "sbt.coursier.home": f"{root}/coursier",
        "sbt.override.build.repos": "true",
        "sbt.repository.config": f"{root}/sbt/repositories",
        "sbt.offline": "false",
        "java.net.useSystemProxies": "false",
        "http.proxyHost": "owjvmdep-proxy",
        "http.proxyPort": "3128",
        "https.proxyHost": "owjvmdep-proxy",
        "https.proxyPort": "3128",
        "http.nonProxyHosts": "",
    }
    assert configuration.file_payloads == (
        (
            f".orchestwin/jvm/{_ATTEMPT.hex}/sbt/repositories",
            b"[repositories]\nmaven-central: https://repo.maven.apache.org/maven2/\n",
        ),
    )


@pytest.mark.parametrize("target", _TARGETS)
def test_offline_settings_retain_the_attempt_cache_and_remove_setup_proxy_values(
    target: ExecutionTarget,
) -> None:
    setup = setup_configuration(target, _ATTEMPT, _network())
    offline = setup_configuration(target, _ATTEMPT, None)

    assert offline.cache_root == setup.cache_root
    assert _environment(offline)["HOME"] == _environment(setup)["HOME"]
    assert "owjvmdep-proxy" not in repr(offline)
    assert "proxyHost" not in repr(offline)
    assert "proxyPort" not in repr(offline)
    assert "nonProxyHosts" not in repr(offline)
    if target is ExecutionTarget.JVM_SCALA:
        assert _sbt_properties(offline)["sbt.offline"] == "true"
        assert offline.file_payloads == setup.file_payloads
    else:
        assert "org.gradle.offline" not in _gradle_properties(offline)
        assert _gradle_properties(offline)["systemProp.java.net.useSystemProxies"] == "false"


@pytest.mark.parametrize(
    ("target", "attempt_id", "network", "error"),
    [
        ("JVM_JAVA", _ATTEMPT, None, TypeError),
        (None, _ATTEMPT, None, TypeError),
        (ExecutionTarget.WEB_STATIC, _ATTEMPT, None, ValueError),
        (ExecutionTarget.JVM_JAVA, str(_ATTEMPT), None, TypeError),
        (ExecutionTarget.JVM_JAVA, "../../shared", None, TypeError),
        (ExecutionTarget.JVM_JAVA, "id\n-Duser.home=/shared", None, TypeError),
        (ExecutionTarget.JVM_JAVA, 1, None, TypeError),
        (ExecutionTarget.JVM_JAVA, _ATTEMPT, {}, TypeError),
        (ExecutionTarget.JVM_JAVA, _ATTEMPT, "bridge", TypeError),
    ],
)
def test_configuration_rejects_invalid_targets_ids_and_network_objects(
    target: object, attempt_id: object, network: object, error: type[Exception]
) -> None:
    with pytest.raises(error):
        setup_configuration(target, attempt_id, network)


def test_generation_does_not_read_host_environment_or_access_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Pure JVM configuration must not access host state")

    class ForbiddenEnvironment(dict):
        __getitem__ = get = __iter__ = forbidden

    with monkeypatch.context() as patch:
        patch.setattr(os, "environ", ForbiddenEnvironment())
        patch.setattr(os, "getenv", forbidden)
        patch.setattr(builtins, "open", forbidden)
        for method in ("open", "mkdir", "read_bytes", "write_bytes", "read_text", "write_text"):
            patch.setattr(Path, method, forbidden)
        configurations = [
            setup_configuration(target, _ATTEMPT, network)
            for target in _TARGETS
            for network in (None, _network())
        ]

    assert len(configurations) == 6
