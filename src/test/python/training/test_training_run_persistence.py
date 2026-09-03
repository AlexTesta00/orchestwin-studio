"""Tests for owner-scoped append-only QLoRA training run persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.training_run_persistence import (
    InMemoryTrainingRunRepository,
    TrainingRunStoreStatus,
    stored_training_run,
    training_checkpoint_to_record,
    training_run_to_record,
)
from orchestwin.training.unsloth_adapter import (
    QloraTrainingStatus,
    TrainingCheckpointEvidence,
    TrainingMetricObservation,
    create_qlora_training_outcome,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000124001")
RUN_ID = UUID("00000000-0000-4000-8000-000000124002")
DATASET_REFERENCE = DatasetManifestReference(
    dataset_id=UUID("00000000-0000-4000-8000-000000124003"),
    version_number=4,
    content_hash="a" * 64,
)
STARTED_AT = datetime(2026, 10, 16, 11, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 10, 16, 11, 5, tzinfo=UTC)


def _outcome(*, request_sha256: str = "b" * 64):
    return create_qlora_training_outcome(
        run_id=RUN_ID,
        owner_user_id=OWNER_ID,
        request_sha256=request_sha256,
        configuration_sha256="c" * 64,
        dataset_reference=DATASET_REFERENCE,
        package_lock_sha256="d" * 64,
        environment_sha256="e" * 64,
        status=QloraTrainingStatus.SUCCEEDED,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        duration_milliseconds=300_000,
        peak_gpu_memory_mb=6_610,
        metrics=(
            TrainingMetricObservation(name="train_loss", value=0.34, step=20),
            TrainingMetricObservation(name="eval_loss", value=0.39, step=20),
        ),
        checkpoints=(
            TrainingCheckpointEvidence(
                step=20,
                relative_path="outputs/checkpoint-20",
                content_sha256="f" * 64,
            ),
        ),
        process_log_relative_path="process-log.json",
        process_log_sha256="1" * 64,
        adapter_relative_path="outputs/adapter",
        adapter_sha256="2" * 64,
        failure_kind=None,
        failure_message=None,
    )


def _repository(*, owner_user_id: UUID = OWNER_ID, has_dataset: bool = True):
    references = (
        frozenset(
            {
                (
                    DATASET_REFERENCE.dataset_id,
                    DATASET_REFERENCE.version_number,
                    DATASET_REFERENCE.content_hash,
                )
            }
        )
        if has_dataset
        else frozenset()
    )
    return InMemoryTrainingRunRepository(
        owner_user_id=owner_user_id,
        dataset_references=references,
    )


def test_repository_is_owner_scoped_idempotent_and_conflict_aware() -> None:
    repository = _repository()
    outcome = _outcome()

    created = asyncio.run(repository.append(outcome))
    repeated = asyncio.run(repository.append(outcome))
    conflict = asyncio.run(repository.append(_outcome(request_sha256="9" * 64)))
    stored = asyncio.run(repository.get_owned(run_id=RUN_ID))

    assert created.status is TrainingRunStoreStatus.APPENDED
    assert repeated.status is TrainingRunStoreStatus.ALREADY_PRESENT
    assert conflict.status is TrainingRunStoreStatus.CONTENT_CONFLICT
    assert stored == created.training_run == repeated.training_run
    assert stored is not None
    assert stored.metric_count == 2
    assert stored.checkpoints[0].step == 20
    assert stored.process_log_sha256 == "1" * 64


def test_repository_rejects_wrong_owner_and_unknown_dataset() -> None:
    wrong_owner = _repository(owner_user_id=UUID("00000000-0000-4000-8000-000000124099"))
    missing_dataset = _repository(has_dataset=False)

    assert (
        asyncio.run(wrong_owner.append(_outcome())).status is TrainingRunStoreStatus.OWNER_NOT_FOUND
    )
    assert (
        asyncio.run(missing_dataset.append(_outcome())).status
        is TrainingRunStoreStatus.DATASET_NOT_FOUND
    )


def test_record_mapping_preserves_metrics_logs_checkpoints_and_adapter_identity() -> None:
    outcome = _outcome()

    record = training_run_to_record(outcome)
    checkpoint = training_checkpoint_to_record(
        run_id=outcome.run_id,
        owner_user_id=outcome.owner_user_id,
        checkpoint=outcome.checkpoints[0],
    )
    projection = stored_training_run(outcome)

    assert record.metric_count == 2
    assert record.checkpoint_count == 1
    assert record.process_log_relative_path == "process-log.json"
    assert record.adapter_sha256 == "2" * 64
    assert record.content_hash in record.outcome_snapshot_json
    assert checkpoint.training_run_id == RUN_ID
    assert checkpoint.content_sha256 == "f" * 64
    assert projection.content_hash == outcome.content_hash


def test_history_is_stable_and_ordered() -> None:
    repository = _repository()
    asyncio.run(repository.append(_outcome()))

    first = asyncio.run(repository.history())
    second = asyncio.run(repository.history())

    assert first == second
    assert tuple(item.run_id for item in first) == (RUN_ID,)
