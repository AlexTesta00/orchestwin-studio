#!/usr/bin/env python3
"""Opt-in CPU integration probe: randomly initialized tiny Qwen3, never thesis weights/data."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from complete_training_data import save
from complete_training_runtime import (
    TrainingPolicy,
    check_checkpoint,
    trainer_components,
    training_arguments,
)


def verify(output):
    os.environ.update(CUDA_VISIBLE_DEVICES="", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    import torch
    from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
    from transformers import Qwen3Config, Qwen3ForCausalLM, TrainerCallback

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    trainer_class, collator_class, callback_class = trainer_components()
    policy = TrainingPolicy(max_steps=8, save_steps=3, accumulation=2, max_active_seconds=300)
    output.mkdir(parents=True, exist_ok=False)

    class Examples:
        def __init__(self):
            self.seen = []

        def __len__(self):
            return 12

        def __getitem__(self, index):
            return dict(input_ids=[1, index + 3, 4, 5, 2], labels=[-100, -100, 4, 5, 2])

    class RecordingTrainer(trainer_class):
        def training_step(self, model, inputs, num_items_in_batch=None):
            # Accelerate prefetches a batch. Compare consumed optimizer inputs, not lookups.
            self.train_dataset.seen.extend(inputs["input_ids"][:, 1].tolist())
            return super().training_step(model, inputs, num_items_in_batch)

    class Interrupt(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            if state.global_step == 3:
                control.should_training_stop = True
                control.should_save = True
            return control

    def build(directory, *, interrupted=False, previous_seconds=0):
        torch.manual_seed(17)
        config = Qwen3Config(
            vocab_size=32,
            hidden_size=16,
            intermediate_size=32,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=1,
            head_dim=8,
            max_position_embeddings=64,
            attention_dropout=0.1,
            use_cache=False,
            pad_token_id=0,
            bos_token_id=1,
            eos_token_id=2,
        )
        config._attn_implementation = "eager"
        model = get_peft_model(
            Qwen3ForCausalLM(config),
            LoraConfig(
                r=2,
                lora_alpha=4,
                lora_dropout=0.1,
                target_modules=["q_proj", "v_proj"],
                task_type="CAUSAL_LM",
            ),
        )
        dataset = Examples()
        directory.mkdir(exist_ok=True)
        callbacks = [
            callback_class(directory, policy, "cpu-probe", previous_seconds=previous_seconds)
        ]
        if interrupted:
            callbacks.append(Interrupt())
        trainer = RecordingTrainer(
            model=model,
            args=training_arguments(directory, policy, cpu=True),
            train_dataset=dataset,
            data_collator=collator_class(0),
            callbacks=callbacks,
        )
        return trainer, dataset

    continuous, continuous_data = build(output / "continuous")
    continuous.train()
    interrupted, interrupted_data = build(output / "resumed", interrupted=True)
    interrupted.train()
    checkpoint = output / "resumed/checkpoints/checkpoint-3"
    seal = check_checkpoint(checkpoint, "cpu-probe")
    resumed, resumed_data = build(output / "resumed", previous_seconds=seal["active_seconds"])
    resumed.train(resume_from_checkpoint=str(checkpoint))
    left, right = (
        get_peft_model_state_dict(t.model, save_embedding_layers=False)
        for t in (continuous, resumed)
    )
    assert left.keys() == right.keys()
    differences = {name: (left[name] - right[name]).abs().max().item() for name in left}
    assert all(value == 0 for value in differences.values()), differences
    assert continuous_data.seen == interrupted_data.seen + resumed_data.seen
    assert continuous.state.global_step == resumed.state.global_step == 8
    assert continuous.lr_scheduler.state_dict() == resumed.lr_scheduler.state_dict()
    for index, state in continuous.optimizer.state_dict()["state"].items():
        other = resumed.optimizer.state_dict()["state"][index]
        for name, value in state.items():
            assert (
                torch.equal(value, other[name]) if torch.is_tensor(value) else value == other[name]
            )
    assert not list(output.rglob("*.md"))
    report = dict(
        status="PASSED",
        device="CPU",
        pretrained_weights_loaded=False,
        thesis_examples_read=False,
        optimizer_steps=8,
        interrupted_at=3,
        crossed_epoch_boundary=True,
        sample_order_identical=True,
        adapter_parameters_bitwise_identical=True,
        optimizer_state_identical=True,
        scheduler_state_identical=True,
        dropout_enabled=True,
        max_parameter_difference=max(differences.values()),
    )
    save(output / "verification.json", report)
    print(report, flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    verify(parser.parse_args().output)
