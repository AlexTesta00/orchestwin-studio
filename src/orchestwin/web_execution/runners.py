"""Digest-pinned base images and repository-owned Web runner build recipes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus

_LOCK_SCHEMA_VERSION: Final = 1
_RUNNER_ID_PATTERN: Final = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_REPOSITORY_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[._/-][a-z0-9]+)*$")
_SUPPORTED_PLATFORM_SCOPES: Final = frozenset({"linux-amd64", "multi-arch-index"})


class WebRunnerKind(StrEnum):
    """Controlled container runner families required by Sprint 08."""

    BROWSER = "BROWSER"
    NODE = "NODE"
    PHP = "PHP"


@dataclass(frozen=True, slots=True, order=True)
class PinnedBaseImage:
    """Exact upstream image reference used by one repository-owned build recipe."""

    image_id: str
    reference: ContainerImageReference
    platform_scope: str
    source: str
    retrieved_at: str

    def __post_init__(self) -> None:
        _validate_runner_id(self.image_id, label="Web base-image ID")
        if self.platform_scope not in _SUPPORTED_PLATFORM_SCOPES:
            raise ValueError("unsupported Web base-image platform scope")
        if not self.source.startswith("https://"):
            raise ValueError("Web base-image source must be an HTTPS reference")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.retrieved_at) is None:
            raise ValueError("Web base-image retrieval date must use ISO date format")
        if ":latest@" in self.reference.value.casefold():
            raise ValueError("Web runner images must never use the latest tag")

    def to_snapshot(self) -> dict[str, str]:
        return {
            "image_id": self.image_id,
            "reference": self.reference.value,
            "platform_scope": self.platform_scope,
            "source": self.source,
            "retrieved_at": self.retrieved_at,
        }


@dataclass(frozen=True, slots=True, order=True)
class WebRunnerBuildDefinition:
    """Versioned runner recipe awaiting a locally observed final image digest."""

    runner_id: str
    kind: WebRunnerKind
    version: str
    dockerfile_path: str
    base_image_ids: tuple[str, ...]
    output_repository: str
    capability_status: ExecutionCapabilityStatus
    built_image_reference: ContainerImageReference | None

    def __post_init__(self) -> None:
        _validate_runner_id(self.runner_id, label="Web runner ID")
        _validate_relative_path(self.dockerfile_path)
        if not self.version or self.version != self.version.strip():
            raise ValueError("Web runner version must be normalized")
        if self.base_image_ids != tuple(sorted(self.base_image_ids)) or len(
            self.base_image_ids
        ) != len(set(self.base_image_ids)):
            raise ValueError("Web runner base-image IDs must be canonical and unique")
        if not self.base_image_ids:
            raise ValueError("Web runner build requires at least one pinned base image")
        if _REPOSITORY_PATTERN.fullmatch(self.output_repository) is None:
            raise ValueError("Web runner output repository must be normalized and unpinned")
        if self.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C:
            if self.built_image_reference is not None:
                raise ValueError("design-only runner must not claim a validated built image")
        elif self.built_image_reference is None:
            raise ValueError("Level D runner requires an observed built image digest")

    @property
    def is_built_and_pinned(self) -> bool:
        return self.built_image_reference is not None

    def to_snapshot(self) -> dict[str, object]:
        return {
            "runner_id": self.runner_id,
            "kind": self.kind.value,
            "version": self.version,
            "dockerfile_path": self.dockerfile_path,
            "base_image_ids": list(self.base_image_ids),
            "output_repository": self.output_repository,
            "capability_status": self.capability_status.value,
            "built_image_reference": (
                None if self.built_image_reference is None else self.built_image_reference.value
            ),
        }


@dataclass(frozen=True, slots=True)
class WebRunnerImageLock:
    """Canonical lock binding upstream digests to repository-owned runner recipes."""

    base_images: tuple[PinnedBaseImage, ...]
    runners: tuple[WebRunnerBuildDefinition, ...]
    schema_version: int = _LOCK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _LOCK_SCHEMA_VERSION:
            raise ValueError("unsupported Web runner image-lock schema")
        if self.base_images != tuple(sorted(self.base_images, key=lambda item: item.image_id)):
            raise ValueError("Web base images must use canonical ID order")
        if self.runners != tuple(sorted(self.runners, key=lambda item: item.runner_id)):
            raise ValueError("Web runners must use canonical ID order")
        base_ids = tuple(image.image_id for image in self.base_images)
        runner_ids = tuple(runner.runner_id for runner in self.runners)
        if len(base_ids) != len(set(base_ids)) or len(runner_ids) != len(set(runner_ids)):
            raise ValueError("Web runner lock IDs must be unique")
        available_bases = set(base_ids)
        if any(not set(runner.base_image_ids) <= available_bases for runner in self.runners):
            raise ValueError("Web runner references an unknown pinned base image")
        if {runner.kind for runner in self.runners} != set(WebRunnerKind):
            raise ValueError("Web runner lock must define Node, browser, and PHP runners")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._content_snapshot())).hexdigest()

    @property
    def ready_for_level_d_validation(self) -> bool:
        """Remain false until local builds provide exact final image digests."""
        return all(runner.is_built_and_pinned for runner in self.runners)

    def base_image(self, image_id: str) -> PinnedBaseImage:
        try:
            return next(image for image in self.base_images if image.image_id == image_id)
        except StopIteration as error:
            raise KeyError(image_id) from error

    def runner(self, kind: WebRunnerKind) -> WebRunnerBuildDefinition:
        try:
            return next(runner for runner in self.runners if runner.kind is kind)
        except StopIteration as error:
            raise KeyError(kind.value) from error

    def to_snapshot(self) -> dict[str, object]:
        return {**self._content_snapshot(), "content_hash": self.content_hash}

    def _content_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "base_images": [image.to_snapshot() for image in self.base_images],
            "runners": [runner.to_snapshot() for runner in self.runners],
        }


def load_web_runner_image_lock(path: Path) -> WebRunnerImageLock:
    """Load a repository-owned JSON lock without resolving moving tags."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Web runner image lock is not readable JSON") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != _LOCK_SCHEMA_VERSION:
        raise ValueError("Web runner image lock has an unsupported schema")
    raw_images = payload.get("base_images")
    raw_runners = payload.get("runners")
    if not isinstance(raw_images, list) or not isinstance(raw_runners, list):
        raise ValueError("Web runner image lock requires image and runner arrays")

    base_images = tuple(
        sorted(
            (_parse_base_image(item) for item in raw_images),
            key=lambda item: item.image_id,
        )
    )
    runners = tuple(
        sorted(
            (_parse_runner(item) for item in raw_runners),
            key=lambda item: item.runner_id,
        )
    )
    return WebRunnerImageLock(base_images=base_images, runners=runners)


