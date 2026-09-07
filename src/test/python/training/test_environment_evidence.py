"""Tests for model-spike environment, resource, and adapter evidence."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.training.environment_evidence import (
    AdapterExportLoadEvidence,
    InferenceMeasurementStatus,
    TrainingEnvironmentObservation,
    TrainingEnvironmentObservationStatus,
    TrainingEnvironmentProbeId,
    capture_training_environment,
    create_adapter_export_load_evidence,
    create_inference_resource_measurement,
    summarize_inference_resources,
)

CAPTURED_AT = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
CANDIDATE_ID = "model-candidate-small-instruct"


@dataclass
class _FakeProbe:
    missing: TrainingEnvironmentProbeId | None = None

    async def observe(
        self,
        probe_id: TrainingEnvironmentProbeId,
    ) -> TrainingEnvironmentObservation:
        if probe_id is self.missing:
            return TrainingEnvironmentObservation(
                probe_id=probe_id,
                status=TrainingEnvironmentObservationStatus.NOT_AVAILABLE,
                value=None,
                source=f"fixture:{probe_id.value}",
                detail="The fixture deliberately omitted this value.",
            )
        value = {
            TrainingEnvironmentProbeId.OPERATING_SYSTEM: "Linux-WSL2",
            TrainingEnvironmentProbeId.WSL_DISTRIBUTION: "Ubuntu-24.04",
            TrainingEnvironmentProbeId.PYTHON_VERSION: "3.13.7",
            TrainingEnvironmentProbeId.NVIDIA_DRIVER_VERSION: "580.97",
            TrainingEnvironmentProbeId.CUDA_VISIBLE_VERSION: "13.0",
            TrainingEnvironmentProbeId.GPU_NAME: "NVIDIA GeForce RTX 4060",
            TrainingEnvironmentProbeId.GPU_MEMORY_MB: "8188",
            TrainingEnvironmentProbeId.TORCH_VERSION: "2.8.0",
        }[probe_id]
        return TrainingEnvironmentObservation(
            probe_id=probe_id,
            status=TrainingEnvironmentObservationStatus.OBSERVED,
            value=value,
            source=f"fixture:{probe_id.value}",
        )


def test_capture_records_all_required_values_and_package_lock() -> None:
    snapshot = asyncio.run(
        capture_training_environment(
            capture_id=UUID("00000000-0000-4000-8000-000000118001"),
            probe=_FakeProbe(),
            package_lock_sha256="a" * 64,
            captured_at=CAPTURED_AT,
        )
    )

    assert snapshot.complete is True
    assert snapshot.gpu_memory_mb == 8188
    assert len(snapshot.observations) == len(TrainingEnvironmentProbeId)
    assert snapshot.package_lock_sha256 == "a" * 64
    assert len(snapshot.content_hash) == 64


def test_missing_probe_stays_explicit_and_prevents_complete_evidence() -> None:
    snapshot = asyncio.run(
        capture_training_environment(
            capture_id=UUID("00000000-0000-4000-8000-000000118002"),
            probe=_FakeProbe(missing=TrainingEnvironmentProbeId.GPU_MEMORY_MB),
            package_lock_sha256="b" * 64,
            captured_at=CAPTURED_AT,
        )
    )

    assert snapshot.complete is False
    assert snapshot.gpu_memory_mb is None
    observation = snapshot.observation(TrainingEnvironmentProbeId.GPU_MEMORY_MB)
    assert observation.status is TrainingEnvironmentObservationStatus.NOT_AVAILABLE
    assert observation.detail is not None


def test_observation_rejects_fabricated_value_status_combinations() -> None:
    with pytest.raises(ValueError, match="must match its status"):
        TrainingEnvironmentObservation(
            probe_id=TrainingEnvironmentProbeId.CUDA_VISIBLE_VERSION,
            status=TrainingEnvironmentObservationStatus.NOT_AVAILABLE,
            value="13.0",
            source="fixture:cuda",
            detail="The value should not be present.",
        )


def _measurement(number: int, *, status: InferenceMeasurementStatus):
    succeeded = status is InferenceMeasurementStatus.SUCCEEDED
    return create_inference_resource_measurement(
        measurement_id=UUID(f"00000000-0000-4000-8000-{number:012d}"),
        candidate_id=CANDIDATE_ID,
        task_id=f"bench-en-{number:03d}",
        repetition=1,
        status=status,
        latency_milliseconds=100 + number if succeeded else None,
        peak_gpu_memory_mb=4_000 + number if succeeded else None,
        input_tokens=100 if succeeded else None,
        output_tokens=30 if succeeded else None,
        failure_summary=None if succeeded else "The local runtime timed out.",
        evidence_reference=f"artifact:inference-{number}",
        observed_at=CAPTURED_AT,
    )


def test_resource_summary_preserves_failures_and_observed_peak() -> None:
    measurements = (
        _measurement(1, status=InferenceMeasurementStatus.SUCCEEDED),
        _measurement(2, status=InferenceMeasurementStatus.SUCCEEDED),
    )
    complete = summarize_inference_resources(
        candidate_id=CANDIDATE_ID,
        measurements=measurements,
    )
    incomplete = summarize_inference_resources(
        candidate_id=CANDIDATE_ID,
        measurements=(*measurements, _measurement(3, status=InferenceMeasurementStatus.FAILED)),
    )

    assert complete.complete is True
    assert complete.mean_latency_milliseconds == 101.5
    assert complete.peak_gpu_memory_mb == 4002
    assert incomplete.complete is False
    assert incomplete.successful_count == 2


def test_adapter_evidence_requires_export_before_load_and_reports_pass_state() -> None:
    passed = create_adapter_export_load_evidence(
        candidate_id=CANDIDATE_ID,
        smoke_training_succeeded=True,
        adapter_exported=True,
        adapter_loaded=True,
        structured_output_valid=True,
        adapter_artifact_sha256="c" * 64,
        evidence_references=("artifact:adapter-smoke", "report:schema-validation"),
        observed_at=CAPTURED_AT,
    )

    assert passed.passed is True
    with pytest.raises(ValueError, match="cannot load before"):
        replace(
            passed,
            adapter_exported=False,
            adapter_artifact_sha256=None,
        )
    with pytest.raises(ValueError, match="content hash is inconsistent"):
        AdapterExportLoadEvidence(
            candidate_id=CANDIDATE_ID,
            smoke_training_succeeded=True,
            adapter_exported=True,
            adapter_loaded=True,
            structured_output_valid=True,
            adapter_artifact_sha256="d" * 64,
            evidence_references=("artifact:adapter-smoke",),
            observed_at=CAPTURED_AT,
            content_hash="e" * 64,
        )
