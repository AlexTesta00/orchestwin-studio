#!/usr/bin/env python3
"""Offline, authenticated loopback serving for proposal adapters; no training.

Uses the existing WSL/Unsloth environment and an exact cached base revision.
JSON schemas constrain token selection; the application still validates outputs.
An optional proposer adapter must be explicitly selected with both file hashes.
The specialized final-evaluator adapter is never used for proposal requests.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.proposal_tasks import SOURCE_TASKS, TASKS  # noqa: E402
from orchestwin.models.schema_decoding import (  # noqa: E402
    POLICY as SCHEMA_DECODING,
)
from orchestwin.models.schema_decoding import (  # noqa: E402
    VERSION as LLGUIDANCE_VERSION,
)
from orchestwin.models.schema_decoding import (  # noqa: E402
    build_schema_processor_factory,
)
from orchestwin.models.strict_evaluator_json import strict_json_object  # noqa: E402
from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
MAX_SEQUENCE = 16384
MAX_OUTPUT = 8192
MAX_GENERATION_SECONDS = 120
MAX_BODY = 2_000_000


def adapter_selection(state):
    """The endpoint's declared selection, not the shared model's idle adapter."""
    name = state.get("adapter_name")
    if name is None and state.get("shared_adapter_loaded") and state.get("evaluator"):
        name = "default"
    identity = state["identity"]
    if name is not None:
        expected = "default" if state.get("evaluator") else "proposer"
        if (
            name != expected
            or not state.get("shared_adapter_loaded")
            or identity.adapter_id is None
            or identity.adapter_sha256 is None
            or name not in getattr(state["model"], "peft_config", {})
        ):
            raise ValueError("ADAPTER_ROLE_OR_IDENTITY_MISMATCH")
    elif identity.adapter_id is not None or identity.adapter_sha256 is not None:
        raise ValueError("ADAPTER_IDENTITY_WITHOUT_SELECTION")
    return name


@contextmanager
def selected_adapter(state):
    """Select under the shared request lock and restore even after generation fails.

    PEFT set_adapter can enable gradients; freezing after every switch keeps both
    serving roles inference-only. A proposer without a selected adapter disables
    every loaded adapter for its entire forward pass.
    """
    model = state["model"]
    selected = adapter_selection(state)
    loaded = state.get("shared_adapter_loaded", False)
    if not loaded:
        if selected is not None:
            raise ValueError("ADAPTER_SELECTION_WITHOUT_LOADED_MODEL")
        yield
        return
    if selected is None:
        with model.disable_adapter():
            yield
        return
    previous = list(model.active_adapters)
    if len(previous) != 1 or selected not in model.peft_config:
        raise ValueError("ADAPTER_SELECTION_MISMATCH")
    try:
        model.set_adapter(selected)
        model.requires_grad_(False)
        if model.active_adapters != [selected]:
            raise ValueError("ADAPTER_SELECTION_MISMATCH")
        yield
    finally:
        model.set_adapter(previous[0])
        model.requires_grad_(False)
        if model.active_adapters != previous:
            raise ValueError("ADAPTER_RESTORATION_FAILED")


def verify_proposer_adapter(
    path, weights_hash, config_hash, *, repository=MODEL, revision=REVISION
):
    """Verify explicit regular files and model compatibility before any GPU load."""
    supplied = (path, weights_hash, config_hash)
    if not any(value is not None for value in supplied):
        return {}
    if not all(value is not None for value in supplied):
        raise ValueError("PROPOSER_ADAPTER_PATH_AND_HASHES_REQUIRED")
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in supplied[1:]):
        raise ValueError("PROPOSER_ADAPTER_HASH_INVALID")
    path = Path(path).resolve(strict=True)
    files = {"adapter_model.safetensors": weights_hash, "adapter_config.json": config_hash}
    for name, expected in files.items():
        item = path / name
        if item.is_symlink() or not item.is_file():
            raise ValueError("PROPOSER_ADAPTER_FILE_INVALID")
        with item.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("PROPOSER_ADAPTER_HASH_MISMATCH")
    raw = (path / "adapter_config.json").read_bytes()
    if len(raw) > 1_000_000:
        raise ValueError("PROPOSER_ADAPTER_CONFIGURATION_INVALID")
    config = strict_json_object(raw)
    if (
        config.get("base_model_name_or_path") != repository
        or config.get("peft_type") != "LORA"
        or config.get("task_type") != "CAUSAL_LM"
        or config.get("revision") not in (None, revision)
    ):
        raise ValueError("PROPOSER_ADAPTER_BASE_OR_TYPE_MISMATCH")
    return files


def supported_tasks(state):
    """Admission and health must expose the same explicit endpoint capabilities."""
    if state.get("evaluator"):
        expected = ["user-twin-evaluation"]
        if state.get("supported_tasks", expected) != expected:
            raise ValueError("TASK_CONFIGURATION_MISMATCH")
        return expected
    tasks = state.get("supported_tasks", sorted(TASKS))
    if tasks not in (sorted(TASKS), sorted(SOURCE_TASKS)):
        raise ValueError("TASK_CONFIGURATION_MISMATCH")
    return tasks


def health_snapshot(state):
    selected = adapter_selection(state)
    return {
        "health_contract_version": 2,
        "status": "READY",
        "model_name": state["model_name"],
        "model_identity": state["identity"].to_snapshot(),
        "supported_tasks": supported_tasks(state),
        "max_sequence_length": MAX_SEQUENCE,
        "max_output_tokens": MAX_OUTPUT,
        "generation_watchdog": f"COOPERATIVE_{state.get('max_generation_seconds', MAX_GENERATION_SECONDS)}_SECONDS_NOT_HARD_GPU_PREEMPTION",
        "schema_decoding": SCHEMA_DECODING,
        "schema_decoder_version": LLGUIDANCE_VERSION,
        "completed_generation_count": state["completed_generation_count"],
        "adapter_loaded": state.get("shared_adapter_loaded", False),
        "adapter_active": selected is not None,
        "adapter_name": selected,
        "adapter_role": ("evaluator" if state.get("evaluator") else "proposal")
        if selected
        else None,
        "training_executed": False,
        "fallback_policy": "FAIL_CLOSED_NO_FAKE_FALLBACK",
    }


def selected_model(repository: str | None, revision: str | None) -> tuple[str, str]:
    """A replacement is explicit and immutable; never resolve a moving branch."""
    if repository is None and revision is None:
        return MODEL, REVISION
    if (
        not isinstance(repository, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository)
        is None
        or not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
    ):
        raise ValueError("MODEL_REPOSITORY_AND_EXACT_REVISION_REQUIRED")
    return repository, revision


def load_model(repository=MODEL, revision=REVISION):
    """Reuse the tested exact-revision loader, always with network disabled."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    spec = importlib.util.spec_from_file_location(
        "proposal_model_loader", ROOT / "environments/training/run_model_spike.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    torch, model, tokenizer, evidence = module._load_model(
        {
            "model_repository": repository,
            "model_revision": revision,
            "tokenizer_repository": repository,
            "tokenizer_revision": revision,
            "generation": {"seed": 42, "max_sequence_length": MAX_SEQUENCE},
        },
        network_authorized=False,
    )
    if getattr(model, "peft_config", None) or evidence["observed_model_revision"] != revision:
        raise RuntimeError("exact base-model identity was not observed")
    return torch, model, tokenizer, evidence


