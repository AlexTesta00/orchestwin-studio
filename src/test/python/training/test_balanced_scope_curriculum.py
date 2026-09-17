"""Scope contrasts, corpus composition and contamination boundaries without inference."""

import importlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from orchestwin.training.balanced_scope_curriculum import (
    CONTRASTS,
    balanced_case,
    example,
    render_contrast,
)
from orchestwin.training.scoped_evaluator_scoring import assess


def find(name):
    return next(c for c in CONTRASTS if c.variant.name == name)


@pytest.mark.parametrize("locale", ["en", "it"])
@pytest.mark.parametrize("ordinal", range(18))
def test_all_rendered_contrasts_obey_independent_facts_and_native_contract(locale, ordinal):
    case = balanced_case(615, "train", ordinal)
    for contrast in CONTRASTS:
        row = example(case, contrast, locale)
        assert assess(row["messages"][2]["content"], row, eos_finished=True, schema_finished=True)[
            "passed"
        ]


@pytest.mark.parametrize("selected", ["both", "field", "button"])
@pytest.mark.parametrize("label,button", [("explicit", "text"), ("none", "empty")])
def test_identical_page_ownership_does_not_override_requested_ancestry(selected, label, button):
    case = balanced_case(100, "validation", 0)
    a, b = [
        find(f"owned-{label}-{button}-{selected}-{policy}") for policy in ("descendants", "owner")
    ]
    assert render_contrast(case, a, "en") == render_contrast(case, b, "en")
    inside, owner = [json.loads(example(case, c, "en")["messages"][2]["content"]) for c in (a, b)]
    assert inside["abstained"] and len(inside["evidence_gaps"]) == (2 if selected == "both" else 1)
    assert not owner["abstained"] and not owner["evidence_gaps"]
    assert bool(owner["findings"]) == (label == "none")


@pytest.mark.parametrize(
    "name,states",
    [
        ("external-label-explicit", ["PRESENT", "PRESENT"]),
        ("external-label-wrong", ["MISSING", "PRESENT"]),
        ("external-label-blank", ["MISSING", "PRESENT"]),
        ("multiple-references", ["PRESENT", "PRESENT"]),
        ("external-references", ["PRESENT", "PRESENT"]),
        ("blank-references", ["PRESENT", "MISSING"]),
        ("foreign-both-owner", ["INSUFFICIENT", "INSUFFICIENT"]),
        ("foreign-both-descendants", ["PRESENT", "PRESENT"]),
        ("detached-both-owner", ["INSUFFICIENT", "INSUFFICIENT"]),
        ("detached-with-external-label", ["INSUFFICIENT", "MISSING"]),
    ],
)
def test_supporting_text_location_is_distinct_from_target_scope(name, states):
    row = example(balanced_case(11, "train", 0), find(name), "it")
    assert [c["state"] for c in row["control_judgements"]] == states


def test_instruction_in_page_is_not_a_repair_instruction():
    row = example(balanced_case(26, "train", 1), find("untrusted-instruction"), "en")
    output = json.loads(row["messages"][2]["content"])
    assert len(output["findings"]) == 2
    assert all("remove" not in f["recommended_action"].lower() for f in output["findings"])
    assert all(f["epistemic_status"] == "MODEL_INFERRED" for f in output["findings"])


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "environments/training"))
    return importlib.import_module("prepare_balanced_evaluator")


def test_normalization_removes_identity_but_preserves_request_policy(operator):
    case = balanced_case(23, "train", 0)
    row = example(case, find("owned-explicit-text-both-owner"), "en")
    renamed = json.dumps(row)
    for i, token in enumerate(row["identity_tokens"]):
        renamed = renamed.replace(token, f"renamed-{i}")
    assert operator.semantic_key(row) == operator.semantic_key(json.loads(renamed))
    other = example(case, find("owned-explicit-text-both-descendants"), "en")
    assert operator.semantic_key(row) != operator.semantic_key(other)


