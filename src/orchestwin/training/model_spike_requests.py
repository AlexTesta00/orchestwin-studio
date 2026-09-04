"""Deterministic evidence-bound requests and execution plans for live model spikes."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import UUID, uuid5

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_SHA256,
)
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    FrozenModelCandidateMatrix,
    FrozenModelCandidatePreflight,
)
from orchestwin.training.model_source_evidence import (
    CapturedModelSourceEvidence,
    ModelSourceFileRole,
    validate_captured_model_source_evidence,
)

MODEL_SPIKE_PLAN_SCHEMA_VERSION: Final = 1
MODEL_SPIKE_REQUEST_SCHEMA_VERSION: Final = 1
MODEL_SPIKE_PLAN_ID: Final = "user-twin-evaluator-model-spike-plan-v1"
MODEL_SPIKE_SELECTION_STATUS: Final = "NO_MODEL_SELECTED"
MODEL_SPIKE_REQUEST_NAMESPACE: Final = UUID("a3c6bec6-30f2-4db7-997f-47676434e044")
_MAX_PLAN_BYTES: Final = 2_000_000
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")


class ModelSpikeRequestError(ValueError):
    """Raised when source evidence or a request plan is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class ModelSpikeRequestReference:
    """One exact request file and its upstream source-evidence identity."""

    candidate_id: str
    run_id: UUID
    request_reference: str
    request_sha256: str
    source_evidence_content_hash: str
    source_evidence_file_sha256: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.request_reference, label="model-spike request reference")
        for value, label in (
            (self.request_sha256, "model-spike request digest"),
            (self.source_evidence_content_hash, "source evidence content hash"),
            (self.source_evidence_file_sha256, "source evidence file digest"),
        ):
            _validate_sha256(value, label=label)

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "run_id": str(self.run_id),
            "request_reference": self.request_reference,
            "request_sha256": self.request_sha256,
            "source_evidence_content_hash": self.source_evidence_content_hash,
            "source_evidence_file_sha256": self.source_evidence_file_sha256,
        }


@dataclass(frozen=True, slots=True)
class ModelSpikeExecutionPlan:
    """Immutable plan binding every request to frozen inputs and observed environment."""

    plan_id: str
    created_at: datetime
    candidate_matrix_sha256: str
    candidate_matrix_content_hash: str
    benchmark_suite_sha256: str
    benchmark_suite_content_hash: str
    package_lock_sha256: str
    environment_sha256: str
    requests: tuple[ModelSpikeRequestReference, ...]
    selection_status: str
    content_hash: str
    schema_version: int = MODEL_SPIKE_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SPIKE_PLAN_SCHEMA_VERSION:
            raise ModelSpikeRequestError("unsupported model-spike plan schema")
        if self.plan_id != MODEL_SPIKE_PLAN_ID:
            raise ModelSpikeRequestError("unexpected model-spike plan identity")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ModelSpikeRequestError("model-spike plan timestamp must be timezone-aware")
        if self.candidate_matrix_sha256 != FROZEN_MODEL_CANDIDATE_MATRIX_SHA256:
            raise ModelSpikeRequestError("model-spike plan matrix file identity changed")
        if self.candidate_matrix_content_hash != FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH:
            raise ModelSpikeRequestError("model-spike plan matrix content identity changed")
        if self.benchmark_suite_sha256 != FROZEN_BENCHMARK_SUITE_SHA256:
            raise ModelSpikeRequestError("model-spike plan benchmark file identity changed")
        if self.benchmark_suite_content_hash != FROZEN_BENCHMARK_SUITE_CONTENT_HASH:
            raise ModelSpikeRequestError("model-spike plan benchmark content identity changed")
        for value, label in (
            (self.package_lock_sha256, "model-spike package lock digest"),
            (self.environment_sha256, "model-spike environment digest"),
            (self.content_hash, "model-spike plan content hash"),
        ):
            _validate_sha256(value, label=label)
        if self.requests != tuple(sorted(self.requests, key=lambda item: item.sort_key)):
            raise ModelSpikeRequestError("model-spike requests must use canonical order")
        if not self.requests or len({item.candidate_id for item in self.requests}) != len(
            self.requests
        ):
            raise ModelSpikeRequestError("model-spike plan requires unique requests")
        if self.selection_status != MODEL_SPIKE_SELECTION_STATUS:
            raise ModelSpikeRequestError("model-spike plan cannot preselect a model")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeRequestError("model-spike plan content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "created_at": self.created_at.isoformat(),
            "candidate_matrix_sha256": self.candidate_matrix_sha256,
            "candidate_matrix_content_hash": self.candidate_matrix_content_hash,
            "benchmark_suite_sha256": self.benchmark_suite_sha256,
            "benchmark_suite_content_hash": self.benchmark_suite_content_hash,
            "package_lock_sha256": self.package_lock_sha256,
            "environment_sha256": self.environment_sha256,
            "requests": [item.to_snapshot() for item in self.requests],
            "selection_status": self.selection_status,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}

    def request(self, candidate_id: str) -> ModelSpikeRequestReference:
        return next(item for item in self.requests if item.candidate_id == candidate_id)


