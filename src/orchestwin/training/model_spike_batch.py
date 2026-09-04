"""Governed sequential execution records for evidence-bound live model spikes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.model_spike_requests import (
    ModelSpikeExecutionPlan,
    ModelSpikeRequestReference,
    load_model_spike_execution_plan,
    request_payload_sha256,
    sha256_file,
)

MODEL_SPIKE_BATCH_SCHEMA_VERSION: Final = 1
MODEL_SPIKE_BATCH_NETWORK_GATE: Final = "ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK"
MODEL_SPIKE_BATCH_ALL_GATE: Final = "ORCHESTWIN_MODEL_SPIKE_ALLOW_ALL"
_MAX_LOG_BYTES: Final = 32_000_000
_MAX_TIMEOUT_SECONDS: Final = 14_400


class ModelSpikeBatchError(ValueError):
    """Raised when a batch selection, workspace, or process artifact is invalid."""


class ModelSpikeProcessStatus(StrEnum):
    """Observed process outcome without converting failures into successes."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    RESULT_MISSING = "RESULT_MISSING"


@dataclass(frozen=True, slots=True)
class ModelSpikeProcessRecord:
    """Immutable process and artifact evidence for one attempted candidate."""

    candidate_id: str
    request_reference: str
    request_sha256: str
    result_reference: str | None
    result_file_sha256: str | None
    stdout_reference: str
    stdout_sha256: str
    stderr_reference: str
    stderr_sha256: str
    exit_code: int | None
    status: ModelSpikeProcessStatus
    started_at: datetime
    completed_at: datetime
    duration_milliseconds: int
    network_authorized: bool
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_reference, "batch request reference"),
            (self.stdout_reference, "batch stdout reference"),
            (self.stderr_reference, "batch stderr reference"),
        ):
            _validate_relative_path(value, label=label)
        if self.result_reference is not None:
            _validate_relative_path(self.result_reference, label="batch result reference")
        for value, label in (
            (self.request_sha256, "batch request digest"),
            (self.stdout_sha256, "batch stdout digest"),
            (self.stderr_sha256, "batch stderr digest"),
            (self.content_hash, "batch process record hash"),
        ):
            _validate_sha256(value, label=label)
        if (self.result_reference is None) != (self.result_file_sha256 is None):
            raise ModelSpikeBatchError("batch result reference and digest must appear together")
        if self.result_file_sha256 is not None:
            _validate_sha256(self.result_file_sha256, label="batch result file digest")
        for value, label in (
            (self.started_at, "batch process start"),
            (self.completed_at, "batch process completion"),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ModelSpikeBatchError(f"{label} timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ModelSpikeBatchError("batch process completion precedes its start")
        if self.duration_milliseconds < 0:
            raise ModelSpikeBatchError("batch process duration must not be negative")
        if self.status is ModelSpikeProcessStatus.SUCCEEDED and self.exit_code != 0:
            raise ModelSpikeBatchError("successful model-spike process must exit zero")
        if self.status is ModelSpikeProcessStatus.TIMED_OUT and self.exit_code is not None:
            raise ModelSpikeBatchError("timed-out process cannot report an exit code")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeBatchError("batch process record content hash is inconsistent")

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "request_reference": self.request_reference,
            "request_sha256": self.request_sha256,
            "result_reference": self.result_reference,
            "result_file_sha256": self.result_file_sha256,
            "stdout_reference": self.stdout_reference,
            "stdout_sha256": self.stdout_sha256,
            "stderr_reference": self.stderr_reference,
            "stderr_sha256": self.stderr_sha256,
            "exit_code": self.exit_code,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_milliseconds": self.duration_milliseconds,
            "network_authorized": self.network_authorized,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ModelSpikeBatchRecord:
    """Immutable record proving which candidates were attempted once and in which order."""

    plan_content_hash: str
    plan_file_sha256: str
    selected_candidate_ids: tuple[str, ...]
    processes: tuple[ModelSpikeProcessRecord, ...]
    started_at: datetime
    completed_at: datetime
    network_authorized: bool
    execution_complete: bool
    all_succeeded: bool
    content_hash: str
    schema_version: int = MODEL_SPIKE_BATCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SPIKE_BATCH_SCHEMA_VERSION:
            raise ModelSpikeBatchError("unsupported model-spike batch schema")
        for value, label in (
            (self.plan_content_hash, "batch plan content hash"),
            (self.plan_file_sha256, "batch plan file digest"),
            (self.content_hash, "batch content hash"),
        ):
            _validate_sha256(value, label=label)
        if not self.selected_candidate_ids:
            raise ModelSpikeBatchError("model-spike batch must select at least one candidate")
        if len(set(self.selected_candidate_ids)) != len(self.selected_candidate_ids):
            raise ModelSpikeBatchError("model-spike batch candidate selection must be unique")
        if tuple(item.candidate_id for item in self.processes) != self.selected_candidate_ids:
            raise ModelSpikeBatchError("model-spike process order differs from batch selection")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ModelSpikeBatchError("batch start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ModelSpikeBatchError("batch completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ModelSpikeBatchError("batch completion precedes its start")
        expected_complete = len(self.processes) == len(self.selected_candidate_ids)
        if self.execution_complete != expected_complete:
            raise ModelSpikeBatchError("batch completion flag is inconsistent")
        expected_success = expected_complete and all(
            item.status is ModelSpikeProcessStatus.SUCCEEDED for item in self.processes
        )
        if self.all_succeeded != expected_success:
            raise ModelSpikeBatchError("batch success flag is inconsistent")
        if any(item.network_authorized != self.network_authorized for item in self.processes):
            raise ModelSpikeBatchError("batch network evidence differs across processes")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeBatchError("model-spike batch content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_content_hash": self.plan_content_hash,
            "plan_file_sha256": self.plan_file_sha256,
            "selected_candidate_ids": list(self.selected_candidate_ids),
            "processes": [item.to_snapshot() for item in self.processes],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "network_authorized": self.network_authorized,
            "execution_complete": self.execution_complete,
            "all_succeeded": self.all_succeeded,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


def select_model_spike_requests(
    *,
    plan: ModelSpikeExecutionPlan,
    candidate_ids: Iterable[str],
    all_requested: bool,
    all_authorized: bool,
) -> tuple[ModelSpikeRequestReference, ...]:
    """Select a canonical subset while requiring an explicit gate for the full matrix."""
    requested = tuple(candidate_ids)
    if all_requested:
        if requested:
            raise ModelSpikeBatchError("cannot combine --all with explicit candidate IDs")
        if not all_authorized:
            raise ModelSpikeBatchError(
                f"full matrix execution requires {MODEL_SPIKE_BATCH_ALL_GATE}=1"
            )
        return plan.requests
    if not requested:
        raise ModelSpikeBatchError("select at least one candidate or use the authorized --all")
    if len(set(requested)) != len(requested):
        raise ModelSpikeBatchError("candidate IDs must not be repeated")
    references: list[ModelSpikeRequestReference] = []
    for candidate_id in requested:
        try:
            references.append(plan.request(candidate_id))
        except StopIteration as error:
            raise ModelSpikeBatchError(
                f"candidate is not present in the execution plan: {candidate_id}"
            ) from error
    return tuple(references)


def execute_model_spike_batch(
    *,
    plan_path: Path,
    output_root: Path,
    runner_path: Path,
    selected: tuple[ModelSpikeRequestReference, ...],
    network_authorized: bool,
    timeout_seconds: int,
    python_executable: str = sys.executable,
    environment: Mapping[str, str] | None = None,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.perf_counter,
) -> tuple[ModelSpikeBatchRecord, Path]:
    """Execute each candidate once in a separate process and preserve all raw evidence."""
    if not 60 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS:
        raise ModelSpikeBatchError("model-spike timeout must be between 60 and 14400 seconds")
    plan = load_model_spike_execution_plan(plan_path)
    output_root = output_root.resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ModelSpikeBatchError("model-spike output directory must be absent or empty")
    output_root.mkdir(parents=True, exist_ok=True)
    if runner_path.is_symlink() or not runner_path.is_file():
        raise ModelSpikeBatchError("model-spike runner must be a regular file")
    current_time = now or (lambda: datetime.now(UTC))
    started_at = current_time()
    processes: list[ModelSpikeProcessRecord] = []
    for reference in selected:
        plan_reference = plan.request(reference.candidate_id)
        if plan_reference != reference:
            raise ModelSpikeBatchError("selected request differs from the execution plan")
        process = _execute_one(
            plan_path=plan_path,
            output_root=output_root,
            runner_path=runner_path,
            reference=reference,
            network_authorized=network_authorized,
            timeout_seconds=timeout_seconds,
            python_executable=python_executable,
            environment=environment,
            now=current_time,
            monotonic=monotonic,
        )
        processes.append(process)
    completed_at = current_time()
    semantic = {
        "schema_version": MODEL_SPIKE_BATCH_SCHEMA_VERSION,
        "plan_content_hash": plan.content_hash,
        "plan_file_sha256": sha256_file(plan_path),
        "selected_candidate_ids": [item.candidate_id for item in selected],
        "processes": [item.to_snapshot() for item in processes],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "network_authorized": network_authorized,
        "execution_complete": len(processes) == len(selected),
        "all_succeeded": len(processes) == len(selected)
        and all(item.status is ModelSpikeProcessStatus.SUCCEEDED for item in processes),
    }
    record = ModelSpikeBatchRecord(
        plan_content_hash=plan.content_hash,
        plan_file_sha256=sha256_file(plan_path),
        selected_candidate_ids=tuple(item.candidate_id for item in selected),
        processes=tuple(processes),
        started_at=started_at,
        completed_at=completed_at,
        network_authorized=network_authorized,
        execution_complete=True,
        all_succeeded=bool(semantic["all_succeeded"]),
        content_hash=snapshot_content_hash(semantic),
    )
    record_path = output_root / "batch-result.json"
    _write_json(record_path, record.to_snapshot())
    return record, record_path


def _execute_one(
    *,
    plan_path: Path,
    output_root: Path,
    runner_path: Path,
    reference: ModelSpikeRequestReference,
    network_authorized: bool,
    timeout_seconds: int,
    python_executable: str,
    environment: Mapping[str, str] | None,
    now: Callable[[], datetime],
    monotonic: Callable[[], float],
) -> ModelSpikeProcessRecord:
    plan_root = plan_path.resolve().parent
    request_path = _resolve_reference(plan_root, reference.request_reference)
    _verify_request_file(request_path, reference)
    run_root = output_root / "runs" / reference.candidate_id
    run_root.mkdir(parents=True, exist_ok=False)
    result_path = run_root / "result.json"
    stdout_path = run_root / "stdout.log"
    stderr_path = run_root / "stderr.log"
    command = (
        python_executable,
        str(runner_path.resolve()),
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    )
    process_environment = dict(os.environ if environment is None else environment)
    if network_authorized:
        process_environment[MODEL_SPIKE_BATCH_NETWORK_GATE] = "1"
        process_environment.pop("HF_HUB_OFFLINE", None)
        process_environment.pop("TRANSFORMERS_OFFLINE", None)
    else:
        process_environment.pop(MODEL_SPIKE_BATCH_NETWORK_GATE, None)
        process_environment["HF_HUB_OFFLINE"] = "1"
        process_environment["TRANSFORMERS_OFFLINE"] = "1"
    started_at = now()
    started_clock = monotonic()
    exit_code: int | None
    status: ModelSpikeProcessStatus
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        try:
            completed = subprocess.run(
                command,
                cwd=runner_path.resolve().parent,
                env=process_environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            exit_code = completed.returncode
            if not result_path.is_file():
                status = ModelSpikeProcessStatus.RESULT_MISSING
            elif exit_code == 0:
                status = ModelSpikeProcessStatus.SUCCEEDED
            else:
                status = ModelSpikeProcessStatus.FAILED
        except subprocess.TimeoutExpired:
            exit_code = None
            status = ModelSpikeProcessStatus.TIMED_OUT
    duration = max(0, round((monotonic() - started_clock) * 1000))
    completed_at = now()
    _enforce_log_size(stdout_path)
    _enforce_log_size(stderr_path)
    result_reference = None
    result_sha256 = None
    if result_path.is_file():
        result_reference = result_path.relative_to(output_root).as_posix()
        result_sha256 = sha256_file(result_path)
    semantic = {
        "candidate_id": reference.candidate_id,
        "request_reference": reference.request_reference,
        "request_sha256": reference.request_sha256,
        "result_reference": result_reference,
        "result_file_sha256": result_sha256,
        "stdout_reference": stdout_path.relative_to(output_root).as_posix(),
        "stdout_sha256": _sha256_regular_file(stdout_path),
        "stderr_reference": stderr_path.relative_to(output_root).as_posix(),
        "stderr_sha256": _sha256_regular_file(stderr_path),
        "exit_code": exit_code,
        "status": status.value,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_milliseconds": duration,
        "network_authorized": network_authorized,
    }
    record = ModelSpikeProcessRecord(
        candidate_id=reference.candidate_id,
        request_reference=reference.request_reference,
        request_sha256=reference.request_sha256,
        result_reference=result_reference,
        result_file_sha256=result_sha256,
        stdout_reference=str(semantic["stdout_reference"]),
        stdout_sha256=str(semantic["stdout_sha256"]),
        stderr_reference=str(semantic["stderr_reference"]),
        stderr_sha256=str(semantic["stderr_sha256"]),
        exit_code=exit_code,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration,
        network_authorized=network_authorized,
        content_hash=snapshot_content_hash(semantic),
    )
    _write_json(run_root / "process.json", record.to_snapshot())
    return record


def _verify_request_file(
    path: Path,
    reference: ModelSpikeRequestReference,
) -> None:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeBatchError("model-spike request must be canonical UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSpikeBatchError("model-spike request must contain a JSON object")
    if raw != canonical_json(payload).encode("utf-8"):
        raise ModelSpikeBatchError("model-spike request file is not canonical JSON")
    if payload.get("request_sha256") != reference.request_sha256:
        raise ModelSpikeBatchError("request identity differs from the execution plan")
    if request_payload_sha256(payload) != reference.request_sha256:
        raise ModelSpikeBatchError("model-spike request content digest is inconsistent")


def _resolve_reference(root: Path, reference: str) -> Path:
    _validate_relative_path(reference, label="model-spike artifact reference")
    path = root.joinpath(*PurePosixPath(reference).parts).resolve()
    root_resolved = root.resolve()
    if root_resolved not in path.parents:
        raise ModelSpikeBatchError("model-spike artifact reference escapes its root")
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeBatchError("model-spike artifact reference must identify a regular file")
    return path


def _enforce_log_size(path: Path) -> None:
    if path.stat().st_size > _MAX_LOG_BYTES:
        raise ModelSpikeBatchError(f"model-spike log exceeds size limit: {path.name}")


def _sha256_regular_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeBatchError("batch artifact must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(canonical_json(dict(payload)), encoding="utf-8")
        os.replace(temporary, path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ModelSpikeBatchError(f"cannot write batch artifact: {path.name}") from error


def _validate_relative_path(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModelSpikeBatchError(f"{label} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelSpikeBatchError(f"{label} must be traversal-free")


def _validate_sha256(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ModelSpikeBatchError(f"{label} must use lowercase SHA-256")