def completion(state, payload):
    if payload.get("model") != state["model_name"]:
        raise ValueError("MODEL_MISMATCH")
    metadata = payload.get("metadata", {})
    if metadata.get("expected_model_identity") != state["identity"].to_snapshot():
        raise ValueError("IDENTITY_MISMATCH")
    evaluator = state.get("evaluator", False)
    capabilities = supported_tasks(state)
    tasks = (
        {"user-twin-evaluation-v1"}
        if evaluator
        else {f"proposal-{task}-v1" for task in capabilities}
    )
    if metadata.get("orchestwin_task_id") not in tasks:
        raise ValueError("TASK_REJECTED")
    messages = payload.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) != 2
        or [item.get("role") for item in messages] != ["system", "user"]
        or any(not isinstance(item.get("content"), str) for item in messages)
    ):
        raise ValueError("MESSAGES_REJECTED")
    maximum = payload.get("max_tokens")
    temperature = payload.get("temperature")
    if type(maximum) is not int or not 1 <= maximum <= MAX_OUTPUT:
        raise ValueError("TOKEN_BUDGET_REJECTED")
    if type(temperature) not in (float, int) or not 0 <= temperature <= 2:
        raise ValueError("TEMPERATURE_REJECTED")
    if capabilities == sorted(SOURCE_TASKS) and temperature <= 0:
        raise ValueError("SAMPLED_SOURCE_PROPOSAL_REQUIRED")
    response_format = payload.get("response_format", {})
    specification = response_format.get("json_schema", {})
    schema = specification.get("schema")
    visible = strict_json_object(messages[1]["content"])
    if (
        response_format.get("type") != "json_schema"
        or specification.get("strict") is not True
        or not isinstance(schema, dict)
        or (not evaluator and schema != visible.get("output_schema"))
    ):
        raise ValueError("SCHEMA_MISMATCH")
    if evaluator:
        from orchestwin.models.strict_evaluator_json import check_evaluator_schema

        check_evaluator_schema(schema)
        if temperature != 0:
            raise ValueError("EVALUATOR_TEMPERATURE_REJECTED")
    torch, model, tokenizer = state["torch"], state["model"], state["tokenizer"]
    encoded = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt", return_dict=True
    )
    inputs = {key: value.to(model.device) for key, value in encoded.items()}
    input_tokens = inputs["input_ids"].shape[-1]
    if input_tokens + maximum > MAX_SEQUENCE:
        raise ValueError("CONTEXT_BUDGET_EXCEEDED")
    processor = state["schema_processor"](schema, input_tokens)
    generation_seconds = state.get("max_generation_seconds", MAX_GENERATION_SECONDS)
    started = time.perf_counter()
    options = {"do_sample": temperature > 0}
    if temperature > 0:
        options["temperature"] = temperature
    with selected_adapter(state), torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=maximum,
            max_time=generation_seconds,
            use_cache=True,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            logits_processor=[processor],
            **options,
        )
    tokens = generated[0, input_tokens:]
    # Preserve model text: no trimming, JSON repair, fallback or regeneration.
    content = tokenizer.decode(tokens, skip_special_tokens=True)
    eos = tokenizer.eos_token_id
    eos_ids = {eos} if isinstance(eos, int) else set(eos or ())
    finished = len(tokens) > 0 and int(tokens[-1]) in eos_ids
    schema_complete = processor.finish(generated)
    if finished and not schema_complete:
        raise ValueError("SCHEMA_INCOMPLETE_AT_EOS")
    return {
        "id": f"proposal-{uuid4()}",
        "model": state["model_name"],
        "model_identity": state["identity"].to_snapshot(),
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop" if finished else "length",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": len(tokens),
            "total_tokens": input_tokens + len(tokens),
        },
        "orchestwin_serving": {
            "model_visible_messages_sha256": snapshot_content_hash(messages),
            "max_sequence_length": MAX_SEQUENCE,
            "max_output_tokens": MAX_OUTPUT,
            "output_repair_used": False,
            "adapter_loaded": state.get("shared_adapter_loaded", False),
            "adapter_active": adapter_selection(state) is not None,
            "adapter_name": adapter_selection(state),
            "adapter_role": ("evaluator" if evaluator else "proposal")
            if adapter_selection(state)
            else None,
            "generation_wall_time_budget_seconds": generation_seconds,
            "generation_wall_time_milliseconds": round((time.perf_counter() - started) * 1000),
            "schema_decoding": SCHEMA_DECODING,
            "schema_complete": schema_complete,
        },
    }


