from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.artifacts.design_finding_validations import (
    MAX_FINDING_NOTE_LENGTH,
    FindingDecision,
    create_finding_validation,
    dismissed_finding_keys,
    finding_source_id,
    finding_source_key,
    finding_validation_from_snapshot,
    normalize_finding_note,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash

RUN_ID = UUID("00000000-0000-4000-8000-000000000901")
TWIN_A = UUID("00000000-0000-4000-8000-000000000911")
TWIN_B = UUID("00000000-0000-4000-8000-000000000912")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


def values(**changes):
    return {
        "evaluation_run_id": RUN_ID,
        "twin_id": TWIN_A,
        "finding_id": "UTF-001",
        "sequence_number": 1,
        "project_id": PROJECT_ID,
        "owner_user_id": OWNER_ID,
        "decision": FindingDecision.OWNER_DISMISSED,
        "note": None,
        "decided_at": NOW,
        **changes,
    }


def decide(decision, *, minutes=0, **changes):
    return create_finding_validation(
        **values(decision=decision, decided_at=NOW + timedelta(minutes=minutes), **changes)
    )


def test_owner_decisions_are_governance_choices_only():
    assert [item.value for item in FindingDecision] == ["OWNER_CONFIRMED", "OWNER_DISMISSED"]


def test_snapshot_names_every_field_and_hashes_its_semantic_part():
    validation = decide(FindingDecision.OWNER_DISMISSED, note="  Out   of\nscope  ")
    snapshot = validation.to_snapshot()
    assert snapshot == {
        "evaluation_run_id": str(RUN_ID),
        "twin_id": str(TWIN_A),
        "finding_id": "UTF-001",
        "sequence_number": 1,
        "project_id": str(PROJECT_ID),
        "owner_user_id": str(OWNER_ID),
        "decision": "OWNER_DISMISSED",
        "note": "Out of scope",
        "decided_at": NOW.isoformat(),
        "content_hash": validation.content_hash,
    }
    assert validation.semantic_snapshot() == {
        key: value for key, value in snapshot.items() if key != "content_hash"
    }
    assert validation.content_hash == snapshot_content_hash(validation.semantic_snapshot())
    assert validation.key == (RUN_ID, TWIN_A, "UTF-001")
    assert finding_validation_from_snapshot(snapshot) == validation
    assert create_finding_validation(**values(decision="OWNER_CONFIRMED")).decision is (
        FindingDecision.OWNER_CONFIRMED
    )


def test_snapshots_must_stay_canonical():
    snapshot = decide(FindingDecision.OWNER_CONFIRMED).to_snapshot()
    with pytest.raises(ValueError, match="hash is inconsistent"):
        finding_validation_from_snapshot({**snapshot, "decision": "OWNER_DISMISSED"})
    for changed in ({"sequence_number": "1"}, {"reviewer": "someone"}):
        with pytest.raises(ValueError, match="not canonical"):
            finding_validation_from_snapshot({**snapshot, **changed})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"finding_id": "UTF-01"}, "UTF-NNN"),
        ({"finding_id": "UTF-1234567"}, "UTF-NNN"),
        ({"finding_id": "REQ-001"}, "UTF-NNN"),
        ({"sequence_number": 0}, "positive"),
        ({"sequence_number": True}, "positive"),
        ({"decision": "USER_VALIDATED"}, "not a valid FindingDecision"),
        ({"note": "   "}, "must not be empty"),
        ({"note": "x" * (MAX_FINDING_NOTE_LENGTH + 1)}, "maximum length"),
        ({"decided_at": datetime(2026, 9, 27, 9, 0)}, "timezone-aware"),
    ],
)
def test_invalid_validations_are_refused(changes, message):
    with pytest.raises(ValueError, match=message):
        create_finding_validation(**values(**changes))


def test_direct_construction_keeps_the_hash_and_the_note_honest():
    validation = decide(FindingDecision.OWNER_CONFIRMED, note="Keep it")
    with pytest.raises(ValueError, match="hash is inconsistent"):
        replace(validation, note="Changed")
    with pytest.raises(ValueError, match="must be normalized"):
        replace(validation, note=" Keep it ")
    with pytest.raises(ValueError, match="must be a FindingDecision"):
        replace(validation, decision="OWNER_CONFIRMED")


def test_notes_are_optional_normalized_and_bounded():
    longest = "x" * MAX_FINDING_NOTE_LENGTH
    assert normalize_finding_note(None) is None
    assert normalize_finding_note(" a \n\t b ") == "a b"
    assert normalize_finding_note(longest) == longest
    assert decide(FindingDecision.OWNER_CONFIRMED, note=longest).note == longest
    assert normalize_finding_note("word  " * 200) == " ".join(["word"] * 200)
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_finding_note("")


def test_only_the_latest_decision_of_each_finding_counts():
    history = [
        decide(FindingDecision.OWNER_DISMISSED, sequence_number=2, minutes=2),
        decide(FindingDecision.OWNER_CONFIRMED),
        decide(FindingDecision.OWNER_DISMISSED, twin_id=TWIN_B),
        decide(FindingDecision.OWNER_DISMISSED, finding_id="UTF-002"),
        decide(FindingDecision.OWNER_CONFIRMED, finding_id="UTF-002", sequence_number=2, minutes=1),
    ]
    expected = {(RUN_ID, TWIN_A, "UTF-001"), (RUN_ID, TWIN_B, "UTF-001")}
    assert dismissed_finding_keys(history) == expected
    assert dismissed_finding_keys(reversed(history)) == expected
    assert isinstance(dismissed_finding_keys(history), frozenset)
    assert dismissed_finding_keys(()) == frozenset()


def test_synthetic_finding_sources_are_recognised_only_in_the_canonical_form():
    source = finding_source_id(RUN_ID, TWIN_A, "UTF-001")
    assert source == f"run:{RUN_ID}:{TWIN_A}:UTF-001"
    assert finding_source_key(source) == (RUN_ID, TWIN_A, "UTF-001")
    assert finding_source_key(f" run:{str(RUN_ID).upper()}:{TWIN_A}:UTF-001 ") == (
        RUN_ID,
        TWIN_A,
        "UTF-001",
    )
    for other in (
        "run:1:UTF-001",
        f"run:{RUN_ID}:UTF-001",
        f"run:{RUN_ID}:{TWIN_A}:UTF-1",
        f"run:{RUN_ID}:{TWIN_A}:UTF-001:extra",
        f"{RUN_ID}:{TWIN_A}:UTF-001",
        "chat:turn-7",
    ):
        assert finding_source_key(other) is None
