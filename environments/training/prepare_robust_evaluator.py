#!/usr/bin/env python3
"""Freeze v6 invariance training and holdouts, retaining every v5 training byte."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from prepare_complete_evaluator import checked_output, digest, save  # noqa: E402

from orchestwin.training.evaluator_assessment import validate_domain_response  # noqa: E402
from orchestwin.training.robust_interface_curriculum import iter_curriculum  # noqa: E402
from orchestwin.training.robust_interface_fixtures import (  # noqa: E402
    CURRICULUM_ID,
    LAYOUTS,
    SERVICES,
)
from orchestwin.training.robustness_leakage import semantic_key  # noqa: E402
from orchestwin.training.scoped_evaluator_scoring import assess  # noqa: E402


def protected_inputs(sources, known):
    keys, groups, records = set(), set(), []
    for source in sources:
        manifest = json.loads((source / "manifest.json").read_bytes())
        path = source / "validation.jsonl"
        expected = manifest["files"]["validation.jsonl"]
        if digest(path) != expected["sha256"]:
            raise ValueError("protected validation digest differs")
        count = 0
        with path.open("rb") as stream:
            for line in stream:
                row = json.loads(line)
                if row["split"] != "validation":
                    raise ValueError("protected split is not validation")
                keys.add(semantic_key(row))
                groups.add(row["group_id"])
                count += 1
        if count != expected["rows"]:
            raise ValueError("protected validation count differs")
        records.append(dict(path=str(path), sha256=digest(path), rows=count))
    for path in known:
        rows = json.loads(path.read_bytes())
        if not rows or any(len(r["messages"]) != 2 for r in rows):
            raise ValueError("known development inputs require system/user messages only")
        keys.update(semantic_key(row) for row in rows)
        records.append(dict(path=str(path), sha256=digest(path), rows=len(rows)))
    return keys, groups, records


def export(output, *, retention, protected_validation=(), known_inputs=(), seed=2026091706):
    old = json.loads((retention / "manifest.json").read_bytes())
    if old["curriculum_id"] != "grounded-evaluator-balanced-scope-v5":
        raise ValueError("frozen balanced v5 retention required")
    expected = old["files"]["train.jsonl"]
    if digest(retention / "train.jsonl") != expected["sha256"]:
        raise ValueError("retention source changed")
    protected, protected_groups, references = protected_inputs(
        tuple(dict.fromkeys((retention, *protected_validation))), known_inputs
    )
    output = checked_output(output)
    seen, groups, invariants, files, statistics = {}, {}, {}, {}, {}
    for split in ("train", "validation"):
        path = output / (split + ".jsonl")
        counts, locales, modes, surfaces = Counter(), Counter(), Counter(), Counter()
        with path.open("xb") as target:
            for row in iter_curriculum(seed=seed, split=split):
                key = semantic_key(row)
                gold = tuple(
                    (f["family"], f["state"], f["reason"]) for f in row["control_judgements"]
                )
                if groups.setdefault(row["group_id"], split) != split:
                    raise ValueError("sibling group crosses partitions")
                if split == "train" and (key in protected or row["group_id"] in protected_groups):
                    raise ValueError("training overlaps protected development")
                if key in seen and seen[key] != (split, gold):
                    raise ValueError("normalized input crosses splits or changes its label")
                counts["normalized_siblings_retained"] += key in seen
                seen[key] = split, gold
                family = row["invariance_group"]
                if invariants.setdefault(family, gold) != gold:
                    raise ValueError("surface or prose intervention changes static facts")
                target.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode())
                counts["robustness_rows"] += 1
                locales[row["locale"]] += 1
                modes[row["condition"]] += 1
                surfaces[
                    (row["id_style"], row["quote_style"], row["void_style"], row["prose_style"])
                ] += 1
            if split == "train":
                new_training_keys = set(seen)
                new_training_groups = set(groups)
                source_hash = hashlib.sha256()
                with (retention / "train.jsonl").open("rb") as source:
                    for line in source:
                        source_hash.update(line)
                        row = json.loads(line)
                        key = semantic_key(row)
                        if (
                            row["split"] != "train"
                            or row["group_id"] in protected_groups
                            or key in protected
                        ):
                            raise ValueError("retained training overlaps protected development")
                        if row["group_id"] in new_training_groups:
                            raise ValueError("new and retained group identities overlap")
                        groups[row["group_id"]] = "train"
                        if key in new_training_keys:
                            raise ValueError("new training duplicates retained input")
                        value = json.loads(row["messages"][2]["content"])
                        validate_domain_response(value, row)
                        if (
                            row.get("control_judgements")
                            and not assess(
                                row["messages"][2]["content"],
                                row,
                                eos_finished=True,
                                schema_finished=True,
                            )["passed"]
                        ):
                            raise ValueError("retained gold fails frozen scoring")
                        seen[key] = "train", None
                        target.write(line)
                        counts["retention_rows"] += 1
                        locales[row["locale"]] += 1
                if (
                    source_hash.hexdigest() != expected["sha256"]
                    or counts["retention_rows"] != expected["rows"]
                ):
                    raise ValueError("retention bytes/count changed during copying")
        total = counts["robustness_rows"] + counts["retention_rows"]
        files[path.name] = dict(rows=total, size_bytes=path.stat().st_size, sha256=digest(path))
        statistics[split] = dict(
            counts=counts,
            locales=locales,
            modes=modes,
            surfaces={str(k): v for k, v in surfaces.items()},
        )
    source_paths = [Path(__file__), ROOT / "environments/training/prepare_complete_evaluator.py"]
    source_paths += [
        ROOT / "src/orchestwin/training" / name
        for name in (
            "robust_interface_fixtures.py",
            "robust_interface_curriculum.py",
            "robustness_leakage.py",
            "scoped_interface_validation.py",
            "complete_interface_validation.py",
            "scoped_evaluator_scoring.py",
            "evaluator_assessment.py",
            "grounded_evaluator_curriculum.py",
            "relational_evaluator_curriculum.py",
        )
    ]
    operators = output / "operators"
    operators.mkdir()
    for path in source_paths:
        (operators / path.name).write_bytes(path.read_bytes())
    manifest = dict(
        curriculum_id=CURRICULUM_ID,
        seed=seed,
        files=files,
        statistics=statistics,
        source_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in source_paths},
        task_splits=SERVICES,
        template_splits=LAYOUTS,
        invariance_groups=len(invariants),
        retention=dict(
            path=str(retention),
            manifest_sha256=digest(retention / "manifest.json"),
            train_sha256=expected["sha256"],
            rows=expected["rows"],
            all_rows_and_whole_groups_byte_identical=True,
            row_share=expected["rows"] / files["train.jsonl"]["rows"],
        ),
        leakage_audit=dict(
            protected_sources=references,
            normalized_training_overlap=0,
            train_validation_overlap=0,
            group_overlap=0,
            normalization="Consistent DOM/task ID references and parsed equivalent quote/void syntax; natural language text is not altered. Invariant siblings are retained within their original split.",
        ),
        synthetic=True,
        empirical=False,
        training_executed=False,
        final_test_files_opened=False,
        human_expert_validation=False,
        scope="SYNTHETIC_ROBUSTNESS_DEVELOPMENT_NOT_FINAL_QUALIFICATION",
    )
    save(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retention", type=Path, required=True)
    parser.add_argument("--protected-validation", type=Path, action="append", default=[])
    parser.add_argument("--known-inputs", type=Path, action="append", default=[])
    parser.add_argument("--seed", type=int, default=2026091706)
    report = export(**vars(parser.parse_args()))
    print(json.dumps({k: report[k] for k in ("curriculum_id", "files", "retention")}))


if __name__ == "__main__":
    main()
