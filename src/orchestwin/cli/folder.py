from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import secrets
import shutil
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.knowledge.archive import VerifiedFolder

IGNORED_NAMES: Final = frozenset({".gitattributes", ".DS_Store", "Thumbs.db", "desktop.ini"})
GITATTRIBUTES: Final = ".gitattributes"
GITATTRIBUTES_CONTENT: Final = b"* -text\n"
MANIFEST_NAME: Final = "orchestwin.json"
INDEX_NAME: Final = "ORCHESTWIN.md"
FOLDER_STAGES: Final = ("brief", "team", "twins", "requirements", "design")
ENTRY_DATE_TIME: Final = (1980, 1, 1, 0, 0, 0)
ENTRY_PERMISSIONS: Final = 0o644 << 16
LINE_ENDINGS: Final = "LINE_ENDINGS"


@dataclass(frozen=True, slots=True)
class StageSummary:
    stage: str
    version_number: int | None
    gate_status: str | None


@dataclass(frozen=True, slots=True)
class FolderSummary:
    project_id: str
    project_name: str
    version_number: int
    content_hash: str
    created_at: str | None
    language: str | None
    file_count: int
    stages: tuple[StageSummary, ...]

    def stage(self, name: str) -> StageSummary | None:
        return next((entry for entry in self.stages if entry.stage == name), None)


def read_files(folder: Path) -> dict[str, str]:
    root = Path(folder)
    files: dict[str, str] = {}
    for directory, children, names in os.walk(root):
        children.sort()
        for name in sorted(names):
            path = Path(directory) / name
            if name in IGNORED_NAMES or path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            try:
                files[relative] = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                raise not_verified(root, "FOLDER_DOCUMENT_INVALID", relative) from None
    return files


def verify(folder: Path) -> VerifiedFolder:
    from orchestwin.knowledge.archive import KnowledgeArchiveError, verify_folder

    if not Path(folder).is_dir():
        raise not_verified(folder, "FOLDER_MISSING", str(folder))
    files = read_files(folder)
    try:
        return verify_folder(files)
    except KnowledgeArchiveError as error:
        rewritten = rewritten_file(files)
        if rewritten is None:
            raise not_verified(folder, error.code, error.detail or "") from None
        raise not_verified(folder, error.code, rewritten, reason=LINE_ENDINGS) from None


def verify_archive(content: bytes) -> VerifiedFolder:
    from orchestwin.knowledge.archive import KnowledgeArchiveError, read_verified_folder

    try:
        return read_verified_folder(content)
    except KnowledgeArchiveError as error:
        raise CliError(
            "FOLDER_NOT_VERIFIED", values={"code": error.code, "path": error.detail or ""}
        ) from None


def rewritten_file(files: Mapping[str, str]) -> str | None:
    from orchestwin.knowledge.archive import KnowledgeArchiveError, verify_folder

    try:
        manifest = json.loads(files.get(MANIFEST_NAME, ""))
    except (ValueError, RecursionError):
        return None
    digests = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(digests, dict):
        return None
    repaired = dict(files)
    first: str | None = None
    for path, digest in digests.items():
        content = files.get(path)
        if content is None or _digest(content) == digest:
            continue
        normalized = content.replace("\r\n", "\n")
        if normalized == content or _digest(normalized) != digest:
            return None
        repaired[path] = normalized
        first = first or path
    if first is None:
        return None
    try:
        verify_folder(repaired)
    except KnowledgeArchiveError:
        return None
    return first


def unpack(archive: bytes, folder: Path) -> VerifiedFolder:
    from orchestwin.knowledge.archive import safe_path

    verified = verify_archive(archive)
    target = Path(os.path.abspath(folder))
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = secrets.token_hex(6)
    staging = target.parent / f".{target.name}.new-{marker}"
    aside = target.parent / f".{target.name}.old-{marker}"
    try:
        _write_files(staging, verified.files, safe_path)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    _swap(staging, target, aside)
    return verified


def pack(folder: Path) -> bytes:
    files = read_files(folder)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ENTRY_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = ENTRY_PERMISSIONS
            archive.writestr(info, files[name].encode("utf-8"))
    return buffer.getvalue()


def summary(folder: Path) -> FolderSummary | None:
    path = Path(folder) / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise not_verified(folder, "FOLDER_DOCUMENT_INVALID", MANIFEST_NAME) from None
    found = summary_from(document)
    if found is None:
        raise not_verified(folder, "FOLDER_DOCUMENT_INVALID", MANIFEST_NAME)
    return found


def summary_from(document: object) -> FolderSummary | None:
    if not isinstance(document, dict):
        return None
    package = document.get("package")
    project = document.get("project")
    stages = document.get("stages")
    files = document.get("files")
    if not all(isinstance(part, dict) for part in (package, project, stages, files)):
        return None
    version = package.get("version_number")
    content_hash = package.get("content_hash")
    identifier = project.get("id")
    name = project.get("name")
    if not _integer(version) or not all(
        isinstance(value, str) for value in (content_hash, identifier, name)
    ):
        return None
    created = package.get("created_at")
    language = project.get("language")
    return FolderSummary(
        project_id=identifier,
        project_name=name,
        version_number=version,
        content_hash=content_hash,
        created_at=created if isinstance(created, str) else None,
        language=language if isinstance(language, str) else None,
        file_count=len(files) + 2,
        stages=tuple(_stage_summary(stage, stages.get(stage)) for stage in FOLDER_STAGES),
    )


def not_verified(folder: Path, code: str, path: str, *, reason: str | None = None) -> CliError:
    values: dict[str, object] = {"code": code, "path": path, "folder": str(folder)}
    if reason is not None:
        values["reason"] = reason
    return CliError("FOLDER_NOT_VERIFIED", values=values)


def _stage_summary(stage: str, entry: object) -> StageSummary:
    if not isinstance(entry, dict):
        return StageSummary(stage=stage, version_number=None, gate_status=None)
    version = entry.get("version_number")
    gate = entry.get("gate")
    status = gate.get("status") if isinstance(gate, dict) else None
    return StageSummary(
        stage=stage,
        version_number=version if _integer(version) else None,
        gate_status=status if isinstance(status, str) else None,
    )


def _write_files(
    staging: Path,
    files: Mapping[str, str],
    safe_path: Callable[[str], bool],
) -> None:
    staging.mkdir()
    root = staging.resolve()
    for name in sorted(files):
        destination = staging.joinpath(*name.split("/"))
        if not safe_path(name) or not destination.resolve().is_relative_to(root):
            raise CliError(
                "FOLDER_NOT_VERIFIED", values={"code": "FOLDER_ARCHIVE_INVALID", "path": name}
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(files[name].encode("utf-8"))
    (staging / GITATTRIBUTES).write_bytes(GITATTRIBUTES_CONTENT)


def _swap(staging: Path, target: Path, aside: Path) -> None:
    existed = target.exists()
    if existed:
        try:
            _rename(target, aside)
        except OSError as error:
            shutil.rmtree(staging, ignore_errors=True)
            raise _swap_failed(target, error) from error
    try:
        _rename(staging, target)
    except OSError as error:
        if existed:
            with contextlib.suppress(OSError):
                _rename(aside, target)
        shutil.rmtree(staging, ignore_errors=True)
        raise _swap_failed(target, error) from error
    if existed:
        shutil.rmtree(aside, ignore_errors=True)


def _rename(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _swap_failed(target: Path, error: OSError) -> CliError:
    blocked = error.filename if isinstance(error.filename, str) else str(target)
    return CliError("FOLDER_SWAP_FAILED", values={"folder": str(target), "path": blocked})


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
