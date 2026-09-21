from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_launch_inputs import load_formal_case_launch_input
from orchestwin.evaluation.case_operator_workspace import initialize_case_operator_session

PROJECT_ID = UUID("00000000-0000-4000-8000-000000048001")
RUN_ID = UUID("00000000-0000-4000-8000-000000048002")
NOW = datetime(2026, 9, 7, 19, 15, tzinfo=UTC)


def test_operator_session_initializes_existing_workspace_without_claiming_result(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    launch = load_formal_case_launch_input(
        repo_root / "experiments" / "case-studies" / "run-inputs" / "web-calculator-v1.json"
    )
    workspace = tmp_path / "workspace"
    for name in ("evidence", "raw", "final"):
        (workspace / name).mkdir(parents=True, exist_ok=True)

    session = initialize_case_operator_session(
        workspace_root=workspace,
        launch=launch,
        project_id=PROJECT_ID,
        workflow_run_id=RUN_ID,
        prepared_at=NOW,
    )

    assert session.status == "PREPARED"
    assert session.observed_result_available is False
    assert (workspace / "raw" / "launch-input.json").exists()
    assert (workspace / "raw" / "gate-journal.json").exists()
    persisted = json.loads((workspace / "raw" / "operator-session.json").read_text())
    assert persisted["owner_gates_required"] is True
    assert persisted["observed_result_available"] is False
