from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.projects.insight_applications import InsightSourceKind, InsightTarget

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0057_design_evaluation_loop.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "design_evaluation_loop_migration", MIGRATION_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the design evaluation loop migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_operations(migration, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, tuple, dict]] = []
    for name in ("create_table", "create_index", "drop_index", "drop_table"):
        monkeypatch.setattr(
            migration.op,
            name,
            lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs)),
        )
    return calls


def quoted(items):
    return {f"'{item.value}'" for item in items}


def names(items, kind):
    return [item.name for item in items if isinstance(item, kind)]


def test_revision_follows_the_clarification_round_drop() -> None:
    migration = load_migration()
    assert migration.revision == "0057_design_evaluation_loop"
    assert migration.down_revision == "0056_drop_clarification_rounds"
    assert set(migration.CRITERIA.split(",")) == quoted(SyntheticFindingCriterion)
    assert set(migration.SEVERITIES.split(",")) == quoted(SyntheticFindingSeverity)
    assert set(migration.EPISTEMIC.split(",")) == quoted(SyntheticFindingEpistemicStatus)
    assert set(migration.SOURCE_KINDS.split(",")) == quoted(InsightSourceKind)
    assert set(migration.TARGETS.split(",")) == quoted(InsightTarget)


def test_upgrade_creates_the_run_finding_and_application_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.upgrade()
    assert [call[0] for call in calls] == [
        "create_table",
        "create_index",
        "create_table",
        "create_index",
        "create_table",
        "create_index",
    ]
    runs = calls[0][1]
    assert runs[0] == "design_evaluation_runs"
    assert names(runs[1:], sa.Column)[:8] == [
        "id",
        "project_id",
        "owner_user_id",
        "design_version_id",
        "design_version_number",
        "design_content_hash",
        "alternative_id",
        "alternative_code",
    ]
    assert "run_snapshot" in names(runs[1:], sa.Column)
    assert names(runs[1:], sa.ForeignKeyConstraint) == [
        "fk_design_evaluation_runs_project",
        "fk_design_evaluation_runs_owner",
        "fk_design_evaluation_runs_design_version",
    ]
    assert "ck_design_evaluation_runs_response_count" in names(runs[1:], sa.CheckConstraint)
    findings = calls[2][1]
    assert findings[0] == "design_synthetic_findings"
    assert names(findings[1:], sa.PrimaryKeyConstraint) == ["pk_design_synthetic_findings"]
    assert "fk_design_synthetic_findings_run" in names(findings[1:], sa.ForeignKeyConstraint)
    assert "ck_design_synthetic_findings_criterion" in names(findings[1:], sa.CheckConstraint)
    applications = calls[4][1]
    assert applications[0] == "insight_applications"
    assert names(applications[1:], sa.Column)[3:9] == [
        "source_kind",
        "source_id",
        "source_twin_id",
        "text",
        "target",
        "target_field",
    ]
    assert calls[1][1] == (
        "ix_design_evaluation_runs_project_started",
        "design_evaluation_runs",
        ["project_id", "started_at"],
    )
    assert calls[5][1] == (
        "ix_insight_applications_project_created",
        "insight_applications",
        ["project_id", "created_at"],
    )


def test_downgrade_drops_the_three_tables_in_reverse_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    calls = record_operations(migration, monkeypatch)
    migration.downgrade()
    assert [(call[0], call[1][0]) for call in calls] == [
        ("drop_index", "ix_insight_applications_project_created"),
        ("drop_table", "insight_applications"),
        ("drop_index", "ix_design_synthetic_findings_project_twin"),
        ("drop_table", "design_synthetic_findings"),
        ("drop_index", "ix_design_evaluation_runs_project_started"),
        ("drop_table", "design_evaluation_runs"),
    ]
