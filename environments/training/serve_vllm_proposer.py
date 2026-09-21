#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.proposal_tasks import SOURCE_TASKS, TASKS  # noqa: E402
from orchestwin.models.schema_decoding import POLICY as SCHEMA_DECODING  # noqa: E402
from orchestwin.models.schema_decoding import VERSION as LLGUIDANCE_VERSION  # noqa: E402
from orchestwin.models.schema_decoding import _schema_grammar  # noqa: E402
from orchestwin.models.strict_evaluator_json import strict_json_object  # noqa: E402
from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)

MAX_BODY = 2_000_000
MAX_UPSTREAM_BODY = 8_000_000
PROVIDER_ID = "vllm-proposal-model"


def upstream_json(base_url, path, payload=None, timeout=60):
    request = urllib.request.Request(
        base_url + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_UPSTREAM_BODY + 1)
    if len(raw) > MAX_UPSTREAM_BODY:
        raise ValueError("UPSTREAM_BODY_TOO_LARGE")
    return strict_json_object(raw)


def guided_schema(schema):
    from llguidance import LLMatcher

    grammar = _schema_grammar(schema, LLMatcher.grammar_from_json_schema)
    try:
        grammars = json.loads(grammar)["grammars"]
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("SCHEMA_GRAMMAR_REJECTED") from error
    if len(grammars) != 1 or not isinstance(grammars[0].get("json_schema"), dict):
        raise ValueError("SCHEMA_GRAMMAR_REJECTED")
    return grammars[0]["json_schema"]


def validate_request(state, payload):
    if payload.get("model") != state["model_name"]:
        raise ValueError("MODEL_MISMATCH")
    metadata = payload.get("metadata", {})
    if metadata.get("expected_model_identity") != state["identity"].to_snapshot():
        raise ValueError("IDENTITY_MISMATCH")
    tasks = {f"proposal-{task}-v1" for task in state["supported_tasks"]}
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
    if type(maximum) is not int or not 1 <= maximum <= state["max_output"]:
        raise ValueError("TOKEN_BUDGET_REJECTED")
    if type(temperature) not in (float, int) or not 0 <= temperature <= 2:
        raise ValueError("TEMPERATURE_REJECTED")
    if state["supported_tasks"] == sorted(SOURCE_TASKS) and temperature <= 0:
        raise ValueError("SAMPLED_SOURCE_PROPOSAL_REQUIRED")
    response_format = payload.get("response_format", {})
    specification = response_format.get("json_schema", {})
    schema = specification.get("schema")
    visible = strict_json_object(messages[1]["content"])
    if (
        response_format.get("type") != "json_schema"
        or specification.get("strict") is not True
        or not isinstance(schema, dict)
        or schema != visible.get("output_schema")
    ):
        raise ValueError("SCHEMA_MISMATCH")
    return messages, maximum, float(temperature), schema


def completion(state, payload):
    messages, maximum, temperature, schema = validate_request(state, payload)
    guided = guided_schema(schema)
    started = time.perf_counter()
    upstream_payload = {
        "model": state["upstream_model"],
        "messages": messages,
        "max_tokens": maximum,
        "temperature": temperature,
        "seed": secrets.randbelow(2**31),
        "structured_outputs": {"json": guided},
    }
    try:
        upstream = upstream_json(
            state["upstream"],
            "/v1/chat/completions",
            upstream_payload,
            timeout=state["max_generation_seconds"],
        )
    except urllib.error.HTTPError as error:
        body = error.read(4096).decode("utf-8", errors="replace")
        if error.code in (400, 422) and "maximum context length" in body:
            raise ValueError("CONTEXT_BUDGET_EXCEEDED") from error
        raise ValueError("UPSTREAM_REJECTED") from error
    except (TimeoutError, urllib.error.URLError, OSError) as error:
        raise RuntimeError("UPSTREAM_UNAVAILABLE") from error
    choices = upstream.get("choices")
    usage = upstream.get("usage") or {}
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("UPSTREAM_CHOICES_INVALID")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content")
    finish = choice.get("finish_reason")
    if not isinstance(content, str) or finish not in ("stop", "length"):
        raise RuntimeError("UPSTREAM_COMPLETION_INVALID")
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    if prompt_tokens + maximum > state["max_sequence"]:
        raise ValueError("CONTEXT_BUDGET_EXCEEDED")
    return {
        "id": f"proposal-{uuid4()}",
        "model": state["model_name"],
        "model_identity": state["identity"].to_snapshot(),
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "orchestwin_serving": {
            "model_visible_messages_sha256": snapshot_content_hash(messages),
            "max_sequence_length": state["max_sequence"],
            "max_output_tokens": state["max_output"],
            "precision": state["precision"],
            "output_repair_used": False,
            "adapter_loaded": False,
            "adapter_active": False,
            "adapter_name": None,
            "adapter_role": None,
            "generation_wall_time_budget_seconds": state["max_generation_seconds"],
            "generation_wall_time_milliseconds": round((time.perf_counter() - started) * 1000),
            "schema_decoding": SCHEMA_DECODING,
            "schema_complete": finish == "stop",
            "serving_engine": state["engine"],
        },
    }


