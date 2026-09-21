#!/usr/bin/env python3
"""Opt-in local serving of the frozen S67 User Twin evaluator; no training.

Repository-owned local operator, NOT a public production server. It uses the
existing WSL training interpreter and verifies an explicitly selected committed
source snapshot. Startup loads verified weights and checks HTTP authentication;
it performs no generation. Every restart creates new records and credentials.
The v1 source and observations remain unchanged.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import logging
import math
import os
import platform
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

RESTART_BASE_COMMIT = "2bfe813da9b78d9b309951b85d6dcdc0e9f14d50"
RUNTIME_ID = "s67-final-evaluator-serving-v2"
RESTART_POLICY = "EXPLICIT_COMMIT_AND_COMMITTED_FILES_V1"
SERVER_REL = "environments/training/serve_final_evaluator.py"
BRANCH = "sprint/12-case-studies-expert-evaluation"
MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
ADAPTER_DIGEST = "82e051affb54f7fdced4c85780f8724fcc8f47063e27997bb6f5624421422664"
WEIGHTS_DIGEST = "c9e50dd95f0eb60fb750022c859af8c9d7964a750376736f8bab9af299a8d648"
MODEL_NAME = "ut-evaluator-s67-final"
TRAINING_REL = "environments/training/artifacts/thesis-training/s67-r2-final-qlora-20260905T210557Z-qhCJDx/training-run"
SPIKE_REL = "environments/training/run_model_spike.py"
SPIKE_GIT_BLOB = "5cbd0c6d2c832630aa2f357eae9b8c8ebcc7e25f"
LOCK_REL = "environments/training/uv.lock"
LORA_PARAMETERS = 33030144
MAX_BODY = 2000000
MAX_SEQUENCE = 4096
MAX_TOKENS = 1024
PACKAGES = {
    "torch": "2.11.0",
    "transformers": "5.5.0",
    "peft": "0.20.0",
    "unsloth": "2026.8.22",
    "unsloth_zoo": "2026.8.16",
    "bitsandbytes": "0.50.2",
    "safetensors": "0.8.0",
    "accelerate": "1.14.0",
}


class ServingError(RuntimeError):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code = code
        self.status = status


def ensure(condition, code, status=422):
    if not condition:
        raise ServingError(code, status)


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest_json(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    value = {}
    for name, item in pairs:
        ensure(name not in value, "DUPLICATE_JSON_KEY")
        value[name] = item
    return value


def _nonfinite(_value):
    raise ServingError("NONFINITE_JSON")


def json_object(raw: bytes) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        ensure(isinstance(value, dict), "JSON_OBJECT_REQUIRED")
        canonical(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ServingError("INVALID_JSON") from None


def safe_path(path: Path) -> None:
    ensure(".." not in path.parts, "PARENT_PATH_NOT_ALLOWED")
    ensure(
        not any(
            p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
            for p in (path, *path.parents)
        ),
        "REDIRECTED_PATH",
    )


def read_regular(path: Path, limit: int) -> bytes:
    safe_path(path)
    ensure(path.is_file() and path.stat().st_size <= limit, "FILE_MISSING_OR_TOO_LARGE")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    ensure(len(raw) <= limit, "FILE_TOO_LARGE")
    return raw


def directory_digest(root: Path):
    """Same relative-path/NUL/file-bytes/NUL digest as run_thesis_qlora.py."""
    safe_path(root)
    ensure(root.is_dir(), "FINAL_ADAPTER_DIRECTORY_MISSING")
    paths = sorted(root.rglob("*"), key=lambda p: p.as_posix())
    ensure(len(paths) <= 100, "ADAPTER_FILE_COUNT_EXCEEDED")
    total = 0
    digest = hashlib.sha256()
    inventory = []
    for path in paths:
        safe_path(path)
        if path.is_dir():
            continue
        ensure(path.is_file(), "ADAPTER_NONREGULAR_ENTRY")
        size = path.stat().st_size
        total += size
        ensure(total <= 512 * 1024 * 1024, "ADAPTER_SIZE_EXCEEDED")
        name = path.relative_to(root).as_posix()
        digest.update(name.encode("utf-8") + b"\x00")
        file_digest = hashlib.sha256()
        actual = 0
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                actual += len(chunk)
                ensure(actual <= size, "ADAPTER_CHANGED_DURING_READ")
                digest.update(chunk)
                file_digest.update(chunk)
        ensure(actual == size, "ADAPTER_CHANGED_DURING_READ")
        digest.update(b"\x00")
        inventory.append({"path": name, "size_bytes": size, "sha256": file_digest.hexdigest()})
    return (digest.hexdigest(), inventory)


def verify_artifacts(training_root: Path):
    raw = read_regular(training_root / "final-result.json", 4 * 1024 * 1024)
    report = json_object(raw)
    body = {k: v for k, v in report.items() if k != "content_hash"}
    ensure(report.get("content_hash") == digest_json(body), "FINAL_RESULT_HASH_MISMATCH")
    for field, expected in {
        "status": "FINAL_QLORA_TRAINING_SUCCEEDED",
        "global_step": 4814,
        "base_model_repository": MODEL,
        "base_model_revision": REVISION,
        "adapter_relative_path": "adapter-best",
        "adapter_sha256": ADAPTER_DIGEST,
        "trainable_lora_parameters": LORA_PARAMETERS,
    }.items():
        ensure(report.get(field) == expected, "FINAL_RESULT_IDENTITY_MISMATCH")
    adapter = training_root / "adapter-best"
    observed, inventory = directory_digest(adapter)
    ensure(observed == ADAPTER_DIGEST, "FINAL_ADAPTER_HASH_MISMATCH")
    ensure(inventory == report.get("adapter_inventory"), "FINAL_ADAPTER_INVENTORY_MISMATCH")
    weights = next((x for x in inventory if x["path"] == "adapter_model.safetensors"), None)
    ensure(
        weights is not None and weights["sha256"] == WEIGHTS_DIGEST,
        "FINAL_ADAPTER_WEIGHTS_MISMATCH",
    )
    ensure(
        not any((adapter / f).exists() for f in ("adapter_model.bin", "pytorch_model.bin")),
        "UNSAFE_ADAPTER_SERIALIZATION",
    )
    config = json_object(read_regular(adapter / "adapter_config.json", 1000000))
    ensure(
        config.get("peft_type") == "LORA" and config.get("task_type") == "CAUSAL_LM",
        "FINAL_ADAPTER_CONFIGURATION_MISMATCH",
    )
    return (
        adapter,
        {
            "adapter_sha256": observed,
            "adapter_weights_sha256": weights["sha256"],
            "training_result_sha256": hashlib.sha256(raw).hexdigest(),
            "training_result_content_hash": report["content_hash"],
        },
    )


def require_no_training_grants():
    for key, value in os.environ.items():
        if (
            key.startswith("ORCHESTWIN_")
            and key.endswith(("ALLOW_TRAINING", "ALLOW_NETWORK"))
            and (value.casefold() in {"1", "true", "yes", "on"})
        ):
            raise ServingError("TRAINING_OR_DOWNLOAD_GRANT_MUST_BE_CLEARED")
    ensure(os.environ.get("WORLD_SIZE", "1") == "1", "DISTRIBUTED_RUNTIME_NOT_SUPPORTED")


def git(root, *arguments):
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=20,
    )
    ensure(result.returncode == 0, "GIT_CHECK_FAILED")
    return result.stdout


def check_repository(root: Path, expected_commit: str) -> dict:
    """Bind startup to the owner's exact commit, not a silently chosen latest ref."""
    ensure(
        isinstance(expected_commit, str)
        and re.fullmatch("[0-9a-f]{40}", expected_commit) is not None,
        "EXPECTED_COMMIT_REQUIRED",
    )
    ensure(git(root, "rev-parse", "HEAD").decode().strip() == expected_commit, "UNEXPECTED_HEAD")
    ensure(git(root, "branch", "--show-current").decode().strip() == BRANCH, "UNEXPECTED_BRANCH")
    ensure(not git(root, "status", "--porcelain").strip(), "WORKING_TREE_NOT_CLEAN")
    git(root, "merge-base", "--is-ancestor", RESTART_BASE_COMMIT, expected_commit)
    ensure(Path(__file__).absolute() == root / SERVER_REL, "USE_REPOSITORY_SERVING_SCRIPT")
    files = []
    for relative, limit in ((SERVER_REL, 100000), (SPIKE_REL, 100000), (LOCK_REL, 2000000)):
        committed = git(root, "show", f"{expected_commit}:{relative}")
        blob = hashlib.sha1(
            b"blob " + str(len(committed)).encode() + b"\x00" + committed
        ).hexdigest()
        local = read_regular(root / relative, limit)
        ensure(
            local.replace(b"\r\n", b"\n") == committed.replace(b"\r\n", b"\n"),
            "RUNTIME_SOURCE_NOT_COMMITTED",
        )
        if relative == SPIKE_REL:
            ensure(blob == SPIKE_GIT_BLOB, "FROZEN_PROMPT_LOADER_CHANGED")
        files.append(
            {
                "path": relative,
                "git_blob": blob,
                "sha256": hashlib.sha256(local).hexdigest(),
                "size_bytes": len(local),
            }
        )
    return {
        "policy": RESTART_POLICY,
        "base_commit": RESTART_BASE_COMMIT,
        "commit": expected_commit,
        "tree": git(root, "rev-parse", f"{expected_commit}^{{tree}}").decode().strip(),
        "files": files,
    }


