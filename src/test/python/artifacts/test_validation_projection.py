from __future__ import annotations

from copy import deepcopy

import pytest

from orchestwin.validation import (
    ValidationError,
    scenario_walkthrough,
    validation_candidates,
    validation_overview,
)


def document():
    def node(key, kind, *, required=False, current=True):
        return {
            "key": key,
            "code": key,
            "kind": kind,
            "title": key,
            "reference": {"artifact_id": key, "version_number": 1, "content_hash": "a" * 64},
            "current": current,
            "validation_required": required,
            "gaps": [],
            "declared_context": {},
        }

    twin = node("twin", "USER_TWIN", required=True)
    claim = node("claim", "USER_TWIN_CLAIM", required=True)
    scenario = node("scenario", "SCENARIO")
    scenario["declared_context"]["scenario"] = {
        "goal": "Synthetic task",
        "steps": ["Open synthetic page", "Read synthetic label"],
        "expected_outcome": "Synthetic expectation",
    }
    element = node("element", "PROTOTYPE_ELEMENT")
    element["declared_context"]["mockup"] = {
        "alternative_id": "alternative",
        "document_hashes": {"it": "b" * 64},
    }
    finding = node("finding", "SYNTHETIC_FINDING")
    return {
        "project_id": "project",
        "nodes": [
            twin,
            claim,
            scenario,
            element,
            finding,
            node("historic", "SYNTHETIC_FINDING", current=False),
        ],
        "links": [
            {"source": "claim", "target": "twin", "kind": "CLAIM_OF"},
            {"source": "scenario", "target": "claim", "kind": "GROUNDED_IN"},
            {"source": "scenario", "target": "twin", "kind": "ACTOR"},
            {"source": "element", "target": "scenario", "kind": "TRACES_TO"},
            {"source": "finding", "target": "element", "kind": "EVALUATES"},
        ],
    }


def records():
    hypothesis = {
        "id": "h",
        "code": "HYP-001",
        "version_number": 1,
        "content_hash": "c" * 64,
        "origin_key": "claim",
        "twin_key": "twin",
        "scenario_key": "scenario",
        "design_key": "element",
        "question": "Synthetic question?",
        "task": None,
    }
    outcome = {
        "id": "o",
        "code": "HVO-001",
        "hypothesis_id": "h",
        "hypothesis_version_number": 1,
        "hypothesis_content_hash": "c" * 64,
        "session_kind": "HUMAN_SESSION",
        "outcome": "CONFIRMED",
        "coverage": "COMPLETE",
        "evidence_id": "e",
        "evidence_version": 1,
        "evidence_content_hash": "d" * 64,
        "citation": {"quote": "Synthetic fixture only"},
    }
    evidence = {
        "evidence": [
            {
                "id": "e",
                "version": 1,
                "content_hash": "d" * 64,
                "status": "ACTIVE",
                "text_available": True,
            }
        ]
    }
    return hypothesis, outcome, evidence


def test_candidates_derive_without_aggregates_history_or_mutation():
    value = document()
    before = deepcopy(value)
    candidates = validation_candidates(value)
    assert [item["key"] for item in candidates] == ["finding", "claim"]
    assert candidates[1]["scenario_candidates"][0]["key"] == "scenario"
    assert candidates[1]["twin_references"][0]["key"] == "twin"
    assert value == before
    assert validation_overview(document=value)["hypotheses"] == []


def test_walkthrough_keeps_scenario_text_and_only_scenario_level_anchors():
    value = scenario_walkthrough(
        document(), "scenario", alternative_id="alternative", document_hash="b" * 64
    )
    assert value["task"] == "Synthetic task"
    assert value["expected_outcome"] == "Synthetic expectation"
    assert [item["text"] for item in value["steps"]] == [
        "Open synthetic page",
        "Read synthetic label",
    ]
    assert [item["key"] for item in value["anchor_candidates"]] == ["element"]
    assert all(
        not item["anchors"] and item["gaps"][0]["code"] == "STEP_ANCHOR_NOT_ATTESTED"
        for item in value["steps"]
    )
    assert not scenario_walkthrough(document(), "scenario", document_hash="e" * 64)[
        "anchor_candidates"
    ]
    with pytest.raises(ValidationError, match="VALIDATION_INPUT_INVALID"):
        scenario_walkthrough(document(), "twin")


def test_walkthrough_code_prefers_unique_current_scenario_and_exact_key_keeps_history():
    value = document()
    current = next(node for node in value["nodes"] if node["kind"] == "SCENARIO")
    current["code"] = "SCN-001"
    current["reference"]["version_number"] = 3
    historical = []
    for number in (1, 2):
        previous = deepcopy(current)
        previous.update(key=f"scenario-v{number}", current=False)
        previous["reference"].update(version_number=number, content_hash=str(number) * 64)
        previous["declared_context"]["scenario"].update(goal=f"Synthetic historical task {number}")
        historical.append(previous)
    value["nodes"].extend(historical)
    before = deepcopy(value)
    selected = scenario_walkthrough(value, "SCN-001")
    assert selected["scenario"]["key"] == current["key"]
    assert selected["reference"]["version_number"] == 3
    old = scenario_walkthrough(value, "scenario-v1")
    assert old["reference"] == historical[0]["reference"]
    assert old["task"] == "Synthetic historical task 1"
    assert any(gap["code"] == "CONTEXT_OUTDATED" for gap in old["gaps"])
    assert value == before


