"""Serving evidence contracts stay exact, loopback-only, and epistemically bounded."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.models.openai_compatible import (
    OpenAICompatibleLocalConfig,
    _request_payload,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmarking import create_benchmark_generation_request
from orchestwin.training.qlora_smoke_serving import (
    FALLBACK_POLICY,
    MAX_CONCURRENCY,
    SERVING_ENGINE_ID,
    SERVING_MODEL_NAME,
    SERVING_POLICY_ID,
    VLLM_OBSERVATION_STATUS,
    QloraSmokeServingError,
    build_serving_evidence,
    serving_configuration_snapshot,
)

ROOT = Path(__file__).resolve().parents[4]


def _fake_inputs():
    candidate = SimpleNamespace(
        repository_id="Qwen/Qwen3-4B-Instruct-2507",
        revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        tokenizer_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
    )
    bundle = SimpleNamespace(
        request={
            "request_sha256": "1" * 64,
        }
    )
    return SimpleNamespace(
        candidate=candidate,
        bundle=bundle,
        adapter_weight_sha256="2" * 64,
        recovery_report={"content_hash": "3" * 64},
        ablation_report={"content_hash": "4" * 64},
    )


def _identity_snapshot(inputs):
    config = serving_configuration_snapshot(inputs)
    return ModelRuntimeIdentity(
        provider_id="orchestwin-local",
        runtime_id="openai-compatible-local",
        base_model_repository=inputs.candidate.repository_id,
        base_model_revision=inputs.candidate.revision,
        tokenizer_revision=inputs.candidate.tokenizer_revision,
        configuration_sha256=__import__(
            "orchestwin.projects.requirements_primitives",
            fromlist=["snapshot_content_hash"],
        ).snapshot_content_hash(config),
        adapter_id="ut-evaluator-s59-smoke",
        adapter_sha256=inputs.adapter_weight_sha256,
    ).to_snapshot()


def _observations(inputs):
    identity = _identity_snapshot(inputs)
    return {
        "health": {
            "status": "SERVING",
            "engine_id": SERVING_ENGINE_ID,
            "loopback_only": True,
            "network_authorized": False,
        },
        "identity": {
            "model_name": SERVING_MODEL_NAME,
            "model_identity": identity,
        },
        "structured_generation": {
            "status": "SUCCEEDED",
            "schema_valid": True,
            "actual_identity": identity,
        },
        "concurrency": {
            "max_concurrency": MAX_CONCURRENCY,
            "rate_limit_status_code": 429,
        },
        "timeout": {
            "loopback_transport_timeout_observed": True,
        },
        "memory": {
            "model_load_peak_torch_reserved_memory_mib": 2700,
            "generation_peak_torch_reserved_memory_mib": 3200,
        },
        "fallback": {
            "policy": FALLBACK_POLICY,
            "mismatched_identity_status_code": 409,
            "base_fallback_attempted": False,
            "generation_count_unchanged": True,
        },
    }


def test_serving_configuration_keeps_vllm_unobserved_and_smoke_scope_explicit():
    config = serving_configuration_snapshot(_fake_inputs())
    assert config["policy_id"] == SERVING_POLICY_ID
    assert config["engine_id"] == SERVING_ENGINE_ID
    assert config["runtime_id"] == "openai-compatible-local"
    assert config["max_concurrency"] == 1
    assert config["fallback_policy"] == "FORBID"
    assert config["vllm_documented_runtime_family"] == "vllm"
    assert config["vllm_observation_status"] == VLLM_OBSERVATION_STATUS
    assert config["smoke_scope"] == "EIGHT_STEP_ADAPTER_SERVING_PROBE_ONLY"


def test_serving_report_records_required_evidence_without_selecting_model():
    inputs = _fake_inputs()
    report = build_serving_evidence(
        inputs=inputs,
        observations=_observations(inputs),
        created_at=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert report["local_openai_compatible_serving_validated"] is True
    assert report["vllm_serving_validated"] is False
    assert report["final_adapter_serving_validated"] is False
    assert report["selection_status"] == "NO_MODEL_SELECTED"
    assert report["model_selected"] is False
    assert report["quality_improvement_claimed"] is False
    assert report["real_user_behavior_validated"] is False
    assert report["training_executed"] is False
    assert report["network_authorized"] is False
    assert "not vLLM" in report["methodological_notice"]


def test_serving_report_rejects_missing_fallback_refusal():
    inputs = _fake_inputs()
    observations = _observations(inputs)
    observations["fallback"]["generation_count_unchanged"] = False
    with pytest.raises(QloraSmokeServingError, match="fallback"):
        build_serving_evidence(
            inputs=inputs,
            observations=observations,
            created_at=datetime(2026, 9, 5, tzinfo=UTC),
        )


def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load test module: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _server_module():
    return _load_module_from_path(
        "serving_server_under_test",
        ROOT / "environments/training/serve_qlora_smoke_openai.py",
    )


def _spike_module():
    return _load_module_from_path(
        "serving_spike_under_test",
        ROOT / "environments/training/run_model_spike.py",
    )


def test_server_reconstructs_exact_frozen_prompt_from_real_openai_adapter_payload():
    module = _server_module()
    spike = _spike_module()
    identity = ModelRuntimeIdentity(
        provider_id="orchestwin-local",
        runtime_id="openai-compatible-local",
        base_model_repository="Qwen/Qwen3-4B-Instruct-2507",
        base_model_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        tokenizer_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        configuration_sha256="a" * 64,
        adapter_id="ut-evaluator-s59-smoke",
        adapter_sha256="b" * 64,
    )
    suite = load_frozen_evaluator_benchmark_suite(ROOT)
    task = next(task for task in suite.tasks if task.task_id == "bench-en-002")
    generation_request = create_benchmark_generation_request(
        run_id=UUID("00000000-0000-4000-8000-000000162001"),
        task=task,
        model_identity=identity,
    )
    config = OpenAICompatibleLocalConfig(
        base_url="http://127.0.0.1:8080",
        model_name=SERVING_MODEL_NAME,
        expected_identity=identity,
    )
    payload = _request_payload(config, generation_request)
    state = SimpleNamespace(
        identity=identity,
        spike=spike,
        inputs=SimpleNamespace(
            ablation_inputs=SimpleNamespace(suite=suite),
        ),
    )

    messages, max_tokens, digest = module._validated_model_request(payload, state)

    expected = spike._create_chat_messages(generation_request)
    assert messages == expected
    assert max_tokens == generation_request.max_output_tokens
    assert digest == snapshot_content_hash({"messages": list(expected)})


def test_server_rejects_base_identity_instead_of_silent_fallback():
    module = _server_module()
    adapter_identity = ModelRuntimeIdentity(
        provider_id="orchestwin-local",
        runtime_id="openai-compatible-local",
        base_model_repository="Qwen/Qwen3-4B-Instruct-2507",
        base_model_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        tokenizer_revision="abcc171021d4f320b2e7f47c6f0deca67ded870c",
        configuration_sha256="a" * 64,
        adapter_id="ut-evaluator-s59-smoke",
        adapter_sha256="b" * 64,
    )
    base_identity = ModelRuntimeIdentity(
        provider_id=adapter_identity.provider_id,
        runtime_id=adapter_identity.runtime_id,
        base_model_repository=adapter_identity.base_model_repository,
        base_model_revision=adapter_identity.base_model_revision,
        tokenizer_revision=adapter_identity.tokenizer_revision,
        configuration_sha256=adapter_identity.configuration_sha256,
    )
    payload = {
        "model": SERVING_MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "{}"},
        ],
        "temperature": 0.0,
        "max_tokens": 64,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "test",
                "strict": True,
                "schema": {"type": "object"},
            },
        },
        "metadata": {"expected_model_identity": base_identity.to_snapshot()},
    }
    state = SimpleNamespace(identity=adapter_identity, spike=_spike_module())
    with pytest.raises(module.ServingHttpError) as raised:
        module._validated_model_request(payload, state)
    assert raised.value.status_code == 409
    assert raised.value.code == "ADAPTER_NOT_LOADED"


def test_server_and_verifier_are_offline_training_free_and_loopback_only():
    server = (ROOT / "environments/training/serve_qlora_smoke_openai.py").read_text(
        encoding="utf-8"
    )
    verifier = (ROOT / "environments/training/verify_qlora_smoke_serving.py").read_text(
        encoding="utf-8"
    )

    assert '"local_files_only": True' in server
    assert "is_trainable=False" in server
    assert 'args.host != "127.0.0.1"' in server
    assert "BoundedSemaphore(MAX_CONCURRENCY)" in server
    assert "_frozen_benchmark_metadata(" in server
    assert "create_benchmark_generation_request(" in server
    assert "sys.modules[spec.name] = module" in server
    assert "sys.modules.pop(spec.name, None)" in server
    assert 'os.environ.get(TRAINING_GATE) == "1"' in server

    assert "environment.pop(TRAINING_GATE, None)" in verifier
    assert 'environment.pop("ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK", None)' in verifier
    assert '"--allow-diagnostics"' in verifier
    assert "OpenAICompatibleLocalStructuredAdapter" in verifier
    assert "score_benchmark_result" in verifier
