"""Typed environment, resource, and adapter evidence for the model feasibility spike."""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

ENVIRONMENT_EVIDENCE_SCHEMA_VERSION: Final = 1
_MAX_VALUE_LENGTH: Final = 2_000
_MAX_REFERENCE_LENGTH: Final = 512
_PROBE_TIMEOUT_SECONDS: Final = 10


class TrainingEnvironmentProbeId(StrEnum):
    """Stable observations required to interpret local inference and QLoRA evidence."""

    OPERATING_SYSTEM = "operating_system"
    WSL_DISTRIBUTION = "wsl_distribution"
    PYTHON_VERSION = "python_version"
    NVIDIA_DRIVER_VERSION = "nvidia_driver_version"
    CUDA_VISIBLE_VERSION = "cuda_visible_version"
    GPU_NAME = "gpu_name"
    GPU_MEMORY_MB = "gpu_memory_mb"
    TORCH_VERSION = "torch_version"


class TrainingEnvironmentObservationStatus(StrEnum):
    """Explicit observation outcomes that prevent fabricated environment values."""

    OBSERVED = "OBSERVED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    COMMAND_FAILED = "COMMAND_FAILED"


@dataclass(frozen=True, slots=True)
class TrainingEnvironmentObservation:
    """One environment value or an explicit reason why it was not observed."""

    probe_id: TrainingEnvironmentProbeId
    status: TrainingEnvironmentObservationStatus
    value: str | None
    source: str
    detail: str | None = None

    def __post_init__(self) -> None:
        normalized_value = normalize_optional_text(
            self.value,
            label="training environment observation value",
            maximum_length=_MAX_VALUE_LENGTH,
        )
        normalized_detail = normalize_optional_text(
            self.detail,
            label="training environment observation detail",
            maximum_length=_MAX_VALUE_LENGTH,
        )
        if normalized_value != self.value or normalized_detail != self.detail:
            raise ValueError("training environment observation text must be normalized")
        if (
            normalize_required_text(
                self.source,
                label="training environment observation source",
                maximum_length=_MAX_REFERENCE_LENGTH,
            )
            != self.source
        ):
            raise ValueError("training environment observation source must be normalized")
        observed = self.status is TrainingEnvironmentObservationStatus.OBSERVED
        if observed != (self.value is not None):
            raise ValueError("environment observation value must match its status")
        if observed and self.detail is not None:
            raise ValueError("successful environment observations cannot contain failure detail")
        if not observed and self.detail is None:
            raise ValueError("unavailable environment observations require a detail")
        if self.probe_id is TrainingEnvironmentProbeId.GPU_MEMORY_MB and observed:
            _positive_integer_text(self.value or "", label="GPU memory")

    @property
    def sort_key(self) -> str:
        return self.probe_id.value

    def to_snapshot(self) -> dict[str, object]:
        return {
            "probe_id": self.probe_id.value,
            "status": self.status.value,
            "value": self.value,
            "source": self.source,
            "detail": self.detail,
        }


class TrainingEnvironmentProbePort(Protocol):
    """Side-effect boundary for a fixed set of environment observations."""

    async def observe(
        self,
        probe_id: TrainingEnvironmentProbeId,
    ) -> TrainingEnvironmentObservation: ...


@dataclass(frozen=True, slots=True)
class TrainingEnvironmentSnapshot:
    """Content-addressed environment evidence bound to one package lock."""

    capture_id: UUID
    observations: tuple[TrainingEnvironmentObservation, ...]
    package_lock_sha256: str
    captured_at: datetime
    complete: bool
    content_hash: str
    schema_version: int = ENVIRONMENT_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENVIRONMENT_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("unsupported training environment evidence schema version")
        expected_order = tuple(sorted(self.observations, key=lambda item: item.sort_key))
        if self.observations != expected_order:
            raise ValueError("training environment observations must use canonical order")
        if {item.probe_id for item in self.observations} != set(TrainingEnvironmentProbeId):
            raise ValueError("training environment snapshot must include every required probe")
        validate_sha256(self.package_lock_sha256, label="training package lock digest")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("training environment capture timestamp must be timezone-aware")
        expected_complete = all(
            item.status is TrainingEnvironmentObservationStatus.OBSERVED
            for item in self.observations
        )
        if self.complete != expected_complete:
            raise ValueError("training environment completeness is inconsistent")
        validate_sha256(self.content_hash, label="training environment content hash")
        if self.content_hash != _environment_snapshot_hash(
            capture_id=self.capture_id,
            observations=self.observations,
            package_lock_sha256=self.package_lock_sha256,
            captured_at=self.captured_at,
            complete=self.complete,
            schema_version=self.schema_version,
        ):
            raise ValueError("training environment content hash is inconsistent")

    def observation(
        self,
        probe_id: TrainingEnvironmentProbeId,
    ) -> TrainingEnvironmentObservation:
        return next(item for item in self.observations if item.probe_id is probe_id)

    @property
    def gpu_memory_mb(self) -> int | None:
        observation = self.observation(TrainingEnvironmentProbeId.GPU_MEMORY_MB)
        return None if observation.value is None else int(observation.value)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capture_id": str(self.capture_id),
            "observations": [item.to_snapshot() for item in self.observations],
            "package_lock_sha256": self.package_lock_sha256,
            "captured_at": self.captured_at.isoformat(),
            "complete": self.complete,
            "content_hash": self.content_hash,
        }


