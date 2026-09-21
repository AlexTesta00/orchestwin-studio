#!/usr/bin/env python3
"""Stream a large, deduplicated complete-page curriculum; never train or publish."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orchestwin.training.complete_interface_curriculum import iter_curriculum  # noqa: E402
from orchestwin.training.complete_interface_fixtures import (  # noqa: E402
    CURRICULUM_ID,
    LAYOUTS,
    SERVICE_SPLITS,
    SERVICES,
)
from orchestwin.training.evaluator_assessment import validate_domain_response  # noqa: E402


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def semantic_key(row):
    """Ignore opaque IDs/hashes and arbitrary reference numbers, retaining task/DOM relations."""
    user = json.loads(row["messages"][1]["content"])["input"]
    content = user.get("verified_artifact_content")
    value = dict(
        instruction=row["messages"][0]["content"],
        task=user["artifact_bundle"]["scenario"]["task"],
        profile=user["user_twin"]["profile"],
        html=content["items"][0]["data"] if content else None,
        locale=row["locale"],
    )
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    raw = raw.replace(row["form_target"], "form-target")
    for index, control in enumerate(row["control_judgements"]):
        raw = raw.replace(control["target"], f"control-{index}")
    raw = re.sub(r"\b(?:Reference|Item) \d+\b", "Example reference", raw)
    return hashlib.sha256(raw.encode()).hexdigest()


def checked_output(output):
    output = output.absolute()
    if ".." in output.parts or any(
        p.is_symlink() or p.is_junction() for p in (output, *output.parents)
    ):
        raise ValueError("dataset output cannot traverse links")
    allowed = ROOT / "environments/training/artifacts"
    if output == ROOT or (ROOT in output.parents and allowed not in output.parents):
        raise ValueError("dataset output must be external or inside training artifacts")
    output.mkdir(parents=True, exist_ok=False)
    return output


def export(
    output: Path,
    *,
    seed=2026091503,
    train_groups=1800,
    validation_groups=96,
    test_groups=96,
    retention: Path | None = None,
):
    counts = dict(train=train_groups, validation=validation_groups, test=test_groups)
    for groups in counts.values():
        if (
            isinstance(groups, bool)
            or not isinstance(groups, int)
            or not 3 <= groups <= 30000
            or groups % 3
        ):
            raise ValueError("group counts must be multiples of three between 3 and 30000")
    retention_manifest = None
    if retention is not None:
        retention_manifest = json.loads((retention / "manifest.json").read_bytes())
        if retention_manifest["curriculum_id"] != "grounded-evaluator-relational-calibration-v2":
            raise ValueError("retention source must be the existing relational curriculum")
        expected = retention_manifest["files"]["train.jsonl"]
        if digest(retention / "train.jsonl") != expected["sha256"]:
            raise ValueError("retention source data changed")
        protected_tasks = {
            SERVICES[index][language]
            for split in ("validation", "test")
            for index in SERVICE_SPLITS[split]
            for language in (0, 1)
        }
        with (retention / "train.jsonl").open("rb") as source:
            for line in source:
                row = json.loads(line)
                task = json.loads(row["messages"][1]["content"])["input"]["artifact_bundle"][
                    "scenario"
                ]["name"]
                if row["split"] != "train" or task in protected_tasks:
                    raise ValueError("retention includes a held-out split or service task")
    output = checked_output(output)
    sources = [
        Path(__file__),
        *[
            ROOT / "src/orchestwin/training" / name
            for name in (
                "complete_interface_curriculum.py",
                "complete_interface_fixtures.py",
                "complete_interface_validation.py",
                "grounded_evaluator_curriculum.py",
                "relational_evaluator_curriculum.py",
                "evaluator_assessment.py",
            )
        ],
    ]
    operators = output / "operators"
    operators.mkdir()
    for source in sources:
        (operators / source.name).write_bytes(source.read_bytes())
    seen, identities, files, statistics = {}, {}, {}, {}
    generated = kept = 0
    with (output / "deduplicated.jsonl").open("x", encoding="utf-8") as duplicates:
        for split, groups in counts.items():
            labels, control_states, conditions, sizes, families = (Counter() for _ in range(5))
            retained = dropped = broad = 0
            with (output / f"{split}.jsonl").open("xb") as stream:
                for row in iter_curriculum(seed=seed, split=split, groups=groups):
                    generated += 1
                    key = semantic_key(row)
                    gold = tuple(
                        (c["family"], c["state"], c["reason"]) for c in row["control_judgements"]
                    )
                    if key in seen:
                        previous_split, previous_gold = seen[key]
                        if previous_split != split:
                            raise ValueError("normalized prompt leaked across dataset splits")
                        if gold != previous_gold:
                            raise ValueError("equivalent semantic inputs have conflicting labels")
                        duplicates.write(
                            json.dumps(
                                dict(
                                    group_id=row["group_id"],
                                    locale=row["locale"],
                                    condition=row["condition"],
                                    semantic_sha256=key,
                                )
                            )
                            + "\n"
                        )
                        dropped += 1
                        continue
                    seen[key] = (split, gold)
                    group = row["group_id"]
                    if identities.setdefault(group, split) != split:
                        raise ValueError("counterfactual group leakage")
                    stream.write(
                        (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode()
                    )
                    broad += 1
                    kept += 1
                    labels[row["judgement"]] += 1
                    sizes[str(len(row["control_judgements"]))] += 1
                    conditions[row["condition"]] += 1
                    control_states.update(c["state"] for c in row["control_judgements"])
                    families.update(c["family"] for c in row["control_judgements"])
                    if kept % 1000 == 0:
                        value = dict(
                            stage="GENERATING", split=split, generated=generated, kept=kept
                        )
                        temporary = output / "progress.tmp"
                        save(temporary, value)
                        temporary.replace(output / "progress.json")
                        print(json.dumps(value), flush=True)
                if split == "train" and retention is not None:
                    with (retention / "train.jsonl").open("rb") as source:
                        for line in source:
                            row = json.loads(line)
                            if row["split"] != "train" or row["group_id"] in identities:
                                raise ValueError(
                                    "retention must contain separate training groups only"
                                )
                            validate_domain_response(
                                json.loads(row["messages"][-1]["content"]), row
                            )
                            # Keep each previous row byte-for-byte, not its validation/test files.
                            stream.write(line if line.endswith(b"\n") else line + b"\n")
                            retained += 1
                            labels[row["judgement"]] += 1
                    if retained != retention_manifest["files"]["train.jsonl"]["rows"]:
                        raise ValueError("retention source row count changed")
            path = output / f"{split}.jsonl"
            files[path.name] = dict(
                rows=broad + retained, size_bytes=path.stat().st_size, sha256=digest(path)
            )
            statistics[split] = dict(
                broad_rows=broad,
                retention_rows=retained,
                generated_broad_rows=broad + dropped,
                removed_id_only_or_repeated_semantic_inputs=dropped,
                judgement_counts=dict(labels),
                broad_control_states=dict(control_states),
                broad_control_families=dict(families),
                broad_target_counts=dict(sizes),
                conditions=dict(conditions),
                service_families=list(SERVICE_SPLITS[split]),
                structure_families=list(LAYOUTS[split]),
            )
    manifest = dict(
        curriculum_id=CURRICULUM_ID,
        seed=seed,
        groups_requested=counts,
        files=files,
        statistics=statistics,
        scope="SYNTHETIC_COMPLETE_PAGE_AND_NARROW_RETENTION_TRAINING_CANDIDATE",
        source_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
        native_domain_validated_rows=sum(f["rows"] for f in files.values()),
        independently_checked_broad_rows=sum(s["broad_rows"] for s in statistics.values()),
        counterfactual_groups_cross_splits=False,
        normalized_prompt_overlap_cross_splits=False,
        split_policy="Complete counterfactual groups and both translations stay in one split; broad service phrases and layout families are held out together. Repeated semantic inputs after identifier normalization are removed within a split and forbidden across splits.",
        retention_source=None
        if retention is None
        else dict(
            path=str(retention),
            manifest_sha256=digest(retention / "manifest.json"),
            train_sha256=digest(retention / "train.jsonl"),
            rows=statistics["train"]["retention_rows"],
            validation_and_test_copied=False,
        ),
        supervision="Full completion targets; old three-state decision-token masking is incompatible with multi-control and partial-evidence examples.",
        sampling_policy="Combinatorial corpus, not a natural prevalence estimate. Choose training sampling using validation, and report any oversampling separately from unique dataset rows.",
        requires_tokenization_audit=True,
        training_executed=False,
        selected_for_production=False,
        formal_case_used=False,
        human_label_review_performed=False,
        empirical_validation=False,
        limitations=[
            "Closed static HTML grammar; not the complete accessible-name algorithm or a browser audit.",
            "Template-derived synthetic labels are not expert or real-user observations.",
            "Row count is not a count of independent real-world scenarios.",
            "Independent inference and semantic review are required after training; old 108 reserved cases remain separate.",
        ],
    )
    save(output / "manifest.json", manifest)
    save(output / "progress.json", dict(stage="DATASET_PREPARED", files=files, training=False))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2026091503)
    parser.add_argument("--train-groups", type=int, default=1800)
    parser.add_argument("--validation-groups", type=int, default=96)
    parser.add_argument("--test-groups", type=int, default=96)
    parser.add_argument("--retention", type=Path)
    args = parser.parse_args()
    manifest = export(
        args.output,
        seed=args.seed,
        train_groups=args.train_groups,
        validation_groups=args.validation_groups,
        test_groups=args.test_groups,
        retention=args.retention,
    )
    print(json.dumps(dict(output=str(args.output), files=manifest["files"])), flush=True)


if __name__ == "__main__":
    main()
