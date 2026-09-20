"""Tests for immutable formal case run workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_workspace import (
    load_case_study_run_request,
    prepare_case_study_run_workspace,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000012701")


def test_workspace_binds_frozen_case_to_real_workflow_run_id(tmp_path) -> None:
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="5" * 40)

    workspace, request = prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=datetime(2026, 9, 7, 16, 30, tzinfo=UTC),
    )

    assert workspace.evidence_dir.is_dir()
    assert workspace.raw_dir.is_dir()
    assert workspace.final_dir.is_dir()
    assert load_case_study_run_request(workspace.request_path) == request
    assert request.workflow_run_id == WORKFLOW_RUN_ID
    assert request.execution_profile == "WEB_STATIC"
    assert request.campaign_content_hash == campaign.content_hash


def test_workspace_refuses_to_overwrite_existing_run_identity(tmp_path) -> None:
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="5" * 40)
    arguments = {
        "case_id": "web-calculator",
        "workflow_run_id": WORKFLOW_RUN_ID,
        "requested_at": datetime(2026, 9, 7, 16, 30, tzinfo=UTC),
    }
    prepare_case_study_run_workspace(tmp_path, campaign, **arguments)

    with pytest.raises(FileExistsError, match="already exists"):
        prepare_case_study_run_workspace(tmp_path, campaign, **arguments)
