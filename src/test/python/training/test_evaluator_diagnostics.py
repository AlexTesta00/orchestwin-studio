"""Guard against label leakage, changed facts and stale native artifact digests."""

import copy
import json

import pytest

from orchestwin.training.evaluator_assessment import request_for
from orchestwin.training.evaluator_diagnostics import observed_states, variant
from orchestwin.training.scoped_interface_curriculum import example
from orchestwin.training.scoped_interface_fixtures import Variant, scenario


def source(locale="en", placement="inside"):
    row = example(
        scenario(719, "validation", 1),
        Variant("external-label", placement=placement, button="empty"),
        locale,
    )
    row["condition"] = "external-label"
    row["control_judgements"] = [
        {k: c[k] for k in ("target", "family", "state")} for c in row["control_judgements"]
    ]
    return row


@pytest.mark.parametrize("locale", ["en", "it"])
@pytest.mark.parametrize(
    "factor", ["original", "rename_ids", "explicit_decision_rules", "html_quotes"]
)
def test_variant_preserves_facts_and_native_provenance_without_gold_answer(locale, factor):
    row = source(locale)
    original = copy.deepcopy(row)
    result = variant(row, factor)
    assert row == original
    assert [m["role"] for m in result["messages"]] == ["system", "user"]
    assert observed_states(result) == result["control_judgements"]
    assert [c["state"] for c in result["control_judgements"]] == [
        c["state"] for c in row["control_judgements"]
    ]
    request_for(result)
    before, after = (json.loads(r["messages"][1]["content"]) for r in (row, result))
    assert before["output_schema"] == after["output_schema"]
    assert before["input"]["user_twin"] == after["input"]["user_twin"]
    assert "control_judgements" not in after["input"]
    if factor == "original":
        assert result["messages"] == row["messages"][:2]
    elif factor == "explicit_decision_rules":
        assert (
            before["input"]["verified_artifact_content"]["items"]
            == after["input"]["verified_artifact_content"]["items"]
        )
    else:
        assert (
            before["input"]["artifact_bundle"]["artifacts"][0]["sha256_digest"]
            != after["input"]["artifact_bundle"]["artifacts"][0]["sha256_digest"]
        )


def test_detached_label_remains_unassessable_when_ids_change():
    row = source(placement="detached")
    result = variant(row, "rename_ids")
    assert result["control_judgements"][0]["state"] == "INSUFFICIENT"
    assert result["control_judgements"][0]["target"] != row["control_judgements"][0]["target"]
    assert result["control_judgements"][1]["state"] == "MISSING"


def test_wrong_gold_is_rejected_before_creating_a_contrast():
    row = source()
    row["control_judgements"][1]["state"] = "PRESENT"
    with pytest.raises(ValueError, match="source labels"):
        variant(row, "html_quotes")


@pytest.mark.parametrize("factor", ["unknown", "neutral_page_text", "summary_sentence"])
def test_inapplicable_intervention_is_rejected_instead_of_becoming_a_noop(factor):
    with pytest.raises(ValueError):
        variant(source(), factor)
