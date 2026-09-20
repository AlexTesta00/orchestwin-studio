"""Reverify prepared Web sources and copy them into an owned mutable workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from orchestwin.web_execution.detection import WebDetectionSnapshot
from orchestwin.web_execution.workspaces import (
    _DIGEST,
    _MAX_FILE_BYTES,
    _MAX_FILES,
    _MAX_TOTAL_BYTES,
    PreparedWebWorkspace,
    WebWorkspaceError,
    _hash,
    _portable_path,
    _regular_parents,
)


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


@dataclass(frozen=True, slots=True)
class MutableWebPhaseWorkspace:
    """An isolated mutable tree; the handle retains its cleanup ownership identity."""

    path: Path
    source_revision_content_hash: str
    source_tree_hash: str
    _owned_parent: Path = field(repr=False)
    _workspaces_root: Path = field(repr=False)
    _parent_identity: tuple[int, int] = field(repr=False)
    _workspace_identity: tuple[int, int] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    def close(self) -> None:
        """Remove only the original owned tree, without following generated links."""
        if self._closed:
            return
        try:
            if (
                not self.path.is_absolute()
                or self.path.parent != self._owned_parent
                or self._owned_parent.parent != self._workspaces_root
                or self.path.name != "workspace"
            ):
                raise WebWorkspaceError("WEB_PHASE_WORKSPACE_OWNERSHIP_MISMATCH")
            _regular_parents(self._owned_parent)
            parent_metadata = self._owned_parent.lstat()
            if (
                not stat.S_ISDIR(parent_metadata.st_mode)
                or _identity(parent_metadata) != self._parent_identity
            ):
                raise WebWorkspaceError("WEB_PHASE_WORKSPACE_OWNERSHIP_MISMATCH")
            _regular_parents(self.path)
            try:
                metadata = self.path.lstat()
            except FileNotFoundError:
                metadata = None
            if metadata is not None:
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or _identity(metadata) != self._workspace_identity
                ):
                    raise WebWorkspaceError("WEB_PHASE_WORKSPACE_OWNERSHIP_MISMATCH")
                # The private parent cannot be changed by the runner. rmtree removes
                # descendant symlinks and Windows junctions without traversing them.
                shutil.rmtree(self.path)
            self._owned_parent.rmdir()
            object.__setattr__(self, "_closed", True)
        except OSError:
            raise WebWorkspaceError("WEB_PHASE_WORKSPACE_CLEANUP_FAILED") from None


def _validate_metadata(prepared: PreparedWebWorkspace) -> None:
    if any(
        not isinstance(value, str) or _DIGEST.fullmatch(value) is None
        for value in (prepared.source_revision_content_hash, prepared.source_tree_hash)
    ):
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_DIGEST_INVALID")
    if type(prepared.file_count) is not int or not 1 <= prepared.file_count <= _MAX_FILES:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_FILE_COUNT_INVALID")
    if (
        type(prepared.total_size_bytes) is not int
        or not 0 <= prepared.total_size_bytes <= _MAX_TOTAL_BYTES
    ):
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_TOTAL_BUDGET_EXCEEDED")


def _read_file(target: Path, metadata: os.stat_result) -> bytes:
    if not 0 <= metadata.st_size <= _MAX_FILE_BYTES:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_FILE_BUDGET_EXCEEDED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(target, flags | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(opened.st_mode)
            or _identity(opened) != _identity(metadata)
            or opened.st_size != metadata.st_size
        ):
            raise WebWorkspaceError("WEB_PHASE_WORKSPACE_SOURCE_CHANGED")
        _regular_parents(target)
        content = stream.read(metadata.st_size + 1)
    if len(content) != metadata.st_size:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_SOURCE_CHANGED")
    return content


def _capture_source(
    source: Path, prepared: PreparedWebWorkspace, snapshot: WebDetectionSnapshot
) -> tuple[tuple[str, bytes], ...]:
    paths = tuple(_portable_path(value) for value in snapshot.included_paths)
    if not 1 <= len(paths) <= _MAX_FILES:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_FILE_COUNT_INVALID")
    expected = set(paths)
    folded = {value.casefold() for value in paths}
    directories = {
        parent.as_posix()
        for value in paths
        for parent in PurePosixPath(value).parents
        if parent.as_posix() != "."
    }
    if len(folded) != len(paths) or any(value.casefold() in folded for value in directories):
        raise WebWorkspaceError("WEB_WORKSPACE_PATH_COLLISION")
    if not stat.S_ISDIR(source.lstat().st_mode):
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_SOURCE_MISSING")
    captured: dict[str, bytes] = {}
    pending = [source]
    total = 0
    while pending:
        directory = pending.pop()
        _regular_parents(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                target = directory / entry.name
                relative = _portable_path(target.relative_to(source).as_posix())
                _regular_parents(target)
                metadata = target.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    # Only source-file parents are valid, bounding traversal as well
                    # as reads. Prepared source materialization creates no other dirs.
                    if relative not in directories:
                        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_PATHS_MISMATCH")
                    pending.append(target)
                elif stat.S_ISREG(metadata.st_mode):
                    if relative not in expected or relative in captured:
                        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_PATHS_MISMATCH")
                    if len(captured) >= _MAX_FILES:
                        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_FILE_COUNT_INVALID")
                    total += metadata.st_size
                    if total > _MAX_TOTAL_BYTES:
                        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_TOTAL_BUDGET_EXCEEDED")
                    captured[relative] = _read_file(target, metadata)
                else:
                    raise WebWorkspaceError("WEB_PHASE_WORKSPACE_SPECIAL_FILE")
    if captured.keys() != expected:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_PATHS_MISMATCH")
    if len(captured) != prepared.file_count or total != prepared.total_size_bytes:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_COUNTS_MISMATCH")
    for item in snapshot.text_files:
        content = captured[item.normalized_path]
        if (
            content != item.content.encode("utf-8")
            or hashlib.sha256(content).hexdigest() != item.sha256_digest
        ):
            raise WebWorkspaceError("WEB_PHASE_WORKSPACE_TEXT_MISMATCH")
    ordered = tuple(sorted(captured.items(), key=lambda item: (item[0].casefold(), item[0])))
    tree_hash = _hash(
        {
            "files": [
                {
                    "normalized_path": name,
                    "sha256_digest": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
                for name, content in ordered
            ]
        }
    )
    if tree_hash != prepared.source_tree_hash:
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_TREE_HASH_MISMATCH")
    return ordered


def prepare_phase_workspace(
    prepared: PreparedWebWorkspace,
    snapshot: WebDetectionSnapshot,
    *,
    workspaces_root: Path,
) -> MutableWebPhaseWorkspace:
    """Capture and verify all source bytes before creating a fresh writable copy."""
    workspace = None
    parent = None
    parent_identity = None
    try:
        _validate_metadata(prepared)
        source = Path(prepared.path).absolute()
        output = Path(workspaces_root).absolute()
        _regular_parents(source)
        _regular_parents(output)
        if source == output or source in output.parents or output in source.parents:
            raise WebWorkspaceError("WEB_WORKSPACE_ROOTS_OVERLAP")
        contents = _capture_source(source, prepared, snapshot)
        output.mkdir(parents=True, exist_ok=True)
        _regular_parents(output)
        parent = Path(tempfile.mkdtemp(prefix="web-phase-", dir=output))
        parent_identity = _identity(parent.lstat())
        parent.chmod(0o700)
        target_root = parent / "workspace"
        target_root.mkdir(mode=0o777)
        workspace = MutableWebPhaseWorkspace(
            path=target_root,
            source_revision_content_hash=prepared.source_revision_content_hash,
            source_tree_hash=prepared.source_tree_hash,
            _owned_parent=parent,
            _workspaces_root=output,
            _parent_identity=parent_identity,
            _workspace_identity=_identity(target_root.lstat()),
        )
        target_root.chmod(0o777)
        for relative, content in contents:
            target = target_root.joinpath(*PurePosixPath(relative).parts)
            directory = target_root
            for part in PurePosixPath(relative).parts[:-1]:
                directory /= part
                directory.mkdir(exist_ok=True)
                _regular_parents(directory)
                directory.chmod(0o777)
            _regular_parents(target)
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o666)
        return workspace
    except (OSError, KeyError, TypeError, ValueError) as error:
        try:
            if workspace is not None:
                workspace.close()
            elif parent is not None:
                _regular_parents(parent)
                if _identity(parent.lstat()) != parent_identity:
                    raise WebWorkspaceError("WEB_PHASE_WORKSPACE_OWNERSHIP_MISMATCH") from None
                parent.rmdir()
        except OSError:
            raise WebWorkspaceError("WEB_PHASE_WORKSPACE_CLEANUP_FAILED") from None
        if isinstance(error, WebWorkspaceError):
            raise
        raise WebWorkspaceError("WEB_PHASE_WORKSPACE_PREPARATION_FAILED") from None
