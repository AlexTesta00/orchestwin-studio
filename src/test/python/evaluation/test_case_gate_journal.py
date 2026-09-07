from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.case_gate_journal import (
    ObservedGateDecision,
    append_gate_decision,
    create_gate_journal,
    load_gate_journal,
    write_gate_journal,
)
from orchestwin.evaluation.case_launch_inputs import FormalGateType

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000041001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000041002")
GATE_ID = UUID("00000000-0000-4000-8000-000000041003")
EVENT_ID = UUID("00000000-0000-4000-8000-000000041004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000041005")
NOW = datetime(2026, 9, 7, 18, 30, tzinfo=UTC)


def _decision() -> ObservedGateDecision:
    return ObservedGateDecision(
        gate_type=FormalGateType.PROJECT_BRIEF,
        gate_id=GATE_ID,
        source_event_id=EVENT_ID,
        sequence_number=2,
        action="APPROVE",
        resulting_status="APPROVED",
        artifact_id=ARTIFACT_ID,
        artifact_version=1,
        artifact_content_hash="a" * 64,
        actor_user_id=OWNER_ID,
        occurred_at=NOW,
        source_snapshot_sha256="b" * 64,
    )


def test_gate_journal_appends_only_content_addressed_observations(tmp_path) -> None:
    journal = create_gate_journal(case_id="web-calculator", workflow_run_id=WORKFLOW_RUN_ID)
    updated = append_gate_decision(journal, _decision())
    path = tmp_path / "gate-journal.json"
    write_gate_journal(path, updated)

    loaded = load_gate_journal(path)

    assert loaded == updated
    assert loaded.observations[0].resulting_status == "APPROVED"
    assert loaded.real_user_behavior_validated is False
    assert loaded.empirical_user_evidence_created is False


def test_gate_journal_rejects_duplicate_source_event_ids() -> None:
    journal = create_gate_journal(case_id="web-calculator", workflow_run_id=WORKFLOW_RUN_ID)
    once = append_gate_decision(journal, _decision())

    with pytest.raises(ValueError, match="source event IDs must be unique"):
        append_gate_decision(once, _decision())
