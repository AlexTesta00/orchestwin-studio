#!/usr/bin/env python3
"""Prepare a verified proposer cache and train a guarded, unselected LoRA candidate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from complete_training_data import MODEL, REVISION
from proposer_training_data import MAX_SEQUENCE, prepare_cache
from run_complete_evaluator import train


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    for name in ("data", "output"):
        prepare.add_argument(f"--{name}", type=Path, required=True)
    prepare.add_argument("--manifest-sha256", required=True)
    run = commands.add_parser("train")
    for name in ("cache", "output", "policy", "guard-state"):
        run.add_argument(f"--{name}", type=Path, required=True)
    run.add_argument("--resume", type=Path)
    run.add_argument("--authorize-cloud-training", action="store_true")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.action == "prepare":
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            MODEL, revision=REVISION, local_files_only=True, trust_remote_code=False
        )
        print(json.dumps(prepare_cache(args.data, args.output, args.manifest_sha256, tokenizer)))
    else:
        train(
            args,
            max_sequence=MAX_SEQUENCE,
            additional_sources=("run_proposer.py", "proposer_training_data.py"),
        )


if __name__ == "__main__":
    main()