def build_configuration(
    source_record: dict, packages: dict, artifact_info: dict, observation: dict
) -> dict:
    """Record the actual startup source independently of the unchanged model weights."""
    inventory = {item["path"]: item for item in source_record["files"]}
    return {
        "serving_contract_version": 2,
        "runtime_id": RUNTIME_ID,
        "source_verification": source_record,
        "operator_script_sha256": inventory[SERVER_REL]["sha256"],
        "platform_commit": source_record["commit"],
        "package_versions": packages,
        "training_lock_sha256": inventory[LOCK_REL]["sha256"],
        "prompt_builder_sha256": inventory[SPIKE_REL]["sha256"],
        **artifact_info,
        "model_name": MODEL_NAME,
        "max_sequence_length": MAX_SEQUENCE,
        "max_output_tokens": MAX_TOKENS,
        "seed": 20260904,
        "temperature": 0,
        "generation_max_time_seconds": 60,
        "max_concurrency": 1,
        "quantization_observed": observation["quantization"],
        "prompt_metadata_policy": "EXPLICIT_TASK_AND_EVIDENCE_REFS_NO_BENCHMARK_LOOKUP",
    }


def package_metadata():
    installed = {}
    for name, expected in PACKAGES.items():
        try:
            installed[name] = version(name)
        except PackageNotFoundError:
            raise ServingError("WRONG_INFERENCE_INTERPRETER_PACKAGE_MISSING") from None
        ensure(installed[name] == expected, "INFERENCE_PACKAGE_VERSION_CHANGED")
    return installed


