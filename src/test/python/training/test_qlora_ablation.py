"""The smoke ablation must be paired, frozen, descriptive, and training-free."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.training.benchmark_measurement_v2 import summarize_measurements_v2
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmarking import create_benchmark_generation_request
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.qlora_ablation import (
    ABLATION_POLICY_ID,
    ADAPTER_VARIANT,
    BASE_VARIANT,
    EXPECTED_GENERATION,
    QloraAblationError,
    build_ablation_report,
    descriptive_comparison,
    validate_worker_pair,
    verify_worker_artifacts,
)

ROOT = Path(__file__).resolve().parents[4]


def _ratio(value):
    return {"numerator": 0 if value is None else int(value * 10), "denominator": 10, "value": value}


def summary(*, schema=0.5, unsupported=0.25):
    return {
        "expected_task_count": 12,
        "observed_task_count": 12,
        "successful_generation_count": 12,
        "failed_generation_count": 0,
        "unobserved_generation_count": 0,
        "json_object_valid_count": 10,
        "json_schema_valid_count": int(schema * 12),
        "schema_evaluated_task_count": 10,
        "semantic_evaluated_task_count": int(schema * 12),
        "length_terminated_count": 1,
        "rates": {
            "generation_success_given_observed": _ratio(1.0),
            "json_object_valid_given_generation": _ratio(10 / 12),
            "json_schema_valid_given_generation": _ratio(schema),
            "json_schema_valid_given_json_object": _ratio(schema),
        },
        "protocol_checks": {
            "expected_finding_count": _ratio(0.8),
            "unique_finding_ids": _ratio(1.0),
            "nonempty_text": _ratio(1.0),
            "abstention_shape": _ratio(1.0),
            "abstention_matches_label": _ratio(0.5),
        },
        "abstention_confusion": {
            "observed_decisions": 12,
            "true_positive": 1,
            "false_positive": 1,
            "false_negative": 1,
            "true_negative": 9,
            "precision": _ratio(0.5),
            "recall": _ratio(0.5),
        },
        "semantic_metrics": {
            "evidence_reference_precision": _ratio(0.9),
            "unsupported_finding_heuristic_rate": _ratio(unsupported),
            "human_validation_false_rate": _ratio(0.1),
            "required_reference_recall": _ratio(0.8),
            "role_term_recall": _ratio(0.9),
            "criterion_jaccard": _ratio(0.7),
            "severity_jaccard": _ratio(0.6),
        },
    }


def test_frozen_ablation_generation_and_benchmark_identity():
    matrix = load_frozen_model_candidate_matrix(ROOT)
    suite = load_frozen_evaluator_benchmark_suite(ROOT)
    assert matrix.generation.to_snapshot() == EXPECTED_GENERATION
    assert len(suite.tasks) == 12
    assert [task.language.value for task in suite.tasks].count("en") == 6
    assert [task.language.value for task in suite.tasks].count("it") == 6


def spike_module():
    path = ROOT / "environments/training/run_model_spike.py"
    spec = importlib.util.spec_from_file_location("ablation_test_spike_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_base_and_adapter_use_identical_model_visible_prompts():
    suite = load_frozen_evaluator_benchmark_suite(ROOT)
    task = suite.tasks[0]
    spike = spike_module()

    base_identity = ModelRuntimeIdentity(
        provider_id="huggingface-local",
        runtime_id="base-test",
        base_model_repository="Qwen/Qwen3-4B-Instruct-2507",
        base_model_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        tokenizer_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        configuration_sha256="a" * 64,
    )
    adapter_identity = ModelRuntimeIdentity(
        provider_id="huggingface-local",
        runtime_id="adapter-test",
        base_model_repository="Qwen/Qwen3-4B-Instruct-2507",
        base_model_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        tokenizer_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        configuration_sha256="b" * 64,
    )
    base = create_benchmark_generation_request(
        run_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"),
        task=task,
        model_identity=base_identity,
    )
    adapter = create_benchmark_generation_request(
        run_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000002"),
        task=task,
        model_identity=adapter_identity,
    )
    assert spike._create_chat_messages(base) == spike._create_chat_messages(adapter)


def test_descriptive_comparison_never_turns_delta_into_a_winner():
    compared = descriptive_comparison(
        summary(schema=0.5, unsupported=0.4),
        summary(schema=0.75, unsupported=0.2),
    )
    schema = compared["rates.json_schema_valid_given_generation"]
    unsupported = compared["semantic_metrics.unsupported_finding_heuristic_rate"]
    assert schema == {
        "base": 0.5,
        "adapter": 0.75,
        "adapter_minus_base": 0.25,
        "interpretation": "DESCRIPTIVE_ONLY",
    }
    assert unsupported == {
        "base": 0.4,
        "adapter": 0.2,
        "adapter_minus_base": -0.2,
        "interpretation": "DESCRIPTIVE_ONLY",
    }


def test_descriptive_comparison_preserves_missing_denominators():
    base = summary()
    adapter = summary()
    base["semantic_metrics"]["role_term_recall"] = {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }
    compared = descriptive_comparison(base, adapter)
    assert compared["semantic_metrics.role_term_recall"] == {
        "base": None,
        "adapter": 0.9,
        "adapter_minus_base": None,
        "interpretation": "DESCRIPTIVE_ONLY",
    }


def _fake_inputs():
    tasks = tuple(
        SimpleNamespace(task_id=f"task-{index:02d}", content_hash=f"{index:064x}")
        for index in range(12)
    )
    return SimpleNamespace(
        identity={"frozen": True},
        suite=SimpleNamespace(tasks=tasks),
    )


def _worker_report(variant, *, prompt_suffix=""):
    tasks = [
        {
            "task_id": f"task-{index:02d}",
            "task_content_hash": f"{index:064x}",
            "repetition": 1,
            "messages_sha256": f"{index:063x}{prompt_suffix or '0'}",
            "prompt_version_ref": "user-twin-evaluator-v1",
            "output_schema_content_hash": "9a8615d2579317c27fc4186e00ec45887ac3b8be5d14787dadfa0a75f234f40a",
        }
        for index in range(12)
    ]
    return {
        "policy_id": ABLATION_POLICY_ID,
        "variant": variant,
        "status": "COMPLETED",
        "identity": {"frozen": True},
        "training_executed": False,
        "network_authorized": False,
        "model_selected": False,
        "task_count": 12,
        "tasks": tasks,
        "summary": summary(),
        "resource_summary": {
            "model_load_duration_milliseconds": 1,
            "model_load_peak_torch_reserved_memory_mib": 100,
            "generation_total_latency_milliseconds": 12,
            "generation_mean_latency_milliseconds": 1.0,
            "generation_max_peak_torch_reserved_memory_mib": 110,
            "observed_generation_count": 12,
        },
        "content_hash": ("a" if variant == BASE_VARIANT else "b") * 64,
    }


def test_pair_validation_rejects_prompt_drift():
    inputs = _fake_inputs()
    base = _worker_report(BASE_VARIANT)
    adapter = _worker_report(ADAPTER_VARIANT)
    validate_worker_pair(inputs, base, adapter)

    adapter["tasks"][3]["messages_sha256"] = "f" * 64
    with pytest.raises(QloraAblationError, match="paired prompt contract"):
        validate_worker_pair(inputs, base, adapter)


def test_report_keeps_epistemic_and_selection_boundaries():
    inputs = _fake_inputs()
    report = build_ablation_report(
        inputs=inputs,
        base=_worker_report(BASE_VARIANT),
        adapter=_worker_report(ADAPTER_VARIANT),
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert report["selection_status"] == "NO_MODEL_SELECTED"
    assert report["model_selected"] is False
    assert report["quality_comparison_executed"] is True
    assert report["quality_improvement_claimed"] is False
    assert report["real_user_behavior_validated"] is False
    assert report["serving_validated"] is False
    assert report["expert_pairwise_evaluation_executed"] is False
    assert "not empirical target-user validation" in report["methodological_notice"]


def runner_source():
    return (ROOT / "environments/training/run_qlora_ablation.py").read_text(encoding="utf-8")


def test_live_runner_reuses_frozen_spike_prompt_and_generation_contracts():
    source = runner_source()
    assert "spike._create_chat_messages(generation_request)" in source
    assert "spike._prepare_inputs(" in source
    assert "spike._generated_sequences(generated)" in source
    assert 'max_new_tokens=generation["max_output_tokens"]' in source
    assert "do_sample=False" in source
    assert "use_cache=True" in source


def test_live_runner_is_offline_and_never_enables_training_gate():
    source = runner_source()
    assert "environment.pop(TRAINING_GATE, None)" in source
    assert 'ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING", "1"' not in source
    assert '"HF_HUB_OFFLINE": "1"' in source
    assert '"TRANSFORMERS_OFFLINE": "1"' in source
    assert "is_trainable=False" in source


def test_measurement_summary_contract_still_accepts_failed_observation_without_imputation():
    record = {
        "generation_succeeded": False,
        "finish_reason": None,
        "measurement": {
            "json_object_valid": None,
            "json_schema_valid": None,
            "protocol_checks": {
                "expected_finding_count": None,
                "unique_finding_ids": None,
                "nonempty_text": None,
                "abstention_shape": None,
                "abstention_matches_label": None,
            },
            "observed_abstained": None,
            "expected_abstention": True,
            "semantic_metrics": None,
        },
    }
    result = summarize_measurements_v2([record])
    assert result["failed_generation_count"] == 1
    assert result["rates"]["json_schema_valid_given_generation"]["value"] is None


def test_worker_artifacts_are_hash_bound_and_no_extra_files_are_accepted(tmp_path):
    import hashlib

    root = tmp_path / "worker"
    prompts = root / "prompts"
    raw = root / "raw"
    prompts.mkdir(parents=True)
    raw.mkdir()

    prompt_payload = {
        "messages_sha256": "a" * 64,
        "prompt_version_ref": "ut-evaluator-benchmark-v1",
        "output_schema_content_hash": "9a8615d2579317c27fc4186e00ec45887ac3b8be5d14787dadfa0a75f234f40a",
    }
    from orchestwin.projects.requirements_primitives import canonical_json

    prompt_bytes = canonical_json(prompt_payload).encode("utf-8")
    prompt = prompts / "task.json"
    prompt.write_bytes(prompt_bytes)
    raw_file = raw / "task.txt"
    raw_file.write_text("{}", encoding="utf-8")
    (root / "worker-report.json").write_text("{}", encoding="utf-8")

    report = {
        "tasks": [
            {
                "prompt_reference": "prompts/task.json",
                "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
                "raw_output_reference": "raw/task.txt",
                "raw_output_sha256": hashlib.sha256(raw_file.read_bytes()).hexdigest(),
                "messages_sha256": "a" * 64,
                "prompt_version_ref": "ut-evaluator-benchmark-v1",
                "output_schema_content_hash": "9a8615d2579317c27fc4186e00ec45887ac3b8be5d14787dadfa0a75f234f40a",
            }
        ]
    }
    verify_worker_artifacts(root, report)

    (root / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(QloraAblationError, match="unrecorded"):
        verify_worker_artifacts(root, report)
