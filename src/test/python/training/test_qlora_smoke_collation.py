"""Regression tests for input binding and completion-only batch collation."""

from __future__ import annotations

import copy
import json

import pytest
from test_qlora_smoke_tokenization import ROOT, WHEN, execute

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.qlora_smoke_collation import (
    SmokeCollationError,
    audit_collator,
    load_verified_smoke_inputs,
    run_collator_preflight,
)


class FakeCollator:
    """List-based oracle used only by tests; it does not attest TRL execution."""

    def __init__(self, pad=0):
        self.pad = pad

    def __call__(self, rows):
        width = max(len(row["input_ids"]) for row in rows)
        output = {"input_ids": [], "attention_mask": [], "labels": []}
        for row in rows:
            ids = row["input_ids"]
            padding = width - len(ids)
            output["input_ids"].append(ids + [self.pad] * padding)
            output["attention_mask"].append([1] * len(ids) + [0] * padding)
            output["labels"].append(
                [
                    token if keep else -100
                    for token, keep in zip(ids, row["completion_mask"], strict=True)
                ]
                + [-100] * padding
            )
        return output


def verified(tmp_path):
    report = execute(tmp_path)
    return load_verified_smoke_inputs(
        repository_root=ROOT,
        preparation_root=tmp_path / "prepared",
        tokenization_root=report.parent,
        source_evidence_path=tmp_path / "sources/evidence.json",
    )


def test_twenty_rows_are_bound_to_the_frozen_preparation(tmp_path):
    data = verified(tmp_path)
    assert len(data.examples) == 20
    assert len(data.rows("train")) == 16
    assert len(data.rows("validation")) == 4
    assert data.prepared.configuration["optimization"]["max_steps"] == 8


def test_every_label_and_padding_position_is_checked(tmp_path):
    data = verified(tmp_path)
    audit = audit_collator(data, FakeCollator())
    assert audit["sample_count"] == 20
    assert audit["single_batch_checks"] == 20
    assert audit["padded_batch_checks"] == 2
    assert audit["completion_only_labels_verified"] is True


@pytest.mark.parametrize("field", ["input_ids", "attention_mask", "labels"])
def test_corrupted_collation_is_rejected(tmp_path, field):
    data = verified(tmp_path)
    base = FakeCollator()

    def corrupt(rows):
        out = base(rows)
        out[field][0][0] = 4321
        return out

    with pytest.raises(SmokeCollationError):
        audit_collator(data, corrupt)


def test_prompt_or_padding_loss_cannot_be_enabled_silently(tmp_path):
    data = verified(tmp_path)
    base = FakeCollator()

    def unmasked(rows):
        out = base(rows)
        out["labels"] = copy.deepcopy(out["input_ids"])
        return out

    with pytest.raises(SmokeCollationError, match="labels"):
        audit_collator(data, unmasked)


def test_report_is_non_authorizing_and_does_not_overwrite(tmp_path):
    data = verified(tmp_path)
    output = tmp_path / "audit"
    path = run_collator_preflight(data, FakeCollator(), output_root=output, created_at=WHEN)
    report = json.loads(path.read_text())
    assert report["status"] == "COLLATOR_VERIFIED_NOT_AUTHORIZED"
    assert report["training_executed"] is False
    assert report["owner_fixture_review"] == "PENDING"
    assert report["model_weights_loaded"] is False
    with pytest.raises(SmokeCollationError, match="new"):
        run_collator_preflight(data, FakeCollator(), output_root=output, created_at=WHEN)


@pytest.mark.parametrize(
    "path",
    [
        "tokenized/tokenization-report.json",
        "tokenized/tokenized-train.jsonl",
        "tokenized/tokenized-validation.jsonl",
        "sources/files/tokenizer.json",
        "prepared/train.jsonl",
    ],
)
def test_changed_inputs_are_rejected(tmp_path, path):
    execute(tmp_path)
    file = tmp_path / path
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ValueError):
        load_verified_smoke_inputs(
            repository_root=ROOT,
            preparation_root=tmp_path / "prepared",
            tokenization_root=tmp_path / "tokenized",
            source_evidence_path=tmp_path / "sources/evidence.json",
        )


def test_self_rehashed_wrong_mask_is_rejected_by_observation_digests(tmp_path):
    execute(tmp_path)
    file = tmp_path / "tokenized/tokenized-train.jsonl"
    rows = [json.loads(line) for line in file.read_text().splitlines()]
    rows[0]["completion_mask"][0] = 1
    file.write_bytes(b"".join(canonical_json(row).encode() + b"\n" for row in rows))
    import hashlib

    path = tmp_path / "tokenized/tokenization-report.json"
    report = json.loads(path.read_text())
    report["output_file_sha256"][file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    report.pop("content_hash")
    report["content_hash"] = snapshot_content_hash(report)
    path.write_bytes(canonical_json(report).encode())
    with pytest.raises(SmokeCollationError):
        load_verified_smoke_inputs(
            repository_root=ROOT,
            preparation_root=tmp_path / "prepared",
            tokenization_root=tmp_path / "tokenized",
            source_evidence_path=tmp_path / "sources/evidence.json",
        )


def test_probe_output_cannot_be_placed_inside_the_inputs(tmp_path):
    data = verified(tmp_path)
    with pytest.raises(SmokeCollationError, match="protected"):
        run_collator_preflight(
            data,
            FakeCollator(),
            output_root=tmp_path / "prepared/new-output",
            created_at=WHEN,
        )


def test_floating_point_label_arrays_are_not_accepted(tmp_path):
    data = verified(tmp_path)
    base = FakeCollator()

    def wrong_dtype(rows):
        out = base(rows)
        out["labels"] = [[float(v) for v in row] for row in out["labels"]]
        return out

    with pytest.raises(SmokeCollationError, match="labels"):
        audit_collator(data, wrong_dtype)
