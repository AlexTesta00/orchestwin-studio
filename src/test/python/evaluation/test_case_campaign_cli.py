"""Tests for the formal case preparation and finalization CLI application layer."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_campaign_cli import main, prepare_formal_case_run
from orchestwin.evaluation.case_environment import CaseStudyRuntimeVersion
from orchestwin.evaluation.case_environment_io import load_case_study_environment_identity
from orchestwin.evaluation.case_preflight import CaseExecutionHostState
from orchestwin.evaluation.case_workspace import load_case_study_run_request

REPO_ROOT = Path(__file__).resolve().parents[4]
BRANCH = "sprint/12-case-studies-expert-evaluation"
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000012901")


def _prepared(tmp_path):
    host = CaseExecutionHostState(
        platform_commit="7" * 40,
        branch=BRANCH,
        worktree_clean=True,
        available_execution_profiles=("WEB_STATIC", "WEB_VUE_NODE"),
    )
    return prepare_formal_case_run(
        repo_root=REPO_ROOT,
        artifact_root=tmp_path,
        host=host,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=datetime(2026, 9, 7, 17, 0, tzinfo=UTC),
        expected_branch=BRANCH,
        runtime_versions=(CaseStudyRuntimeVersion(component="Node.js", version="24.0.0"),),
        container_images=(),
        network_policy="No external network during generated application execution.",
    )


def test_prepare_application_creates_bound_workspace_after_green_preflight(tmp_path) -> None:
    prepared = _prepared(tmp_path)

    request = load_case_study_run_request(prepared.run_request_path)
    environment = load_case_study_environment_identity(prepared.environment_path)
    assert request.workflow_run_id == WORKFLOW_RUN_ID
    assert environment.platform_commit == request.platform_commit
    assert environment.execution_profile == request.execution_profile


def test_plan_cli_prints_frozen_generic_campaign(capsys) -> None:
    exit_code = main(
        [
            "plan",
            "--repo-root",
            str(REPO_ROOT),
            "--platform-commit",
            "8" * 40,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert [case["case_id"] for case in payload["cases"]] == [
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    ]
    assert payload["owner_gates_must_not_be_bypassed"] is True


def test_finalize_cli_can_preserve_an_observed_failed_run_without_inventing_success(
    tmp_path, capsys
) -> None:
    prepared = _prepared(tmp_path)
    workspace = prepared.workspace_root
    (workspace / "evidence" / "build.json").write_text('{"build":"failed"}\n', encoding="utf-8")
    (workspace / "raw" / "evidence-map.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": [
                    {
                        "kind": "BUILD_REPORT",
                        "relative_path": "build.json",
                        "criterion_ids": ["CALC-002"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "finalize",
            "--repo-root",
            str(REPO_ROOT),
            "--workspace-root",
            str(workspace),
            "--started-at",
            "2026-09-07T17:00:00+00:00",
            "--completed-at",
            "2026-09-07T17:05:00+00:00",
            "--status",
            "FAILED",
            "--note",
            "Observed build failure preserved for analysis.",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["status"] == "FAILED"
    assert payload["definition_of_done_complete"] is False
    assert Path(payload["record_path"]).is_file()