def test_retention_covers_every_stratum_and_state_before_balancing(operator):
    groups = {
        f"g{i}": dict(rows=10, stratum=("complete", i % 3, i % 2), coverage={("property", i % 4)})
        for i in range(30)
    }
    selected = operator.select_retention(groups, 100, 0.6)
    assert len(selected) * 10 >= 150
    assert {groups[g]["stratum"] for g in selected} == {g["stratum"] for g in groups.values()}
    assert set().union(*(groups[g]["coverage"] for g in selected)) == {
        ("property", i) for i in range(4)
    }
    with pytest.raises(ValueError, match="cannot meet"):
        operator.select_retention(groups, 1000, 0.6)


def test_export_preserves_whole_retention_groups_and_checks_all_source_bytes(operator, tmp_path):
    old = importlib.import_module("prepare_complete_evaluator")
    source = tmp_path / "v3"
    old.export(source, train_groups=12, validation_groups=3, test_groups=3)
    output = tmp_path / "v5"
    manifest = operator.export(output, retention=source, train_groups=1, validation_groups=1)
    chosen = set(manifest["retention"]["selected_groups"])
    original = [
        line
        for line in (source / "train.jsonl").read_bytes().splitlines(keepends=True)
        if json.loads(line)["group_id"] in chosen
    ]
    assert (output / "train.jsonl").read_bytes().endswith(b"".join(original))
    assert manifest["retention"]["measured_row_share"] >= 0.6
    assert manifest["retention"]["source_strata"] == manifest["retention"]["selected_strata"]
    assert set(manifest["files"]) == {"train.jsonl", "validation.jsonl"}
    assert not (output / "test.jsonl").exists()
    rows = [json.loads(line) for line in (output / "train.jsonl").read_bytes().splitlines()]
    assert Counter(r["locale"] for r in rows)["en"] == Counter(r["locale"] for r in rows)["it"]
    with (source / "train.jsonl").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError):
        operator.export(
            tmp_path / "tampered", retention=source, train_groups=1, validation_groups=1
        )
    assert not (tmp_path / "tampered").exists()


def test_protected_known_prompt_is_rejected_even_with_different_ids(operator, tmp_path):
    old = importlib.import_module("prepare_complete_evaluator")
    source = tmp_path / "v3"
    old.export(source, train_groups=12, validation_groups=3, test_groups=3)
    row = example(balanced_case(2026091705, "train", 0), find("multiple-references"), "en")
    renamed = json.dumps(deepcopy(row))
    for i, token in enumerate(row["identity_tokens"]):
        renamed = renamed.replace(token, f"other-{i}")
    known = tmp_path / "known.json"
    known.write_text(json.dumps([dict(messages=json.loads(renamed)["messages"][:2])]))
    with pytest.raises(ValueError, match="overlaps protected"):
        operator.export(
            tmp_path / "v5",
            retention=source,
            known_inputs=known,
            train_groups=1,
            validation_groups=1,
        )
    assert not (tmp_path / "v5/manifest.json").exists()


def test_balanced_preflight_requires_explicit_version_and_does_not_read_test(
    operator, tmp_path, monkeypatch
):
    old = importlib.import_module("prepare_complete_evaluator")
    audit = importlib.import_module("audit_scoped_evaluator")
    source = tmp_path / "v3"
    old.export(source, train_groups=12, validation_groups=3, test_groups=3)
    data = tmp_path / "v5"
    manifest = operator.export(data, retention=source, train_groups=1, validation_groups=1)
    with pytest.raises(ValueError, match="development corpus"):
        audit.audit(data, tmp_path / "wrong-version", None)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path.name != "test.jsonl", "reserved test was opened"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    class Tokenizer:
        eos_token_id = 9

        def apply_chat_template(self, messages, **kwargs):
            return [1, 2] if len(messages) == 2 else [1, 2, 3, 9]

    report = audit.audit(
        data, tmp_path / "preflight", Tokenizer(), curriculum_id=operator.CURRICULUM_ID
    )
    assert report["cache"]["rows"] == manifest["files"]["train.jsonl"]["rows"]
    assert report["curriculum_id"] == operator.CURRICULUM_ID
    assert report["cache"]["curriculum_id"] == operator.CURRICULUM_ID
    manifest["files"]["test.jsonl"] = manifest["files"]["validation.jsonl"]
    operator.save(data / "manifest.json", manifest)
    with pytest.raises(ValueError, match="development corpus"):
        audit.audit(data, tmp_path / "forbidden", None, curriculum_id=operator.CURRICULUM_ID)
