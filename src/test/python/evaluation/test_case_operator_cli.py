from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_operator_cli import main

PROJECT_ID = UUID("00000000-0000-4000-8000-000000049001")
RUN_ID = UUID("00000000-0000-4000-8000-000000049002")


def test_operator_cli_shows_frozen_input(capsys) -> None:
    repo_root = Path(__file__).resolve().parents[4]

    assert main(["show-input", "--repo-root", str(repo_root), "--case-id", "web-calculator"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["case_id"] == "web-calculator"
    assert payload["execution_profile"] == "WEB_STATIC"


def test_operator_cli_initializes_existing_workspace(tmp_path, capsys) -> None:
    repo_root = Path(__file__).resolve().parents[4]
    workspace = tmp_path / "workspace"
    for name in ("evidence", "raw", "final"):
        (workspace / name).mkdir(parents=True, exist_ok=True)

    assert (
        main(
            [
                "initialize",
                "--repo-root",
                str(repo_root),
                "--workspace-root",
                str(workspace),
                "--case-id",
                "web-calculator",
                "--project-id",
                str(PROJECT_ID),
                "--workflow-run-id",
                str(RUN_ID),
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PREPARED"
    assert payload["observed_result_available"] is False