class InferenceMeasurementStatus(StrEnum):
    """Observed outcome of one exact inference repetition."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, slots=True)
class InferenceResourceMeasurement:
    """One observable inference repetition without inferred resource values."""

    measurement_id: UUID
    candidate_id: str
    task_id: str
    repetition: int
    status: InferenceMeasurementStatus
    latency_milliseconds: int | None
    peak_gpu_memory_mb: int | None
    input_tokens: int | None
    output_tokens: int | None
    failure_summary: str | None
    evidence_reference: str
    observed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.candidate_id, "inference candidate ID"),
            (self.task_id, "inference task ID"),
            (self.evidence_reference, "inference evidence reference"),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=_MAX_REFERENCE_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")
        validate_positive_integer(self.repetition, label="inference repetition")
        succeeded = self.status is InferenceMeasurementStatus.SUCCEEDED
        observed_values = (
            self.latency_milliseconds,
            self.peak_gpu_memory_mb,
            self.input_tokens,
            self.output_tokens,
        )
        if succeeded != all(value is not None for value in observed_values):
            raise ValueError("inference measurement values must match successful status")
        if succeeded != (self.failure_summary is None):
            raise ValueError("inference failure summary must match measurement status")
        for value, label in zip(
            observed_values,
            ("latency", "peak GPU memory", "input tokens", "output tokens"),
            strict=True,
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"inference {label} must be a non-negative integer")
        normalized_failure = normalize_optional_text(
            self.failure_summary,
            label="inference failure summary",
            maximum_length=_MAX_VALUE_LENGTH,
        )
        if normalized_failure != self.failure_summary:
            raise ValueError("inference failure summary must be normalized")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("inference observation timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="inference measurement content hash")
        if self.content_hash != _inference_measurement_hash(
            measurement_id=self.measurement_id,
            candidate_id=self.candidate_id,
            task_id=self.task_id,
            repetition=self.repetition,
            status=self.status,
            latency_milliseconds=self.latency_milliseconds,
            peak_gpu_memory_mb=self.peak_gpu_memory_mb,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            failure_summary=self.failure_summary,
            evidence_reference=self.evidence_reference,
            observed_at=self.observed_at,
        ):
            raise ValueError("inference measurement content hash is inconsistent")

    @property
    def sort_key(self) -> tuple[str, str, int]:
        return (self.candidate_id, self.task_id, self.repetition)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "measurement_id": str(self.measurement_id),
            "candidate_id": self.candidate_id,
            "task_id": self.task_id,
            "repetition": self.repetition,
            "status": self.status.value,
            "latency_milliseconds": self.latency_milliseconds,
            "peak_gpu_memory_mb": self.peak_gpu_memory_mb,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failure_summary": self.failure_summary,
            "evidence_reference": self.evidence_reference,
            "observed_at": self.observed_at.isoformat(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class InferenceResourceSummary:
    """Deterministic aggregate of exact repetitions for one candidate."""

    candidate_id: str
    measurement_count: int
    successful_count: int
    mean_latency_milliseconds: float | None
    peak_gpu_memory_mb: int | None
    complete: bool

    def __post_init__(self) -> None:
        if self.measurement_count < 0 or not 0 <= self.successful_count <= self.measurement_count:
            raise ValueError("inference resource summary counts are inconsistent")
        has_success = self.successful_count > 0
        if has_success != (self.mean_latency_milliseconds is not None):
            raise ValueError("mean latency must exist exactly when measurements succeeded")
        if has_success != (self.peak_gpu_memory_mb is not None):
            raise ValueError("peak GPU memory must exist exactly when measurements succeeded")
        if self.complete != (
            self.measurement_count > 0 and self.successful_count == self.measurement_count
        ):
            raise ValueError("inference resource completeness is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "measurement_count": self.measurement_count,
            "successful_count": self.successful_count,
            "mean_latency_milliseconds": self.mean_latency_milliseconds,
            "peak_gpu_memory_mb": self.peak_gpu_memory_mb,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class AdapterExportLoadEvidence:
    """Observed smoke-training, export, reload, and schema-validation evidence."""

    candidate_id: str
    smoke_training_succeeded: bool
    adapter_exported: bool
    adapter_loaded: bool
    structured_output_valid: bool
    adapter_artifact_sha256: str | None
    evidence_references: tuple[str, ...]
    observed_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if (
            normalize_required_text(
                self.candidate_id,
                label="adapter evidence candidate ID",
                maximum_length=_MAX_REFERENCE_LENGTH,
            )
            != self.candidate_id
        ):
            raise ValueError("adapter evidence candidate ID must be normalized")
        normalized_refs = normalize_text_items(
            self.evidence_references,
            label="adapter evidence references",
            maximum_item_length=_MAX_REFERENCE_LENGTH,
            require_items=True,
        )
        if self.evidence_references != tuple(sorted(normalized_refs)):
            raise ValueError("adapter evidence references must use canonical order")
        if self.adapter_artifact_sha256 is not None:
            validate_sha256(self.adapter_artifact_sha256, label="adapter artifact digest")
        if self.adapter_exported != (self.adapter_artifact_sha256 is not None):
            raise ValueError("adapter export state must match its artifact digest")
        if self.adapter_loaded and not self.adapter_exported:
            raise ValueError("an adapter cannot load before it is exported")
        if self.structured_output_valid and not self.adapter_loaded:
            raise ValueError("adapter output cannot be valid before the adapter loads")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("adapter evidence timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="adapter evidence content hash")
        if self.content_hash != _adapter_evidence_hash(
            candidate_id=self.candidate_id,
            smoke_training_succeeded=self.smoke_training_succeeded,
            adapter_exported=self.adapter_exported,
            adapter_loaded=self.adapter_loaded,
            structured_output_valid=self.structured_output_valid,
            adapter_artifact_sha256=self.adapter_artifact_sha256,
            evidence_references=self.evidence_references,
            observed_at=self.observed_at,
        ):
            raise ValueError("adapter evidence content hash is inconsistent")

    @property
    def passed(self) -> bool:
        return all(
            (
                self.smoke_training_succeeded,
                self.adapter_exported,
                self.adapter_loaded,
                self.structured_output_valid,
            )
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "smoke_training_succeeded": self.smoke_training_succeeded,
            "adapter_exported": self.adapter_exported,
            "adapter_loaded": self.adapter_loaded,
            "structured_output_valid": self.structured_output_valid,
            "adapter_artifact_sha256": self.adapter_artifact_sha256,
            "evidence_references": list(self.evidence_references),
            "observed_at": self.observed_at.isoformat(),
            "content_hash": self.content_hash,
        }


async def capture_training_environment(
    *,
    capture_id: UUID,
    probe: TrainingEnvironmentProbePort,
    package_lock_sha256: str,
    captured_at: datetime,
) -> TrainingEnvironmentSnapshot:
    """Capture every required probe and preserve unavailable values explicitly."""
    observations = tuple(
        sorted(
            [await probe.observe(probe_id) for probe_id in TrainingEnvironmentProbeId],
            key=lambda item: item.sort_key,
        )
    )
    complete = all(
        item.status is TrainingEnvironmentObservationStatus.OBSERVED for item in observations
    )
    content_hash = _environment_snapshot_hash(
        capture_id=capture_id,
        observations=observations,
        package_lock_sha256=package_lock_sha256,
        captured_at=captured_at,
        complete=complete,
        schema_version=ENVIRONMENT_EVIDENCE_SCHEMA_VERSION,
    )
    return TrainingEnvironmentSnapshot(
        capture_id=capture_id,
        observations=observations,
        package_lock_sha256=package_lock_sha256,
        captured_at=captured_at,
        complete=complete,
        content_hash=content_hash,
    )


def create_inference_resource_measurement(
    *,
    measurement_id: UUID,
    candidate_id: str,
    task_id: str,
    repetition: int,
    status: InferenceMeasurementStatus,
    latency_milliseconds: int | None,
    peak_gpu_memory_mb: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    failure_summary: str | None,
    evidence_reference: str,
    observed_at: datetime,
) -> InferenceResourceMeasurement:
    content_hash = _inference_measurement_hash(
        measurement_id=measurement_id,
        candidate_id=candidate_id,
        task_id=task_id,
        repetition=repetition,
        status=status,
        latency_milliseconds=latency_milliseconds,
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        failure_summary=failure_summary,
        evidence_reference=evidence_reference,
        observed_at=observed_at,
    )
    return InferenceResourceMeasurement(
        measurement_id=measurement_id,
        candidate_id=candidate_id,
        task_id=task_id,
        repetition=repetition,
        status=status,
        latency_milliseconds=latency_milliseconds,
        peak_gpu_memory_mb=peak_gpu_memory_mb,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        failure_summary=failure_summary,
        evidence_reference=evidence_reference,
        observed_at=observed_at,
        content_hash=content_hash,
    )


def summarize_inference_resources(
    *,
    candidate_id: str,
    measurements: tuple[InferenceResourceMeasurement, ...],
) -> InferenceResourceSummary:
    selected = tuple(item for item in measurements if item.candidate_id == candidate_id)
    successful = tuple(
        item for item in selected if item.status is InferenceMeasurementStatus.SUCCEEDED
    )
    return InferenceResourceSummary(
        candidate_id=candidate_id,
        measurement_count=len(selected),
        successful_count=len(successful),
        mean_latency_milliseconds=(
            None
            if not successful
            else sum(item.latency_milliseconds or 0 for item in successful) / len(successful)
        ),
        peak_gpu_memory_mb=(
            None if not successful else max(item.peak_gpu_memory_mb or 0 for item in successful)
        ),
        complete=bool(selected) and len(successful) == len(selected),
    )


def create_adapter_export_load_evidence(
    *,
    candidate_id: str,
    smoke_training_succeeded: bool,
    adapter_exported: bool,
    adapter_loaded: bool,
    structured_output_valid: bool,
    adapter_artifact_sha256: str | None,
    evidence_references: tuple[str, ...],
    observed_at: datetime,
) -> AdapterExportLoadEvidence:
    canonical_refs = tuple(sorted(set(evidence_references)))
    content_hash = _adapter_evidence_hash(
        candidate_id=candidate_id,
        smoke_training_succeeded=smoke_training_succeeded,
        adapter_exported=adapter_exported,
        adapter_loaded=adapter_loaded,
        structured_output_valid=structured_output_valid,
        adapter_artifact_sha256=adapter_artifact_sha256,
        evidence_references=canonical_refs,
        observed_at=observed_at,
    )
    return AdapterExportLoadEvidence(
        candidate_id=candidate_id,
        smoke_training_succeeded=smoke_training_succeeded,
        adapter_exported=adapter_exported,
        adapter_loaded=adapter_loaded,
        structured_output_valid=structured_output_valid,
        adapter_artifact_sha256=adapter_artifact_sha256,
        evidence_references=canonical_refs,
        observed_at=observed_at,
        content_hash=content_hash,
    )


class LocalTrainingEnvironmentProbe:
    """Fixed-command local probe suitable for WSL2 evidence capture, never shell input."""

    async def observe(
        self,
        probe_id: TrainingEnvironmentProbeId,
    ) -> TrainingEnvironmentObservation:
        if probe_id is TrainingEnvironmentProbeId.OPERATING_SYSTEM:
            return _observed(probe_id, platform.platform(), source="python:platform.platform")
        if probe_id is TrainingEnvironmentProbeId.PYTHON_VERSION:
            version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            return _observed(probe_id, version, source="python:sys.version_info")
        if probe_id is TrainingEnvironmentProbeId.WSL_DISTRIBUTION:
            distribution = os.environ.get("WSL_DISTRO_NAME")
            if distribution:
                return _observed(probe_id, distribution, source="env:WSL_DISTRO_NAME")
            return _unavailable(probe_id, source="env:WSL_DISTRO_NAME", detail="Not in WSL")
        if probe_id is TrainingEnvironmentProbeId.TORCH_VERSION:
            try:
                version = importlib.metadata.version("torch")
            except importlib.metadata.PackageNotFoundError:
                return _unavailable(
                    probe_id,
                    source="python:importlib.metadata",
                    detail="torch is not installed",
                )
            return _observed(probe_id, version, source="python:importlib.metadata")
        query = {
            TrainingEnvironmentProbeId.NVIDIA_DRIVER_VERSION: "driver_version",
            TrainingEnvironmentProbeId.CUDA_VISIBLE_VERSION: "cuda_version",
            TrainingEnvironmentProbeId.GPU_NAME: "name",
            TrainingEnvironmentProbeId.GPU_MEMORY_MB: "memory.total",
        }[probe_id]
        return await asyncio.to_thread(_observe_nvidia_smi, probe_id, query)


def _observe_nvidia_smi(
    probe_id: TrainingEnvironmentProbeId,
    query: str,
) -> TrainingEnvironmentObservation:
    command = (
        "nvidia-smi",
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    )
    source = "command:" + " ".join(command)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return _unavailable(probe_id, source=source, detail="nvidia-smi not found")
    except subprocess.TimeoutExpired:
        return _failed(probe_id, source=source, detail="nvidia-smi timed out")
    except OSError:
        return _failed(probe_id, source=source, detail="nvidia-smi could not start")
    if result.returncode != 0:
        return _failed(
            probe_id,
            source=source,
            detail=f"nvidia-smi exited with code {result.returncode}",
        )
    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not first_line:
        return _failed(probe_id, source=source, detail="nvidia-smi returned no value")
    if probe_id is TrainingEnvironmentProbeId.GPU_MEMORY_MB:
        first_line = str(int(float(first_line)))
    return _observed(probe_id, first_line, source=source)


def _observed(
    probe_id: TrainingEnvironmentProbeId,
    value: str,
    *,
    source: str,
) -> TrainingEnvironmentObservation:
    return TrainingEnvironmentObservation(
        probe_id=probe_id,
        status=TrainingEnvironmentObservationStatus.OBSERVED,
        value=value.strip(),
        source=source,
    )


def _unavailable(
    probe_id: TrainingEnvironmentProbeId,
    *,
    source: str,
    detail: str,
) -> TrainingEnvironmentObservation:
    return TrainingEnvironmentObservation(
        probe_id=probe_id,
        status=TrainingEnvironmentObservationStatus.NOT_AVAILABLE,
        value=None,
        source=source,
        detail=detail,
    )


def _failed(
    probe_id: TrainingEnvironmentProbeId,
    *,
    source: str,
    detail: str,
) -> TrainingEnvironmentObservation:
    return TrainingEnvironmentObservation(
        probe_id=probe_id,
        status=TrainingEnvironmentObservationStatus.COMMAND_FAILED,
        value=None,
        source=source,
        detail=detail,
    )


def _environment_snapshot_hash(
    *,
    capture_id: UUID,
    observations: tuple[TrainingEnvironmentObservation, ...],
    package_lock_sha256: str,
    captured_at: datetime,
    complete: bool,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "capture_id": str(capture_id),
            "observations": [item.to_snapshot() for item in observations],
            "package_lock_sha256": package_lock_sha256,
            "captured_at": captured_at.isoformat(),
            "complete": complete,
        }
    )


def _inference_measurement_hash(
    *,
    measurement_id: UUID,
    candidate_id: str,
    task_id: str,
    repetition: int,
    status: InferenceMeasurementStatus,
    latency_milliseconds: int | None,
    peak_gpu_memory_mb: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    failure_summary: str | None,
    evidence_reference: str,
    observed_at: datetime,
) -> str:
    return snapshot_content_hash(
        {
            "measurement_id": str(measurement_id),
            "candidate_id": candidate_id,
            "task_id": task_id,
            "repetition": repetition,
            "status": status.value,
            "latency_milliseconds": latency_milliseconds,
            "peak_gpu_memory_mb": peak_gpu_memory_mb,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "failure_summary": failure_summary,
            "evidence_reference": evidence_reference,
            "observed_at": observed_at.isoformat(),
        }
    )


def _adapter_evidence_hash(
    *,
    candidate_id: str,
    smoke_training_succeeded: bool,
    adapter_exported: bool,
    adapter_loaded: bool,
    structured_output_valid: bool,
    adapter_artifact_sha256: str | None,
    evidence_references: tuple[str, ...],
    observed_at: datetime,
) -> str:
    return snapshot_content_hash(
        {
            "candidate_id": candidate_id,
            "smoke_training_succeeded": smoke_training_succeeded,
            "adapter_exported": adapter_exported,
            "adapter_loaded": adapter_loaded,
            "structured_output_valid": structured_output_valid,
            "adapter_artifact_sha256": adapter_artifact_sha256,
            "evidence_references": list(evidence_references),
            "observed_at": observed_at.isoformat(),
        }
    )


def _positive_integer_text(value: str, *, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an integer") from error
    validate_positive_integer(parsed, label=label)
    return parsed
