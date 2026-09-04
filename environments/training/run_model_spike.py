#!/usr/bin/env python3
"""Execute one evidence-bound local model spike against the frozen evaluator suite."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid5

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
_SOURCE_ROOT: Final = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.models.structured_generation import (  # noqa: E402
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
    StructuredGenerationUsage,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)
from orchestwin.training.benchmark_suite_files import (  # noqa: E402
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_PATH,
    FROZEN_BENCHMARK_SUITE_SHA256,
    benchmark_artifact_sha256,
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.benchmarking import (  # noqa: E402
    EvaluatorBenchmarkTaskScore,
    aggregate_benchmark_metrics,
    create_benchmark_generation_request,
    score_benchmark_result,
)
from orchestwin.training.environment_evidence import (  # noqa: E402
    InferenceMeasurementStatus,
    create_inference_resource_measurement,
    summarize_inference_resources,
)

MODEL_SPIKE_PROCESS_SCHEMA_VERSION: Final = 1
EXIT_MISSING_DEPENDENCY: Final = 20
EXIT_GPU_UNAVAILABLE: Final = 21
EXIT_INVALID_INPUT: Final = 22
EXIT_OUT_OF_MEMORY: Final = 23
EXIT_INTERRUPTED: Final = 24
EXIT_MODEL_LOAD_FAILED: Final = 25
EXIT_IDENTITY_MISMATCH: Final = 26
EXIT_PARTIAL_RESULT: Final = 27

_MAX_REQUEST_BYTES: Final = 1_000_000
_MAX_RESULT_BYTES: Final = 16_000_000
_MAX_RAW_OUTPUT_BYTES: Final = 2_000_000
_MAX_FAILURE_LENGTH: Final = 2_000
_MAX_SEQUENCE_LENGTH: Final = 32_768
_MAX_OUTPUT_TOKENS: Final = 2_048
_MAX_REPETITIONS: Final = 5
_MODEL_SPIKE_NETWORK_GATE: Final = "ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK"
_CANDIDATE_ID_PATTERN: Final = re.compile(r"model-candidate-[a-z0-9][a-z0-9-]{2,95}")
_REPOSITORY_PATTERN: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
)
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40,64}")
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_TASK_MEASUREMENT_NAMESPACE: Final = UUID("2f5c9f27-1e42-4858-bad8-57bcd290f4cb")

_REQUEST_KEYS: Final = {
    "schema_version",
    "run_id",
    "candidate_id",
    "model_repository",
    "model_revision",
    "tokenizer_repository",
    "tokenizer_revision",
    "model_card_sha256",
    "license_evidence_sha256",
    "benchmark_suite_sha256",
    "benchmark_suite_content_hash",
    "package_lock_sha256",
    "environment_sha256",
    "generation",
    "requested_at",
    "request_sha256",
}
_GENERATION_KEYS: Final = {
    "max_sequence_length",
    "max_output_tokens",
    "repetitions",
    "seed",
    "load_in_4bit",
    "trust_remote_code",
}
_FORBIDDEN_PROMPT_LABELS: Final = {
    "expected",
    "expected_criteria",
    "expected_severities",
    "forbidden_claim_fragments",
    "maximum_findings",
    "minimum_findings",
    "required_evidence_refs",
    "required_role_terms",
    "should_abstain",
}


class ModelSpikeInputError(ValueError):
    """Raised when a live model-spike request or local evidence artifact is invalid."""


class ModelSpikeIdentityError(RuntimeError):
    """Raised when the loaded model does not match the exact requested revision."""


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an exact-revision Unsloth inference spike over the frozen bilingual "
            "User Twin evaluator benchmark. The default is offline; set "
            f"{_MODEL_SPIKE_NETWORK_GATE}=1 only for an authorized model download."
        )
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request_sha256(payload: Mapping[str, object]) -> str:
    request_without_hash = dict(payload)
    request_without_hash.pop("request_sha256", None)
    return snapshot_content_hash(request_without_hash)


def _result_sha256(payload: Mapping[str, object]) -> str:
    result_without_hash = dict(payload)
    result_without_hash.pop("result_sha256", None)
    return snapshot_content_hash(result_without_hash)


def _read_json_object(path: Path, *, label: str, maximum_bytes: int) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeInputError(f"{label} must identify a regular file")
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise ModelSpikeInputError(f"{label} exceeds the configured size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeInputError(f"{label} must contain UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSpikeInputError(f"{label} must contain a JSON object")
    return payload


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ModelSpikeInputError(f"{label} fields do not match schema version 1")


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSpikeInputError(f"{key} must be a normalized string")
    return value


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelSpikeInputError(f"{key} must be an integer")
    return value


def _required_boolean(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ModelSpikeInputError(f"{key} must be a boolean")
    return value


def _require_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ModelSpikeInputError(f"{label} must use lowercase SHA-256")


def _require_revision(value: str, *, label: str) -> None:
    if _REVISION_PATTERN.fullmatch(value) is None:
        raise ModelSpikeInputError(f"{label} must be an exact lowercase commit revision")


def _load_request(path: Path) -> dict[str, object]:
    payload = _read_json_object(
        path,
        label="model-spike request",
        maximum_bytes=_MAX_REQUEST_BYTES,
    )
    _require_exact_keys(payload, _REQUEST_KEYS, label="model-spike request")
    if _required_integer(payload, "schema_version") != MODEL_SPIKE_PROCESS_SCHEMA_VERSION:
        raise ModelSpikeInputError("unsupported model-spike request schema version")

    try:
        UUID(_required_string(payload, "run_id"))
    except ValueError as error:
        raise ModelSpikeInputError("model-spike run ID must be a UUID") from error

    candidate_id = _required_string(payload, "candidate_id")
    if _CANDIDATE_ID_PATTERN.fullmatch(candidate_id) is None:
        raise ModelSpikeInputError("candidate_id must use model-candidate-<slug>")

    for key in ("model_repository", "tokenizer_repository"):
        value = _required_string(payload, key)
        if _REPOSITORY_PATTERN.fullmatch(value) is None:
            raise ModelSpikeInputError(f"{key} must use owner/repository syntax")
    for key in ("model_revision", "tokenizer_revision"):
        _require_revision(_required_string(payload, key), label=key)
    for key in (
        "model_card_sha256",
        "license_evidence_sha256",
        "benchmark_suite_sha256",
        "benchmark_suite_content_hash",
        "package_lock_sha256",
        "environment_sha256",
        "request_sha256",
    ):
        _require_sha256(_required_string(payload, key), label=key)

    generation_value = payload.get("generation")
    if not isinstance(generation_value, dict):
        raise ModelSpikeInputError("generation must be a JSON object")
    generation = generation_value
    _require_exact_keys(generation, _GENERATION_KEYS, label="model-spike generation")
    max_sequence_length = _required_integer(generation, "max_sequence_length")
    max_output_tokens = _required_integer(generation, "max_output_tokens")
    repetitions = _required_integer(generation, "repetitions")
    seed = _required_integer(generation, "seed")
    if not 512 <= max_sequence_length <= _MAX_SEQUENCE_LENGTH:
        raise ModelSpikeInputError("max_sequence_length must be between 512 and 32768")
    if not 64 <= max_output_tokens <= _MAX_OUTPUT_TOKENS:
        raise ModelSpikeInputError("max_output_tokens must be between 64 and 2048")
    if max_output_tokens >= max_sequence_length:
        raise ModelSpikeInputError("max_output_tokens must be below max_sequence_length")
    if not 1 <= repetitions <= _MAX_REPETITIONS:
        raise ModelSpikeInputError("repetitions must be between one and five")
    if not 0 <= seed <= 2**32 - 1:
        raise ModelSpikeInputError("seed must be an unsigned 32-bit integer")
    if _required_boolean(generation, "load_in_4bit") is not True:
        raise ModelSpikeInputError("the local spike requires four-bit loading")
    if _required_boolean(generation, "trust_remote_code") is not False:
        raise ModelSpikeInputError("the local spike forbids remote code execution")

    requested_at = _required_string(payload, "requested_at")
    try:
        requested_datetime = datetime.fromisoformat(requested_at)
    except ValueError as error:
        raise ModelSpikeInputError("requested_at must use ISO-8601") from error
    if requested_datetime.tzinfo is None or requested_datetime.utcoffset() is None:
        raise ModelSpikeInputError("requested_at must be timezone-aware")

    expected_hash = _request_sha256(payload)
    if _required_string(payload, "request_sha256") != expected_hash:
        raise ModelSpikeInputError("model-spike request digest is inconsistent")
    if any(key in json.dumps(payload).casefold() for key in ("hf_token", "api_key", "password")):
        raise ModelSpikeInputError("model-spike request must not contain credentials")
    return payload


def _verify_repository_evidence(
    request: Mapping[str, object],
) -> tuple[object, dict[str, object]]:
    suite = load_frozen_evaluator_benchmark_suite(_REPOSITORY_ROOT)
    if _required_string(request, "benchmark_suite_sha256") != FROZEN_BENCHMARK_SUITE_SHA256:
        raise ModelSpikeInputError("request does not reference the frozen benchmark file")
    if (
        _required_string(request, "benchmark_suite_content_hash")
        != FROZEN_BENCHMARK_SUITE_CONTENT_HASH
    ):
        raise ModelSpikeInputError("request does not reference the frozen benchmark content")
    suite_path = _REPOSITORY_ROOT / FROZEN_BENCHMARK_SUITE_PATH
    if benchmark_artifact_sha256(suite_path) != FROZEN_BENCHMARK_SUITE_SHA256:
        raise ModelSpikeInputError("frozen benchmark file changed after request creation")

    lock_path = _REPOSITORY_ROOT / "environments" / "training" / "uv.lock"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ModelSpikeInputError("committed training lock must be a regular file")
    if _sha256_file(lock_path) != _required_string(request, "package_lock_sha256"):
        raise ModelSpikeInputError("training lock digest does not match the request")

    environment_path = (
        _REPOSITORY_ROOT / "environments" / "training" / "artifacts" / "environment.json"
    )
    environment = _read_json_object(
        environment_path,
        label="training environment record",
        maximum_bytes=_MAX_REQUEST_BYTES,
    )
    if _sha256_file(environment_path) != _required_string(request, "environment_sha256"):
        raise ModelSpikeInputError("training environment digest does not match the request")
    if environment.get("complete") is not True:
        raise ModelSpikeInputError("training environment record must be complete")
    if environment.get("uv_lock_sha256") != request.get("package_lock_sha256"):
        raise ModelSpikeInputError("training environment references a different package lock")
    gpu = environment.get("gpu")
    if not isinstance(gpu, dict) or gpu.get("status") != "OBSERVED":
        raise ModelSpikeInputError("training environment does not contain observed GPU evidence")
    toolchain = environment.get("build_toolchain")
    if not isinstance(toolchain, dict) or toolchain.get("status") != "OBSERVED":
        raise ModelSpikeInputError("training environment does not contain observed build toolchain")
    return suite, environment


def _supported_kwargs(callable_value: object, values: dict[str, Any]) -> dict[str, Any]:
    parameters = inspect.signature(callable_value).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return values
    return {key: value for key, value in values.items() if key in parameters}


def _load_runtime_dependencies() -> tuple[Any, Any, Any]:
    import torch
    from transformers import AutoTokenizer
    from unsloth import FastLanguageModel

    return torch, AutoTokenizer, FastLanguageModel


def _optional_attribute(value: object, name: str) -> object | None:
    return getattr(value, name, None)


def _observed_revision(value: object) -> str | None:
    config = _optional_attribute(value, "config")
    for candidate in (
        _optional_attribute(value, "_commit_hash"),
        _optional_attribute(config, "_commit_hash") if config is not None else None,
    ):
        if isinstance(candidate, str) and _REVISION_PATTERN.fullmatch(candidate):
            return candidate
    init_kwargs = _optional_attribute(value, "init_kwargs")
    if isinstance(init_kwargs, dict):
        candidate = init_kwargs.get("_commit_hash")
        if isinstance(candidate, str) and _REVISION_PATTERN.fullmatch(candidate):
            return candidate
    return None


def _load_model(
    request: Mapping[str, object],
    *,
    network_authorized: bool,
) -> tuple[Any, Any, Any, dict[str, object]]:
    torch, AutoTokenizer, FastLanguageModel = _load_runtime_dependencies()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable to the isolated model-spike process")

    generation = request["generation"]
    assert isinstance(generation, dict)
    torch.manual_seed(_required_integer(generation, "seed"))
    torch.cuda.manual_seed_all(_required_integer(generation, "seed"))
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()

    model_values = {
        "model_name": _required_string(request, "model_repository"),
        "revision": _required_string(request, "model_revision"),
        "max_seq_length": _required_integer(generation, "max_sequence_length"),
        "dtype": None,
        "load_in_4bit": True,
        "trust_remote_code": False,
        "local_files_only": not network_authorized,
    }
    model, bundled_tokenizer = FastLanguageModel.from_pretrained(
        **_supported_kwargs(FastLanguageModel.from_pretrained, model_values)
    )

    tokenizer_repository = _required_string(request, "tokenizer_repository")
    tokenizer_revision = _required_string(request, "tokenizer_revision")
    if tokenizer_repository == _required_string(
        request, "model_repository"
    ) and tokenizer_revision == _required_string(request, "model_revision"):
        tokenizer = bundled_tokenizer
    else:
        tokenizer_values = {
            "pretrained_model_name_or_path": tokenizer_repository,
            "revision": tokenizer_revision,
            "trust_remote_code": False,
            "local_files_only": not network_authorized,
        }
        tokenizer = AutoTokenizer.from_pretrained(
            **_supported_kwargs(AutoTokenizer.from_pretrained, tokenizer_values)
        )

    FastLanguageModel.for_inference(model)
    if _optional_attribute(tokenizer, "chat_template") is None:
        raise ModelSpikeIdentityError("the exact tokenizer revision has no chat template")
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ModelSpikeIdentityError("the tokenizer has neither pad nor EOS token")
        tokenizer.pad_token = tokenizer.eos_token

    torch.cuda.synchronize()
    load_duration = max(0, round((time.perf_counter() - started) * 1000))
    load_peak = round(torch.cuda.max_memory_reserved() / (1024 * 1024))
    requested_model_revision = _required_string(request, "model_revision")
    requested_tokenizer_revision = _required_string(request, "tokenizer_revision")
    observed_model_revision = _observed_revision(model)
    observed_tokenizer_revision = _observed_revision(tokenizer)
    if observed_model_revision is not None and observed_model_revision != requested_model_revision:
        raise ModelSpikeIdentityError("loaded model revision differs from the request")
    if (
        observed_tokenizer_revision is not None
        and observed_tokenizer_revision != requested_tokenizer_revision
    ):
        raise ModelSpikeIdentityError("loaded tokenizer revision differs from the request")

    evidence = {
        "requested_model_revision": requested_model_revision,
        "observed_model_revision": observed_model_revision,
        "requested_tokenizer_revision": requested_tokenizer_revision,
        "observed_tokenizer_revision": observed_tokenizer_revision,
        "model_revision_observation": (
            "MODEL_CONFIG_COMMIT_HASH"
            if observed_model_revision is not None
            else "REQUEST_PIN_ONLY"
        ),
        "tokenizer_revision_observation": (
            "TOKENIZER_COMMIT_HASH"
            if observed_tokenizer_revision is not None
            else "REQUEST_PIN_ONLY"
        ),
        "model_load_duration_milliseconds": load_duration,
        "model_load_peak_gpu_memory_mb": load_peak,
    }
    return torch, model, tokenizer, evidence


def _model_identity(request: Mapping[str, object]) -> ModelRuntimeIdentity:
    generation = request["generation"]
    assert isinstance(generation, dict)
    configuration_sha256 = snapshot_content_hash(
        {
            "runtime": "unsloth-direct-inference-v1",
            "generation": generation,
            "model_card_sha256": _required_string(request, "model_card_sha256"),
            "license_evidence_sha256": _required_string(request, "license_evidence_sha256"),
        }
    )
    return ModelRuntimeIdentity(
        provider_id="huggingface-local",
        runtime_id="unsloth-direct-inference-v1",
        base_model_repository=_required_string(request, "model_repository"),
        base_model_revision=_required_string(request, "model_revision"),
        tokenizer_revision=_required_string(request, "tokenizer_revision"),
        configuration_sha256=configuration_sha256,
    )


def _create_chat_messages(generation_request: object) -> tuple[dict[str, str], ...]:
    input_payload = json.loads(generation_request.input_payload_json)
    output_schema = json.loads(generation_request.output_schema.canonical_schema_json)
    user_payload = {
        "task_id": generation_request.task_id,
        "input": input_payload,
        "allowed_evidence_refs": list(generation_request.allowed_evidence_refs),
        "output_schema": output_schema,
        "response_contract": [
            "Return exactly one JSON object and no other text.",
            "Do not wrap the JSON object in Markdown fences.",
            "Do not expose hidden reasoning or chain-of-thought.",
        ],
    }
    serialized = canonical_json(user_payload)
    lowered = serialized.casefold()
    for forbidden in _FORBIDDEN_PROMPT_LABELS:
        if f'"{forbidden}"' in lowered:
            raise RuntimeError("frozen benchmark labels leaked into the model-visible prompt")
    return (
        {"role": "system", "content": generation_request.system_instruction},
        {"role": "user", "content": serialized},
    )


def _prepare_inputs(
    tokenizer: Any,
    messages: tuple[dict[str, str], ...],
    torch: Any,
) -> dict[str, Any]:
    encoded = tokenizer.apply_chat_template(
        list(messages),
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
        return_dict=True,
    )
    if isinstance(encoded, Mapping):
        inputs = {key: value.to("cuda") for key, value in encoded.items() if hasattr(value, "to")}
    elif hasattr(encoded, "to"):
        inputs = {"input_ids": encoded.to("cuda")}
    else:
        raise RuntimeError("chat template did not return tensor inputs")
    input_ids = inputs.get("input_ids")
    if input_ids is None or not hasattr(input_ids, "shape"):
        raise RuntimeError("chat template did not return input_ids")
    if "attention_mask" not in inputs:
        inputs["attention_mask"] = torch.ones_like(input_ids)
    return inputs


def _generated_sequences(value: object) -> Any:
    sequences = _optional_attribute(value, "sequences")
    return value if sequences is None else sequences


def _strict_json_object(raw_text: str) -> dict[str, object] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return None
    return payload


def _invalid_json_score(
    task: object,
    *,
    latency_milliseconds: int,
) -> EvaluatorBenchmarkTaskScore:
    return EvaluatorBenchmarkTaskScore(
        task_id=task.task_id,
        task_content_hash=task.content_hash,
        language=task.language,
        generation_status=StructuredGenerationStatus.SUCCEEDED,
        schema_valid_rate=0.0,
        evidence_reference_precision=0.0,
        unsupported_claim_rate=1.0,
        abstention_accuracy=0.0,
        role_adherence=0.0,
        criterion_agreement=0.0,
        severity_agreement=0.0,
        context_reference_recall=0.0,
        latency_milliseconds=latency_milliseconds,
        failure_code=None,
    )


def _failed_generation_score(
    task: object,
    *,
    failure_code: StructuredGenerationFailureCode,
) -> EvaluatorBenchmarkTaskScore:
    result = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL,
        code=failure_code,
        message="Local model generation failed during the measured spike.",
        retryable=False,
    )
    return score_benchmark_result(task=task, result=result)


def _write_text_artifact(path: Path, value: str) -> str:
    raw = value.encode("utf-8")
    if len(raw) > _MAX_RAW_OUTPUT_BYTES:
        raise RuntimeError("model-spike text artifact exceeds the configured size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)
    return _sha256_bytes(raw)


def _write_json_artifact(path: Path, payload: Mapping[str, object]) -> str:
    serialized = canonical_json(dict(payload)).encode("utf-8")
    if len(serialized) > _MAX_RESULT_BYTES:
        raise RuntimeError("model-spike JSON artifact exceeds the configured size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(serialized)
    os.replace(temporary, path)
    return _sha256_bytes(serialized)


def _relative_reference(path: Path, workspace: Path) -> str:
    resolved = path.resolve()
    workspace_resolved = workspace.resolve()
    if workspace_resolved not in resolved.parents:
        raise RuntimeError("model-spike artifact escaped its workspace")
    return resolved.relative_to(workspace_resolved).as_posix()


def _generate_one(
    *,
    torch: Any,
    model: Any,
    tokenizer: Any,
    task: object,
    repetition: int,
    generation_request: object,
    generation: Mapping[str, object],
    workspace: Path,
    candidate_id: str,
    run_id: UUID,
    model_identity: ModelRuntimeIdentity,
) -> tuple[dict[str, object], object, EvaluatorBenchmarkTaskScore]:
    messages = _create_chat_messages(generation_request)
    prompt_payload = {
        "schema_version": MODEL_SPIKE_PROCESS_SCHEMA_VERSION,
        "task_id": task.task_id,
        "task_content_hash": task.content_hash,
        "repetition": repetition,
        "messages": list(messages),
        "output_schema_sha256": generation_request.output_schema.content_hash,
        "prompt_version_ref": generation_request.prompt_version_ref,
    }
    suffix = f"{task.task_id}-r{repetition:02d}"
    prompt_path = workspace / "prompts" / f"{suffix}.json"
    prompt_sha256 = _write_json_artifact(prompt_path, prompt_payload)
    prompt_reference = _relative_reference(prompt_path, workspace)

    observed_at = datetime.now(UTC)
    measurement_id = uuid5(
        _TASK_MEASUREMENT_NAMESPACE,
        f"{run_id}:{task.task_id}:{repetition}:{task.content_hash}",
    )
    try:
        inputs = _prepare_inputs(tokenizer, messages, torch)
        input_tokens = int(inputs["input_ids"].shape[-1])
        max_output_tokens = _required_integer(generation, "max_output_tokens")
        max_sequence_length = _required_integer(generation, "max_sequence_length")
        if input_tokens + max_output_tokens > max_sequence_length:
            raise RuntimeError("tokenized prompt plus maximum output exceeds max_sequence_length")

        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=max_output_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        torch.cuda.synchronize()
        latency = max(0, round((time.perf_counter() - started) * 1000))
        peak_memory = round(torch.cuda.max_memory_reserved() / (1024 * 1024))
        sequences = _generated_sequences(generated)
        generated_ids = sequences[0, input_tokens:]
        output_tokens = int(generated_ids.shape[-1])
        raw_text = tokenizer.decode(generated_ids, skip_special_tokens=True).strip()
        finish_reason = (
            StructuredGenerationFinishReason.LENGTH
            if output_tokens >= max_output_tokens
            else StructuredGenerationFinishReason.STOP
        )

        raw_path = workspace / "raw" / f"{suffix}.txt"
        raw_sha256 = _write_text_artifact(raw_path, raw_text)
        raw_reference = _relative_reference(raw_path, workspace)
        structured = _strict_json_object(raw_text)
        structured_reference: str | None = None
        structured_sha256: str | None = None
        if structured is None:
            task_status = "INVALID_JSON"
            score = _invalid_json_score(task, latency_milliseconds=latency)
        else:
            structured_path = workspace / "structured" / f"{suffix}.json"
            structured_sha256 = _write_json_artifact(structured_path, structured)
            structured_reference = _relative_reference(structured_path, workspace)
            success = create_structured_generation_success(
                payload=structured,
                actual_identity=model_identity,
                usage=StructuredGenerationUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_milliseconds=latency,
                ),
                finish_reason=finish_reason,
                provider_request_id=None,
            )
            result = successful_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.UNSLOTH_DIRECT_LOCAL,
                success=success,
            )
            score = score_benchmark_result(task=task, result=result)
            task_status = "SCHEMA_VALID" if score.schema_valid_rate == 1.0 else "SCHEMA_INVALID"

        measurement = create_inference_resource_measurement(
            measurement_id=measurement_id,
            candidate_id=candidate_id,
            task_id=task.task_id,
            repetition=repetition,
            status=InferenceMeasurementStatus.SUCCEEDED,
            latency_milliseconds=latency,
            peak_gpu_memory_mb=peak_memory,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            failure_summary=None,
            evidence_reference=raw_reference,
            observed_at=observed_at,
        )
        observation = {
            "task_id": task.task_id,
            "task_content_hash": task.content_hash,
            "language": task.language.value,
            "category": task.category.value,
            "repetition": repetition,
            "status": task_status,
            "prompt_reference": prompt_reference,
            "prompt_sha256": prompt_sha256,
            "raw_output_reference": raw_reference,
            "raw_output_sha256": raw_sha256,
            "structured_output_reference": structured_reference,
            "structured_output_sha256": structured_sha256,
            "finish_reason": finish_reason.value,
            "score": score.to_snapshot(),
            "resource_measurement": measurement.to_snapshot(),
            "failure_kind": None,
            "failure_message": None,
        }
        observation["content_hash"] = snapshot_content_hash(observation)
        return observation, measurement, score
    except KeyboardInterrupt:
        raise
    except (RuntimeError, TypeError, ValueError) as error:
        message = " ".join(str(error).split())[:_MAX_FAILURE_LENGTH]
        is_oom = "out of memory" in message.casefold()
        failure_kind = "OUT_OF_MEMORY" if is_oom else "GENERATION_FAILED"
        failure_code = StructuredGenerationFailureCode.PROVIDER_ERROR
        measurement = create_inference_resource_measurement(
            measurement_id=measurement_id,
            candidate_id=candidate_id,
            task_id=task.task_id,
            repetition=repetition,
            status=InferenceMeasurementStatus.FAILED,
            latency_milliseconds=None,
            peak_gpu_memory_mb=None,
            input_tokens=None,
            output_tokens=None,
            failure_summary=message or failure_kind,
            evidence_reference=prompt_reference,
            observed_at=observed_at,
        )
        score = _failed_generation_score(task, failure_code=failure_code)
        observation = {
            "task_id": task.task_id,
            "task_content_hash": task.content_hash,
            "language": task.language.value,
            "category": task.category.value,
            "repetition": repetition,
            "status": "FAILED",
            "prompt_reference": prompt_reference,
            "prompt_sha256": prompt_sha256,
            "raw_output_reference": None,
            "raw_output_sha256": None,
            "structured_output_reference": None,
            "structured_output_sha256": None,
            "finish_reason": None,
            "score": score.to_snapshot(),
            "resource_measurement": measurement.to_snapshot(),
            "failure_kind": failure_kind,
            "failure_message": message or failure_kind,
        }
        observation["content_hash"] = snapshot_content_hash(observation)
        return observation, measurement, score


def _write_result(path: Path, payload: dict[str, object]) -> None:
    payload["result_sha256"] = _result_sha256(payload)
    _write_json_artifact(path, payload)


def _failure_payload(
    *,
    started_at: datetime,
    started_clock: float,
    request_sha256: str | None,
    failure_kind: str,
    failure_message: str,
) -> dict[str, object]:
    completed_at = datetime.now(UTC)
    return {
        "schema_version": MODEL_SPIKE_PROCESS_SCHEMA_VERSION,
        "request_sha256": request_sha256,
        "status": "FAILED",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_milliseconds": max(0, round((time.perf_counter() - started_clock) * 1000)),
        "candidate_id": None,
        "model_identity": None,
        "observed_identity": None,
        "benchmark": None,
        "environment": None,
        "network_authorized": os.environ.get(_MODEL_SPIKE_NETWORK_GATE) == "1",
        "model_load": None,
        "tasks": [],
        "benchmark_metrics": [],
        "resource_summary": None,
        "failure_kind": failure_kind,
        "failure_message": " ".join(failure_message.split())[:_MAX_FAILURE_LENGTH],
    }


def _run(request: dict[str, object], result_path: Path) -> int:
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    request_sha256 = _required_string(request, "request_sha256")
    candidate_id = _required_string(request, "candidate_id")
    run_id = UUID(_required_string(request, "run_id"))
    network_authorized = os.environ.get(_MODEL_SPIKE_NETWORK_GATE) == "1"

    try:
        suite, environment = _verify_repository_evidence(request)
    except ModelSpikeInputError as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_sha256,
            failure_kind="INVALID_INPUT",
            failure_message=str(error),
        )
        _write_result(result_path, payload)
        return EXIT_INVALID_INPUT

    try:
        torch, model, tokenizer, load_evidence = _load_model(
            request,
            network_authorized=network_authorized,
        )
    except ModuleNotFoundError as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_sha256,
            failure_kind="MISSING_DEPENDENCY",
            failure_message=f"Missing model-spike dependency: {error.name or 'unknown'}.",
        )
        _write_result(result_path, payload)
        return EXIT_MISSING_DEPENDENCY
    except ModelSpikeIdentityError as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_sha256,
            failure_kind="IDENTITY_MISMATCH",
            failure_message=str(error),
        )
        _write_result(result_path, payload)
        return EXIT_IDENTITY_MISMATCH
    except RuntimeError as error:
        message = " ".join(str(error).split())
        if "CUDA is unavailable" in message:
            kind = "GPU_UNAVAILABLE"
            code = EXIT_GPU_UNAVAILABLE
        elif "out of memory" in message.casefold():
            kind = "OUT_OF_MEMORY"
            code = EXIT_OUT_OF_MEMORY
        else:
            kind = "MODEL_LOAD_FAILED"
            code = EXIT_MODEL_LOAD_FAILED
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_sha256,
            failure_kind=kind,
            failure_message=message,
        )
        _write_result(result_path, payload)
        return code
    except (OSError, TypeError, ValueError) as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_sha256,
            failure_kind="MODEL_LOAD_FAILED",
            failure_message=str(error),
        )
        _write_result(result_path, payload)
        return EXIT_MODEL_LOAD_FAILED

    workspace = result_path.parent.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    model_identity = _model_identity(request)
    generation = request["generation"]
    assert isinstance(generation, dict)
    observations: list[dict[str, object]] = []
    measurements: list[object] = []
    scores: list[EvaluatorBenchmarkTaskScore] = []
    terminal_failure: tuple[str, str] | None = None

    try:
        for task in suite.tasks:
            generation_request = create_benchmark_generation_request(
                run_id=run_id,
                task=task,
                model_identity=model_identity,
            )
            for repetition in range(1, _required_integer(generation, "repetitions") + 1):
                observation, measurement, score = _generate_one(
                    torch=torch,
                    model=model,
                    tokenizer=tokenizer,
                    task=task,
                    repetition=repetition,
                    generation_request=generation_request,
                    generation=generation,
                    workspace=workspace,
                    candidate_id=candidate_id,
                    run_id=run_id,
                    model_identity=model_identity,
                )
                observations.append(observation)
                measurements.append(measurement)
                scores.append(score)
                if observation["failure_kind"] == "OUT_OF_MEMORY":
                    terminal_failure = (
                        "OUT_OF_MEMORY",
                        str(observation["failure_message"]),
                    )
                    break
            if terminal_failure is not None:
                break
    except KeyboardInterrupt:
        terminal_failure = ("INTERRUPTED", "Model-spike execution was interrupted.")

    metrics = aggregate_benchmark_metrics(tuple(scores)) if scores else ()
    resource_summary = (
        summarize_inference_resources(
            candidate_id=candidate_id,
            measurements=tuple(measurements),
        )
        if measurements
        else None
    )
    expected_count = len(suite.tasks) * _required_integer(generation, "repetitions")
    any_failed = any(item["status"] == "FAILED" for item in observations)
    complete = len(observations) == expected_count and terminal_failure is None
    status = "COMPLETED" if complete and not any_failed else "PARTIAL"
    failure_kind = None if terminal_failure is None else terminal_failure[0]
    failure_message = None if terminal_failure is None else terminal_failure[1]
    completed_at = datetime.now(UTC)
    result_payload: dict[str, object] = {
        "schema_version": MODEL_SPIKE_PROCESS_SCHEMA_VERSION,
        "request_sha256": request_sha256,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_milliseconds": max(0, round((time.perf_counter() - started_clock) * 1000)),
        "candidate_id": candidate_id,
        "model_identity": model_identity.to_snapshot(),
        "observed_identity": load_evidence,
        "benchmark": {
            "suite_id": suite.suite_id,
            "suite_version_number": suite.version_number,
            "suite_sha256": FROZEN_BENCHMARK_SUITE_SHA256,
            "suite_content_hash": suite.content_hash,
            "task_count": len(suite.tasks),
            "repetitions": _required_integer(generation, "repetitions"),
            "expected_measurement_count": expected_count,
            "observed_measurement_count": len(observations),
            "complete": complete,
        },
        "environment": {
            "environment_sha256": _required_string(request, "environment_sha256"),
            "package_lock_sha256": _required_string(request, "package_lock_sha256"),
            "environment_id": environment.get("environment_id"),
            "gpu": environment.get("gpu"),
            "build_toolchain": environment.get("build_toolchain"),
        },
        "network_authorized": network_authorized,
        "model_load": load_evidence,
        "tasks": observations,
        "benchmark_metrics": [metric.to_snapshot() for metric in metrics],
        "resource_summary": None if resource_summary is None else resource_summary.to_snapshot(),
        "failure_kind": failure_kind,
        "failure_message": failure_message,
    }
    _write_result(result_path, result_payload)

    if terminal_failure is not None and terminal_failure[0] == "INTERRUPTED":
        return EXIT_INTERRUPTED
    if terminal_failure is not None and terminal_failure[0] == "OUT_OF_MEMORY":
        return EXIT_OUT_OF_MEMORY
    return 0 if status == "COMPLETED" else EXIT_PARTIAL_RESULT


def main() -> int:
    arguments = _parse_arguments()
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    request_hash: str | None = None
    try:
        request = _load_request(arguments.request.resolve())
        request_hash = _required_string(request, "request_sha256")
    except (ModelSpikeInputError, OSError) as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_hash,
            failure_kind="INVALID_INPUT",
            failure_message=str(error),
        )
        with contextlib.suppress(OSError):
            _write_result(arguments.result.resolve(), payload)
        return EXIT_INVALID_INPUT
    try:
        return _run(request, arguments.result.resolve())
    except OSError as error:
        payload = _failure_payload(
            started_at=started_at,
            started_clock=started_clock,
            request_sha256=request_hash,
            failure_kind="ARTIFACT_WRITE_FAILED",
            failure_message=str(error),
        )
        with contextlib.suppress(OSError):
            _write_result(arguments.result.resolve(), payload)
        return EXIT_INVALID_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
