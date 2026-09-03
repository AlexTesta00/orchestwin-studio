"""Tests for the constrained Unsloth QLoRA training adapter."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
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
from orchestwin.training.unsloth_adapter import (
    QloraTrainingFailureKind,
    QloraTrainingStatus,
    TrainingMetricObservation,
    UnslothProcessInvocation,
    UnslothProcessResult,
    UnslothQloraTrainingAdapter,
    UnslothTrainingRequest,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000123001")
RUN_ID = UUID("00000000-0000-4000-8000-000000123002")
NOW = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)


def _configuration():
    return create_qlora_training_configuration(
        configuration_id=UUID("00000000-0000-4000-8000-000000123003"),
        candidate_id="small-instruct-candidate",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_repository="example/small-instruct",
        tokenizer_revision="b" * 40,
        dataset_reference=DatasetManifestReference(
            dataset_id=UUID("00000000-0000-4000-8000-000000123004"),
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
            target_modules=("q_proj", "k_proj", "v_proj"),
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


def _request() -> UnslothTrainingRequest:
    return UnslothTrainingRequest(
        run_id=RUN_ID,
        owner_user_id=OWNER_ID,
        configuration=_configuration(),
        train_dataset_path="datasets/train.jsonl",
        validation_dataset_path="datasets/validation.jsonl",
        output_directory="outputs",
        package_lock_sha256="d" * 64,
        environment_sha256="e" * 64,
        requested_at=NOW,
    )


def _input_root(tmp_path: Path) -> Path:
    root = tmp_path / "inputs"
    (root / "datasets").mkdir(parents=True)
    (root / "datasets" / "train.jsonl").write_text('{"text":"train"}\n')
    (root / "datasets" / "validation.jsonl").write_text('{"text":"validation"}\n')
    return root


@dataclass
class _FakeProcess:
    mode: str
    invocation: UnslothProcessInvocation | None = None

    async def run(self, invocation: UnslothProcessInvocation) -> UnslothProcessResult:
        self.invocation = invocation
        if self.mode == "timeout":
            return UnslothProcessResult(None, "", "", 5_000, True, False)
        if self.mode == "missing":
            return UnslothProcessResult(20, "", "unsloth is not installed", 20, False, False)
        request_path = Path(invocation.arguments[invocation_index(invocation, "--request") + 1])
        result_path = Path(invocation.arguments[invocation_index(invocation, "--result") + 1])
        request_payload = json.loads(request_path.read_text())
        digest = request_payload["request_sha256"]
        if self.mode == "bad-digest":
            digest = "0" * 64
        result_path.write_text(
            json.dumps(
                {
                    "request_sha256": digest,
                    "status": "SUCCEEDED",
                    "started_at": NOW.isoformat(),
                    "completed_at": NOW.replace(minute=1).isoformat(),
                    "duration_milliseconds": 60_000,
                    "peak_gpu_memory_mb": 6_420,
                    "metrics": [
                        {"name": "eval_loss", "value": 0.42, "step": 20},
                        {"name": "train_loss", "value": 0.38, "step": 20},
                    ],
                    "checkpoints": [
                        {
                            "step": 20,
                            "relative_path": "outputs/checkpoint-20",
                            "content_sha256": "f" * 64,
                        }
                    ],
                    "adapter_relative_path": "outputs/adapter",
                    "adapter_sha256": "1" * 64,
                    "failure_kind": None,
                    "failure_message": None,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return UnslothProcessResult(0, "completed", "", 60_000, False, False)


def invocation_index(invocation: UnslothProcessInvocation, argument: str) -> int:
    return invocation.arguments.index(argument)


def _adapter(tmp_path: Path, process: _FakeProcess) -> UnslothQloraTrainingAdapter:
    environment = tmp_path / "environment"
    environment.mkdir(parents=True)
    (environment / "run_qlora.py").write_text("raise SystemExit(0)\n")
    return UnslothQloraTrainingAdapter(
        process_port=process,
        training_environment_directory=environment,
        input_artifact_root=_input_root(tmp_path),
        workspace_root=tmp_path / "workspaces",
        timeout_seconds=600,
    )


def test_adapter_stages_inputs_and_accepts_a_content_addressed_success(tmp_path: Path) -> None:
    process = _FakeProcess("success")
    request = _request()

    outcome = asyncio.run(_adapter(tmp_path, process).train(request))

    assert outcome.status is QloraTrainingStatus.SUCCEEDED
    assert outcome.adapter_sha256 == "1" * 64
    assert outcome.metrics[0].name == "eval_loss"
    assert outcome.content_hash != request.content_hash
    assert outcome.process_log_relative_path == "process-log.json"
    assert len(outcome.process_log_sha256) == 64
    assert process.invocation is not None
    assert process.invocation.executable == "uv"
    assert process.invocation.arguments[:6] == (
        "run",
        "--frozen",
        "--python",
        "3.13",
        "python",
        "run_qlora.py",
    )
    workspace = tmp_path / "workspaces" / str(RUN_ID)
    assert (workspace / "datasets" / "train.jsonl").is_file()
    process_payload = json.loads((workspace / "request.json").read_text())
    assert "owner_user_id" not in process_payload
    assert "HF_TOKEN" not in json.dumps(process_payload)


def test_missing_dependency_and_timeout_are_typed_failures(tmp_path: Path) -> None:
    missing = asyncio.run(_adapter(tmp_path / "missing", _FakeProcess("missing")).train(_request()))
    timed_out = asyncio.run(
        _adapter(tmp_path / "timeout", _FakeProcess("timeout")).train(
            replace(_request(), run_id=UUID("00000000-0000-4000-8000-000000123099"))
        )
    )

    assert missing.status is QloraTrainingStatus.FAILED
    assert missing.failure_kind is QloraTrainingFailureKind.MISSING_DEPENDENCY
    assert timed_out.status is QloraTrainingStatus.TIMED_OUT
    assert timed_out.failure_kind is QloraTrainingFailureKind.TIMEOUT


def test_result_identity_drift_is_rejected(tmp_path: Path) -> None:
    outcome = asyncio.run(_adapter(tmp_path, _FakeProcess("bad-digest")).train(_request()))

    assert outcome.status is QloraTrainingStatus.FAILED
    assert outcome.failure_kind is QloraTrainingFailureKind.INVALID_RESULT
    assert outcome.adapter_sha256 is None


def test_request_and_input_staging_reject_unsafe_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="traversal-free"):
        replace(_request(), train_dataset_path="../train.jsonl")
    with pytest.raises(ValueError, match="distinct"):
        replace(_request(), validation_dataset_path="datasets/train.jsonl")

    root = _input_root(tmp_path)
    link = root / "datasets" / "linked.jsonl"
    try:
        link.symlink_to(root / "datasets" / "train.jsonl")
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")
    request = replace(_request(), train_dataset_path="datasets/linked.jsonl")
    environment = tmp_path / "environment"
    environment.mkdir(parents=True)
    (environment / "run_qlora.py").write_text("raise SystemExit(0)\n")
    adapter = UnslothQloraTrainingAdapter(
        process_port=_FakeProcess("success"),
        training_environment_directory=environment,
        input_artifact_root=root,
        workspace_root=tmp_path / "workspaces",
        timeout_seconds=600,
    )

    with pytest.raises(ValueError, match="symbolic links"):
        asyncio.run(adapter.train(request))


def test_metrics_reject_non_finite_values_and_runner_help_is_dependency_free() -> None:
    with pytest.raises(ValueError, match="finite"):
        TrainingMetricObservation(name="loss", value=float("nan"), step=1)

    source = Path("environments/training/run_qlora.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "from unsloth import FastLanguageModel" in source
    assert source.index("def _load_runtime_dependencies") < source.index(
        "from unsloth import FastLanguageModel"
    )
