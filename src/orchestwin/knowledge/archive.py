from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from orchestwin.knowledge.layout import (
    KNOWLEDGE_FOLDER_KIND,
    KNOWLEDGE_INDEX,
    KNOWLEDGE_MANIFEST,
    KNOWLEDGE_SCHEMA_VERSION,
    STAGES,
    stage_document,
)
from orchestwin.knowledge.schema import KnowledgeSchemaError, validate_document, validate_files

MAX_ARCHIVE_SIZE: Final = 16 * 1024 * 1024
MAX_ARCHIVE_ENTRIES: Final = 400
MAX_ENTRY_SIZE: Final = 8 * 1024 * 1024
MAX_FOLDER_SIZE: Final = 64 * 1024 * 1024
MAX_PATH_LENGTH: Final = 240
_FORBIDDEN_PATH_CHARACTERS: Final = frozenset('\\:*?"<>|\0')


class KnowledgeArchiveError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class VerifiedFolder:
    manifest: Mapping[str, object]
    documents: Mapping[str, Mapping[str, object]]
    files: Mapping[str, str]

    @property
    def project_id(self) -> str:
        return str(self.manifest["project"]["id"])

    @property
    def project_name(self) -> str:
        return str(self.manifest["project"]["name"])

    @property
    def package_version(self) -> int:
        return int(self.manifest["package"]["version_number"])

    @property
    def content_hash(self) -> str:
        return str(self.manifest["package"]["content_hash"])


def safe_path(name: str) -> bool:
    if not name or len(name) > MAX_PATH_LENGTH or name != name.strip():
        return False
    if name.startswith("/") or any(character in _FORBIDDEN_PATH_CHARACTERS for character in name):
        return False
    parts = name.split("/")
    return all(part not in {"", ".", ".."} and part == part.strip() for part in parts)


def read_folder_archive(content: bytes) -> dict[str, str]:
    if not content:
        raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID")
    if len(content) > MAX_ARCHIVE_SIZE:
        raise KnowledgeArchiveError("FOLDER_ARCHIVE_TOO_LARGE")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as error:
        raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID") from error
    with archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
            raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID", "entries")
        names = [item.filename for item in entries]
        if len(names) != len(set(names)):
            raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID", "duplicate entries")
        unsafe = [name for name in names if not safe_path(name)]
        if unsafe:
            raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID", unsafe[0][:MAX_PATH_LENGTH])
        if (
            any(item.file_size > MAX_ENTRY_SIZE for item in entries)
            or sum(item.file_size for item in entries) > MAX_FOLDER_SIZE
        ):
            raise KnowledgeArchiveError("FOLDER_ARCHIVE_TOO_LARGE")
        files: dict[str, str] = {}
        total = 0
        for item in entries:
            try:
                with archive.open(item) as stream:
                    data = stream.read(MAX_ENTRY_SIZE + 1)
            except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as error:
                raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID", item.filename) from error
            total += len(data)
            if len(data) > MAX_ENTRY_SIZE or total > MAX_FOLDER_SIZE:
                raise KnowledgeArchiveError("FOLDER_ARCHIVE_TOO_LARGE")
            try:
                files[item.filename] = data.decode("utf-8")
            except UnicodeDecodeError as error:
                raise KnowledgeArchiveError("FOLDER_ARCHIVE_INVALID", item.filename) from error
    return files


def _json(files: Mapping[str, str], path: str) -> Mapping[str, object]:
    if path not in files:
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_MISSING", path)
    try:
        document = json.loads(files[path])
    except ValueError as error:
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_INVALID", path) from error
    if not isinstance(document, dict):
        raise KnowledgeArchiveError("FOLDER_DOCUMENT_INVALID", path)
    return document


def verify_folder(files: Mapping[str, str]) -> VerifiedFolder:
    manifest = _json(files, KNOWLEDGE_MANIFEST)
    try:
        validate_document("manifest", manifest)
    except KnowledgeSchemaError as error:
        raise KnowledgeArchiveError(
            "FOLDER_DOCUMENT_INVALID", f"{KNOWLEDGE_MANIFEST}: {error.location}"
        ) from error
    if (
        manifest["kind"] != KNOWLEDGE_FOLDER_KIND
        or manifest["schema_version"] != KNOWLEDGE_SCHEMA_VERSION
    ):
        raise KnowledgeArchiveError("FOLDER_SCHEMA_UNSUPPORTED")
    digests = manifest["files"]
    for path, digest in digests.items():
        if path not in files:
            raise KnowledgeArchiveError("FOLDER_DOCUMENT_MISSING", path)
        if hashlib.sha256(files[path].encode("utf-8")).hexdigest() != digest:
            raise KnowledgeArchiveError("FOLDER_TAMPERED", path)
    unlisted = sorted(set(files) - set(digests) - {KNOWLEDGE_MANIFEST, KNOWLEDGE_INDEX})
    if unlisted:
        raise KnowledgeArchiveError("FOLDER_TAMPERED", unlisted[0])
    try:
        validate_files(files)
    except KnowledgeSchemaError as error:
        raise KnowledgeArchiveError(
            "FOLDER_DOCUMENT_INVALID", f"{error.document}: {error.location}"
        ) from error
    documents = {stage: _json(files, stage_document(stage)) for stage in STAGES}
    for stage, document in documents.items():
        entry = manifest["stages"][stage]
        if (
            document["content_hash"] != entry["content_hash"]
            or document["id"] != entry["version_id"]
            or document["project_id"] != manifest["project"]["id"]
        ):
            raise KnowledgeArchiveError("FOLDER_TAMPERED", stage_document(stage))
    return VerifiedFolder(manifest=manifest, documents=documents, files=dict(files))


def read_verified_folder(content: bytes) -> VerifiedFolder:
    return verify_folder(read_folder_archive(content))


__all__ = [
    "MAX_ARCHIVE_ENTRIES",
    "MAX_ARCHIVE_SIZE",
    "MAX_ENTRY_SIZE",
    "MAX_FOLDER_SIZE",
    "KnowledgeArchiveError",
    "VerifiedFolder",
    "read_folder_archive",
    "read_verified_folder",
    "safe_path",
    "verify_folder",
]
