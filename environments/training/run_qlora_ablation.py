#!/usr/bin/env python3
"""Run a paired, offline base-versus-smoke-adapter benchmark on the frozen evaluator suite."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.structured_generation import ModelRuntimeIdentity  # noqa: E402
from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)
from orchestwin.training.benchmark_measurement_v2 import (  # noqa: E402
    measure_evaluator_output_v2,
    summarize_measurements_v2,
)
from orchestwin.training.benchmarking import create_benchmark_generation_request  # noqa: E402
from orchestwin.training.qlora_ablation import (  # noqa: E402
    ABLATION_POLICY_ID,
    ADAPTER_VARIANT,
    BASE_VARIANT,
    QloraAblationError,
    build_ablation_report,
    load_ablation_inputs,
    verify_worker_artifacts,
    write_ablation_report,
)
from orchestwin.training.qlora_smoke_collation import read_snapshot  # noqa: E402

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
_WORKER_TIMEOUT_SECONDS = 1200
_ABLATION_NAMESPACE = UUID("9b98b13e-20f8-4471-9b28-40af2253f14c")


def _load_spike_module():
    path = ROOT / "environments/training/run_model_spike.py"
    spec = importlib.util.spec_from_file_location("orchestwin_ablation_spike_contract", path)
    if spec is None or spec.loader is None:
        raise QloraAblationError("could not load the frozen model-spike contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _new_directory(path: Path) -> Path:
    path = path.absolute()
    artifacts = ROOT / "environments/training/artifacts"
    if ROOT not in path.parents or artifacts not in path.parents:
        raise QloraAblationError("ablation output must remain inside training artifacts")
    if path.exists() or path.is_symlink():
        raise QloraAblationError("ablation output must be a new directory")
    path.mkdir(parents=True)
    return path


def _write_snapshot(path: Path, value: Mapping[str, object]) -> None:
    payload = dict(value)
    payload["content_hash"] = snapshot_content_hash(payload)
    path.write_bytes(canonical_json(payload).encode("utf-8"))


def _sha256_bytes(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _write_text(path: Path, value: str) -> str:
    raw = value.encode("utf-8")
    path.write_bytes(raw)
    return _sha256_bytes(raw)


def _load_variant_model(inputs, variant: str):
    spike = _load_spike_module()
    torch, _, FastLanguageModel = spike._load_runtime_dependencies()
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise QloraAblationError("ablation requires exactly one visible CUDA GPU")

    generation = inputs.matrix.generation.to_snapshot()
    torch.manual_seed(generation["seed"])
    torch.cuda.manual_seed_all(generation["seed"])
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()

    values = {
        "model_name": inputs.candidate.repository_id,
        "revision": inputs.candidate.revision,
        "max_seq_length": generation["max_sequence_length"],
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
        raise QloraAblationError(
            f"loaded base revision differs: expected={inputs.candidate.revision}; observed={observed}"
        )
    if getattr(model, "is_loaded_in_4bit", False) is not True:
        raise QloraAblationError("ablation base model is not loaded in four bit")

    FastLanguageModel.for_inference(model)
    adapter_lora_parameters = 0
    adapter_trainable_lora_parameters = 0
    if variant == ADAPTER_VARIANT:
        from peft import PeftModel

        model = PeftModel.from_pretrained(
            model,
            str(inputs.bundle.adapter_root),
            is_trainable=False,
            local_files_only=True,
        )
        model.eval()
        unsafe = []
        for name, parameter in model.named_parameters():
            if "lora_" in name:
                adapter_lora_parameters += parameter.numel()
                if parameter.requires_grad:
                    adapter_trainable_lora_parameters += parameter.numel()
            elif parameter.requires_grad:
                unsafe.append(name)
        expected = inputs.bundle.result["observations"]["trainable_lora_parameters"]
        if unsafe or adapter_lora_parameters != expected or adapter_trainable_lora_parameters != 0:
            raise QloraAblationError("adapter reload differs from the verified S60 identity")
    elif variant != BASE_VARIANT:
        raise QloraAblationError("unknown ablation variant")

    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise QloraAblationError("tokenizer has neither pad nor EOS token")
        tokenizer.pad_token = tokenizer.eos_token
    if getattr(tokenizer, "chat_template", None) is None:
        raise QloraAblationError("frozen tokenizer has no chat template")

    torch.cuda.synchronize()
    return (
        spike,
        torch,
        FastLanguageModel,
        model,
        tokenizer,
        {
            "observed_base_revision": observed,
            "load_duration_milliseconds": max(0, round((time.perf_counter() - started) * 1000)),
            "load_peak_torch_reserved_memory_mib": round(
                torch.cuda.max_memory_reserved() / 1024**2
            ),
            "adapter_lora_parameters": adapter_lora_parameters,
            "adapter_trainable_lora_parameters": adapter_trainable_lora_parameters,
        },
    )


def _runtime_identity(inputs, variant: str) -> ModelRuntimeIdentity:
    configuration = {
        "policy_id": ABLATION_POLICY_ID,
        "variant": variant,
        "generation": inputs.matrix.generation.to_snapshot(),
        "candidate_matrix_content_hash": inputs.matrix.content_hash,
        "benchmark_suite_content_hash": inputs.suite.content_hash,
        "training_identity": inputs.identity["training"],
        "adapter_inventory_sha256": (
            None
            if variant == BASE_VARIANT
            else inputs.identity["training"]["adapter_inventory_sha256"]
        ),
    }
    return ModelRuntimeIdentity(
        provider_id="huggingface-local",
        runtime_id=f"unsloth-qlora-ablation-{variant.casefold()}-v1",
        base_model_repository=inputs.candidate.repository_id,
        base_model_revision=inputs.candidate.revision,
        tokenizer_revision=inputs.candidate.tokenizer_revision,
        configuration_sha256=snapshot_content_hash(configuration),
    )


def _worker(
    *,
    variant: str,
    training_root: Path,
    recovery_report: Path,
    output_root: Path,
) -> int:
    if os.environ.get(TRAINING_GATE) == "1":
        print("ablation worker refuses the training authorization gate", file=sys.stderr)
        return 22

    output_root.mkdir(parents=True, exist_ok=False)
    report_path = output_root / "worker-report.json"

    try:
        inputs = load_ablation_inputs(ROOT, training_root, recovery_report)
        spike, torch, _, model, tokenizer, load = _load_variant_model(inputs, variant)
        model_identity = _runtime_identity(inputs, variant)
        generation = inputs.matrix.generation.to_snapshot()
        run_id = uuid5(
            _ABLATION_NAMESPACE,
            f"{inputs.bundle.request['request_id']}:{variant}:{inputs.suite.content_hash}",
        )
        task_records = []
        raw_root = output_root / "raw"
        prompt_root = output_root / "prompts"
        raw_root.mkdir()
        prompt_root.mkdir()

        for task in inputs.suite.tasks:
            generation_request = create_benchmark_generation_request(
                run_id=run_id,
                task=task,
                model_identity=model_identity,
            )
            messages = spike._create_chat_messages(generation_request)
            messages_sha256 = snapshot_content_hash({"messages": list(messages)})
            prompt_payload = {
                "task_id": task.task_id,
                "task_content_hash": task.content_hash,
                "repetition": 1,
                "messages": list(messages),
                "messages_sha256": messages_sha256,
                "prompt_version_ref": generation_request.prompt_version_ref,
                "output_schema_content_hash": generation_request.output_schema.content_hash,
                "generation": generation,
            }
            prompt_path = prompt_root / f"{task.task_id}.json"
            prompt_bytes = canonical_json(prompt_payload).encode("utf-8")
            prompt_path.write_bytes(prompt_bytes)
            prompt_reference = prompt_path.relative_to(output_root).as_posix()
            prompt_sha256 = _sha256_bytes(prompt_bytes)

            raw_text = None
            generation_succeeded = False
            failure_kind = None
            failure_message = None
            finish_reason = None
            latency = None
            peak = None
            input_tokens = None
            output_tokens = None
            try:
                inputs_tensor = spike._prepare_inputs(
                    tokenizer,
                    messages,
                    torch,
                    inputs.candidate.chat_template_control,
                )
                input_tokens = int(inputs_tensor["input_ids"].shape[-1])
                if (
                    input_tokens + generation["max_output_tokens"]
                    > generation["max_sequence_length"]
                ):
                    raise QloraAblationError(
                        "tokenized prompt plus maximum output exceeds frozen sequence length"
                    )
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                torch.cuda.synchronize()
                started = time.perf_counter()
                with torch.inference_mode():
                    generated = model.generate(
                        **inputs_tensor,
                        max_new_tokens=generation["max_output_tokens"],
                        do_sample=False,
                        use_cache=True,
                        pad_token_id=tokenizer.pad_token_id,
                        eos_token_id=tokenizer.eos_token_id,
                    )
                torch.cuda.synchronize()
                latency = max(0, round((time.perf_counter() - started) * 1000))
                peak = round(torch.cuda.max_memory_reserved() / 1024**2)
                sequences = spike._generated_sequences(generated)
                generated_ids = sequences[0, input_tokens:]
                output_tokens = int(generated_ids.shape[-1])
                raw_text = tokenizer.decode(
                    generated_ids,
                    skip_special_tokens=True,
                ).strip()
                finish_reason = (
                    "LENGTH" if output_tokens >= generation["max_output_tokens"] else "STOP"
                )
                generation_succeeded = True
            except (RuntimeError, TypeError, ValueError, QloraAblationError) as error:
                failure_message = " ".join(str(error).split())[:2000]
                failure_kind = (
                    "OUT_OF_MEMORY"
                    if "out of memory" in failure_message.casefold()
                    else "GENERATION_FAILED"
                )

            raw_reference = None
            raw_sha256 = None
            if generation_succeeded:
                raw_path = raw_root / f"{task.task_id}.txt"
                raw_sha256 = _write_text(raw_path, raw_text or "")
                raw_reference = raw_path.relative_to(output_root).as_posix()

            output_schema = json.loads(generation_request.output_schema.canonical_schema_json)
            measurement = measure_evaluator_output_v2(
                task=task,
                raw_output=raw_text if generation_succeeded else None,
                output_schema=output_schema,
            ).to_snapshot()
            task_records.append(
                {
                    "task_id": task.task_id,
                    "task_content_hash": task.content_hash,
                    "language": task.language.value,
                    "category": task.category.value,
                    "repetition": 1,
                    "messages_sha256": messages_sha256,
                    "prompt_reference": prompt_reference,
                    "prompt_sha256": prompt_sha256,
                    "prompt_version_ref": generation_request.prompt_version_ref,
                    "output_schema_content_hash": generation_request.output_schema.content_hash,
                    "generation_succeeded": generation_succeeded,
                    "finish_reason": finish_reason,
                    "raw_output_reference": raw_reference,
                    "raw_output_sha256": raw_sha256,
                    "latency_milliseconds": latency,
                    "peak_torch_reserved_memory_mib": peak,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "failure_kind": failure_kind,
                    "failure_message": failure_message,
                    "measurement": measurement,
                }
            )
            if failure_kind == "OUT_OF_MEMORY":
                break

        complete = len(task_records) == len(inputs.suite.tasks) and all(
            item["generation_succeeded"] for item in task_records
        )
        summary = summarize_measurements_v2(task_records)
        by_language = {
            language: summarize_measurements_v2(
                [item for item in task_records if item["language"] == language]
            )
            for language in ("en", "it")
        }
        latencies = [
            item["latency_milliseconds"]
            for item in task_records
            if type(item["latency_milliseconds"]) is int
        ]
        peaks = [
            item["peak_torch_reserved_memory_mib"]
            for item in task_records
            if type(item["peak_torch_reserved_memory_mib"]) is int
        ]
        resource_summary = {
            "model_load_duration_milliseconds": load["load_duration_milliseconds"],
            "model_load_peak_torch_reserved_memory_mib": load[
                "load_peak_torch_reserved_memory_mib"
            ],
            "generation_total_latency_milliseconds": sum(latencies),
            "generation_mean_latency_milliseconds": (
                None if not latencies else round(sum(latencies) / len(latencies), 3)
            ),
            "generation_max_peak_torch_reserved_memory_mib": (None if not peaks else max(peaks)),
            "observed_generation_count": len(latencies),
        }
        report = {
            "schema_version": 1,
            "policy_id": ABLATION_POLICY_ID,
            "variant": variant,
            "status": "COMPLETED" if complete else "PARTIAL",
            "created_at": datetime.now(UTC).isoformat(),
            "identity": inputs.identity,
            "model_runtime_identity": model_identity.to_snapshot(),
            "model_load": load,
            "task_count": len(task_records),
            "tasks": task_records,
            "summary": summary,
            "by_language": by_language,
            "resource_summary": resource_summary,
            "training_executed": False,
            "network_authorized": False,
            "model_selected": False,
            "serving_validated": False,
        }
        _write_snapshot(report_path, report)
        print(report_path)
        return 0 if complete else 27
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        QloraAblationError,
    ) as error:
        print(
            f"qlora_ablation_worker_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22
    finally:
        with __import__("contextlib").suppress(Exception):
            del model
        gc.collect()
        with __import__("contextlib").suppress(Exception):
            torch.cuda.empty_cache()


def _controller(
    *,
    training_root: Path,
    recovery_report: Path,
    output_root: Path,
) -> int:
    if os.environ.get(TRAINING_GATE) == "1":
        print("ablation controller refuses the training authorization gate", file=sys.stderr)
        return 22
    try:
        inputs = load_ablation_inputs(ROOT, training_root, recovery_report)
        destination = _new_directory(output_root)
        environment = _offline_environment()
        reports = {}

        for variant in (BASE_VARIANT, ADAPTER_VARIANT):
            worker_root = destination / variant.casefold()
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-variant",
                variant,
                "--training-root",
                str(training_root),
                "--recovery-report",
                str(recovery_report),
                "--worker-output-root",
                str(worker_root),
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT / "environments/training",
                env=environment,
                capture_output=True,
                text=True,
                timeout=_WORKER_TIMEOUT_SECONDS,
                check=False,
            )
            (destination / f"{variant.casefold()}.stdout.log").write_text(
                completed.stdout,
                encoding="utf-8",
            )
            (destination / f"{variant.casefold()}.stderr.log").write_text(
                completed.stderr,
                encoding="utf-8",
            )
            report_path = worker_root / "worker-report.json"
            if completed.returncode != 0 or not report_path.is_file():
                raise QloraAblationError(
                    f"{variant} worker failed with exit {completed.returncode}"
                )
            report = read_snapshot(report_path)
            verify_worker_artifacts(worker_root, report)
            reports[variant] = report

        final = build_ablation_report(
            inputs=inputs,
            base=reports[BASE_VARIANT],
            adapter=reports[ADAPTER_VARIANT],
            created_at=datetime.now(UTC),
        )
        report_path = destination / "ablation-report.json"
        write_ablation_report(report_path, final)
        print(report_path)
        print("qlora_ablation: COMPLETED (descriptive only, no model selected)")
        return 0
    except (
        OSError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
        KeyError,
        QloraAblationError,
    ) as error:
        print(
            f"qlora_ablation_controller_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-root", required=True, type=Path)
    parser.add_argument("--recovery-report", required=True, type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--worker-variant",
        choices=(BASE_VARIANT, ADAPTER_VARIANT),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-output-root", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args()

    if arguments.worker_variant is not None:
        if arguments.worker_output_root is None:
            parser.error("--worker-output-root is required for worker mode")
        return _worker(
            variant=arguments.worker_variant,
            training_root=arguments.training_root,
            recovery_report=arguments.recovery_report,
            output_root=arguments.worker_output_root,
        )

    if arguments.output_root is None:
        parser.error("--output-root is required")
    return _controller(
        training_root=arguments.training_root,
        recovery_report=arguments.recovery_report,
        output_root=arguments.output_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