def _local_host(host) -> bool:
    if host in ("localhost", b"localhost"):
        return True
    try:
        return ipaddress.ip_address(host.decode() if isinstance(host, bytes) else host).is_loopback
    except (ValueError, TypeError):
        return False


class NetworkGuard:
    """Python audit guard, not a kernel/network-namespace sandbox."""

    def __init__(self):
        self.blocked = 0

    def __call__(self, event, args):
        host = None
        if event in {"socket.connect", "socket.sendto"}:
            address = args[-1]
            if isinstance(address, tuple) and address:
                host = address[0]
        elif event == "socket.getaddrinfo":
            host = args[0]
        if host is not None and (not _local_host(host)):
            self.blocked += 1
            raise OSError("OUTBOUND_NETWORK_BLOCKED")


def configure_offline_caches(output: Path):
    home = Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))).absolute()
    cache = Path(
        os.environ.get("HF_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE", str(home / "hub")))
    ).absolute()
    snapshot = cache / "models--Qwen--Qwen3-4B-Instruct-2507" / "snapshots" / REVISION
    ensure(snapshot.is_dir(), "EXACT_BASE_REVISION_NOT_IN_LOCAL_CACHE")
    runtime_cache = output / "runtime-cache"
    runtime_cache.mkdir(mode=0o700)
    os.environ.update(
        {
            "HF_HOME": str(home),
            "HF_HUB_CACHE": str(cache),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "UNSLOTH_DISABLE_STATISTICS": "1",
            "TORCHINDUCTOR_CACHE_DIR": str(runtime_cache / "inductor"),
            "TRITON_CACHE_DIR": str(runtime_cache / "triton"),
            "TORCH_EXTENSIONS_DIR": str(runtime_cache / "extensions"),
            "UNSLOTH_COMPILE_LOCATION": str(runtime_cache / "unsloth_compiled_cache"),
        }
    )
    os.chdir(runtime_cache)
    return cache


