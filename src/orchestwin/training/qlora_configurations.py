"""Immutable, content-addressed QLoRA training configurations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_manifests import DatasetManifestReference

QLORA_CONFIGURATION_SCHEMA_VERSION: Final = 1

_REPOSITORY_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
)
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_MODULE_PATTERN: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}")
_MAX_IDENTIFIER_LENGTH: Final = 256


class QloraQuantizationType(StrEnum):
    """Four-bit quantization formats admitted by the training protocol."""

    NF4 = "nf4"
    FP4 = "fp4"


class QloraComputeDtype(StrEnum):
    """Compute dtypes used while loading quantized base weights."""

    BFLOAT16 = "bfloat16"
    FLOAT16 = "float16"


class QloraPrecision(StrEnum):
    """Trainer precision selected after the hardware feasibility spike."""

    BF16 = "bf16"
    FP16 = "fp16"


class QloraOptimizer(StrEnum):
    """Explicit optimizer choices supported by the isolated trainer."""

    ADAMW_8BIT = "adamw_8bit"
    ADAMW_TORCH = "adamw_torch"


class QloraScheduler(StrEnum):
    """Explicit learning-rate schedulers supported by the training script."""

    LINEAR = "linear"
    COSINE = "cosine"


class LoraBiasMode(StrEnum):
    """PEFT bias policy recorded with each adapter configuration."""

    NONE = "none"
    ALL = "all"
    LORA_ONLY = "lora_only"


@dataclass(frozen=True, slots=True)
class QloraQuantizationConfiguration:
    """Exact four-bit base-model loading policy."""

    quantization_type: QloraQuantizationType
    compute_dtype: QloraComputeDtype
    double_quantization: bool
    load_in_4bit: bool = True

    def __post_init__(self) -> None:
        if not self.load_in_4bit:
            raise ValueError("QLoRA configuration must load the base model in four bits")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "load_in_4bit": self.load_in_4bit,
            "quantization_type": self.quantization_type.value,
            "compute_dtype": self.compute_dtype.value,
            "double_quantization": self.double_quantization,
        }


@dataclass(frozen=True, slots=True)
class LoraAdapterConfiguration:
    """Immutable LoRA topology and target-module policy."""

    rank: int
    alpha: int
    dropout: float
    target_modules: tuple[str, ...]
    bias: LoraBiasMode
    use_rslora: bool

    def __post_init__(self) -> None:
        validate_positive_integer(self.rank, label="LoRA rank")
        validate_positive_integer(self.alpha, label="LoRA alpha")
        if not math.isfinite(float(self.dropout)) or not 0.0 <= float(self.dropout) < 1.0:
            raise ValueError("LoRA dropout must be finite and between zero and one")
        if not self.target_modules:
            raise ValueError("LoRA target modules must not be empty")
        if self.target_modules != tuple(sorted(set(self.target_modules))):
            raise ValueError("LoRA target modules must be unique and use canonical order")
        if any(_MODULE_PATTERN.fullmatch(module) is None for module in self.target_modules):
            raise ValueError("LoRA target modules must use dotted Python-style identifiers")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "alpha": self.alpha,
            "dropout": float(self.dropout),
            "target_modules": list(self.target_modules),
            "bias": self.bias.value,
            "use_rslora": self.use_rslora,
        }


@dataclass(frozen=True, slots=True)
class QloraOptimizationConfiguration:
    """Reproducible supervised fine-tuning and memory policy."""

    max_sequence_length: int
    per_device_train_batch_size: int
    gradient_accumulation_steps: int
    learning_rate: float
    weight_decay: float
    warmup_ratio: float
    max_steps: int | None
    num_train_epochs: float | None
    optimizer: QloraOptimizer
    scheduler: QloraScheduler
    precision: QloraPrecision
    gradient_checkpointing: bool
    gradient_clip_norm: float
    logging_steps: int

    def __post_init__(self) -> None:
        for value, label in (
            (self.max_sequence_length, "maximum sequence length"),
            (self.per_device_train_batch_size, "per-device training batch size"),
            (self.gradient_accumulation_steps, "gradient accumulation steps"),
            (self.logging_steps, "training logging steps"),
        ):
            validate_positive_integer(value, label=label)
        if (self.max_steps is None) == (self.num_train_epochs is None):
            raise ValueError("configure exactly one of maximum steps or training epochs")
        if self.max_steps is not None:
            validate_positive_integer(self.max_steps, label="maximum training steps")
        if self.num_train_epochs is not None and (
            not math.isfinite(float(self.num_train_epochs)) or self.num_train_epochs <= 0
        ):
            raise ValueError("training epochs must be finite and positive")
        _validate_positive_float(self.learning_rate, label="learning rate")
        _validate_non_negative_float(self.weight_decay, label="weight decay")
        if not math.isfinite(float(self.warmup_ratio)) or not 0.0 <= self.warmup_ratio < 1.0:
            raise ValueError("warmup ratio must be finite and between zero and one")
        _validate_positive_float(self.gradient_clip_norm, label="gradient clipping norm")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "max_sequence_length": self.max_sequence_length,
            "per_device_train_batch_size": self.per_device_train_batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "learning_rate": float(self.learning_rate),
            "weight_decay": float(self.weight_decay),
            "warmup_ratio": float(self.warmup_ratio),
            "max_steps": self.max_steps,
            "num_train_epochs": self.num_train_epochs,
            "optimizer": self.optimizer.value,
            "scheduler": self.scheduler.value,
            "precision": self.precision.value,
            "gradient_checkpointing": self.gradient_checkpointing,
            "gradient_clip_norm": float(self.gradient_clip_norm),
            "logging_steps": self.logging_steps,
        }


@dataclass(frozen=True, slots=True)
class QloraCheckpointPolicy:
    """Checkpoint, evaluation, and early-stopping behavior."""

    save_steps: int
    evaluation_steps: int
    save_total_limit: int
    load_best_model_at_end: bool
    metric_for_best_model: str | None
    greater_is_better: bool | None
    early_stopping_patience: int | None

    def __post_init__(self) -> None:
        for value, label in (
            (self.save_steps, "checkpoint save steps"),
            (self.evaluation_steps, "evaluation steps"),
            (self.save_total_limit, "checkpoint retention limit"),
        ):
            validate_positive_integer(value, label=label)
        if self.save_steps % self.evaluation_steps != 0:
            raise ValueError("checkpoint save steps must be a multiple of evaluation steps")
        has_metric = self.metric_for_best_model is not None
        if self.load_best_model_at_end != has_metric:
            raise ValueError("best-model loading requires exactly one evaluation metric")
        if has_metric:
            normalized = normalize_required_text(
                self.metric_for_best_model or "",
                label="best-model metric",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            if normalized != self.metric_for_best_model or any(
                character.isspace() for character in normalized
            ):
                raise ValueError("best-model metric must be a normalized identifier")
            if self.greater_is_better is None:
                raise ValueError("best-model direction is required with a metric")
        elif self.greater_is_better is not None:
            raise ValueError("best-model direction requires a selected metric")
        if self.early_stopping_patience is not None:
            validate_positive_integer(
                self.early_stopping_patience,
                label="early-stopping patience",
            )
            if not self.load_best_model_at_end:
                raise ValueError("early stopping requires best-model loading")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "save_steps": self.save_steps,
            "evaluation_steps": self.evaluation_steps,
            "save_total_limit": self.save_total_limit,
            "load_best_model_at_end": self.load_best_model_at_end,
            "metric_for_best_model": self.metric_for_best_model,
            "greater_is_better": self.greater_is_better,
            "early_stopping_patience": self.early_stopping_patience,
        }


@dataclass(frozen=True, slots=True)
class QloraTrainingConfiguration:
    """Exact base, dataset, QLoRA, optimizer, and checkpoint identity."""

    configuration_id: UUID
    candidate_id: str
    base_model_repository: str
    base_model_revision: str
    tokenizer_repository: str
    tokenizer_revision: str
    dataset_reference: DatasetManifestReference
    quantization: QloraQuantizationConfiguration
    adapter: LoraAdapterConfiguration
    optimization: QloraOptimizationConfiguration
    checkpoints: QloraCheckpointPolicy
    seed: int
    created_at: datetime
    content_hash: str
    schema_version: int = QLORA_CONFIGURATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != QLORA_CONFIGURATION_SCHEMA_VERSION:
            raise ValueError("unsupported QLoRA configuration schema version")
        _validate_identifier(self.candidate_id, label="model candidate ID")
        _validate_repository(self.base_model_repository, label="base model repository")
        _validate_revision(self.base_model_revision, label="base model revision")
        _validate_repository(self.tokenizer_repository, label="tokenizer repository")
        _validate_revision(self.tokenizer_revision, label="tokenizer revision")
        validate_positive_integer(self.seed, label="training seed")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("QLoRA configuration timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="QLoRA configuration content hash")
        if self.content_hash != qlora_training_configuration_hash(
            candidate_id=self.candidate_id,
            base_model_repository=self.base_model_repository,
            base_model_revision=self.base_model_revision,
            tokenizer_repository=self.tokenizer_repository,
            tokenizer_revision=self.tokenizer_revision,
            dataset_reference=self.dataset_reference,
            quantization=self.quantization,
            adapter=self.adapter,
            optimization=self.optimization,
            checkpoints=self.checkpoints,
            seed=self.seed,
            schema_version=self.schema_version,
        ):
            raise ValueError("QLoRA configuration content hash is inconsistent")

    def semantic_snapshot(self) -> dict[str, object]:
        return _qlora_semantic_snapshot(
            candidate_id=self.candidate_id,
            base_model_repository=self.base_model_repository,
            base_model_revision=self.base_model_revision,
            tokenizer_repository=self.tokenizer_repository,
            tokenizer_revision=self.tokenizer_revision,
            dataset_reference=self.dataset_reference,
            quantization=self.quantization,
            adapter=self.adapter,
            optimization=self.optimization,
            checkpoints=self.checkpoints,
            seed=self.seed,
            schema_version=self.schema_version,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "configuration_id": str(self.configuration_id),
            **self.semantic_snapshot(),
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
        }


def create_lora_adapter_configuration(
    *,
    rank: int,
    alpha: int,
    dropout: float,
    target_modules: tuple[str, ...],
    bias: LoraBiasMode,
    use_rslora: bool,
) -> LoraAdapterConfiguration:
    """Canonicalize target modules before creating a LoRA configuration."""
    return LoraAdapterConfiguration(
        rank=rank,
        alpha=alpha,
        dropout=dropout,
        target_modules=tuple(sorted(set(target_modules))),
        bias=bias,
        use_rslora=use_rslora,
    )


def create_qlora_training_configuration(
    *,
    configuration_id: UUID,
    candidate_id: str,
    base_model_repository: str,
    base_model_revision: str,
    tokenizer_repository: str,
    tokenizer_revision: str,
    dataset_reference: DatasetManifestReference,
    quantization: QloraQuantizationConfiguration,
    adapter: LoraAdapterConfiguration,
    optimization: QloraOptimizationConfiguration,
    checkpoints: QloraCheckpointPolicy,
    seed: int,
    created_at: datetime,
) -> QloraTrainingConfiguration:
    """Create one content-addressed immutable QLoRA configuration."""
    content_hash = qlora_training_configuration_hash(
        candidate_id=candidate_id,
        base_model_repository=base_model_repository,
        base_model_revision=base_model_revision,
        tokenizer_repository=tokenizer_repository,
        tokenizer_revision=tokenizer_revision,
        dataset_reference=dataset_reference,
        quantization=quantization,
        adapter=adapter,
        optimization=optimization,
        checkpoints=checkpoints,
        seed=seed,
        schema_version=QLORA_CONFIGURATION_SCHEMA_VERSION,
    )
    return QloraTrainingConfiguration(
        configuration_id=configuration_id,
        candidate_id=candidate_id,
        base_model_repository=base_model_repository,
        base_model_revision=base_model_revision,
        tokenizer_repository=tokenizer_repository,
        tokenizer_revision=tokenizer_revision,
        dataset_reference=dataset_reference,
        quantization=quantization,
        adapter=adapter,
        optimization=optimization,
        checkpoints=checkpoints,
        seed=seed,
        created_at=created_at,
        content_hash=content_hash,
    )


def qlora_training_configuration_hash(
    *,
    candidate_id: str,
    base_model_repository: str,
    base_model_revision: str,
    tokenizer_repository: str,
    tokenizer_revision: str,
    dataset_reference: DatasetManifestReference,
    quantization: QloraQuantizationConfiguration,
    adapter: LoraAdapterConfiguration,
    optimization: QloraOptimizationConfiguration,
    checkpoints: QloraCheckpointPolicy,
    seed: int,
    schema_version: int,
) -> str:
    """Hash semantic training inputs independently from identity and timestamp."""
    return snapshot_content_hash(
        _qlora_semantic_snapshot(
            candidate_id=candidate_id,
            base_model_repository=base_model_repository,
            base_model_revision=base_model_revision,
            tokenizer_repository=tokenizer_repository,
            tokenizer_revision=tokenizer_revision,
            dataset_reference=dataset_reference,
            quantization=quantization,
            adapter=adapter,
            optimization=optimization,
            checkpoints=checkpoints,
            seed=seed,
            schema_version=schema_version,
        )
    )


def _qlora_semantic_snapshot(
    *,
    candidate_id: str,
    base_model_repository: str,
    base_model_revision: str,
    tokenizer_repository: str,
    tokenizer_revision: str,
    dataset_reference: DatasetManifestReference,
    quantization: QloraQuantizationConfiguration,
    adapter: LoraAdapterConfiguration,
    optimization: QloraOptimizationConfiguration,
    checkpoints: QloraCheckpointPolicy,
    seed: int,
    schema_version: int,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "candidate_id": candidate_id,
        "base_model_repository": base_model_repository,
        "base_model_revision": base_model_revision,
        "tokenizer_repository": tokenizer_repository,
        "tokenizer_revision": tokenizer_revision,
        "dataset_reference": dataset_reference.to_snapshot(),
        "quantization": quantization.to_snapshot(),
        "adapter": adapter.to_snapshot(),
        "optimization": optimization.to_snapshot(),
        "checkpoints": checkpoints.to_snapshot(),
        "seed": seed,
    }


def _validate_repository(value: str, *, label: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must use owner/repository form")


def _validate_revision(value: str, *, label: str) -> None:
    if _REVISION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be an exact hexadecimal revision")


def _validate_identifier(value: str, *, label: str) -> None:
    normalized = normalize_required_text(
        value,
        label=label,
        maximum_length=_MAX_IDENTIFIER_LENGTH,
    )
    if normalized != value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be a normalized identifier")


def _validate_positive_float(value: float, *, label: str) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
        raise ValueError(f"{label} must be finite and positive")


def _validate_non_negative_float(value: float, *, label: str) -> None:
    if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) < 0:
        raise ValueError(f"{label} must be finite and non-negative")
