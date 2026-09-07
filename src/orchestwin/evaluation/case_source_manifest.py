"""Content-addressed manifest for the actual files used by formal case evidence harvesting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_relative_path(value: str) -> None:
    if not value or value != " ".join(value.split()) or "\\" in value:
        raise ValueError("observed source path must be normalized POSIX relative text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("observed source path must remain inside the evidence root")


def _resolve_actual_file(evidence_root: Path, relative_path: str) -> Path:
    if evidence_root.is_symlink():
        raise ValueError("formal evidence root must not be a symlink")
    root = evidence_root.resolve(strict=True)
    relative = PurePosixPath(relative_path)
    current = evidence_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"observed evidence must not use symlinks: {relative_path}")
    try:
        candidate = (evidence_root / Path(*relative.parts)).resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"observed evidence is missing: {relative_path}") from error
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"observed evidence is outside the evidence root: {relative_path}")
    if candidate.stat().st_size < 1:
        raise ValueError(f"observed evidence is empty: {relative_path}")
    return candidate


@dataclass(frozen=True, slots=True)
class ObservedEvidenceSource:
    """One immutable file identity from the real run evidence directory."""

    relative_path: str
    sha256_digest: str
    size_bytes: int

    def __post_init__(self) -> None:
        _validate_relative_path(self.relative_path)
        if len(self.sha256_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256_digest
        ):
            raise ValueError("observed source digest must be a lowercase SHA-256 digest")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 1:
            raise ValueError("observed source size must be a positive integer")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.relative_path, self.sha256_digest)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class ObservedEvidenceManifest:
    """Immutable manifest proving which actual files were read during metric harvesting."""

    schema_version: int
    case_id: str
    workflow_run_id: UUID
    sources: tuple[ObservedEvidenceSource, ...]
    captured_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported observed evidence manifest version")
        if not self.case_id or self.case_id != " ".join(self.case_id.split()):
            raise ValueError("observed evidence case ID must be normalized")
        if not self.sources:
            raise ValueError("observed evidence manifest must contain at least one source")
        if self.sources != tuple(sorted(self.sources, key=lambda item: item.sort_key)):
            raise ValueError("observed evidence sources must use canonical order")
        paths = tuple(source.relative_path for source in self.sources)
        if len(paths) != len(set(paths)):
            raise ValueError("observed evidence source paths must be unique")
        if self.captured_at.tzinfo is None:
            raise ValueError("observed evidence capture timestamp must be timezone-aware")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("observed evidence manifest content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "workflow_run_id": str(self.workflow_run_id),
            "sources": [source.to_snapshot() for source in self.sources],
            "captured_at": self.captured_at.isoformat(),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def capture_observed_evidence_manifest(
    *,
    evidence_root: Path,
    case_id: str,
    workflow_run_id: UUID,
    relative_paths: tuple[str, ...],
    captured_at: datetime,
) -> ObservedEvidenceManifest:
    """Hash only explicit non-empty files that physically exist under the evidence root."""
    if not relative_paths or len(relative_paths) != len(set(relative_paths)):
        raise ValueError("observed evidence paths must be non-empty and unique")
    sources = []
    for relative_path in sorted(relative_paths):
        _validate_relative_path(relative_path)
        path = _resolve_actual_file(evidence_root, relative_path)
        sources.append(
            ObservedEvidenceSource(
                relative_path=relative_path,
                sha256_digest=_sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
    ordered = tuple(sources)
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "case_id": case_id,
        "workflow_run_id": str(workflow_run_id),
        "sources": [source.to_snapshot() for source in ordered],
        "captured_at": captured_at.isoformat(),
    }
    return ObservedEvidenceManifest(
        schema_version=1,
        case_id=case_id,
        workflow_run_id=workflow_run_id,
        sources=ordered,
        captured_at=captured_at,
        content_hash=_hash(snapshot),
    )


def verify_observed_evidence_manifest(
    evidence_root: Path,
    manifest: ObservedEvidenceManifest,
) -> None:
    """Re-hash every source and reject evidence changed after manifest capture."""
    for source in manifest.sources:
        path = _resolve_actual_file(evidence_root, source.relative_path)
        if path.stat().st_size != source.size_bytes or _sha256_file(path) != source.sha256_digest:
            raise ValueError(f"observed evidence changed after capture: {source.relative_path}")


def write_observed_evidence_manifest(path: Path, manifest: ObservedEvidenceManifest) -> None:
    """Persist an immutable source manifest without replacement."""
    if path.exists():
        raise FileExistsError(f"observed evidence manifest already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(manifest.to_snapshot(), ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


def load_observed_evidence_manifest(path: Path) -> ObservedEvidenceManifest:
    """Load and revalidate one observed evidence manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ObservedEvidenceManifest(
        schema_version=payload["schema_version"],
        case_id=payload["case_id"],
        workflow_run_id=UUID(payload["workflow_run_id"]),
        sources=tuple(
            ObservedEvidenceSource(
                relative_path=item["relative_path"],
                sha256_digest=item["sha256_digest"],
                size_bytes=item["size_bytes"],
            )
            for item in payload["sources"]
        ),
        captured_at=datetime.fromisoformat(payload["captured_at"]),
        content_hash=payload["content_hash"],
    )
