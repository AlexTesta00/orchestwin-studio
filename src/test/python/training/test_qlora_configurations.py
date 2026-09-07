"""Tests for immutable reproducible QLoRA training configurations."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

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

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def _configuration():
    adapter = create_lora_adapter_configuration(
        rank=16,
        alpha=32,
        dropout=0.0,
        target_modules=("v_proj", "q_proj", "k_proj", "q_proj"),
        bias=LoraBiasMode.NONE,
        use_rslora=False,
    )
    return create_qlora_training_configuration(
        configuration_id=UUID("00000000-0000-4000-8000-000000122001"),
        candidate_id="model-candidate-small-instruct",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_repository="example/small-instruct",
        tokenizer_revision="b" * 40,
        dataset_reference=DatasetManifestReference(
            dataset_id=UUID("00000000-0000-4000-8000-000000122002"),
            version_number=3,
            content_hash="c" * 64,
        ),
        quantization=QloraQuantizationConfiguration(
            quantization_type=QloraQuantizationType.NF4,
            compute_dtype=QloraComputeDtype.BFLOAT16,
            double_quantization=True,
        ),
        adapter=adapter,
        optimization=QloraOptimizationConfiguration(
            max_sequence_length=2048,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=16,
            learning_rate=0.0002,
            weight_decay=0.01,
            warmup_ratio=0.03,
            max_steps=120,
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
            save_total_limit=3,
            load_best_model_at_end=True,
            metric_for_best_model="eval_loss",
            greater_is_better=False,
            early_stopping_patience=3,
        ),
        seed=3407,
        created_at=NOW,
    )


def test_configuration_is_canonical_content_addressed_and_complete() -> None:
    configuration = _configuration()

    assert configuration.adapter.target_modules == ("k_proj", "q_proj", "v_proj")
    assert configuration.semantic_snapshot()["dataset_reference"]["version_number"] == 3
    assert configuration.to_snapshot()["content_hash"] == configuration.content_hash
    assert len(configuration.content_hash) == 64


def test_equivalent_semantic_configuration_has_the_same_hash() -> None:
    first = _configuration()
    second = create_qlora_training_configuration(
        configuration_id=UUID("00000000-0000-4000-8000-000000122099"),
        candidate_id=first.candidate_id,
        base_model_repository=first.base_model_repository,
        base_model_revision=first.base_model_revision,
        tokenizer_repository=first.tokenizer_repository,
        tokenizer_revision=first.tokenizer_revision,
        dataset_reference=first.dataset_reference,
        quantization=first.quantization,
        adapter=first.adapter,
        optimization=first.optimization,
        checkpoints=first.checkpoints,
        seed=first.seed,
        created_at=NOW.replace(hour=10),
    )

    assert first.configuration_id != second.configuration_id
    assert first.created_at != second.created_at
    assert first.content_hash == second.content_hash


def test_configuration_rejects_hash_drift_and_non_exact_revisions() -> None:
    configuration = _configuration()

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(configuration, content_hash="0" * 64)
    with pytest.raises(ValueError, match="exact hexadecimal revision"):
        replace(configuration, base_model_revision="main")


def test_optimization_requires_one_bounded_training_duration() -> None:
    valid = _configuration().optimization

    with pytest.raises(ValueError, match="exactly one"):
        replace(valid, max_steps=None, num_train_epochs=None)
    with pytest.raises(ValueError, match="exactly one"):
        replace(valid, max_steps=100, num_train_epochs=1.0)


def test_checkpoint_and_lora_policies_reject_ambiguous_values() -> None:
    configuration = _configuration()

    with pytest.raises(ValueError, match="multiple of evaluation steps"):
        replace(configuration.checkpoints, save_steps=15)
    with pytest.raises(ValueError, match="best-model loading"):
        replace(
            configuration.checkpoints,
            load_best_model_at_end=False,
            metric_for_best_model="eval_loss",
        )
    with pytest.raises(ValueError, match="canonical order"):
        replace(configuration.adapter, target_modules=("v_proj", "q_proj"))
