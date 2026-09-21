"""Scope rules and counterfactual supervision, checked without model inference."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from orchestwin.training.scoped_interface_curriculum import example
from orchestwin.training.scoped_interface_fixtures import VARIANTS, Variant, scenario
from orchestwin.training.scoped_interface_validation import observe, validate_annotations


@pytest.mark.parametrize(
    "html,scope,expected",
    [
        (
            '<form id="booking"><label for="person">Person</label><input id="person" /></form>',
            "descendants",
            "PRESENT",
        ),
        (
            '<form id="booking"><label>Person<input id="person" /></label></form>',
            "descendants",
            "MISSING",
        ),
        (
            '<label for="person">Person</label><form id="booking"><input id="person" /></form>',
            "descendants",
            "PRESENT",
        ),
        ('<input id="person" /><form id="booking"></form>', "descendants", "INSUFFICIENT"),
        (
            '<label for="person">Person</label><input id="person" form="booking" /><form id="booking"></form>',
            "owner",
            "PRESENT",
        ),
        (
            '<label for="person">Person</label><input id="person" form="booking" /><form id="booking"></form>',
            "descendants",
            "INSUFFICIENT",
        ),
        (
            '<form id="booking"><label for="person">Person</label><input id="person" form="elsewhere" /></form><form id="elsewhere"></form>',
            "owner",
            "INSUFFICIENT",
        ),
        (
            '<label for="person">Person</label><input id="person" form="booking" />',
            "owner",
            "INSUFFICIENT",
        ),
        ('<div id="booking"><input id="person" /></div>', "descendants", "INSUFFICIENT"),
        (None, "owner", "INSUFFICIENT"),
    ],
)
def test_independent_scope_facts(html, scope, expected):
    raw = "<html>" + html + "</html>" if html else None
    assert (
        observe(raw, "booking", [dict(target="person", family="input_label")], scope)[0]["state"]
        == expected
    )


@pytest.mark.parametrize(
    "content,state",
    [
        ('<button id="go"><!-- Submit --></button>', "MISSING"),
        ('<span>Submit</span><button id="go" aria-labelledby="gone"></button>', "MISSING"),
        (
            '<button id="go" aria-labelledby="name"></button><span id="name">Submit</span>',
            "PRESENT",
        ),
    ],
)
def test_button_comments_and_broken_references_are_not_names(content, state):
    assert (
        observe(
            f'<html><form id="booking">{content}</form></html>',
            "booking",
            [dict(target="go", family="button_name")],
            "descendants",
        )[0]["state"]
        == state
    )


@pytest.mark.parametrize(
    "split,ordinal",
    [("train", 0), ("train", 6), ("train", 12), ("validation", 0), ("validation", 2)],
)
def test_every_variant_matches_design_intent_and_native_domain(split, ordinal):
    for variant in VARIANTS:
        for locale in ("en", "it"):
            row = example(scenario(816, split, ordinal), variant, locale)
            validate_annotations(row)
            payload = json.loads(row["messages"][1]["content"])
            assert (
                not {"control_judgements", "judgement", "condition", "scope_policy"}
                & payload.keys()
            )
            assert row["synthetic"] and not row["empirical"]


def test_same_html_different_requested_scope_changes_abstention():
    case = scenario(816, "train", 0)
    owner = example(case, Variant("one", placement="owned", scope="owner"), "en")
    descendants = example(case, Variant("two", placement="owned"), "en")

    def html(row):
        return json.loads(row["messages"][1]["content"])["input"]["verified_artifact_content"][
            "items"
        ][0]["data"]

    assert html(owner) == html(descendants)
    assert not json.loads(owner["messages"][2]["content"])["abstained"]
    assert json.loads(descendants["messages"][2]["content"])["abstained"]


def test_unrequested_decoy_changes_cannot_change_requested_summary_or_locations():
    case = scenario(19, "train", 0)
    rows = [example(case, v, "it") for v in VARIANTS if v.name.startswith("button-subset-")]
    outputs = [json.loads(r["messages"][2]["content"]) for r in rows]
    assert outputs[0]["overall_summary"] == outputs[1]["overall_summary"]
    assert (
        [f["location"] for f in outputs[0]["findings"]]
        == [f["location"] for f in outputs[1]["findings"]]
        == ["dom:#" + case.button]
    )
    corrupted = deepcopy(rows[0])
    outputs[0]["overall_summary"] += f" #{case.decoy} is satisfied."
    corrupted["messages"][2]["content"] = json.dumps(outputs[0])
    with pytest.raises(ValueError, match="unrequested target"):
        validate_annotations(corrupted)


def test_partial_gaps_and_supported_findings_must_both_survive():
    row = example(
        scenario(17, "train", 0), Variant("partial", placement="detached", button="empty"), "en"
    )
    value = json.loads(row["messages"][2]["content"])
    assert len(value["findings"]) == len(value["evidence_gaps"]) == 1 and not value["abstained"]
    value["evidence_gaps"] = []
    row["messages"][2]["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="scope gaps"):
        validate_annotations(row)


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / "environments/training"))
    return importlib.import_module("prepare_scoped_evaluator")


def test_normalization_includes_unrequested_ids_but_preserves_scope(operator):
    case = scenario(47, "train", 0)
    row = example(case, Variant("owned", placement="owned", scope="owner", selected="button"), "en")
    raw = json.dumps(row)
    for i, token in enumerate(row["identity_tokens"]):
        raw = raw.replace(token, f"renamed-{i}")
    assert operator.semantic_key(json.loads(raw)) == operator.semantic_key(row)
    alternative = example(case, Variant("inside-only", placement="owned", selected="button"), "en")
    assert operator.semantic_key(alternative) != operator.semantic_key(row)


def test_export_freezes_groups_partitions_and_positive_scope_coverage(operator, tmp_path):
    output = tmp_path / "scoped"
    manifest = operator.export(output, train_groups=2, validation_groups=2)
    partitions = []
    for split in ("train", "validation"):
        path = output / (split + ".jsonl")
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        assert operator.digest(path) == manifest["files"][path.name]["sha256"]
        assert len(rows) == manifest["files"][path.name]["rows"]
        partitions.append({r["group_id"] for r in rows})
        assert {r["locale"] for r in rows} == {"en", "it"}
        assert all(
            v > 0 for v in manifest["statistics"][split]["scoped_structural_coverage_rows"].values()
        )
    assert not partitions[0] & partitions[1]
    assert not (output / "test.jsonl").exists()
    assert not set(manifest["service_splits"]["train"]) & set(
        manifest["service_splits"]["validation"]
    )
    assert not set(manifest["layout_splits"]["train"]) & set(
        manifest["layout_splits"]["validation"]
    )


def test_retention_keeps_whole_training_groups_and_rejects_changed_bytes(operator, tmp_path):
    source = tmp_path / "previous"
    source.mkdir()
    original = [
        example(scenario(92, "train", 0), v, loc) for v in VARIANTS[:2] for loc in ("en", "it")
    ]
    for r in original:
        r["family"] = "complete_interface"
    raw = b"".join((json.dumps(r) + "\n").encode() for r in original)
    (source / "train.jsonl").write_bytes(raw)
    operator.save(
        source / "manifest.json",
        dict(
            curriculum_id="grounded-evaluator-complete-interface-v3",
            files={"train.jsonl": dict(rows=4, sha256=operator.digest(source / "train.jsonl"))},
        ),
    )
    output = tmp_path / "with-retention"
    manifest = operator.export(
        output, train_groups=1, validation_groups=1, retention=source, retention_groups=1
    )
    assert manifest["statistics"]["train"]["retention_rows"] == 4
    assert (output / "train.jsonl").read_bytes().endswith(raw)
    (source / "train.jsonl").write_bytes(raw + raw)
    with pytest.raises(ValueError, match="source changed"):
        operator.export(tmp_path / "invalid", retention=source, retention_groups=1)
    assert not (tmp_path / "invalid").exists()


def test_scoped_preflight_checks_cache_and_never_opens_reserved_test(
    operator, tmp_path, monkeypatch
):
    audit = importlib.import_module("audit_scoped_evaluator")
    source = tmp_path / "source"
    manifest = operator.export(source, train_groups=1, validation_groups=1)
    reserved = source / "test.jsonl"
    reserved.write_bytes(b"reserved cases must not be opened")
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != reserved, "reserved test was opened"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    class Tokenizer:
        eos_token_id = 9

        def apply_chat_template(self, messages, **kwargs):
            return [1, 2] if len(messages) == 2 else [1, 2, 3, 9]

    output = tmp_path / "preflight"
    report = audit.audit(source, output, Tokenizer())
    assert report["cache"]["rows"] == manifest["files"]["train.jsonl"]["rows"]
    assert report["cache"]["completion_tokens"] == report["cache"]["rows"] * 2
    assert report["splits"]["validation"]["rows"] == manifest["files"]["validation.jsonl"]["rows"]
    assert not report["final_test_files_opened"] and not report["training_executed"]
    assert (output / "cache/train.sqlite").is_file()


def test_scoped_preflight_rejects_manifest_with_reserved_partition(operator, tmp_path):
    audit = importlib.import_module("audit_scoped_evaluator")
    source = tmp_path / "source"
    manifest = operator.export(source, train_groups=1, validation_groups=1)
    manifest["files"]["test.jsonl"] = manifest["files"]["validation.jsonl"]
    operator.save(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="development corpus"):
        audit.audit(source, tmp_path / "forbidden", None)
    assert not (tmp_path / "forbidden").exists()