def load_spike(root: Path):
    path = root / SPIKE_REL
    spec = importlib.util.spec_from_file_location("orchestwin_final_serving_prompt", path)
    ensure(spec is not None and spec.loader is not None, "PROMPT_MODULE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_final_model(spike, adapter: Path):
    """Use the known Unsloth -> Torch -> Transformers order, then frozen PEFT."""
    torch, _tokenizer_class, fast_model = spike._load_runtime_dependencies()
    ensure(torch.cuda.is_available() and torch.cuda.device_count() == 1, "ONE_CUDA_GPU_REQUIRED")
    ensure(torch.cuda.is_bf16_supported(), "BF16_CUDA_REQUIRED")
    from peft import PeftModel
    from transformers import BitsAndBytesConfig

    torch.manual_seed(20260904)
    torch.cuda.manual_seed_all(20260904)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.monotonic()
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    kwargs = {
        "model_name": MODEL,
        "revision": REVISION,
        "max_seq_length": MAX_SEQUENCE,
        "dtype": torch.bfloat16,
        "load_in_4bit": True,
        "trust_remote_code": False,
        "local_files_only": True,
        "use_exact_model_name": True,
        "fast_inference": False,
        "quantization_config": quantization,
    }
    base, tokenizer = fast_model.from_pretrained(
        **spike._supported_kwargs(fast_model.from_pretrained, kwargs)
    )
    ensure(spike._observed_revision(base) == REVISION, "LOADED_BASE_REVISION_MISMATCH")
    ensure(getattr(base, "is_loaded_in_4bit", False) is True, "FOUR_BIT_LOAD_NOT_OBSERVED")
    q = getattr(base.config, "quantization_config", None)
    q = q.to_dict() if hasattr(q, "to_dict") else q
    ensure(isinstance(q, dict), "QUANTIZATION_NOT_OBSERVED")
    for key, expected in {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
    }.items():
        ensure(q.get(key) == expected, "QUANTIZATION_MISMATCH")
    tokenizer_observed = spike._observed_revision(tokenizer)
    ensure(tokenizer_observed in (None, REVISION), "TOKENIZER_REVISION_MISMATCH")
    fast_model.for_inference(base)
    model = PeftModel.from_pretrained(base, str(adapter), is_trainable=False, local_files_only=True)
    model.eval()
    active = getattr(model, "active_adapters", None)
    if isinstance(active, str):
        active = [active]
    ensure(
        active == ["default"] and set(model.peft_config) == {"default"}, "FINAL_ADAPTER_NOT_ACTIVE"
    )
    total = sum((p.numel() for name, p in model.named_parameters() if "lora_" in name))
    trainable = sum((p.numel() for _name, p in model.named_parameters() if p.requires_grad))
    ensure(total == LORA_PARAMETERS and trainable == 0, "INFERENCE_PARAMETER_STATE_INVALID")
    ensure(bool(getattr(tokenizer, "chat_template", None)), "TOKENIZER_CHAT_TEMPLATE_MISSING")
    if tokenizer.pad_token_id is None:
        ensure(tokenizer.eos_token_id is not None, "TOKENIZER_SPECIAL_IDS_MISSING")
        tokenizer.pad_token = tokenizer.eos_token
    torch.cuda.synchronize()
    info = {
        "base_revision_observed": REVISION,
        "tokenizer_revision_observed": tokenizer_observed,
        "tokenizer_revision_basis": "TOKENIZER_METADATA"
        if tokenizer_observed
        else "EXACT_LOADER_REQUEST",
        "active_adapters": active,
        "lora_parameters": total,
        "trainable_parameters": trainable,
        "load_in_4bit_observed": True,
        "quantization": q,
        "cuda_device_count": torch.cuda.device_count(),
        "gpu_name": torch.cuda.get_device_name(0),
        "load_seconds": round(time.monotonic() - started, 3),
        "peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1024**2),
    }
    return (torch, model, tokenizer, info)


def parse_request(payload, identity):
    ensure(isinstance(payload, dict), "REQUEST_OBJECT_REQUIRED")
    ensure(payload.get("model") == MODEL_NAME, "MODEL_NOT_SERVED")
    ensure(payload.get("stream", False) is False, "STREAMING_NOT_SUPPORTED")
    ensure(
        not set(payload)
        - {
            "model",
            "messages",
            "temperature",
            "max_tokens",
            "response_format",
            "metadata",
            "stream",
        },
        "UNKNOWN_REQUEST_FIELDS",
    )
    temp = payload.get("temperature")
    ensure(
        type(temp) in (int, float) and temp == 0 and math.isfinite(temp),
        "TEMPERATURE_ZERO_REQUIRED",
    )
    maximum = payload.get("max_tokens")
    ensure(type(maximum) is int and 1 <= maximum <= MAX_TOKENS, "MAX_TOKENS_INVALID")
    messages = payload.get("messages")
    ensure(isinstance(messages, list) and len(messages) == 2, "TWO_MESSAGES_REQUIRED")
    for item, role in zip(messages, ("system", "user"), strict=True):
        ensure(
            isinstance(item, dict)
            and set(item) == {"role", "content"}
            and (item["role"] == role)
            and isinstance(item["content"], str)
            and (0 < len(item["content"]) <= 300000),
            "INVALID_MESSAGES",
        )
    input_payload = json_object(messages[1]["content"].encode())
    fmt = payload.get("response_format")
    ensure(isinstance(fmt, dict) and fmt.get("type") == "json_schema", "JSON_SCHEMA_REQUIRED")
    schema = fmt.get("json_schema")
    ensure(
        isinstance(schema, dict)
        and schema.get("strict") is True
        and isinstance(schema.get("schema"), dict),
        "STRICT_SCHEMA_REQUIRED",
    )
    metadata = payload.get("metadata")
    ensure(isinstance(metadata, dict), "METADATA_REQUIRED")
    ensure(metadata.get("expected_model_identity") == identity, "IDENTITY_MISMATCH", 409)
    task_id = metadata.get("orchestwin_task_id")
    refs = metadata.get("allowed_evidence_refs")
    ensure(
        isinstance(task_id, str) and re.fullmatch("[A-Za-z][A-Za-z0-9._-]{0,127}", task_id),
        "EXPLICIT_TASK_METADATA_REQUIRED",
    )
    ensure(
        isinstance(refs, list)
        and len(refs) <= 128
        and all(isinstance(x, str) and 0 < len(x) <= 256 and (x.strip() == x) for x in refs),
        "EXPLICIT_EVIDENCE_METADATA_REQUIRED",
    )
    ensure(len(refs) == len(set(refs)), "DUPLICATE_EVIDENCE_REFERENCES")
    return {
        "system": messages[0]["content"],
        "input_json": canonical(input_payload).decode(),
        "schema_json": canonical(schema["schema"]).decode(),
        "task_id": task_id,
        "refs": tuple(refs),
        "max_tokens": maximum,
    }


class ModelRuntime:
    def __init__(self, spike, torch, model, tokenizer, identity, observation, guard):
        self.spike, self.torch, self.model, self.tokenizer = (spike, torch, model, tokenizer)
        self.identity, self.observation, self.guard = (identity, observation, guard)
        self.slot = threading.Lock()
        self.counters = threading.Lock()
        self.completed = 0

    def snapshot(self):
        with self.counters:
            count = self.completed
        return {
            "status": "FINAL_EVALUATOR_READY",
            "model_name": MODEL_NAME,
            "model_identity": self.identity,
            "load_observation": self.observation,
            "completed_generation_count": count,
            "max_concurrency": 1,
            "outbound_python_socket_attempts_blocked": self.guard.blocked,
            "network_sandbox": "PYTHON_AUDIT_ONLY_NOT_KERNEL_ISOLATION",
            "fallback_policy": "FAIL_CLOSED_NO_BASE_FALLBACK",
            "training_executed": False,
            "benchmark_reexecuted": False,
            "formal_run_started": False,
            "backend_provider_wired": False,
            "production_deployment": False,
            "schema_decoding": "PROMPTED_NOT_CONSTRAINED_OUTPUT_MUST_BE_VALIDATED",
            "generation_watchdog": "COOPERATIVE_60_SECONDS_NOT_HARD_GPU_PREEMPTION",
        }

    def generate(self, payload):
        args = parse_request(payload, self.identity)
        ensure(self.slot.acquire(blocking=False), "GENERATION_SLOT_BUSY", 429)
        try:
            prompt = SimpleNamespace(
                task_id=args["task_id"],
                input_payload_json=args["input_json"],
                output_schema=SimpleNamespace(canonical_schema_json=args["schema_json"]),
                allowed_evidence_refs=args["refs"],
                system_instruction=args["system"],
            )
            messages = self.spike._create_chat_messages(prompt)
            control = SimpleNamespace(
                mode=self.spike.CandidateChatTemplateControlMode.DEFAULT_NON_THINKING
            )
            inputs = self.spike._prepare_inputs(self.tokenizer, messages, self.torch, control)
            input_tokens = int(inputs["input_ids"].shape[-1])
            ensure(input_tokens + args["max_tokens"] <= MAX_SEQUENCE, "SEQUENCE_LIMIT_EXCEEDED")
            self.torch.cuda.synchronize()
            started = time.monotonic()
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **inputs,
                    max_new_tokens=args["max_tokens"],
                    do_sample=False,
                    use_cache=True,
                    max_time=60.0,
                    pad_token_id=self.tokenizer.pad_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            self.torch.cuda.synchronize()
            elapsed = time.monotonic() - started
            ensure(elapsed < 60.0, "GENERATION_TIME_LIMIT", 504)
            tokens = self.spike._generated_sequences(generated)[0, input_tokens:]
            count = int(tokens.shape[-1])
            raw = self.tokenizer.decode(tokens, skip_special_tokens=True).strip()
            ensure(
                len(raw.encode()) <= MAX_BODY
                and (
                    not re.search(
                        "</?(?:think|analysis|reasoning)(?:\\s[^>]*)?>", raw, re.IGNORECASE
                    )
                ),
                "OUTPUT_REJECTED",
                502,
            )
            finish = "length" if count >= args["max_tokens"] else "stop"
            with self.counters:
                self.completed += 1
            return {
                "id": "orchestwin-s67-" + uuid4().hex,
                "object": "chat.completion",
                "model": MODEL_NAME,
                "model_identity": self.identity,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": finish,
                        "message": {"role": "assistant", "content": raw},
                    }
                ],
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": count,
                    "total_tokens": input_tokens + count,
                },
                "orchestwin_serving": {
                    "latency_milliseconds": round(elapsed * 1000),
                    "model_visible_messages_sha256": digest_json({"messages": list(messages)}),
                    "output_repair_used": False,
                },
            }
        finally:
            self.slot.release()


