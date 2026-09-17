"""Adversarial response mutations distinguish scope truth from valid JSON."""

import json
from copy import deepcopy

import pytest

from orchestwin.training.scoped_evaluator_scoring import assess
from orchestwin.training.scoped_interface_curriculum import example
from orchestwin.training.scoped_interface_fixtures import VARIANTS, Variant, scenario


def score(row, value=None, **kwargs):
    return assess(
        row["messages"][2]["content"] if value is None else json.dumps(value),
        row,
        **(dict(eos_finished=True, schema_finished=True) | kwargs),
    )


@pytest.mark.parametrize("locale", ["en", "it"])
def test_all_independently_validated_fixture_answers_pass(locale):
    for variant in VARIANTS:
        row = example(scenario(31, "validation", 1), variant, locale)
        result = score(row)
        assert result["passed"], (variant.name, result)
        assert result["narrative_review_required"] and not result["promotion"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_finding",
        "duplicate_finding",
        "wrong_location",
        "wrong_criterion",
        "missing_gap",
        "duplicate_gap",
        "wrong_gap",
        "substring_gap",
        "full_abstention",
        "scope_summary",
        "wrong_artifact",
        "empirical_claim",
    ],
)
def test_valid_json_cannot_hide_wrong_scope_or_domain(fault):
    case = scenario(32, "train", 0)
    row = example(case, Variant("partial", placement="detached", button="empty"), "it")
    value = json.loads(row["messages"][2]["content"])
    if fault == "missing_finding":
        value["findings"] = []
    elif fault == "duplicate_finding":
        duplicate = deepcopy(value["findings"][0])
        duplicate["finding_id"] = "UTF-002"
        value["findings"].append(duplicate)
    elif fault == "wrong_location":
        value["findings"][0]["location"] = "dom:#" + case.decoy
    elif fault == "wrong_criterion":
        value["findings"][0]["criterion"] = "trust"
    elif fault == "missing_gap":
        value["evidence_gaps"] = []
    elif fault == "duplicate_gap":
        value["evidence_gaps"] *= 2
    elif fault == "wrong_gap":
        value["evidence_gaps"] = ["#" + case.button + " non valutabile"]
    elif fault == "substring_gap":
        value["evidence_gaps"] = ["#" + case.field + "-extra non valutabile"]
    elif fault == "full_abstention":
        value["abstained"] = True
    elif fault == "scope_summary":
        value["overall_summary"] += " #" + case.decoy + " e corretto."
    elif fault == "wrong_artifact":
        value["findings"][0]["artifact_version"] += 1
    elif fault == "empirical_claim":
        value["findings"][0]["epistemic_status"] = "EMPIRICALLY_SUPPORTED"
    assert not score(row, value)["passed"]


@pytest.mark.parametrize(
    "raw", ["not JSON", "[]", '{"findings":null}', '{"abstained":false,"abstained":true}']
)
def test_malformed_outputs_fail_without_being_repaired(raw):
    row = example(scenario(13, "train", 0), VARIANTS[0], "en")
    result = assess(raw, row, eos_finished=True, schema_finished=True)
    assert not result["passed"] and result["errors"]


@pytest.mark.parametrize("flag", ["eos_finished", "schema_finished"])
def test_valid_answer_without_complete_generation_fails(flag):
    row = example(scenario(14, "train", 0), VARIANTS[0], "en")
    assert not score(row, **{flag: False})["passed"]
