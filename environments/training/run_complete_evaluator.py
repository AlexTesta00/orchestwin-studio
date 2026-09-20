#!/usr/bin/env python3
"""Prepare training-only caches or execute a bounded, resumable cloud candidate run."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
import time
import tomllib
from pathlib import Path

from complete_training_data import (
    MAX_SEQUENCE,
    MODEL,
    REVISION,
    TokenDataset,
    digest,
    prepare_cache,
    save,
)
from complete_training_runtime import (
    TrainingPolicy,
    check_checkpoint,
    contract,
    trainer_components,
    training_arguments,
)

DIRECTORY = Path(__file__).resolve().parent


def runtime_identity():
    lock = tomllib.loads((DIRECTORY / "uv.lock").read_text())
    names = {
        "torch",
        "transformers",
        "accelerate",
        "peft",
        "bitsandbytes",
        "tokenizers",
        "unsloth",
        "unsloth-zoo",
        "safetensors",
        "triton",
    }
    expected = {p["name"]: p["version"] for p in lock["package"] if p["name"] in names}
    actual = {name: importlib.metadata.version(name) for name in sorted(names)}
    # A platform build suffix does not change the locked Python distribution version.
    if any(actual[name].split("+")[0] != version for name, version in expected.items()):
        raise ValueError("cloud runtime differs from the committed dependency lock")
    if sys.version_info[:2] != (3, 13):
        raise ValueError("the locked training runtime requires Python 3.13")
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("exactly one CUDA GPU required")
    if not torch.cuda.is_bf16_supported():
        raise ValueError("native bf16 support required")
    return dict(
        python=platform.python_version(),
        packages=actual,
        cuda=torch.version.cuda,
        gpu=torch.cuda.get_device_name(),
        vram=torch.cuda.get_device_properties(0).total_memory,
        lock_sha256=digest(DIRECTORY / "uv.lock"),
    )


def train(args, *, max_sequence=MAX_SEQUENCE, additional_sources=()):
    if not args.authorize_cloud_training:
        raise ValueError("explicit cloud training authorization flag required")
    if not os.environ.get("RUNPOD_POD_ID"):
        raise ValueError("training must run on the registered Runpod Pod")
    guard = json.loads(args.guard_state.read_bytes())
    if (
        guard["stage"] != "ARMED"
        or guard["pod_id"] != os.environ["RUNPOD_POD_ID"]
        or not 0 <= time.time() - guard["updated_unix"] <= 180
        or guard["run_directory"] != str(args.output.resolve())
    ):
        raise ValueError("a fresh cloud budget guard bound to this run is required")
    policy = TrainingPolicy(**json.loads(args.policy.read_bytes()))
    dataset = TokenDataset(args.cache.resolve(), max_sequence=max_sequence)
    runtime = runtime_identity()
    sources = {
        name: digest(DIRECTORY / name)
        for name in (
            "run_complete_evaluator.py",
            "complete_training_runtime.py",
            "complete_training_data.py",
            *additional_sources,
        )
    }
    value = contract(args.cache, policy, runtime, sources, max_sequence=max_sequence)
    previous = None
    if args.resume:
        if json.loads((args.output / "contract.json").read_bytes()) != value:
            raise ValueError("resume cannot change cache, policy, sources, runtime or GPU")
        if args.resume.resolve().parent != (args.output / "checkpoints").resolve():
            raise ValueError("resume checkpoint must belong to this run")
        previous = check_checkpoint(args.resume, digest(args.output / "contract.json"))
        if previous["active_seconds"] >= policy.max_active_seconds:
            raise ValueError("the experiment's active-time allowance is exhausted")
        if previous["global_step"] >= policy.max_steps:
            raise ValueError("the experiment already completed its optimizer steps")
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        save(args.output / "contract.json", value)
    if (args.output / "STOP_REQUESTED").exists():
        raise ValueError("STOP_REQUESTED is present; resolve the prior stop before resuming")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    # Import Unsloth first to use the same efficient QLoRA model backend as the prior experiment.
    # isort: off
    from unsloth import FastLanguageModel
    import torch
    from transformers import AutoTokenizer
    # isort: on

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
    )
    model, loaded_tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL,
        revision=REVISION,
        max_seq_length=max_sequence,
        dtype=torch.bfloat16,
        load_in_4bit=True,
        use_exact_model_name=True,
        trust_remote_code=False,
        local_files_only=True,
    )
    if model.config._commit_hash != REVISION or not model.is_loaded_in_4bit:
        raise ValueError("base model identity or quantization mismatch")
    if loaded_tokenizer.get_vocab() != tokenizer.get_vocab():
        raise ValueError("model tokenizer differs from the pinned tokenizer")
    model = FastLanguageModel.get_peft_model(
        model,
        r=policy.rank,
        lora_alpha=policy.alpha,
        lora_dropout=0,
        bias="none",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        use_gradient_checkpointing="unsloth",
        random_state=2026091503,
    )
    model.config.use_cache = False
    trainer_class, collator_class, callback_class = trainer_components()
    callback = callback_class(
        args.output,
        policy,
        digest(args.output / "contract.json"),
        previous_seconds=previous["active_seconds"] if previous else 0,
        guard_state=args.guard_state,
    )
    trainer = trainer_class(
        model=model,
        args=training_arguments(args.output, policy),
        train_dataset=dataset,
        processing_class=tokenizer,
        data_collator=collator_class(tokenizer.pad_token_id),
        callbacks=[callback],
    )
    torch.cuda.reset_peak_memory_stats()
    try:
        trained = trainer.train(resume_from_checkpoint=str(args.resume) if args.resume else None)
        # Trainer normally saves the last step; explicitly ensure the final usable checkpoint exists.
        step = trainer.state.global_step
        checkpoint = args.output / "checkpoints" / f"checkpoint-{step}"
        if step and not (checkpoint / "seal.json").exists():
            trainer._save_checkpoint(model, None)
            callback.on_save(trainer.args, trainer.state, trainer.control)
        if step:
            check_checkpoint(checkpoint, callback.contract_sha256)
        completed = step >= policy.max_steps
        status = (
            "TRAINED_CANDIDATE_NOT_SELECTED"
            if completed
            else ("PAUSED_WITH_CHECKPOINT" if step else "STOPPED_BEFORE_FIRST_CHECKPOINT")
        )
        if completed:
            trainer.save_model(str(args.output / "adapter"))
        save(
            args.output / "training-result.json",
            dict(
                status=status,
                reason=callback.reason,
                global_step=step,
                max_steps=policy.max_steps,
                metrics=trained.metrics,
                active_seconds=callback.active_seconds(),
                checkpoint=str(checkpoint) if step else None,
                peak_reserved_bytes=torch.cuda.max_memory_reserved(),
                contract_sha256=callback.contract_sha256,
                final_cases_inferred=False,
                adapter_sha256=digest(args.output / "adapter" / "adapter_model.safetensors")
                if completed
                else None,
            ),
        )
        progress = json.loads((args.output / "progress.json").read_bytes())
        save(args.output / "progress.json", dict(progress, stage=status, updated_unix=time.time()))
    finally:
        dataset.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--data", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--manifest-sha256", required=True)
    prepare.add_argument("--group-limit", type=int)
    run = commands.add_parser("train")
    for flag in ("cache", "output", "policy", "guard-state"):
        run.add_argument(f"--{flag}", type=Path, required=True)
    run.add_argument("--resume", type=Path)
    run.add_argument("--authorize-cloud-training", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if DIRECTORY.parents[1] in args.output.parents:
        raise ValueError("write model and cache artifacts outside the repository")
    if args.action == "prepare":
        os.environ.update(
            HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false"
        )
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
        )
        report = prepare_cache(
            args.data, args.output, args.manifest_sha256, tokenizer, group_limit=args.group_limit
        )
        print(json.dumps(report), flush=True)
    else:
        train(args)


if __name__ == "__main__":
    main()
