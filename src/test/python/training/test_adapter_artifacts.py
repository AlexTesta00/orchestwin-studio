"""Tests for content-addressed LoRA adapter artifact registration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.training.adapter_artifacts import (
    AdapterRegistrationStatus,
    ContentAddressedAdapterRegistry,
    create_adapter_artifact_manifest,
    inspect_adapter_directory,
)
from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.qlora_configurations import (
    LoraBiasMode,
    QloraCheckpointPolicy,
    QloraComputeDtype,
    QloraOptimizationConfiguration,
    QloraOptimizer,
    QloraPrecision,
    QloraQuantizationConfiguration,
    QloraQuantizationType,
    QloraScheduler,
    create_lora_adapter_configuration,
    create_qlora_training_configuration,
)
from orchestwin.training.unsloth_adapter import (
    QloraTrainingStatus,
    create_qlora_training_outcome,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000125001")
RUN_ID = UUID("00000000-0000-4000-8000-000000125002")
ADAPTER_ID = UUID("00000000-0000-4000-8000-000000125003")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _configuration():
    return create_qlora_training_configuration(
        configuration_id=UUID("00000000-0000-4000-8000-000000125004"),
        candidate_id="selected-small-instruct",
        base_model_repository="example/selected-small-instruct",
        base_model_revision="a" * 40,
        tokenizer_repository="example/selected-small-instruct",
        tokenizer_revision="b" * 40,
        dataset_reference=DatasetManifestReference(
            dataset_id=UUID("00000000-0000-4000-8000-000000125005"),
            version_number=2,
            content_hash="c" * 64,
        ),
        quantization=QloraQuantizationConfiguration(
            quantization_type=QloraQuantizationType.NF4,
            compute_dtype=QloraComputeDtype.BFLOAT16,
            double_quantization=True,
        ),
        adapter=create_lora_adapter_configuration(
            rank=16,
            alpha=32,
            dropout=0.0,
            target_modules=("k_proj", "q_proj", "v_proj"),
            bias=LoraBiasMode.NONE,
            use_rslora=False,
        ),
        optimization=QloraOptimizationConfiguration(
            max_sequence_length=2048,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
            learning_rate=0.0002,
            weight_decay=0.01,
            warmup_ratio=0.03,
            max_steps=40,
            num_train_epochs=None,
            optimizer=QloraOptimizer.ADAMW_8BIT,
            scheduler=QloraScheduler.LINEAR,
            precision=QloraPrecision.BF16,
            gradient_checkpointing=True,
            gradient_clip_norm=1.0,
            logging_steps=1,
        ),
        checkpoints=QloraCheckpointPolicy(
            save_steps=20,
            evaluation_steps=10,
            save_total_limit=2,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            early_stopping_patience=2,
        ),
        seed=3407,
        created_at=NOW,
    )


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source-adapter"
    source.mkdir()
    (source / "adapter_config.json").write_text(
        json.dumps({"peft_type": "LORA", "r": 16}, sort_keys=True),
        encoding="utf-8",
    )
    (source / "adapter_model.safetensors").write_bytes(b"adapter-weights-v1")
    (source / "tokenizer_config.json").write_text(
        json.dumps({"model_max_length": 2048}, sort_keys=True),
        encoding="utf-8",
    )
    return source


def _outcome(configuration, adapter_sha256: str):
    return create_qlora_training_outcome(
        run_id=RUN_ID,
        owner_user_id=OWNER_ID,
        request_sha256="d" * 64,
        configuration_sha256=configuration.content_hash,
        dataset_reference=configuration.dataset_reference,
        package_lock_sha256="e" * 64,
        environment_sha256="f" * 64,
        status=QloraTrainingStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW.replace(minute=3),
        duration_milliseconds=180_000,
        peak_gpu_memory_mb=6_500,
        metrics=(),
        checkpoints=(),
        process_log_relative_path="process-log.json",
        process_log_sha256="1" * 64,
        adapter_relative_path="outputs/adapter",
        adapter_sha256=adapter_sha256,
        failure_kind=None,
        failure_message=None,
    )


def test_registry_copies_and_verifies_exact_content_addressed_adapter(tmp_path: Path) -> None:
    source = _source(tmp_path)
    files, digest = inspect_adapter_directory(source)
    configuration = _configuration()
    manifest = create_adapter_artifact_manifest(
        adapter_id=ADAPTER_ID,
        outcome=_outcome(configuration, digest),
        configuration=configuration,
        license_spdx="Apache-2.0",
        files=files,
        adapter_sha256=digest,
        created_at=NOW,
    )
    registry = ContentAddressedAdapterRegistry(tmp_path / "registry")

    created = registry.register(source_directory=source, manifest=manifest)
    repeated = registry.register(source_directory=source, manifest=manifest)

    assert created.status is AdapterRegistrationStatus.REGISTERED
    assert repeated.status is AdapterRegistrationStatus.ALREADY_PRESENT
    assert created.artifact_directory == repeated.artifact_directory
    assert created.artifact_directory.name == digest
    assert created.manifest_path.is_file()
    stored_files, stored_digest = inspect_adapter_directory(created.artifact_directory)
    assert stored_files == files
    assert stored_digest == digest
    assert json.loads(created.manifest_path.read_text())["training_run_id"] == str(RUN_ID)


def test_manifest_binds_exact_base_dataset_configuration_and_license(tmp_path: Path) -> None:
    files, digest = inspect_adapter_directory(_source(tmp_path))
    configuration = _configuration()

    manifest = create_adapter_artifact_manifest(
        adapter_id=ADAPTER_ID,
        outcome=_outcome(configuration, digest),
        configuration=configuration,
        license_spdx="Apache-2.0",
        files=files,
        adapter_sha256=digest,
        created_at=NOW,
    )

    assert manifest.base_model_revision == "a" * 40
    assert manifest.tokenizer_revision == "b" * 40
    assert manifest.dataset_reference == configuration.dataset_reference
    assert manifest.training_configuration_sha256 == configuration.content_hash
    assert manifest.storage_key == f"sha256/{digest[:2]}/{digest}"
    assert manifest.license_spdx == "Apache-2.0"


def test_registration_rejects_digest_drift_and_invalid_adapter_configuration(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    files, digest = inspect_adapter_directory(source)
    configuration = _configuration()
    manifest = create_adapter_artifact_manifest(
        adapter_id=ADAPTER_ID,
        outcome=_outcome(configuration, digest),
        configuration=configuration,
        license_spdx="Apache-2.0",
        files=files,
        adapter_sha256=digest,
        created_at=NOW,
    )
    (source / "adapter_model.safetensors").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="does not match"):
        ContentAddressedAdapterRegistry(tmp_path / "registry").register(
            source_directory=source,
            manifest=manifest,
        )

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "adapter_config.json").write_text('{"peft_type":"PREFIX_TUNING"}')
    (invalid / "adapter_model.safetensors").write_bytes(b"weights")
    with pytest.raises(ValueError, match="LoRA"):
        inspect_adapter_directory(invalid)


def test_inspection_rejects_missing_weights_and_symbolic_links(tmp_path: Path) -> None:
    missing_weights = tmp_path / "missing-weights"
    missing_weights.mkdir()
    (missing_weights / "adapter_config.json").write_text('{"peft_type":"LORA"}')
    files, digest = inspect_adapter_directory(missing_weights)
    configuration = _configuration()

    with pytest.raises(ValueError, match="weight files"):
        create_adapter_artifact_manifest(
            adapter_id=ADAPTER_ID,
            outcome=_outcome(configuration, digest),
            configuration=configuration,
            license_spdx="Apache-2.0",
            files=files,
            adapter_sha256=digest,
            created_at=NOW,
        )

    source = _source(tmp_path)
    try:
        (source / "linked.bin").symlink_to(source / "adapter_model.safetensors")
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")
    with pytest.raises(ValueError, match="symbolic links"):
        inspect_adapter_directory(source)


def test_manifest_rejects_training_configuration_identity_drift(tmp_path: Path) -> None:
    source = _source(tmp_path)
    files, digest = inspect_adapter_directory(source)
    configuration = _configuration()
    mismatched_outcome = create_qlora_training_outcome(
        run_id=RUN_ID,
        owner_user_id=OWNER_ID,
        request_sha256="d" * 64,
        configuration_sha256="9" * 64,
        dataset_reference=configuration.dataset_reference,
        package_lock_sha256="e" * 64,
        environment_sha256="f" * 64,
        status=QloraTrainingStatus.SUCCEEDED,
        started_at=NOW,
        completed_at=NOW.replace(minute=3),
        duration_milliseconds=180_000,
        peak_gpu_memory_mb=6_500,
        metrics=(),
        checkpoints=(),
        process_log_relative_path="process-log.json",
        process_log_sha256="1" * 64,
        adapter_relative_path="outputs/adapter",
        adapter_sha256=digest,
        failure_kind=None,
        failure_message=None,
    )

    with pytest.raises(ValueError, match="configuration identity"):
        create_adapter_artifact_manifest(
            adapter_id=ADAPTER_ID,
            outcome=mismatched_outcome,
            configuration=configuration,
            license_spdx="Apache-2.0",
            files=files,
            adapter_sha256=digest,
            created_at=NOW,
        )
