"""Seed an attempt-owned Gradle wrapper cache from the pinned distribution bytes."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final
from uuid import UUID

GRADLE_DISTRIBUTION_IMAGE_PATH: Final = "/opt/orchestwin/gradle-9.5.0-bin.zip"
GRADLE_DISTRIBUTION_URL: Final = "https://services.gradle.org/distributions/gradle-9.5.0-bin.zip"
GRADLE_DISTRIBUTION_SHA256: Final = (
    "553c78f50dafcd54d65b9a444649057857469edf836431389695608536d6b746"
)
GRADLE_DISTRIBUTION_MAX_BYTES: Final = 512 * 1024 * 1024
_COPY_CHUNK_BYTES: Final = 1024 * 1024
# Gradle 9.5.0 PathAssembler: positive MD5(URL UTF-8), rendered in base 36.
# This value selects a cache directory; SHA-256 above authenticates the ZIP.
_DISTRIBUTION_CACHE_PATH: Final = (
    "wrapper/dists/gradle-9.5.0-bin/bvnork1r7n8i6kp5cnkibsc9q/gradle-9.5.0-bin.zip"
)


class GradleWrapperCacheSeedError(ValueError):
    """The source distribution or destination cache is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class GradleWrapperCacheSeedReceipt:
    """Content receipt for a copied ZIP, without claiming wrapper execution."""

    attempt_id: UUID
    gradle_user_home_relative: str
    destination_relative: str
    distribution_url: str
    distribution_sha256: str
    size_bytes: int


def seed_gradle_wrapper_cache(
    *, workspace_root: Path, attempt_id: UUID, distribution_path: Path
) -> GradleWrapperCacheSeedReceipt:
    """Copy the pinned ZIP into a new cache; Gradle must verify and extract it.

    The caller owns this workspace and must keep it idle during preparation.
    The helper and subsequent wrapper need the same filesystem owner, or explicit
    ownership preparation by the runtime. No shared cache or installation marker
    is created, and a previous wrapper cache is never reused or overwritten.
    """
    if not isinstance(attempt_id, UUID):
        raise GradleWrapperCacheSeedError("attempt_id must be a UUID")
    created_directories: list[tuple[Path, tuple[int, int]]] = []
    created_file: tuple[Path, tuple[int, int]] | None = None
    root_identity: tuple[int, int] | None = None
    try:
        _check_canonical_path(workspace_root, label="workspace root")
        if not workspace_root.is_dir():
            raise GradleWrapperCacheSeedError("workspace root must be an existing directory")
        root_identity = _identity(workspace_root.stat(follow_symlinks=False))
        _check_canonical_path(distribution_path, label="distribution source")
        source_metadata = distribution_path.stat(follow_symlinks=False)
        if not stat.S_ISREG(source_metadata.st_mode):
            raise GradleWrapperCacheSeedError("distribution source must be a regular file")
        _check_size(source_metadata.st_size)

        home_relative = f".orchestwin/jvm/{attempt_id.hex}/gradle"
        destination_relative = f"{home_relative}/{_DISTRIBUTION_CACHE_PATH}"
        wrapper_root = workspace_root / home_relative / "wrapper"
        destination = workspace_root / destination_relative
        _check_canonical_path(destination, label="wrapper cache")
        if wrapper_root.exists():
            raise GradleWrapperCacheSeedError("wrapper cache already exists")

        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(distribution_path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(source_metadata):
                raise GradleWrapperCacheSeedError("distribution source changed before opening")
            _check_size(opened.st_size)
            _check_canonical_path(distribution_path, label="distribution source")

            current = workspace_root
            for component in destination.relative_to(workspace_root).parts[:-1]:
                _check_root_identity(workspace_root, root_identity)
                current = current / component
                _check_canonical_path(current, label="wrapper cache")
                try:
                    current.mkdir(mode=0o755)
                except FileExistsError:
                    if current == wrapper_root:
                        raise GradleWrapperCacheSeedError("wrapper cache already exists") from None
                    if not current.is_dir():
                        raise GradleWrapperCacheSeedError(
                            "wrapper cache parent must be a directory"
                        ) from None
                else:
                    created_directories.append(
                        (current, _identity(current.stat(follow_symlinks=False)))
                    )
                _check_canonical_path(current, label="wrapper cache")

            _check_root_identity(workspace_root, root_identity)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(destination, flags, 0o644)
            with os.fdopen(descriptor, "wb") as target:
                created_file = (destination, _identity(os.fstat(target.fileno())))
                digest, size = _copy_distribution(source, target)
                target.flush()
                os.fsync(target.fileno())
            after = os.fstat(source.fileno())
            if (
                after.st_size != opened.st_size
                or after.st_mtime_ns != opened.st_mtime_ns
                or size != opened.st_size
            ):
                raise GradleWrapperCacheSeedError("distribution source changed while copying")
            if digest != GRADLE_DISTRIBUTION_SHA256:
                raise GradleWrapperCacheSeedError(
                    "distribution SHA-256 differs from the pinned ZIP"
                )

        _check_root_identity(workspace_root, root_identity)
        _check_canonical_path(destination, label="wrapper cache")
        if _identity(destination.stat(follow_symlinks=False)) != created_file[1]:
            raise GradleWrapperCacheSeedError("wrapper cache changed while copying")
        return GradleWrapperCacheSeedReceipt(
            attempt_id=attempt_id,
            gradle_user_home_relative=home_relative,
            destination_relative=destination_relative,
            distribution_url=GRADLE_DISTRIBUTION_URL,
            distribution_sha256=digest,
            size_bytes=size,
        )
    except (OSError, ValueError) as error:
        if root_identity is not None:
            _remove_owned_outputs(workspace_root, root_identity, created_file, created_directories)
        if isinstance(error, GradleWrapperCacheSeedError):
            raise
        raise GradleWrapperCacheSeedError(
            "could not read or seed the Gradle wrapper cache"
        ) from error


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _check_canonical_path(path: Path, *, label: str) -> None:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise GradleWrapperCacheSeedError(f"{label} must be an absolute canonical path")
    if any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)):
        raise GradleWrapperCacheSeedError(f"{label} must not contain filesystem redirects")
    if path.resolve() != path:
        raise GradleWrapperCacheSeedError(f"{label} must be an absolute canonical path")


