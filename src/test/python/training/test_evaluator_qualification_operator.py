"""Cohort isolation and exact engineering decisions, without GPU inference."""

import hashlib
import json

import pytest

from src.test.python.training.test_evaluator_calibration_operator import operator


def test_explicit_cohort_preserves_whole_unseen_counterfactual_groups(tmp_path):
    prepare = operator("prepare_evaluator_calibration")
    qualify = operator("qualify_evaluator_candidate")
    data = tmp_path / "data"
    prepare.export(data, variants=16, curriculum="relational")
    diagnostic = qualify.select_cohort(data)
    assert len(diagnostic) == 36
    _, rows = qualify.calibration_operator().read_data(data)
    seen = {row["group_id"] for row in diagnostic}
    reserved = {row["group_id"] for row in rows["test"]} - seen
    payload = {
        "dataset_manifest_sha256": hashlib.sha256(
            (data / "manifest.json").read_bytes()
        ).hexdigest(),
        "split": "test",
        "group_ids": sorted(reserved),
    }
    selection = tmp_path / "groups.json"
    selection.write_text(json.dumps(payload))
    final = qualify.select_cohort(data, group_file=selection)
    assert len(final) == 36
    assert not seen & {row["group_id"] for row in final}
    assert {row["locale"] for row in final} == {"en", "it"}
    assert {row["judgement"] for row in final} == {"MISSING", "PRESENT", "INSUFFICIENT"}
    for changes in (
        {"dataset_manifest_sha256": "0" * 64},
        {"split": "validation"},
        {"group_ids": [*sorted(reserved), min(reserved)]},
        {"group_ids": ["unknown"]},
    ):
        selection.write_text(json.dumps(payload | changes))
        with pytest.raises(ValueError):
            qualify.select_cohort(data, group_file=selection)


@pytest.mark.parametrize(
    "change",
    [
        {"base_artifact_hash": "0" * 64},
        {"evaluation_hash": "0" * 64},
        {"supported_finding_refs": ["invented"]},
        {"supported_finding_refs": []},
        {"replacement_html": "<button></button>"},
        {"action": "AUTOMATIC"},
    ],
)
def test_revision_cannot_escape_the_reviewed_bytes_and_findings(change):
    qualify = operator("qualify_evaluator_candidate")
    raw = b"<button></button>"
    decision = {
        "base_artifact_hash": qualify.digest(raw),
        "evaluation_hash": "a" * 64,
        "action": "APPROVE",
        "reason": "The observed empty button has no name; add its intended action.",
        "supported_finding_refs": ["twin:approved:v1:UTF-001"],
        "replacement_html": "<button>Save</button>",
    }
    scope = {
        "raw": raw,
        "evaluation_hash": "a" * 64,
        "finding_refs": decision["supported_finding_refs"],
    }
    assert qualify.reviewed_revision(decision, **scope) == b"<button>Save</button>"
    with pytest.raises(ValueError):
        qualify.reviewed_revision(decision | change, **scope)
    assert qualify.reviewed_revision(decision | {"action": "STOP"}, **scope) is None