def handler_for(state, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, status, payload):
            body = canonical_json(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authenticated(self):
            return secrets.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}")

        def do_GET(self):
            if not self._authenticated():
                return self._send(401, {"error": "UNAUTHORIZED"})
            if self.path != "/health":
                return self._send(404, {"error": "NOT_FOUND"})
            self._send(200, health_snapshot(state))

        def do_POST(self):
            self.connection.settimeout(10)
            if not self._authenticated():
                return self._send(401, {"error": "UNAUTHORIZED"})
            if self.path != "/v1/chat/completions":
                return self._send(404, {"error": "NOT_FOUND"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                    raise ValueError("BODY_REJECTED")
                payload = strict_json_object(self.rfile.read(length))
            except (ValueError, OSError):
                return self._send(400, {"error": "BODY_REJECTED"})
            if not state["slot"].acquire(blocking=False):
                return self._send(429, {"error": "MODEL_BUSY"})
            try:
                response = completion(state, payload)
                state["completed_generation_count"] += 1
            except (ValueError, TypeError, KeyError) as error:
                log_failure(error)
                return self._send(422, {"error": request_failure_code(error)})
            except Exception as error:
                log_failure(error)
                return self._send(500, {"error": "GENERATION_FAILED"})
            finally:
                state["slot"].release()
            self._send(200, response)

    return Handler


def request_failure_code(error):
    """Expose only the actionable context limit, never arbitrary exception text."""
    return (
        "CONTEXT_BUDGET_EXCEEDED"
        if isinstance(error, ValueError) and str(error) == "CONTEXT_BUDGET_EXCEEDED"
        else "REQUEST_REJECTED"
    )


def log_failure(error):
    """Local diagnostics contain no request text, tokens, source or credentials."""
    code = str(error)
    print(
        canonical_json(
            {
                "event": "PROPOSAL_FAILURE",
                "type": type(error).__name__,
                "code": code if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", code) else None,
                "frames": [
                    {"file": Path(frame.filename).name, "line": frame.lineno}
                    for frame in traceback.extract_tb(error.__traceback__)[-6:]
                ],
            }
        ),
        flush=True,
    )


def generation_timeout(value):
    """Keep cooperative generation and the client wait finite and explicit."""
    try:
        seconds = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("generation timeout must be an integer") from error
    if not 30 <= seconds <= 540:
        raise argparse.ArgumentTypeError("generation timeout must be between 30 and 540 seconds")
    return seconds


def context_limits(sequence: int, output: int) -> tuple[int, int]:
    if (
        type(sequence) is not int
        or type(output) is not int
        or not 1024 <= sequence <= 131072
        or not 128 <= output <= 16384
        or output >= sequence
    ):
        raise ValueError("MODEL_CONTEXT_LIMITS_INVALID")
    return sequence, output


def main():
    global MAX_SEQUENCE, MAX_OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--model-repository")
    parser.add_argument("--model-revision")
    parser.add_argument("--proposer-adapter", type=Path)
    parser.add_argument("--proposer-weights-sha256")
    parser.add_argument("--proposer-config-sha256")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--max-sequence-length", type=int, default=MAX_SEQUENCE)
    parser.add_argument("--max-output-tokens", type=int, default=MAX_OUTPUT)
    parser.add_argument(
        "--generation-timeout-seconds", type=generation_timeout, default=MAX_GENERATION_SECONDS
    )
    args = parser.parse_args()
    MAX_SEQUENCE, MAX_OUTPUT = context_limits(args.max_sequence_length, args.max_output_tokens)
    repository, revision = selected_model(args.model_repository, args.model_revision)
    adapter_files = verify_proposer_adapter(
        args.proposer_adapter,
        args.proposer_weights_sha256,
        args.proposer_config_sha256,
        repository=repository,
        revision=revision,
    )
    directory = args.output_directory.resolve()
    # New directory per launch; never overwrite previous credentials or observations.
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    # Unsloth creates a relative compilation cache; keep it in the existing ignored
    # training boundary, not beside application source or evaluation reports.
    os.chdir(ROOT / "environments/training")
    print("Loading the exact cached proposal base model (offline).", flush=True)
    torch, model, tokenizer, evidence = load_model(repository, revision)
    if adapter_files:
        from peft import PeftModel
        from unsloth import FastLanguageModel

        model = PeftModel.from_pretrained(
            model,
            args.proposer_adapter,
            adapter_name="proposer",
            is_trainable=False,
            local_files_only=True,
        )
        FastLanguageModel.for_inference(model)
        model.requires_grad_(False)
        verify_proposer_adapter(
            args.proposer_adapter,
            args.proposer_weights_sha256,
            args.proposer_config_sha256,
            repository=repository,
            revision=revision,
        )
    schema_processor = build_schema_processor_factory(tokenizer, torch, model.config.vocab_size)
    configuration = {
        "runtime_id": f"proposal-base-{uuid4()}",
        "supported_tasks": sorted(SOURCE_TASKS if args.source_only else TASKS),
        "model": repository,
        "revision": revision,
        "max_sequence": MAX_SEQUENCE,
        "max_output": MAX_OUTPUT,
        "max_generation_seconds": args.generation_timeout_seconds,
        "load_in_4bit": True,
        "loader_evidence": evidence,
        "adapter_loaded": bool(adapter_files),
        "adapter_files": adapter_files,
        "adapter_name": "proposer" if adapter_files else None,
        "network_authorized": False,
        "server_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_decoding": SCHEMA_DECODING,
        "schema_decoder_version": LLGUIDANCE_VERSION,
        "schema_decoder_sha256": hashlib.sha256(
            (ROOT / "src/orchestwin/models/schema_decoding.py").read_bytes()
        ).hexdigest(),
        "proposal_dependencies_sha256": hashlib.sha256(
            (ROOT / "environments/training/requirements-proposals.txt").read_bytes()
        ).hexdigest(),
        "loader_sha256": hashlib.sha256(
            (ROOT / "environments/training/run_model_spike.py").read_bytes()
        ).hexdigest(),
        "training_lock_sha256": hashlib.sha256(
            (ROOT / "environments/training/uv.lock").read_bytes()
        ).hexdigest(),
    }
    identity = ModelRuntimeIdentity(
        provider_id="local-proposal-model",
        runtime_id=configuration["runtime_id"],
        base_model_repository=repository,
        base_model_revision=revision,
        tokenizer_revision=revision,
        configuration_sha256=snapshot_content_hash(configuration),
        adapter_id="interactive-proposer-" + args.proposer_weights_sha256[:16]
        if adapter_files
        else None,
        adapter_sha256=snapshot_content_hash(adapter_files) if adapter_files else None,
    )
    token = secrets.token_urlsafe(48)
    token_file = directory / "access-token.secret"
    with token_file.open("x", encoding="ascii") as stream:
        stream.write(token)
    token_file.chmod(0o600)
    state = {
        "torch": torch,
        "model": model,
        "tokenizer": tokenizer,
        "schema_processor": schema_processor,
        "identity": identity,
        "model_name": "qwen3-4b-proposals"
        if (repository, revision) == (MODEL, REVISION)
        else repository,
        "slot": threading.BoundedSemaphore(1),
        "completed_generation_count": 0,
        "max_generation_seconds": args.generation_timeout_seconds,
        "shared_adapter_loaded": bool(adapter_files),
        "adapter_name": "proposer" if adapter_files else None,
        "supported_tasks": configuration["supported_tasks"],
    }
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(state, token))
    server.daemon_threads = True
    runtime = {
        "schema_version": 1,
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "model_name": state["model_name"],
        "identity": identity.to_snapshot(),
        "token_file": str(token_file),
        "temperature": 0.6,
        "max_output_tokens": MAX_OUTPUT,
        "timeout_seconds": args.generation_timeout_seconds + 60,
    }
    (directory / "loader.json").write_text(canonical_json(configuration), encoding="utf-8")
    (directory / "runtime.json").write_text(canonical_json(runtime), encoding="utf-8")
    print(str(directory / "runtime.json"), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        (directory / "stopped.json").write_text(json.dumps({"runtime_id": identity.runtime_id}))


if __name__ == "__main__":
    main()
