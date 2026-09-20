#!/usr/bin/env python3
"""Offline evaluator experiment over owned process pipes; no service or promotion.

One explicitly hashed adapter or pinned unadapted base, unchanged outputs and no retry.
The frozen S67 serving operator and its production selection remain independent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.models.final_evaluator_gateway import model_visible_messages  # noqa: E402
from orchestwin.models.strict_evaluator_json import (  # noqa: E402
    check_evaluator_schema,
    strict_json_object,
    validate_evaluator_value,
)
from orchestwin.models.structured_generation import (  # noqa: E402
    ModelRuntimeIdentity,
    StructuredGenerationRequest,
    StructuredJsonSchema,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash  # noqa: E402

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
PREFIX = "ORCHESTWIN_EVALUATOR_EVENT "


def save(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def emit(value):
    print(PREFIX + json.dumps(value), flush=True)


def hydrate(value, identity):
    request = StructuredGenerationRequest(
        **{
            **value,
            "request_id": UUID(value["request_id"]),
            "expected_identity": ModelRuntimeIdentity(**value["expected_identity"]),
            "output_schema": StructuredJsonSchema(**value["output_schema"]),
            "allowed_evidence_refs": tuple(value["allowed_evidence_refs"]),
        }
    )
    if request.expected_identity != identity or request.task_id != "user-twin-evaluation-v1":
        raise ValueError("candidate request identity or task mismatch")
    if request.temperature != 0 or not 1 <= request.max_output_tokens <= 2048:
        raise ValueError("candidate request decoding bounds")
    check_evaluator_schema(strict_json_object(request.output_schema.canonical_schema_json))
    return request


def verify_adapter(path, weights_hash, config_hash):
    files = {"adapter_model.safetensors": weights_hash, "adapter_config.json": config_hash}
    for name, expected in files.items():
        item = path / name
        if item.is_symlink() or hashlib.sha256(item.read_bytes()).hexdigest() != expected:
            raise ValueError("candidate adapter bytes differ")
    config = strict_json_object((path / "adapter_config.json").read_bytes())
    if config["base_model_name_or_path"] != MODEL or config.get("peft_type") != "LORA":
        raise ValueError("candidate adapter base or type differs")
    return files


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--adapter", type=Path)
    choice.add_argument("--base-only", action="store_true")
    parser.add_argument("--weights-sha256")
    parser.add_argument("--config-sha256")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decoding", choices=("prompted", "schema"), default="prompted")
    parser.add_argument("--max-requests", type=int, default=64)
    args = parser.parse_args(argv)
    supplied = (args.weights_sha256, args.config_sha256)
    if (args.base_only and any(supplied)) or (not args.base_only and not all(supplied)):
        parser.error("adapter mode requires both hashes; base-only mode forbids adapter hashes")
    if not 1 <= args.max_requests <= 256:
        raise ValueError("candidate request count must be between 1 and 256")
    return args


def inference_model(base, adapter, *, load_adapter, prepare_inference):
    if adapter is None:
        if getattr(base, "peft_config", None) or getattr(base, "_hf_peft_config_loaded", False):
            raise ValueError("unadapted baseline must not contain a loaded adapter")
        model = base
        model.requires_grad_(False)
    else:
        model = load_adapter(base, adapter, is_trainable=False, local_files_only=True)
    prepare_inference(model)
    if any(p.requires_grad for p in model.parameters()):
        raise ValueError("experiment model must be inference only")
    if adapter is not None and model.active_adapters != ["default"]:
        raise ValueError("candidate adapter not active for inference only")
    return model


def main():
    args = parse_arguments()
    adapter = args.adapter.absolute() if args.adapter else None
    output = args.output.absolute()
    if (
        ROOT in output.parents
        or output == ROOT
        or any(p.is_symlink() for p in (output, *output.parents))
    ):
        raise ValueError("use a new external experiment directory without links")
    hashes = verify_adapter(adapter, args.weights_sha256, args.config_sha256) if adapter else {}
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).read_bytes()
    (output / "operator.py").write_bytes(source)
    config = {
        "policy": "OFFLINE_EVALUATOR_CANDIDATE_V1",
        "base": MODEL,
        "revision": REVISION,
        "adapter_files": hashes,
        "base_only": args.base_only,
        "operator_sha256": hashlib.sha256(source).hexdigest(),
        "max_sequence": 6144,
        "max_generation_seconds": 180,
        "max_requests": args.max_requests,
        "decoding": args.decoding,
        "training": False,
        "promotion": False,
        "formal_case": False,
        "output_repair": False,
        "network": False,
    }
    save(output / "configuration.json", config)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", WANDB_DISABLED="true")
    os.chdir(ROOT / "environments/training")
    # isort: off
    from unsloth import FastLanguageModel
    import torch
    from peft import PeftModel

    # isort: on
    base, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL,
        revision=REVISION,
        max_seq_length=config["max_sequence"],
        dtype=torch.bfloat16,
        load_in_4bit=True,
        use_exact_model_name=True,
        trust_remote_code=False,
        local_files_only=True,
    )
    if base.config._commit_hash != REVISION or not base.is_loaded_in_4bit:
        raise ValueError("loaded candidate base identity differs")
    model = inference_model(
        base,
        adapter,
        load_adapter=PeftModel.from_pretrained,
        prepare_inference=FastLanguageModel.for_inference,
    )
    identity = ModelRuntimeIdentity(
        provider_id="unsloth-evaluator-experiment",
        runtime_id=str(uuid4()),
        base_model_repository=MODEL,
        base_model_revision=REVISION,
        tokenizer_revision=REVISION,
        configuration_sha256=snapshot_content_hash(config),
        adapter_id="experimental-" + args.weights_sha256[:16] if adapter else None,
        adapter_sha256=snapshot_content_hash(hashes) if adapter else None,
    )
    save(output / "identity.json", identity.to_snapshot())
    emit({"event": "READY", "identity": identity.to_snapshot()})
    from orchestwin.models.schema_decoding import build_schema_processor_factory

    factory = build_schema_processor_factory(tokenizer, torch, model.config.vocab_size)
    completed = 0
    for _ in range(config["max_requests"]):
        line = sys.stdin.buffer.readline(4_000_001)
        if not line:
            break
        request = hydrate(strict_json_object(line), identity)
        case = output / str(request.request_id)
        case.mkdir()
        save(case / "request.json", request.to_snapshot())
        messages = model_visible_messages(request)
        schema = strict_json_object(request.output_schema.canonical_schema_json)
        encoded = tokenizer.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
            return_dict=True,
        )
        encoded = {k: v.to(model.device) for k, v in encoded.items()}
        length = encoded["input_ids"].shape[-1]
        if length + request.max_output_tokens > config["max_sequence"]:
            raise ValueError("complete evaluator request exceeds context")
        processor = factory(schema, length) if args.decoding == "schema" else None
        started = time.monotonic()
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                do_sample=False,
                max_new_tokens=request.max_output_tokens,
                max_time=min(request.timeout_seconds, config["max_generation_seconds"]),
                logits_processor=[processor] if processor else [],
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        tokens = generated[0, length:]
        raw = tokenizer.decode(tokens, skip_special_tokens=True)
        valid = False
        try:
            validate_evaluator_value(strict_json_object(raw), schema)
            valid = True
        except (ValueError, TypeError):
            pass
        result = {
            "request_hash": request.content_hash,
            "identity": identity.to_snapshot(),
            "input_messages": messages,
            "raw_output": raw,
            "output_token_ids": tokens.tolist(),
            "input_tokens": length,
            "output_tokens": len(tokens),
            "latency_milliseconds": round((time.monotonic() - started) * 1000),
            "eos_finished": bool(len(tokens) and int(tokens[-1]) == tokenizer.eos_token_id),
            "schema_valid": valid,
            "schema_finished": processor.finish(generated) if processor else None,
        }
        save(case / "result.json", result)
        completed += 1
        emit(
            {
                "event": "RESULT",
                "request_id": str(request.request_id),
                "request_hash": request.content_hash,
            }
        )
    save(output / "stopped.json", {"completed_requests": completed, "training": False})
    emit({"event": "STOPPED", "completed_requests": completed})


if __name__ == "__main__":
    main()
