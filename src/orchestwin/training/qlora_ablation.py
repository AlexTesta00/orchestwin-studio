"""Evidence-bound base-versus-adapter comparison for the bounded QLoRA smoke.

The comparison is descriptive only. It uses the repository-owned frozen benchmark and
measurement-v2 policy, never selects a model, and never treats synthetic findings as
empirical user evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import measurement_policy_snapshot
from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_SHA256,
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.qlora_smoke_collation import checked_path, read_snapshot
from orchestwin.training.qlora_smoke_recovery import (
    RECOVERY_POLICY_ID,
    RecoveryBundle,
    load_recovery_bundle,
    recovery_identity,
)

ABLATION_POLICY_ID: Final = "qlora-smoke-base-adapter-ablation-v1"
BASE_VARIANT: Final = "BASE"
ADAPTER_VARIANT: Final = "ADAPTER"
VARIANTS: Final = (BASE_VARIANT, ADAPTER_VARIANT)

EXPECTED_GENERATION: Final = {
    "max_sequence_length": 4096,
    "max_output_tokens": 1024,
    "repetitions": 1,
    "seed": 20260904,
    "load_in_4bit": True,
    "trust_remote_code": False,
}

_COMPARISON_PATHS: Final = (
    ("rates", "generation_success_given_observed"),
    ("rates", "json_object_valid_given_generation"),
    ("rates", "json_schema_valid_given_generation"),
    ("rates", "json_schema_valid_given_json_object"),
    ("protocol_checks", "expected_finding_count"),
    ("protocol_checks", "unique_finding_ids"),
    ("protocol_checks", "nonempty_text"),
    ("protocol_checks", "abstention_shape"),
    ("protocol_checks", "abstention_matches_label"),
    ("abstention_confusion", "precision"),
    ("abstention_confusion", "recall"),
    ("semantic_metrics", "evidence_reference_precision"),
    ("semantic_metrics", "unsupported_finding_heuristic_rate"),
    ("semantic_metrics", "human_validation_false_rate"),
    ("semantic_metrics", "required_reference_recall"),
    ("semantic_metrics", "role_term_recall"),
    ("semantic_metrics", "criterion_jaccard"),
    ("semantic_metrics", "severity_jaccard"),
)


class QloraAblationError(ValueError):
    """Ablation evidence is incomplete, inconsistent, or outside the frozen policy."""


@dataclass(frozen=True, slots=True)
class QloraAblationInputs:
    repository: Path
    training_root: Path
    recovery_report_path: Path
    bundle: RecoveryBundle
    recovery_report: dict[str, Any]
    suite: Any
    matrix: Any
    candidate: Any

    @property
    def identity(self) -> dict[str, object]:
        return {
            "training": recovery_identity(self.bundle),
            "recovery_report_content_hash": self.recovery_report["content_hash"],
            "benchmark_suite_sha256": FROZEN_BENCHMARK_SUITE_SHA256,
            "benchmark_suite_content_hash": FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
            "candidate_matrix_sha256": FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
            "candidate_matrix_content_hash": FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
            "candidate_id": self.candidate.candidate_id,
            "base_model_repository": self.candidate.repository_id,
            "base_model_revision": self.candidate.revision,
            "tokenizer_repository": self.candidate.tokenizer_repository_id,
            "tokenizer_revision": self.candidate.tokenizer_revision,
            "generation": EXPECTED_GENERATION,
        }


def _regular_file(path: Path) -> Path:
    path = checked_path(path)
    if not path.is_file():
        raise QloraAblationError(f"expected regular file: {path.name}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular_file(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_reference(root: Path, reference: object) -> Path:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise QloraAblationError("worker artifact reference must be relative POSIX syntax")
    pure = Path(*reference.split("/"))
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in reference.split("/")):
        raise QloraAblationError("worker artifact reference is unsafe")
    path = checked_path(root / pure)
    try:
        path.relative_to(root)
    except ValueError as error:
        raise QloraAblationError("worker artifact escaped its root") from error
    return _regular_file(path)


def verify_worker_artifacts(
    worker_root: Path,
    report: Mapping[str, object],
) -> None:
    """Verify paired prompt/raw bytes before accepting a worker report."""
    root = checked_path(worker_root)
    if not root.is_dir():
        raise QloraAblationError("worker artifact root must be a directory")
    tasks = report.get("tasks")
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
        raise QloraAblationError("worker report tasks must be a sequence")
    expected_files = {"worker-report.json"}
    for item in tasks:
        if not isinstance(item, Mapping):
            raise QloraAblationError("worker task row must be an object")
        prompt = _artifact_reference(root, item.get("prompt_reference"))
        raw = _artifact_reference(root, item.get("raw_output_reference"))
        if _sha256_file(prompt) != item.get("prompt_sha256"):
            raise QloraAblationError("worker prompt bytes changed")
        if _sha256_file(raw) != item.get("raw_output_sha256"):
            raise QloraAblationError("worker raw output bytes changed")
        try:
            payload = json.loads(prompt.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise QloraAblationError("worker prompt is not valid UTF-8 JSON") from error
        if (
            not isinstance(payload, dict)
            or canonical_json(payload).encode("utf-8") != prompt.read_bytes()
            or payload.get("messages_sha256") != item.get("messages_sha256")
            or payload.get("prompt_version_ref") != item.get("prompt_version_ref")
            or payload.get("output_schema_content_hash") != item.get("output_schema_content_hash")
        ):
            raise QloraAblationError("worker prompt content differs from its report")
        expected_files.add(prompt.relative_to(root).as_posix())
        expected_files.add(raw.relative_to(root).as_posix())

    actual_files = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise QloraAblationError("worker artifact tree contains a symbolic link")
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
    if actual_files != expected_files:
        raise QloraAblationError("worker artifact tree contains missing or unrecorded files")


def load_ablation_inputs(
    repository_root: Path,
    training_root: Path,
    recovery_report_path: Path,
) -> QloraAblationInputs:
    repository = checked_path(repository_root)
    bundle = load_recovery_bundle(repository, training_root)
    recovery_path = _regular_file(recovery_report_path)
    recovery = read_snapshot(recovery_path)

    if any(
        (
            recovery.get("policy_id") != RECOVERY_POLICY_ID,
            recovery.get("status") != "QLORA_SMOKE_RECOVERY_VERIFIED",
            recovery.get("identity") != recovery_identity(bundle),
            recovery.get("fresh_processes_used") != 2,
            recovery.get("verification_training_executed") is not False,
            recovery.get("optimizer_steps_added") != 0,
            recovery.get("source_training_global_step") != 8,
            recovery.get("network_authorized") is not False,
            recovery.get("model_selected") is not False,
            recovery.get("quality_improvement_measured") is not False,
            recovery.get("serving_validated") is not False,
        )
    ):
        raise QloraAblationError("recovery report does not attest the completed bounded smoke")

    suite = load_frozen_evaluator_benchmark_suite(repository)
    matrix = load_frozen_model_candidate_matrix(repository)
    try:
        candidate = matrix.candidate(bundle.request["candidate_id"])
    except StopIteration as error:
        raise QloraAblationError("training candidate is absent from the frozen matrix") from error

    if (
        candidate.repository_id != bundle.request["base_model_repository"]
        or candidate.revision != bundle.request["base_model_revision"]
        or candidate.tokenizer_repository_id != bundle.request["base_model_repository"]
        or candidate.tokenizer_revision != bundle.request["base_model_revision"]
    ):
        raise QloraAblationError("training identity differs from the frozen candidate")

    if matrix.generation.to_snapshot() != EXPECTED_GENERATION:
        raise QloraAblationError("frozen generation settings changed")
    if suite.content_hash != FROZEN_BENCHMARK_SUITE_CONTENT_HASH or len(suite.tasks) != 12:
        raise QloraAblationError("frozen benchmark identity changed")

    languages = [task.language.value for task in suite.tasks]
    if languages.count("en") != 6 or languages.count("it") != 6:
        raise QloraAblationError("frozen benchmark bilingual balance changed")

    return QloraAblationInputs(
        repository=repository,
        training_root=checked_path(training_root),
        recovery_report_path=recovery_path,
        bundle=bundle,
        recovery_report=recovery,
        suite=suite,
        matrix=matrix,
        candidate=candidate,
    )


def _ratio_value(summary: Mapping[str, object], path: tuple[str, str]) -> float | None:
    parent = summary.get(path[0])
    if not isinstance(parent, Mapping):
        raise QloraAblationError(f"summary is missing {path[0]}")
    ratio = parent.get(path[1])
    if not isinstance(ratio, Mapping):
        raise QloraAblationError(f"summary is missing {'/'.join(path)}")
    value = ratio.get("value")
    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise QloraAblationError(f"summary ratio {'/'.join(path)} has invalid value")
    return None if value is None else float(value)


def descriptive_comparison(
    base_summary: Mapping[str, object],
    adapter_summary: Mapping[str, object],
) -> dict[str, object]:
    """Compare observed values without inventing denominators or declaring a winner."""
    metrics: dict[str, object] = {}
    for path in _COMPARISON_PATHS:
        base = _ratio_value(base_summary, path)
        adapter = _ratio_value(adapter_summary, path)
        key = ".".join(path)
        metrics[key] = {
            "base": base,
            "adapter": adapter,
            "adapter_minus_base": (
                None if base is None or adapter is None else round(adapter - base, 6)
            ),
            "interpretation": "DESCRIPTIVE_ONLY",
        }
    for key in (
        "successful_generation_count",
        "failed_generation_count",
        "json_object_valid_count",
        "json_schema_valid_count",
        "semantic_evaluated_task_count",
        "length_terminated_count",
    ):
        base = base_summary.get(key)
        adapter = adapter_summary.get(key)
        if type(base) is not int or type(adapter) is not int:
            raise QloraAblationError(f"summary count is invalid: {key}")
        metrics[f"count.{key}"] = {
            "base": base,
            "adapter": adapter,
            "adapter_minus_base": adapter - base,
            "interpretation": "DESCRIPTIVE_ONLY",
        }
    return metrics


def _task_index(report: Mapping[str, object]) -> dict[tuple[str, int], Mapping[str, object]]:
    tasks = report.get("tasks")
    if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
        raise QloraAblationError("worker report tasks must be a sequence")
    indexed: dict[tuple[str, int], Mapping[str, object]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            raise QloraAblationError("worker task row must be an object")
        task_id = task.get("task_id")
        repetition = task.get("repetition")
        if not isinstance(task_id, str) or type(repetition) is not int:
            raise QloraAblationError("worker task identity is invalid")
        key = (task_id, repetition)
        if key in indexed:
            raise QloraAblationError("duplicate worker task observation")
        indexed[key] = task
    return indexed


def validate_worker_pair(
    inputs: QloraAblationInputs,
    base: Mapping[str, object],
    adapter: Mapping[str, object],
) -> None:
    expected_identity = inputs.identity
    for variant, report in ((BASE_VARIANT, base), (ADAPTER_VARIANT, adapter)):
        if any(
            (
                report.get("policy_id") != ABLATION_POLICY_ID,
                report.get("variant") != variant,
                report.get("status") != "COMPLETED",
                report.get("identity") != expected_identity,
                report.get("training_executed") is not False,
                report.get("network_authorized") is not False,
                report.get("model_selected") is not False,
                report.get("task_count") != 12,
            )
        ):
            raise QloraAblationError(f"{variant} worker report violates the paired policy")
        summary = report.get("summary")
        resources = report.get("resource_summary")
        if not isinstance(summary, Mapping):
            raise QloraAblationError(f"{variant} worker report is missing a summary")
        if not isinstance(resources, Mapping):
            raise QloraAblationError(f"{variant} worker report is missing resource evidence")
        if (
            summary.get("expected_task_count") != 12
            or summary.get("successful_generation_count") != 12
            or summary.get("failed_generation_count") != 0
            or summary.get("unobserved_generation_count") != 0
        ):
            raise QloraAblationError(f"{variant} worker did not complete all 12 generations")

    base_tasks = _task_index(base)
    adapter_tasks = _task_index(adapter)
    expected_keys = {(task.task_id, 1) for task in inputs.suite.tasks}
    if set(base_tasks) != expected_keys or set(adapter_tasks) != expected_keys:
        raise QloraAblationError("worker task sets differ from the frozen benchmark")

    for key in sorted(expected_keys):
        left = base_tasks[key]
        right = adapter_tasks[key]
        if (
            left.get("task_content_hash") != right.get("task_content_hash")
            or left.get("messages_sha256") != right.get("messages_sha256")
            or left.get("prompt_version_ref") != right.get("prompt_version_ref")
            or left.get("output_schema_content_hash") != right.get("output_schema_content_hash")
        ):
            raise QloraAblationError(f"paired prompt contract differs for task {key[0]}")


def build_ablation_report(
    *,
    inputs: QloraAblationInputs,
    base: Mapping[str, object],
    adapter: Mapping[str, object],
    created_at: datetime,
) -> dict[str, object]:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise QloraAblationError("created_at must be timezone-aware")
    validate_worker_pair(inputs, base, adapter)

    base_summary = base["summary"]
    adapter_summary = adapter["summary"]
    assert isinstance(base_summary, Mapping)
    assert isinstance(adapter_summary, Mapping)

    report: dict[str, object] = {
        "schema_version": 1,
        "policy_id": ABLATION_POLICY_ID,
        "report_id": "user-twin-evaluator-qlora-smoke-ablation-v1",
        "created_at": created_at.isoformat(),
        "identity": inputs.identity,
        "measurement_policy": measurement_policy_snapshot(),
        "base_report_content_hash": base["content_hash"],
        "adapter_report_content_hash": adapter["content_hash"],
        "base_summary": dict(base_summary),
        "adapter_summary": dict(adapter_summary),
        "base_resource_summary": dict(base["resource_summary"]),
        "adapter_resource_summary": dict(adapter["resource_summary"]),
        "descriptive_comparison": descriptive_comparison(base_summary, adapter_summary),
        "paired_prompt_count": 12,
        "live_inference_executed": True,
        "training_executed": False,
        "network_authorized": False,
        "selection_status": "NO_MODEL_SELECTED",
        "model_selected": False,
        "quality_comparison_executed": True,
        "quality_improvement_claimed": False,
        "real_user_behavior_validated": False,
        "serving_validated": False,
        "expert_pairwise_evaluation_executed": False,
        "methodological_notice": (
            "Technical smoke ablation on the frozen synthetic evaluator benchmark. "
            "Adapter-minus-base values are descriptive observations, not causal evidence, "
            "not expert preference, and not empirical target-user validation. "
            "This eight-step smoke adapter is not the final thesis adapter."
        ),
    }
    report["content_hash"] = snapshot_content_hash(report)
    return report


def write_ablation_report(path: Path, report: Mapping[str, object]) -> None:
    destination = Path(os.path.abspath(path))
    for component in (*reversed(destination.parents), destination):
        if component.is_symlink():
            raise QloraAblationError("ablation output path must not contain symbolic links")
    if destination.exists():
        raise QloraAblationError("ablation output must be a new file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json(dict(report)).encode("utf-8"))