class LocalServer(ThreadingHTTPServer):
    """Bound the number of HTTP handler threads; only a local operator endpoint."""

    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 4

    def __init__(self, address, handler):
        ensure(address[0] == "127.0.0.1", "LOOPBACK_BIND_REQUIRED")
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        return


def handler_for(runtime, token):

    class Handler(BaseHTTPRequestHandler):
        server_version = "OrchesTwinFinalEvaluator/2"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, _format, *args):
            return

        def send_json(self, code, value):
            raw = canonical(value)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(raw)
            self.close_connection = True

        def authorize(self):
            values = self.headers.get_all("Authorization", [])
            ensure(
                len(values) == 1
                and secrets.compare_digest(
                    values[0].encode("utf-8"), ("Bearer " + token).encode("ascii")
                ),
                "AUTHENTICATION_REQUIRED",
                401,
            )
            ensure(not self.headers.get("Origin"), "BROWSER_ORIGIN_NOT_ALLOWED", 403)

        def body(self):
            ensure(not self.headers.get("Transfer-Encoding"), "CHUNKED_NOT_SUPPORTED", 400)
            lengths = self.headers.get_all("Content-Length", [])
            ensure(
                len(lengths) == 1 and lengths[0].isascii() and lengths[0].isdigit(),
                "CONTENT_LENGTH_REQUIRED",
                400,
            )
            length = int(lengths[0])
            ensure(0 < length <= MAX_BODY, "BODY_LIMIT", 413)
            ensure(
                self.headers.get_content_type() == "application/json",
                "JSON_CONTENT_TYPE_REQUIRED",
                415,
            )
            body = self.rfile.read(length)
            ensure(len(body) == length, "TRUNCATED_REQUEST", 400)
            return json_object(body)

        def dispatch(self, post=False):
            try:
                self.authorize()
                if not post and self.path == "/health":
                    response = runtime.snapshot()
                elif not post and self.path == "/v1/models":
                    response = {
                        "object": "list",
                        "data": [
                            {
                                "id": MODEL_NAME,
                                "object": "model",
                                "model_identity": runtime.identity,
                            }
                        ],
                    }
                elif post and self.path == "/v1/chat/completions":
                    response = runtime.generate(self.body())
                else:
                    raise ServingError("NOT_FOUND", 404)
                self.send_json(200, response)
            except ServingError as error:
                self.send_json(error.status, {"error": {"code": error.code, "message": error.code}})
            except (TimeoutError, ConnectionError):
                with contextlib.suppress(OSError):
                    self.send_json(408, {"error": {"code": "REQUEST_TIMEOUT"}})
            except Exception:
                self.send_json(500, {"error": {"code": "INFERENCE_RUNTIME_ERROR"}})

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch(post=True)

    return Handler


