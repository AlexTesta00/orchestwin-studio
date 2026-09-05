"""Evidence contracts for local OpenAI-compatible serving of the bounded QLoRA smoke.

The serving probe is deliberately narrower than production deployment. It proves that the
exact S59 smoke adapter can be exposed through OrchesTwin's provider-neutral local
OpenAI-compatible boundary. It does not select a model, validate vLLM, or promote the
eight-step adapter to the final thesis adapter.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.qlora_ablation import (
    ABLATION_POLICY_ID,
    QloraAblationInputs,
    load_ablation_inputs,
)
from orchestwin.training.qlora_smoke_collation import checked_path, read_snapshot

SERVING_POLICY_ID: Final = "qlora-smoke-openai-compatible-serving-v1"
SERVING_ENGINE_ID: Final = "orchestwin-unsloth-peft-http-smoke-v1"
SERVING_RUNTIME_ID: Final = "openai-compatible-local"
SERVING_MODEL_NAME: Final = "ut-evaluator-s59-smoke"
SERVING_ADAPTER_ID: Final = "ut-evaluator-s59-smoke"
MAX_CONCURRENCY: Final = 1
FALLBACK_POLICY: Final = "FORBID"
VLLM_OBSERVATION_STATUS: Final = "DOCUMENTED_NOT_LOCALLY_OBSERVED"


class QloraSmokeServingError(ValueError):
    """Serving evidence is incomplete, inconsistent, or outside the bounded smoke policy."""


@dataclass(frozen=True, slots=True)
class QloraSmokeServingInputs:
    repository: Path
    training_root: Path
    recovery_report_path: Path
    ablation_report_path: Path
    ablation_inputs: QloraAblationInputs
    recovery_report: dict[str, Any]
    ablation_report: dict[str, Any]
    adapter_weight_sha256: str

    @property
    def candidate(self):
        return self.ablation_inputs.candidate

    @property
    def bundle(self):
        return self.ablation_inputs.bundle


def _regular_file(path: Path) -> Path:
    path = checked_path(path)
    if not path.is_file():
        raise QloraSmokeServingError(f"expected regular file: {path.name}")
    return path


def _adapter_weight_digest(inputs: QloraAblationInputs) -> str:
    observations = inputs.bundle.result.get("observations")
    if not isinstance(observations, dict):
        raise QloraSmokeServingError("S59 result is missing observations")
    inventory = observations.get("adapter_files")
    if not isinstance(inventory, list):
        raise QloraSmokeServingError("S59 adapter inventory is missing")
    matches = [
        item
        for item in inventory
        if isinstance(item, dict) and item.get("path") == "adapter_model.safetensors"
    ]
    if len(matches) != 1:
        raise QloraSmokeServingError("S59 adapter must contain exactly one safetensors weight file")
    digest = matches[0].get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise QloraSmokeServingError("S59 adapter weight digest is invalid")
    return digest


def load_serving_inputs(
    repository_root: Path,
    training_root: Path,
    recovery_report_path: Path,
    ablation_report_path: Path,
) -> QloraSmokeServingInputs:
    repository = checked_path(repository_root)
    ablation_inputs = load_ablation_inputs(
        repository,
        training_root,
        recovery_report_path,
    )
    recovery_path = _regular_file(recovery_report_path)
    ablation_path = _regular_file(ablation_report_path)
    recovery = read_snapshot(recovery_path)
    ablation = read_snapshot(ablation_path)

    if any(
        (
            recovery.get("status") != "QLORA_SMOKE_RECOVERY_VERIFIED",
            recovery.get("optimizer_steps_added") != 0,
            recovery.get("verification_training_executed") is not False,
            recovery.get("model_selected") is not False,
            recovery.get("serving_validated") is not False,
        )
    ):
        raise QloraSmokeServingError("S60 recovery evidence is not the expected bounded result")

    if any(
        (
            ablation.get("policy_id") != ABLATION_POLICY_ID,
            ablation.get("report_id") != "user-twin-evaluator-qlora-smoke-ablation-v1",
            ablation.get("identity") != ablation_inputs.identity,
            ablation.get("paired_prompt_count") != 12,
            ablation.get("live_inference_executed") is not True,
            ablation.get("training_executed") is not False,
            ablation.get("network_authorized") is not False,
            ablation.get("selection_status") != "NO_MODEL_SELECTED",
            ablation.get("model_selected") is not False,
            ablation.get("quality_improvement_claimed") is not False,
            ablation.get("real_user_behavior_validated") is not False,
            ablation.get("serving_validated") is not False,
        )
    ):
        raise QloraSmokeServingError("S61 ablation evidence violates the serving preconditions")

    candidate_snapshot = ablation_inputs.candidate.to_snapshot()
    serving = candidate_snapshot.get("serving")
    if not isinstance(serving, dict):
        raise QloraSmokeServingError("frozen candidate has no serving declaration")
    if (
        serving.get("runtime_id") != SERVING_RUNTIME_ID
        or serving.get("runtime_family") != "vllm"
        or serving.get("status") != VLLM_OBSERVATION_STATUS
    ):
        raise QloraSmokeServingError("frozen candidate serving declaration changed")

    return QloraSmokeServingInputs(
        repository=repository,
        training_root=checked_path(training_root),
        recovery_report_path=recovery_path,
        ablation_report_path=ablation_path,
        ablation_inputs=ablation_inputs,
        recovery_report=recovery,
        ablation_report=ablation,
        adapter_weight_sha256=_adapter_weight_digest(ablation_inputs),
    )


def serving_configuration_snapshot(inputs: QloraSmokeServingInputs) -> dict[str, object]:
    """Bind the observed smoke server to exact immutable evidence and explicit limitations."""
    return {
        "policy_id": SERVING_POLICY_ID,
        "engine_id": SERVING_ENGINE_ID,
        "runtime_id": SERVING_RUNTIME_ID,
        "model_name": SERVING_MODEL_NAME,
        "loopback_only": True,
        "offline_model_loading_required": True,
        "max_concurrency": MAX_CONCURRENCY,
        "fallback_policy": FALLBACK_POLICY,
        "structured_response_format": "json_schema",
        "base_model_repository": inputs.candidate.repository_id,
        "base_model_revision": inputs.candidate.revision,
        "tokenizer_revision": inputs.candidate.tokenizer_revision,
        "adapter_id": SERVING_ADAPTER_ID,
        "adapter_weight_sha256": inputs.adapter_weight_sha256,
        "source_training_request_sha256": inputs.bundle.request["request_sha256"],
        "source_recovery_report_content_hash": inputs.recovery_report["content_hash"],
        "source_ablation_report_content_hash": inputs.ablation_report["content_hash"],
        "source_training_global_step": 8,
        "vllm_documented_runtime_family": "vllm",
        "vllm_observation_status": VLLM_OBSERVATION_STATUS,
        "smoke_scope": "EIGHT_STEP_ADAPTER_SERVING_PROBE_ONLY",
    }


def serving_model_identity(inputs: QloraSmokeServingInputs) -> ModelRuntimeIdentity:
    config = serving_configuration_snapshot(inputs)
    return ModelRuntimeIdentity(
        provider_id="orchestwin-local",
        runtime_id=SERVING_RUNTIME_ID,
        base_model_repository=inputs.candidate.repository_id,
        base_model_revision=inputs.candidate.revision,
        tokenizer_revision=inputs.candidate.tokenizer_revision,
        configuration_sha256=snapshot_content_hash(config),
        adapter_id=SERVING_ADAPTER_ID,
        adapter_sha256=inputs.adapter_weight_sha256,
    )


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise QloraSmokeServingError(f"{label} must be an object")
    return value


def build_serving_evidence(
    *,
    inputs: QloraSmokeServingInputs,
    observations: Mapping[str, object],
    created_at: datetime,
) -> dict[str, object]:
    """Create a bounded serving report only after all required observations are present."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise QloraSmokeServingError("created_at must be timezone-aware")

    health = _require_mapping(observations.get("health"), "health observation")
    identity = _require_mapping(observations.get("identity"), "identity observation")
    generation = _require_mapping(
        observations.get("structured_generation"),
        "structured generation observation",
    )
    concurrency = _require_mapping(observations.get("concurrency"), "concurrency observation")
    timeout = _require_mapping(observations.get("timeout"), "timeout observation")
    memory = _require_mapping(observations.get("memory"), "memory observation")
    fallback = _require_mapping(observations.get("fallback"), "fallback observation")

    expected_identity = serving_model_identity(inputs).to_snapshot()
    if health.get("status") != "SERVING":
        raise QloraSmokeServingError("health check did not observe a serving runtime")
    if identity.get("model_identity") != expected_identity:
        raise QloraSmokeServingError("served model identity differs from the exact smoke adapter")
    if generation.get("status") != "SUCCEEDED" or generation.get("schema_valid") is not True:
        raise QloraSmokeServingError("structured generation example did not satisfy the schema")
    if generation.get("actual_identity") != expected_identity:
        raise QloraSmokeServingError("structured generation returned a different model identity")
    if concurrency.get("max_concurrency") != MAX_CONCURRENCY:
        raise QloraSmokeServingError("observed concurrency limit changed")
    if concurrency.get("rate_limit_status_code") != 429:
        raise QloraSmokeServingError("concurrency saturation did not return HTTP 429")
    if timeout.get("loopback_transport_timeout_observed") is not True:
        raise QloraSmokeServingError("timeout behavior was not observed")
    if (
        type(memory.get("model_load_peak_torch_reserved_memory_mib")) is not int
        or type(memory.get("generation_peak_torch_reserved_memory_mib")) is not int
        or memory["model_load_peak_torch_reserved_memory_mib"] <= 0
        or memory["generation_peak_torch_reserved_memory_mib"] <= 0
    ):
        raise QloraSmokeServingError("serving memory evidence is missing")
    if (
        fallback.get("policy") != FALLBACK_POLICY
        or fallback.get("base_fallback_attempted") is not False
        or fallback.get("mismatched_identity_status_code") != 409
        or fallback.get("generation_count_unchanged") is not True
    ):
        raise QloraSmokeServingError("silent base fallback was not demonstrably refused")

    report: dict[str, object] = {
        "schema_version": 1,
        "policy_id": SERVING_POLICY_ID,
        "report_id": "user-twin-evaluator-qlora-smoke-serving-v1",
        "created_at": created_at.isoformat(),
        "configuration": serving_configuration_snapshot(inputs),
        "model_identity": expected_identity,
        "observations": dict(observations),
        "health_check_observed": True,
        "exact_model_adapter_identity_observed": True,
        "structured_generation_observed": True,
        "concurrency_limit_observed": True,
        "timeout_behavior_observed": True,
        "memory_usage_observed": True,
        "fallback_policy_observed": True,
        "local_openai_compatible_serving_validated": True,
        "vllm_serving_validated": False,
        "final_adapter_serving_validated": False,
        "training_executed": False,
        "network_authorized": False,
        "selection_status": "NO_MODEL_SELECTED",
        "model_selected": False,
        "quality_improvement_claimed": False,
        "real_user_behavior_validated": False,
        "methodological_notice": (
            "Local loopback serving evidence for the exact eight-step smoke adapter. "
            "The observed engine is the bounded OrchesTwin Unsloth/PEFT HTTP smoke runtime, "
            "not vLLM. This proves interface/loadability behavior only; it does not select "
            "the base model, validate production concurrency, validate real users, or "
            "promote the smoke adapter to the final thesis adapter."
        ),
    }
    report["content_hash"] = snapshot_content_hash(report)
    return report


def write_serving_snapshot(path: Path, payload: Mapping[str, object]) -> None:
    destination = Path(os.path.abspath(path))
    for component in (*reversed(destination.parents), destination):
        if component.is_symlink():
            raise QloraSmokeServingError("serving output path must not contain symbolic links")
    if destination.exists():
        raise QloraSmokeServingError("serving output must be a new file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json(dict(payload)).encode("utf-8"))
