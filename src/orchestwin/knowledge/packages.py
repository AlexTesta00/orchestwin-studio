from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

MAX_PACKAGE_FILE_NAME_LENGTH: Final = 200
MAX_PACKAGE_ARCHIVE_SIZE: Final = 64 * 1024 * 1024
_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class KnowledgePackageVersion:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    version_number: int
    schema_version: int
    content_hash: str
    archive_hash: str
    file_name: str
    file_count: int
    archive_size: int
    manifest: Mapping[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "knowledge package ID"),
            (self.project_id, "knowledge package project ID"),
            (self.owner_user_id, "knowledge package owner ID"),
        ):
            if not isinstance(value, UUID):
                raise ValueError(f"{label} must be a UUID")
        for value, label in (
            (self.version_number, "knowledge package version number"),
            (self.schema_version, "knowledge package schema version"),
            (self.file_count, "knowledge package file count"),
            (self.archive_size, "knowledge package archive size"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive integer")
        if self.archive_size > MAX_PACKAGE_ARCHIVE_SIZE:
            raise ValueError("knowledge package archive is too large")
        for value, label in (
            (self.content_hash, "knowledge package content hash"),
            (self.archive_hash, "knowledge package archive hash"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{label} must be a SHA-256 digest")
        if (
            not self.file_name
            or self.file_name != self.file_name.strip()
            or len(self.file_name) > MAX_PACKAGE_FILE_NAME_LENGTH
            or any(character in self.file_name for character in '/\\"\r\n')
        ):
            raise ValueError("knowledge package file name is invalid")
        if not isinstance(self.manifest, Mapping) or not self.manifest:
            raise ValueError("knowledge package manifest is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("knowledge package timestamp must be timezone-aware")

    @property
    def entries(self) -> tuple[str, ...]:
        files = self.manifest.get("files", {})
        names = {str(path) for path in files}
        for key in ("manifest", "index"):
            name = self.manifest.get(key)
            if isinstance(name, str):
                names.add(name)
        return tuple(sorted(names))

    def matches(self, archive: bytes) -> bool:
        return (
            len(archive) == self.archive_size
            and hashlib.sha256(archive).hexdigest() == self.archive_hash
        )


__all__ = [
    "MAX_PACKAGE_ARCHIVE_SIZE",
    "MAX_PACKAGE_FILE_NAME_LENGTH",
    "KnowledgePackageVersion",
]
