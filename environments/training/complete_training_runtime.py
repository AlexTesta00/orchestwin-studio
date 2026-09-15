"""Resumable, single-GPU completion training with a sealed experiment contract."""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from complete_training_data import MAX_SEQUENCE, SEED, digest, padded_rows, save


@dataclass(frozen=True)
class TrainingPolicy:
    max_steps: int = 40
    batch_size: int = 1
    accumulation: int = 4
    learning_rate: float = 1e-4
    rank: int = 16
    alpha: int = 32
    save_steps: int = 10
    max_active_seconds: int = 3600

    def __post_init__(self):
        for name in (
            "max_steps",
            "batch_size",
            "accumulation",
            "rank",
            "alpha",
            "save_steps",
            "max_active_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"positive integer required: {name}")
        if not math.isfinite(self.learning_rate) or not 0 < self.learning_rate <= 0.001:
            raise ValueError("invalid learning rate")
        if self.save_steps > self.max_steps:
            raise ValueError("checkpoint interval exceeds the experiment")


def file_inventory(directory):
    return {
        p.relative_to(directory).as_posix(): digest(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != "seal.json"
    }


def check_checkpoint(path, contract_sha256):
    """Reject partial checkpoints and provenance changes before loading any pickle state."""
    path = Path(path)
    seal = json.loads((path / "seal.json").read_bytes())
    if seal["contract_sha256"] != contract_sha256:
        raise ValueError("checkpoint belongs to a different experiment contract")
    required = {
        "adapter_model.safetensors",
        "adapter_config.json",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
        "trainer_state.json",
    }
    if not required <= seal["files"].keys() or file_inventory(path) != seal["files"]:
        raise ValueError("incomplete or changed checkpoint")
    state = json.loads((path / "trainer_state.json").read_bytes())
    if (
        state["global_step"] != seal["global_step"]
        or path.name != f"checkpoint-{seal['global_step']}"
    ):
        raise ValueError("checkpoint step mismatch")
    if not math.isfinite(seal["active_seconds"]) or seal["active_seconds"] < 0:
        raise ValueError("invalid checkpoint timing")
    return seal


def trainer_components():
    # Import only inside the isolated training runtime; CPU control tests remain lightweight.
    import torch
    from peft import get_peft_model_state_dict
    from safetensors.torch import save_file
    from transformers import Trainer, TrainerCallback

    class EpochSampler(torch.utils.data.Sampler):
        def __init__(self, dataset):
            self.size, self.epoch = len(dataset), 0

        def set_epoch(self, epoch):
            self.epoch = epoch

        def __len__(self):
            return self.size

        def __iter__(self):
            indices = list(range(self.size))
            random.Random(SEED + self.epoch).shuffle(indices)
            return iter(indices)

    class CompletionCollator:
        def __init__(self, pad_token_id):
            self.pad_token_id = pad_token_id

        def __call__(self, rows):
            return {
                key: torch.tensor(value, dtype=torch.long)
                for key, value in padded_rows(rows, self.pad_token_id).items()
            }

    class CompleteTrainer(Trainer):
        def _get_train_sampler(self, train_dataset=None):
            return EpochSampler(self.train_dataset if train_dataset is None else train_dataset)

        def _save(self, output_dir=None, state_dict=None):
            # PEFT's generic save_pretrained also generates a README; export only artifacts.
            destination = Path(output_dir or self.args.output_dir)
            destination.mkdir(parents=True, exist_ok=True)
            weights = get_peft_model_state_dict(
                self.model, state_dict=state_dict, save_embedding_layers=False
            )
            save_file(
                {k: v.detach().cpu().contiguous() for k, v in weights.items()},
                str(destination / "adapter_model.safetensors"),
            )
            self.model.peft_config["default"].save_pretrained(destination)
            if self.processing_class is not None:
                self.processing_class.save_pretrained(destination)
            torch.save(self.args, destination / "training_args.bin")

    class ProgressCallback(TrainerCallback):
        def __init__(
            self,
            output,
            policy,
            contract_sha256,
            *,
            previous_seconds=0,
            clock=time.monotonic,
            guard_state=None,
        ):
            self.output, self.policy = Path(output), policy
            self.contract_sha256 = contract_sha256
            self.clock, self.started = clock, clock()
            self.previous_seconds = previous_seconds
            self.initial_step = None
            self.guard_state = guard_state
            self.reason = None

        def active_seconds(self):
            return self.previous_seconds + self.clock() - self.started

        def on_train_begin(self, args, state, control, **kwargs):
            self.initial_step = state.global_step
            return self.on_step_end(args, state, control)

        def on_step_end(self, args, state, control, **kwargs):
            elapsed = self.clock() - self.started
            completed = state.global_step - self.initial_step
            seconds_per_step = elapsed / completed if completed >= 5 else None
            if (self.output / "STOP_REQUESTED").exists():
                self.reason = "STOP_REQUESTED"
            elif self.active_seconds() >= self.policy.max_active_seconds:
                self.reason = "ACTIVE_TIME_LIMIT"
            if self.guard_state is not None:
                try:
                    guard = json.loads(Path(self.guard_state).read_bytes())
                    fresh = 0 <= time.time() - guard["updated_unix"] <= 180
                    if guard["stage"] != "ARMED" or not fresh:
                        self.reason = "CLOUD_GUARD_NOT_HEALTHY"
                except (OSError, ValueError, KeyError):
                    self.reason = "CLOUD_GUARD_NOT_HEALTHY"
            if self.reason:
                control.should_training_stop = True
                control.should_save = state.global_step > 0
            save(
                self.output / "progress.json",
                dict(
                    stage="STOPPING" if self.reason else "TRAINING",
                    reason=self.reason,
                    global_step=state.global_step,
                    max_steps=self.policy.max_steps,
                    active_seconds=self.active_seconds(),
                    session_seconds=elapsed,
                    session_steps=completed,
                    seconds_per_step=seconds_per_step,
                    eta_seconds=(self.policy.max_steps - state.global_step) * seconds_per_step
                    if seconds_per_step is not None
                    else None,
                    updated_unix=time.time(),
                    contract_sha256=self.contract_sha256,
                ),
            )
            return control

        def on_save(self, args, state, control, **kwargs):
            checkpoint = self.output / "checkpoints" / f"checkpoint-{state.global_step}"
            save(
                checkpoint / "seal.json",
                dict(
                    contract_sha256=self.contract_sha256,
                    global_step=state.global_step,
                    active_seconds=self.active_seconds(),
                    files=file_inventory(checkpoint),
                ),
            )
            check_checkpoint(checkpoint, self.contract_sha256)

    return CompleteTrainer, CompletionCollator, ProgressCallback


def training_arguments(output, policy, *, cpu=False):
    from transformers import TrainingArguments

    return TrainingArguments(
        output_dir=str(Path(output) / "checkpoints"),
        max_steps=policy.max_steps,
        per_device_train_batch_size=policy.batch_size,
        gradient_accumulation_steps=policy.accumulation,
        learning_rate=policy.learning_rate,
        warmup_steps=math.ceil(policy.max_steps * 0.05),
        weight_decay=0.01,
        optim="adamw_torch" if cpu else "adamw_8bit",
        bf16=not cpu,
        use_cpu=cpu,
        gradient_checkpointing=not cpu,
        logging_steps=5,
        eval_strategy="no",
        save_strategy="steps",
        save_steps=policy.save_steps,
        save_total_limit=3,
        save_only_model=False,
        report_to="none",
        seed=SEED,
        data_seed=SEED,
        remove_unused_columns=False,
        dataloader_num_workers=0,
        dataloader_pin_memory=False,
        accelerator_config={"use_seedable_sampler": False},
        ignore_data_skip=False,
        push_to_hub=False,
        disable_tqdm=True,
    )


def contract(cache, policy, runtime, sources):
    return dict(
        version=1,
        cache_manifest_sha256=digest(Path(cache) / "cache.json"),
        training_policy=asdict(policy),
        runtime=runtime,
        sources=sources,
        max_sequence=MAX_SEQUENCE,
        loss="ALL_COMPLETION_TOKENS_INCLUDING_EOS",
        sampler=dict(policy="PYTHON_SHUFFLE_WITHOUT_REPLACEMENT_PER_EPOCH", seed=SEED),
        packing=False,
        final_cases_inferred=False,
        production_selected=False,
    )
