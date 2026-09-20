"""Check supervision against content, production schema and counterfactual isolation."""

import json
from collections import defaultdict

import pytest

from orchestwin.training.grounded_evaluator_curriculum import (
    FAMILIES,
    build_curriculum,
    example,
    oracle,
)


@pytest.mark.parametrize("family", FAMILIES)
def test_labels_change_with_content_while_ids_stay_constant(family):
    rows = [
        example(seed=7, family=family, variant=3, locale="en", state=state)
        for state in ("MISSING", "PRESENT", "INSUFFICIENT")
    ]
    inputs = [json.loads(row["messages"][1]["content"])["input"] for row in rows]
    outputs = [json.loads(row["messages"][2]["content"]) for row in rows]
    assert len({i["project_id"] for i in inputs}) == 1
    assert len({i["user_twin"]["profile"]["name"] for i in inputs}) == 1
    assert len(outputs[0]["findings"]) == 1
    assert outputs[0]["findings"][0]["requires_human_validation"] is True
    assert outputs[1]["findings"] == [] and outputs[1]["abstained"] is False
    assert outputs[2]["findings"] == [] and outputs[2]["abstained"] is True
    assert outputs[2]["evidence_gaps"]
    assert "verified_artifact_content" not in inputs[2]


def test_oracle_reads_selected_element_and_ignores_distractor():
    raw = '<html><button id="target"></button><button id="other">Submit</button></html>'
    assert oracle(raw, "button_name", "target") == "MISSING"
    assert oracle(raw, "button_name", "other") == "PRESENT"
    assert oracle(raw, "button_name", "absent") == "INSUFFICIENT"
    assert oracle(None, "button_name", "target") == "INSUFFICIENT"


def test_counterfactuals_and_translations_never_cross_splits():
    rows = build_curriculum(variants=8)
    groups = defaultdict(list)
    tasks = defaultdict(set)
    for row in rows:
        groups[row["group_id"]].append(row)
        payload = json.loads(row["messages"][1]["content"])
        tasks[row["split"]].add(payload["input"]["artifact_bundle"]["scenario"]["name"])
        assert row["synthetic"] and not row["empirical"]
        assert "group_id" not in row["messages"][1]["content"]
    assert all(len(g) == 6 and len({r["split"] for r in g}) == 1 for g in groups.values())
    assert tasks["train"].isdisjoint(tasks["test"] | tasks["validation"])
    assert tasks["test"].isdisjoint(tasks["validation"])


def test_seed_changes_opaque_ids_without_changing_the_judgement():
    rows = [
        example(seed=seed, family="heading", variant=0, locale="it", state="MISSING")
        for seed in (1, 2)
    ]
    assert rows[0]["group_id"] != rows[1]["group_id"]
    assert rows[0]["judgement"] == rows[1]["judgement"] == "MISSING"


def test_invalid_family_cannot_silently_select_an_oracle():
    with pytest.raises(ValueError):
        oracle("<html />", "invented", "target")
