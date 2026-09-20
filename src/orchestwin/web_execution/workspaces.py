"""Restore verified Web source objects to a fresh execution workspace.

This is storage preparation, not authorization or execution. Callers must load
an owner-scoped revision first. Hashes prove consistency, not human approval.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

_MAX_FILES = 1000
_MAX_FILE_BYTES = 1048576
_MAX_TOTAL_BYTES = 20971520
_DIGEST = re.compile(r"[0-9a-f]{64}")
_RESERVED = frozenset({"con", "prn", "aux", "nul", "conin$", "conout$"})
_BLOCKED = frozenset({".git", ".ssh", ".orchestwin", ".venv", "node_modules", "vendor"})
_KEYS = frozenset(
    {
        "id",
        "project_id",
        "created_by_user_id",
        "version_number",
        "based_on",
        "target_selection",
        "validation_scope_hash",
        "origin",
        "files",
        "provenance_references",
        "related_failure_signature",
        "created_at",
        "source_tree_hash",
        "content_hash",
    }
)


class WebWorkspaceError(ValueError):
    """Safe preparation failure containing no file contents or credentials."""


@dataclass(frozen=True, slots=True)
class PreparedWebWorkspace:
    """Internal workspace handle; its host path is not a public API artifact."""

    path: Path
    source_revision_id: str
    source_revision_content_hash: str
    source_tree_hash: str
    file_count: int
    total_size_bytes: int


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _portable_path(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise WebWorkspaceError("WEB_WORKSPACE_PATH_INVALID")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or PureWindowsPath(value).drive
        or "\\" in value
        or ":" in value
        or pure.as_posix() != value
        or any(ord(char) < 32 for char in value)
    ):
        raise WebWorkspaceError("WEB_WORKSPACE_PATH_INVALID")
    for part in pure.parts:
        base = part.split(".", 1)[0].casefold()
        if (
            part in {"", ".", ".."}
            or part.endswith((" ", "."))
            or part.casefold() in _BLOCKED
            or part.casefold().startswith(".env")
            or base in _RESERVED
            or re.fullmatch(r"(?:com|lpt)[1-9\u00b9\u00b2\u00b3]", base)
            or any(char in part for char in '<>"|?*')
        ):
            raise WebWorkspaceError("WEB_WORKSPACE_PATH_INVALID")
    return value


def _regular_parents(path: Path) -> None:
    if ".." in path.parts:
        raise WebWorkspaceError("WEB_WORKSPACE_ROOT_UNSAFE")
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            raise WebWorkspaceError("WEB_WORKSPACE_REDIRECTED_PATH")


def _read_object(root: Path, entry: Mapping[str, object]) -> bytes:
    sha = entry.get("sha256_digest")
    size = entry.get("size_bytes")
    if not isinstance(sha, str) or _DIGEST.fullmatch(sha) is None:
        raise WebWorkspaceError("WEB_WORKSPACE_DIGEST_INVALID")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= _MAX_FILE_BYTES:
        raise WebWorkspaceError("WEB_WORKSPACE_FILE_BUDGET_EXCEEDED")
    key = f"sha256/{sha[:2]}/{sha}"
    if entry.get("storage_key") != key:
        raise WebWorkspaceError("WEB_WORKSPACE_STORAGE_KEY_INVALID")
    target = root / key
    _regular_parents(target)
    metadata = target.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != size:
        raise WebWorkspaceError("WEB_WORKSPACE_OBJECT_SIZE_MISMATCH")
    descriptor = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != size:
            raise WebWorkspaceError("WEB_WORKSPACE_OBJECT_CHANGED")
        content = stream.read(size + 1)
    if len(content) != size or hashlib.sha256(content).hexdigest() != sha:
        raise WebWorkspaceError("WEB_WORKSPACE_OBJECT_HASH_MISMATCH")
    return content


def materialize_web_source_snapshot(
    snapshot: Mapping[str, object],
    *,
    content_root: Path,
    workspaces_root: Path,
) -> PreparedWebWorkspace:
    """Verify every object before writing; never overwrite an existing workspace."""
    workspace = None
    try:
        if set(snapshot) != _KEYS:
            raise WebWorkspaceError("WEB_WORKSPACE_REVISION_SCHEMA_INVALID")
        revision_id = str(UUID(str(snapshot["id"])))
        revision_hash = _hash(
            {
                key: value
                for key, value in snapshot.items()
                if key not in {"content_hash", "source_tree_hash"}
            }
        )
        if revision_hash != snapshot["content_hash"]:
            raise WebWorkspaceError("WEB_WORKSPACE_REVISION_HASH_MISMATCH")
        entries = snapshot["files"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= _MAX_FILES:
            raise WebWorkspaceError("WEB_WORKSPACE_FILE_COUNT_INVALID")
        paths = [_portable_path(item["normalized_path"]) for item in entries]
        if paths != sorted(paths, key=lambda value: (value.casefold(), value)):
            raise WebWorkspaceError("WEB_WORKSPACE_PATH_ORDER_INVALID")
        folded = [path.casefold() for path in paths]
        if len(set(folded)) != len(folded) or any(
            prefix.as_posix().casefold() in folded
            for path in paths
            for prefix in PurePosixPath(path).parents
            if prefix.as_posix() != "."
        ):
            raise WebWorkspaceError("WEB_WORKSPACE_PATH_COLLISION")
        tree_hash = _hash(
            {
                "files": [
                    {key: item[key] for key in ("normalized_path", "sha256_digest", "size_bytes")}
                    for item in entries
                ]
            }
        )
        if tree_hash != snapshot["source_tree_hash"]:
            raise WebWorkspaceError("WEB_WORKSPACE_TREE_HASH_MISMATCH")
        sizes = [item["size_bytes"] for item in entries]
        if any(isinstance(size, bool) or not isinstance(size, int) or size < 0 for size in sizes):
            raise WebWorkspaceError("WEB_WORKSPACE_SIZE_INVALID")
        total = sum(sizes)
        if total > _MAX_TOTAL_BYTES:
            raise WebWorkspaceError("WEB_WORKSPACE_TOTAL_BUDGET_EXCEEDED")
        source = Path(content_root).absolute()
        output = Path(workspaces_root).absolute()
        _regular_parents(source)
        _regular_parents(output)
        if source == output or source in output.parents or output in source.parents:
            raise WebWorkspaceError("WEB_WORKSPACE_ROOTS_OVERLAP")
        if not source.is_dir():
            raise WebWorkspaceError("WEB_WORKSPACE_STORE_MISSING")
        # At most 20 MiB in memory; no partially materialized tree on bad input.
        contents = [_read_object(source, entry) for entry in entries]
        output.mkdir(parents=True, exist_ok=True)
        _regular_parents(output)
        workspace = Path(tempfile.mkdtemp(prefix=f"web-{revision_id[:8]}-", dir=output))
        workspace.chmod(0o755)
        for relative, content in zip(paths, contents, strict=True):
            target = workspace.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            _regular_parents(target.parent)
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o644)
        return PreparedWebWorkspace(
            path=workspace,
            source_revision_id=revision_id,
            source_revision_content_hash=revision_hash,
            source_tree_hash=tree_hash,
            file_count=len(entries),
            total_size_bytes=total,
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)
        if isinstance(error, WebWorkspaceError):
            raise
        raise WebWorkspaceError("WEB_WORKSPACE_PREPARATION_FAILED") from None