def write_record(path, value):
    report = {**value, "content_hash": digest_json(value)}
    raw = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    with path.open("xb") as handle:
        handle.write(raw)
    return report


def http_health(port, token):
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        headers = {} if token is None else {"Authorization": "Bearer " + token}
        client.request("GET", "/health", headers=headers)
        response = client.getresponse()
        raw = response.read(MAX_BODY + 1)
        ensure(len(raw) <= MAX_BODY, "HEALTH_RESPONSE_TOO_LARGE")
        return (response.status, json_object(raw))
    finally:
        client.close()


def check_ready(path: Path):
    ensure(
        not any((path.parent / name).exists() for name in ("stopped.json", "failure.json")),
        "FINAL_SESSION_TERMINATED",
    )
    ready = json_object(read_regular(path, MAX_BODY))
    ensure(
        ready.get("content_hash")
        == digest_json({k: v for k, v in ready.items() if k != "content_hash"}),
        "READY_FILE_HASH_MISMATCH",
    )
    ensure(ready.get("status") == "FINAL_EVALUATOR_SERVING_READY", "READY_FILE_INVALID")
    ensure(
        ready.get("host") == "127.0.0.1"
        and type(ready.get("port")) is int
        and (1024 <= ready["port"] <= 65535),
        "READY_ENDPOINT_INVALID",
    )
    token = read_regular(path.parent / "access-token.secret", 100).decode().strip()
    ensure(re.fullmatch("[0-9a-f]{64}", token), "TOKEN_FILE_INVALID")
    status, health = http_health(ready["port"], token)
    ensure(
        status == 200 and health.get("model_identity") == ready["model_identity"],
        "LIVE_HEALTH_IDENTITY_MISMATCH",
    )
    print(
        json.dumps(
            {
                "status": "FINAL_EVALUATOR_LIVE_HEALTH_VERIFIED",
                "health": health,
                "generation_performed_by_this_check": False,
            },
            indent=2,
        )
    )


