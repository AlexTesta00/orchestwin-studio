#!/usr/bin/env python3
"""Freeze v5 scope contrasts with broad, byte-identical whole-group retention."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from prepare_complete_evaluator import checked_output, digest, save  # noqa: E402

from orchestwin.training.balanced_scope_curriculum import (  # noqa: E402
    CURRICULUM_ID,
    iter_curriculum,
)
from orchestwin.training.complete_interface_validation import validate_annotations  # noqa: E402
from orchestwin.training.evaluator_assessment import validate_domain_response  # noqa: E402
from orchestwin.training.scoped_evaluator_scoring import assess  # noqa: E402
from orchestwin.training.scoped_interface_fixtures import (  # noqa: E402
    LAYOUT_SPLITS,
    SERVICE_SPLITS,
)


def semantic_key(row):
    """Normalize opaque identities, retaining scope, properties, language and DOM relations."""
    user = json.loads(row["messages"][1]["content"])
    payload = user["input"]
    content = payload.get("verified_artifact_content")
    raw = content["items"][0]["data"] if content else None
    task = payload["artifact_bundle"]["scenario"]["task"]
    ids = list(
        dict.fromkeys(
            re.findall(r'\bid=["\']([^"\']+)', raw or "") + re.findall(r"#([\w-]+)", task)
        )
    )
    text = json.dumps(
        dict(
            instruction=row["messages"][0]["content"],
            task=task,
            profile=payload["user_twin"]["profile"],
            html=raw,
            schema=user["output_schema"],
            contract=user.get("response_contract"),
        ),
        sort_keys=True,
        ensure_ascii=False,
    )
    mapping = {token: f"{{ELEMENT_{i}}}" for i, token in enumerate(ids)}
    if ids:
        text = re.sub(
            "|".join(re.escape(t) for t in sorted(ids, key=len, reverse=True)),
            lambda m: mapping[m.group()],
            text,
        )
    text = re.sub(r"\b(?:Reference|Item) \d+\b", "Example reference", text)
    return hashlib.sha256(text.encode()).hexdigest()


def coverage(row):
    """Coverage categories, not a model-quality metric or an arbitrary HTML oracle."""
    locale = row["locale"]
    facts = row.get("control_judgements", [])
    result = {(row["family"], locale, row["judgement"])}
    if facts:
        result.add(("arity_mode", locale, len(facts), row["condition"]))
        for fact in facts:
            result.add(("property_state", locale, fact["family"], fact["state"]))
            result.add(("property_reason", locale, fact["family"], fact["reason"]))
    return result


def index_retention(source):
    manifest = json.loads((source / "manifest.json").read_bytes())
    if manifest["curriculum_id"] != "grounded-evaluator-complete-interface-v3":
        raise ValueError("pinned v3 training corpus required")
    groups, hasher, count = {}, hashlib.sha256(), 0
    with (source / "train.jsonl").open("rb") as stream:
        for line in stream:
            hasher.update(line)
            row = json.loads(line)
            if row["split"] != "train":
                raise ValueError("retention cannot use held-out rows")
            count += 1
            stratum = (row["family"], row.get("service_family"), row.get("structure_family"))
            group = groups.setdefault(
                row["group_id"], dict(rows=0, stratum=stratum, coverage=set())
            )
            if group["stratum"] != stratum:
                raise ValueError("retention group crosses strata")
            group["rows"] += 1
            group["coverage"].update(coverage(row))
    expected = manifest["files"]["train.jsonl"]
    if hasher.hexdigest() != expected["sha256"] or count != expected["rows"]:
        raise ValueError("retention source changed")
    return manifest, groups


def select_retention(groups, scope_rows, minimum_share=0.60):
    if not 0.5 <= minimum_share <= 0.8:
        raise ValueError("retention share must be between 0.5 and 0.8")
    target = math.ceil(scope_rows * minimum_share / (1 - minimum_share))
    ranked = sorted(groups, key=lambda g: hashlib.sha256((CURRICULUM_ID + g).encode()).hexdigest())
    selected, covered = set(), set()
    strata = {g["stratum"] for g in groups.values()}
    required = set().union(*(g["coverage"] for g in groups.values()))
    queues = defaultdict(list)
    for key in ranked:
        queues[groups[key]["stratum"]].append(key)
    # At least one complete group from EVERY source family/service/layout stratum.
    for stratum in sorted(strata, key=str):
        key = queues[stratum].pop(0)
        selected.add(key)
        covered.update(groups[key]["coverage"])
    for key in ranked:
        if groups[key]["coverage"] - covered:
            selected.add(key)
            covered.update(groups[key]["coverage"])
    retained = sum(groups[key]["rows"] for key in selected)
    while retained < target:
        before = retained
        for stratum in sorted(queues, key=str):
            while queues[stratum] and queues[stratum][0] in selected:
                queues[stratum].pop(0)
            if queues[stratum] and retained < target:
                key = queues[stratum].pop(0)
                selected.add(key)
                retained += groups[key]["rows"]
        if retained == before:
            raise ValueError("retention source cannot meet the minimum share")
    assert covered == required
    return selected


def protected_inputs(validation_sources, known_inputs):
    keys, groups, records = set(), set(), []
    for source in validation_sources:
        manifest = json.loads((source / "manifest.json").read_bytes())
        path = source / "validation.jsonl"  # Never discover or read test files.
        expected = manifest["files"][path.name]
        if digest(path) != expected["sha256"]:
            raise ValueError("protected validation changed")
        count = 0
        with path.open("rb") as stream:
            for line in stream:
                row = json.loads(line)
                if row["split"] != "validation":
                    raise ValueError("protected source must be validation")
                keys.add(semantic_key(row))
                groups.add(row["group_id"])
                count += 1
        if count != expected["rows"]:
            raise ValueError("protected validation row count differs")
        records.append(dict(path=str(path), sha256=digest(path), rows=count))
    if known_inputs is not None:
        rows = json.loads(known_inputs.read_bytes())
        if not rows or any(len(r["messages"]) != 2 for r in rows):
            raise ValueError("known development inputs must contain only system/user messages")
        keys.update(semantic_key(row) for row in rows)
        records.append(dict(path=str(known_inputs), sha256=digest(known_inputs), rows=len(rows)))
    return keys, groups, records


def export(
    output,
    *,
    retention,
    seed=2026091705,
    train_groups=54,
    validation_groups=12,
    minimum_retention_share=0.60,
    protected_validation=(),
    known_inputs=None,
):
    for count in (train_groups, validation_groups):
        if type(count) is not int or not 1 <= count <= 1000:
            raise ValueError("scope group count must be between 1 and 1000")
    retained_manifest, group_index = index_retention(retention)
    validation_sources = tuple(dict.fromkeys((retention, *protected_validation)))
    protected, protected_groups, references = protected_inputs(validation_sources, known_inputs)
    output = checked_output(output)
    files, statistics, seen, group_splits = {}, {}, {}, {}
    counts, chosen, trained_keys = {}, set(), set()
    for split, count in (("train", train_groups), ("validation", validation_groups)):
        stats = dict(scope_rows=0, retention_rows=0, normalized_scope_duplicates_removed=0)
        states, locales, conditions, retained_families, retained_coverage = (
            Counter() for _ in range(5)
        )
        path = output / f"{split}.jsonl"
        with path.open("xb") as stream:
            for row in iter_curriculum(seed=seed, split=split, groups=count):
                group = row["group_id"]
                if group_splits.setdefault(group, split) != split or group in group_index:
                    raise ValueError("scope group leaked across partitions or retention")
                key = semantic_key(row)
                if split == "train" and (key in protected or group in protected_groups):
                    raise ValueError("training overlaps protected development inputs")
                gold = tuple(
                    (c["family"], c["state"], c["reason"]) for c in row["control_judgements"]
                )
                if key in seen:
                    if seen[key] != (split, gold):
                        raise ValueError(
                            "normalized prompt crosses splits or has conflicting labels"
                        )
                    stats["normalized_scope_duplicates_removed"] += 1
                    continue
                seen[key] = split, gold
                if split == "validation" and key in trained_keys:
                    raise ValueError("new validation overlaps retained training")
                if not assess(
                    row["messages"][2]["content"], row, eos_finished=True, schema_finished=True
                )["passed"]:
                    raise ValueError("scope gold fails frozen development scoring")
                stream.write((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode())
                stats["scope_rows"] += 1
                states[row["judgement"]] += 1
                locales[row["locale"]] += 1
                conditions[row["condition"]] += 1
                if split == "train":
                    trained_keys.add(key)
            if split == "train":
                chosen = select_retention(group_index, stats["scope_rows"], minimum_retention_share)
                copied, hasher, duplicates = Counter(), hashlib.sha256(), 0
                with (retention / "train.jsonl").open("rb") as source:
                    for line in source:
                        hasher.update(line)
                        row = json.loads(line)
                        if row["group_id"] not in chosen:
                            continue
                        key = semantic_key(row)
                        if (
                            row["split"] != "train"
                            or key in protected
                            or row["group_id"] in protected_groups
                        ):
                            raise ValueError(
                                "retained training overlaps protected development inputs"
                            )
                        validate_domain_response(json.loads(row["messages"][2]["content"]), row)
                        if row["family"] == "complete_interface":
                            validate_annotations(row)
                            if not assess(
                                row["messages"][2]["content"],
                                row,
                                eos_finished=True,
                                schema_finished=True,
                            )["passed"]:
                                raise ValueError(
                                    "retention gold fails exact target/gap/criterion scoring"
                                )
                        duplicates += key in trained_keys
                        trained_keys.add(key)
                        stream.write(line)  # Preserve every byte and every sibling of the group.
                        copied[row["group_id"]] += 1
                        stats["retention_rows"] += 1
                        retained_families[row["family"]] += 1
                        retained_coverage.update(coverage(row))
                if hasher.hexdigest() != retained_manifest["files"]["train.jsonl"]["sha256"]:
                    raise ValueError("retention source changed during copying")
                if dict(copied) != {key: group_index[key]["rows"] for key in chosen}:
                    raise ValueError("retention lost whole-group siblings")
                stats["retention_normalized_duplicates_preserved"] = duplicates
        rows = stats["scope_rows"] + stats["retention_rows"]
        counts[split] = rows
        files[path.name] = dict(rows=rows, size_bytes=path.stat().st_size, sha256=digest(path))
        stats.update(
            scope_states=dict(states),
            scope_locales=dict(locales),
            conditions=dict(conditions),
            retention_families=dict(retained_families),
            retention_coverage={str(k): v for k, v in sorted(retained_coverage.items(), key=str)},
        )
        statistics[split] = stats
    source_names = [
        "environments/training/prepare_balanced_evaluator.py",
        "environments/training/prepare_complete_evaluator.py",
    ]
    source_names += [
        "src/orchestwin/training/" + name + ".py"
        for name in (
            "balanced_scope_curriculum",
            "scoped_interface_curriculum",
            "scoped_interface_fixtures",
            "scoped_interface_validation",
            "complete_interface_validation",
            "evaluator_assessment",
            "scoped_evaluator_scoring",
            "grounded_evaluator_curriculum",
            "relational_evaluator_curriculum",
        )
    ]
    operators = output / "operators"
    operators.mkdir()
    for name in source_names:
        (operators / Path(name).name).write_bytes((ROOT / name).read_bytes())
    manifest = dict(
        curriculum_id=CURRICULUM_ID,
        seed=seed,
        files=files,
        statistics=statistics,
        source_sha256={name: digest(ROOT / name) for name in source_names},
        service_splits=SERVICE_SPLITS,
        layout_splits=LAYOUT_SPLITS,
        retention=dict(
            path=str(retention),
            manifest_sha256=digest(retention / "manifest.json"),
            train_sha256=retained_manifest["files"]["train.jsonl"]["sha256"],
            selected_groups=sorted(chosen),
            whole_groups_byte_identical=True,
            source_strata=len({g["stratum"] for g in group_index.values()}),
            selected_strata=len({group_index[g]["stratum"] for g in chosen}),
            minimum_row_share=minimum_retention_share,
            measured_row_share=statistics["train"]["retention_rows"] / counts["train"],
            selection="SHA256-ranked whole training groups, every source family/service/layout stratum and every observed property/state/reason/locale/arity/mode category; round-robin strata until row share is met. No model scores.",
        ),
        leakage_audit=dict(
            protected_sources=references,
            normalized_training_overlap=0,
            protected_group_overlap=0,
            new_train_validation_overlap=0,
            normalization="System instruction, task, profile, complete HTML, output schema and response contract; consistently rename all DOM/task IDs and arbitrary Reference/Item numbers.",
        ),
        native_domain_validated_rows=sum(counts.values()),
        final_test_files_opened=False,
        training_executed=False,
        human_label_review_performed=False,
        scope="SYNTHETIC_DEVELOPMENT_CURRICULUM_NOT_FINAL_QUALIFICATION",
        limitations=[
            "Closed static HTML grammar; no rendered browser, arbitrary accessibility or real-user claims.",
            "A minimum retention row fraction is not a token-level balance guarantee; token audit is required.",
            "Legacy retention rows are unchanged, including any measured normalized duplicates.",
            "Development inputs and known challenge are not independent final qualification; no quality improvement is claimed before inference.",
        ],
    )
    save(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retention", type=Path, required=True)
    parser.add_argument("--protected-validation", type=Path, action="append", default=[])
    parser.add_argument("--known-inputs", type=Path)
    parser.add_argument("--seed", type=int, default=2026091705)
    parser.add_argument("--train-groups", type=int, default=54)
    parser.add_argument("--validation-groups", type=int, default=12)
    parser.add_argument("--minimum-retention-share", type=float, default=0.60)
    args = parser.parse_args()
    manifest = export(**vars(args))
    print(
        json.dumps(
            dict(
                curriculum_id=CURRICULUM_ID,
                files=manifest["files"],
                retention={
                    k: v for k, v in manifest["retention"].items() if k != "selected_groups"
                },
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
