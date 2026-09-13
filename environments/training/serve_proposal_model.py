#!/usr/bin/env python3
"""Offline, authenticated loopback serving for proposal adapters; no training.

Uses the existing WSL/Unsloth environment and exact cached Qwen base revision.
JSON schemas are model-visible instructions; the application validates outputs.
This operator does not load the specialized final-evaluator LoRA adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.proposal_tasks import TASKS  # noqa: E402
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
MAX_BODY = 2_000_000


def health_snapshot(state):
    return {
        "health_contract_version": 2,
        "status": "READY",
        "model_name": state["model_name"],
        "model_identity": state["identity"].to_snapshot(),
        "supported_tasks": sorted(TASKS),
        "max_sequence_length": MAX_SEQUENCE,
        "max_output_tokens": MAX_OUTPUT,
        "completed_generation_count": state["completed_generation_count"],
        "adapter_loaded": False,
        "training_executed": False,
        "fallback_policy": "FAIL_CLOSED_NO_FAKE_FALLBACK",
    }


def load_model():
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
            "model_repository": MODEL,
            "model_revision": REVISION,
            "tokenizer_repository": MODEL,
            "tokenizer_revision": REVISION,
            "generation": {"seed": 42, "max_sequence_length": MAX_SEQUENCE},
        },
        network_authorized=False,
    )
    if getattr(model, "peft_config", None) or evidence["observed_model_revision"] != REVISION:
        raise RuntimeError("exact base-model identity was not observed")
    return torch, model, tokenizer, evidence


def completion(state, payload):
    if payload.get("model") != state["model_name"]:
        raise ValueError("MODEL_MISMATCH")
    metadata = payload.get("metadata", {})
    if metadata.get("expected_model_identity") != state["identity"].to_snapshot():
        raise ValueError("IDENTITY_MISMATCH")
    if metadata.get("orchestwin_task_id") not in {f"proposal-{task}-v1" for task in TASKS}:
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
    torch, model, tokenizer = state["torch"], state["model"], state["tokenizer"]
    encoded = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt", return_dict=True
    )
    inputs = {key: value.to(model.device) for key, value in encoded.items()}
    input_tokens = inputs["input_ids"].shape[-1]
    if input_tokens + maximum > MAX_SEQUENCE:
        raise ValueError("CONTEXT_BUDGET_EXCEEDED")
    options = {"do_sample": temperature > 0}
    if temperature > 0:
        options["temperature"] = temperature
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=maximum,
            use_cache=True,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
            **options,
        )
    tokens = generated[0, input_tokens:]
    # Preserve model text: no trimming, JSON repair, fallback or regeneration.
    content = tokenizer.decode(tokens, skip_special_tokens=True)
    eos = tokenizer.eos_token_id
    eos_ids = {eos} if isinstance(eos, int) else set(eos or ())
    finished = len(tokens) > 0 and int(tokens[-1]) in eos_ids
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
            "output_repair_used": False,
            "adapter_loaded": False,
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
            except (ValueError, TypeError, KeyError):
                return self._send(422, {"error": "REQUEST_REJECTED"})
            except Exception:
                return self._send(500, {"error": "GENERATION_FAILED"})
            finally:
                state["slot"].release()
            self._send(200, response)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    # New directory per launch; never overwrite previous credentials or observations.
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    # Unsloth creates a relative compilation cache; keep it in the existing ignored
    # training boundary, not beside application source or evaluation reports.
    os.chdir(ROOT / "environments/training")
    print("Loading the exact cached proposal base model (offline).", flush=True)
    torch, model, tokenizer, evidence = load_model()
    configuration = {
        "runtime_id": f"proposal-base-{uuid4()}",
        "model": MODEL,
        "revision": REVISION,
        "max_sequence": MAX_SEQUENCE,
        "max_output": MAX_OUTPUT,
        "load_in_4bit": True,
        "loader_evidence": evidence,
        "adapter_loaded": False,
        "network_authorized": False,
        "server_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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
        base_model_repository=MODEL,
        base_model_revision=REVISION,
        tokenizer_revision=REVISION,
        configuration_sha256=snapshot_content_hash(configuration),
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
        "identity": identity,
        "model_name": "qwen3-4b-proposals",
        "slot": threading.BoundedSemaphore(1),
        "completed_generation_count": 0,
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
        "timeout_seconds": 180,
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
