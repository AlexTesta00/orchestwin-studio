"""Campaign inputs never grant approval or bypass the clean-commit boundary."""

from subprocess import CompletedProcess

import pytest

from orchestwin.web_execution.validation_campaign import (
    CampaignError,
    checked_commit,
    create_campaign_plan,
    verify_campaign_plan,
)


def test_dirty_tree_is_rejected_before_work(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_campaign.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, b" M code.py\n", b""),
    )
    with pytest.raises(CampaignError, match="DIRTY"):
        checked_commit(tmp_path)


def test_changed_commit_is_rejected(monkeypatch, tmp_path):
    results = iter((b"", b"a" * 40 + b"\n"))
    monkeypatch.setattr(
        "orchestwin.web_execution.validation_campaign.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, next(results), b""),
    )
    with pytest.raises(CampaignError, match="COMMIT_CHANGED"):
        checked_commit(tmp_path, expected="b" * 40)


def test_plan_has_three_independent_projects_per_configuration():
    from types import SimpleNamespace
    from uuid import uuid4

    fixtures = tuple(
        SimpleNamespace(fixture_id=f"f{index}", fixture_bundle_hash="a" * 64) for index in range(8)
    )
    plan = create_campaign_plan(
        owner_user_id=uuid4(), commit="b" * 40, configuration_hash="c" * 64, fixtures=fixtures
    )
    verify_campaign_plan(plan, commit="b" * 40, configuration_hash="c" * 64, fixtures=fixtures)
    assert len({row["project_id"] for row in plan["cases"]}) == 24
    assert len({row["source_id"] for row in plan["cases"]}) == 24
    assert {row["role"] for row in plan["cases"]} == {"valid", "repeated", "failed"}
    assert "approval" not in str(plan)
    plan["cases"][0]["fixture_bundle_hash"] = "d" * 64
    with pytest.raises(CampaignError, match="PLAN"):
        verify_campaign_plan(plan, commit="b" * 40, configuration_hash="c" * 64, fixtures=fixtures)