def _parse_base_image(value: object) -> PinnedBaseImage:
    if not isinstance(value, dict):
        raise ValueError("Web runner base-image entries must be objects")
    return PinnedBaseImage(
        image_id=_required_string(value, "image_id"),
        reference=ContainerImageReference(_required_string(value, "reference")),
        platform_scope=_required_string(value, "platform_scope"),
        source=_required_string(value, "source"),
        retrieved_at=_required_string(value, "retrieved_at"),
    )


def _parse_runner(value: object) -> WebRunnerBuildDefinition:
    if not isinstance(value, dict):
        raise ValueError("Web runner entries must be objects")
    built_reference = value.get("built_image_reference")
    if built_reference is not None and not isinstance(built_reference, str):
        raise ValueError("Web runner built image reference must be a string or null")
    return WebRunnerBuildDefinition(
        runner_id=_required_string(value, "runner_id"),
        kind=WebRunnerKind(_required_string(value, "kind")),
        version=_required_string(value, "version"),
        dockerfile_path=_required_string(value, "dockerfile_path"),
        base_image_ids=tuple(sorted(_required_string_list(value, "base_image_ids"))),
        output_repository=_required_string(value, "output_repository"),
        capability_status=ExecutionCapabilityStatus(_required_string(value, "capability_status")),
        built_image_reference=(
            None if built_reference is None else ContainerImageReference(built_reference)
        ),
    )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Web runner image lock field {key} must be a non-empty string")
    return value


def _required_string_list(payload: dict[str, object], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Web runner image lock field {key} must be a string array")
    return value


def _validate_runner_id(value: str, *, label: str) -> None:
    if _RUNNER_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a portable lowercase identifier")


def _validate_relative_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Web runner Dockerfile path must be normalized and relative")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
