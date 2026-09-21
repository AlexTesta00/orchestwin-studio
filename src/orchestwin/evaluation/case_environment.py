"""Content-addressed environment identity for reproducible formal case-study runs."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from orchestwin.evaluation.case_runs import CaseStudyRunRecord

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_GIT_SHA1_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_CONTAINER_DIGEST_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}")


def _normalize(value: str, *, label: str, maximum: int = 500) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds maximum length")
    if normalized != value:
        raise ValueError(f"{label} must be normalized")
    return normalized


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaseStudyRuntimeVersion:
    """Observed version for one relevant tool or runtime."""

    component: str
    version: str

    def __post_init__(self) -> None:
        _normalize(self.component, label="runtime component", maximum=100)
        _normalize(self.version, label="runtime version", maximum=300)

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.component.casefold(), self.version)

    def to_snapshot(self) -> dict[str, str]:
        return {"component": self.component, "version": self.version}


@dataclass(frozen=True, slots=True)
class CaseStudyContainerImage:
    """Pinned container image identity observed during one formal case run."""

    name: str
    digest: str

    def __post_init__(self) -> None:
        _normalize(self.name, label="container image name", maximum=300)
        if _CONTAINER_DIGEST_PATTERN.fullmatch(self.digest) is None:
            raise ValueError("container image digest must use sha256:<64 lowercase hex>")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.name, self.digest)

    def to_snapshot(self) -> dict[str, str]:
        return {"name": self.name, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class CaseStudyEnvironmentIdentity:
    """Immutable environment identity referenced by a finalized case-study run."""

    schema_version: int
    platform_commit: str
    execution_profile: str
    operating_system: str
    architecture: str
    python_version: str
    runtime_versions: tuple[CaseStudyRuntimeVersion, ...]
    container_images: tuple[CaseStudyContainerImage, ...]
    network_policy: str
    captured_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported case-study environment schema version")
        if _GIT_SHA1_PATTERN.fullmatch(self.platform_commit) is None:
            raise ValueError("environment platform commit must be a lowercase Git SHA")
        _normalize(self.execution_profile, label="environment execution profile", maximum=200)
        _normalize(self.operating_system, label="environment operating system")
        _normalize(self.architecture, label="environment architecture")
        _normalize(self.python_version, label="environment Python version")
        _normalize(self.network_policy, label="environment network policy", maximum=1_000)
        if self.captured_at.tzinfo is None:
            raise ValueError("environment capture timestamp must be timezone-aware")
        if self.runtime_versions != tuple(
            sorted(self.runtime_versions, key=lambda item: item.sort_key)
        ):
            raise ValueError("runtime versions must use canonical order")
        runtime_names = tuple(item.component.casefold() for item in self.runtime_versions)
        if len(runtime_names) != len(set(runtime_names)):
            raise ValueError("runtime component names must be unique")
        if self.container_images != tuple(
            sorted(self.container_images, key=lambda item: item.sort_key)
        ):
            raise ValueError("container images must use canonical order")
        image_names = tuple(item.name for item in self.container_images)
        if len(image_names) != len(set(image_names)):
            raise ValueError("container image names must be unique")
        if _SHA256_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("environment content hash must be a lowercase SHA-256 digest")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("case-study environment content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "platform_commit": self.platform_commit,
            "execution_profile": self.execution_profile,
            "operating_system": self.operating_system,
            "architecture": self.architecture,
            "python_version": self.python_version,
            "runtime_versions": [item.to_snapshot() for item in self.runtime_versions],
            "container_images": [item.to_snapshot() for item in self.container_images],
            "network_policy": self.network_policy,
            "captured_at": self.captured_at.isoformat(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_case_study_environment_identity(
    *,
    platform_commit: str,
    execution_profile: str,
    operating_system: str,
    architecture: str,
    python_version: str,
    runtime_versions: tuple[CaseStudyRuntimeVersion, ...],
    container_images: tuple[CaseStudyContainerImage, ...],
    network_policy: str,
    captured_at: datetime,
) -> CaseStudyEnvironmentIdentity:
    """Create an environment identity from explicit observed version evidence."""
    ordered_runtimes = tuple(sorted(runtime_versions, key=lambda item: item.sort_key))
    ordered_images = tuple(sorted(container_images, key=lambda item: item.sort_key))
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "platform_commit": platform_commit,
        "execution_profile": execution_profile,
        "operating_system": operating_system,
        "architecture": architecture,
        "python_version": python_version,
        "runtime_versions": [item.to_snapshot() for item in ordered_runtimes],
        "container_images": [item.to_snapshot() for item in ordered_images],
        "network_policy": network_policy,
        "captured_at": captured_at.isoformat(),
    }
    return CaseStudyEnvironmentIdentity(
        schema_version=1,
        platform_commit=platform_commit,
        execution_profile=execution_profile,
        operating_system=operating_system,
        architecture=architecture,
        python_version=python_version,
        runtime_versions=ordered_runtimes,
        container_images=ordered_images,
        network_policy=network_policy,
        captured_at=captured_at,
        content_hash=_hash(snapshot),
    )


def collect_local_case_study_environment_identity(
    *,
    platform_commit: str,
    execution_profile: str,
    runtime_versions: tuple[CaseStudyRuntimeVersion, ...] = (),
    container_images: tuple[CaseStudyContainerImage, ...] = (),
    network_policy: str,
) -> CaseStudyEnvironmentIdentity:
    """Capture host identity while requiring caller-supplied external runtime observations."""
    return create_case_study_environment_identity(
        platform_commit=platform_commit,
        execution_profile=execution_profile,
        operating_system=platform.platform(),
        architecture=platform.machine(),
        python_version=platform.python_version(),
        runtime_versions=runtime_versions,
        container_images=container_images,
        network_policy=network_policy,
        captured_at=datetime.now(UTC),
    )


def verify_case_study_environment_binding(
    run: CaseStudyRunRecord,
    environment: CaseStudyEnvironmentIdentity,
) -> None:
    """Require exact commit, profile, and environment-hash binding for one run."""
    if run.platform_commit != environment.platform_commit:
        raise ValueError("case-study run and environment use different platform commits")
    if run.execution_profile != environment.execution_profile:
        raise ValueError("case-study run and environment use different execution profiles")
    if run.environment_identity_hash != environment.content_hash:
        raise ValueError("case-study run is not bound to the supplied environment identity")
