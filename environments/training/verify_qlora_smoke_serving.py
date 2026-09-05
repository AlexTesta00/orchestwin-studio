#!/usr/bin/env python3
"""Observe bounded local serving evidence for the exact S59 QLoRA smoke adapter."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.openai_compatible import (  # noqa: E402
    OpenAICompatibleLocalConfig,
    OpenAICompatibleLocalStructuredAdapter,
    UrllibOpenAICompatibleTransport,
    _request_payload,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import snapshot_content_hash  # noqa: E402
from orchestwin.training.benchmarking import (  # noqa: E402
    create_benchmark_generation_request,
    score_benchmark_result,
)
from orchestwin.training.qlora_smoke_collation import read_snapshot  # noqa: E402
from orchestwin.training.qlora_smoke_serving import (  # noqa: E402
    FALLBACK_POLICY,
    MAX_CONCURRENCY,
    SERVING_MODEL_NAME,
    QloraSmokeServingError,
    build_serving_evidence,
    load_serving_inputs,
    serving_model_identity,
    write_serving_snapshot,
)

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
_READY_TIMEOUT_SECONDS = 180


def _offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    environment.pop(TRAINING_GATE, None)
    environment.pop("ORCHESTWIN_MODEL_SPIKE_ALLOW_NETWORK", None)
    environment.pop("ORCHESTWIN_MODEL_SOURCE_ALLOW_NETWORK", None)
    return environment


def _http_json(
    method: str,
    url: str,
    *,
    payload: object | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, object]]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(4_000_000)
            status = int(response.status)
    except HTTPError as error:
        raw = error.read(4_000_000)
        status = int(error.code)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise QloraSmokeServingError("serving probe response must be a JSON object")
    return status, value


def _load_spike_module():
    path = ROOT / "environments/training/run_model_spike.py"
    spec = importlib.util.spec_from_file_location("orchestwin_serving_verify_spike", path)
    if spec is None or spec.loader is None:
        raise QloraSmokeServingError("could not load the model-spike prompt contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wait_ready(path: Path, process: subprocess.Popen, timeout_seconds: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise QloraSmokeServingError(
                f"serving process exited before readiness with code {process.returncode}"
            )
        if path.is_file():
            return read_snapshot(path)
        time.sleep(0.2)
    raise QloraSmokeServingError("serving process did not become ready within the timeout")


def _wait_active(base_url: str, expected: int, timeout_seconds: float = 5.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last = {}
    while time.monotonic() < deadline:
        status, value = _http_json("GET", f"{base_url}/diagnostics/state", timeout=1)
        if status == 200:
            last = value
            if value.get("active_requests") == expected:
                return value
        time.sleep(0.05)
    raise QloraSmokeServingError(
        f"diagnostic active request count did not become {expected}: {last}"
    )


def _structured_generation(
    *,
    inputs,
    identity: ModelRuntimeIdentity,
    base_url: str,
) -> tuple[dict[str, object], object]:
    task = next(
        task for task in inputs.ablation_inputs.suite.tasks if task.task_id == "bench-en-002"
    )
    generation_request = create_benchmark_generation_request(
        run_id=UUID("00000000-0000-4000-8000-000000162001"),
        task=task,
        model_identity=identity,
    )
    adapter = OpenAICompatibleLocalStructuredAdapter(
        config=OpenAICompatibleLocalConfig(
            base_url=base_url,
            model_name=SERVING_MODEL_NAME,
            expected_identity=identity,
        ),
        transport=UrllibOpenAICompatibleTransport(),
    )
    result = asyncio.run(adapter.generate(generation_request))
    if result.success is None:
        failure = None if result.failure is None else result.failure.to_snapshot()
        raise QloraSmokeServingError(f"local structured serving example failed: {failure}")
    score = score_benchmark_result(task=task, result=result)
    if score.schema_valid_rate != 1.0:
        raise QloraSmokeServingError("local structured serving example was not schema-valid")

    spike = _load_spike_module()
    expected_messages = spike._create_chat_messages(generation_request)
    expected_prompt_hash = snapshot_content_hash({"messages": list(expected_messages)})
    status, state = _http_json("GET", f"{base_url}/diagnostics/state")
    if status != 200 or state.get("last_model_visible_messages_sha256") != expected_prompt_hash:
        raise QloraSmokeServingError(
            "served model-visible prompt differs from the frozen spike prompt contract"
        )

    observation = {
        "status": "SUCCEEDED",
        "task_id": task.task_id,
        "schema_valid": True,
        "actual_identity": result.success.actual_identity.to_snapshot(),
        "finish_reason": result.success.finish_reason.value,
        "usage": result.success.usage.to_snapshot(),
        "score": score.to_snapshot(),
        "model_visible_messages_sha256": expected_prompt_hash,
        "server_completed_generation_count": state.get("completed_generation_count"),
    }
    return observation, generation_request


def _fallback_probe(
    *,
    identity: ModelRuntimeIdentity,
    base_url: str,
    request,
) -> dict[str, object]:
    config = OpenAICompatibleLocalConfig(
        base_url=base_url,
        model_name=SERVING_MODEL_NAME,
        expected_identity=identity,
    )
    payload = _request_payload(config, request)
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    base_identity = ModelRuntimeIdentity(
        provider_id=identity.provider_id,
        runtime_id=identity.runtime_id,
        base_model_repository=identity.base_model_repository,
        base_model_revision=identity.base_model_revision,
        tokenizer_revision=identity.tokenizer_revision,
        configuration_sha256=identity.configuration_sha256,
    )
    metadata["expected_model_identity"] = base_identity.to_snapshot()

    _, before = _http_json("GET", f"{base_url}/diagnostics/state")
    status, response = _http_json(
        "POST",
        f"{base_url}/v1/chat/completions",
        payload=payload,
        timeout=5,
    )
    _, after = _http_json("GET", f"{base_url}/diagnostics/state")
    error = response.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if status != 409 or code != "ADAPTER_NOT_LOADED":
        raise QloraSmokeServingError("mismatched base identity was not rejected before generation")
    unchanged = before.get("completed_generation_count") == after.get("completed_generation_count")
    if not unchanged:
        raise QloraSmokeServingError("base fallback probe unexpectedly executed a generation")
    return {
        "policy": FALLBACK_POLICY,
        "mismatched_identity_status_code": status,
        "error_code": code,
        "base_fallback_attempted": False,
        "generation_count_unchanged": unchanged,
    }


def _concurrency_probe(base_url: str) -> dict[str, object]:
    first: dict[str, object] = {}

    def hold() -> None:
        status, payload = _http_json(
            "POST",
            f"{base_url}/diagnostics/hold",
            payload={"hold_milliseconds": 1_200},
            timeout=3,
        )
        first["status"] = status
        first["payload"] = payload

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    _wait_active(base_url, 1)
    status, second = _http_json(
        "POST",
        f"{base_url}/diagnostics/hold",
        payload={"hold_milliseconds": 100},
        timeout=2,
    )
    thread.join(timeout=4)
    if thread.is_alive() or first.get("status") != 200 or status != 429:
        raise QloraSmokeServingError("single-slot concurrency behavior was not observed")
    error = second.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code != "RATE_LIMITED":
        raise QloraSmokeServingError("concurrency saturation did not report RATE_LIMITED")
    _wait_active(base_url, 0)
    return {
        "max_concurrency": MAX_CONCURRENCY,
        "first_hold_status_code": first["status"],
        "rate_limit_status_code": status,
        "rate_limit_error_code": code,
        "observed": True,
    }


def _timeout_probe(base_url: str) -> dict[str, object]:
    request = Request(
        f"{base_url}/diagnostics/hold",
        data=json.dumps({"hold_milliseconds": 1_000}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    observed = False
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=0.1) as response:
            response.read(1024)
    except TimeoutError:
        observed = True
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            observed = True
        else:
            raise
    elapsed = max(0, round((time.perf_counter() - started) * 1000))
    if not observed:
        raise QloraSmokeServingError("loopback timeout probe unexpectedly completed")
    _wait_active(base_url, 0, timeout_seconds=3)
    status, health = _http_json("GET", f"{base_url}/health")
    if status != 200 or health.get("status") != "SERVING":
        raise QloraSmokeServingError("server did not remain healthy after client timeout")
    return {
        "loopback_transport_timeout_observed": True,
        "client_timeout_milliseconds": 100,
        "elapsed_until_timeout_milliseconds": elapsed,
        "server_healthy_after_timeout": True,
        "scope": "TRANSPORT_TIMEOUT_NOT_GPU_CANCELLATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--recovery-report", type=Path, required=True)
    parser.add_argument("--ablation-report", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get(TRAINING_GATE) == "1":
        print("serving verifier refuses the training authorization gate", file=sys.stderr)
        return 22

    destination = args.output_root.absolute()
    if destination.exists() or destination.is_symlink():
        print("serving output root must be new", file=sys.stderr)
        return 22
    destination.mkdir(parents=True)

    ready_path = destination / "server-ready.json"
    server_stdout = destination / "server.stdout.log"
    server_stderr = destination / "server.stderr.log"
    process = None
    stdout_handle = None
    stderr_handle = None

    try:
        inputs = load_serving_inputs(
            ROOT,
            args.training_root,
            args.recovery_report,
            args.ablation_report,
        )
        identity = serving_model_identity(inputs)
        environment = _offline_environment()
        stdout_handle = server_stdout.open("w", encoding="utf-8")
        stderr_handle = server_stderr.open("w", encoding="utf-8")
        command = [
            sys.executable,
            str(ROOT / "environments/training/serve_qlora_smoke_openai.py"),
            "--training-root",
            str(args.training_root),
            "--recovery-report",
            str(args.recovery_report),
            "--ablation-report",
            str(args.ablation_report),
            "--ready-file",
            str(ready_path),
            "--host",
            "127.0.0.1",
            "--port",
            "0",
            "--allow-diagnostics",
        ]
        process = subprocess.Popen(
            command,
            cwd=ROOT / "environments/training",
            env=environment,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )
        ready = _wait_ready(ready_path, process, _READY_TIMEOUT_SECONDS)
        base_url = ready.get("base_url")
        if not isinstance(base_url, str) or not base_url.startswith("http://127.0.0.1:"):
            raise QloraSmokeServingError("ready evidence contains an unexpected base URL")
        if ready.get("model_identity") != identity.to_snapshot():
            raise QloraSmokeServingError("ready evidence contains a different model identity")

        status, health = _http_json("GET", f"{base_url}/health")
        if status != 200 or health.get("status") != "SERVING":
            raise QloraSmokeServingError("health endpoint did not report SERVING")
        status, models = _http_json("GET", f"{base_url}/v1/models")
        if status != 200:
            raise QloraSmokeServingError("model identity endpoint failed")
        data = models.get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise QloraSmokeServingError("model identity endpoint returned an invalid list")
        observed_identity = data[0].get("model_identity")
        if observed_identity != identity.to_snapshot():
            raise QloraSmokeServingError("served /v1/models identity differs")

        generation, request = _structured_generation(
            inputs=inputs,
            identity=identity,
            base_url=base_url,
        )
        fallback = _fallback_probe(
            identity=identity,
            base_url=base_url,
            request=request,
        )
        concurrency = _concurrency_probe(base_url)
        timeout = _timeout_probe(base_url)
        _, final_state = _http_json("GET", f"{base_url}/diagnostics/state")
        load_peak = final_state.get("model_load_peak_torch_reserved_memory_mib")
        generation_peak = final_state.get("last_generation_peak_torch_reserved_memory_mib")
        gpu_total = final_state.get("gpu_total_memory_mib")
        if (
            type(load_peak) is not int
            or type(generation_peak) is not int
            or type(gpu_total) is not int
            or not 0 < load_peak <= gpu_total
            or not 0 < generation_peak <= gpu_total
        ):
            raise QloraSmokeServingError("observed serving GPU memory values are invalid")

        observations = {
            "health": {
                "status": health.get("status"),
                "engine_id": health.get("engine_id"),
                "loopback_only": health.get("loopback_only"),
                "network_authorized": health.get("network_authorized"),
                "max_concurrency": health.get("max_concurrency"),
                "fallback_policy": health.get("fallback_policy"),
                "vllm_observation_status": health.get("vllm_observation_status"),
            },
            "identity": {
                "model_name": data[0].get("id"),
                "model_identity": observed_identity,
            },
            "structured_generation": generation,
            "concurrency": concurrency,
            "timeout": timeout,
            "memory": {
                "model_load_duration_milliseconds": final_state.get(
                    "model_load_duration_milliseconds"
                ),
                "model_load_peak_torch_reserved_memory_mib": load_peak,
                "generation_peak_torch_reserved_memory_mib": generation_peak,
                "generation_latency_milliseconds": final_state.get(
                    "last_generation_latency_milliseconds"
                ),
                "gpu_total_memory_mib": gpu_total,
            },
            "fallback": fallback,
        }
        report = build_serving_evidence(
            inputs=inputs,
            observations=observations,
            created_at=datetime.now(UTC),
        )
        report_path = destination / "serving-report.json"
        write_serving_snapshot(report_path, report)
        print(report_path.resolve())
        print("qlora_smoke_serving_verification: PASSED (local OpenAI-compatible smoke)")
        return 0
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        HTTPError,
        URLError,
        subprocess.SubprocessError,
        QloraSmokeServingError,
    ) as error:
        print(
            f"qlora_smoke_serving_verification_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if stdout_handle is not None:
            stdout_handle.close()
        if stderr_handle is not None:
            stderr_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
