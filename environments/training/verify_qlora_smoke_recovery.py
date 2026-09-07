#!/usr/bin/env python3
"""Verify S59 adapter reload and checkpoint-8 recovery in fresh, offline processes."""

from __future__ import annotations

import argparse
import gc
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)
from orchestwin.training.qlora_smoke_collation import (  # noqa: E402
    checked_path,
    load_verified_smoke_inputs,
    read_snapshot,
)
from orchestwin.training.qlora_smoke_recovery import (  # noqa: E402
    RECOVERY_POLICY_ID,
    SmokeRecoveryError,
    load_recovery_bundle,
    recovery_identity,
    verify_inventory,
)

TRAINING_GATE = "ORCHESTWIN_QLORA_SMOKE_ALLOW_TRAINING"
_WORKER_TIMEOUT_SECONDS = 600


def _write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    value = dict(payload)
    value["content_hash"] = snapshot_content_hash(value)
    path.write_bytes(canonical_json(value).encode("utf-8"))


def _new_output(path: Path) -> Path:
    path = path.absolute()
    artifacts = ROOT / "environments/training/artifacts"
    if ROOT not in path.parents or artifacts not in path.parents:
        raise SmokeRecoveryError("recovery output must remain inside training artifacts")
    if path.exists() or path.is_symlink():
        raise SmokeRecoveryError("recovery output must be a new directory")
    path.mkdir(parents=True)
    return path


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


