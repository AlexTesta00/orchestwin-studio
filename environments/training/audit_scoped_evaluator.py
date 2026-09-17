#!/usr/bin/env python3
"""Verify scoped development token budgets and prepare an offline training cache."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path

from audit_complete_evaluator import MODEL, REVISION, measure
from complete_training_data import MAX_SEQUENCE, OUTPUT_RESERVE, prepare_cache
from prepare_complete_evaluator import checked_output, digest, save

CURRICULUM = "grounded-evaluator-scoped-interface-v4"


def audit(data, output, tokenizer, *, tokenizer_files=None, curriculum_id=CURRICULUM):
    manifest_path = data / "manifest.json"
    manifest_hash = digest(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    if (
        curriculum_id not in {CURRICULUM, "grounded-evaluator-balanced-scope-v5"}
        or (manifest["curriculum_id"] != curriculum_id)
        or set(manifest["files"])
        != {
            "train.jsonl",
            "validation.jsonl",
        }
    ):
        raise ValueError("scoped train/validation development corpus required")
    output = checked_output(output)
    report = dict(
        curriculum_id=curriculum_id,
        model=MODEL,
        revision=REVISION,
        dataset_manifest_sha256=manifest_hash,
        tokenizer_files=tokenizer_files,
        max_sequence=MAX_SEQUENCE,
        output_reserve=OUTPUT_RESERVE,
        truncation=False,
        completion_boundary_checked=True,
        eos_checked=True,
        model_weights_loaded=False,
        training_executed=False,
        final_test_files_opened=False,
        splits={},
    )
    for split in ("train", "validation"):
        report["splits"][split] = measure(
            tokenizer,
            data / f"{split}.jsonl",
            manifest["files"][f"{split}.jsonl"],
            max_sequence=MAX_SEQUENCE,
            output_reserve=OUTPUT_RESERVE,
            progress=output / "progress.json",
        )
    cache = prepare_cache(data, output / "cache", manifest_hash, tokenizer)
    for key in ("rows", "total_tokens", "completion_tokens", "max_tokens", "min_tokens"):
        if cache[key] != report["splits"]["train"][key]:
            raise ValueError("training cache differs from independent token audit")
    if digest(manifest_path) != manifest_hash:
        raise ValueError("manifest changed during scoped preflight")
    report["cache"] = cache
    sources = [
        Path(__file__),
        *[
            Path(__file__).with_name(name)
            for name in (
                "audit_complete_evaluator.py",
                "complete_training_data.py",
                "prepare_complete_evaluator.py",
            )
        ],
    ]
    (output / "operators").mkdir()
    for path in sources:
        (output / "operators" / path.name).write_bytes(path.read_bytes())
    report["operator_sha256"] = {p.name: digest(p) for p in sources}
    save(output / "tokenization.json", report)
    save(output / "progress.json", dict(stage="VERIFIED_NO_TRAINING", rows=cache["rows"]))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--curriculum",
        choices=(CURRICULUM, "grounded-evaluator-balanced-scope-v5"),
        default=CURRICULUM,
    )
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    from huggingface_hub import try_to_load_from_cache
    from transformers import AutoTokenizer

    files = {}
    for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
        path = try_to_load_from_cache(MODEL, name, revision=REVISION)
        if isinstance(path, str):
            files[name] = dict(path=path, sha256=digest(Path(path)))
    if not {"tokenizer.json", "tokenizer_config.json"} <= files.keys():
        raise ValueError("pinned tokenizer is not available in the offline cache")
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
    )
    report = audit(
        args.data, args.output, tokenizer, tokenizer_files=files, curriculum_id=args.curriculum
    )
    report["package_versions"] = {
        name: importlib.metadata.version(name) for name in ("transformers", "tokenizers")
    }
    save(args.output / "tokenization.json", report)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