@pytest.mark.parametrize("current", [True, False])
def test_walkthrough_code_rejects_two_current_or_two_historical_matches(current):
    value = document()
    first = next(node for node in value["nodes"] if node["kind"] == "SCENARIO")
    first.update(code="SCN-001", current=current)
    second = deepcopy(first)
    second["key"] = "other-scenario"
    value["nodes"].append(second)
    with pytest.raises(ValidationError, match="VALIDATION_INPUT_INVALID"):
        scenario_walkthrough(value, "SCN-001")


def test_walkthrough_code_accepts_unique_historical_scenario_when_no_current_exists():
    value = document()
    historical = next(node for node in value["nodes"] if node["kind"] == "SCENARIO")
    historical.update(code="SCN-001", current=False)
    result = scenario_walkthrough(value, "SCN-001")
    assert result["scenario"]["key"] == historical["key"]
    assert any(gap["code"] == "CONTEXT_OUTDATED" for gap in result["gaps"])


@pytest.mark.parametrize("retired,deleted", [(True, False), (True, True)])
def test_retirement_and_body_deletion_keep_outcome_history_and_reopen_hypothesis(retired, deleted):
    hypothesis, outcome, evidence = records()
    evidence["evidence"][0].update(
        status="RETIRED" if retired else "ACTIVE", text_available=not deleted
    )
    result = validation_overview(
        document=document(), hypotheses=[hypothesis], outcomes=[outcome], evidence=evidence
    )
    assert result["hypotheses"][0]["state"] == "TO_VERIFY"
    assert result["outcomes"][0]["effective_status"] == "RETIRED"
    assert result["outcomes"][0]["outcome"] == "CONFIRMED"
    assert result["outcomes"][0]["citation"] == outcome["citation"]
    assert result["summary"]["retired_outcomes"] == 1
    assert "effective_status" not in outcome


def test_retired_source_does_not_cancel_independent_active_outcome():
    hypothesis, outcome, evidence = records()
    evidence["evidence"][0]["status"] = "RETIRED"
    evidence["evidence"].append({**evidence["evidence"][0], "id": "e2", "status": "ACTIVE"})
    result = validation_overview(
        document=document(),
        hypotheses=[hypothesis],
        outcomes=[outcome, {**outcome, "id": "o2", "evidence_id": "e2"}],
        evidence=evidence,
    )
    assert result["hypotheses"][0]["state"] == "CONFIRMED"
    assert result["hypotheses"][0]["active_outcome_ids"] == ["o2"]


def test_synthetic_owner_decisions_and_old_version_do_not_validate_current_hypothesis():
    hypothesis, outcome, evidence = records()
    value = document()
    value["nodes"][4]["declared_context"]["owner_decision"] = {"decision": "OWNER_CONFIRMED"}
    result = validation_overview(
        document=value,
        hypotheses=[hypothesis, {**hypothesis, "version_number": 2, "content_hash": "f" * 64}],
        outcomes=[{**outcome, "session_kind": "SYNTHETIC_EXERCISE"}],
        evidence=evidence,
    )
    assert all(item["state"] == "TO_VERIFY" for item in result["hypotheses"])
    assert result["empirical_summary"] == {
        "human_session_outcomes": 0,
        "synthetic_exercise_outcomes": 1,
    }
    assert result["hypotheses"][1]["outcomes"] == []


@pytest.mark.parametrize(
    "outcome_value,coverage,expected",
    [
        ("UNCERTAIN", "COMPLETE", "UNCERTAIN"),
        ("CONFIRMED", "PARTIAL", "UNCERTAIN"),
        ("REFUTED", "COMPLETE", "CONTESTED"),
    ],
)
def test_uncertainty_partial_and_disagreement_remain_explicit(outcome_value, coverage, expected):
    hypothesis, outcome, evidence = records()
    second = {
        **outcome,
        "id": "o2",
        "code": "HVO-002",
        "outcome": outcome_value,
        "coverage": coverage,
    }
    result = validation_overview(
        document=document(), hypotheses=[hypothesis], outcomes=[outcome, second], evidence=evidence
    )
    assert result["hypotheses"][0]["state"] == expected
    assert len(result["hypotheses"][0]["outcomes"]) == 2


def test_imported_active_source_without_body_is_not_retired():
    hypothesis, outcome, evidence = records()
    evidence["evidence"][0]["text_available"] = False
    result = validation_overview(
        document=document(), hypotheses=[hypothesis], outcomes=[outcome], evidence=evidence
    )
    assert result["hypotheses"][0]["state"] == "CONFIRMED"
    assert result["outcomes"][0]["effective_status"] == "ACTIVE"
    assert result["outcomes"][0]["gaps"] == [{"code": "SOURCE_TEXT_UNAVAILABLE"}]