def create_model_spike_request_payload(
    *,
    candidate: FrozenModelCandidatePreflight,
    matrix: FrozenModelCandidateMatrix,
    source_evidence: CapturedModelSourceEvidence,
    package_lock_sha256: str,
    environment_sha256: str,
    requested_at: datetime,
    run_id: UUID,
) -> dict[str, object]:
    """Create the exact request schema consumed by the isolated live runner."""
    validate_captured_model_source_evidence(evidence=source_evidence, candidate=candidate)
    if requested_at.tzinfo is None or requested_at.utcoffset() is None:
        raise ModelSpikeRequestError("model-spike request timestamp must be timezone-aware")
    _validate_sha256(package_lock_sha256, label="model-spike package lock digest")
    _validate_sha256(environment_sha256, label="model-spike environment digest")
    model_card = source_evidence.file_for_role(ModelSourceFileRole.MODEL_CARD)
    license_file = source_evidence.file_for_role(ModelSourceFileRole.LICENSE)
    payload: dict[str, object] = {
        "schema_version": MODEL_SPIKE_REQUEST_SCHEMA_VERSION,
        "run_id": str(run_id),
        "candidate_id": candidate.candidate_id,
        "candidate_matrix_sha256": FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        "candidate_matrix_content_hash": FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        "model_repository": candidate.repository_id,
        "model_revision": candidate.revision,
        "tokenizer_repository": candidate.tokenizer_repository_id,
        "tokenizer_revision": candidate.tokenizer_revision,
        "model_card_sha256": model_card.sha256,
        "license_evidence_sha256": license_file.sha256,
        "benchmark_suite_sha256": FROZEN_BENCHMARK_SUITE_SHA256,
        "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
        "package_lock_sha256": package_lock_sha256,
        "environment_sha256": environment_sha256,
        "generation": matrix.generation.to_snapshot(),
        "requested_at": requested_at.isoformat(),
    }
    payload["request_sha256"] = snapshot_content_hash(payload)
    return payload


def materialize_model_spike_execution_plan(
    *,
    matrix: FrozenModelCandidateMatrix,
    source_evidence: Iterable[tuple[CapturedModelSourceEvidence, str]],
    output_root: Path,
    package_lock_sha256: str,
    environment_sha256: str,
    created_at: datetime,
) -> tuple[ModelSpikeExecutionPlan, Path]:
    """Write canonical request files and one content-addressed execution plan."""
    evidence_by_candidate = {
        item.candidate_id: (item, file_sha) for item, file_sha in source_evidence
    }
    expected_ids = {candidate.candidate_id for candidate in matrix.candidates}
    if set(evidence_by_candidate) != expected_ids:
        raise ModelSpikeRequestError("source evidence set must cover every frozen candidate")
    output_root = output_root.resolve()
    requests_root = output_root / "requests"
    requests_root.mkdir(parents=True, exist_ok=True)
    references: list[ModelSpikeRequestReference] = []
    for candidate in matrix.candidates:
        evidence, evidence_file_sha256 = evidence_by_candidate[candidate.candidate_id]
        _validate_sha256(evidence_file_sha256, label="source evidence file digest")
        run_id = uuid5(
            MODEL_SPIKE_REQUEST_NAMESPACE,
            ":".join(
                (
                    candidate.candidate_id,
                    candidate.revision,
                    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
                    created_at.isoformat(),
                )
            ),
        )
        payload = create_model_spike_request_payload(
            candidate=candidate,
            matrix=matrix,
            source_evidence=evidence,
            package_lock_sha256=package_lock_sha256,
            environment_sha256=environment_sha256,
            requested_at=created_at,
            run_id=run_id,
        )
        request_path = requests_root / f"{candidate.candidate_id}.json"
        _write_canonical_json(request_path, payload)
        reference = request_path.relative_to(output_root).as_posix()
        references.append(
            ModelSpikeRequestReference(
                candidate_id=candidate.candidate_id,
                run_id=run_id,
                request_reference=reference,
                request_sha256=str(payload["request_sha256"]),
                source_evidence_content_hash=evidence.content_hash,
                source_evidence_file_sha256=evidence_file_sha256,
            )
        )
    canonical_references = tuple(sorted(references, key=lambda item: item.sort_key))
    semantic = {
        "schema_version": MODEL_SPIKE_PLAN_SCHEMA_VERSION,
        "plan_id": MODEL_SPIKE_PLAN_ID,
        "created_at": created_at.isoformat(),
        "candidate_matrix_sha256": FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        "candidate_matrix_content_hash": FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        "benchmark_suite_sha256": FROZEN_BENCHMARK_SUITE_SHA256,
        "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
        "package_lock_sha256": package_lock_sha256,
        "environment_sha256": environment_sha256,
        "requests": [item.to_snapshot() for item in canonical_references],
        "selection_status": MODEL_SPIKE_SELECTION_STATUS,
    }
    plan = ModelSpikeExecutionPlan(
        plan_id=MODEL_SPIKE_PLAN_ID,
        created_at=created_at,
        candidate_matrix_sha256=FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
        candidate_matrix_content_hash=FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
        benchmark_suite_sha256=FROZEN_BENCHMARK_SUITE_SHA256,
        benchmark_suite_content_hash=FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
        package_lock_sha256=package_lock_sha256,
        environment_sha256=environment_sha256,
        requests=canonical_references,
        selection_status=MODEL_SPIKE_SELECTION_STATUS,
        content_hash=snapshot_content_hash(semantic),
    )
    plan_path = output_root / "execution-plan.json"
    _write_canonical_json(plan_path, plan.to_snapshot())
    return plan, plan_path


