#!/usr/bin/env python3
"""Export a new synthetic calibration candidate without training or publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.grounded_evaluator_curriculum import (  # noqa: E402
    CURRICULUM_ID,
    build_curriculum,
)


def export(
    output: Path, *, seed: int = 20260914, variants: int = 32, curriculum: str = "basic"
) -> dict:
    output = output.absolute()
    if ".." in output.parts or any(
        p.is_symlink() or p.is_junction() for p in (output, *output.parents)
    ):
        raise ValueError("calibration output cannot traverse links")
    allowed = ROOT / "environments/training/artifacts"
    if output == ROOT or (ROOT in output.parents and allowed not in output.parents):
        raise ValueError("calibration output must be outside source or inside training artifacts")
    curriculum_id = CURRICULUM_ID
    builder = build_curriculum
    if curriculum == "relational":
        from orchestwin.training.relational_evaluator_curriculum import (
            CURRICULUM_ID as relational_id,
        )
        from orchestwin.training.relational_evaluator_curriculum import (
            build_curriculum as build_relational,
        )

        curriculum_id, builder = relational_id, build_relational
    elif curriculum != "basic":
        raise ValueError("unknown calibration curriculum")
    rows = builder(seed=seed, variants=variants)
    output.mkdir(parents=True, exist_ok=False)
    counts = Counter(row["split"] for row in rows)
    files = {}
    for split in ("train", "validation", "test"):
        raw = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
            if row["split"] == split
        ).encode()
        filename = split + ".jsonl"
        (output / filename).write_bytes(raw)
        files[filename] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "rows": counts[split],
        }
    sources = [Path(__file__), ROOT / "src/orchestwin/training/grounded_evaluator_curriculum.py"]
    if curriculum == "relational":
        sources.append(ROOT / "src/orchestwin/training/relational_evaluator_curriculum.py")
    source_directory = output / "operators"
    source_directory.mkdir()
    for source in sources:
        (source_directory / source.name).write_bytes(source.read_bytes())
    report = {
        "curriculum_id": curriculum_id,
        "seed": seed,
        "variants_per_family": variants,
        "files": files,
        "source_sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        },
        "labels": dict(Counter(r["judgement"] for r in rows)),
        "scope": "SYNTHETIC_NARROW_CONTRACT_CALIBRATION",
        "formal_case_used": False,
        "human_label_review_performed": False,
        "empirical_validation": False,
        "production_schema_validated_rows": len(rows),
        "domain_validated_rows": len(rows),
        "split_policy": "Whole counterfactual groups and translations; test/validation task phrases absent from train across all families.",
        "structure_holdout": curriculum == "relational",
        "limitations": [
            "Closed HTML fixture grammar, not a general accessibility oracle.",
            "Template-generated targets are not representative real-user labels.",
            "Independent held-out inference is required before candidate selection.",
            "Historical S66/S67 and formal case evidence are unchanged.",
        ],
        "training_executed": False,
        "model_selected": False,
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--variants", type=int, default=32)
    parser.add_argument("--curriculum", choices=("basic", "relational"), default="basic")
    args = parser.parse_args()
    report = export(args.output, seed=args.seed, variants=args.variants, curriculum=args.curriculum)
    print(json.dumps({"output": str(args.output), "files": report["files"]}, indent=2))


if __name__ == "__main__":
    main()
