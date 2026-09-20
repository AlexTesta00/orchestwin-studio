"""Pure, attempt-scoped JVM dependency settings for a restricted SETUP network.

These values do not create directories, seed launchers, resolve dependencies, or
attest offline execution. A future executor must materialize the runtime files
safely, provide a clean container environment, and enforce Docker network isolation.
In particular, Gradle still requires ``--offline`` after SETUP; a properties file
is not a substitute for that command flag or the network boundary.

Property references:
https://docs.gradle.org/current/userguide/networking.html
https://docs.gradle.org/current/userguide/build_environment.html
https://www.scala-sbt.org/1.x/docs/Command-Line-Reference.html
https://www.scala-sbt.org/1.x/docs/Proxy-Repositories.html
https://get-coursier.io/docs/cache
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from orchestwin.jvm_execution.policy import policy_for
from orchestwin.sandbox.container_runtime import ContainerEnvironmentVariable
from orchestwin.sandbox.execution_profiles import ExecutionTarget

_JVM_TARGETS: Final = (
    ExecutionTarget.JVM_JAVA,
    ExecutionTarget.JVM_KOTLIN,
    ExecutionTarget.JVM_SCALA,
)
_NETWORK_NAME_PATTERN: Final = re.compile(r"owjvmdep-[0-9a-f]{32}-internal")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_PROXY_HOST: Final = "owjvmdep-proxy"
_PROXY_PORT: Final = 3128
_MAVEN_CENTRAL_URL: Final = "https://repo.maven.apache.org/maven2/"


def jvm_setup_policy_snapshot() -> dict[str, object]:
    """Return fresh policy data without admitting caller-supplied repositories."""
    return {
        "schema_version": 1,
        "profile_policies": [policy_for(target).to_snapshot() for target in _JVM_TARGETS],
        "network": {
            "allowed_connect_authorities": ["repo.maven.apache.org:443"],
            "controlled_phase": "SETUP",
            "post_setup_mode": "DISABLED",
            "tls_interception": False,
            "proxy_host": _PROXY_HOST,
            "proxy_port": _PROXY_PORT,
        },
        "cache": {
            "scope": "EXECUTION_ATTEMPT",
            "root_template": "/workspace/.orchestwin/jvm/{attempt_id_hex}",
            "host_cache_allowed": False,
            "shared_across_attempts": False,
        },
    }


JVM_SETUP_POLICY_HASH: Final = hashlib.sha256(
    json.dumps(
        jvm_setup_policy_snapshot(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


@dataclass(frozen=True, slots=True)
class ControlledJvmNetwork:
    """Exact provisioner binding; Docker existence and ownership need runtime checks."""

    name: str
    network_id: str
    policy_hash: str
    proxy_host: str = _PROXY_HOST
    proxy_port: int = _PROXY_PORT

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NETWORK_NAME_PATTERN.fullmatch(self.name) is None:
            raise ValueError("JVM network name must identify an owned internal network")
        for label, value in (("network ID", self.network_id), ("policy hash", self.policy_hash)):
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(f"JVM {label} must be lowercase SHA-256")
        if self.policy_hash != JVM_SETUP_POLICY_HASH:
            raise ValueError("JVM network policy hash does not match the closed SETUP policy")
        if self.proxy_host != _PROXY_HOST or not isinstance(self.proxy_host, str):
            raise ValueError("JVM proxy host must match the owned dependency proxy")
        if type(self.proxy_port) is not int or self.proxy_port != _PROXY_PORT:
            raise ValueError("JVM proxy port must be 3128")

    def to_snapshot(self) -> dict[str, str | int]:
        return {
            "name": self.name,
            "network_id": self.network_id,
            "policy_hash": self.policy_hash,
            "proxy_host": self.proxy_host,
            "proxy_port": self.proxy_port,
        }


@dataclass(frozen=True, slots=True)
class JvmDependencySetupConfiguration:
    """Deterministic values; file paths are relative to the mounted workspace."""

    target: ExecutionTarget
    attempt_id: UUID
    network: ControlledJvmNetwork | None
    cache_root: str = field(init=False)
    environment_variables: tuple[ContainerEnvironmentVariable, ...] = field(init=False)
    file_payloads: tuple[tuple[str, bytes], ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.target, ExecutionTarget):
            raise TypeError("JVM dependency setup requires an ExecutionTarget")
        if self.target not in _JVM_TARGETS:
            raise ValueError("JVM dependency setup requires a JVM target")
        if not isinstance(self.attempt_id, UUID):
            raise TypeError("JVM dependency setup requires a UUID attempt ID")
        if self.network is not None and not isinstance(self.network, ControlledJvmNetwork):
            raise TypeError("JVM dependency setup requires a controlled JVM network or None")

        relative_root = f".orchestwin/jvm/{self.attempt_id.hex}"
        cache_root = f"/workspace/{relative_root}"
        if self.target is ExecutionTarget.JVM_SCALA:
            variables, payloads = _sbt_configuration(cache_root, relative_root, self.network)
        else:
            variables, payloads = _gradle_configuration(cache_root, relative_root, self.network)
        object.__setattr__(self, "cache_root", cache_root)
        object.__setattr__(self, "environment_variables", variables)
        object.__setattr__(self, "file_payloads", payloads)


def setup_configuration(
    target: ExecutionTarget,
    attempt_id: UUID,
    network: ControlledJvmNetwork | None,
) -> JvmDependencySetupConfiguration:
    """Describe SETUP settings, or post-SETUP settings when ``network`` is None."""
    return JvmDependencySetupConfiguration(target, attempt_id, network)


def _proxy_properties(network: ControlledJvmNetwork | None) -> tuple[tuple[str, str], ...]:
    # The executor must also omit inherited JAVA_OPTS/JAVA_TOOL_OPTIONS and other
    # unapproved environment values. Explicit properties alone cannot sanitize it.
    properties = (("java.net.useSystemProxies", "false"),)
    if network is None:
        return properties
    return (
        *properties,
        ("http.proxyHost", network.proxy_host),
        ("http.proxyPort", str(network.proxy_port)),
        ("https.proxyHost", network.proxy_host),
        ("https.proxyPort", str(network.proxy_port)),
        # Java HTTPS uses http.nonProxyHosts as well; disable its default bypass.
        ("http.nonProxyHosts", ""),
    )


def _gradle_configuration(
    cache_root: str,
    relative_root: str,
    network: ControlledJvmNetwork | None,
) -> tuple[tuple[ContainerEnvironmentVariable, ...], tuple[tuple[str, bytes], ...]]:
    home = f"{cache_root}/home"
    variables = (
        ContainerEnvironmentVariable("GRADLE_USER_HOME", f"{cache_root}/gradle", False),
        ContainerEnvironmentVariable("HOME", home, False),
    )
    properties = (
        ("org.gradle.daemon", "false"),
        ("org.gradle.java.installations.auto-download", "false"),
        ("org.gradle.jvmargs", f"-Duser.home={home}"),
        *((f"systemProp.{key}", value) for key, value in _proxy_properties(network)),
    )
    payload = "".join(f"{key}={value}\n" for key, value in properties).encode("utf-8")
    return variables, ((f"{relative_root}/gradle/gradle.properties", payload),)


def _sbt_configuration(
    cache_root: str,
    relative_root: str,
    network: ControlledJvmNetwork | None,
) -> tuple[tuple[ContainerEnvironmentVariable, ...], tuple[tuple[str, bytes], ...]]:
    home = f"{cache_root}/home"
    properties = (
        ("user.home", home),
        ("sbt.boot.directory", f"{cache_root}/sbt/boot"),
        ("sbt.global.base", f"{cache_root}/sbt/global"),
        ("sbt.ivy.home", f"{cache_root}/ivy"),
        ("sbt.coursier.home", f"{cache_root}/coursier"),
        ("sbt.override.build.repos", "true"),
        ("sbt.repository.config", f"{cache_root}/sbt/repositories"),
        ("sbt.offline", "true" if network is None else "false"),
        *_proxy_properties(network),
    )
    variables = (
        ContainerEnvironmentVariable("HOME", home, False),
        ContainerEnvironmentVariable(
            "SBT_OPTS", " ".join(f"-D{key}={value}" for key, value in properties), False
        ),
    )
    # No local, Ivy, plugin, or implicit repo1.maven.org fallback is configured.
    payload = f"[repositories]\nmaven-central: {_MAVEN_CENTRAL_URL}\n".encode()
    return variables, ((f"{relative_root}/sbt/repositories", payload),)