def _load_runner_module():
    path = ROOT / "environments/training/run_qlora_smoke.py"
    spec = importlib.util.spec_from_file_location("orchestwin_recovery_smoke_runner", path)
    if spec is None or spec.loader is None:
        raise SmokeRecoveryError("could not load the bounded smoke runner module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cache_root() -> Path:
    path = checked_path(
        Path(os.environ.get("HF_HUB_CACHE", str(Path.home() / ".cache/huggingface/hub")))
    )
    if path == ROOT or ROOT in path.parents:
        raise SmokeRecoveryError("Hugging Face cache must remain outside the repository")
    return path


def _quantization(runner, deps, config):
    quant = config["quantization"]
    dtype = deps.torch.bfloat16 if quant["compute_dtype"] == "bfloat16" else deps.torch.float16
    value = runner.strict_call(
        deps.BitsAndBytesConfig,
        {
            "load_in_4bit": True,
            "bnb_4bit_quant_type": quant["quantization_type"],
            "bnb_4bit_compute_dtype": dtype,
            "bnb_4bit_use_double_quant": quant["double_quantization"],
        },
    )
    return dtype, value


def _observed_base_revision(model) -> str | None:
    base = model.get_base_model() if hasattr(model, "get_base_model") else model
    return getattr(getattr(base, "config", None), "_commit_hash", None)


def _lora_parameter_counts(model) -> tuple[int, int, list[str]]:
    total = 0
    trainable = 0
    unsafe_trainable = []
    for name, parameter in model.named_parameters():
        if "lora_" in name:
            total += parameter.numel()
            if parameter.requires_grad:
                trainable += parameter.numel()
        elif parameter.requires_grad:
            unsafe_trainable.append(name)
    return total, trainable, unsafe_trainable


def _load_exact_base(bundle, runner, deps):
    data = load_verified_smoke_inputs(
        repository_root=ROOT,
        preparation_root=bundle.bindings["prepared_root"],
        tokenization_root=bundle.bindings["tokenized_root"],
        source_evidence_path=bundle.bindings["source_evidence"],
    )
    config = data.prepared.configuration
    dtype, quantization = _quantization(runner, deps, config)
    model, tokenizer = runner.strict_call(
        deps.FastLanguageModel.from_pretrained,
        runner.model_loading_kwargs(config, dtype, quantization, _cache_root()),
    )
    observed = _observed_base_revision(model)
    if observed != bundle.request["base_model_revision"]:
        raise SmokeRecoveryError(
            "fresh base revision differs from the training request: "
            f"expected={bundle.request['base_model_revision']}; observed={observed}"
        )
    if getattr(model, "is_loaded_in_4bit", False) is not True:
        raise SmokeRecoveryError("fresh recovery base model is not loaded in four bit")
    return data, config, model, tokenizer, observed


def _adapter_worker(training_root: Path, output: Path) -> None:
    if os.environ.get(TRAINING_GATE) == "1":
        raise SmokeRecoveryError("recovery worker refuses the training authorization gate")
    bundle = load_recovery_bundle(ROOT, training_root)
    runner = _load_runner_module()
    deps = runner.load_dependencies()
    data, _, base_model, _, observed = _load_exact_base(bundle, runner, deps)

    from peft import PeftModel

    model = PeftModel.from_pretrained(
        base_model,
        str(bundle.adapter_root),
        is_trainable=False,
        local_files_only=True,
    )
    total_lora, trainable_lora, unsafe = _lora_parameter_counts(model)
    expected_lora = bundle.result["observations"]["trainable_lora_parameters"]
    if unsafe or total_lora != expected_lora:
        raise SmokeRecoveryError("fresh adapter reload does not match trained LoRA parameters")
    if trainable_lora != 0:
        raise SmokeRecoveryError("inference adapter reload unexpectedly leaves LoRA trainable")

    verify_inventory(bundle.adapter_root, bundle.result["observations"]["adapter_files"])
    payload = {
        "schema_version": 1,
        "policy_id": RECOVERY_POLICY_ID,
        "stage": "ADAPTER_RELOAD",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "ADAPTER_RELOAD_VERIFIED_FRESH_PROCESS",
        "identity": recovery_identity(bundle),
        "observed_base_revision": observed,
        "model_weights_loaded": True,
        "adapter_weights_loaded": True,
        "lora_parameter_count": total_lora,
        "trainable_lora_parameter_count": trainable_lora,
        "verification_training_executed": False,
        "optimizer_steps_added": 0,
        "network_authorized": False,
        "model_selected": False,
        "quality_improvement_measured": False,
        "serving_validated": False,
        "peak_torch_reserved_memory_mib": round(deps.torch.cuda.max_memory_reserved() / 1024**2),
    }
    _write_snapshot(output, payload)
    del model, base_model, data
    gc.collect()
    deps.torch.cuda.empty_cache()


def _no_step_callback(callback_base):
    class NoAdditionalStep(callback_base):
        optimizer_step_attempts = 0

        def on_step_begin(self, args, state, control, **kwargs):
            self.optimizer_step_attempts += 1
            raise RuntimeError("checkpoint recovery attempted an optimizer step beyond step 8")

    return NoAdditionalStep()


def _wrap_restore_method(trainer, name: str, calls: dict[str, int]) -> None:
    original = getattr(trainer, name, None)
    if not callable(original):
        raise SmokeRecoveryError(f"pinned Trainer runtime lacks recovery method: {name}")

    def wrapped(*args, **kwargs):
        calls[name] += 1
        return original(*args, **kwargs)

    setattr(trainer, name, wrapped)


def _ensure_terminal_rng_restore(
    trainer,
    checkpoint: Path,
    calls: dict[str, int],
) -> str:
    """Replay RNG state explicitly when a terminal checkpoint skips the epoch loop.

    Transformers restores model and optimizer/scheduler state before entering the epoch
    loop. RNG restoration happens inside the epoch loop. For a checkpoint already at
    max_steps, the epoch loop can legitimately be skipped, so verify the same pinned
    `_load_rng_state` path explicitly without authorizing any additional optimizer step.
    """
    observed = calls.get("_load_rng_state", 0)
    if observed > 0:
        return "AUTOMATIC_DURING_RESUME"
    before = observed
    trainer._load_rng_state(str(checkpoint))
    if calls.get("_load_rng_state", 0) != before + 1:
        raise SmokeRecoveryError("explicit terminal-checkpoint RNG replay was not observed")
    return "EXPLICIT_TERMINAL_CHECKPOINT_REPLAY"


def _checkpoint_worker(training_root: Path, output: Path) -> None:
    if os.environ.get(TRAINING_GATE) == "1":
        raise SmokeRecoveryError("checkpoint worker refuses the training authorization gate")
    bundle = load_recovery_bundle(ROOT, training_root)
    runner = _load_runner_module()
    deps = runner.load_dependencies()
    data, config, model, _, observed = _load_exact_base(bundle, runner, deps)

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
    initial_lora = runner.verify_trainable_parameters(model)
    expected_lora = bundle.result["observations"]["trainable_lora_parameters"]
    if initial_lora != expected_lora:
        raise SmokeRecoveryError("fresh recovery model has a different LoRA parameter count")

    model.config.use_cache = False
    model.config.pad_token_id = data.tokenization["tokenizer"]["pad_token_id"]
    collator = runner.make_collator(deps, data.tokenization["tokenizer"]["pad_token_id"])

    with tempfile.TemporaryDirectory(prefix="orchestwin-restore-output-") as temporary:
        args = runner.strict_call(
            deps.SFTConfig,
            runner.sft_kwargs(config, Path(temporary) / "unused-checkpoints"),
        )
        blocker = _no_step_callback(deps.TrainerCallback)
        trainer = runner.strict_call(
            deps.SFTTrainer,
            {
                "model": model,
                "args": args,
                "train_dataset": deps.Dataset.from_list(data.rows("train")),
                "eval_dataset": deps.Dataset.from_list(data.rows("validation")),
                "processing_class": runner.load_exact_tokenizer(
                    data,
                    deps,
                    Path(tempfile.mkdtemp(prefix="orchestwin-restore-tokenizer-")),
                ),
                "data_collator": collator,
                "callbacks": [blocker],
            },
        )

        calls = {
            "_load_from_checkpoint": 0,
            "_load_optimizer_and_scheduler": 0,
            "_load_rng_state": 0,
        }
        for name in tuple(calls):
            _wrap_restore_method(trainer, name, calls)

        before_step = trainer.state.global_step
        train_output = trainer.train(resume_from_checkpoint=str(bundle.checkpoint8))
        after_step = trainer.state.global_step
        automatic_restore_calls = dict(calls)
        rng_restore_mode = _ensure_terminal_rng_restore(trainer, bundle.checkpoint8, calls)

    if blocker.optimizer_step_attempts != 0:
        raise SmokeRecoveryError("checkpoint restore attempted additional optimization")
    if before_step != 0 or after_step != 8 or getattr(train_output, "global_step", None) != 8:
        raise SmokeRecoveryError("checkpoint restore did not recover exactly global_step 8")
    if automatic_restore_calls["_load_from_checkpoint"] < 1:
        raise SmokeRecoveryError("Trainer did not automatically restore checkpoint model state")
    if automatic_restore_calls["_load_optimizer_and_scheduler"] < 1:
        raise SmokeRecoveryError("Trainer did not automatically restore optimizer/scheduler state")
    if calls["_load_rng_state"] < 1:
        raise SmokeRecoveryError("checkpoint RNG state was not verified")
    if trainer.optimizer is None or trainer.lr_scheduler is None:
        raise SmokeRecoveryError("checkpoint restore did not reconstruct optimizer and scheduler")
    optimizer_state_entries = len(getattr(trainer.optimizer, "state", {}))
    if optimizer_state_entries < 1:
        raise SmokeRecoveryError("checkpoint restore produced an empty optimizer state")

    recorded = bundle.result["observations"]["checkpoints"][1]["files"]
    verify_inventory(bundle.checkpoint8, recorded)

    payload = {
        "schema_version": 1,
        "policy_id": RECOVERY_POLICY_ID,
        "stage": "CHECKPOINT_RESTORE",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "CHECKPOINT8_RESTORE_VERIFIED_FRESH_PROCESS",
        "identity": recovery_identity(bundle),
        "observed_base_revision": observed,
        "model_weights_loaded": True,
        "checkpoint_adapter_loaded": True,
        "trainer_automatic_restore_calls": automatic_restore_calls,
        "trainer_restore_calls": calls,
        "rng_restore_mode": rng_restore_mode,
        "trainer_global_step_before_restore": before_step,
        "trainer_global_step_after_restore": after_step,
        "train_output_global_step": train_output.global_step,
        "optimizer_state_entries": optimizer_state_entries,
        "scheduler_state": trainer.lr_scheduler.state_dict(),
        "additional_step_callback_attempts": blocker.optimizer_step_attempts,
        "verification_training_executed": False,
        "optimizer_steps_added": 0,
        "network_authorized": False,
        "model_selected": False,
        "quality_improvement_measured": False,
        "serving_validated": False,
        "peak_torch_reserved_memory_mib": round(deps.torch.cuda.max_memory_reserved() / 1024**2),
    }
    _write_snapshot(output, payload)


def _run_worker(mode: str, training_root: Path, output: Path) -> int:
    try:
        if mode == "adapter":
            _adapter_worker(training_root, output)
        elif mode == "checkpoint":
            _checkpoint_worker(training_root, output)
        else:
            raise SmokeRecoveryError("unknown recovery worker mode")
    except (
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        SmokeRecoveryError,
    ) as error:
        print(
            f"qlora_smoke_recovery_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22
    print(output)
    return 0


def _controller(training_root: Path, output_root: Path) -> int:
    if os.environ.get(TRAINING_GATE) == "1":
        print("recovery verification refuses the training authorization gate", file=sys.stderr)
        return 22
    try:
        bundle = load_recovery_bundle(ROOT, training_root)
        destination = _new_output(output_root)
        environment = _offline_environment()
        stage_reports = {}
        for mode in ("adapter", "checkpoint"):
            report_path = destination / f"{mode}-report.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker-mode",
                mode,
                "--training-root",
                str(training_root),
                "--worker-output",
                str(report_path),
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
            (destination / f"{mode}.stdout.log").write_text(
                completed.stdout,
                encoding="utf-8",
            )
            (destination / f"{mode}.stderr.log").write_text(
                completed.stderr,
                encoding="utf-8",
            )
            if completed.returncode != 0 or not report_path.is_file():
                raise SmokeRecoveryError(
                    f"{mode} fresh-process verification failed with exit {completed.returncode}"
                )
            report = read_snapshot(report_path)
            stage_reports[mode] = report

        adapter = stage_reports["adapter"]
        checkpoint = stage_reports["checkpoint"]
        if any(
            (
                adapter.get("status") != "ADAPTER_RELOAD_VERIFIED_FRESH_PROCESS",
                checkpoint.get("status") != "CHECKPOINT8_RESTORE_VERIFIED_FRESH_PROCESS",
                adapter.get("identity") != recovery_identity(bundle),
                checkpoint.get("identity") != recovery_identity(bundle),
                adapter.get("optimizer_steps_added") != 0,
                checkpoint.get("optimizer_steps_added") != 0,
                adapter.get("verification_training_executed") is not False,
                checkpoint.get("verification_training_executed") is not False,
            )
        ):
            raise SmokeRecoveryError("fresh-process stage reports violate recovery policy")

        final = {
            "schema_version": 1,
            "policy_id": RECOVERY_POLICY_ID,
            "report_id": "ut-evaluator-qlora-smoke-recovery-v1",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "QLORA_SMOKE_RECOVERY_VERIFIED",
            "identity": recovery_identity(bundle),
            "adapter_reload_status": adapter["status"],
            "checkpoint_restore_status": checkpoint["status"],
            "adapter_report_content_hash": adapter["content_hash"],
            "checkpoint_report_content_hash": checkpoint["content_hash"],
            "fresh_processes_used": 2,
            "verification_training_executed": False,
            "optimizer_steps_added": 0,
            "source_training_global_step": 8,
            "network_authorized": False,
            "redistribution_authorized": False,
            "full_training_authorized": False,
            "model_selected": False,
            "quality_improvement_measured": False,
            "serving_validated": False,
        }
        report_path = destination / "recovery-report.json"
        _write_snapshot(report_path, final)
    except (
        OSError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
        KeyError,
        SmokeRecoveryError,
    ) as error:
        print(
            f"qlora_smoke_recovery_controller_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22

    print(report_path)
    print("qlora_smoke_recovery: QLORA_SMOKE_RECOVERY_VERIFIED (0 optimizer steps added)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-root", required=True, type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--worker-mode",
        choices=("adapter", "checkpoint"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.worker_mode:
        if args.worker_output is None:
            parser.error("--worker-output is required for worker mode")
        return _run_worker(
            args.worker_mode,
            args.training_root,
            args.worker_output,
        )
    if args.output_root is None:
        parser.error("--output-root is required")
    return _controller(args.training_root, args.output_root)


if __name__ == "__main__":
    raise SystemExit(main())
