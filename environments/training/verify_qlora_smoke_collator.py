#!/usr/bin/env python3
"""Check the installed TRL collator on S50 token IDs without model loading or training."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.qlora_smoke_collation import (  # noqa: E402
    load_verified_smoke_inputs,
    run_collator_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, type=Path)
    parser.add_argument("--tokenized", required=True, type=Path)
    parser.add_argument("--source-evidence", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    try:
        data = load_verified_smoke_inputs(
            repository_root=ROOT,
            preparation_root=args.prepared,
            tokenization_root=args.tokenized,
            source_evidence_path=args.source_evidence,
        )
        # Match the actual smoke runtime: patch before TRL can import Transformers.
        # No model is instantiated; Unsloth initialization may inspect CUDA.
        importlib.import_module("unsloth")
        collator_class = importlib.import_module(
            "trl.trainer.sft_trainer"
        ).DataCollatorForLanguageModeling
        collator = collator_class(
            pad_token_id=data.tokenization["tokenizer"]["pad_token_id"],
            completion_only_loss=True,
            padding_free=False,
            pad_to_multiple_of=None,
            return_tensors="pt",
        )
        path = run_collator_preflight(
            data,
            collator,
            output_root=args.output_root,
            created_at=datetime.now(UTC),
        )
    except (ImportError, OSError, ValueError, RuntimeError, TypeError) as error:
        print(f"collator_preflight_failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 22
    print(path)
    print("qlora_smoke_collator: VERIFIED_NOT_AUTHORIZED (20 rows, 2 padding probes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
