#!/usr/bin/env python3
"""Serve the exact S59 smoke adapter on a bounded loopback OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)
from orchestwin.training.benchmarking import create_benchmark_generation_request  # noqa: E402
from orchestwin.training.qlora_smoke_serving import (  # noqa: E402
    FALLBACK_POLICY,
    MAX_CONCURRENCY,
    SERVING_ENGINE_ID,
    SERVING_MODEL_NAME,
    VLLM_OBSERVATION_STATUS,
    QloraSmokeServingError,
    load_serving_inputs,
    serving_model_identity,
    write_serving_snapshot,
)

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
_MAX_BODY_BYTES = 2_000_000
_MAX_OUTPUT_TOKENS = 1_024
_MAX_SEQUENCE_LENGTH = 4_096


class ServingHttpError(ValueError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class RuntimeState:
    inputs: Any
    spike: Any
    torch: Any
    model: Any
    tokenizer: Any
    identity: ModelRuntimeIdentity
    model_load_duration_milliseconds: int
    model_load_peak_torch_reserved_memory_mib: int
    gpu_total_memory_mib: int
    allow_diagnostics: bool
    generation_slot: threading.BoundedSemaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(MAX_CONCURRENCY)
    )
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    active_requests: int = 0
    completed_generation_count: int = 0
    rejected_concurrency_count: int = 0
    last_model_visible_messages_sha256: str | None = None
    last_generation_peak_torch_reserved_memory_mib: int | None = None
    last_generation_latency_milliseconds: int | None = None

    def begin(self) -> bool:
        if not self.generation_slot.acquire(blocking=False):
            with self.state_lock:
                self.rejected_concurrency_count += 1
            return False
        with self.state_lock:
            self.active_requests += 1
        return True

    def finish(self) -> None:
        with self.state_lock:
            self.active_requests -= 1
        self.generation_slot.release()

    def snapshot(self) -> dict[str, object]:
        with self.state_lock:
            return {
                "status": "SERVING",
                "engine_id": SERVING_ENGINE_ID,
                "model_name": SERVING_MODEL_NAME,
                "model_identity": self.identity.to_snapshot(),
                "loopback_only": True,
                "network_authorized": False,
                "max_concurrency": MAX_CONCURRENCY,
                "fallback_policy": FALLBACK_POLICY,
                "active_requests": self.active_requests,
                "completed_generation_count": self.completed_generation_count,
                "rejected_concurrency_count": self.rejected_concurrency_count,
                "last_model_visible_messages_sha256": (self.last_model_visible_messages_sha256),
                "model_load_duration_milliseconds": self.model_load_duration_milliseconds,
                "model_load_peak_torch_reserved_memory_mib": (
                    self.model_load_peak_torch_reserved_memory_mib
                ),
                "last_generation_peak_torch_reserved_memory_mib": (
                    self.last_generation_peak_torch_reserved_memory_mib
                ),
                "last_generation_latency_milliseconds": (self.last_generation_latency_milliseconds),
                "gpu_total_memory_mib": self.gpu_total_memory_mib,
                "vllm_observation_status": VLLM_OBSERVATION_STATUS,
                "smoke_scope": "EIGHT_STEP_ADAPTER_SERVING_PROBE_ONLY",
            }


def _load_spike_module():
    path = ROOT / "environments/training/run_model_spike.py"
    spec = importlib.util.spec_from_file_location("orchestwin_serving_spike_contract", path)
    if spec is None or spec.loader is None:
        raise QloraSmokeServingError("could not load the frozen model-spike prompt contract")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _parse_identity(value: object) -> ModelRuntimeIdentity:
    if not isinstance(value, dict):
        raise ServingHttpError(422, "IDENTITY_REQUIRED", "expected model identity is required")
    try:
        return ModelRuntimeIdentity(
            provider_id=value["provider_id"],
            runtime_id=value["runtime_id"],
            base_model_repository=value["base_model_repository"],
            base_model_revision=value["base_model_revision"],
            tokenizer_revision=value["tokenizer_revision"],
            configuration_sha256=value["configuration_sha256"],
            adapter_id=value.get("adapter_id"),
            adapter_sha256=value.get("adapter_sha256"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ServingHttpError(
            422,
            "INVALID_IDENTITY",
            "expected model identity is malformed",
        ) from error


def _evidence_reference_ids(input_payload: Mapping[str, object]) -> tuple[str, ...]:
    evidence = input_payload.get("evidence")
    if not isinstance(evidence, list):
        return ()
    refs: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        reference = item.get("reference_id")
        if isinstance(reference, str) and reference:
            refs.append(reference)
    return tuple(sorted(set(refs)))


def _frozen_benchmark_metadata(
    state: RuntimeState,
    *,
    input_payload_json: str,
    output_schema_json: str,
) -> tuple[str, str, tuple[str, ...]] | None:
    """Recover exact frozen prompt metadata for the serving smoke benchmark probe.

    The repository's current OpenAI-compatible adapter transmits the exact input and schema
    but not task_id/allowed_evidence_refs/prompt_version_ref as separate HTTP fields. The
    bounded serving probe may recover those fields only when the input+schema exactly match
    one frozen benchmark task. Arbitrary application requests use the generic fallback path
    and no claim of direct-spike prompt equivalence is made for them.
    """
    for task in state.inputs.ablation_inputs.suite.tasks:
        request = create_benchmark_generation_request(
            run_id=UUID("00000000-0000-4000-8000-000000162099"),
            task=task,
            model_identity=state.identity,
        )
        if (
            request.input_payload_json == input_payload_json
            and request.output_schema.canonical_schema_json == output_schema_json
        ):
            return (
                task.task_id,
                request.prompt_version_ref,
                request.allowed_evidence_refs,
            )
    return None


def _validated_model_request(
    payload: object,
    state: RuntimeState,
) -> tuple[tuple[dict[str, str], ...], int, str]:
    if not isinstance(payload, dict):
        raise ServingHttpError(400, "INVALID_REQUEST", "completion payload must be an object")
    if payload.get("model") != SERVING_MODEL_NAME:
        raise ServingHttpError(404, "MODEL_NOT_FOUND", "requested model name is not served")

    messages = payload.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or not all(isinstance(item, dict) for item in messages)
        or messages[0].get("role") != "system"
        or messages[1].get("role") != "user"
        or not isinstance(messages[0].get("content"), str)
        or not isinstance(messages[1].get("content"), str)
    ):
        raise ServingHttpError(
            422, "INVALID_MESSAGES", "exactly one system and one user message are required"
        )

    temperature = payload.get("temperature")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ServingHttpError(422, "INVALID_TEMPERATURE", "temperature must be numeric")
    if float(temperature) != 0.0:
        raise ServingHttpError(
            422,
            "DETERMINISTIC_ONLY",
            "the bounded evaluator serving probe accepts temperature zero only",
        )

    max_tokens = payload.get("max_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= _MAX_OUTPUT_TOKENS
    ):
        raise ServingHttpError(
            422, "INVALID_MAX_TOKENS", "max_tokens is outside the serving smoke limit"
        )

    response_format = payload.get("response_format")
    if not isinstance(response_format, dict) or response_format.get("type") != "json_schema":
        raise ServingHttpError(422, "JSON_SCHEMA_REQUIRED", "response_format must use json_schema")
    json_schema = response_format.get("json_schema")
    if (
        not isinstance(json_schema, dict)
        or json_schema.get("strict") is not True
        or not isinstance(json_schema.get("schema"), dict)
    ):
        raise ServingHttpError(422, "INVALID_JSON_SCHEMA", "strict JSON schema is required")

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ServingHttpError(422, "METADATA_REQUIRED", "OrchesTwin metadata is required")
    expected = _parse_identity(metadata.get("expected_model_identity"))
    if expected != state.identity:
        code = "ADAPTER_NOT_LOADED" if expected.adapter_id is None else "IDENTITY_MISMATCH"
        raise ServingHttpError(
            409,
            code,
            "the loopback runtime refuses any identity other than the exact S59 adapter",
        )

    try:
        input_payload = json.loads(messages[1]["content"])
    except json.JSONDecodeError as error:
        raise ServingHttpError(
            422,
            "INVALID_INPUT_JSON",
            "user content must contain a JSON object",
        ) from error
    if not isinstance(input_payload, dict):
        raise ServingHttpError(
            422,
            "INVALID_INPUT_JSON",
            "user content must contain a JSON object",
        )

    input_payload_json = canonical_json(input_payload)
    output_schema_json = canonical_json(json_schema["schema"])
    task_id = metadata.get("orchestwin_task_id")
    prompt_version = metadata.get("orchestwin_prompt_version_ref")
    allowed_refs = metadata.get("allowed_evidence_refs")

    explicit_metadata = (
        isinstance(task_id, str)
        and bool(task_id)
        and isinstance(prompt_version, str)
        and bool(prompt_version)
        and isinstance(allowed_refs, list)
        and all(isinstance(item, str) for item in allowed_refs)
    )
    if explicit_metadata:
        refs = tuple(sorted(set(allowed_refs)))
    else:
        recovered = _frozen_benchmark_metadata(
            state,
            input_payload_json=input_payload_json,
            output_schema_json=output_schema_json,
        )
        if recovered is not None:
            task_id, prompt_version, refs = recovered
        else:
            task_id = "local-serving-probe"
            prompt_version = "local-serving-probe-v1"
            refs = _evidence_reference_ids(input_payload)

    request_like = SimpleNamespace(
        task_id=task_id,
        input_payload_json=input_payload_json,
        allowed_evidence_refs=refs,
        output_schema=SimpleNamespace(canonical_schema_json=output_schema_json),
        system_instruction=messages[0]["content"],
    )
    model_messages = state.spike._create_chat_messages(request_like)
    message_hash = snapshot_content_hash({"messages": list(model_messages)})
    return model_messages, max_tokens, message_hash


def _load_runtime(
    *,
    training_root: Path,
    recovery_report: Path,
    ablation_report: Path,
    allow_diagnostics: bool,
) -> RuntimeState:
    if os.environ.get(TRAINING_GATE) == "1":
        raise QloraSmokeServingError("serving smoke refuses the training authorization gate")
    if os.environ.get("ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK") == "1":
        raise QloraSmokeServingError("serving smoke refuses model network authorization")

    inputs = load_serving_inputs(
        ROOT,
        training_root,
        recovery_report,
        ablation_report,
    )
    identity = serving_model_identity(inputs)
    spike = _load_spike_module()
    torch, _, FastLanguageModel = spike._load_runtime_dependencies()
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise QloraSmokeServingError("serving smoke requires exactly one visible CUDA GPU")

    torch.manual_seed(20260904)
    torch.cuda.manual_seed_all(20260904)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()

    values = {
        "model_name": inputs.candidate.repository_id,
        "revision": inputs.candidate.revision,
        "max_seq_length": _MAX_SEQUENCE_LENGTH,
        "dtype": None,
        "load_in_4bit": True,
        "trust_remote_code": False,
        "local_files_only": True,
        "use_exact_model_name": True,
        "fast_inference": False,
    }
    model, tokenizer = FastLanguageModel.from_pretrained(
        **spike._supported_kwargs(FastLanguageModel.from_pretrained, values)
    )
    observed = spike._observed_revision(model)
    if observed is not None and observed != inputs.candidate.revision:
        raise QloraSmokeServingError("served base revision differs from the exact S59 request")
    if getattr(model, "is_loaded_in_4bit", False) is not True:
        raise QloraSmokeServingError("served base model is not four-bit")

    FastLanguageModel.for_inference(model)
    from peft import PeftModel

    model = PeftModel.from_pretrained(
        model,
        str(inputs.bundle.adapter_root),
        is_trainable=False,
        local_files_only=True,
    )
    model.eval()

    total_lora = 0
    trainable_lora = 0
    unsafe_trainable = []
    for name, parameter in model.named_parameters():
        if "lora_" in name:
            total_lora += parameter.numel()
            if parameter.requires_grad:
                trainable_lora += parameter.numel()
        elif parameter.requires_grad:
            unsafe_trainable.append(name)
    expected_lora = inputs.bundle.result["observations"]["trainable_lora_parameters"]
    if unsafe_trainable or total_lora != expected_lora or trainable_lora != 0:
        raise QloraSmokeServingError("served adapter differs from the S59/S60 adapter identity")

    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise QloraSmokeServingError("served tokenizer has neither pad nor EOS token")
        tokenizer.pad_token = tokenizer.eos_token
    if getattr(tokenizer, "chat_template", None) is None:
        raise QloraSmokeServingError("served tokenizer has no chat template")

    torch.cuda.synchronize()
    load_duration = max(0, round((time.perf_counter() - started) * 1000))
    load_peak = round(torch.cuda.max_memory_reserved() / 1024**2)
    total_memory = round(torch.cuda.get_device_properties(0).total_memory / 1024**2)
    return RuntimeState(
        inputs=inputs,
        spike=spike,
        torch=torch,
        model=model,
        tokenizer=tokenizer,
        identity=identity,
        model_load_duration_milliseconds=load_duration,
        model_load_peak_torch_reserved_memory_mib=load_peak,
        gpu_total_memory_mib=total_memory,
        allow_diagnostics=allow_diagnostics,
    )


def _generate(state: RuntimeState, payload: object) -> dict[str, object]:
    model_messages, max_tokens, message_hash = _validated_model_request(payload, state)
    if not state.begin():
        raise ServingHttpError(429, "RATE_LIMITED", "the single serving slot is busy")
    try:
        inputs = state.spike._prepare_inputs(
            state.tokenizer,
            model_messages,
            state.torch,
            state.inputs.candidate.chat_template_control,
        )
        input_tokens = int(inputs["input_ids"].shape[-1])
        if input_tokens + max_tokens > _MAX_SEQUENCE_LENGTH:
            raise ServingHttpError(
                422,
                "SEQUENCE_LIMIT",
                "prompt plus requested output exceeds the serving smoke sequence limit",
            )

        state.torch.cuda.empty_cache()
        state.torch.cuda.reset_peak_memory_stats()
        state.torch.cuda.synchronize()
        started = time.perf_counter()
        with state.torch.inference_mode():
            generated = state.model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=state.tokenizer.pad_token_id,
                eos_token_id=state.tokenizer.eos_token_id,
            )
        state.torch.cuda.synchronize()
        latency = max(0, round((time.perf_counter() - started) * 1000))
        peak = round(state.torch.cuda.max_memory_reserved() / 1024**2)
        sequences = state.spike._generated_sequences(generated)
        ids = sequences[0, input_tokens:]
        output_tokens = int(ids.shape[-1])
        raw = state.tokenizer.decode(ids, skip_special_tokens=True).strip()
        finish_reason = "length" if output_tokens >= max_tokens else "stop"

        with state.state_lock:
            state.completed_generation_count += 1
            state.last_model_visible_messages_sha256 = message_hash
            state.last_generation_peak_torch_reserved_memory_mib = peak
            state.last_generation_latency_milliseconds = latency

        return {
            "id": f"orchestwin-local-{uuid4()}",
            "object": "chat.completion",
            "model": SERVING_MODEL_NAME,
            "model_identity": state.identity.to_snapshot(),
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": raw},
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            "orchestwin_serving": {
                "engine_id": SERVING_ENGINE_ID,
                "model_visible_messages_sha256": message_hash,
                "fallback_policy": FALLBACK_POLICY,
            },
        }
    finally:
        state.finish()


def _diagnostic_hold(state: RuntimeState, payload: object) -> dict[str, object]:
    if not state.allow_diagnostics:
        raise ServingHttpError(404, "NOT_FOUND", "diagnostics are disabled")
    if not isinstance(payload, dict):
        raise ServingHttpError(400, "INVALID_REQUEST", "diagnostic payload must be an object")
    milliseconds = payload.get("hold_milliseconds")
    if (
        isinstance(milliseconds, bool)
        or not isinstance(milliseconds, int)
        or not 50 <= milliseconds <= 5_000
    ):
        raise ServingHttpError(422, "INVALID_HOLD", "hold_milliseconds must be 50..5000")
    if not state.begin():
        raise ServingHttpError(429, "RATE_LIMITED", "the single serving slot is busy")
    try:
        time.sleep(milliseconds / 1000)
        return {"status": "HELD", "hold_milliseconds": milliseconds}
    finally:
        state.finish()


def _handler(state: RuntimeState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "OrchesTwinSmokeServing/1"

        def log_message(self, format: str, *args) -> None:
            return

        def _send(self, status: int, payload: Mapping[str, object]) -> None:
            raw = canonical_json(dict(payload)).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(raw)

        def _body(self) -> object:
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError as error:
                raise ServingHttpError(400, "INVALID_LENGTH", "invalid Content-Length") from error
            if not 0 < length <= _MAX_BODY_BYTES:
                raise ServingHttpError(413, "BODY_LIMIT", "request body exceeds serving limit")
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ServingHttpError(
                    400, "INVALID_JSON", "request body must be UTF-8 JSON"
                ) from error

        def do_GET(self) -> None:
            try:
                if self.path == "/health":
                    self._send(200, state.snapshot())
                    return
                if self.path == "/v1/models":
                    self._send(
                        200,
                        {
                            "object": "list",
                            "data": [
                                {
                                    "id": SERVING_MODEL_NAME,
                                    "object": "model",
                                    "model_identity": state.identity.to_snapshot(),
                                }
                            ],
                        },
                    )
                    return
                if self.path == "/diagnostics/state" and state.allow_diagnostics:
                    self._send(200, state.snapshot())
                    return
                raise ServingHttpError(404, "NOT_FOUND", "endpoint not found")
            except ServingHttpError as error:
                self._send(
                    error.status_code,
                    {"error": {"code": error.code, "message": error.message}},
                )

        def do_POST(self) -> None:
            try:
                payload = self._body()
                if self.path == "/v1/chat/completions":
                    response = _generate(state, payload)
                elif self.path == "/diagnostics/hold":
                    response = _diagnostic_hold(state, payload)
                else:
                    raise ServingHttpError(404, "NOT_FOUND", "endpoint not found")
                self._send(200, response)
            except ServingHttpError as error:
                self._send(
                    error.status_code,
                    {"error": {"code": error.code, "message": error.message}},
                )
            except (RuntimeError, TypeError, ValueError) as error:
                self._send(
                    500,
                    {
                        "error": {
                            "code": "SERVING_RUNTIME_ERROR",
                            "message": " ".join(str(error).split())[:1_000],
                        }
                    },
                )

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--recovery-report", type=Path, required=True)
    parser.add_argument("--ablation-report", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--allow-diagnostics", action="store_true")
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        print("serving smoke binds to 127.0.0.1 only", file=sys.stderr)
        return 22
    if not 0 <= args.port <= 65535:
        print("invalid serving port", file=sys.stderr)
        return 22

    try:
        state = _load_runtime(
            training_root=args.training_root,
            recovery_report=args.recovery_report,
            ablation_report=args.ablation_report,
            allow_diagnostics=args.allow_diagnostics,
        )
        server = ThreadingHTTPServer((args.host, args.port), _handler(state))
        server.daemon_threads = True
        port = int(server.server_address[1])
        ready = {
            "schema_version": 1,
            "status": "READY",
            "host": args.host,
            "port": port,
            "base_url": f"http://{args.host}:{port}",
            "model_name": SERVING_MODEL_NAME,
            "model_identity": state.identity.to_snapshot(),
            "runtime_state": state.snapshot(),
        }
        ready["content_hash"] = snapshot_content_hash(ready)
        write_serving_snapshot(args.ready_file, ready)
        print(args.ready_file.resolve(), flush=True)
        print(f"qlora_smoke_serving: READY http://{args.host}:{port}", flush=True)
        server.serve_forever(poll_interval=0.2)
        return 0
    except KeyboardInterrupt:
        return 130
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        QloraSmokeServingError,
    ) as error:
        print(
            f"qlora_smoke_serving_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22


if __name__ == "__main__":
    raise SystemExit(main())
