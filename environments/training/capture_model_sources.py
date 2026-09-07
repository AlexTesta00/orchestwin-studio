#!/usr/bin/env python3
"""Capture only frozen small upstream model artifacts at exact revisions."""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.projects.requirements_primitives import canonical_json  # noqa: E402
from orchestwin.training.model_candidate_matrix_files import (  # noqa: E402
    FrozenModelCandidatePreflight,
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_source_evidence import (  # noqa: E402
    CapturedModelSourceEvidence,
    ModelSourceCaptureMode,
    ModelSourceEvidenceError,
    create_captured_model_source_evidence,
    expected_candidate_source_roles,
    serialize_captured_model_source_evidence,
)

MODEL_SOURCE_CAPTURE_SCHEMA_VERSION: Final = 1
EXIT_INVALID_INPUT: Final = 22
EXIT_CAPTURE_FAILED: Final = 25
_MODEL_SOURCE_NETWORK_GATE: Final = "ORCHESTWIN_MODEL_SOURCE_ALLOW_NETWORK"
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_MAX_CAPTURE_FILE_BYTES: Final = 100_000_000
_MAX_RESULT_MESSAGE_LENGTH: Final = 2_000

Downloader = Callable[..., str]


class ModelSourceCaptureFailure(RuntimeError):
    """Raised when the bounded Hugging Face source adapter cannot capture a file."""


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture only the model-card, license, and tokenizer metadata files frozen in "
            "the model candidate matrix. Network access is disabled unless "
            f"{_MODEL_SOURCE_NETWORK_GATE}=1."
        )
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("artifacts/model-sources"),
    )
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--captured-at")
    return parser.parse_args()


def _load_hugging_face_downloader() -> Downloader:
    try:
        from huggingface_hub import hf_hub_download
    except ModuleNotFoundError as error:
        raise ModelSourceCaptureFailure(
            "huggingface-hub is missing from the isolated training environment"
        ) from error
    return hf_hub_download


