from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.artifacts.human_validation import (
    HypothesisVersion,
    create_hypothesis,
    create_outcome,
    hypothesis_from_snapshot,
    outcome_from_snapshot,
)
from orchestwin.artifacts.human_validation_persistence import SqlAlchemyHumanValidationRepository
from orchestwin.projects.research_evidence import EvidenceStatus
from orchestwin.validation import ValidationError, validation_overview
from orchestwin.why import build_why_document, explain_why
from src.test.python.artifacts.test_validation_projection import document
from src.test.python.projects.test_research_evidence import source

PROJECT = UUID(int=3501)
OWNER = UUID(int=3502)
NOW = datetime(2026, 10, 3, 10, tzinfo=UTC)
TEXT = "Ω synthetic fixture\nè exact synthetic observation\nNo participants."


def request():
    return {
        "candidate_key": "claim",
        "twin_key": "twin",
        "scenario_key": "scenario",
        "design_key": "element",
        "question": "Can the synthetic task be completed?",
        "task": None,
        "observe": ["Synthetic task completion"],
        "limitations": "Synthetic fixture only; no participants.",
    }


def hypothesis(*, changes=None):
    value = document()
    value["project_id"] = str(PROJECT)
    return create_hypothesis(
        document=value,
        project_id=PROJECT,
        owner_user_id=OWNER,
        request={**request(), **(changes or {})},
        code="HYP-001",
        created_at=NOW,
    )


def outcome_request(hypothesis, evidence):
    return {
        "hypothesis_id": str(hypothesis.id),
        "hypothesis_version_number": hypothesis.version_number,
        "hypothesis_content_hash": hypothesis.content_hash,
        "session_ref": "SES-001",
        "session_kind": "HUMAN_SESSION",
        "outcome": "CONFIRMED",
        "coverage": "COMPLETE",
        "limitations": "Synthetic contract fixture; no actual human session.",
        "evidence_id": str(evidence.id),
        "evidence_version": evidence.version,
        "quote": "è exact synthetic observation",
        "line": 2,
    }


def outcome(*, changes=None, evidence=None, text=TEXT):
    chosen = hypothesis()
    evidence = evidence or source(TEXT, empirical=True)
    return create_outcome(
        hypothesis=chosen,
        source=evidence,
        text=text,
        project_id=PROJECT,
        owner_user_id=OWNER,
        request={**outcome_request(chosen, evidence), **(changes or {})},
        code="HVO-001",
        recorded_at=NOW,
    )


def test_selected_completed_hypothesis_is_canonical_immutable_and_versioned():
    record = hypothesis()
    payload = record.to_snapshot()
    assert hypothesis_from_snapshot(payload) == record
    payload["question"] = "Changed externally"
    assert record.to_snapshot()["question"] == request()["question"]
    with pytest.raises(ValidationError, match="VALIDATION_STORED_SNAPSHOT_INVALID"):
        hypothesis_from_snapshot(payload)
    with pytest.raises(ValidationError):
        HypothesisVersion(record.snapshot_json + " ")
    value = document()
    value["project_id"] = str(PROJECT)
    revised = create_hypothesis(
        document=value,
        project_id=PROJECT,
        owner_user_id=OWNER,
        request={**request(), "question": "A revised synthetic question?"},
        code=record.to_snapshot()["code"],
        created_at=NOW,
        hypothesis_id=record.id,
        version_number=2,
        based_on_version_number=1,
    )
    assert revised.id == record.id and revised.content_hash != record.content_hash
    assert revised.to_snapshot()["based_on_version_number"] == 1


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"question": "", "task": None}, "VALIDATION_INPUT_INVALID"),
        ({"observe": []}, "VALIDATION_INPUT_INVALID"),
        ({"candidate_key": "twin"}, "VALIDATION_CONTEXT_CHANGED"),
        ({"scenario_key": "missing"}, "VALIDATION_CONTEXT_CHANGED"),
        ({"candidate_key": []}, "VALIDATION_INPUT_INVALID"),
        ({"anchor_keys": [{}]}, "VALIDATION_INPUT_INVALID"),
    ],
)
def test_incomplete_or_unselected_hypothesis_and_invalid_references_are_rejected(changes, code):
    with pytest.raises(ValidationError, match=code):
        hypothesis(changes=changes)


def test_task_alone_and_owner_selected_existing_scenario_are_allowed():
    record = hypothesis(changes={"question": None, "task": "Perform the synthetic task"})
    assert record.to_snapshot()["task"] == "Perform the synthetic task"
    assert record.to_snapshot()["question"] is None


def test_exact_unicode_citation_is_calculated_by_studio_and_retained():
    record = outcome()
    payload = record.to_snapshot()
    assert payload["citation"]["start"] == TEXT.index("è exact")
    assert payload["citation"]["start_line"] == payload["citation"]["end_line"] == 2
    assert outcome_from_snapshot(payload) == record
    assert "text" not in payload and "method" not in payload


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"line": 1}, "VALIDATION_CITATION_INVALID"),
        ({"quote": "invented observation"}, "VALIDATION_CITATION_INVALID"),
        ({"session_ref": "participant@example.invalid"}, "VALIDATION_INPUT_INVALID"),
        ({"outcome": "OWNER_CONFIRMED"}, "VALIDATION_INPUT_INVALID"),
        ({"hypothesis_version_number": 2}, "HYPOTHESIS_VERSION_CONFLICT"),
        ({"evidence_version": True}, "VALIDATION_INPUT_INVALID"),
    ],
)
def test_outcome_rejects_wrong_version_owner_decision_or_unverified_citation(changes, expected):
    with pytest.raises(ValidationError, match=expected):
        outcome(changes=changes)


