"""Bounded-memory, training-only token cache for the complete-interface curriculum."""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import struct
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path

MODEL = "Qwen/Qwen3-4B-Instruct-2507"
REVISION = "abcc171021d4f320b2e7f47c6f0deca67ded870c"
CURRICULUM = "grounded-evaluator-complete-interface-v3"
MAX_SEQUENCE = 6144
OUTPUT_RESERVE = 2048
SEED = 2026091503


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    """Publish a complete status/manifest only after flushing its contents to disk."""
    import os

    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def encode(tokenizer, messages):
    if [m["role"] for m in messages] != ["system", "user", "assistant"]:
        raise ValueError("complete three-message training example required")
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
    if len(complete) > MAX_SEQUENCE or boundary + OUTPUT_RESERVE > MAX_SEQUENCE:
        raise ValueError("complete example exceeds context; truncation is forbidden")
    if len(complete) - boundary > OUTPUT_RESERVE:
        raise ValueError("completion exceeds generation reserve")
    return complete, boundary


def iter_train(data):
    # Deliberately never open validation.jsonl or test.jsonl in this operator.
    with (Path(data) / "train.jsonl").open("rb") as stream:
        for number, line in enumerate(stream):
            row = json.loads(line)
            if row["split"] != "train":
                raise ValueError("non-training row in training source")
            yield number, row


def selected_groups(data, limit):
    """Select whole groups round-robin across training service/layout/component strata.

    Selection never reads model scores or final cases. Within selected groups all
    states and translations are retained; this is a throughput pilot, not a quality test.
    """
    groups = {}
    for _, row in iter_train(data):
        stratum = (
            row.get("component", "retention"),
            str(row.get("service_family", "")),
            str(row.get("structure_family", "")),
        )
        previous = groups.setdefault(row["group_id"], stratum)
        if previous != stratum:
            raise ValueError("group crosses training strata")
    if limit is None:
        return set(groups)
    if type(limit) is not int or limit < 1:
        raise ValueError("positive group limit required")
    strata = defaultdict(list)
    for group, stratum in groups.items():
        strata[stratum].append(group)
    rng = random.Random(SEED)
    queues = [sorted(strata[key]) for key in sorted(strata)]
    for queue in queues:
        rng.shuffle(queue)
    rng.shuffle(queues)
    chosen = []
    while queues and len(chosen) < limit:
        following = []
        for queue in queues:
            if len(chosen) == limit:
                break
            chosen.append(queue.pop())
            if queue:
                following.append(queue)
        queues = following
    return set(chosen)


def prepare_cache(data, output, manifest_sha256, tokenizer, *, group_limit=None):
    data, output = Path(data), Path(output)
    if digest(data / "manifest.json") != manifest_sha256:
        raise ValueError("dataset manifest changed")
    manifest = json.loads((data / "manifest.json").read_bytes())
    if manifest["curriculum_id"] != CURRICULUM:
        raise ValueError("complete-interface v3 curriculum required")
    expected = manifest["files"]["train.jsonl"]
    if digest(data / "train.jsonl") != expected["sha256"]:
        raise ValueError("training source digest mismatch")
    groups = selected_groups(data, group_limit)
    output.mkdir(parents=True, exist_ok=False)
    database = output / "train.sqlite"
    rows = tokens = completions = source_rows = 0
    states, locales, lengths = Counter(), Counter(), Counter()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "CREATE TABLE examples (id INTEGER PRIMARY KEY, source_row INTEGER, "
            "group_id TEXT, tokens BLOB, boundary INTEGER)"
        )
        for number, row in iter_train(data):
            source_rows += 1
            if row["group_id"] not in groups:
                continue
            ids, boundary = encode(tokenizer, row["messages"])
            connection.execute(
                "INSERT INTO examples VALUES (?, ?, ?, ?, ?)",
                (rows, number, row["group_id"], struct.pack(f"<{len(ids)}I", *ids), boundary),
            )
            rows += 1
            tokens += len(ids)
            completions += len(ids) - boundary
            states[row["judgement"]] += 1
            locales[row["locale"]] += 1
            lengths[len(ids)] += 1
            if rows % 200 == 0:
                connection.commit()
                save(output / "progress.json", dict(stage="TOKENIZING_TRAIN", rows=rows))
        connection.commit()
    if source_rows != expected["rows"] or digest(data / "train.jsonl") != expected["sha256"]:
        raise ValueError("training source changed during preparation")
    if not rows:
        raise ValueError("empty training cache")
    report = dict(
        format_version=1,
        model=MODEL,
        revision=REVISION,
        curriculum_id=CURRICULUM,
        dataset_manifest_sha256=manifest_sha256,
        source=expected,
        database_sha256=digest(database),
        rows=rows,
        total_tokens=tokens,
        completion_tokens=completions,
        selected_groups=sorted(groups),
        group_limit=group_limit,
        seed=SEED,
        states=dict(states),
        locales=dict(locales),
        min_tokens=min(lengths),
        max_tokens=max(lengths),
        max_sequence=MAX_SEQUENCE,
        output_reserve=OUTPUT_RESERVE,
        completion_only=True,
        truncation=False,
        final_cases_read=False,
        sampler="SEE_RUN_PROTOCOL",
        operator_sha256=digest(Path(__file__)),
    )
    save(output / "cache.json", report)
    return report


class TokenDataset:
    """Map-style dataset: only one token sequence is materialized per lookup."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.metadata = json.loads((self.directory / "cache.json").read_bytes())
        if (self.metadata["model"], self.metadata["revision"], self.metadata["max_sequence"]) != (
            MODEL,
            REVISION,
            MAX_SEQUENCE,
        ):
            raise ValueError("token cache model or context mismatch")
        path = self.directory / "train.sqlite"
        if digest(path) != self.metadata["database_sha256"]:
            raise ValueError("token cache digest mismatch")
        self.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        count = self.connection.execute("SELECT count(*) FROM examples").fetchone()[0]
        if count != self.metadata["rows"]:
            self.close()
            raise ValueError("token cache row count mismatch")

    def __len__(self):
        return self.metadata["rows"]

    def __getitem__(self, index):
        row = self.connection.execute(
            "SELECT tokens, boundary FROM examples WHERE id=?", (int(index),)
        ).fetchone()
        if row is None:
            raise IndexError(index)
        blob, boundary = row
        ids = list(struct.unpack(f"<{len(blob) // 4}I", blob))
        return dict(input_ids=ids, labels=[-100] * boundary + ids[boundary:])

    def close(self):
        self.connection.close()


def padded_rows(rows, pad_token_id):
    """Right padding never adds loss; every target token, including EOS, keeps loss."""
    width = max(len(row["input_ids"]) for row in rows)
    result = dict(input_ids=[], attention_mask=[], labels=[])
    for row in rows:
        ids, labels = row["input_ids"], row["labels"]
        if not ids or len(labels) != len(ids) or all(label == -100 for label in labels):
            raise ValueError("empty or invalid supervised example")
        padding = width - len(ids)
        result["input_ids"].append(ids + [pad_token_id] * padding)
        result["attention_mask"].append([1] * len(ids) + [0] * padding)
        result["labels"].append(labels + [-100] * padding)
    return result
