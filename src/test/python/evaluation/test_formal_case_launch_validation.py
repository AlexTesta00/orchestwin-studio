from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_gate_journal import (
    ObservedGateDecision,
    append_gate_decision,
    create_gate_journal,
)
from orchestwin.evaluation.case_launch_inputs import (
    REQUIRED_FORMAL_GATES,
    load_formal_case_launch_input,
)
from orchestwin.evaluation.case_launch_validation import (
    verify_formal_case_launch_configuration,
    verify_gate_journal_complete,
)

RUN_ID = UUID("00000000-0000-4000-8000-000000050001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000050002")
START = datetime(2026, 9, 7, 20, 0, tzinfo=UTC)


def test_all_formal_launch_inputs_match_frozen_case_definitions() -> None:
    repo_root = Path(__file__).resolve().parents[4]

    summary = verify_formal_case_launch_configuration(repo_root)

    assert summary.case_ids == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert summary.execution_profiles == ("WEB_STATIC", "WEB_VUE_NODE", "WEB_VUE_NODE")
    assert summary.technology_union == (
        "CSS",
        "Express",
        "HTML",
        "JavaScript",
        "Node.js",
        "Vue",
    )
    assert summary.required_gate_count == 8
    assert summary.mobile_scope_present is False
    assert summary.php_in_scope is False
    assert summary.ready_for_observed_execution is True


def test_gate_completion_requires_observed_approvals_for_all_eight_gates() -> None:
    repo_root = Path(__file__).resolve().parents[4]
    launch = load_formal_case_launch_input(
        repo_root / "experiments" / "case-studies" / "run-inputs" / "web-calculator-v1.json"
    )
    journal = create_gate_journal(case_id=launch.case_id, workflow_run_id=RUN_ID)

    with pytest.raises(ValueError, match="incomplete"):
        verify_gate_journal_complete(launch, journal)

    for index, gate in enumerate(REQUIRED_FORMAL_GATES):
        journal = append_gate_decision(
            journal,
            ObservedGateDecision(
                gate_type=gate,
                gate_id=UUID(int=0x500100 + index),
                source_event_id=UUID(int=0x500200 + index),
                sequence_number=2,
                action="APPROVE",
                resulting_status="APPROVED",
                artifact_id=UUID(int=0x500300 + index),
                artifact_version=1,
                artifact_content_hash=f"{index + 1:064x}",
                actor_user_id=OWNER_ID,
                occurred_at=START + timedelta(minutes=index),
                source_snapshot_sha256=f"{index + 101:064x}",
            ),
        )

    verify_gate_journal_complete(launch, journal)
