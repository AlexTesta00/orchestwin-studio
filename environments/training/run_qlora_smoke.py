#!/usr/bin/env python3
"""Preflight or explicitly authorize the eight-step, offline S49/S50 QLoRA smoke.

This dedicated runner does not alter the legacy run_qlora.py API. It trains only the
reproducible smoke fixture, exports an adapter and leaves reload/restore evidence pending.
"""

from __future__ import annotations

import argparse
import inspect
import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.qlora_smoke_collation import (  # noqa: E402
    COLLATION_POLICY_ID,
    VerifiedSmokeInputs,
    audit_collator,
    checked_path,
    load_verified_smoke_inputs,
    new_output_root,
    package_versions,
    read_bounded,
    read_snapshot,
    sha256,
    write_snapshot,
)
from orchestwin.training.qlora_smoke_tokenization import audit_tokenized_record  # noqa: E402

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
RUNTIME_ID = "unsloth-eight-step-smoke-v1"


def authorize(args: argparse.Namespace, environment: dict[str, str]) -> dict[str, object]:
    """Record explicit owner declarations; these are not empirical or license-law attestations."""
    if environment.get(TRAINING_GATE) != "1":
        raise ValueError(f"training requires {TRAINING_GATE}=1")
    if not all((args.approve_fixtures, args.approve_model_license, args.approve_local_training)):
        raise ValueError(
            "explicit fixture, local-license and eight-step training approvals required"
        )
    owner = args.owner_id
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 128:
        raise ValueError("a nonempty owner identifier of at most 128 characters is required")
    return {
        "owner_id": owner.strip(),
        "fixture_review": "OWNER_DECLARED",
        "local_model_license_review": "OWNER_DECLARED",
        "scope": "LOCAL_EIGHT_STEP_SMOKE_ONLY",
        "redistribution_approved": False,
        "full_training_approved": False,
        "model_selected": False,
    }


def strict_call(function: Any, values: dict[str, Any]) -> Any:
    try:
        inspect.signature(function).bind(**values)
    except (TypeError, ValueError) as error:
        raise ValueError(f"runtime cannot accept the exact required arguments: {error}") from error
    return function(**values)


def load_dependencies() -> SimpleNamespace:
    # isort: off
    from unsloth import FastLanguageModel
    import torch
    from datasets import Dataset
    from transformers import AutoTokenizer, BitsAndBytesConfig, TrainerCallback
    from trl import SFTConfig, SFTTrainer
    from trl.trainer.sft_trainer import DataCollatorForLanguageModeling

    # isort: on
    return SimpleNamespace(
        FastLanguageModel=FastLanguageModel,
        torch=torch,
        Dataset=Dataset,
        AutoTokenizer=AutoTokenizer,
        BitsAndBytesConfig=BitsAndBytesConfig,
        TrainerCallback=TrainerCallback,
        SFTConfig=SFTConfig,
        SFTTrainer=SFTTrainer,
        DataCollator=DataCollatorForLanguageModeling,
    )


def model_loading_kwargs(config, dtype, quantization, cache_dir):
    return {
        "model_name": config["base_model_repository"],
        "revision": config["base_model_revision"],
        "max_seq_length": config["optimization"]["max_sequence_length"],
        "dtype": dtype,
        "load_in_4bit": True,
        "quantization_config": quantization,
        "trust_remote_code": False,
        "use_exact_model_name": True,
        "fast_inference": False,
        "local_files_only": True,
        "cache_dir": str(cache_dir),
    }