def _parse_timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ModelSourceEvidenceError("captured-at must use ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ModelSourceEvidenceError("captured-at must be timezone-aware")
    return parsed


def _resolved_snapshot_revision(path: Path) -> str:
    parts = path.parts
    matches = [
        parts[index + 1]
        for index, part in enumerate(parts[:-1])
        if part == "snapshots" and _REVISION_PATTERN.fullmatch(parts[index + 1])
    ]
    if len(matches) != 1:
        raise ModelSourceCaptureFailure(
            "Hugging Face cache path does not expose one exact snapshot revision"
        )
    return matches[0]


def _capture_file(
    *,
    candidate: FrozenModelCandidatePreflight,
    relative_path: str,
    downloader: Downloader,
    network_authorized: bool,
    cache_dir: Path | None,
) -> tuple[bytes, str]:
    values: dict[str, object] = {
        "repo_id": candidate.repository_id,
        "filename": relative_path,
        "revision": candidate.revision,
        "repo_type": "model",
        "local_files_only": not network_authorized,
        "force_download": False,
    }
    if cache_dir is not None:
        values["cache_dir"] = str(cache_dir)
    try:
        downloaded = Path(downloader(**values))
    except Exception as error:  # External adapter boundary; result is recorded by the CLI.
        raise ModelSourceCaptureFailure(
            f"failed to capture {relative_path}: {type(error).__name__}: {error}"
        ) from error
    if not downloaded.is_file():
        raise ModelSourceCaptureFailure(f"captured path is not a regular file: {relative_path}")
    size = downloaded.stat().st_size
    if size > _MAX_CAPTURE_FILE_BYTES:
        raise ModelSourceCaptureFailure(f"captured file exceeds size limit: {relative_path}")
    revision = _resolved_snapshot_revision(downloaded)
    try:
        content = downloaded.read_bytes()
    except OSError as error:
        raise ModelSourceCaptureFailure(f"cannot read captured file: {relative_path}") from error
    if len(content) != size:
        raise ModelSourceCaptureFailure(f"captured file changed while reading: {relative_path}")
    return content, revision


def capture_candidate_sources(
    *,
    candidate: FrozenModelCandidatePreflight,
    output_root: Path,
    downloader: Downloader,
    network_authorized: bool,
    cache_dir: Path | None,
    captured_at: datetime,
) -> tuple[CapturedModelSourceEvidence, Path]:
    """Capture one candidate's bounded files and write only copied regular artifacts."""
    expected = expected_candidate_source_roles(candidate)
    captured: dict[str, bytes] = {}
    revisions: set[str] = set()
    for relative_path in sorted(expected):
        content, revision = _capture_file(
            candidate=candidate,
            relative_path=relative_path,
            downloader=downloader,
            network_authorized=network_authorized,
            cache_dir=cache_dir,
        )
        captured[relative_path] = content
        revisions.add(revision)
    if revisions != {candidate.revision}:
        raise ModelSourceCaptureFailure("captured files do not share the frozen exact revision")

    evidence = create_captured_model_source_evidence(
        candidate=candidate,
        captured_files=captured,
        capture_mode=(
            ModelSourceCaptureMode.NETWORK_AUTHORIZED
            if network_authorized
            else ModelSourceCaptureMode.CACHE_ONLY
        ),
        captured_at=captured_at,
        resolved_revision=candidate.revision,
    )
    candidate_root = (output_root / candidate.candidate_id).resolve()
    files_root = candidate_root / "files"
    candidate_root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in captured.items():
        destination = _safe_destination(files_root, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes_atomically(destination, content)
    evidence_path = candidate_root / "evidence.json"
    _write_bytes_atomically(evidence_path, serialize_captured_model_source_evidence(evidence))
    return evidence, evidence_path


def _safe_destination(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    destination = root.joinpath(*pure.parts).resolve()
    root_resolved = root.resolve()
    if destination != root_resolved and root_resolved not in destination.parents:
        raise ModelSourceCaptureFailure("captured artifact path escapes its output root")
    return destination


def _write_bytes_atomically(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ModelSourceCaptureFailure(f"cannot write capture artifact: {path.name}") from error


def _write_capture_result(
    *,
    path: Path,
    candidate_id: str,
    status: str,
    network_authorized: bool,
    evidence: CapturedModelSourceEvidence | None,
    evidence_path: Path | None,
    failure_kind: str | None,
    failure_message: str | None,
) -> None:
    payload = {
        "schema_version": MODEL_SOURCE_CAPTURE_SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "status": status,
        "network_authorized": network_authorized,
        "evidence_content_hash": None if evidence is None else evidence.content_hash,
        "evidence_path": None if evidence_path is None else evidence_path.as_posix(),
        "failure_kind": failure_kind,
        "failure_message": (
            None
            if failure_message is None
            else " ".join(failure_message.split())[:_MAX_RESULT_MESSAGE_LENGTH]
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_bytes_atomically(path, canonical_json(payload).encode("utf-8"))


def main() -> int:
    arguments = _parse_arguments()
    matrix = load_frozen_model_candidate_matrix(_REPOSITORY_ROOT)
    try:
        candidate = matrix.candidate(arguments.candidate_id)
    except StopIteration:
        print("candidate is not present in the frozen matrix", file=sys.stderr)
        return EXIT_INVALID_INPUT

    output_root = arguments.output_root
    if not output_root.is_absolute():
        output_root = (_REPOSITORY_ROOT / "environments" / "training" / output_root).resolve()
    result_path = output_root / candidate.candidate_id / "capture-result.json"
    network_authorized = os.environ.get(_MODEL_SOURCE_NETWORK_GATE) == "1"
    try:
        evidence, evidence_path = capture_candidate_sources(
            candidate=candidate,
            output_root=output_root,
            downloader=_load_hugging_face_downloader(),
            network_authorized=network_authorized,
            cache_dir=arguments.cache_dir,
            captured_at=_parse_timestamp(arguments.captured_at),
        )
    except (ModelSourceEvidenceError, ModelSourceCaptureFailure, OSError) as error:
        _write_capture_result(
            path=result_path,
            candidate_id=candidate.candidate_id,
            status="FAILED",
            network_authorized=network_authorized,
            evidence=None,
            evidence_path=None,
            failure_kind=type(error).__name__,
            failure_message=str(error),
        )
        print(str(error), file=sys.stderr)
        return EXIT_CAPTURE_FAILED

    _write_capture_result(
        path=result_path,
        candidate_id=candidate.candidate_id,
        status="CAPTURED",
        network_authorized=network_authorized,
        evidence=evidence,
        evidence_path=evidence_path,
        failure_kind=None,
        failure_message=None,
    )
    print(evidence_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