def load_model_spike_execution_plan(path: Path) -> ModelSpikeExecutionPlan:
    """Load one strict bounded plan and validate its canonical content identity."""
    payload = _read_json_object(path, maximum_bytes=_MAX_PLAN_BYTES, label="model-spike plan")
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "plan_id",
            "created_at",
            "candidate_matrix_sha256",
            "candidate_matrix_content_hash",
            "benchmark_suite_sha256",
            "benchmark_suite_content_hash",
            "package_lock_sha256",
            "environment_sha256",
            "requests",
            "selection_status",
            "content_hash",
        },
        label="model-spike plan",
    )
    raw_requests = payload.get("requests")
    if not isinstance(raw_requests, list):
        raise ModelSpikeRequestError("model-spike plan requests must be an array")
    requests = tuple(_parse_request_reference(item) for item in raw_requests)
    created_at_raw = _required_string(payload, "created_at")
    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except ValueError as error:
        raise ModelSpikeRequestError("model-spike plan timestamp must use ISO-8601") from error
    plan = ModelSpikeExecutionPlan(
        schema_version=_required_integer(payload, "schema_version"),
        plan_id=_required_string(payload, "plan_id"),
        created_at=created_at,
        candidate_matrix_sha256=_required_string(payload, "candidate_matrix_sha256"),
        candidate_matrix_content_hash=_required_string(payload, "candidate_matrix_content_hash"),
        benchmark_suite_sha256=_required_string(payload, "benchmark_suite_sha256"),
        benchmark_suite_content_hash=_required_string(payload, "benchmark_suite_content_hash"),
        package_lock_sha256=_required_string(payload, "package_lock_sha256"),
        environment_sha256=_required_string(payload, "environment_sha256"),
        requests=requests,
        selection_status=_required_string(payload, "selection_status"),
        content_hash=_required_string(payload, "content_hash"),
    )
    if plan.to_snapshot() != payload:
        raise ModelSpikeRequestError("model-spike plan is not a canonical snapshot")
    return plan


def request_payload_sha256(payload: Mapping[str, object]) -> str:
    """Return the semantic digest expected in a live runner request."""
    without_hash = dict(payload)
    without_hash.pop("request_sha256", None)
    return snapshot_content_hash(without_hash)


def sha256_file(path: Path) -> str:
    """Hash one regular file without following a mutable directory abstraction."""
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeRequestError("evidence input must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_request_reference(value: object) -> ModelSpikeRequestReference:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelSpikeRequestError("model-spike request reference must be an object")
    _require_exact_keys(
        value,
        {
            "candidate_id",
            "run_id",
            "request_reference",
            "request_sha256",
            "source_evidence_content_hash",
            "source_evidence_file_sha256",
        },
        label="model-spike request reference",
    )
    try:
        run_id = UUID(_required_string(value, "run_id"))
    except ValueError as error:
        raise ModelSpikeRequestError("model-spike request run ID must be a UUID") from error
    return ModelSpikeRequestReference(
        candidate_id=_required_string(value, "candidate_id"),
        run_id=run_id,
        request_reference=_required_string(value, "request_reference"),
        request_sha256=_required_string(value, "request_sha256"),
        source_evidence_content_hash=_required_string(value, "source_evidence_content_hash"),
        source_evidence_file_sha256=_required_string(value, "source_evidence_file_sha256"),
    )


def _read_json_object(path: Path, *, maximum_bytes: int, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeRequestError(f"{label} must be a regular file")
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise ModelSpikeRequestError(f"{label} exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeRequestError(f"{label} must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSpikeRequestError(f"{label} must contain a JSON object")
    return payload


def _write_canonical_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(canonical_json(dict(payload)), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ModelSpikeRequestError(f"cannot write model-spike artifact: {path.name}") from error


def _validate_relative_path(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModelSpikeRequestError(f"{label} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelSpikeRequestError(f"{label} must be traversal-free")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ModelSpikeRequestError(f"{label} must use lowercase SHA-256")


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ModelSpikeRequestError(f"{label} fields do not match schema version 1")


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSpikeRequestError(f"{key} must be a normalized string")
    return value


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelSpikeRequestError(f"{key} must be an integer")
    return value