def _check_root_identity(root: Path, expected: tuple[int, int]) -> None:
    _check_canonical_path(root, label="workspace root")
    if _identity(root.stat(follow_symlinks=False)) != expected:
        raise GradleWrapperCacheSeedError("workspace root changed while copying")


def _check_size(size: int) -> None:
    if not 0 < size <= GRADLE_DISTRIBUTION_MAX_BYTES:
        raise GradleWrapperCacheSeedError("distribution exceeds the non-empty 512 MiB byte limit")


def _copy_distribution(source: BinaryIO, target: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := source.read(min(_COPY_CHUNK_BYTES, GRADLE_DISTRIBUTION_MAX_BYTES - size + 1)):
        size += len(block)
        _check_size(size)
        digest.update(block)
        target.write(block)
    _check_size(size)
    return digest.hexdigest(), size


def _remove_owned_outputs(
    root: Path,
    root_identity: tuple[int, int],
    created_file: tuple[Path, tuple[int, int]] | None,
    created_directories: list[tuple[Path, tuple[int, int]]],
) -> None:
    """Remove only still-identical outputs; never recurse through an unknown tree."""
    try:
        _check_root_identity(root, root_identity)
        if created_file is not None:
            path, identity = created_file
            _check_canonical_path(path, label="wrapper cache")
            if path.exists() and _identity(path.stat(follow_symlinks=False)) == identity:
                path.unlink()
        for path, identity in reversed(created_directories):
            _check_canonical_path(path, label="wrapper cache")
            if path.exists() and _identity(path.stat(follow_symlinks=False)) == identity:
                path.rmdir()
    except (OSError, ValueError):
        # A replacement or foreign file belongs to the caller, not this helper.
        return
