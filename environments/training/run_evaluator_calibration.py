#!/usr/bin/env python3
"""Offline calibration experiment with immutable data, masked loss and raw held-out outputs.

This operator never replaces S67, serves an API, publishes a model or changes the
formal campaign. A trained candidate remains unselected until separate assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
MAX_LENGTH = 4096
SEED = 20260914


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def read_data(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["curriculum_id"] != "grounded-evaluator-contract-calibration-v1":
        raise ValueError("unexpected calibration dataset")
    rows = {}
    for split in ("train", "validation", "test"):
        name = split + ".jsonl"
        raw = (folder / name).read_bytes()
        expected = manifest["files"][name]
        if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError("calibration data changed")
        rows[split] = [json.loads(line) for line in raw.splitlines()]
        if len(rows[split]) != expected["rows"] or any(r["split"] != split for r in rows[split]):
            raise ValueError("calibration split changed")
    groups = [{r["group_id"] for r in rows[s]} for s in rows]
    if any(a & b for i, a in enumerate(groups) for b in groups[i + 1 :]):
        raise ValueError("counterfactual leakage")
    return manifest, rows


def encode(tokenizer, row):
    prefix = tokenizer.apply_chat_template(
        row["messages"][:2], tokenize=True, add_generation_prompt=True
    )
    full = tokenizer.apply_chat_template(
        row["messages"], tokenize=True, add_generation_prompt=False
    )
    if full[: len(prefix)] != prefix or len(full) > MAX_LENGTH or len(full) <= len(prefix):
        raise ValueError("tokenization truncation or completion-boundary mismatch")
    if tokenizer.eos_token_id not in full[len(prefix) :]:
        raise ValueError("completion EOS missing")
    return {
        "input_ids": full,
        "completion_mask": [0] * len(prefix) + [1] * (len(full) - len(prefix)),
    }


def assess(output, row):
    from orchestwin.models.strict_evaluator_json import strict_json_object, validate_evaluator_value
    from orchestwin.training.grounded_evaluator_curriculum import SCHEMA

    result = {"schema_valid": False, "judgement_correct": False, "reference_correct": False}
    try:
        payload = strict_json_object(output)
        validate_evaluator_value(payload, SCHEMA)
        result["schema_valid"] = True
        actual = (
            "INSUFFICIENT"
            if payload["abstained"]
            else "MISSING"
            if payload["findings"]
            else "PRESENT"
        )
        result["judgement_correct"] = actual == row["judgement"]
        expected = json.loads(row["messages"][-1]["content"])
        user = json.loads(row["messages"][1]["content"])
        artifact = user["input"]["artifact_bundle"]["artifacts"][0]
        result["reference_correct"] = all(
            f["artifact_id"] == artifact["artifact_id"]
            and f["artifact_version"] == artifact["version_number"]
            and f["location"] == artifact["location"]
            and set(f["evidence_refs"]) == set(user["allowed_evidence_refs"])
            and f["epistemic_status"] == "MODEL_INFERRED"
            and f["requires_human_validation"] is True
            for f in payload["findings"]
        ) and (bool(payload["findings"]) == bool(expected["findings"]))
        result["abstention_contract_valid"] = not payload["abstained"] or (
            not payload["findings"] and bool(payload["evidence_gaps"])
        )
        result["passed"] = all(result.values())
    except (ValueError, TypeError, KeyError):
        result["passed"] = False
    return result


def main():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["WANDB_DISABLED"] = "true"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("tokenize", "train", "evaluate"))
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter", type=Path)
    parser.add_argument("--decoding", choices=("prompted", "schema"), default="prompted")
    parser.add_argument(
        "--supervision", choices=("completion", "decision-balanced"), default="completion"
    )
    parser.add_argument("--authorize-local-training", action="store_true")
    args = parser.parse_args()
    if args.action == "evaluate" and args.supervision != "completion":
        raise ValueError("supervision selection applies to training or tokenization only")
    if args.action == "train" and (not args.authorize_local_training or args.adapter):
        raise ValueError("training requires explicit local scope and starts from the exact base")
    output = args.output.absolute()
    if ".." in output.parts or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError("output traversal is forbidden")
    if (
        output == ROOT
        or ROOT in output.parents
        or args.data.absolute() in (output, *output.parents)
    ):
        raise ValueError("use a new external experiment directory")
    manifest, rows = read_data(args.data)
    output.mkdir(parents=True, exist_ok=False)
    (output / "operator.py").write_bytes(Path(__file__).read_bytes())
    save(
        output / "protocol.json",
        {
            "action": args.action,
            "base_model": MODEL,
            "base_revision": REVISION,
            "dataset_manifest_sha256": hashlib.sha256(
                (args.data / "manifest.json").read_bytes()
            ).hexdigest(),
            "dataset_files": manifest["files"],
            "max_length": MAX_LENGTH,
            "seed": SEED,
            "network": False,
            "operator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "training_authorized": args.authorize_local_training,
            "adapter": str(args.adapter) if args.adapter else None,
            "deployment": False,
            "formal_case": False,
            "human_validation": False,
            "decoding": args.decoding,
            "supervision": args.supervision,
            "decoding_scope": "Prompted generation matches the current UT serving mode; schema masking is a separate experimental condition with canonical wire order.",
            "evaluation_selection": "First group by sorted opaque group ID in each family, both languages and all three states; 36 held-out cases. No test examples used for gradient updates.",
            "training_policy": {
                "rank": 16,
                "alpha": 32,
                "learning_rate": 0.0001,
                "epochs": 1,
                "batch": 1,
                "accumulation": 4,
                "completion_only_loss": True,
                "packing": False,
            },
        },
    )
    # Import Unsloth before Transformers as required by the installed runtime.
    os.chdir(ROOT / "environments/training")
    # isort: off
    from unsloth import FastLanguageModel
    import torch
    from transformers import AutoTokenizer
    # isort: on

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
    )
    tokenized = {
        split: [encode(tokenizer, row) for row in values] for split, values in rows.items()
    }
    stats = {
        s: {
            "rows": len(values),
            "min_tokens": min(len(r["input_ids"]) for r in values),
            "max_tokens": max(len(r["input_ids"]) for r in values),
            "completion_tokens": sum(sum(r["completion_mask"]) for r in values),
        }
        for s, values in tokenized.items()
    }
    save(
        output / "tokenization.json",
        {"splits": stats, "truncation": False, "completion_boundary_verified": True},
    )
    print(json.dumps(stats), flush=True)
    if args.supervision == "decision-balanced":
        from orchestwin.training import decision_supervision
        from orchestwin.training.decision_supervision import balance_decision_supervision

        tokenized["train"], supervision = balance_decision_supervision(
            rows["train"], tokenized["train"]
        )
        supervision_source = Path(decision_supervision.__file__).read_bytes()
        (output / "decision-supervision.py").write_bytes(supervision_source)
        supervision["source_sha256"] = hashlib.sha256(supervision_source).hexdigest()
        save(output / "supervision.json", supervision)
    if args.action == "tokenize":
        return
    if not torch.cuda.is_available():
        raise ValueError("a CUDA GPU is required")
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    model, loaded_tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL,
        revision=REVISION,
        max_seq_length=MAX_LENGTH,
        dtype=torch.bfloat16,
        load_in_4bit=True,
        use_exact_model_name=True,
        trust_remote_code=False,
        local_files_only=True,
    )
    if model.config._commit_hash != REVISION or not model.is_loaded_in_4bit:
        raise ValueError("model identity or quantization mismatch")
    if loaded_tokenizer.get_vocab() != tokenizer.get_vocab():
        raise ValueError("loaded tokenizer differs")
    torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    if args.action == "train":
        from datasets import Dataset
        from peft import get_peft_model_state_dict
        from safetensors.torch import save_file
        from trl import SFTConfig, SFTTrainer
        from trl.trainer.sft_trainer import DataCollatorForLanguageModeling

        model = FastLanguageModel.get_peft_model(
            model,
            r=16,
            lora_alpha=32,
            lora_dropout=0,
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=SEED,
        )
        model.config.use_cache = False
        collator = DataCollatorForLanguageModeling(
            pad_token_id=tokenizer.pad_token_id, completion_only_loss=True
        )
        # Check both variable-length padding and prompt masking before any optimizer step.
        batch_rows = [
            min(tokenized["train"], key=lambda r: len(r["input_ids"])),
            max(tokenized["train"], key=lambda r: len(r["input_ids"])),
        ]
        sparse = next(
            (
                row
                for row in tokenized["train"]
                if 0 in row["completion_mask"][row["completion_mask"].index(1) :]
            ),
            None,
        )
        if sparse is not None:
            batch_rows.append(sparse)
        batch = collator(batch_rows)
        for i, row in enumerate(batch_rows):
            expected = [
                token if mask else -100
                for token, mask in zip(row["input_ids"], row["completion_mask"], strict=True)
            ]
            labels = batch["labels"][i].tolist()
            if labels[: len(expected)] != expected or any(
                v != -100 for v in labels[len(expected) :]
            ):
                raise ValueError("completion-only collation mismatch")
        config = SFTConfig(
            output_dir=str(output / "training"),
            max_length=MAX_LENGTH,
            num_train_epochs=1,
            per_device_train_batch_size=1,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=4,
            learning_rate=1e-4,
            warmup_ratio=0.05,
            weight_decay=0.01,
            optim="adamw_8bit",
            bf16=True,
            gradient_checkpointing=True,
            logging_steps=10,
            eval_strategy="epoch",
            save_strategy="no",
            report_to="none",
            seed=SEED,
            data_seed=SEED,
            packing=False,
            completion_only_loss=True,
            assistant_only_loss=False,
            dataset_kwargs={"skip_prepare_dataset": True},
            remove_unused_columns=False,
            dataloader_num_workers=0,
            dataloader_pin_memory=False,
            push_to_hub=False,
        )
        trainer = SFTTrainer(
            model=model,
            args=config,
            train_dataset=Dataset.from_list(tokenized["train"]),
            eval_dataset=Dataset.from_list(tokenized["validation"]),
            processing_class=tokenizer,
            data_collator=collator,
        )
        if args.supervision == "decision-balanced":
            from orchestwin.training.decision_supervision import configure_decision_loss

            save(output / "loss-normalization.json", configure_decision_loss(trainer))
        trained = trainer.train()
        adapter = output / "adapter"
        adapter.mkdir()
        # Export safe weights/config directly; do not generate a Markdown model card.
        weights = {
            k: v.detach().cpu().contiguous() for k, v in get_peft_model_state_dict(model).items()
        }
        save_file(weights, str(adapter / "adapter_model.safetensors"))
        model.peft_config["default"].save_pretrained(adapter)
        tokenizer.save_pretrained(adapter)
        trainer.state.save_to_json(str(output / "trainer-state.json"))
        save(
            output / "training-result.json",
            {
                "status": "TRAINED_CANDIDATE_NOT_SELECTED",
                "metrics": trained.metrics,
                "seconds": time.monotonic() - started,
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
                "adapter_sha256": hashlib.sha256(
                    (adapter / "adapter_model.safetensors").read_bytes()
                ).hexdigest(),
                "config_sha256": hashlib.sha256(
                    (adapter / "adapter_config.json").read_bytes()
                ).hexdigest(),
                "optimizer_steps": trainer.state.global_step,
            },
        )
        return
    if args.adapter:
        from peft import PeftModel

        adapter_config = json.loads((args.adapter / "adapter_config.json").read_text())
        if adapter_config["base_model_name_or_path"] != MODEL:
            raise ValueError("adapter base mismatch")
        save(
            output / "adapter-identity.json",
            {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (
                    args.adapter / "adapter_config.json",
                    args.adapter / "adapter_model.safetensors",
                )
            },
        )
        model = PeftModel.from_pretrained(
            model, args.adapter, is_trainable=False, local_files_only=True
        )
    FastLanguageModel.for_inference(model)
    from orchestwin.models.schema_decoding import POLICY, build_schema_processor_factory
    from orchestwin.training.grounded_evaluator_curriculum import FAMILIES, SCHEMA

    factory = (
        build_schema_processor_factory(tokenizer, torch, model.config.vocab_size)
        if args.decoding == "schema"
        else None
    )
    save(
        output / "decoding.json",
        {
            "policy": POLICY if factory else "PROMPTED_UNCONSTRAINED_STRICT_VALIDATION",
            "output_repair": False,
            "schema_decoding_source_sha256": hashlib.sha256(
                (ROOT / "src/orchestwin/models/schema_decoding.py").read_bytes()
            ).hexdigest(),
        },
    )
    selected_groups = {
        min(r["group_id"] for r in rows["test"] if r["family"] == f) for f in FAMILIES
    }
    selected = sorted(
        (r for r in rows["test"] if r["group_id"] in selected_groups),
        key=lambda r: (r["family"], r["locale"], r["judgement"]),
    )
    save(
        output / "selection.json",
        [{k: r[k] for k in ("group_id", "family", "locale", "judgement")} for r in selected],
    )
    results = []
    for number, row in enumerate(selected, 1):
        encoded = tokenizer.apply_chat_template(
            row["messages"][:2],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
        encoded = {k: v.to(model.device) for k, v in encoded.items()}
        length = encoded["input_ids"].shape[-1]
        if length + 900 > MAX_LENGTH:
            raise ValueError("held-out input exceeds the complete generation window")
        processor = factory(SCHEMA, length) if factory else None
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=900,
                max_time=120,
                logits_processor=[processor] if processor else [],
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        tokens = generated[0, length:]
        raw = tokenizer.decode(tokens, skip_special_tokens=True)
        measured = assess(raw, row)
        measured.update(
            ordinal=number,
            family=row["family"],
            locale=row["locale"],
            judgement=row["judgement"],
            schema_complete=processor.finish(generated) if processor else measured["schema_valid"],
            eos_finished=bool(len(tokens) and int(tokens[-1]) == tokenizer.eos_token_id),
            output_tokens=len(tokens),
            input_tokens=length,
        )
        measured["passed"] = (
            measured["passed"] and measured["schema_complete"] and measured["eos_finished"]
        )
        save(
            output / f"{number:02d}-output.json",
            {
                "input_messages": row["messages"][:2],
                "raw_output": raw,
                "token_ids": tokens.tolist(),
                "assessment": measured,
            },
        )
        results.append(measured)
        print(json.dumps(measured), flush=True)
    save(
        output / "evaluation-result.json",
        {
            "cases": results,
            "passed": sum(r["passed"] for r in results),
            "total": len(results),
            "seconds": time.monotonic() - started,
            "scope": "HELD_OUT_SYNTHETIC_CONTRACT_CHECKS_NOT_REAL_USER_VALIDATION",
            "selected_for_production": False,
        },
    )


if __name__ == "__main__":
    main()
