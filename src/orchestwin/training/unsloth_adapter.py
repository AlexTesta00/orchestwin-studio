"""Typed Unsloth QLoRA adapter with a constrained subprocess boundary."""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.qlora_configurations import QloraTrainingConfiguration

UNSLOTH_TRAINING_SCHEMA_VERSION: Final = 1

_MAX_MESSAGE_LENGTH: Final = 2_000
_MAX_REFERENCE_LENGTH: Final = 512
_MAX_INPUT_FILE_BYTES: Final = 512 * 1024 * 1024
_MAX_PROCESS_LOG_TEXT_LENGTH: Final = 1_000_000
_MAX_RESUME_CHECKPOINT_BYTES: Final = 4 * 1024 * 1024 * 1024
_ALLOWED_ENVIRONMENT_KEYS: Final = (
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "HF_TOKEN",
    "HOME",
    "PATH",
    "TRANSFORMERS_CACHE",
)
_EXIT_FAILURES: Final = {
    20: "MISSING_DEPENDENCY",
    21: "GPU_UNAVAILABLE",
    22: "INVALID_INPUT",
    23: "OUT_OF_MEMORY",
    24: "INTERRUPTED",
    25: "TRAINING_FAILED",
    26: "EXPORT_FAILED",
}


class QloraTrainingStatus(StrEnum):
    """Final outcome of one bounded training process."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    TIMED_OUT = "TIMED_OUT"


class QloraTrainingFailureKind(StrEnum):
    """Stable failure categories exposed by the training adapter."""

    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    INTERRUPTED = "INTERRUPTED"
    TIMEOUT = "TIMEOUT"
    TRAINING_FAILED = "TRAINING_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    INVALID_RESULT = "INVALID_RESULT"
    PROCESS_FAILED = "PROCESS_FAILED"


@dataclass(frozen=True, slots=True)
class TrainingMetricObservation:
    """One numeric trainer observation at an optional global step."""

    name: str
    value: float
    step: int | None

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.name,
            label="training metric name",
            maximum_length=128,
        )
        if normalized != self.name or any(character.isspace() for character in self.name):
            raise ValueError("training metric name must be a normalized identifier")
        if (
            not isinstance(self.value, (int, float))
            or isinstance(self.value, bool)
            or not math.isfinite(float(self.value))
        ):
            raise ValueError("training metric value must be finite and numeric")
        if self.step is not None:
            validate_positive_integer(self.step, label="training metric step")

    @property
    def sort_key(self) -> tuple[int, str]:
        return (-1 if self.step is None else self.step, self.name)

    def to_snapshot(self) -> dict[str, object]:
        return {"name": self.name, "value": float(self.value), "step": self.step}


@dataclass(frozen=True, slots=True)
class TrainingCheckpointEvidence:
    """Content-addressed checkpoint directory produced during one run."""

    step: int
    relative_path: str
    content_sha256: str

    def __post_init__(self) -> None:
        validate_positive_integer(self.step, label="training checkpoint step")
        _validate_relative_path(self.relative_path, label="training checkpoint path")
        validate_sha256(self.content_sha256, label="training checkpoint digest")

    @property
    def sort_key(self) -> tuple[int, str]:
        return (self.step, self.relative_path)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "step": self.step,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class UnslothTrainingRequest:
    """Exact authorized inputs staged for the isolated WSL2 trainer."""

    run_id: UUID
    owner_user_id: UUID
    configuration: QloraTrainingConfiguration
    train_dataset_path: str
    validation_dataset_path: str
    output_directory: str
    package_lock_sha256: str
    environment_sha256: str
    requested_at: datetime
    resume_checkpoint_path: str | None = None
    schema_version: int = UNSLOTH_TRAINING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != UNSLOTH_TRAINING_SCHEMA_VERSION:
            raise ValueError("unsupported Unsloth training request schema version")
        for value, label in (
            (self.train_dataset_path, "training dataset path"),
            (self.validation_dataset_path, "validation dataset path"),
            (self.output_directory, "training output directory"),
        ):
            _validate_relative_path(value, label=label)
        if not self.train_dataset_path.endswith(".jsonl"):
            raise ValueError("training dataset path must identify a JSONL file")
        if not self.validation_dataset_path.endswith(".jsonl"):
            raise ValueError("validation dataset path must identify a JSONL file")
        if self.train_dataset_path == self.validation_dataset_path:
            raise ValueError("training and validation dataset paths must be distinct")
        if self.resume_checkpoint_path is not None:
            _validate_relative_path(
                self.resume_checkpoint_path,
                label="resume checkpoint path",
            )
        output = PurePosixPath(self.output_directory)
        for input_path in (
            PurePosixPath(self.train_dataset_path),
            PurePosixPath(self.validation_dataset_path),
        ):
            if output == input_path or output in input_path.parents:
                raise ValueError("training output directory cannot contain dataset inputs")
        validate_sha256(self.package_lock_sha256, label="training package lock digest")
        validate_sha256(self.environment_sha256, label="training environment digest")
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("training request timestamp must be timezone-aware")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    @property
    def dataset_reference(self) -> DatasetManifestReference:
        return self.configuration.dataset_reference

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "owner_user_id": str(self.owner_user_id),
            "configuration": self.configuration.to_snapshot(),
            "train_dataset_path": self.train_dataset_path,
            "validation_dataset_path": self.validation_dataset_path,
            "output_directory": self.output_directory,
            "resume_checkpoint_path": self.resume_checkpoint_path,
            "package_lock_sha256": self.package_lock_sha256,
            "environment_sha256": self.environment_sha256,
            "requested_at": self.requested_at.isoformat(),
        }

    def process_payload(self) -> dict[str, object]:
        """Return only non-secret fields required by the training process."""
        return {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "configuration": self.configuration.to_snapshot(),
            "train_dataset_path": self.train_dataset_path,
            "validation_dataset_path": self.validation_dataset_path,
            "output_directory": self.output_directory,
            "resume_checkpoint_path": self.resume_checkpoint_path,
            "package_lock_sha256": self.package_lock_sha256,
            "environment_sha256": self.environment_sha256,
            "request_sha256": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class UnslothProcessInvocation:
    """Structured process invocation that never requires shell interpolation."""

    executable: str
    arguments: tuple[str, ...]
    working_directory: Path
    timeout_seconds: int
    allowed_environment_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = normalize_required_text(
            self.executable,
            label="training process executable",
            maximum_length=256,
        )
        if normalized != self.executable or any(
            character.isspace() for character in self.executable
        ):
            raise ValueError("training executable must be a normalized token")
        if not self.arguments or any(not argument for argument in self.arguments):
            raise ValueError("training process arguments must not be empty")
        validate_positive_integer(self.timeout_seconds, label="training process timeout")
        if self.allowed_environment_keys != tuple(sorted(set(self.allowed_environment_keys))):
            raise ValueError("allowed environment keys must be unique and canonical")


@dataclass(frozen=True, slots=True)
class UnslothProcessResult:
    """Observable process result before interpreting trainer output."""

    exit_code: int | None
    stdout: str
    stderr: str
    duration_milliseconds: int
    timed_out: bool
    interrupted: bool

    def __post_init__(self) -> None:
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("training process exit code must be an integer")
        if isinstance(self.duration_milliseconds, bool) or self.duration_milliseconds < 0:
            raise ValueError("training process duration must be non-negative")
        if self.timed_out and self.interrupted:
            raise ValueError("training process cannot be timed out and interrupted together")
        if (self.timed_out or self.interrupted) and self.exit_code is not None:
            raise ValueError("terminated training processes must not report an exit code")


class UnslothProcessPort(Protocol):
    """Least-privilege process boundary used by the training adapter."""

    async def run(self, invocation: UnslothProcessInvocation) -> UnslothProcessResult: ...


@dataclass(frozen=True, slots=True)
class QloraTrainingOutcome:
    """Canonical final training outcome suitable for persistence and audit."""

    run_id: UUID
    owner_user_id: UUID
    request_sha256: str
    configuration_sha256: str
    dataset_reference: DatasetManifestReference
    package_lock_sha256: str
    environment_sha256: str
    status: QloraTrainingStatus
    started_at: datetime
    completed_at: datetime
    duration_milliseconds: int
    peak_gpu_memory_mb: int | None
    metrics: tuple[TrainingMetricObservation, ...]
    checkpoints: tuple[TrainingCheckpointEvidence, ...]
    process_log_relative_path: str
    process_log_sha256: str
    adapter_relative_path: str | None
    adapter_sha256: str | None
    failure_kind: QloraTrainingFailureKind | None
    failure_message: str | None
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_sha256, "training request digest"),
            (self.configuration_sha256, "training configuration digest"),
            (self.package_lock_sha256, "training package lock digest"),
            (self.environment_sha256, "training environment digest"),
        ):
            validate_sha256(value, label=label)
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("training start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("training completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("training completion cannot precede its start")
        if isinstance(self.duration_milliseconds, bool) or self.duration_milliseconds < 0:
            raise ValueError("training duration must be non-negative")
        if self.peak_gpu_memory_mb is not None and (
            isinstance(self.peak_gpu_memory_mb, bool) or self.peak_gpu_memory_mb < 0
        ):
            raise ValueError("training peak GPU memory must be non-negative")
        if self.metrics != tuple(sorted(self.metrics, key=lambda item: item.sort_key)):
            raise ValueError("training metrics must use canonical order")
        if self.checkpoints != tuple(sorted(self.checkpoints, key=lambda item: item.sort_key)):
            raise ValueError("training checkpoints must use canonical order")
        _validate_relative_path(self.process_log_relative_path, label="training process log path")
        validate_sha256(self.process_log_sha256, label="training process log digest")
        succeeded = self.status is QloraTrainingStatus.SUCCEEDED
        if succeeded:
            if self.adapter_relative_path is None or self.adapter_sha256 is None:
                raise ValueError("successful training requires an adapter artifact")
            _validate_relative_path(self.adapter_relative_path, label="adapter output path")
            validate_sha256(self.adapter_sha256, label="adapter artifact digest")
            if self.failure_kind is not None or self.failure_message is not None:
                raise ValueError("successful training cannot contain failure details")
        else:
            if self.adapter_relative_path is not None or self.adapter_sha256 is not None:
                raise ValueError("failed training cannot expose an adapter artifact")
            if self.failure_kind is None or self.failure_message is None:
                raise ValueError("failed training requires typed failure details")
            normalized_failure = normalize_required_text(
                self.failure_message,
                label="training failure message",
                maximum_length=_MAX_MESSAGE_LENGTH,
            )
            if normalized_failure != self.failure_message:
                raise ValueError("training failure message must be normalized")
        validate_sha256(self.content_hash, label="training outcome content hash")
        if self.content_hash != qlora_training_outcome_hash(self):
            raise ValueError("training outcome content hash is inconsistent")

    def semantic_snapshot(self) -> dict[str, object]:
        return _training_outcome_semantic_snapshot(
            run_id=self.run_id,
            owner_user_id=self.owner_user_id,
            request_sha256=self.request_sha256,
            configuration_sha256=self.configuration_sha256,
            dataset_reference=self.dataset_reference,
            package_lock_sha256=self.package_lock_sha256,
            environment_sha256=self.environment_sha256,
            status=self.status,
            started_at=self.started_at,
            completed_at=self.completed_at,
            duration_milliseconds=self.duration_milliseconds,
            peak_gpu_memory_mb=self.peak_gpu_memory_mb,
            metrics=self.metrics,
            checkpoints=self.checkpoints,
            process_log_relative_path=self.process_log_relative_path,
            process_log_sha256=self.process_log_sha256,
            adapter_relative_path=self.adapter_relative_path,
            adapter_sha256=self.adapter_sha256,
            failure_kind=self.failure_kind,
            failure_message=self.failure_message,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


class AsyncioUnslothProcessAdapter:
    """Execute the repository-owned trainer without invoking a shell."""

    async def run(self, invocation: UnslothProcessInvocation) -> UnslothProcessResult:
        environment = {
            key: value
            for key in invocation.allowed_environment_keys
            if (value := os.environ.get(key)) is not None
        }
        process = await asyncio.create_subprocess_exec(
            invocation.executable,
            *invocation.arguments,
            cwd=invocation.working_directory,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        started = asyncio.get_running_loop().time()
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=invocation.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return UnslothProcessResult(
                exit_code=None,
                stdout="",
                stderr="Training process exceeded its configured timeout.",
                duration_milliseconds=_elapsed_milliseconds(started),
                timed_out=True,
                interrupted=False,
            )
        except asyncio.CancelledError:
            process.terminate()
            await process.wait()
            raise
        return UnslothProcessResult(
            exit_code=process.returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_milliseconds=_elapsed_milliseconds(started),
            timed_out=False,
            interrupted=False,
        )


class UnslothQloraTrainingAdapter:
    """Stage one request, invoke the isolated trainer, and validate its result."""

    def __init__(
        self,
        *,
        process_port: UnslothProcessPort,
        training_environment_directory: Path,
        input_artifact_root: Path,
        workspace_root: Path,
        timeout_seconds: int,
    ) -> None:
        validate_positive_integer(timeout_seconds, label="Unsloth training timeout")
        self._process_port = process_port
        self._environment_directory = Path(training_environment_directory)
        self._input_artifact_root = Path(input_artifact_root)
        self._workspace_root = Path(workspace_root)
        self._timeout_seconds = timeout_seconds

    async def train(self, request: UnslothTrainingRequest) -> QloraTrainingOutcome:
        self._validate_environment()
        run_directory = self._prepare_run_directory(request.run_id)
        self._stage_inputs(request, run_directory)
        request_path = run_directory / "request.json"
        result_path = run_directory / "result.json"
        request_path.write_text(canonical_json(request.process_payload()), encoding="utf-8")
        invocation = UnslothProcessInvocation(
            executable="uv",
            arguments=(
                "run",
                "--frozen",
                "--python",
                "3.13",
                "python",
                "run_qlora.py",
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ),
            working_directory=self._environment_directory,
            timeout_seconds=self._timeout_seconds,
            allowed_environment_keys=tuple(sorted(_ALLOWED_ENVIRONMENT_KEYS)),
        )
        process_result = await self._process_port.run(invocation)
        process_log_path, process_log_sha256 = _write_process_log(
            run_directory,
            process_result,
        )
        if process_result.timed_out:
            return _failed_outcome(
                request,
                status=QloraTrainingStatus.TIMED_OUT,
                kind=QloraTrainingFailureKind.TIMEOUT,
                message="The isolated Unsloth training process timed out.",
                duration_milliseconds=process_result.duration_milliseconds,
                process_log_relative_path=process_log_path,
                process_log_sha256=process_log_sha256,
            )
        if process_result.interrupted:
            return _failed_outcome(
                request,
                status=QloraTrainingStatus.INTERRUPTED,
                kind=QloraTrainingFailureKind.INTERRUPTED,
                message="The isolated Unsloth training process was interrupted.",
                duration_milliseconds=process_result.duration_milliseconds,
                process_log_relative_path=process_log_path,
                process_log_sha256=process_log_sha256,
            )
        if result_path.is_symlink():
            return _invalid_result_outcome(
                request,
                process_result.duration_milliseconds,
                process_log_relative_path=process_log_path,
                process_log_sha256=process_log_sha256,
            )
        if result_path.is_file():
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
                outcome = _outcome_from_payload(
                    request,
                    payload,
                    process_log_relative_path=process_log_path,
                    process_log_sha256=process_log_sha256,
                )
                _validate_process_outcome(process_result.exit_code, outcome)
                return outcome
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                return _invalid_result_outcome(
                    request,
                    process_result.duration_milliseconds,
                    process_log_relative_path=process_log_path,
                    process_log_sha256=process_log_sha256,
                )
        failure_kind = _failure_from_exit_code(process_result.exit_code)
        return _failed_outcome(
            request,
            status=(
                QloraTrainingStatus.INTERRUPTED
                if failure_kind is QloraTrainingFailureKind.INTERRUPTED
                else QloraTrainingStatus.FAILED
            ),
            kind=failure_kind,
            message=_process_failure_message(process_result, failure_kind),
            duration_milliseconds=process_result.duration_milliseconds,
            process_log_relative_path=process_log_path,
            process_log_sha256=process_log_sha256,
        )

    def _validate_environment(self) -> None:
        if self._environment_directory.is_symlink() or not self._environment_directory.is_dir():
            raise ValueError("training environment must be a regular directory")
        runner = self._environment_directory / "run_qlora.py"
        if runner.is_symlink() or not runner.is_file():
            raise ValueError("repository-owned Unsloth runner is missing")

    def _prepare_run_directory(self, run_id: UUID) -> Path:
        if self._workspace_root.is_symlink():
            raise ValueError("training workspace root must not be a symbolic link")
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        run_directory = self._workspace_root / str(run_id)
        if run_directory.exists() or run_directory.is_symlink():
            raise ValueError("training run workspace already exists")
        run_directory.mkdir()
        return run_directory

    def _stage_inputs(self, request: UnslothTrainingRequest, run_directory: Path) -> None:
        for relative_path in (
            request.train_dataset_path,
            request.validation_dataset_path,
        ):
            source = _safe_source_path(self._input_artifact_root, relative_path)
            if not source.is_file():
                raise ValueError("training dataset input must identify a regular file")
            if source.stat().st_size > _MAX_INPUT_FILE_BYTES:
                raise ValueError("training dataset input exceeds the configured size limit")
            destination = _destination_path(run_directory, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        if request.resume_checkpoint_path is not None:
            source = _safe_source_path(
                self._input_artifact_root,
                request.resume_checkpoint_path,
            )
            if not source.is_dir():
                raise ValueError("resume checkpoint input must identify a regular directory")
            destination = _destination_path(run_directory, request.resume_checkpoint_path)
            _copy_regular_tree(
                source,
                destination,
                maximum_bytes=_MAX_RESUME_CHECKPOINT_BYTES,
            )


def create_qlora_training_outcome(
    *,
    run_id: UUID,
    owner_user_id: UUID,
    request_sha256: str,
    configuration_sha256: str,
    dataset_reference: DatasetManifestReference,
    package_lock_sha256: str,
    environment_sha256: str,
    status: QloraTrainingStatus,
    started_at: datetime,
    completed_at: datetime,
    duration_milliseconds: int,
    peak_gpu_memory_mb: int | None,
    metrics: tuple[TrainingMetricObservation, ...],
    checkpoints: tuple[TrainingCheckpointEvidence, ...],
    process_log_relative_path: str,
    process_log_sha256: str,
    adapter_relative_path: str | None,
    adapter_sha256: str | None,
    failure_kind: QloraTrainingFailureKind | None,
    failure_message: str | None,
) -> QloraTrainingOutcome:
    """Create a canonically ordered content-addressed final training outcome."""
    ordered_metrics = tuple(sorted(metrics, key=lambda item: item.sort_key))
    ordered_checkpoints = tuple(sorted(checkpoints, key=lambda item: item.sort_key))
    semantic = _training_outcome_semantic_snapshot(
        run_id=run_id,
        owner_user_id=owner_user_id,
        request_sha256=request_sha256,
        configuration_sha256=configuration_sha256,
        dataset_reference=dataset_reference,
        package_lock_sha256=package_lock_sha256,
        environment_sha256=environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration_milliseconds,
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        metrics=ordered_metrics,
        checkpoints=ordered_checkpoints,
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=adapter_relative_path,
        adapter_sha256=adapter_sha256,
        failure_kind=failure_kind,
        failure_message=failure_message,
    )
    return QloraTrainingOutcome(
        run_id=run_id,
        owner_user_id=owner_user_id,
        request_sha256=request_sha256,
        configuration_sha256=configuration_sha256,
        dataset_reference=dataset_reference,
        package_lock_sha256=package_lock_sha256,
        environment_sha256=environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration_milliseconds,
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        metrics=ordered_metrics,
        checkpoints=ordered_checkpoints,
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=adapter_relative_path,
        adapter_sha256=adapter_sha256,
        failure_kind=failure_kind,
        failure_message=failure_message,
        content_hash=snapshot_content_hash(semantic),
    )


def qlora_training_outcome_hash(outcome: QloraTrainingOutcome) -> str:
    """Hash one complete final outcome independently from persistence metadata."""
    return snapshot_content_hash(outcome.semantic_snapshot())


def _outcome_from_payload(
    request: UnslothTrainingRequest,
    payload: object,
    *,
    process_log_relative_path: str,
    process_log_sha256: str,
) -> QloraTrainingOutcome:
    if not isinstance(payload, dict):
        raise ValueError("training result must be a JSON object")
    if payload.get("request_sha256") != request.content_hash:
        raise ValueError("training result request digest does not match")
    status = QloraTrainingStatus(_required_string(payload, "status"))
    started_at = datetime.fromisoformat(_required_string(payload, "started_at"))
    completed_at = datetime.fromisoformat(_required_string(payload, "completed_at"))
    metrics = _parse_metrics(payload.get("metrics", []))
    checkpoints = _parse_checkpoints(payload.get("checkpoints", []))
    duration = _non_negative_integer(payload, "duration_milliseconds")
    peak_memory = _optional_non_negative_integer(payload, "peak_gpu_memory_mb")
    adapter_path = _optional_string(payload, "adapter_relative_path")
    adapter_sha256 = _optional_string(payload, "adapter_sha256")
    failure_kind_value = _optional_string(payload, "failure_kind")
    failure_kind = (
        None if failure_kind_value is None else QloraTrainingFailureKind(failure_kind_value)
    )
    failure_message = _optional_string(payload, "failure_message")
    semantic = _training_outcome_semantic_snapshot(
        run_id=request.run_id,
        owner_user_id=request.owner_user_id,
        request_sha256=request.content_hash,
        configuration_sha256=request.configuration.content_hash,
        dataset_reference=request.dataset_reference,
        package_lock_sha256=request.package_lock_sha256,
        environment_sha256=request.environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration,
        peak_gpu_memory_mb=peak_memory,
        metrics=metrics,
        checkpoints=checkpoints,
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=adapter_path,
        adapter_sha256=adapter_sha256,
        failure_kind=failure_kind,
        failure_message=failure_message,
    )
    return QloraTrainingOutcome(
        run_id=request.run_id,
        owner_user_id=request.owner_user_id,
        request_sha256=request.content_hash,
        configuration_sha256=request.configuration.content_hash,
        dataset_reference=request.dataset_reference,
        package_lock_sha256=request.package_lock_sha256,
        environment_sha256=request.environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration,
        peak_gpu_memory_mb=peak_memory,
        metrics=metrics,
        checkpoints=checkpoints,
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=adapter_path,
        adapter_sha256=adapter_sha256,
        failure_kind=failure_kind,
        failure_message=failure_message,
        content_hash=snapshot_content_hash(semantic),
    )


def _failed_outcome(
    request: UnslothTrainingRequest,
    *,
    status: QloraTrainingStatus,
    kind: QloraTrainingFailureKind,
    message: str,
    duration_milliseconds: int,
    process_log_relative_path: str,
    process_log_sha256: str,
) -> QloraTrainingOutcome:
    normalized_message = " ".join(message.split())[:_MAX_MESSAGE_LENGTH]
    if not normalized_message:
        normalized_message = f"The Unsloth training process failed with {kind.value}."
    started_at = request.requested_at
    completed_at = started_at + timedelta(milliseconds=duration_milliseconds)
    semantic = _training_outcome_semantic_snapshot(
        run_id=request.run_id,
        owner_user_id=request.owner_user_id,
        request_sha256=request.content_hash,
        configuration_sha256=request.configuration.content_hash,
        dataset_reference=request.dataset_reference,
        package_lock_sha256=request.package_lock_sha256,
        environment_sha256=request.environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration_milliseconds,
        peak_gpu_memory_mb=None,
        metrics=(),
        checkpoints=(),
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=None,
        adapter_sha256=None,
        failure_kind=kind,
        failure_message=normalized_message,
    )
    return QloraTrainingOutcome(
        run_id=request.run_id,
        owner_user_id=request.owner_user_id,
        request_sha256=request.content_hash,
        configuration_sha256=request.configuration.content_hash,
        dataset_reference=request.dataset_reference,
        package_lock_sha256=request.package_lock_sha256,
        environment_sha256=request.environment_sha256,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_milliseconds=duration_milliseconds,
        peak_gpu_memory_mb=None,
        metrics=(),
        checkpoints=(),
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
        adapter_relative_path=None,
        adapter_sha256=None,
        failure_kind=kind,
        failure_message=normalized_message,
        content_hash=snapshot_content_hash(semantic),
    )


def _training_outcome_semantic_snapshot(
    *,
    run_id: UUID,
    owner_user_id: UUID,
    request_sha256: str,
    configuration_sha256: str,
    dataset_reference: DatasetManifestReference,
    package_lock_sha256: str,
    environment_sha256: str,
    status: QloraTrainingStatus,
    started_at: datetime,
    completed_at: datetime,
    duration_milliseconds: int,
    peak_gpu_memory_mb: int | None,
    metrics: tuple[TrainingMetricObservation, ...],
    checkpoints: tuple[TrainingCheckpointEvidence, ...],
    process_log_relative_path: str,
    process_log_sha256: str,
    adapter_relative_path: str | None,
    adapter_sha256: str | None,
    failure_kind: QloraTrainingFailureKind | None,
    failure_message: str | None,
) -> dict[str, object]:
    return {
        "run_id": str(run_id),
        "owner_user_id": str(owner_user_id),
        "request_sha256": request_sha256,
        "configuration_sha256": configuration_sha256,
        "dataset_reference": dataset_reference.to_snapshot(),
        "package_lock_sha256": package_lock_sha256,
        "environment_sha256": environment_sha256,
        "status": status.value,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_milliseconds": duration_milliseconds,
        "peak_gpu_memory_mb": peak_gpu_memory_mb,
        "metrics": [item.to_snapshot() for item in metrics],
        "checkpoints": [item.to_snapshot() for item in checkpoints],
        "process_log_relative_path": process_log_relative_path,
        "process_log_sha256": process_log_sha256,
        "adapter_relative_path": adapter_relative_path,
        "adapter_sha256": adapter_sha256,
        "failure_kind": None if failure_kind is None else failure_kind.value,
        "failure_message": failure_message,
    }


def _parse_metrics(value: object) -> tuple[TrainingMetricObservation, ...]:
    if not isinstance(value, list):
        raise ValueError("training metrics must be a list")
    metrics: list[TrainingMetricObservation] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("training metric must be an object")
        step = item.get("step")
        if step is not None and (isinstance(step, bool) or not isinstance(step, int)):
            raise ValueError("training metric step must be an integer")
        metric_value = item.get("value")
        if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            raise ValueError("training metric value must be numeric")
        metrics.append(
            TrainingMetricObservation(
                name=_required_string(item, "name"),
                value=float(metric_value),
                step=step,
            )
        )
    return tuple(sorted(metrics, key=lambda item: item.sort_key))


def _parse_checkpoints(value: object) -> tuple[TrainingCheckpointEvidence, ...]:
    if not isinstance(value, list):
        raise ValueError("training checkpoints must be a list")
    checkpoints: list[TrainingCheckpointEvidence] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("training checkpoint must be an object")
        checkpoints.append(
            TrainingCheckpointEvidence(
                step=_positive_integer(item, "step"),
                relative_path=_required_string(item, "relative_path"),
                content_sha256=_required_string(item, "content_sha256"),
            )
        )
    return tuple(sorted(checkpoints, key=lambda item: item.sort_key))


def _failure_from_exit_code(exit_code: int | None) -> QloraTrainingFailureKind:
    if exit_code is None:
        return QloraTrainingFailureKind.PROCESS_FAILED
    value = _EXIT_FAILURES.get(exit_code)
    if value is None:
        return QloraTrainingFailureKind.PROCESS_FAILED
    return QloraTrainingFailureKind(value)


def _process_failure_message(
    result: UnslothProcessResult,
    kind: QloraTrainingFailureKind,
) -> str:
    detail = " ".join(result.stderr.split())[:_MAX_MESSAGE_LENGTH]
    return detail or f"The Unsloth training process failed with {kind.value}."


def _validate_process_outcome(
    exit_code: int | None,
    outcome: QloraTrainingOutcome,
) -> None:
    if exit_code is None:
        raise ValueError("completed training process must expose an exit code")
    if outcome.status is QloraTrainingStatus.SUCCEEDED:
        if exit_code != 0:
            raise ValueError("successful training result requires process exit code zero")
        return
    if exit_code == 0:
        raise ValueError("failed training result cannot use process exit code zero")
    if outcome.status is QloraTrainingStatus.INTERRUPTED and exit_code != 24:
        raise ValueError("interrupted training result requires the interruption exit code")


def _invalid_result_outcome(
    request: UnslothTrainingRequest,
    duration_milliseconds: int,
    *,
    process_log_relative_path: str,
    process_log_sha256: str,
) -> QloraTrainingOutcome:
    return _failed_outcome(
        request,
        status=QloraTrainingStatus.FAILED,
        kind=QloraTrainingFailureKind.INVALID_RESULT,
        message="The Unsloth trainer produced an invalid result artifact.",
        duration_milliseconds=duration_milliseconds,
        process_log_relative_path=process_log_relative_path,
        process_log_sha256=process_log_sha256,
    )


def _write_process_log(
    run_directory: Path,
    result: UnslothProcessResult,
) -> tuple[str, str]:
    payload = {
        "exit_code": result.exit_code,
        "stdout": _bounded_process_text(result.stdout),
        "stderr": _bounded_process_text(result.stderr),
        "duration_milliseconds": result.duration_milliseconds,
        "timed_out": result.timed_out,
        "interrupted": result.interrupted,
    }
    content = canonical_json(payload)
    path = run_directory / "process-log.json"
    path.write_text(content, encoding="utf-8")
    return path.relative_to(run_directory).as_posix(), snapshot_content_hash(payload)


def _bounded_process_text(value: str) -> str:
    bounded = value[:_MAX_PROCESS_LOG_TEXT_LENGTH]
    token = os.environ.get("HF_TOKEN")
    if token:
        bounded = bounded.replace(token, "[REDACTED]")
    return bounded


def _validate_relative_path(value: str, *, label: str) -> None:
    normalized = normalize_required_text(
        value,
        label=label,
        maximum_length=_MAX_REFERENCE_LENGTH,
    )
    if normalized != value or "\\" in value:
        raise ValueError(f"{label} must be a normalized POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must remain relative and traversal-free")


def _safe_source_path(root: Path, relative_path: str) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("training input artifact root must be a regular directory")
    current = root
    for part in PurePosixPath(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("training input artifacts cannot contain symbolic links")
    root_resolved = root.resolve()
    resolved = current.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("training input artifact escapes its configured root")
    return resolved


def _destination_path(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    destination = root.joinpath(*PurePosixPath(relative_path).parts).resolve()
    if destination != resolved_root and resolved_root not in destination.parents:
        raise ValueError("staged training path escapes its run workspace")
    return destination


def _copy_regular_tree(source: Path, destination: Path, *, maximum_bytes: int) -> None:
    total_bytes = 0
    paths = sorted(source.rglob("*"), key=lambda item: item.as_posix())
    for path in paths:
        if path.is_symlink():
            raise ValueError("resume checkpoint cannot contain symbolic links")
        if path.is_file():
            total_bytes += path.stat().st_size
            if total_bytes > maximum_bytes:
                raise ValueError("resume checkpoint exceeds the configured size limit")
    destination.mkdir(parents=True, exist_ok=False)
    for path in paths:
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def _required_string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"training result {key} must be a string")
    return value


def _optional_string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"training result {key} must be a string or null")
    return value


def _positive_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"training result {key} must be a positive integer")
    return value


def _non_negative_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"training result {key} must be a non-negative integer")
    return value


def _optional_non_negative_integer(values: dict[str, object], key: str) -> int | None:
    value = values.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"training result {key} must be a non-negative integer or null")
    return value


def _elapsed_milliseconds(started: float) -> int:
    return max(0, round((asyncio.get_running_loop().time() - started) * 1_000))