def serve(repo_root: Path, output_root: Path, port: int, expected_commit: str):
    root, output = (repo_root.absolute(), output_root.absolute())
    safe_path(root)
    safe_path(output)
    ensure(
        platform.system() == "Linux" and "microsoft" in platform.release().casefold(),
        "USE_EXISTING_WSL_INFERENCE_ENVIRONMENT",
    )
    ensure(
        sys.version_info[:2] == (3, 13) and sys.prefix != sys.base_prefix,
        "USE_EXISTING_PYTHON_313_VENV",
    )
    ensure(Path(sys.prefix).absolute() == root / "environments/training/.venv", "WRONG_VENV")
    ensure(
        output != root and root not in output.parents and (not output.exists()),
        "OUTPUT_MUST_BE_NEW_AND_EXTERNAL",
    )
    ensure(port == 0 or 1024 <= port <= 65535, "PORT_INVALID")
    require_no_training_grants()
    print("[CHECK_REPOSITORY_AND_INSTALLED_VERSIONS]", flush=True)
    source_record = check_repository(root, expected_commit)
    packages = package_metadata()
    print("[VERIFY_FINAL_S67_ADAPTER_READ_ONLY]", flush=True)
    adapter, artifact_info = verify_artifacts(root / TRAINING_REL)
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    stage = "OFFLINE_CACHE_SETUP"
    server = None
    thread = None
    started = datetime.now(UTC).isoformat()
    original_cwd = Path.cwd()
    try:
        configure_offline_caches(output)
        guard = NetworkGuard()
        sys.addaudithook(guard)
        stage = "IMPORT_AND_LOAD_FINAL_MODEL"
        print("[LOAD_FINAL_ADAPTER_ON_CUDA] No training. Loader log stays local.", flush=True)
        with (
            (output / "load.private.log").open("x", encoding="utf-8", buffering=1) as logfile,
            contextlib.redirect_stdout(logfile),
            contextlib.redirect_stderr(logfile),
        ):
            try:
                spike = load_spike(root)
                torch, model, tokenizer, observation = load_final_model(spike, adapter)
            except BaseException:
                import traceback

                traceback.print_exc()
                raise
        stage = "VERIFY_LOADED_ARTIFACTS_AND_REPOSITORY"
        ensure(directory_digest(adapter)[0] == ADAPTER_DIGEST, "ADAPTER_CHANGED_DURING_LOAD")
        ensure(
            check_repository(root, expected_commit) == source_record, "SOURCE_CHANGED_DURING_LOAD"
        )
        ensure(guard.blocked == 0, "OUTBOUND_NETWORK_ATTEMPT_DURING_LOAD")
        configuration = build_configuration(source_record, packages, artifact_info, observation)
        identity = spike.ModelRuntimeIdentity(
            provider_id="huggingface-local",
            runtime_id=RUNTIME_ID,
            base_model_repository=MODEL,
            base_model_revision=REVISION,
            tokenizer_revision=REVISION,
            configuration_sha256=digest_json(configuration),
            adapter_id="s67-final-user-twin-evaluator",
            adapter_sha256=ADAPTER_DIGEST,
        ).to_snapshot()
        state = ModelRuntime(spike, torch, model, tokenizer, identity, observation, guard)
        token = secrets.token_hex(32)
        descriptor = os.open(
            output / "access-token.secret", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
        stage = "BIND_LOOPBACK_HTTP"
        server = LocalServer(("127.0.0.1", port), handler_for(state, token))
        thread = threading.Thread(
            target=server.serve_forever, name="orchestwin-final-serving", daemon=True
        )
        thread.start()
        stage = "AUTHENTICATED_HTTP_HEALTH"
        ensure(
            http_health(server.server_port, None)[0] == 401, "UNAUTHENTICATED_HEALTH_NOT_REJECTED"
        )
        code, health = http_health(server.server_port, token)
        ensure(
            code == 200 and health.get("model_identity") == identity, "HEALTH_VERIFICATION_FAILED"
        )
        write_record(output / "configuration.json", configuration)
        ready = write_record(
            output / "ready.json",
            {
                "status": "FINAL_EVALUATOR_SERVING_READY",
                "report_type": "LOCAL_FINAL_MODEL_SERVING_NOT_FORMAL_EVIDENCE",
                "platform_commit": expected_commit,
                "serving_contract_version": 2,
                "host": "127.0.0.1",
                "port": server.server_port,
                "model_name": MODEL_NAME,
                "model_identity": identity,
                "load_observation": observation,
                "started_at": started,
                "authenticated_health_verified": True,
                "unauthenticated_request_rejected": True,
                "completed_generation_count_at_startup": 0,
                "model_generation_verified": False,
                "training_executed": False,
                "benchmark_reexecuted": False,
                "backend_provider_wired": False,
                "formal_run_started": False,
                "full_workflow_validated": False,
                "credential_file": "access-token.secret",
                "outbound_python_socket_attempts_blocked": guard.blocked,
            },
        )
        print(json.dumps(ready, indent=2, sort_keys=True), flush=True)
        print(f"Ready file: {output / 'ready.json'}", flush=True)
        print("FOREGROUND_SERVER_RUNNING — leave this terminal open; Ctrl+C stops it.", flush=True)
        stage = "SERVING"
        while thread.is_alive():
            thread.join(0.5)
        raise ServingError("SERVER_STOPPED_UNEXPECTEDLY")
    except KeyboardInterrupt:
        if stage != "SERVING":
            raise ServingError("INTERRUPTED_DURING_STARTUP") from None
        print("[STOPPING_FINAL_EVALUATOR]", flush=True)
    except BaseException as error:
        public = {
            "status": "FAILED",
            "stage": stage,
            "code": error.code if isinstance(error, ServingError) else type(error).__name__,
            "training_executed": False,
            "formal_run_started": False,
            "load_log": "load.private.log_DO_NOT_SHARE_UNREVIEWED",
        }
        write_record(output / "failure.json", public)
        raise
    finally:
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        os.chdir(original_cwd)
    write_record(
        output / "stopped.json",
        {
            "status": "STOPPED",
            "finished_at": datetime.now(UTC).isoformat(),
            "training_executed": False,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--serve-final-adapter",
        action="store_true",
        help="Explicitly authorize local CUDA model load and foreground loopback serving.",
    )
    group.add_argument(
        "--check-health",
        action="store_true",
        help="Read live health only; no model imports/generation.",
    )
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--expected-commit", help="Exact committed source authorized for this startup."
    )
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    logging.disable(logging.CRITICAL)
    try:
        if args.check_health:
            ensure(args.ready_file is not None, "READY_FILE_REQUIRED")
            check_ready(args.ready_file.absolute())
        else:
            ensure(
                args.repo_root is not None and args.output_root is not None,
                "REPO_AND_OUTPUT_REQUIRED",
            )
            ensure(args.expected_commit is not None, "EXPECTED_COMMIT_REQUIRED")
            serve(args.repo_root, args.output_root, args.port, args.expected_commit)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "code": error.code if isinstance(error, ServingError) else type(error).__name__,
                    "training_executed": False,
                    "formal_run_started": False,
                }
            ),
            flush=True,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
