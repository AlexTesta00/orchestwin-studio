#!/usr/bin/env python3
"""Prepare scope-focused development data and whole-group training retention."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from prepare_complete_evaluator import checked_output, digest, save  # noqa: E402

from orchestwin.training.evaluator_assessment import validate_domain_response  # noqa: E402
from orchestwin.training.evaluator_coverage import structural_features  # noqa: E402
from orchestwin.training.scoped_interface_curriculum import iter_curriculum  # noqa: E402
from orchestwin.training.scoped_interface_fixtures import (  # noqa: E402
    CURRICULUM_ID,
    LAYOUT_SPLITS,
    SERVICE_SPLITS,
)


def semantic_key(row):
    payload = json.loads(row["messages"][1]["content"])["input"]
    content = payload.get("verified_artifact_content")
    selected = dict(
        task=payload["artifact_bundle"]["scenario"]["task"],
        profile=payload["user_twin"]["profile"],
        locale=row["locale"],
        html=content["items"][0]["data"] if content else None,
    )
    raw = json.dumps(selected, ensure_ascii=False, sort_keys=True)
    # Includes unrequested decoys; their opaque identities cannot create fake diversity.
    for index, token in enumerate(row["identity_tokens"]):
        raw = raw.replace(token, f"element-{index}")
    return hashlib.sha256(raw.encode()).hexdigest()


def retention_selection(source, group_limit):
    manifest = json.loads((source / "manifest.json").read_bytes())
    if manifest["curriculum_id"] != "grounded-evaluator-complete-interface-v3":
        raise ValueError("retention must come from the pinned v3 training corpus")
    expected = manifest["files"]["train.jsonl"]
    groups = {}
    hasher = hashlib.sha256()
    rows = 0
    with (source / "train.jsonl").open("rb") as stream:
        for line in stream:
            hasher.update(line)
            row = json.loads(line)
            if row["split"] != "train":
                raise ValueError("retention includes a non-training row")
            rows += 1
            stratum = (row["family"], row.get("service_family"), row.get("structure_family"))
            if groups.setdefault(row["group_id"], stratum) != stratum:
                raise ValueError("retention group crosses strata")
    if hasher.hexdigest() != expected["sha256"] or rows != expected["rows"]:
        raise ValueError("retention training source changed")
    families = sorted({s[0] for s in groups.values()})
    if type(group_limit) is not int or not len(families) <= group_limit <= len(groups):
        raise ValueError("retention budget must cover each source family with complete groups")
    ranked = sorted(
        groups, key=lambda g: hashlib.sha256(("scope-retention-v1:" + g).encode()).hexdigest()
    )
    chosen = {next(g for g in ranked if groups[g][0] == family) for family in families}
    # Add distinct service/layout strata before taking additional groups from a stratum.
    queues = defaultdict(list)
    for group in ranked:
        if group not in chosen:
            queues[groups[group]].append(group)
    while len(chosen) < group_limit:
        for stratum in sorted(queues, key=str):
            if queues[stratum] and len(chosen) < group_limit:
                chosen.add(queues[stratum].pop(0))
    return manifest, chosen


def export(
    output,
    *,
    seed=2026091604,
    train_groups=96,
    validation_groups=12,
    retention=None,
    retention_groups=24,
):
    for count in (train_groups, validation_groups):
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("scoped groups must be between 1 and 1000")
    retained_manifest, retained_groups = (
        (None, set()) if retention is None else retention_selection(retention, retention_groups)
    )
    output = checked_output(output)
    files, stats, seen, group_splits = {}, {}, {}, {}
    for split, count in (("train", train_groups), ("validation", validation_groups)):
        total = duplicates = 0
        kept_groups = set()
        state_counts, conditions, locales, coverage = (Counter() for _ in range(4))
        with (output / f"{split}.jsonl").open("xb") as stream:
            for row in iter_curriculum(seed=seed, split=split, groups=count):
                group = row["group_id"]
                if group in retained_groups or group_splits.setdefault(group, split) != split:
                    raise ValueError("counterfactual group leaked across sources or partitions")
                key = semantic_key(row)
                gold = tuple(
                    (c["family"], c["state"], c["reason"]) for c in row["control_judgements"]
                )
                if key in seen:
                    if seen[key] != (split, gold):
                        raise ValueError(
                            "normalized prompt crosses splits or has conflicting labels"
                        )
                    duplicates += 1
                    continue
                seen[key] = split, gold
                kept_groups.add(group)
                stream.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode())
                total += 1
                state_counts[row["judgement"]] += 1
                conditions[row["condition"]] += 1
                locales[row["locale"]] += 1
                coverage.update(name for name, value in structural_features(row).items() if value)
            retained, retained_families = 0, Counter()
            if split == "train" and retention is not None:
                hasher = hashlib.sha256()
                with (retention / "train.jsonl").open("rb") as previous:
                    for line in previous:
                        hasher.update(line)
                        row = json.loads(line)
                        if row["group_id"] in retained_groups:
                            if row["split"] != "train":
                                raise ValueError("retention cannot include held-out rows")
                            validate_domain_response(json.loads(row["messages"][2]["content"]), row)
                            stream.write(line if line.endswith(b"\n") else line + b"\n")
                            retained += 1
                            retained_families[row["family"]] += 1
                if hasher.hexdigest() != retained_manifest["files"]["train.jsonl"]["sha256"]:
                    raise ValueError("retention changed during copying")
        path = output / f"{split}.jsonl"
        files[path.name] = dict(
            rows=total + retained, size_bytes=path.stat().st_size, sha256=digest(path)
        )
        stats[split] = dict(
            scoped_groups_retained=len(kept_groups),
            scoped_rows=total,
            retention_rows=retained,
            removed_duplicates=duplicates,
            scoped_states=dict(state_counts),
            scoped_locales=dict(locales),
            conditions=dict(conditions),
            scoped_structural_coverage_rows=dict(coverage),
            retention_families=dict(retained_families),
        )
    sources = [
        Path(__file__),
        ROOT / "environments/training/prepare_complete_evaluator.py",
        *[
            ROOT / "src/orchestwin/training" / name
            for name in (
                "scoped_interface_fixtures.py",
                "scoped_interface_curriculum.py",
                "scoped_interface_validation.py",
                "complete_interface_validation.py",
                "evaluator_assessment.py",
                "evaluator_coverage.py",
            )
        ],
    ]
    operators = output / "operators"
    operators.mkdir()
    for path in sources:
        (operators / path.name).write_bytes(path.read_bytes())
    manifest = dict(
        curriculum_id=CURRICULUM_ID,
        seed=seed,
        files=files,
        statistics=stats,
        source_sha256={p.relative_to(ROOT).as_posix(): digest(p) for p in sources},
        service_splits=SERVICE_SPLITS,
        layout_splits=LAYOUT_SPLITS,
        groups_requested=dict(train=train_groups, validation=validation_groups),
        retention=None
        if retention is None
        else dict(
            path=str(retention),
            manifest_sha256=digest(retention / "manifest.json"),
            train_sha256=retained_manifest["files"]["train.jsonl"]["sha256"],
            selected_groups=sorted(retained_groups),
            selection="Deterministic whole training groups covering each source family, then service/layout strata; no model scores.",
        ),
        native_domain_validated_rows=sum(f["rows"] for f in files.values()),
        split_policy="Translation and counterfactual siblings stay in one partition. Services and layouts are disjoint; normalized duplicate inputs are removed and cannot cross partitions.",
        scope="SYNTHETIC_DEVELOPMENT_CURRICULUM_NOT_FINAL_QUALIFICATION",
        independent_qualification_required=True,
        previous_challenge_is_known_regression=True,
        final_test_files_opened=False,
        training_executed=False,
        human_label_review_performed=False,
        limitations=[
            "Closed static scope and two property families, not arbitrary browser behavior or the complete accessible-name algorithm.",
            "Template labels are synthetic engineering supervision, not expert labels or empirical evidence.",
            "Training duration and corpus size do not establish model quality. Fresh independently authored qualification remains required.",
        ],
    )
    save(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--retention", type=Path)
    parser.add_argument("--train-groups", type=int, default=96)
    parser.add_argument("--validation-groups", type=int, default=12)
    parser.add_argument("--retention-groups", type=int, default=24)
    parser.add_argument("--seed", type=int, default=2026091604)
    args = parser.parse_args()
    manifest = export(**vars(args))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "files": manifest["files"],
                "statistics": manifest["statistics"],
            }
        )
    )


if __name__ == "__main__":
    main()
