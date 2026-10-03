from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.workflow_inputs import (
    PROVIDED_PROTOTYPE_LIMIT_MESSAGES,
    PROVIDED_PROTOTYPE_LIMITS,
    WORKFLOW_ACTIONS,
    WORKFLOW_TARGETS,
    WorkflowInputError,
    create_workflow_decision,
    decision_content_hash,
    validate_workflow_records,
    workflow_records,
)

PROJECT_ID = UUID("c22a89a3-4aee-47f9-bd2b-ff541e517e70")
DECISION_ID = UUID("92a91a22-6751-4479-8aef-2718ca72eeaf")
MOMENT = datetime(2026, 10, 3, 15, 40, tzinfo=UTC)
REFERENCE = {
    "artifact_id": "26a781d3-45fd-490c-bd2b-ff541e517e70",
    "version_number": 1,
    "content_hash": "a" * 64,
}


def decision(**changes):
    values = {
        "decision_id": DECISION_ID,
        "project_id": PROJECT_ID,
        "sequence": 1,
        "target": "EVIDENCE",
        "action": "DECLARE_MISSING",
        "reason": "Non abbiamo ancora osservazioni.",
        "base_context": {"BRIEF": REFERENCE},
        "recorded_at": MOMENT,
    }
    return create_workflow_decision(**(values | changes))


def test_envelope_preserves_existing_records_and_detaches_mutable_input():
    source = decision()
    envelope = workflow_records(PROJECT_ID, [source])
    assert envelope == {
        "kind": "orchestwin.workflow-inputs",
        "schema_version": 1,
        "project_id": str(PROJECT_ID),
        "decisions": [source],
        "prototypes": [],
        "limits": [],
    }
    envelope["decisions"][0]["base_context"]["BRIEF"]["version_number"] = 8
    assert source["base_context"]["BRIEF"]["version_number"] == 1


def test_decision_hash_matches_existing_canonical_json_without_unicode_normalization():
    source = decision(reason="Una e\u0301 accentata\r\nSeconda riga\rTerza")
    assert source["reason"] == "Una e\u0301 accentata\nSeconda riga\nTerza"
    content = {key: value for key, value in source.items() if key != "content_hash"}
    serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert source["content_hash"] == hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert decision(reason="é")["content_hash"] != decision(reason="e\u0301")["content_hash"]


@pytest.mark.parametrize("target", WORKFLOW_TARGETS)
@pytest.mark.parametrize("action", WORKFLOW_ACTIONS)
def test_every_declared_target_and_action_has_a_valid_owner_record(target, action):
    source = decision(target=target, action=action)
    assert validate_workflow_records(workflow_records(PROJECT_ID, [source]))["decisions"] == [
        source
    ]


def test_import_origin_keeps_original_identity_and_hash():
    origin = {"project_id": str(PROJECT_ID), "id": str(DECISION_ID), "content_hash": "b" * 64}
    source = decision(origin_reference=origin)
    result = validate_workflow_records(
        json.loads(json.dumps(workflow_records(PROJECT_ID, [source])))
    )
    assert result["decisions"][0] == source
    assert result["decisions"][0]["origin_reference"] == origin


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"target": "DEFINITION"}, "WORKFLOW_TARGET_INVALID"),
        ({"action": "SKIP"}, "WORKFLOW_ACTION_INVALID"),
        ({"reason": "  "}, "WORKFLOW_REASON_INVALID"),
        ({"reason": "a\x00b"}, "WORKFLOW_REASON_INVALID"),
        ({"reason": "a" * 4001}, "WORKFLOW_REASON_INVALID"),
        ({"sequence": True}, "WORKFLOW_RECORDS_INVALID"),
        ({"recorded_at": datetime(2026, 10, 3)}, "WORKFLOW_RECORDS_INVALID"),
        (
            {"base_context": {"BRIEF": {**REFERENCE, "version_number": True}}},
            "WORKFLOW_RECORDS_INVALID",
        ),
        (
            {"base_context": {"BRIEF": {**REFERENCE, "content_hash": "xyz"}}},
            "WORKFLOW_RECORDS_INVALID",
        ),
    ],
)
def test_invalid_owner_input_is_rejected_with_explicit_code(changes, code):
    with pytest.raises(WorkflowInputError) as caught:
        decision(**changes)
    assert caught.value.code == code


def test_mutated_record_is_rejected_even_when_the_envelope_is_well_formed():
    envelope = workflow_records(PROJECT_ID, [decision()])
    envelope["decisions"][0]["reason"] = "Modificata"
    with pytest.raises(WorkflowInputError) as caught:
        validate_workflow_records(envelope)
    assert caught.value.code == "WORKFLOW_HASH_MISMATCH"


def test_foreign_project_and_duplicate_sequence_are_rejected():
    source = decision()
    foreign = deepcopy(source)
    foreign["project_id"] = "ad3d8416-e9b5-46d7-883c-3f5dbf63119a"
    foreign["content_hash"] = decision_content_hash(foreign)
    with pytest.raises(WorkflowInputError) as caught:
        workflow_records(PROJECT_ID, [foreign])
    assert caught.value.code == "WORKFLOW_PROJECT_MISMATCH"
    with pytest.raises(WorkflowInputError):
        workflow_records(PROJECT_ID, [source, source])


def test_validation_does_not_rewrite_a_noncanonical_reason_and_its_hash():
    source = decision()
    source["reason"] = "Prima\r\nSeconda"
    source["content_hash"] = decision_content_hash(source)
    with pytest.raises(WorkflowInputError) as caught:
        workflow_records(PROJECT_ID, [source])
    assert caught.value.code == "WORKFLOW_REASON_INVALID"


@pytest.mark.parametrize("value", [True, 0, 2])
def test_schema_versions_are_explicit(value):
    envelope = workflow_records(PROJECT_ID)
    envelope["schema_version"] = value
    with pytest.raises(WorkflowInputError):
        validate_workflow_records(envelope)


def test_all_consumer_limit_codes_have_shared_italian_and_english_messages():
    for language in ("it", "en"):
        assert set(PROVIDED_PROTOTYPE_LIMIT_MESSAGES[language]) == set(PROVIDED_PROTOTYPE_LIMITS)
        assert all(PROVIDED_PROTOTYPE_LIMIT_MESSAGES[language].values())
