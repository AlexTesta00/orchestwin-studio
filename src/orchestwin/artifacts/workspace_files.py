import os
import re
import stat
from pathlib import Path, PurePosixPath


class WorkspaceFileError(ValueError):
    pass


def regular_path(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise WorkspaceFileError("WORKSPACE_PATH_INVALID")
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise WorkspaceFileError("WORKSPACE_PATH_REDIRECTED")


def portable_path(value: str) -> str:
    pure = PurePosixPath(value)
    if not value or len(value) > 240 or pure.is_absolute() or pure.as_posix() != value:
        raise WorkspaceFileError("WORKSPACE_SOURCE_PATH_INVALID")
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
            raise WorkspaceFileError("WORKSPACE_SOURCE_PATH_INVALID")
    return value


def read_regular_file(path: Path, *, maximum_bytes: int) -> bytes:
    regular_path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise WorkspaceFileError("WORKSPACE_REGULAR_FILE_REQUIRED")
    if before.st_size > maximum_bytes:
        raise WorkspaceFileError("file exceeds the per-file size limit")
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
            raise WorkspaceFileError("WORKSPACE_FILE_CHANGED")
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
        raise WorkspaceFileError("WORKSPACE_FILE_CHANGED")
    return content