def health_snapshot(state):
    return {
        "health_contract_version": 2,
        "status": "READY",
        "model_name": state["model_name"],
        "model_identity": state["identity"].to_snapshot(),
        "supported_tasks": state["supported_tasks"],
        "schema_decoding": SCHEMA_DECODING,
        "schema_decoder_version": state["decoder_version"],
        "max_output_tokens": state["max_output"],
        "max_sequence_length": state["max_sequence"],
        "completed_generation_count": state["completed_generation_count"],
        "adapter_loaded": False,
        "adapter_active": False,
        "adapter_name": None,
        "adapter_role": None,
        "training_executed": False,
        "fallback_policy": "FAIL_CLOSED_NO_FAKE_FALLBACK",
        "precision": state["precision"],
        "generation_watchdog": (
            f"UPSTREAM_TIMEOUT_{state['max_generation_seconds']}_SECONDS_NOT_HARD_GPU_PREEMPTION"
        ),
        "serving_engine": state["engine"],
    }


def request_failure_code(error):
    return (
        "CONTEXT_BUDGET_EXCEEDED"
        if isinstance(error, ValueError) and str(error) == "CONTEXT_BUDGET_EXCEEDED"
        else "REQUEST_REJECTED"
    )


def log_failure(error):
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


def verify_upstream(upstream, model, revision, hf_home):
    models = upstream_json(upstream, "/v1/models")
    served = {item.get("id") for item in models.get("data", []) if isinstance(item, dict)}
    if model not in served:
        raise ValueError("UPSTREAM_MODEL_MISSING")
    snapshot = (
        Path(hf_home) / "hub" / ("models--" + model.replace("/", "--")) / "snapshots" / revision
    )
    if not snapshot.is_dir():
        raise ValueError("MODEL_SNAPSHOT_MISSING")
    return sorted(served)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--upstream", default="http://127.0.0.1:8100")
    parser.add_argument("--model-repository", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--hf-home", default=os.environ.get("HF_HOME", "/workspace/hf-cache"))
    parser.add_argument("--precision", default="bf16")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--max-sequence-length", type=int, default=32768)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--generation-timeout-seconds", type=int, default=540)
    parser.add_argument("--engine", default="vllm")
    parser.add_argument("--engine-version", required=True)
    parser.add_argument("--decoder-version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.model_revision):
        raise SystemExit("MODEL_REVISION_INVALID")
    if not 128 <= args.max_output_tokens < args.max_sequence_length <= 131072:
        raise SystemExit("MODEL_CONTEXT_LIMITS_INVALID")
    from importlib.metadata import version

    if version("llguidance") != LLGUIDANCE_VERSION:
        raise SystemExit("PINNED_LLGUIDANCE_VERSION_REQUIRED")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.decoder_version):
        raise SystemExit("DECODER_VERSION_INVALID")
    decoder_version = args.decoder_version
    engine_version = args.engine_version
    directory = args.output_directory.resolve()
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    served = verify_upstream(
        args.upstream, args.model_repository, args.model_revision, args.hf_home
    )
    supported = sorted(SOURCE_TASKS if args.source_only else TASKS)
    configuration = {
        "runtime_id": f"proposal-base-{uuid4()}",
        "supported_tasks": supported,
        "model": args.model_repository,
        "revision": args.model_revision,
        "max_sequence": args.max_sequence_length,
        "max_output": args.max_output_tokens,
        "max_generation_seconds": args.generation_timeout_seconds,
        "precision": args.precision,
        "engine": args.engine,
        "engine_version": engine_version,
        "upstream_models": served,
        "adapter_loaded": False,
        "network_authorized": False,
        "server_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_decoding": SCHEMA_DECODING,
        "schema_decoder_version": decoder_version,
        "schema_decoder_sha256": hashlib.sha256(
            (ROOT / "src/orchestwin/models/schema_decoding.py").read_bytes()
        ).hexdigest(),
    }
    identity = ModelRuntimeIdentity(
        provider_id=PROVIDER_ID,
        runtime_id=configuration["runtime_id"],
        base_model_repository=args.model_repository,
        base_model_revision=args.model_revision,
        tokenizer_revision=args.model_revision,
        configuration_sha256=snapshot_content_hash(configuration),
        adapter_id=None,
        adapter_sha256=None,
    )
    token = secrets.token_urlsafe(48)
    token_file = directory / "access-token.secret"
    with token_file.open("x", encoding="ascii") as stream:
        stream.write(token)
    token_file.chmod(0o600)
    state = {
        "identity": identity,
        "model_name": args.model_repository,
        "upstream_model": args.model_repository,
        "upstream": args.upstream,
        "supported_tasks": supported,
        "max_sequence": args.max_sequence_length,
        "max_output": args.max_output_tokens,
        "max_generation_seconds": args.generation_timeout_seconds,
        "precision": args.precision,
        "engine": f"{args.engine}-{engine_version}",
        "decoder_version": decoder_version,
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
        "max_output_tokens": args.max_output_tokens,
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
