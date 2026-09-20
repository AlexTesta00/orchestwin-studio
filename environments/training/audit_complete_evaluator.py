#!/usr/bin/env python3
"""Stream exact pinned-tokenizer checks and a local throughput-based planning estimate.

No model weights, optimizer, GPU inference, gradient updates or output truncation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from prepare_complete_evaluator import checked_output, digest, save

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"


def check_tokens(tokenizer, messages, *, max_sequence, output_reserve):
    if [message["role"] for message in messages] != ["system", "user", "assistant"]:
        raise ValueError("a complete native three-message example is required")
    prefix = tokenizer.apply_chat_template(
        messages[:2], tokenize=True, add_generation_prompt=True, return_dict=False
    )
    complete = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False, return_dict=False
    )
    if complete[: len(prefix)] != prefix or len(complete) <= len(prefix):
        raise ValueError("completion boundary differs from the inference prompt")
    if tokenizer.eos_token_id not in complete[len(prefix) :]:
        raise ValueError("completion EOS missing")
    if len(complete) > max_sequence or len(prefix) + output_reserve > max_sequence:
        raise ValueError("complete example or future generation reserve exceeds context")
    if len(complete) - len(prefix) > output_reserve:
        raise ValueError("target completion exceeds the future output budget")
    return len(prefix), len(complete) - len(prefix)


def measure(tokenizer, path, expected, *, max_sequence, output_reserve, progress=None):
    if digest(path) != expected["sha256"]:
        raise ValueError("dataset digest changed before tokenization")
    lengths, prompts, completions = [], [], []
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            row = json.loads(line)
            try:
                prompt, completion = check_tokens(
                    tokenizer,
                    row["messages"],
                    max_sequence=max_sequence,
                    output_reserve=output_reserve,
                )
            except ValueError as error:
                raise ValueError(f"{path.name} row {number}: {error}") from error
            prompts.append(prompt)
            completions.append(completion)
            lengths.append(prompt + completion)
            if progress and number % 2000 == 0:
                value = dict(
                    stage="TOKENIZING",
                    split=path.stem,
                    completed_rows=number,
                    total_rows=expected["rows"],
                )
                temporary = progress.with_suffix(".tmp")
                save(temporary, value)
                temporary.replace(progress)
                print(json.dumps(value), flush=True)
    if len(lengths) != expected["rows"] or digest(path) != expected["sha256"]:
        raise ValueError("dataset count or bytes changed during tokenization")
    ordered = sorted(lengths)
    return dict(
        rows=len(lengths),
        total_tokens=sum(lengths),
        prompt_tokens=sum(prompts),
        completion_tokens=sum(completions),
        min_tokens=min(lengths),
        max_tokens=max(lengths),
        mean_tokens=sum(lengths) / len(lengths),
        p95_tokens=ordered[int((len(ordered) - 1) * 0.95)],
        p99_tokens=ordered[int((len(ordered) - 1) * 0.99)],
        max_prompt_tokens=max(prompts),
        max_completion_tokens=max(completions),
    )


def estimate_hours(current, reference, training_result):
    # Both recorded timings are retained because the previous host clock was unstable.
    seconds = [training_result["seconds"], training_result["metrics"]["train_runtime"]]
    ratio = current["total_tokens"] / reference["total_tokens"]
    return dict(
        method="PRIOR_LOCAL_TRAINING_TIME_SCALED_BY_COMPLETE_SEQUENCE_TOKENS",
        reference_rows=reference["rows"],
        reference_tokens=reference["total_tokens"],
        reference_reported_seconds=seconds,
        current_rows=current["rows"],
        token_ratio=ratio,
        nominal_one_epoch_hours=[min(seconds) * ratio / 3600, max(seconds) * ratio / 3600],
        includes_validation_or_checkpoint_overhead=False,
        measured_new_training_throughput=False,
        limitation="Planning estimate only: longer sequences, full-completion supervision, memory pressure, sampler policy and checkpointing can change throughput. Measure a pilot before committing to the full run; hours do not predict quality.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-sequence", type=int, default=6144)
    parser.add_argument("--output-reserve", type=int, default=2048)
    parser.add_argument("--reference-data", type=Path)
    parser.add_argument("--reference-result", type=Path)
    args = parser.parse_args()
    if not 2048 <= args.max_sequence <= 8192 or not 256 <= args.output_reserve < args.max_sequence:
        raise ValueError("unsupported complete-interface token budgets")
    if bool(args.reference_data) != bool(args.reference_result):
        raise ValueError("reference data and training result must be supplied together")
    if args.reference_data:
        reference_protocol = json.loads(
            (args.reference_result.parent / "protocol.json").read_bytes()
        )
        if reference_protocol["dataset_manifest_sha256"] != digest(
            args.reference_data / "manifest.json"
        ):
            raise ValueError("reference timing belongs to a different dataset")
        if (
            reference_protocol["base_model"] != MODEL
            or reference_protocol["base_revision"] != REVISION
        ):
            raise ValueError("reference timing belongs to a different model")
    manifest = json.loads((args.data / "manifest.json").read_bytes())
    if manifest["curriculum_id"] != "grounded-evaluator-complete-interface-v3":
        raise ValueError("unexpected complete-interface curriculum")
    output = checked_output(args.output)
    (output / "operator.py").write_bytes(Path(__file__).read_bytes())
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
    )
    report = dict(
        model=MODEL,
        revision=REVISION,
        max_sequence=args.max_sequence,
        output_reserve=args.output_reserve,
        dataset_manifest_sha256=digest(args.data / "manifest.json"),
        operator_sha256=digest(Path(__file__)),
        truncation=False,
        completion_boundary_checked=True,
        eos_checked=True,
        model_weights_loaded=False,
        training_executed=False,
        final_cases_inferred=False,
        splits={},
    )
    for split in ("train", "validation", "test"):
        report["splits"][split] = measure(
            tokenizer,
            args.data / f"{split}.jsonl",
            manifest["files"][f"{split}.jsonl"],
            max_sequence=args.max_sequence,
            output_reserve=args.output_reserve,
            progress=output / "progress.json",
        )
    if args.reference_data:
        reference_manifest = json.loads((args.reference_data / "manifest.json").read_bytes())
        reference = measure(
            tokenizer,
            args.reference_data / "train.jsonl",
            reference_manifest["files"]["train.jsonl"],
            max_sequence=args.max_sequence,
            output_reserve=args.output_reserve,
        )
        report["reference_tokenization"] = reference
        report["reference_training_result_sha256"] = digest(args.reference_result)
        report["estimate"] = estimate_hours(
            report["splits"]["train"], reference, json.loads(args.reference_result.read_bytes())
        )
    save(output / "tokenization.json", report)
    save(
        output / "progress.json",
        dict(stage="TOKENIZATION_VERIFIED", splits=report["splits"], training=False),
    )
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
