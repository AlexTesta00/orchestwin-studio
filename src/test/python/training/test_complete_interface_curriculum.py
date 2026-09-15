"""Independent control facts, partial evidence and leakage checks without inference."""

import importlib.util
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from orchestwin.training.complete_interface_curriculum import example
from orchestwin.training.complete_interface_fixtures import conditions, scenario
from orchestwin.training.complete_interface_validation import observe, validate_annotations


def operator():
    path = (
        Path(__file__).resolve().parents[4] / "environments/training/prepare_complete_evaluator.py"
    )
    spec = importlib.util.spec_from_file_location("prepare_complete_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "html,expected",
    [
        (
            '<label for="name">Name</label><input id="name" /><button id="go">Send</button>',
            ("PRESENT", "PRESENT"),
        ),
        (
            '<label for="other">Name</label><input id="name" /><button id="go">Send</button>',
            ("MISSING", "PRESENT"),
        ),
        (
            '<input id="name" /><section><label for="name"><b>Name</b></label></section><button id="go" aria-labelledby="gone"></button><span id="outside">Send</span>',
            ("PRESENT", "MISSING"),
        ),
        (
            '<input id="name" /><button id="go" aria-labelledby="a b"></button><span id="a">Send</span><span id="b">request</span>',
            ("MISSING", "PRESENT"),
        ),
        (
            '<label>Name<input id="name" /></label><button id="go" aria-label=" "></button>',
            ("MISSING", "MISSING"),
        ),
        ('<button id="go">Send</button>', ("INSUFFICIENT", "PRESENT")),
    ],
)
def test_static_properties_are_independent(html, expected):
    raw = f'<html><body><form id="f">{html}</form></body></html>'
    controls = [dict(target="name", family="input_label"), dict(target="go", family="button_name")]
    assert tuple(row["state"] for row in observe(raw, "f", controls)) == expected


def test_form_absence_and_unavailable_content_have_distinct_reasons():
    controls = [dict(target="go", family="button_name")]
    raw = '<html><body><button id="go">Help</button></body></html>'
    assert observe(raw, "f", controls)[0]["reason"] == "FORM_ABSENT"
    assert observe(None, "f", controls)[0]["reason"] == "CONTENT_NOT_SUPPLIED"
    raw = '<html><body><form id="f"></form><button id="go">Help</button></body></html>'
    assert observe(raw, "f", controls)[0]["reason"] == "TARGET_ABSENT_FROM_FORM"


def test_duplicate_ids_are_not_silently_resolved():
    with pytest.raises(ValueError, match="duplicate fixture ID"):
        observe(
            '<html><form id="f"><button id="go">OK</button><button id="go"></button></form></html>',
            "f",
            [dict(target="go", family="button_name")],
        )


@pytest.mark.parametrize("layout", range(12))
def test_all_layouts_and_counterfactual_vectors_pass_independent_and_native_checks(layout):
    for ordinal in range(3):
        case = replace(scenario(71, "train", ordinal), layout=layout)
        for mode, states in conditions(case):
            row = example(case, "it" if ordinal % 2 else "en", mode, states)
            assert tuple(c["state"] for c in validate_annotations(row)) == states
            user = json.loads(row["messages"][1]["content"])
            assert "control_judgements" not in user and "judgement" not in user
            assert row["synthetic"] is True and row["empirical"] is False


def test_partial_evidence_preserves_supported_findings():
    case = scenario(19, "train", 1)
    row = example(case, "en", "partial", ("INSUFFICIENT", "MISSING", "PRESENT"))
    value = json.loads(row["messages"][2]["content"])
    assert not value["abstained"] and len(value["evidence_gaps"]) == len(value["findings"]) == 1
    assert value["findings"][0]["location"] == f"dom:#{case.controls[1].target}"
    value["abstained"] = True
    row["messages"][2]["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="partial evidence"):
        validate_annotations(row)


def test_missing_control_omission_and_false_positive_are_rejected():
    case = scenario(17, "train", 0)
    row = example(case, "en", "complete", ("MISSING", "MISSING"))
    value = json.loads(row["messages"][2]["content"])
    value["findings"].pop()
    row["messages"][2]["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="each missing control"):
        validate_annotations(row)
    row = example(case, "en", "complete", ("MISSING", "PRESENT"))
    value = json.loads(row["messages"][2]["content"])
    value["findings"][0]["location"] = f"dom:#{case.controls[1].target}"
    row["messages"][2]["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="each missing control"):
        validate_annotations(row)


def test_normalized_deduplication_ignores_identifiers_but_keeps_relations():
    prepare = operator()
    case = scenario(19, "train", 0)
    row = example(case, "en", "complete", ("MISSING", "PRESENT"))
    renamed = deepcopy(row)
    for old, new in [
        (case.form, "new-form"),
        *[(c.target, f"new-{i}") for i, c in enumerate(case.controls)],
    ]:
        renamed = json.loads(json.dumps(renamed).replace(old, new))
    assert prepare.semantic_key(row) == prepare.semantic_key(renamed)
    fixed = example(case, "en", "complete", ("PRESENT", "PRESENT"))
    assert prepare.semantic_key(row) != prepare.semantic_key(fixed)


def test_streaming_export_freezes_separate_services_layouts_and_digests(tmp_path):
    prepare = operator()
    folder = tmp_path / "complete"
    report = prepare.export(folder, train_groups=3, validation_groups=3, test_groups=3)
    sets = []
    for split in ("train", "validation", "test"):
        path = folder / f"{split}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert prepare.digest(path) == report["files"][path.name]["sha256"]
        assert len(rows) == report["files"][path.name]["rows"]
        sets.append({row["group_id"] for row in rows})
    assert not any(a & b for i, a in enumerate(sets) for b in sets[i + 1 :])
    assert report["training_executed"] is report["formal_case_used"] is False
    assert not tuple(folder.rglob("*.md"))
    with pytest.raises(FileExistsError):
        prepare.export(folder, train_groups=3, validation_groups=3, test_groups=3)


def test_only_verified_training_data_can_supply_retention(tmp_path):
    prepare = operator()
    source = tmp_path / "old"
    source.mkdir()
    (source / "train.jsonl").write_bytes(b"{}\n")
    (source / "manifest.json").write_text(
        json.dumps(
            dict(
                curriculum_id="grounded-evaluator-relational-calibration-v2",
                files={"train.jsonl": dict(sha256="0" * 64, rows=1)},
            )
        )
    )
    with pytest.raises(ValueError, match="retention source data changed"):
        prepare.export(
            tmp_path / "out", train_groups=3, validation_groups=3, test_groups=3, retention=source
        )
    assert not (tmp_path / "out").exists()