def sft_kwargs(config: dict[str, Any], output: Path) -> dict[str, Any]:
    opt, checkpoints = config["optimization"], config["checkpoints"]
    if opt["max_steps"] != 8 or opt["max_sequence_length"] != 1536:
        raise ValueError("this runner only accepts the frozen eight-step smoke")
    if opt["warmup_ratio"] != 0.0:
        raise ValueError("this runner only accepts the frozen zero-warmup smoke")
    return {
        "output_dir": str(output),
        "max_length": opt["max_sequence_length"],
        "max_steps": 8,
        "num_train_epochs": 1.0,
        "per_device_train_batch_size": opt["per_device_train_batch_size"],
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": opt["gradient_accumulation_steps"],
        "gradient_checkpointing": opt["gradient_checkpointing"],
        "learning_rate": opt["learning_rate"],
        "weight_decay": opt["weight_decay"],
        "warmup_steps": 0,
        "optim": opt["optimizer"],
        "lr_scheduler_type": opt["scheduler"],
        "bf16": opt["precision"] == "bf16",
        "fp16": opt["precision"] == "fp16",
        "max_grad_norm": opt["gradient_clip_norm"],
        "logging_steps": opt["logging_steps"],
        "eval_strategy": "steps",
        "eval_steps": checkpoints["evaluation_steps"],
        "save_strategy": "steps",
        "save_steps": checkpoints["save_steps"],
        "save_total_limit": checkpoints["save_total_limit"],
        "load_best_model_at_end": False,
        "seed": config["seed"],
        "data_seed": config["seed"],
        "dataset_kwargs": {"skip_prepare_dataset": True},
        "completion_only_loss": True,
        "assistant_only_loss": False,
        "packing": False,
        "eval_packing": False,
        "padding_free": False,
        "remove_unused_columns": False,
        "dataset_num_proc": 1,
        "dataloader_num_workers": 0,
        "dataloader_pin_memory": False,
        "report_to": "none",
        "push_to_hub": False,
    }


def make_collator(deps, pad):
    return strict_call(
        deps.DataCollator,
        {
            "pad_token_id": pad,
            "completion_only_loss": True,
            "padding_free": False,
            "pad_to_multiple_of": None,
            "return_tensors": "pt",
        },
    )


def load_exact_tokenizer(data, deps, directory):
    """Replay all token IDs and masks using only the two authenticated source files."""
    for name, raw in data.tokenizer_files:
        (directory / name).write_bytes(raw)
    tokenizer = deps.AutoTokenizer.from_pretrained(
        str(directory),
        local_files_only=True,
        trust_remote_code=False,
    )
    identity = data.tokenization["tokenizer"]
    for key in ("pad_token_id", "eos_token_id"):
        if getattr(tokenizer, key, None) != identity[key]:
            raise ValueError(f"local tokenizer {key} differs from S50")
    if sha256(tokenizer.get_chat_template().encode()) != identity["chat_template_sha256"]:
        raise ValueError("local tokenizer chat template differs from S50")
    control = data.tokenization["chat_template_control"]
    kwargs = (
        {}
        if control["mode"] == "DEFAULT_NON_THINKING"
        else {
            control["argument_name"]: control["argument_value"],
        }
    )
    for entry, expected in zip(data.prepared.records, data.examples, strict=True):
        observation, row = audit_tokenized_record(
            entry["record"],
            tokenizer=tokenizer,
            max_length=1536,
            template_kwargs=kwargs,
        )
        if observation["issues"] or row != expected.to_features():
            raise ValueError(f"token IDs or mask changed: {expected.sample_id}")
    return tokenizer


def verify_trainable_parameters(model):
    trainable = 0
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            if "lora_" not in name:
                raise ValueError(f"non-LoRA parameter is trainable: {name}")
            trainable += parameter.numel()
    if not trainable:
        raise ValueError("no trainable adapter parameters")
    return trainable


def artifact_inventory(root: Path) -> list[dict[str, object]]:
    inventory = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("export/checkpoint contains a symbolic link")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if total > 2_000_000_000 or len(inventory) >= 200:
            raise ValueError("smoke artifacts exceed the bounded export inventory")
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            }
        )
    return inventory


def verified_checkpoint_inventory(path: Path, step: int) -> list[dict[str, object]]:
    """Require resumable metadata plus safetensors adapter weights for each smoke checkpoint."""
    required = (
        path / "trainer_state.json",
        path / "adapter_config.json",
        path / "adapter_model.safetensors",
    )
    if not all(item.is_file() for item in required):
        raise ValueError(f"checkpoint at step {step} lacks safetensors adapter evidence")
    for forbidden in ("adapter_model.bin", "pytorch_model.bin"):
        if (path / forbidden).exists():
            raise ValueError(
                f"checkpoint at step {step} contains unsafe model-weight serialization: {forbidden}"
            )
    return artifact_inventory(path)


