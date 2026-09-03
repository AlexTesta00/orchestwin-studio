#!/usr/bin/env python3
"""Run one repository-described Unsloth QLoRA job inside the isolated environment."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

EXIT_MISSING_DEPENDENCY: Final = 20
EXIT_GPU_UNAVAILABLE: Final = 21
EXIT_INVALID_INPUT: Final = 22
EXIT_OUT_OF_MEMORY: Final = 23
EXIT_INTERRUPTED: Final = 24
EXIT_TRAINING_FAILED: Final = 25
EXIT_EXPORT_FAILED: Final = 26

_CHECKPOINT_PATTERN: Final = re.compile(r"checkpoint-(\d+)")
_MAX_JSON_BYTES: Final = 4_000_000


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one bounded User Twin evaluator QLoRA training job."
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    return parser.parse_args()


def _load_request(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("request path must identify a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_JSON_BYTES:
        raise ValueError("request artifact exceeds the configured size limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request artifact must contain a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported training request schema version")
    if not isinstance(payload.get("request_sha256"), str):
        raise ValueError("training request digest is required")
    if not isinstance(payload.get("configuration"), dict):
        raise ValueError("training configuration snapshot is required")
    return payload


def _resolve_relative(root: Path, value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{label} must be a relative POSIX path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"{label} must remain traversal-free")
    resolved = root.joinpath(*pure.parts).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"{label} escapes the request workspace")
    return resolved


def _directory_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError("training artifacts cannot contain symbolic links")
        if not path.is_file():
            continue
        relative = path.relative_to(directory).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _supported_kwargs(callable_value: object, values: dict[str, Any]) -> dict[str, Any]:
    parameters = inspect.signature(callable_value).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return values
    return {key: value for key, value in values.items() if key in parameters}


def _training_result_template(request_sha256: str, started_at: datetime) -> dict[str, Any]:
    return {
        "request_sha256": request_sha256,
        "status": "FAILED",
        "started_at": started_at.isoformat(),
        "completed_at": started_at.isoformat(),
        "duration_milliseconds": 0,
        "peak_gpu_memory_mb": None,
        "metrics": [],
        "checkpoints": [],
        "adapter_relative_path": None,
        "adapter_sha256": None,
        "failure_kind": "TRAINING_FAILED",
        "failure_message": "Training did not complete.",
    }


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _finish_failure(
    *,
    result_path: Path,
    result: dict[str, Any],
    started_at: datetime,
    started_clock: float,
    kind: str,
    message: str,
    exit_code: int,
    status: str = "FAILED",
) -> int:
    completed = datetime.now(UTC)
    result.update(
        {
            "status": status,
            "completed_at": completed.isoformat(),
            "duration_milliseconds": max(0, round((time.perf_counter() - started_clock) * 1000)),
            "failure_kind": kind,
            "failure_message": " ".join(message.split())[:2000],
        }
    )
    if completed < started_at:
        result["completed_at"] = started_at.isoformat()
    _write_result(result_path, result)
    return exit_code


def _collect_metrics(log_history: object) -> list[dict[str, Any]]:
    if not isinstance(log_history, list):
        return []
    observations: list[dict[str, Any]] = []
    for entry in log_history:
        if not isinstance(entry, dict):
            continue
        step_value = entry.get("step")
        step = step_value if isinstance(step_value, int) and step_value > 0 else None
        for name, value in sorted(entry.items()):
            if name in {"step", "epoch", "total_flos"}:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            observations.append({"name": name, "value": float(value), "step": step})
    return sorted(
        observations,
        key=lambda item: (
            -1 if item["step"] is None else item["step"],
            item["name"],
        ),
    )


def _collect_checkpoints(output_directory: Path, workspace_root: Path) -> list[dict[str, Any]]:
    checkpoints: list[dict[str, Any]] = []
    if not output_directory.is_dir():
        return checkpoints
    for path in sorted(output_directory.iterdir(), key=lambda item: item.name):
        match = _CHECKPOINT_PATTERN.fullmatch(path.name)
        if match is None or not path.is_dir() or path.is_symlink():
            continue
        checkpoints.append(
            {
                "step": int(match.group(1)),
                "relative_path": path.relative_to(workspace_root).as_posix(),
                "content_sha256": _directory_digest(path),
            }
        )
    return checkpoints


def _load_runtime_dependencies() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    import torch
    from datasets import load_dataset
    from transformers import BitsAndBytesConfig, EarlyStoppingCallback
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    return (
        torch,
        load_dataset,
        BitsAndBytesConfig,
        EarlyStoppingCallback,
        SFTConfig,
        SFTTrainer,
        FastLanguageModel,
    )


def _run_training(request: dict[str, Any], result_path: Path) -> int:
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    request_sha256 = str(request["request_sha256"])
    result = _training_result_template(request_sha256, started_at)
    try:
        (
            torch,
            load_dataset,
            BitsAndBytesConfig,
            EarlyStoppingCallback,
            SFTConfig,
            SFTTrainer,
            FastLanguageModel,
        ) = _load_runtime_dependencies()
    except ModuleNotFoundError as error:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="MISSING_DEPENDENCY",
            message=f"Missing training dependency: {error.name or 'unknown'}.",
            exit_code=EXIT_MISSING_DEPENDENCY,
        )

    if not torch.cuda.is_available():
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="GPU_UNAVAILABLE",
            message="CUDA is not available to the isolated training process.",
            exit_code=EXIT_GPU_UNAVAILABLE,
        )

    workspace_root = result_path.parent.resolve()
    try:
        train_path = _resolve_relative(
            workspace_root,
            request.get("train_dataset_path"),
            label="training dataset path",
        )
        validation_path = _resolve_relative(
            workspace_root,
            request.get("validation_dataset_path"),
            label="validation dataset path",
        )
        output_directory = _resolve_relative(
            workspace_root,
            request.get("output_directory"),
            label="training output directory",
        )
        resume_value = request.get("resume_checkpoint_path")
        resume_path = (
            None
            if resume_value is None
            else _resolve_relative(
                workspace_root,
                resume_value,
                label="resume checkpoint path",
            )
        )
        if not train_path.is_file() or not validation_path.is_file():
            raise ValueError("training and validation JSONL files must exist")
        configuration = request["configuration"]
        optimization = configuration["optimization"]
        adapter = configuration["adapter"]
        quantization = configuration["quantization"]
        checkpoints = configuration["checkpoints"]
    except (KeyError, TypeError, ValueError, OSError) as error:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="INVALID_INPUT",
            message=str(error),
            exit_code=EXIT_INVALID_INPUT,
        )

    try:
        compute_dtype = (
            torch.bfloat16 if quantization["compute_dtype"] == "bfloat16" else torch.float16
        )
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=quantization["quantization_type"],
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=quantization["double_quantization"],
        )
        model_kwargs = {
            "model_name": configuration["base_model_repository"],
            "revision": configuration["base_model_revision"],
            "max_seq_length": optimization["max_sequence_length"],
            "dtype": None,
            "load_in_4bit": True,
            "quantization_config": quantization_config,
        }
        model, tokenizer = FastLanguageModel.from_pretrained(
            **_supported_kwargs(FastLanguageModel.from_pretrained, model_kwargs)
        )
        peft_kwargs = {
            "r": adapter["rank"],
            "target_modules": adapter["target_modules"],
            "lora_alpha": adapter["alpha"],
            "lora_dropout": adapter["dropout"],
            "bias": adapter["bias"],
            "use_gradient_checkpointing": (
                "unsloth" if optimization["gradient_checkpointing"] else False
            ),
            "random_state": configuration["seed"],
            "use_rslora": adapter["use_rslora"],
        }
        model = FastLanguageModel.get_peft_model(
            model,
            **_supported_kwargs(FastLanguageModel.get_peft_model, peft_kwargs),
        )
        train_dataset = load_dataset("json", data_files=str(train_path), split="train")
        validation_dataset = load_dataset(
            "json",
            data_files=str(validation_path),
            split="train",
        )
    except RuntimeError as error:
        kind = "OUT_OF_MEMORY" if "out of memory" in str(error).lower() else "TRAINING_FAILED"
        code = EXIT_OUT_OF_MEMORY if kind == "OUT_OF_MEMORY" else EXIT_TRAINING_FAILED
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind=kind,
            message=str(error),
            exit_code=code,
        )
    except (KeyError, TypeError, ValueError, OSError) as error:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="TRAINING_FAILED",
            message=str(error),
            exit_code=EXIT_TRAINING_FAILED,
        )

    try:
        output_directory.mkdir(parents=True, exist_ok=True)
        sft_values: dict[str, Any] = {
            "output_dir": str(output_directory),
            "dataset_text_field": "text",
            "max_length": optimization["max_sequence_length"],
            "max_seq_length": optimization["max_sequence_length"],
            "per_device_train_batch_size": optimization["per_device_train_batch_size"],
            "gradient_accumulation_steps": optimization["gradient_accumulation_steps"],
            "learning_rate": optimization["learning_rate"],
            "weight_decay": optimization["weight_decay"],
            "warmup_ratio": optimization["warmup_ratio"],
            "max_steps": optimization["max_steps"] if optimization["max_steps"] is not None else -1,
            "num_train_epochs": optimization["num_train_epochs"] or 1.0,
            "optim": optimization["optimizer"],
            "lr_scheduler_type": optimization["scheduler"],
            "fp16": optimization["precision"] == "fp16",
            "bf16": optimization["precision"] == "bf16",
            "max_grad_norm": optimization["gradient_clip_norm"],
            "logging_steps": optimization["logging_steps"],
            "eval_strategy": "steps",
            "evaluation_strategy": "steps",
            "eval_steps": checkpoints["evaluation_steps"],
            "save_strategy": "steps",
            "save_steps": checkpoints["save_steps"],
            "save_total_limit": checkpoints["save_total_limit"],
            "load_best_model_at_end": checkpoints["load_best_model_at_end"],
            "metric_for_best_model": checkpoints["metric_for_best_model"],
            "greater_is_better": checkpoints["greater_is_better"],
            "seed": configuration["seed"],
            "report_to": "none",
        }
        sft_config = SFTConfig(**_supported_kwargs(SFTConfig, sft_values))
        callbacks = []
        patience = checkpoints["early_stopping_patience"]
        if patience is not None:
            callbacks.append(EarlyStoppingCallback(early_stopping_patience=patience))
        trainer_values = {
            "model": model,
            "args": sft_config,
            "train_dataset": train_dataset,
            "eval_dataset": validation_dataset,
            "processing_class": tokenizer,
            "tokenizer": tokenizer,
            "callbacks": callbacks,
        }
        trainer = SFTTrainer(**_supported_kwargs(SFTTrainer, trainer_values))
        trainer.train(resume_from_checkpoint=None if resume_path is None else str(resume_path))
    except KeyboardInterrupt:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="INTERRUPTED",
            message="Training was interrupted before adapter export.",
            exit_code=EXIT_INTERRUPTED,
            status="INTERRUPTED",
        )
    except RuntimeError as error:
        kind = "OUT_OF_MEMORY" if "out of memory" in str(error).lower() else "TRAINING_FAILED"
        code = EXIT_OUT_OF_MEMORY if kind == "OUT_OF_MEMORY" else EXIT_TRAINING_FAILED
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind=kind,
            message=str(error),
            exit_code=code,
        )
    except (TypeError, ValueError, OSError) as error:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="TRAINING_FAILED",
            message=str(error),
            exit_code=EXIT_TRAINING_FAILED,
        )

    try:
        adapter_directory = output_directory / "adapter"
        adapter_directory.mkdir(parents=True, exist_ok=False)
        model.save_pretrained(str(adapter_directory))
        tokenizer.save_pretrained(str(adapter_directory))
        adapter_sha256 = _directory_digest(adapter_directory)
        peak_memory = round(torch.cuda.max_memory_allocated() / (1024 * 1024))
        completed_at = datetime.now(UTC)
        result.update(
            {
                "status": "SUCCEEDED",
                "completed_at": completed_at.isoformat(),
                "duration_milliseconds": max(
                    0,
                    round((time.perf_counter() - started_clock) * 1000),
                ),
                "peak_gpu_memory_mb": max(0, peak_memory),
                "metrics": _collect_metrics(trainer.state.log_history),
                "checkpoints": _collect_checkpoints(output_directory, workspace_root),
                "adapter_relative_path": adapter_directory.relative_to(workspace_root).as_posix(),
                "adapter_sha256": adapter_sha256,
                "failure_kind": None,
                "failure_message": None,
            }
        )
        _write_result(result_path, result)
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return _finish_failure(
            result_path=result_path,
            result=result,
            started_at=started_at,
            started_clock=started_clock,
            kind="EXPORT_FAILED",
            message=str(error),
            exit_code=EXIT_EXPORT_FAILED,
        )


def main() -> int:
    arguments = _parse_arguments()
    try:
        request = _load_request(arguments.request)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        started_at = datetime.now(UTC)
        result = _training_result_template("0" * 64, started_at)
        return _finish_failure(
            result_path=arguments.result,
            result=result,
            started_at=started_at,
            started_clock=time.perf_counter(),
            kind="INVALID_INPUT",
            message=str(error),
            exit_code=EXIT_INVALID_INPUT,
        )
    return _run_training(request, arguments.result)


if __name__ == "__main__":
    sys.exit(main())
