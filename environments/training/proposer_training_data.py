"""Train-only, completion-masked cache for verified source-generation examples."""

from __future__ import annotations

import json
import sqlite3
import struct
from collections import Counter
from contextlib import closing
from pathlib import Path

from complete_training_data import MODEL, REVISION, digest, save

MAX_SEQUENCE = 8192
CURRICULUM = "verified-proposer-web-source-v1"
EXCLUDED_FAMILIES = frozenset({"sales-tax", "temperature", "guest-list", "expense-split"})


def encode(tokenizer, messages, *, max_sequence=MAX_SEQUENCE):
    if [m["role"] for m in messages] != ["system", "user", "assistant"]:
        raise ValueError("three complete messages required")
    if any(not isinstance(m["content"], str) or not m["content"].strip() for m in messages):
        raise ValueError("empty or invalid message")
    prefix = tokenizer.apply_chat_template(
        messages[:2], tokenize=True, add_generation_prompt=True, return_dict=False
    )
    complete = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=False, return_dict=False
    )
    boundary = len(prefix)
    if complete[:boundary] != prefix or len(complete) <= boundary:
        raise ValueError("training and inference completion boundaries differ")
    if tokenizer.eos_token_id not in complete[boundary:]:
        raise ValueError("completion EOS missing")
    if len(complete) > max_sequence:
        raise ValueError("complete example exceeds context; truncation is forbidden")
    return complete, boundary


def prepare_cache(data, output, manifest_sha256, tokenizer):
    """Never load held-out validation examples; only inspect their declared hashes."""
    data, output = Path(data), Path(output)
    if digest(data / "manifest.json") != manifest_sha256:
        raise ValueError("dataset manifest changed")
    manifest = json.loads((data / "manifest.json").read_bytes())
    if manifest["curriculum_id"] != CURRICULUM:
        raise ValueError("verified proposer curriculum required")
    if not set(manifest["excluded_semantic_families"]) >= EXCLUDED_FAMILIES:
        raise ValueError("independent evaluation families are not excluded")
    expected = manifest["files"]["train.jsonl"]["sha256"]
    if digest(data / "train.jsonl") != expected:
        raise ValueError("training source digest mismatch")
    output.mkdir(parents=True, exist_ok=False)
    database = output / "train.sqlite"
    families, locales, stages = Counter(), Counter(), Counter()
    groups, seen = set(), set()
    tokens = completions = 0
    lengths = []
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE examples (id INTEGER PRIMARY KEY, source_row INTEGER, "
            "group_id TEXT, tokens BLOB, boundary INTEGER)"
        )
        with (data / "train.jsonl").open(encoding="utf-8") as stream:
            for number, line in enumerate(stream):
                row = json.loads(line)
                family = row["semantic_family"]
                if row["split"] != "train" or family in EXCLUDED_FAMILIES:
                    raise ValueError("held-out or excluded family in training source")
                if row["provenance"] != "SYNTHETIC_ENGINEER_AUTHORED":
                    raise ValueError("unverified training provenance")
                identity = (row["group_id"], row["locale"], row["step"])
                if identity in seen:
                    raise ValueError("duplicate training example")
                seen.add(identity)
                ids, boundary = encode(tokenizer, row["messages"])
                connection.execute(
                    "INSERT INTO examples VALUES (?, ?, ?, ?, ?)",
                    (number, number, row["group_id"], struct.pack(f"<{len(ids)}I", *ids), boundary),
                )
                families[family] += 1
                locales[row["locale"]] += 1
                stages[row["step"]] += 1
                groups.add(row["group_id"])
                lengths.append(len(ids))
                tokens += len(ids)
                completions += len(ids) - boundary
        if not lengths:
            raise ValueError("empty training source")
        connection.commit()
    report = dict(
        curriculum_id=CURRICULUM,
        model=MODEL,
        revision=REVISION,
        manifest_sha256=manifest_sha256,
        train_sha256=expected,
        database_sha256=digest(database),
        rows=len(lengths),
        total_tokens=tokens,
        completion_tokens=completions,
        max_sequence=MAX_SEQUENCE,
        min_tokens=min(lengths),
        max_tokens=max(lengths),
        selected_groups=sorted(groups),
        semantic_families=dict(families),
        locales=dict(locales),
        stages=dict(stages),
        completion_only=True,
        truncation=False,
        validation_read=False,
        final_cases_read=False,
        operator_sha256=digest(Path(__file__)),
    )
    save(output / "cache.json", report)
    return report