def test_repeated_quote_on_one_line_is_ambiguous():
    text = "same same"
    evidence = source(text, empirical=True)
    with pytest.raises(ValidationError, match="VALIDATION_CITATION_INVALID"):
        outcome(evidence=evidence, text=text, changes={"quote": "same", "line": 1})


@pytest.mark.parametrize("field", ["session_kind", "outcome", "coverage"])
@pytest.mark.parametrize("value", [[], {}, None, True, 1])
def test_structured_outcome_fields_are_input_errors_without_typeerror(field, value):
    with pytest.raises(ValidationError, match="VALIDATION_INPUT_INVALID"):
        outcome(changes={field: value})


def test_source_nature_is_explicit_and_active_text_required_for_new_outcome():
    nonempirical = source(TEXT)
    with pytest.raises(ValidationError, match="VALIDATION_SESSION_SOURCE_INVALID"):
        outcome(evidence=nonempirical)
    assert (
        outcome(
            evidence=nonempirical, changes={"session_kind": "SYNTHETIC_EXERCISE"}
        ).to_snapshot()["session_kind"]
        == "SYNTHETIC_EXERCISE"
    )
    with pytest.raises(ValidationError, match="VALIDATION_SESSION_SOURCE_INVALID"):
        outcome(changes={"session_kind": "SYNTHETIC_EXERCISE"})
    with pytest.raises(ValidationError, match="VALIDATION_SOURCE_RETIRED"):
        outcome(evidence=replace(nonempirical, status=EvidenceStatus.RETIRED, retired_at=NOW))
    with pytest.raises(ValidationError, match="VALIDATION_SOURCE_TEXT_UNAVAILABLE"):
        outcome(text=None)


def test_repository_rechecks_actual_source_nature_for_imported_human_outcome():
    record = outcome()
    metadata = source(TEXT).to_snapshot()

    class Session:
        def __init__(self):
            self.results = iter([PROJECT, record.id, metadata])
            self.writes = []

        async def scalar(self, _statement):
            return next(self.results)

        async def execute(self, statement):
            self.writes.append(statement)

    session = Session()
    with pytest.raises(ValidationError, match="VALIDATION_SESSION_SOURCE_INVALID"):
        asyncio.run(
            SqlAlchemyHumanValidationRepository(session, owner_user_id=OWNER).append_outcome(record)
        )
    assert session.writes == []


def test_why_outcome_source_chain_is_derived_without_promoting_a_twin_claim():
    from src.test.python.artifacts.design_fixtures import design_version
    from src.test.python.artifacts.test_why import chain

    stages, evidence, _, _ = chain()
    design_version_value = design_version()
    stages["design"] = {
        "id": str(design_version_value.id),
        "version_number": design_version_value.version_number,
        "content_hash": design_version_value.content_hash,
        "package": design_version_value.package.to_snapshot(),
    }
    original = build_why_document(project_id=str(PROJECT), stages=stages, evidence=evidence)
    claim = next(
        node
        for node in original["nodes"]
        if node["kind"] == "USER_TWIN_CLAIM" and node["code"].endswith("user_twin.goals")
    )
    twin = next(node for node in original["nodes"] if node["kind"] == "USER_TWIN")
    scenario = next(node for node in original["nodes"] if node["kind"] == "SCENARIO")
    design = next(node for node in original["nodes"] if node["kind"] == "DESIGN_ALTERNATIVE")
    hyp = create_hypothesis(
        document=original,
        project_id=PROJECT,
        owner_user_id=OWNER,
        request={
            **request(),
            "candidate_key": claim["key"],
            "twin_key": twin["key"],
            "scenario_key": scenario["key"],
            "design_key": design["key"],
        },
        code="HYP-001",
        created_at=NOW,
    )
    source_metadata = source(TEXT, empirical=True)
    result = create_outcome(
        hypothesis=hyp,
        source=source_metadata,
        text=TEXT,
        project_id=PROJECT,
        owner_user_id=OWNER,
        request={**outcome_request(hyp, source_metadata), "outcome": "REFUTED"},
        code="HVO-001",
        recorded_at=NOW,
    )
    evidence["evidence"].append(source_metadata.to_snapshot())
    why = build_why_document(
        project_id=str(PROJECT),
        stages=stages,
        evidence=evidence,
        hypotheses=[hyp.to_snapshot()],
        outcomes=[result.to_snapshot()],
    )
    answer = explain_why(why, "HVO-001")
    assert answer["summary"]["complete_to_evidence"]
    assert any(
        node["kind"] == "RESEARCH_EVIDENCE"
        and node["reference"]["artifact_id"] == str(source_metadata.id)
        for node in answer["upstream"]
    )
    assert next(node for node in why["nodes"] if node["key"] == claim["key"]) == claim
    assert not any(
        node["validation_required"]
        for node in why["nodes"]
        if node["kind"].startswith("VALIDATION_")
    )
    evidence["evidence"][-1].update(status="RETIRED", text_available=False)
    withdrawn = build_why_document(
        project_id=str(PROJECT),
        stages=stages,
        evidence=evidence,
        hypotheses=[hyp.to_snapshot()],
        outcomes=[result.to_snapshot()],
    )
    summary = validation_overview(
        document=withdrawn, hypotheses=[hyp.to_snapshot()], outcomes=[result.to_snapshot()]
    )
    assert summary["hypotheses"][0]["state"] == "TO_VERIFY"
    answer = explain_why(withdrawn, "HVO-001")
    assert "SOURCE_RETIRED" in answer["limits"]
    assert not answer["summary"]["complete_to_evidence"]
    assert not answer["summary"]["all_paths_complete"]