def watchdog(callback_base, deadline):
    class BoundedSmokeCallback(callback_base):
        def on_step_begin(self, args, state, control, **kwargs):
            if time.monotonic() > deadline:
                raise TimeoutError("smoke elapsed-time budget exceeded at step boundary")
            if state.global_step >= 8:
                raise ValueError("smoke attempted an optimizer step beyond eight")
            return control

    return BoundedSmokeCallback()


def perform_training(
    data: VerifiedSmokeInputs,
    deps,
    output: Path,
    *,
    timeout_seconds: int,
    progress=None,
):
    """Run only after CLI authorization. Tests inject fake dependencies, never actual weights."""
    progress = {} if progress is None else progress
    output.mkdir(parents=True, exist_ok=True)
    config = data.prepared.configuration
    torch = deps.torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("smoke requires exactly one visible CUDA GPU")
    if not torch.cuda.is_bf16_supported():
        raise ValueError("the frozen smoke requires BF16 support")
    if os.environ.get("WORLD_SIZE", "1") != "1":
        raise ValueError("distributed training is not authorized")
    torch.manual_seed(config["seed"])
    torch.cuda.manual_seed_all(config["seed"])
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    collator = make_collator(deps, data.tokenization["tokenizer"]["pad_token_id"])
    audit = audit_collator(data, collator)
    with tempfile.TemporaryDirectory(prefix="orchestwin-smoke-tokenizer-") as tmp:
        tokenizer = load_exact_tokenizer(data, deps, Path(tmp))
        quant = config["quantization"]
        dtype = torch.bfloat16 if quant["compute_dtype"] == "bfloat16" else torch.float16
        quantization = strict_call(
            deps.BitsAndBytesConfig,
            {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": quant["quantization_type"],
                "bnb_4bit_compute_dtype": dtype,
                "bnb_4bit_use_double_quant": quant["double_quantization"],
            },
        )
        cache = Path(os.environ.get("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
        model, _ = strict_call(
            deps.FastLanguageModel.from_pretrained,
            model_loading_kwargs(config, dtype, quantization, cache),
        )
        progress["model_weights_loaded"] = True
        observed = getattr(getattr(model, "config", None), "_commit_hash", None)
        if observed != config["base_model_revision"]:
            raise ValueError(
                f"base revision mismatch: requested={config['base_model_revision']}; "
                f"observed={observed}"
            )
        if getattr(model, "is_loaded_in_4bit", False) is not True:
            raise ValueError("model did not attest four-bit loading")
        observed_quant = getattr(model.config, "quantization_config", None)
        if hasattr(observed_quant, "to_dict"):
            observed_quant = observed_quant.to_dict()
        if not isinstance(observed_quant, dict) or any(
            observed_quant.get(k) != v
            for k, v in {
                "load_in_4bit": True,
                "bnb_4bit_quant_type": "nf4",
                "bnb_4bit_use_double_quant": True,
            }.items()
        ):
            raise ValueError("observed quantization differs from the frozen NF4 policy")
        lora = config["adapter"]
        model = deps.FastLanguageModel.get_peft_model(
            model,
            r=lora["rank"],
            target_modules=lora["target_modules"],
            lora_alpha=lora["alpha"],
            lora_dropout=lora["dropout"],
            bias=lora["bias"],
            use_gradient_checkpointing="unsloth",
            random_state=config["seed"],
            use_rslora=lora["use_rslora"],
        )
        trainable = verify_trainable_parameters(model)
        model.config.use_cache = False
        model.config.pad_token_id = tokenizer.pad_token_id
        args = strict_call(deps.SFTConfig, sft_kwargs(config, output / "checkpoints"))
        trainer = strict_call(
            deps.SFTTrainer,
            {
                "model": model,
                "args": args,
                "train_dataset": deps.Dataset.from_list(data.rows("train")),
                "eval_dataset": deps.Dataset.from_list(data.rows("validation")),
                "processing_class": tokenizer,
                "data_collator": collator,
                "callbacks": [watchdog(deps.TrainerCallback, started + timeout_seconds)],
            },
        )
        # Inspect what the trainer actually retains, not just its constructor kwargs.
        for split, dataset in (
            ("train", trainer.train_dataset),
            ("validation", trainer.eval_dataset),
        ):
            expected = data.rows(split)
            if len(dataset) != len(expected) or any(
                dataset[i] != row for i, row in enumerate(expected)
            ):
                raise ValueError("trainer changed pretokenized rows or supervision masks")
        if audit_collator(data, trainer.data_collator) != audit:
            raise ValueError("trainer collator changed after construction")
        progress["phase"] = "TRAINING"
        progress["training_call_attempted"] = True
        try:
            trainer.train()
        finally:
            progress["optimizer_steps_completed"] = trainer.state.global_step
            progress["training_executed"] = trainer.state.global_step > 0
            progress["partial_metrics"] = [
                {
                    key: value
                    for key, value in entry.items()
                    if type(value) in (int, float) and math.isfinite(value)
                }
                for entry in trainer.state.log_history
                if isinstance(entry, dict)
            ]
        torch.cuda.synchronize()
        if trainer.state.global_step != 8:
            raise ValueError("trainer did not complete exactly eight optimization steps")
        logs = []
        for entry in trainer.state.log_history:
            numeric = {
                key: value
                for key, value in entry.items()
                if type(value) in (int, float) and math.isfinite(value)
            }
            if any(
                type(value) in (int, float) and not math.isfinite(value) for value in entry.values()
            ):
                raise ValueError("trainer reported a non-finite numeric metric")
            logs.append(numeric)
        if not any("loss" in entry for entry in logs) or not any(
            "eval_loss" in entry for entry in logs
        ):
            raise ValueError("training and validation loss observations are both required")
        checkpoints = []
        for step in (4, 8):
            path = output / "checkpoints" / f"checkpoint-{step}"
            checkpoints.append(
                {
                    "step": step,
                    "files": verified_checkpoint_inventory(path, step),
                }
            )
        progress["phase"] = "EXPORT"
        adapter_path = output / "adapter"
        adapter_path.mkdir()
        model.save_pretrained(adapter_path, safe_serialization=True)
        tokenizer.save_pretrained(adapter_path)
        if (
            not (adapter_path / "adapter_config.json").is_file()
            or not (adapter_path / "adapter_model.safetensors").is_file()
        ):
            raise ValueError("adapter export is incomplete")
    return {
        "global_step": 8,
        "trainable_lora_parameters": trainable,
        "observed_base_revision": observed,
        "peak_torch_reserved_memory_mib": round(torch.cuda.max_memory_reserved() / 1024**2),
        "duration_seconds": time.monotonic() - started,
        "collator_audit": audit,
        "metrics": logs,
        "checkpoints": checkpoints,
        "adapter_exported": True,
        "adapter_files": artifact_inventory(adapter_path),
        "adapter_reload_status": "NOT_RUN",
        "checkpoint_restore_status": "NOT_RUN",
        "quality_improvement_measured": False,
        "serving_validated": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("prepared", "tokenized", "source-evidence", "collator-report", "output-root"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--owner-id")
    for name in ("approve-fixtures", "approve-model-license", "approve-local-training"):
        parser.add_argument(f"--{name}", action="store_true")
    args = parser.parse_args(argv)
    output = None
    result = {
        "schema_version": 1,
        "runtime_id": RUNTIME_ID,
        "started_at": datetime.now(UTC).isoformat(),
        "training_executed": False,
        "model_weights_loaded": False,
        "model_selected": False,
        "full_training_approved": False,
        "network_authorized": False,
        "implementation_sha256": sha256(Path(__file__).read_bytes()),
    }
    try:
        approvals = None if args.preflight_only else authorize(args, dict(os.environ))
        result["owner_declarations"] = approvals
        data = load_verified_smoke_inputs(
            repository_root=ROOT,
            preparation_root=args.prepared,
            tokenization_root=args.tokenized,
            source_evidence_path=args.source_evidence,
        )
        prior = read_snapshot(args.collator_report)
        if (
            prior.get("policy_id") != COLLATION_POLICY_ID
            or prior.get("status") != "COLLATOR_VERIFIED_NOT_AUTHORIZED"
            or prior.get("training_executed") is not False
            or prior.get("inputs") != data.identity
        ):
            raise ValueError("collator report belongs to different inputs")
        env_file = ROOT / "environments/training/artifacts/environment.json"
        lock = ROOT / "environments/training/uv.lock"
        if sha256(read_bounded(lock)) != data.prepared.preparation["package_lock_sha256"]:
            raise ValueError("training lock changed since preparation")
        if sha256(read_bounded(env_file)) != data.prepared.preparation["environment_sha256"]:
            raise ValueError("environment manifest changed since preparation")
        output = new_output_root(data, args.output_root)
        result["inputs"] = data.identity
        result["collator_report_sha256"] = sha256(read_bounded(args.collator_report))
        write_snapshot(output / "request-evidence.json", result)
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
            os.environ[key] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        cache = checked_path(
            Path(os.environ.get("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
        )
        if ROOT in cache.parents or cache == ROOT:
            raise ValueError("Hugging Face cache must remain outside the repository")
        os.environ["HF_HUB_CACHE"] = str(cache)
        deps = load_dependencies()
        versions = package_versions(("torch", "trl", "unsloth", "transformers", "peft", "datasets"))
        result["package_versions"] = versions
        if versions["trl"] != "0.24.0" or versions["unsloth"] != "2026.8.22":
            raise ValueError("this smoke requires the frozen TRL and Unsloth versions")
        collator = make_collator(deps, data.tokenization["tokenizer"]["pad_token_id"])
        observed = audit_collator(data, collator)
        if observed != prior.get("audit"):
            raise ValueError("patched runtime collator differs from the recorded preflight")
        if args.preflight_only:
            with tempfile.TemporaryDirectory(prefix="orchestwin-smoke-preflight-") as tmp:
                tokenizer = load_exact_tokenizer(data, deps, Path(tmp))
                config = data.prepared.configuration
                trainer_args = strict_call(
                    deps.SFTConfig, sft_kwargs(config, output / "unused-checkpoints")
                )
                inspect.signature(deps.SFTTrainer).bind(
                    model=object(),
                    args=trainer_args,
                    train_dataset=deps.Dataset.from_list(data.rows("train")),
                    eval_dataset=deps.Dataset.from_list(data.rows("validation")),
                    processing_class=tokenizer,
                    data_collator=collator,
                    callbacks=[],
                )
                inspect.signature(deps.FastLanguageModel.from_pretrained).bind(
                    **model_loading_kwargs(config, deps.torch.bfloat16, object(), cache)
                )
            result.update(
                status="TRAINER_CONTRACT_VERIFIED_NOT_AUTHORIZED",
                collator_audit=observed,
                token_ids_replayed=20,
                training_authorization="NOT_GRANTED",
            )
        else:
            # Mark an attempted run without pretending that a failed load reached optimizer steps.
            result["status"] = "TRAINING_ATTEMPTED"
            observations = perform_training(
                data, deps, output, timeout_seconds=1800, progress=result
            )
            result.update(
                status="SMOKE_TRAINING_COMPLETED_RELOAD_PENDING",
                observations=observations,
                training_executed=True,
                model_weights_loaded=True,
            )
        code = 0
    except KeyboardInterrupt:
        result.update(
            status="INTERRUPTED",
            failure_kind="KeyboardInterrupt",
            training_completion_attested=False,
        )
        code = 130
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, ModuleNotFoundError):
            kind = "MISSING_DEPENDENCY"
        elif isinstance(error, TimeoutError):
            kind = "TIME_LIMIT"
        elif "out of memory" in str(error).casefold():
            kind = "OUT_OF_MEMORY"
        elif result.get("phase") == "EXPORT":
            kind = "EXPORT_FAILED"
        elif isinstance(error, (TypeError, ValueError, KeyError)):
            kind = "INVALID_INPUT_OR_RUNTIME_CONTRACT"
        elif isinstance(error, OSError):
            kind = "ARTIFACT_IO_FAILED"
        else:
            kind = "TRAINING_RUNTIME_FAILED"
        result.update(
            status="FAILED",
            failure_kind=kind,
            exception_type=type(error).__name__,
            failure_message=str(error)[:2000],
            training_completion_attested=False,
        )
        print(f"qlora_smoke_failed: {type(error).__name__}: {error}", file=sys.stderr)
        code = 22
    if output is not None:
        result["completed_at"] = datetime.now(UTC).isoformat()
        write_snapshot(output / "result.json", result)
        print(output / "result.json")
    if code == 0:
        print(f"qlora_smoke: {result['status']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
