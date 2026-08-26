"""Content-addressed local filesystem storage for sandbox logs and artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import suppress
from pathlib import Path, PurePosixPath
from uuid import UUID

from orchestwin.sandbox.evidence import (
    SandboxArtifactReference,
    SandboxEvidenceStore,
    SandboxLogReference,
    SandboxLogStream,
)


class FileSystemSandboxEvidenceStore(SandboxEvidenceStore):
    """Immutable SHA-256 object store behind sandbox evidence references."""

    def __init__(self, root: Path) -> None:
        """Bind one adapter-local evidence root without creating it eagerly."""
        self._root = Path(root)

    def store_log(
        self,
        *,
        run_id: UUID,
        command_id: str,
        stream: SandboxLogStream,
        content: bytes,
    ) -> SandboxLogReference:
        """Store a complete raw stream and return content-addressed metadata."""
        _validate_bytes(content)
        digest, storage_key = self._store_content(content)
        return SandboxLogReference(
            stream=stream,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=storage_key,
        )

    def store_artifact(
        self,
        *,
        run_id: UUID,
        command_id: str,
        normalized_path: str,
        content: bytes,
        media_type: str,
    ) -> SandboxArtifactReference:
        """Store collected bytes while preserving their logical workspace path."""
        _validate_bytes(content)
        digest, storage_key = self._store_content(content)
        return SandboxArtifactReference(
            normalized_path=normalized_path,
            sha256_digest=digest,
            size_bytes=len(content),
            storage_key=storage_key,
            media_type=media_type,
        )

    def read(self, storage_key: str) -> bytes | None:
        """Resolve one verified object without following a storage symlink."""
        target = self._safe_target_for_key(storage_key)
        if target is None or target.is_symlink() or not target.is_file():
            return None

        try:
            content = target.read_bytes()
        except OSError:
            return None

        expected_digest = PurePosixPath(storage_key).name
        if hashlib.sha256(content).hexdigest() != expected_digest:
            return None
        return content

    def _store_content(self, content: bytes) -> tuple[str, str]:
        """Install one immutable object atomically without overwriting collisions."""
        digest = hashlib.sha256(content).hexdigest()
        storage_key = f"sha256/{digest[:2]}/{digest}"
        target_parent = self._prepare_parent(digest)
        if target_parent is None:
            raise OSError("sandbox evidence storage root could not be prepared safely")

        target = target_parent / digest
        if target.exists() or target.is_symlink():
            self._verify_existing(target, digest=digest, expected_content=content)
            return digest, storage_key

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{digest}.",
            suffix=".tmp",
            dir=target_parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, mode="wb") as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            try:
                os.link(temporary_path, target)
            except FileExistsError:
                self._verify_existing(target, digest=digest, expected_content=content)
            except OSError as error:
                if target.exists() or target.is_symlink():
                    self._verify_existing(target, digest=digest, expected_content=content)
                else:
                    raise OSError("sandbox evidence object could not be installed") from error
        finally:
            with suppress(OSError):
                temporary_path.unlink()

        self._verify_existing(target, digest=digest, expected_content=content)
        return digest, storage_key

    def _prepare_parent(self, digest: str) -> Path | None:
        """Create regular storage directories below a non-symlink root."""
        try:
            if self._root.is_symlink():
                return None
            self._root.mkdir(parents=True, exist_ok=True)
            if not self._root.is_dir() or self._root.is_symlink():
                return None

            current = self._root
            for part in ("sha256", digest[:2]):
                current = current / part
                if current.is_symlink():
                    return None
                current.mkdir(exist_ok=True)
                if not current.is_dir() or current.is_symlink():
                    return None
            return current
        except OSError:
            return None

    def _safe_target_for_key(self, storage_key: str) -> Path | None:
        """Resolve only canonical content-addressed keys under regular parents."""
        path = PurePosixPath(storage_key)
        parts = path.parts
        if (
            len(parts) != 3
            or parts[0] != "sha256"
            or len(parts[1]) != 2
            or len(parts[2]) != 64
            or parts[1] != parts[2][:2]
            or any(character not in "0123456789abcdef" for character in parts[2])
        ):
            return None

        parents = (
            self._root,
            self._root / "sha256",
            self._root / "sha256" / parts[1],
        )
        if any(parent.is_symlink() for parent in parents):
            return None
        return self._root.joinpath(*parts)

    @staticmethod
    def _verify_existing(
        target: Path,
        *,
        digest: str,
        expected_content: bytes,
    ) -> None:
        """Accept identical immutable content and reject corruption or special files."""
        if target.is_symlink() or not target.is_file():
            raise ValueError("sandbox evidence object path is not a regular file")
        try:
            existing_content = target.read_bytes()
        except OSError as error:
            raise OSError("sandbox evidence object could not be read") from error
        if (
            existing_content != expected_content
            or hashlib.sha256(existing_content).hexdigest() != digest
        ):
            raise ValueError("sandbox evidence object does not match its content address")


def _validate_bytes(content: bytes) -> None:
    """Reject implicit text conversion at the raw evidence boundary."""
    if not isinstance(content, bytes):
        raise TypeError("sandbox evidence content must be bytes")
