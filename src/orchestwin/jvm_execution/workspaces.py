"""Verified source copies and fresh, owned JVM execution workspaces."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from uuid import UUID

from orchestwin.artifacts.jvm_sources import JvmSourceRevision
from orchestwin.jvm_execution.dependency_setup import ControlledJvmNetwork, setup_configuration
from orchestwin.jvm_execution.detection import JvmDetectionSnapshot
from orchestwin.jvm_execution.launcher_cache import (
    GradleWrapperCacheSeedReceipt,
    seed_gradle_wrapper_cache,
)
from orchestwin.jvm_execution.targets import JvmBuildSystem


class JvmWorkspaceError(ValueError):
    """Safe filesystem boundary failure without source contents."""


def regular_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise JvmWorkspaceError("JVM_WORKSPACE_PATH_INVALID")
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise JvmWorkspaceError("JVM_WORKSPACE_REDIRECTED")


def portable_path(value: str) -> str:
    pure = PurePosixPath(value)
    if not value or len(value) > 240 or pure.is_absolute() or pure.as_posix() != value:
        raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_PATH_INVALID")
    for part in pure.parts:
        base = part.split(".", 1)[0].casefold()
        if (
            part in {".", ".."}
            or part.endswith((".", " "))
            or part.casefold() in {".git", ".ssh", ".orchestwin"}
            or part.casefold().startswith(".env")
            or base in {"con", "prn", "aux", "nul"}
            or re.fullmatch(r"(?:com|lpt)[1-9¹²³]", base)
            or any(ord(char) < 32 or char in '\\:<>"|?*' for char in part)
        ):
            raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_PATH_INVALID")
    return value


def read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    """Bound the read before allocation and verify the opened file's identity."""
    regular_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise JvmWorkspaceError("JVM_WORKSPACE_REGULAR_FILE_REQUIRED")
    if before.st_size > maximum_bytes:
        raise JvmWorkspaceError("JVM file exceeds the per-file size limit")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        ):
            raise JvmWorkspaceError("JVM_WORKSPACE_FILE_CHANGED")
        content = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    regular_path(path)
    current = path.lstat()
    if len(content) != before.st_size or (
        after.st_size,
        after.st_mtime_ns,
        current.st_dev,
        current.st_ino,
    ) != (before.st_size, before.st_mtime_ns, before.st_dev, before.st_ino):
        raise JvmWorkspaceError("JVM_WORKSPACE_FILE_CHANGED")
    return content


def require_jvm_workspace_owner() -> None:
    # On POSIX the controller must be able to remove files created by UID 65532.
    # Docker Desktop uses the owning Windows account's filesystem access instead.
    if os.name != "nt" and os.geteuid() not in {0, 65532}:
        raise JvmWorkspaceError("JVM_WORKSPACE_CONTROLLER_REQUIRES_RUNNER_UID_65532_OR_ROOT")


