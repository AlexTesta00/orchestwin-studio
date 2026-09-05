"""Materialize a reviewed-next, bounded smoke proposal without invoking a trainer."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid5

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import (
    measurement_policy_snapshot,
    strict_json_loads,
)
from orchestwin.training.benchmark_suite_files import FROZEN_BENCHMARK_SUITE_CONTENT_HASH
from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
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
from orchestwin.training.qlora_smoke_fixtures import (
    SMOKE_FIXTURE_PATH,
    SMOKE_FIXTURE_SHA256,
    SMOKE_LIMITATION,
    SMOKE_PURPOSE,
    SmokePreparationError,
    load_smoke_fixtures,
    regular_smoke_path,
)

_NAMESPACE = UUID("2edfdbf6-0d9c-56df-9eaa-5fce13ff97a8")
_LOCK_SHA256 = "fcd551c5c136ba0c6266d131b41a10ae48b13477dc7269f786a29f7db14d073b"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(payload: object) -> bytes:
    return canonical_json(payload).encode("utf-8")


def _with_hash(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "content_hash": snapshot_content_hash(payload)}


def _report_identity(path: Path, matrix: object, candidate: object) -> tuple[dict, bytes]:
    """Check report consistency and exact inference provenance, without ranking its scores.

    This is a binding to a v2 report, not a new revalidation of its external raw bundle.
    Training authorization and license approval are deliberately not inferred from it.
    """
    raw = regular_smoke_path(path).read_bytes()
    report = strict_json_loads(raw.decode("utf-8"))
    if not isinstance(report, dict):
        raise SmokePreparationError("reanalysis must contain an object")
    semantic = {key: value for key, value in report.items() if key != "content_hash"}
    if raw != _json(report) or report.get("content_hash") != snapshot_content_hash(semantic):
        raise SmokePreparationError("reanalysis content hash or canonical serialization changed")
    expected = {
        "schema_version": 2,
        "report_id": "user-twin-evaluator-model-spike-reanalysis-v2",
        "candidate_matrix_content_hash": matrix.content_hash,
        "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
        "selection_status": "NO_MODEL_SELECTED",
        "ready_for_owner_selection": False,
        "live_inference_executed": False,
        "original_reports_replaced": False,
        "post_hoc": True,
        "package_lock_sha256": _LOCK_SHA256,
        "policy": measurement_policy_snapshot(),
    }
    if _json({key: report.get(key) for key in expected}) != _json(expected):
        raise SmokePreparationError("reanalysis policy, status, or frozen identity differs")
    if report.get("policy_content_hash") != snapshot_content_hash(report["policy"]):
        raise SmokePreparationError("reanalysis policy digest changed")
    if report.get("input_inventory_content_hash") != snapshot_content_hash(
        {
            "files": report.get("input_inventory"),
        }
    ):
        raise SmokePreparationError("reanalysis inventory digest changed")
    for key in ("environment_sha256", "source_plan_content_hash", "source_batch_content_hash"):
        value = report.get(key)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise SmokePreparationError(f"reanalysis {key} must be a SHA-256")
    rows = report.get("candidates")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise SmokePreparationError("reanalysis candidates are missing")
    identifiers = [row.get("candidate_id") for row in rows]
    if len(set(identifiers)) != len(identifiers):
        raise SmokePreparationError("duplicate reanalysis candidate")
    chosen = next((row for row in rows if row.get("candidate_id") == candidate.candidate_id), None)
    if chosen is None:
        raise SmokePreparationError("requested candidate has no reanalysis evidence")
    observed = chosen.get("observed_identity")
    if not isinstance(observed, dict) or any(
        (
            chosen.get("model_repository") != candidate.repository_id,
            chosen.get("requested_revision") != candidate.revision,
            observed.get("observed_model_revision") != candidate.revision,
            chosen.get("process_status") != "SUCCEEDED",
            chosen.get("runner_status") != "COMPLETED",
        )
    ):
        raise SmokePreparationError("candidate lacks completed exact-revision inference evidence")
    return report, raw


def smoke_runtime_requirements() -> dict[str, object]:
    """Explicit requirements to verify in the next runner/tokenizer preflight."""
    return {
        "use_exact_model_name": True,
        "trust_remote_code": False,
        "fast_inference": False,
        "load_in_4bit": True,
        "import_order": ["unsloth", "torch", "transformers", "trl"],
        "dataset_format": "CONVERSATIONAL_PROMPT_COMPLETION",
        "completion_only_loss": True,
        "assistant_only_loss": False,
        "packing": False,
        "eval_packing": False,
        "padding_free": False,
        "per_device_eval_batch_size": 1,
        "dataset_num_proc": 1,
        "dataloader_num_workers": 0,
        "sequence_overflow_policy": "REJECT_NOT_TRUNCATE",
        "tokenizer_revision_observation": "REQUIRED_BEFORE_TRAINING",
        "checkpoint_restore_test": "REQUIRED_AFTER_SMOKE",
        "adapter_export_and_reload": "REQUIRED_AFTER_SMOKE",
        "gpu_peak_memory": "NOT_MEASURED_FOR_TRAINING",
        "training_duration": "NOT_MEASURED",
        "suggested_process_timeout_seconds": 1800,
    }


def _output_path(output: Path, repository: Path, reanalysis: Path) -> Path:
    if ".." in output.parts:
        raise SmokePreparationError("parent traversal is not permitted in output paths")
    path = output.absolute()
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise SmokePreparationError("output path contains a symbolic link")
    for protected in (reanalysis.parent.absolute(), repository / "src", repository / "experiments"):
        if path == protected or protected in path.parents:
            raise SmokePreparationError("output cannot be inside protected input/source trees")
    artifact_root = repository / "environments" / "training" / "artifacts"
    if repository in path.parents and artifact_root not in path.parents:
        raise SmokePreparationError("repository paths outside training artifacts are protected")
    if path.exists():
        raise SmokePreparationError("smoke output directory must be absent")
    return path


def prepare_qlora_smoke(
    *,
    repository_root: Path,
    reanalysis_path: Path,
    candidate_id: str,
    output_root: Path,
    created_at: datetime,
) -> Path:
    """Prepare only data and configuration. No request or authorization is issued."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise SmokePreparationError("smoke timestamp must be timezone-aware")
    repository = repository_root.absolute()
    reanalysis_path = regular_smoke_path(reanalysis_path)
    destination = _output_path(output_root, repository, reanalysis_path)
    matrix = load_frozen_model_candidate_matrix(repository)
    try:
        candidate = matrix.candidate(candidate_id)
    except StopIteration as error:
        raise SmokePreparationError("candidate is not in the frozen matrix") from error
    report, report_raw = _report_identity(reanalysis_path, matrix, candidate)
    fixtures = load_smoke_fixtures(repository)
    data_files: dict[str, bytes] = {}
    entries = []
    for split in ("train", "validation"):
        records = []
        for row_index, sample in enumerate(fixtures.for_split(split)):
            serialized = _json(sample.training_record())
            records.append(serialized + b"\n")
            entries.append(
                {
                    "sample_id": sample.sample_id,
                    "scenario_family_id": sample.scenario_family_id,
                    "language": sample.language,
                    "split": split,
                    "row_index": row_index,
                    "sample_content_hash": snapshot_content_hash(sample.snapshot()),
                    "training_record_sha256": _sha(serialized),
                }
            )
        data_files[f"{split}.jsonl"] = b"".join(records)
    dataset_id = uuid5(_NAMESPACE, "dataset:" + SMOKE_FIXTURE_SHA256)
    manifest = _with_hash(
        {
            "schema_version": 1,
            "manifest_kind": "QLORA_SMOKE_FIXTURE_DATASET",
            "dataset_id": str(dataset_id),
            "version_number": 1,
            "purpose": SMOKE_PURPOSE,
            "limitation": SMOKE_LIMITATION,
            "fixture_path": SMOKE_FIXTURE_PATH,
            "fixture_sha256": SMOKE_FIXTURE_SHA256,
            "example_count": 20,
            "train_count": 16,
            "validation_count": 4,
            "entries": entries,
            "split_file_sha256": {name: _sha(raw) for name, raw in data_files.items()},
            "leakage_screen": fixtures.leakage_report,
        }
    )
    configuration = create_qlora_training_configuration(
        configuration_id=uuid5(_NAMESPACE, f"config:{candidate_id}:{manifest['content_hash']}"),
        candidate_id=candidate_id,
        base_model_repository=candidate.repository_id,
        base_model_revision=candidate.revision,
        tokenizer_repository=candidate.tokenizer_repository_id,
        tokenizer_revision=candidate.tokenizer_revision,
        dataset_reference=DatasetManifestReference(dataset_id, 1, manifest["content_hash"]),
        quantization=QloraQuantizationConfiguration(
            QloraQuantizationType.NF4,
            QloraComputeDtype.BFLOAT16,
            True,
        ),
        adapter=create_lora_adapter_configuration(
            rank=8,
            alpha=16,
            dropout=0.0,
            target_modules=(
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ),
            bias=LoraBiasMode.NONE,
            use_rslora=False,
        ),
        optimization=QloraOptimizationConfiguration(
            max_sequence_length=1536,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=2,
            learning_rate=2e-4,
            weight_decay=0.0,
            warmup_ratio=0.0,
            max_steps=8,
            num_train_epochs=None,
            optimizer=QloraOptimizer.ADAMW_8BIT,
            scheduler=QloraScheduler.LINEAR,
            precision=QloraPrecision.BF16,
            gradient_checkpointing=True,
            gradient_clip_norm=1.0,
            logging_steps=1,
        ),
        checkpoints=QloraCheckpointPolicy(
            save_steps=4,
            evaluation_steps=4,
            save_total_limit=2,
            load_best_model_at_end=False,
            metric_for_best_model=None,
            greater_is_better=None,
            early_stopping_patience=None,
        ),
        seed=20260905,
        created_at=created_at,
    )
    data_files.update(
        {
            "dataset-manifest.json": _json(manifest),
            "configuration.json": _json(configuration.to_snapshot()),
            "reanalysis-source.json": report_raw,
        }
    )
    preparation = _with_hash(
        {
            "schema_version": 1,
            "preparation_id": "ut-evaluator-qlora-smoke-preparation-v1",
            "created_at": created_at.isoformat(),
            "purpose": SMOKE_PURPOSE,
            "status": "PREPARED_NOT_AUTHORIZED",
            "candidate_id": candidate_id,
            "model_selected": False,
            "training_executed": False,
            "network_authorized": False,
            "owner_fixture_review": "PENDING",
            "license_review_status": "PENDING",
            "tokenization_status": "NOT_RUN",
            "runner_compatibility_status": "PENDING_PREFLIGHT",
            "training_authorization": "NOT_GRANTED",
            "configuration_content_hash": configuration.content_hash,
            "dataset_manifest_content_hash": manifest["content_hash"],
            "candidate_matrix_content_hash": matrix.content_hash,
            "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
            "source_report_content_hash": report["content_hash"],
            "source_report_sha256": _sha(report_raw),
            "source_report_validation_scope": "SELF_CONSISTENCY_BINDING_NOT_RAW_BUNDLE_REVALIDATION",
            "package_lock_sha256": report["package_lock_sha256"],
            "environment_sha256": report["environment_sha256"],
            "chat_template_control": candidate.chat_template_control.to_snapshot(),
            "runtime_requirements": smoke_runtime_requirements(),
            "implementation_sha256": {
                name: _sha((Path(__file__).parent / name).read_bytes())
                for name in ("qlora_smoke_fixtures.py", "qlora_smoke_preparation.py")
            },
            "file_sha256": {name: _sha(raw) for name, raw in sorted(data_files.items())},
            "limitation": SMOKE_LIMITATION,
        }
    )
    data_files["preparation.json"] = _json(preparation)
    # Publish a fresh directory only after all pure validation and serialization succeeds.
    # mkdir is exclusive; existing attempts are never cleaned up or overwritten.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".smoke-prepare-",
        dir=destination.parent,
    ) as stage_name:
        stage = Path(stage_name)
        for name, raw in data_files.items():
            (stage / name).write_bytes(raw)
        destination.mkdir(exist_ok=False)
        for name in sorted(data_files):
            os.replace(stage / name, destination / name)
    return destination / "preparation.json"
