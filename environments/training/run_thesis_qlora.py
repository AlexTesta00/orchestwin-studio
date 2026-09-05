#!/usr/bin/env python3
"""Governed final-thesis QLoRA runner with completion-only supervision.

This runtime is deliberately separate from the historical generic run_qlora.py.
It consumes only a C65 thesis dataset with green S66 semantic/tokenizer preflights,
recreates the verified completion masks, trains one shared LoRA adapter, supports
explicit checkpoint resume, and never turns optimization success into an empirical
user-validity or quality-improvement claim.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.projects.requirements_primitives import (  # noqa: E402
    canonical_json,
    snapshot_content_hash,
)

TRAINING_GATE: Final = "ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING"
RUNTIME_ID: Final = "unsloth-final-thesis-qlora-v1"

EXPECTED_MODEL_REPOSITORY: Final = "Qwen/Qwen3-4B-Instruct-2507"
EXPECTED_MODEL_REVISION: Final = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
EXPECTED_POLICY_ID: Final = "qwen3-4b-thesis-qlora-v1"
EXPECTED_TRAIN_COUNT: Final = 19_256
EXPECTED_VALIDATION_COUNT: Final = 2_356
EXPECTED_INTERNAL_TEST_COUNT: Final = 2_388
EXPECTED_TOTAL_COUNT: Final = 24_000
EXPECTED_OPTIMIZER_STEPS: Final = 4_814
EXPECTED_MAX_SEQUENCE_LENGTH: Final = 1_536

EXPECTED_TOKENIZER_JSON_SHA256: Final = (
    "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
)
EXPECTED_TOKENIZER_CONFIG_SHA256: Final = (
    "c32490f354f7559c99627f61b1b3a94bfcbd31e1149ade76762ae44e2f4d5569"
)
EXPECTED_CHAT_TEMPLATE_SHA256: Final = (
    "9215cee970b5c8d15c7f9c6e257082068c1899a46634824ce3809ffd67f42cab"
)

_CHECKPOINT_PATTERN: Final = re.compile(r"checkpoint-([0-9]+)")


@dataclass(frozen=True, slots=True)
class FinalTrainingContract:
    dataset_root: Path
    preflight_root: Path
    materialization: dict[str, Any]
    quality: dict[str, Any]
    policy: dict[str, Any]
    semantic_preflight: dict[str, Any]
    tokenizer_preflight: dict[str, Any]
    train_sha256: str
    validation_sha256: str
    internal_test_sha256: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--preflight-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--owner-id", required=True)
    parser.add_argument("--resume-checkpoint", type=Path)
    parser.add_argument("--approve-synthetic-dataset", action="store_true")
    parser.add_argument("--approve-model-license", action="store_true")
    parser.add_argument("--approve-final-training", action="store_true")
    return parser.parse_args(argv)


def authorize(args: argparse.Namespace, environment: dict[str, str]) -> dict[str, object]:
    if environment.get(TRAINING_GATE) != "1":
        raise ValueError(f"training requires {TRAINING_GATE}=1")
    if not args.approve_synthetic_dataset:
        raise ValueError("explicit synthetic-dataset approval is required")
    if not args.approve_model_license:
        raise ValueError("explicit local model-license review declaration is required")
    if not args.approve_final_training:
        raise ValueError("explicit final-training approval is required")
    owner = args.owner_id
    if not isinstance(owner, str) or not owner.strip() or len(owner.strip()) > 128:
        raise ValueError("owner identifier must contain 1-128 non-whitespace characters")
    return {
        "owner_id": owner.strip(),
        "synthetic_dataset_review": "OWNER_DECLARED",
        "local_model_license_review": "OWNER_DECLARED",
        "final_local_training": "OWNER_DECLARED",
        "scope": "FINAL_THESIS_SHARED_USER_TWIN_EVALUATOR",
        "redistribution_approved": False,
        "empirical_user_validation_claimed": False,
    }


def strict_call(function: Any, values: dict[str, Any]) -> Any:
    try:
        inspect.signature(function).bind(**values)
    except (TypeError, ValueError) as error:
        raise ValueError(f"runtime cannot accept the exact required arguments: {error}") from error
    return function(**values)


def load_dependencies() -> SimpleNamespace:
    # Import order is intentional: Unsloth patches the HF/TRL stack first.
    # isort: off
    from unsloth import FastLanguageModel
    import torch
    from datasets import Dataset
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer, BitsAndBytesConfig, TrainerCallback
    from trl import SFTConfig, SFTTrainer
    from trl.trainer.sft_trainer import DataCollatorForLanguageModeling
    # isort: on

    return SimpleNamespace(
        FastLanguageModel=FastLanguageModel,
        torch=torch,
        Dataset=Dataset,
        hf_hub_download=hf_hub_download,
        AutoTokenizer=AutoTokenizer,
        BitsAndBytesConfig=BitsAndBytesConfig,
        TrainerCallback=TrainerCallback,
        SFTConfig=SFTConfig,
        SFTTrainer=SFTTrainer,
        DataCollator=DataCollatorForLanguageModeling,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected regular JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def read_authenticated_json_object(
    path: Path,
    *,
    expected_sha256: str,
    label: str,
) -> dict[str, Any]:
    # HF snapshot entries are symlinks into content-addressed blobs.
    # Authentication is based on the exact bytes, not symlink rejection.
    if not path.is_file():
        raise ValueError(f"{label} is not a readable file: {path}")
    raw = path.read_bytes()
    observed_sha256 = sha256_bytes(raw)
    if observed_sha256 != expected_sha256:
        raise ValueError(
            f"{label} SHA-256 changed: expected={expected_sha256}; observed={observed_sha256}"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def verify_snapshot_content_hash(value: dict[str, Any], *, label: str) -> None:
    recorded = value.get("content_hash")
    if not isinstance(recorded, str):
        raise ValueError(f"{label} lacks content_hash")
    payload = dict(value)
    payload.pop("content_hash")
    if snapshot_content_hash(payload) != recorded:
        raise ValueError(f"{label} content hash changed")


def checked_directory(path: Path, *, label: str) -> Path:
    path = path.absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError(f"{label} path must not contain symbolic links")
    if not path.is_dir():
        raise ValueError(f"{label} must identify a directory")
    return path


def _inventory_entry(
    materialization: dict[str, Any],
    relative_path: str,
) -> dict[str, Any]:
    files = materialization.get("files")
    if not isinstance(files, list):
        raise ValueError("materialization file inventory is missing")
    matches = [
        item for item in files if isinstance(item, dict) and item.get("path") == relative_path
    ]
    if len(matches) != 1:
        raise ValueError(f"materialization inventory does not bind {relative_path}")
    return matches[0]


def _verify_bound_file(
    dataset_root: Path,
    materialization: dict[str, Any],
    relative_path: str,
) -> str:
    item = _inventory_entry(materialization, relative_path)
    path = dataset_root / relative_path
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"dataset artifact changed: {relative_path}")
    digest = sha256_file(path)
    if digest != item.get("sha256") or path.stat().st_size != item.get("size_bytes"):
        raise ValueError(f"dataset artifact hash/size changed: {relative_path}")
    return digest


def load_contract(dataset_root: Path, preflight_root: Path) -> FinalTrainingContract:
    dataset_root = checked_directory(dataset_root, label="dataset root")
    preflight_root = checked_directory(preflight_root, label="preflight root")
    if dataset_root.parent != preflight_root.parent:
        raise ValueError("dataset and preflight must belong to the same S66 wrapper root")

    materialization = read_json_object(dataset_root / "materialization-manifest.json")
    quality = read_json_object(dataset_root / "quality-report.json")
    policy = read_json_object(dataset_root / "qlora-policy.json")
    semantic = read_json_object(preflight_root / "semantic-diversity-report.json")
    tokenization = read_json_object(preflight_root / "tokenization-report.json")

    verify_snapshot_content_hash(materialization, label="materialization manifest")
    verify_snapshot_content_hash(quality, label="dataset quality report")
    verify_snapshot_content_hash(policy, label="QLoRA policy")
    verify_snapshot_content_hash(tokenization, label="tokenizer preflight")

    if materialization.get("training_executed") is not False:
        raise ValueError("dataset materialization must precede all final training")
    if materialization.get("training_authorized") is not False:
        raise ValueError("dataset materialization must not self-authorize training")
    if materialization.get("split_counts") != {
        "TRAIN": EXPECTED_TRAIN_COUNT,
        "VALIDATION": EXPECTED_VALIDATION_COUNT,
        "INTERNAL_TEST": EXPECTED_INTERNAL_TEST_COUNT,
    }:
        raise ValueError("dataset split counts differ from the final S66 campaign")

    if quality.get("publishable") is not True:
        raise ValueError("dataset quality report is not publishable")
    if quality.get("total_examples") != EXPECTED_TOTAL_COUNT:
        raise ValueError("dataset quality report count changed")
    for key in ("semantic_input_unique_count", "semantic_conversation_unique_count"):
        if quality.get(key) != EXPECTED_TOTAL_COUNT:
            raise ValueError(f"dataset quality gate failed: {key}")
    if quality.get("minimum_unique_semantic_inputs_per_family_language") != 500:
        raise ValueError("family/language semantic diversity changed")
    if quality.get("maximum_unique_semantic_inputs_per_family_language") != 500:
        raise ValueError("family/language semantic diversity changed")
    if quality.get("leakage_issue_count") != 0:
        raise ValueError("dataset split leakage is present")

    if semantic.get("status") != "SEMANTIC_DIVERSITY_VERIFIED":
        raise ValueError("S66 semantic preflight is not green")
    if semantic.get("dataset_rows") != EXPECTED_TOTAL_COUNT:
        raise ValueError("S66 semantic preflight row count changed")
    if semantic.get("unique_model_inputs") != EXPECTED_TOTAL_COUNT:
        raise ValueError("S66 model-input uniqueness changed")
    if semantic.get("unique_semantic_conversations") != EXPECTED_TOTAL_COUNT:
        raise ValueError("S66 semantic-conversation uniqueness changed")
    if semantic.get("input_hashes_crossing_splits") != 0:
        raise ValueError("S66 input leakage is nonzero")
    if semantic.get("semantic_hashes_crossing_splits") != 0:
        raise ValueError("S66 semantic leakage is nonzero")
    if semantic.get("training_authorized") is not False:
        raise ValueError("S66 semantic preflight unexpectedly authorized training")
    if semantic.get("training_executed") is not False:
        raise ValueError("S66 semantic preflight unexpectedly executed training")

    if tokenization.get("status") != "TOKENIZATION_VERIFIED_NOT_AUTHORIZED":
        raise ValueError("S66 tokenizer preflight is not green")
    if tokenization.get("repository_head") != "e5bb1132f43d7209f65711a2957d5f79796ebf99":
        raise ValueError("S66 tokenizer preflight is not bound to C65")
    if tokenization.get("row_count") != EXPECTED_TOTAL_COUNT:
        raise ValueError("S66 tokenizer row count changed")
    for key in (
        "overflow_count",
        "prefix_failure_count",
        "native_tokenization_failure_count",
        "completion_mask_failure_count",
        "eos_missing_count",
        "eos_boundary_failure_count",
    ):
        if tokenization.get(key) != 0:
            raise ValueError(f"S66 tokenizer preflight is blocked: {key}")
    if tokenization.get("optimizer_steps") != EXPECTED_OPTIMIZER_STEPS:
        raise ValueError("S66 optimizer-step count changed")
    if tokenization.get("training_authorized") is not False:
        raise ValueError("S66 tokenizer preflight unexpectedly authorized training")
    if tokenization.get("training_executed") is not False:
        raise ValueError("S66 tokenizer preflight unexpectedly executed training")

    if policy.get("policy_id") != EXPECTED_POLICY_ID:
        raise ValueError("final QLoRA policy ID changed")
    if policy.get("base_model_repository") != EXPECTED_MODEL_REPOSITORY:
        raise ValueError("final base model changed")
    if policy.get("base_model_revision") != EXPECTED_MODEL_REVISION:
        raise ValueError("final base-model revision changed")
    if policy.get("tokenizer_repository") != EXPECTED_MODEL_REPOSITORY:
        raise ValueError("final tokenizer repository changed")
    if policy.get("tokenizer_revision") != EXPECTED_MODEL_REVISION:
        raise ValueError("final tokenizer revision changed")
    if policy.get("authorization_required_before_training") is not True:
        raise ValueError("final QLoRA policy lost the authorization gate")

    quantization = policy.get("quantization")
    lora = policy.get("lora")
    optimization = policy.get("optimization")
    checkpoints = policy.get("checkpoints")
    if quantization != {
        "load_in_4bit": True,
        "quantization_type": "nf4",
        "double_quantization": True,
        "compute_dtype": "bfloat16",
    }:
        raise ValueError("final quantization policy changed")
    if not isinstance(lora, dict) or (
        lora.get("rank"),
        lora.get("alpha"),
        lora.get("dropout"),
        lora.get("bias"),
        lora.get("use_rslora"),
    ) != (16, 32, 0.0, "none", False):
        raise ValueError("final LoRA policy changed")
    if lora.get("target_modules") != [
        "down_proj",
        "gate_proj",
        "k_proj",
        "o_proj",
        "q_proj",
        "up_proj",
        "v_proj",
    ]:
        raise ValueError("final LoRA target modules changed")
    if not isinstance(optimization, dict) or optimization != {
        "max_sequence_length": 1536,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 4,
        "learning_rate": 0.0001,
        "weight_decay": 0.01,
        "warmup_ratio": 0.03,
        "num_train_epochs": 1.0,
        "optimizer": "adamw_8bit",
        "scheduler": "linear",
        "precision": "bf16",
        "gradient_checkpointing": True,
        "gradient_clip_norm": 1.0,
        "logging_steps": 10,
    }:
        raise ValueError("final optimization policy changed")
    if not isinstance(checkpoints, dict) or checkpoints != {
        "save_steps": 1000,
        "evaluation_steps": 1000,
        "save_total_limit": 3,
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
    }:
        raise ValueError("final checkpoint policy changed")

    train_sha = _verify_bound_file(
        dataset_root,
        materialization,
        "sft/train.jsonl",
    )
    validation_sha = _verify_bound_file(
        dataset_root,
        materialization,
        "sft/validation.jsonl",
    )
    internal_sha = _verify_bound_file(
        dataset_root,
        materialization,
        "sft/internal-test.jsonl",
    )

    return FinalTrainingContract(
        dataset_root=dataset_root,
        preflight_root=preflight_root,
        materialization=materialization,
        quality=quality,
        policy=policy,
        semantic_preflight=semantic,
        tokenizer_preflight=tokenization,
        train_sha256=train_sha,
        validation_sha256=validation_sha,
        internal_test_sha256=internal_sha,
    )


def model_loading_kwargs(
    policy: dict[str, Any],
    dtype: object,
    quantization_config: object,
    cache_dir: Path,
) -> dict[str, object]:
    return {
        "model_name": policy["base_model_repository"],
        "revision": policy["base_model_revision"],
        "max_seq_length": policy["optimization"]["max_sequence_length"],
        "dtype": dtype,
        "load_in_4bit": True,
        "quantization_config": quantization_config,
        "trust_remote_code": False,
        "use_exact_model_name": True,
        "fast_inference": False,
        "local_files_only": True,
        "cache_dir": str(cache_dir),
    }


def sft_kwargs(policy: dict[str, Any], checkpoint_root: Path) -> dict[str, Any]:
    optimization = policy["optimization"]
    checkpoints = policy["checkpoints"]
    return {
        "output_dir": str(checkpoint_root),
        "max_length": optimization["max_sequence_length"],
        "num_train_epochs": optimization["num_train_epochs"],
        "per_device_train_batch_size": optimization["per_device_train_batch_size"],
        "per_device_eval_batch_size": 1,
        "gradient_accumulation_steps": optimization["gradient_accumulation_steps"],
        "gradient_checkpointing": optimization["gradient_checkpointing"],
        "learning_rate": optimization["learning_rate"],
        "weight_decay": optimization["weight_decay"],
        "warmup_ratio": optimization["warmup_ratio"],
        "optim": optimization["optimizer"],
        "lr_scheduler_type": optimization["scheduler"],
        "bf16": optimization["precision"] == "bf16",
        "fp16": optimization["precision"] == "fp16",
        "max_grad_norm": optimization["gradient_clip_norm"],
        "logging_steps": optimization["logging_steps"],
        "eval_strategy": "steps",
        "eval_steps": checkpoints["evaluation_steps"],
        "save_strategy": "steps",
        "save_steps": checkpoints["save_steps"],
        "save_total_limit": checkpoints["save_total_limit"],
        "load_best_model_at_end": checkpoints["load_best_model_at_end"],
        "metric_for_best_model": checkpoints["metric_for_best_model"],
        "greater_is_better": checkpoints["greater_is_better"],
        "seed": policy["seed"],
        "data_seed": policy["seed"],
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


def make_collator(deps: SimpleNamespace, pad_token_id: int) -> object:
    return strict_call(
        deps.DataCollator,
        {
            "pad_token_id": pad_token_id,
            "completion_only_loss": True,
            "padding_free": False,
            "pad_to_multiple_of": None,
            "return_tensors": "pt",
        },
    )


def _token_ids(value: object, *, label: str) -> list[int]:
    from collections.abc import Mapping

    if isinstance(value, Mapping):
        value = value.get("input_ids")
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value)
    ):
        raise ValueError(f"{label}: tokenizer did not return flat integer input_ids")
    return value


def _completion_features(
    messages: list[dict[str, str]],
    *,
    tokenizer: Any,
    max_length: int,
    label: str,
) -> dict[str, list[int]]:
    if len(messages) != 3 or [item.get("role") for item in messages] != [
        "system",
        "user",
        "assistant",
    ]:
        raise ValueError(f"{label}: expected one system/user/assistant conversation")
    if not all(isinstance(item.get("content"), str) and item["content"] for item in messages):
        raise ValueError(f"{label}: message content must be nonempty text")

    prompt = messages[:2]
    prompt_text = tokenizer.apply_chat_template(
        prompt,
        tokenize=False,
        add_generation_prompt=True,
    )
    full_text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    if not isinstance(prompt_text, str) or not isinstance(full_text, str):
        raise ValueError(f"{label}: chat template did not return text")
    if not full_text.startswith(prompt_text):
        raise ValueError(f"{label}: prompt text is not a prefix of the full conversation")
    completion_text = full_text[len(prompt_text) :]
    if not completion_text.startswith(messages[2]["content"]):
        raise ValueError(f"{label}: assistant completion changed under the chat template")

    eos_token = getattr(tokenizer, "eos_token", None)
    if not isinstance(eos_token, str) or not eos_token:
        raise ValueError(f"{label}: tokenizer EOS text is unavailable")
    template_tail = completion_text[len(messages[2]["content"]) :]
    if not template_tail.startswith(eos_token):
        raise ValueError(f"{label}: assistant completion is not followed by EOS")
    if template_tail[len(eos_token) :].strip():
        raise ValueError(f"{label}: non-whitespace template text follows EOS")

    options = {
        "add_special_tokens": False,
        "truncation": False,
        "padding": False,
    }
    prompt_ids = _token_ids(tokenizer(prompt_text, **options), label=f"{label}:prompt")
    full_ids = _token_ids(tokenizer(full_text, **options), label=f"{label}:full")
    native_ids = _token_ids(
        tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=False,
        ),
        label=f"{label}:native",
    )
    prefix_length = len(prompt_ids)
    if full_ids[:prefix_length] != prompt_ids:
        raise ValueError(f"{label}: prompt token IDs are not a prefix")
    if full_ids != native_ids:
        raise ValueError(f"{label}: native chat-template tokenization changed")
    if len(full_ids) > max_length:
        raise ValueError(f"{label}: sequence exceeds the frozen maximum length")
    suffix = full_ids[prefix_length:]
    if not suffix:
        raise ValueError(f"{label}: completion token sequence is empty")
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if not isinstance(eos_token_id, int) or eos_token_id not in suffix:
        raise ValueError(f"{label}: EOS token ID is absent from the completion")

    last_eos = len(suffix) - 1 - suffix[::-1].index(eos_token_id)
    post_eos_text = tokenizer.decode(
        suffix[last_eos + 1 :],
        skip_special_tokens=False,
    )
    if post_eos_text.strip():
        raise ValueError(f"{label}: non-whitespace tokens follow EOS")

    completion_mask = [0] * prefix_length + [1] * len(suffix)
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "completion_mask": completion_mask,
    }


def load_pretokenized_rows(
    path: Path,
    *,
    tokenizer: Any,
    max_length: int,
    expected_count: int,
    split: str,
) -> list[dict[str, list[int]]]:
    rows: list[dict[str, list[int]]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw in enumerate(source, start=1):
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{split}:{line_number}: SFT row must be an object")
            messages = value.get("messages")
            if not isinstance(messages, list):
                raise ValueError(f"{split}:{line_number}: messages are required")
            rows.append(
                _completion_features(
                    messages,
                    tokenizer=tokenizer,
                    max_length=max_length,
                    label=f"{split}:{line_number}",
                )
            )
            if line_number % 1000 == 0:
                print(f"prepared {split} {line_number}/{expected_count}", flush=True)
    if len(rows) != expected_count:
        raise ValueError(f"{split}: expected {expected_count} rows, found {len(rows)}")
    return rows


def verify_trainable_parameters(model: Any) -> int:
    trainable = 0
    for name, parameter in model.named_parameters():
        if parameter.requires_grad:
            if "lora_" not in name:
                raise ValueError(f"non-LoRA parameter is trainable: {name}")
            trainable += parameter.numel()
    if trainable <= 0:
        raise ValueError("no trainable LoRA parameters")
    return trainable


def verify_collator_labels(collator: Any, row: dict[str, list[int]]) -> None:
    batch = collator([row])
    labels = batch.get("labels") if isinstance(batch, dict) else getattr(batch, "labels", None)
    if labels is None:
        raise ValueError("completion-only collator did not produce labels")
    labels_list = labels.tolist() if hasattr(labels, "tolist") else labels
    if not isinstance(labels_list, list) or not labels_list:
        raise ValueError("completion-only collator labels are malformed")
    first = labels_list[0] if isinstance(labels_list[0], list) else labels_list
    prefix_length = row["completion_mask"].index(1)
    if any(value != -100 for value in first[:prefix_length]):
        raise ValueError("prompt tokens are not masked from the training loss")
    if not any(value != -100 for value in first[prefix_length:]):
        raise ValueError("assistant completion has no supervised labels")


def tokenizer_identity(deps: SimpleNamespace, policy: dict[str, Any]) -> Any:
    tokenizer_json = Path(
        deps.hf_hub_download(
            repo_id=EXPECTED_MODEL_REPOSITORY,
            filename="tokenizer.json",
            revision=EXPECTED_MODEL_REVISION,
            local_files_only=True,
        )
    )
    tokenizer_config = Path(
        deps.hf_hub_download(
            repo_id=EXPECTED_MODEL_REPOSITORY,
            filename="tokenizer_config.json",
            revision=EXPECTED_MODEL_REVISION,
            local_files_only=True,
        )
    )
    if sha256_file(tokenizer_json) != EXPECTED_TOKENIZER_JSON_SHA256:
        raise ValueError("cached tokenizer.json differs from the frozen S50 identity")
    tokenizer_config_payload = read_authenticated_json_object(
        tokenizer_config,
        expected_sha256=EXPECTED_TOKENIZER_CONFIG_SHA256,
        label="cached tokenizer_config.json",
    )
    if "auto_map" in tokenizer_config_payload:
        raise ValueError("custom remote tokenizer code is forbidden")
    chat_template = tokenizer_config_payload.get("chat_template")
    if not isinstance(chat_template, str) or not chat_template:
        raise ValueError("frozen tokenizer chat template is missing")
    if sha256_bytes(chat_template.encode("utf-8")) != EXPECTED_CHAT_TEMPLATE_SHA256:
        raise ValueError("frozen tokenizer chat template changed")

    tokenizer = deps.AutoTokenizer.from_pretrained(
        EXPECTED_MODEL_REPOSITORY,
        revision=EXPECTED_MODEL_REVISION,
        local_files_only=True,
        trust_remote_code=False,
    )
    if tokenizer.__class__.__name__ != "Qwen2Tokenizer":
        raise ValueError("unexpected tokenizer class")
    if tokenizer.eos_token_id != 151645 or tokenizer.pad_token_id != 151643:
        raise ValueError("tokenizer EOS/PAD identity changed")
    if tokenizer.get_chat_template() != chat_template:
        raise ValueError("runtime tokenizer chat template differs from frozen source")
    observed_revision = getattr(tokenizer, "_commit_hash", None)
    if observed_revision is not None and observed_revision != policy["tokenizer_revision"]:
        raise ValueError("runtime tokenizer revision differs from final policy")
    return tokenizer


def _safe_output_root(path: Path, *, resume: bool) -> Path:
    path = path.absolute()
    artifacts = ROOT / "environments/training/artifacts"
    if ROOT not in path.parents or artifacts not in path.parents:
        raise ValueError("training output must remain inside repository training artifacts")
    for parent in reversed(path.parents):
        if parent.is_symlink():
            raise ValueError("training output path must not cross a symbolic link")
    if path.is_symlink():
        raise ValueError("training output root must not be a symbolic link")
    if resume:
        if not path.is_dir():
            raise ValueError("resume requires the existing original training output root")
    else:
        if path.exists():
            raise ValueError("new training output root must not already exist")
        path.mkdir(parents=True)
    return path


def verified_resume_checkpoint(
    checkpoint: Path | None,
    *,
    output_root: Path,
) -> Path | None:
    if checkpoint is None:
        return None
    checkpoint = checkpoint.absolute()
    checkpoint_root = output_root / "checkpoints"
    if checkpoint.parent != checkpoint_root:
        raise ValueError("resume checkpoint must belong to this training run")
    match = _CHECKPOINT_PATTERN.fullmatch(checkpoint.name)
    if match is None:
        raise ValueError("resume checkpoint must use checkpoint-N")
    step = int(match.group(1))
    if step <= 0 or step >= EXPECTED_OPTIMIZER_STEPS:
        raise ValueError("resume checkpoint step is outside the final training range")
    required = (
        "trainer_state.json",
        "adapter_config.json",
        "adapter_model.safetensors",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    )
    if not checkpoint.is_dir() or checkpoint.is_symlink():
        raise ValueError("resume checkpoint must be a regular directory")
    missing = [name for name in required if not (checkpoint / name).is_file()]
    if missing:
        raise ValueError(f"resume checkpoint is incomplete: {', '.join(missing)}")
    for forbidden in ("adapter_model.bin", "pytorch_model.bin"):
        if (checkpoint / forbidden).exists():
            raise ValueError(f"unsafe checkpoint serialization present: {forbidden}")
    return checkpoint


def directory_inventory(
    root: Path,
    *,
    maximum_bytes: int = 8_000_000_000,
) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("training artifact contains a symbolic link")
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if total > maximum_bytes:
            raise ValueError("training artifact inventory exceeds the safety limit")
        inventory.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": size,
                "sha256": sha256_file(path),
            }
        )
    return inventory


def directory_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError("training artifact contains a symbolic link")
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def checkpoint_inventory(root: Path) -> list[dict[str, object]]:
    checkpoint_root = root / "checkpoints"
    if not checkpoint_root.is_dir():
        return []
    values = []
    for path in sorted(checkpoint_root.iterdir(), key=lambda item: item.name):
        match = _CHECKPOINT_PATTERN.fullmatch(path.name)
        if match is None or not path.is_dir():
            continue
        values.append(
            {
                "step": int(match.group(1)),
                "content_sha256": directory_digest(path),
                "files": directory_inventory(path),
            }
        )
    return values


def write_progress(
    path: Path,
    *,
    global_step: int,
    max_steps: int,
    epoch: float | None,
    training_call_attempted: bool,
    logs: dict[str, object] | None = None,
) -> None:
    payload = {
        "runtime_id": RUNTIME_ID,
        "updated_at": datetime.now(UTC).isoformat(),
        "global_step": global_step,
        "max_steps": max_steps,
        "epoch": epoch,
        "training_call_attempted": training_call_attempted,
        "training_executed": global_step > 0,
        "logs": logs or {},
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical_json(payload), encoding="utf-8")
    os.replace(temporary, path)


def progress_callback(callback_base: type, progress_path: Path):
    class FinalTrainingProgress(callback_base):
        def on_log(self, args, state, control, logs=None, **kwargs):
            write_progress(
                progress_path,
                global_step=int(getattr(state, "global_step", 0)),
                max_steps=int(getattr(state, "max_steps", 0)),
                epoch=getattr(state, "epoch", None),
                training_call_attempted=True,
                logs=logs,
            )
            return control

        def on_save(self, args, state, control, **kwargs):
            write_progress(
                progress_path,
                global_step=int(getattr(state, "global_step", 0)),
                max_steps=int(getattr(state, "max_steps", 0)),
                epoch=getattr(state, "epoch", None),
                training_call_attempted=True,
                logs={"checkpoint_saved": True},
            )
            return control

    return FinalTrainingProgress()


def _attempt_path(output_root: Path) -> Path:
    attempts = output_root / "attempts"
    attempts.mkdir(exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = attempts / f"attempt-{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = attempts / f"attempt-{timestamp}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def perform_training(
    contract: FinalTrainingContract,
    deps: SimpleNamespace,
    output_root: Path,
    *,
    resume_checkpoint: Path | None,
    approvals: dict[str, object],
) -> dict[str, object]:
    torch = deps.torch
    policy = contract.policy

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("final thesis training requires exactly one visible CUDA GPU")
    if not torch.cuda.is_bf16_supported():
        raise ValueError("final thesis training requires BF16 support")
    if os.environ.get("WORLD_SIZE", "1") != "1":
        raise ValueError("distributed training is not authorized")

    tokenizer = tokenizer_identity(deps, policy)
    max_length = policy["optimization"]["max_sequence_length"]

    train_rows = load_pretokenized_rows(
        contract.dataset_root / "sft/train.jsonl",
        tokenizer=tokenizer,
        max_length=max_length,
        expected_count=EXPECTED_TRAIN_COUNT,
        split="TRAIN",
    )
    validation_rows = load_pretokenized_rows(
        contract.dataset_root / "sft/validation.jsonl",
        tokenizer=tokenizer,
        max_length=max_length,
        expected_count=EXPECTED_VALIDATION_COUNT,
        split="VALIDATION",
    )

    collator = make_collator(deps, tokenizer.pad_token_id)
    train_sample_indices = (0, len(train_rows) // 2, len(train_rows) - 1)
    validation_sample_indices = (0, len(validation_rows) // 2, len(validation_rows) - 1)
    expected_train_samples = {index: train_rows[index] for index in train_sample_indices}
    expected_validation_samples = {
        index: validation_rows[index] for index in validation_sample_indices
    }
    for row in (*expected_train_samples.values(), *expected_validation_samples.values()):
        verify_collator_labels(collator, row)

    train_dataset = deps.Dataset.from_list(train_rows)
    validation_dataset = deps.Dataset.from_list(validation_rows)
    del train_rows
    del validation_rows

    quantization = policy["quantization"]
    dtype = torch.bfloat16
    quantization_config = strict_call(
        deps.BitsAndBytesConfig,
        {
            "load_in_4bit": True,
            "bnb_4bit_quant_type": quantization["quantization_type"],
            "bnb_4bit_compute_dtype": dtype,
            "bnb_4bit_use_double_quant": quantization["double_quantization"],
        },
    )

    cache = Path(
        os.environ.get(
            "HF_HUB_CACHE",
            str(Path.home() / ".cache/huggingface/hub"),
        )
    )
    torch.manual_seed(policy["seed"])
    torch.cuda.manual_seed_all(policy["seed"])
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    started_at = datetime.now(UTC)
    started_clock = time.monotonic()

    model, loaded_tokenizer = strict_call(
        deps.FastLanguageModel.from_pretrained,
        model_loading_kwargs(policy, dtype, quantization_config, cache),
    )
    observed_revision = getattr(getattr(model, "config", None), "_commit_hash", None)
    if observed_revision != EXPECTED_MODEL_REVISION:
        raise ValueError(
            f"loaded base model revision differs from the final policy: {observed_revision}"
        )
    if getattr(model, "is_loaded_in_4bit", False) is not True:
        raise ValueError("base model did not attest four-bit loading")
    observed_quantization = getattr(model.config, "quantization_config", None)
    if hasattr(observed_quantization, "to_dict"):
        observed_quantization = observed_quantization.to_dict()
    if not isinstance(observed_quantization, dict):
        raise ValueError("loaded model did not expose quantization evidence")
    for key, expected in {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
    }.items():
        if observed_quantization.get(key) != expected:
            raise ValueError("loaded model quantization differs from the final policy")

    loaded_revision = getattr(loaded_tokenizer, "_commit_hash", None)
    if loaded_revision is not None and loaded_revision != EXPECTED_MODEL_REVISION:
        raise ValueError("model loader returned a tokenizer from a different revision")

    lora = policy["lora"]
    model = deps.FastLanguageModel.get_peft_model(
        model,
        r=lora["rank"],
        target_modules=lora["target_modules"],
        lora_alpha=lora["alpha"],
        lora_dropout=lora["dropout"],
        bias=lora["bias"],
        use_gradient_checkpointing="unsloth",
        random_state=policy["seed"],
        use_rslora=lora["use_rslora"],
    )
    trainable_parameters = verify_trainable_parameters(model)
    model.config.use_cache = False
    model.config.pad_token_id = tokenizer.pad_token_id

    checkpoint_root = output_root / "checkpoints"
    checkpoint_root.mkdir(exist_ok=True)
    args = strict_call(deps.SFTConfig, sft_kwargs(policy, checkpoint_root))
    progress_path = output_root / "progress.json"
    callback = progress_callback(deps.TrainerCallback, progress_path)
    trainer = strict_call(
        deps.SFTTrainer,
        {
            "model": model,
            "args": args,
            "train_dataset": train_dataset,
            "eval_dataset": validation_dataset,
            "processing_class": tokenizer,
            "data_collator": collator,
            "callbacks": [callback],
        },
    )

    if len(trainer.train_dataset) != EXPECTED_TRAIN_COUNT:
        raise ValueError("trainer changed the training dataset cardinality")
    if len(trainer.eval_dataset) != EXPECTED_VALIDATION_COUNT:
        raise ValueError("trainer changed the validation dataset cardinality")
    for index, expected in expected_train_samples.items():
        if trainer.train_dataset[index] != expected:
            raise ValueError("trainer changed a verified training row")
    for index, expected in expected_validation_samples.items():
        if trainer.eval_dataset[index] != expected:
            raise ValueError("trainer changed a verified validation row")
    if getattr(trainer.args, "completion_only_loss", None) is not True:
        raise ValueError("trainer lost completion-only supervision")
    if getattr(trainer.args, "remove_unused_columns", None) is not False:
        raise ValueError("trainer may prune the completion-mask column")

    write_progress(
        progress_path,
        global_step=0,
        max_steps=EXPECTED_OPTIMIZER_STEPS,
        epoch=None,
        training_call_attempted=True,
        logs={"resume_checkpoint": None if resume_checkpoint is None else str(resume_checkpoint)},
    )

    try:
        trainer.train(
            resume_from_checkpoint=(None if resume_checkpoint is None else str(resume_checkpoint))
        )
    finally:
        write_progress(
            progress_path,
            global_step=int(getattr(trainer.state, "global_step", 0)),
            max_steps=int(getattr(trainer.state, "max_steps", EXPECTED_OPTIMIZER_STEPS)),
            epoch=getattr(trainer.state, "epoch", None),
            training_call_attempted=True,
            logs={"training_call_returned": True},
        )

    torch.cuda.synchronize()
    global_step = int(trainer.state.global_step)
    if global_step != EXPECTED_OPTIMIZER_STEPS:
        raise ValueError(
            f"final trainer completed {global_step} optimizer steps; "
            f"expected {EXPECTED_OPTIMIZER_STEPS}"
        )

    best_checkpoint = getattr(trainer.state, "best_model_checkpoint", None)
    best_metric = getattr(trainer.state, "best_metric", None)
    if not isinstance(best_checkpoint, str) or not best_checkpoint:
        raise ValueError("load_best_model_at_end did not record a best checkpoint")
    if isinstance(best_metric, bool) or not isinstance(best_metric, (int, float)):
        raise ValueError("trainer did not record a numeric best eval metric")

    adapter_root = output_root / "adapter-best"
    if adapter_root.exists():
        raise ValueError("final adapter directory already exists")
    adapter_root.mkdir()
    model.save_pretrained(str(adapter_root), safe_serialization=True)
    tokenizer.save_pretrained(str(adapter_root))

    required_adapter = (
        adapter_root / "adapter_config.json",
        adapter_root / "adapter_model.safetensors",
    )
    if not all(path.is_file() for path in required_adapter):
        raise ValueError("final adapter export lacks required safetensors files")
    for forbidden in ("adapter_model.bin", "pytorch_model.bin"):
        if (adapter_root / forbidden).exists():
            raise ValueError(f"unsafe final adapter serialization present: {forbidden}")

    adapter_inventory = directory_inventory(adapter_root)
    adapter_sha256 = directory_digest(adapter_root)
    completed_at = datetime.now(UTC)
    peak_reserved = round(torch.cuda.max_memory_reserved() / (1024 * 1024))
    peak_allocated = round(torch.cuda.max_memory_allocated() / (1024 * 1024))

    metrics = []
    for item in trainer.state.log_history:
        if not isinstance(item, dict):
            continue
        selected = {
            key: value
            for key, value in item.items()
            if key in {"step", "epoch", "loss", "eval_loss", "learning_rate", "grad_norm"}
            and type(value) in (int, float)
            and math.isfinite(value)
        }
        if selected:
            metrics.append(selected)

    report = {
        "schema_version": 1,
        "runtime_id": RUNTIME_ID,
        "status": "FINAL_QLORA_TRAINING_SUCCEEDED",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round(time.monotonic() - started_clock, 2),
        "repository_head_at_runtime": os.environ.get("ORCHESTWIN_FINAL_QLORA_REPOSITORY_HEAD"),
        "approvals": approvals,
        "dataset": {
            "materialization_content_hash": contract.materialization["content_hash"],
            "quality_content_hash": contract.quality["content_hash"],
            "train_sha256": contract.train_sha256,
            "validation_sha256": contract.validation_sha256,
            "internal_test_sha256": contract.internal_test_sha256,
            "train_count": EXPECTED_TRAIN_COUNT,
            "validation_count": EXPECTED_VALIDATION_COUNT,
            "internal_test_count": EXPECTED_INTERNAL_TEST_COUNT,
        },
        "preflight": {
            "semantic_content_hash": contract.semantic_preflight["content_hash"],
            "tokenizer_content_hash": contract.tokenizer_preflight["content_hash"],
        },
        "policy_content_hash": policy["content_hash"],
        "base_model_repository": EXPECTED_MODEL_REPOSITORY,
        "base_model_revision": EXPECTED_MODEL_REVISION,
        "global_step": global_step,
        "trainable_lora_parameters": trainable_parameters,
        "best_model_checkpoint": best_checkpoint,
        "best_eval_loss": float(best_metric),
        "peak_gpu_memory_reserved_mb": peak_reserved,
        "peak_gpu_memory_allocated_mb": peak_allocated,
        "metrics": metrics,
        "checkpoints": checkpoint_inventory(output_root),
        "adapter_relative_path": "adapter-best",
        "adapter_inventory": adapter_inventory,
        "adapter_sha256": adapter_sha256,
        "training_call_attempted": True,
        "training_executed": True,
        "adapter_exported": True,
        "adapter_reload_verified": False,
        "quality_improvement_measured": False,
        "real_user_behavior_validated": False,
        "model_selected_for_training": True,
        "redistribution_authorized": False,
        "methodological_notice": (
            "The adapter was trained on synthetic User Twin evaluator design hypotheses. "
            "A successful optimization run does not establish authentic user behavior, "
            "empirical user validation, or quality improvement over the base model."
        ),
    }
    report["content_hash"] = snapshot_content_hash(report)
    return report


def write_report(path: Path, report: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(canonical_json(report), encoding="utf-8")
    os.replace(temporary, path)


def failure_report(
    *,
    error: BaseException,
    approvals: dict[str, object] | None,
    output_root: Path | None,
) -> dict[str, object]:
    progress: dict[str, Any] = {}
    if output_root is not None:
        progress_path = output_root / "progress.json"
        if progress_path.is_file():
            try:
                progress = read_json_object(progress_path)
            except (OSError, ValueError, TypeError):
                progress = {}
    report = {
        "schema_version": 1,
        "runtime_id": RUNTIME_ID,
        "status": "FINAL_QLORA_TRAINING_FAILED",
        "completed_at": datetime.now(UTC).isoformat(),
        "approvals": approvals,
        "failure_kind": type(error).__name__,
        "failure_message": " ".join(str(error).split())[:2000],
        "progress": progress,
        "training_call_attempted": bool(progress.get("training_call_attempted")),
        "training_executed": bool(progress.get("training_executed")),
        "adapter_exported": False,
        "adapter_reload_verified": False,
        "quality_improvement_measured": False,
        "real_user_behavior_validated": False,
    }
    report["content_hash"] = snapshot_content_hash(report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    approvals = None
    output_root = None
    attempt = None
    try:
        approvals = authorize(args, dict(os.environ))
        contract = load_contract(args.dataset_root, args.preflight_root)
        resume = args.resume_checkpoint is not None
        output_root = _safe_output_root(args.output_root, resume=resume)
        resume_checkpoint = verified_resume_checkpoint(
            args.resume_checkpoint,
            output_root=output_root,
        )
        attempt = _attempt_path(output_root)
        (attempt / "authorization.json").write_text(
            canonical_json(
                {
                    "runtime_id": RUNTIME_ID,
                    "created_at": datetime.now(UTC).isoformat(),
                    "approvals": approvals,
                    "resume_checkpoint": (
                        None if resume_checkpoint is None else str(resume_checkpoint)
                    ),
                    "training_gate_observed": True,
                }
            ),
            encoding="utf-8",
        )

        deps = load_dependencies()
        report = perform_training(
            contract,
            deps,
            output_root,
            resume_checkpoint=resume_checkpoint,
            approvals=approvals,
        )
        write_report(attempt / "result.json", report)
        write_report(output_root / "final-result.json", report)
        print(output_root / "final-result.json")
        print("FINAL QLORA TRAINING: SUCCEEDED")
        return 0
    except KeyboardInterrupt as error:
        report = failure_report(
            error=error,
            approvals=approvals,
            output_root=output_root,
        )
        if attempt is not None:
            write_report(attempt / "result.json", report)
        print("final_qlora_training_interrupted", file=sys.stderr)
        return 24
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
        report = failure_report(
            error=error,
            approvals=approvals,
            output_root=output_root,
        )
        if attempt is not None:
            write_report(attempt / "result.json", report)
        print(
            f"final_qlora_training_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22


if __name__ == "__main__":
    raise SystemExit(main())
