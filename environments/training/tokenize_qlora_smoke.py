#!/usr/bin/env python3
"""Tokenize S49 smoke fixtures from verified local metadata; never train or download."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from orchestwin.training.qlora_smoke_tokenization import (  # noqa: E402
    SmokeTokenizationError,
    load_smoke_preparation,
    tokenize_prepared_smoke,
)


def _load_local_tokenizer(directory: Path) -> Any:
    # A separate CPU-only tokenizer process; no Unsloth, model, or trainer is imported.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["USE_TORCH"] = "0"
    os.environ["USE_TF"] = "0"
    os.environ["USE_FLAX"] = "0"
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(
        str(directory),
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--created-at")
    args = parser.parse_args()
    try:
        created_at = (
            datetime.now(UTC)
            if args.created_at is None
            else datetime.fromisoformat(
                args.created_at,
            )
        )
        # This check reads no optional dependencies and does not regenerate the lock.
        metadata = load_smoke_preparation(_REPOSITORY_ROOT, args.prepared).preparation
        lock = _REPOSITORY_ROOT / "environments/training/uv.lock"
        if lock.is_symlink() or not lock.is_file():
            raise SmokeTokenizationError("training lock must be a regular file")
        if hashlib.sha256(lock.read_bytes()).hexdigest() != metadata["package_lock_sha256"]:
            raise SmokeTokenizationError("current training lock differs from S49 preparation")
        path = tokenize_prepared_smoke(
            repository_root=_REPOSITORY_ROOT,
            preparation_root=args.prepared,
            source_evidence_path=args.source_evidence,
            output_root=args.output_root,
            created_at=created_at,
            tokenizer_loader=_load_local_tokenizer,
        )
        report = json.loads(path.read_text(encoding="utf-8"))
        for item in report["observations"]:
            print(
                f"{item['sample_id']}: prompt={item['prompt_tokens']} "
                f"completion={item['completion_tokens']} total={item['total_tokens']} "
                f"issues={item['issues']}"
            )
        print(path)
        print("qlora_smoke_tokenization:", report["status"])
        return 0 if report["status"] == "TOKENIZATION_VERIFIED_NOT_AUTHORIZED" else 22
    except ModuleNotFoundError as error:
        print(
            f"Missing tokenizer dependency: {error.name}. Use the locked training environment.",
            file=sys.stderr,
        )
        return 20
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
        print(f"Tokenizer preflight failed: {error}", file=sys.stderr)
        return 22


if __name__ == "__main__":
    raise SystemExit(main())