@dataclass(frozen=True, slots=True)
class JvmPhaseWorkspace:
    path: Path
    attempt_id: UUID
    revision: JvmSourceRevision
    parent: Path = field(repr=False)
    root: Path = field(repr=False)
    identities: tuple[tuple[int, int], ...] = field(repr=False)
    seed_receipt: GradleWrapperCacheSeedReceipt | None = None
    closed: bool = False

    def verify_owned(self) -> None:
        if (
            self.closed
            or self.path.parent != self.parent
            or self.parent.parent != self.root
            or self.path.name != "workspace"
        ):
            raise JvmWorkspaceError("JVM_WORKSPACE_OWNERSHIP_MISMATCH")
        for path, identity in zip((self.parent, self.path), self.identities, strict=True):
            regular_path(path)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                raise JvmWorkspaceError("JVM_WORKSPACE_OWNERSHIP_MISMATCH")

    def configure(self, network: ControlledJvmNetwork | None) -> None:
        """Materialize fixed settings only while the workspace has no live container."""
        self.verify_owned()
        config = setup_configuration(
            self.revision.target_selection.target, self.attempt_id, network
        )
        for relative, content in config.file_payloads:
            target = self.path / relative
            regular_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                read_regular_file(target, maximum_bytes=8192)
            descriptor, name = tempfile.mkstemp(prefix=".jvm-config-", dir=target.parent)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                temporary.chmod(0o644)
                self.verify_owned()
                regular_path(target)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        home = self.path / f".orchestwin/jvm/{self.attempt_id.hex}/home"
        regular_path(home)
        home.mkdir(parents=True, exist_ok=True)

    def _prepare_runner_access(self) -> None:
        # This tree contains only our verified copies and fixed launcher settings;
        # it has never been mounted. Keep the unmounted parent owned by the host.
        if os.name == "nt" or os.geteuid() != 0:
            return
        self.verify_owned()
        pending = [self.path]
        while pending:
            path = pending.pop()
            regular_path(path)
            metadata = path.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                pending.extend(path.iterdir())
            elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise JvmWorkspaceError("JVM_WORKSPACE_REGULAR_FILE_REQUIRED")
            os.chown(path, 65532, 65532, follow_symlinks=False)

    def close(self) -> None:
        """Remove only the original tree after all owned containers have been removed."""
        if self.closed:
            return
        self.verify_owned()
        if os.name != "nt" and os.geteuid() == 0:
            # A root controller need not have CAP_DAC_OVERRIDE. Reclaim directory
            # ownership only inside the verified, no-longer-mounted workspace.
            pending = [self.path]
            while pending:
                directory = pending.pop()
                regular_path(directory)
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise JvmWorkspaceError("JVM_WORKSPACE_CLEANUP_DIRECTORY_CHANGED")
                os.chown(directory, 0, 0, follow_symlinks=False)
                directory.chmod(stat.S_IMODE(info.st_mode) | stat.S_IRWXU)
                with os.scandir(directory) as entries:
                    pending.extend(
                        Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)
                    )

        retried = set()

        def writable_retry(function, path, error):
            target = Path(path)
            key = (function, target)
            if key in retried:
                raise JvmWorkspaceError("JVM_WORKSPACE_CLEANUP_RETRY_EXHAUSTED") from error
            retried.add(key)
            if not target.is_relative_to(self.path):
                raise JvmWorkspaceError("JVM_WORKSPACE_CLEANUP_ESCAPE") from error
            regular_path(target)
            info = target.stat()
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise JvmWorkspaceError("JVM_WORKSPACE_CLEANUP_HARDLINK_REFUSED") from error
            target.chmod(info.st_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            if function in {os.open, os.scandir}:
                shutil.rmtree(target, onexc=writable_retry)
            else:
                function(path)

        shutil.rmtree(self.path, onexc=writable_retry)
        regular_path(self.parent)
        if (self.parent.stat().st_dev, self.parent.stat().st_ino) != self.identities[0]:
            raise JvmWorkspaceError("JVM_WORKSPACE_OWNERSHIP_MISMATCH")
        self.parent.rmdir()
        object.__setattr__(self, "closed", True)


def prepare_jvm_phase_workspace(
    *,
    revision: JvmSourceRevision,
    snapshot: JvmDetectionSnapshot,
    source_path: Path,
    workspaces_root: Path,
    attempt_id: UUID,
    distribution_path: Path | None,
) -> JvmPhaseWorkspace:
    """Capture exact source bytes before allocating a fresh, per-attempt cache."""
    require_jvm_workspace_owner()
    for path in (source_path, workspaces_root):
        regular_path(path)
    if (
        source_path == workspaces_root
        or source_path in workspaces_root.parents
        or workspaces_root in source_path.parents
    ):
        raise JvmWorkspaceError("JVM_WORKSPACE_ROOTS_OVERLAP")
    paths = tuple(portable_path(entry.normalized_path) for entry in revision.files)
    if set(paths) != set(snapshot.included_paths) or not 1 <= len(paths) <= 1024:
        raise JvmWorkspaceError("JVM_WORKSPACE_SNAPSHOT_PATHS_MISMATCH")
    if any(
        PurePosixPath(path).parts[0].casefold() in {".gradle", "build", "target"} for path in paths
    ):
        raise JvmWorkspaceError("JVM_WORKSPACE_GENERATED_INPUT_FORBIDDEN")
    directories = {
        str(parent)
        for name in paths
        for parent in PurePosixPath(name).parents
        if str(parent) != "."
    }
    folded = {path.casefold() for path in paths}
    if (
        len(folded) != len(paths)
        or len({path.casefold() for path in directories}) != len(directories)
        or any(path.casefold() in folded for path in directories)
    ):
        raise JvmWorkspaceError("JVM_WORKSPACE_PATH_COLLISION")
    pending = [source_path]
    discovered = set()
    while pending:
        directory = pending.pop()
        regular_path(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                path = directory / entry.name
                relative = path.relative_to(source_path).as_posix()
                regular_path(path)
                if entry.is_dir(follow_symlinks=False) and relative in directories:
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and relative in paths:
                    discovered.add(relative)
                else:
                    raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_TREE_MISMATCH")
    if discovered != set(paths):
        raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_TREE_MISMATCH")
    contents = {}
    total = 0
    for entry in revision.files:
        total += entry.size_bytes
        if total > 64 * 1024 * 1024:
            raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_BUDGET_EXCEEDED")
        content = read_regular_file(
            source_path / entry.normalized_path,
            maximum_bytes=min(entry.size_bytes, 16 * 1024 * 1024),
        )
        if (
            len(content) != entry.size_bytes
            or hashlib.sha256(content).hexdigest() != entry.sha256_digest
        ):
            raise JvmWorkspaceError("JVM_WORKSPACE_SOURCE_HASH_MISMATCH")
        contents[entry.normalized_path] = content
    for text in snapshot.text_files:
        if (
            contents[text.normalized_path] != text.content.encode("utf-8")
            or hashlib.sha256(contents[text.normalized_path]).hexdigest() != text.sha256_digest
        ):
            raise JvmWorkspaceError("JVM_WORKSPACE_SNAPSHOT_TEXT_MISMATCH")
    workspaces_root.mkdir(parents=True, exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix=f"jvm-phase-{attempt_id.hex}-", dir=workspaces_root))
    path = parent / "workspace"
    try:
        parent.chmod(0o700)
        path.mkdir()
    except BaseException:
        # The new parent is still empty and has never been mounted.
        parent.rmdir()
        raise
    owned = JvmPhaseWorkspace(
        path,
        attempt_id,
        revision,
        parent,
        workspaces_root,
        tuple((item.stat().st_dev, item.stat().st_ino) for item in (parent, path)),
    )
    try:
        for name, content in contents.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o755 if name == "gradlew" else 0o644)
        if revision.target_selection.build_system is JvmBuildSystem.GRADLE_KOTLIN_DSL:
            if distribution_path is None:
                raise JvmWorkspaceError("JVM_WORKSPACE_PINNED_DISTRIBUTION_REQUIRED")
            object.__setattr__(
                owned,
                "seed_receipt",
                seed_gradle_wrapper_cache(
                    workspace_root=path, attempt_id=attempt_id, distribution_path=distribution_path
                ),
            )
        owned.configure(None)
        owned._prepare_runner_access()
        return owned
    except BaseException:
        owned.close()
        raise
