"""Content-address actual files from a formal case evidence directory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from orchestwin.evaluation.case_runs import CaseStudyEvidenceReference
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind


@dataclass(frozen=True, slots=True)
class CaseStudyEvidenceMapEntry:
    """Declarative mapping from one observed file to the DoD criteria it supports."""

    kind: CaseStudyEvidenceKind
    relative_path: str
    criterion_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if "\\" in self.relative_path:
            raise ValueError("evidence map paths must use POSIX separators")
        path = PurePosixPath(self.relative_path)
        if not self.relative_path or path.is_absolute() or ".." in path.parts:
            raise ValueError("evidence map path must remain inside the evidence root")
        if not self.criterion_ids:
            raise ValueError("evidence map entry must reference at least one criterion")
        if len(self.criterion_ids) != len(set(self.criterion_ids)):
            raise ValueError("evidence map criterion IDs must be unique")
        if self.criterion_ids != tuple(sorted(self.criterion_ids)):
            raise ValueError("evidence map criterion IDs must use canonical order")

    @property
    def sort_key(self) -> tuple[str, str, tuple[str, ...]]:
        return (self.kind.value, self.relative_path, self.criterion_ids)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "criterion_ids": list(self.criterion_ids),
        }


def load_case_study_evidence_map(path: Path) -> tuple[CaseStudyEvidenceMapEntry, ...]:
    """Load a versioned evidence map without inventing or discovering semantic mappings."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported case-study evidence map version")
    entries = tuple(
        CaseStudyEvidenceMapEntry(
            kind=CaseStudyEvidenceKind(item["kind"]),
            relative_path=item["relative_path"],
            criterion_ids=tuple(item["criterion_ids"]),
        )
        for item in payload["entries"]
    )
    if not entries:
        raise ValueError("case-study evidence map must not be empty")
    paths = tuple(item.relative_path for item in entries)
    if len(paths) != len(set(paths)):
        raise ValueError("case-study evidence map paths must be unique")
    return tuple(sorted(entries, key=lambda item: item.sort_key))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_observed_file(evidence_root: Path, relative_path: str) -> Path:
    if evidence_root.is_symlink():
        raise ValueError("formal evidence root must not be a symlink")
    root = evidence_root.resolve(strict=True)
    relative = PurePosixPath(relative_path)
    current = evidence_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"formal evidence must not use symlinks: {relative_path}")
    try:
        candidate = (evidence_root / Path(*relative.parts)).resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError(f"formal evidence file is missing: {relative_path}") from error
    if not candidate.is_relative_to(root):
        raise ValueError(f"formal evidence escapes the evidence root: {relative_path}")
    if not candidate.is_file():
        raise ValueError(f"formal evidence path is not a file: {relative_path}")
    if candidate.stat().st_size < 1:
        raise ValueError(f"formal evidence file is empty: {relative_path}")
    return candidate


def capture_case_study_evidence(
    evidence_root: Path,
    entries: tuple[CaseStudyEvidenceMapEntry, ...],
) -> tuple[CaseStudyEvidenceReference, ...]:
    """Hash only files that actually exist under the run evidence root."""
    if not evidence_root.exists() or not evidence_root.is_dir():
        raise ValueError("formal case evidence root must be an existing directory")
    if not entries:
        raise ValueError("formal case evidence capture requires explicit map entries")
    references: list[CaseStudyEvidenceReference] = []
    for entry in entries:
        path = _resolve_observed_file(evidence_root, entry.relative_path)
        references.append(
            CaseStudyEvidenceReference(
                kind=entry.kind,
                relative_path=entry.relative_path,
                sha256_digest=_sha256_file(path),
                size_bytes=path.stat().st_size,
                criterion_ids=entry.criterion_ids,
            )
        )
    return tuple(sorted(references, key=lambda item: item.sort_key))
