"""Content relations, valid supervision and isolation of unseen structures."""

import json
from collections import defaultdict

import pytest

from orchestwin.training.evaluator_assessment import validate_domain_response
from orchestwin.training.relational_evaluator_curriculum import build_curriculum, oracle


@pytest.mark.parametrize(
    "raw,family,expected",
    [
        (
            '<html><button id="t" aria-labelledby="name" /><span id="name"><b>Save</b></span></html>',
            "button_name",
            "PRESENT",
        ),
        (
            '<html><button id="t" aria-labelledby="absent" /><span id="name">Save</span></html>',
            "button_name",
            "MISSING",
        ),
        (
            '<html><button id="t" aria-labelledby="name" /><span id="name"> \n </span></html>',
            "button_name",
            "MISSING",
        ),
        ('<html><label for="other">Guest</label><input id="t" /></html>', "input_label", "MISSING"),
        (
            '<html><input id="t" /><section><label for="t"><b>Guest</b></label></section></html>',
            "input_label",
            "PRESENT",
        ),
        ('<html id="t"><section lang="it">Ciao</section></html>', "document_language", "MISSING"),
        ('<html><h1 id="other">Title</h1></html>', "heading", "INSUFFICIENT"),
        ('<html><h1 id="t"><span> </span></h1><h1>Other</h1></html>', "heading", "MISSING"),
    ],
)
def test_relational_oracle_follows_selected_target(raw, family, expected):
    assert oracle(raw, family, "t") == expected


def test_every_label_passes_the_domain_and_structures_never_cross_splits():
    rows = build_curriculum(variants=16)
    structures, groups = defaultdict(set), defaultdict(set)
    insufficiency = set()
    for row in rows:
        validate_domain_response(json.loads(row["messages"][-1]["content"]), row)
        structures[row["split"]].add(row["structure_family"])
        groups[row["group_id"]].add(row["split"])
        user = json.loads(row["messages"][1]["content"])
        if row["judgement"] == "INSUFFICIENT":
            insufficiency.add("verified_artifact_content" in user["input"])
        assert "structure_family" not in row["messages"][1]["content"]
        assert "judgement" not in row["messages"][1]["content"]
    assert structures == {"train": set(range(6)), "validation": {6}, "test": {7}}
    assert all(len(split) == 1 for split in groups.values())
    assert insufficiency == {True, False}
