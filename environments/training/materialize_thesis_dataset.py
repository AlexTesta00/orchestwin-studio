#!/usr/bin/env python3
"""Materialize the frozen 24k-example final thesis User Twin evaluator curriculum."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from orchestwin.projects.requirements_primitives import canonical_json  # noqa: E402
from orchestwin.training.splitting import DatasetSplit  # noqa: E402
from orchestwin.training.thesis_training_campaign import (  # noqa: E402
    BASE_MODEL_REPOSITORY,
    BASE_MODEL_REVISION,
    CAMPAIGN_POLICY_ID,
    benchmark_aligned_training_projection,
    build_campaign_dataset,
    campaign_snapshot,
    final_qlora_policy_snapshot,
    selection_decision_snapshot,
    validate_campaign_dataset,
)

TRAINING_GATE = "ORCHESTWIN_FINAL_QLORA_ALLOW_TRAINING"


def _safe_new_root(path: Path) -> Path:
    root = Path(os.path.abspath(path))
    for component in (*reversed(root.parents), root):
        if component.is_symlink():
            raise ValueError("dataset output path must not contain symbolic links")
    if root.exists():
        raise ValueError("dataset output root must be new")
    root.mkdir(parents=True)
    return root


def _sft_row(example) -> dict[str, object]:
    snapshot = example.to_snapshot()
    projection = benchmark_aligned_training_projection(example)
    return {
        "example_id": snapshot["example_id"],
        "project_id": snapshot["project_id"],
        "scenario_family_id": snapshot["scenario_family_id"],
        "language": snapshot["language"],
        "example_content_hash": snapshot["content_hash"],
        "projection_content_hash": projection["projection_content_hash"],
        "messages": [
            {
                "role": "system",
                "content": projection["system_instruction"],
            },
            {
                "role": "user",
                "content": canonical_json(projection["user_payload"]),
            },
            {
                "role": "assistant",
                "content": canonical_json(projection["target"]),
            },
        ],
    }


def _write_jsonl(path: Path, examples) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for example in examples:
            handle.write(canonical_json(_sft_row(example)))
            handle.write("\n")
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    if os.environ.get(TRAINING_GATE) == "1":
        print(
            "dataset materialization refuses the final training authorization gate", file=sys.stderr
        )
        return 22

    try:
        destination = _safe_new_root(args.output_root)
        examples, split = build_campaign_dataset()
        quality = validate_campaign_dataset(examples, split)

        snapshots = destination / "snapshots"
        sft = destination / "sft"
        snapshots.mkdir()
        sft.mkdir()

        # Full immutable source examples, useful for audit/reconstruction.
        with (snapshots / "all-examples.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for example in examples:
                handle.write(canonical_json(example.to_snapshot()))
                handle.write("\n")

        split_counts = {}
        for split_key, filename in (
            (DatasetSplit.TRAIN, "train.jsonl"),
            (DatasetSplit.VALIDATION, "validation.jsonl"),
            (DatasetSplit.INTERNAL_TEST, "internal-test.jsonl"),
        ):
            rows = split.examples_for(split_key)
            split_counts[split_key.value] = _write_jsonl(sft / filename, rows)

        (destination / "selection-decision.json").write_text(
            canonical_json(selection_decision_snapshot()),
            encoding="utf-8",
        )
        (destination / "campaign.json").write_text(
            canonical_json(campaign_snapshot()),
            encoding="utf-8",
        )
        (destination / "qlora-policy.json").write_text(
            canonical_json(final_qlora_policy_snapshot()),
            encoding="utf-8",
        )
        (destination / "quality-report.json").write_text(
            canonical_json(quality),
            encoding="utf-8",
        )
        (destination / "split-manifest.json").write_text(
            canonical_json(split.to_snapshot()),
            encoding="utf-8",
        )

        import hashlib

        inventory = []
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                inventory.append(
                    {
                        "path": path.relative_to(destination).as_posix(),
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
                )
        manifest = {
            "policy_id": CAMPAIGN_POLICY_ID,
            "base_model_repository": BASE_MODEL_REPOSITORY,
            "base_model_revision": BASE_MODEL_REVISION,
            "split_counts": split_counts,
            "files": inventory,
            "training_executed": False,
            "training_authorized": False,
        }
        manifest["content_hash"] = __import__(
            "orchestwin.projects.requirements_primitives",
            fromlist=["snapshot_content_hash"],
        ).snapshot_content_hash(manifest)
        (destination / "materialization-manifest.json").write_text(
            canonical_json(manifest),
            encoding="utf-8",
        )

        print(destination.resolve())
        print("thesis_dataset_materialization: PASSED")
        print("total_examples:", quality["total_examples"])
        print("train_examples:", split_counts["TRAIN"])
        print("validation_examples:", split_counts["VALIDATION"])
        print("internal_test_examples:", split_counts["INTERNAL_TEST"])
        print("abstention_fraction:", quality["abstention_fraction"])
        print("domain_count:", quality["domain_count"])
        print("role_count:", quality["role_count"])
        print("leakage_issue_count:", quality["leakage_issue_count"])
        print("training_executed: False")
        print("training_authorized: False")
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(
            f"thesis_dataset_materialization_failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 22


if __name__ == "__main__":
    raise SystemExit(main())
