from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "orchestwin"
    / "persistence"
    / "migrations"
    / "versions"
    / "0052_design_first_scope.py"
)

REMOVED_TABLES = frozenset(
    {
        "architecture_package_versions",
        "architecture_package_diffs",
        "brownfield_intake_versions",
        "sandbox_runs",
        "sandbox_command_results",
        "high_impact_operation_versions",
        "web_source_revisions",
        "web_execution_attempts",
        "jvm_source_revisions",
        "jvm_execution_attempts",
        "workflow_runs",
        "workflow_checkpoints",
        "workflow_graph_checkpoints",
        "workflow_graph_writes",
        "workflow_events",
        "evaluation_runs",
        "synthetic_findings",
        "final_reviews",
        "export_bundles",
        "static_browser_inspections",
        "authorized_evaluation_artifacts",
        "web_profile_validation_evidence",
        "web_governed_operations",
        "jvm_profile_validation_evidence",
        "jvm_governed_operations",
    }
)

SURVIVING_TABLES = frozenset(
    {
        "alembic_version",
        "users",
        "auth_sessions",
        "projects",
        "project_brief_versions",
        "clarification_rounds",
        "brief_assumptions",
        "human_gates",
        "human_gate_events",
        "team_proposals",
        "persona_profile_versions",
        "user_twin_profile_versions",
        "user_modeling_snapshot_versions",
        "user_twin_profile_diffs",
        "requirements_specification_versions",
        "requirements_specification_diffs",
        "design_package_versions",
        "design_package_diffs",
        "model_proposal_generations",
        "model_proposal_generation_events",
        "model_proposal_artifact_links",
        "twin_conversations",
        "twin_conversation_turns",
        "training_dataset_versions",
        "training_dataset_quality_reports",
        "training_runs",
        "training_run_checkpoints",
    }
)

PARENTS = {
    "synthetic_findings": ("evaluation_runs",),
    "evaluation_runs": ("workflow_runs",),
    "final_reviews": ("workflow_runs",),
    "export_bundles": ("workflow_runs",),
    "authorized_evaluation_artifacts": ("workflow_runs",),
    "workflow_events": ("workflow_runs",),
    "workflow_graph_checkpoints": ("workflow_runs",),
    "workflow_checkpoints": ("workflow_runs",),
    "static_browser_inspections": ("web_source_revisions",),
    "web_governed_operations": ("web_source_revisions",),
    "web_execution_attempts": ("web_source_revisions",),
    "jvm_governed_operations": ("jvm_source_revisions",),
    "jvm_execution_attempts": ("jvm_source_revisions",),
    "sandbox_command_results": ("sandbox_runs",),
    "sandbox_runs": ("brownfield_intake_versions",),
    "architecture_package_diffs": ("architecture_package_versions",),
}

GATE_TRIGGER = "retain_running_jvm_operation_gate"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("design_first_scope_migration", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load the design first scope migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_extends_the_source_third_attempt_head() -> None:
    migration = load_migration()

    assert migration.revision == "0052_design_first_scope"
    assert migration.down_revision == "0051_source_third_attempt"
    assert len(migration.revision) <= 64
    assert set(migration.TABLES) == REMOVED_TABLES
    assert len(migration.TABLES) == len(REMOVED_TABLES)
    assert not REMOVED_TABLES & SURVIVING_TABLES


def test_upgrade_drops_each_removed_table_before_its_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    dropped: list[str] = []
    executed: list[str] = []
    monkeypatch.setattr(migration.op, "drop_table", lambda name: dropped.append(name))
    monkeypatch.setattr(migration.op, "execute", lambda statement: executed.append(statement))

    migration.upgrade()

    assert dropped == list(migration.TABLES)
    for child, parents in PARENTS.items():
        for parent in parents:
            assert dropped.index(child) < dropped.index(parent)
    assert executed[0] == f"DROP TRIGGER {GATE_TRIGGER} ON human_gates"
    functions = [re.fullmatch(r"DROP FUNCTION ([a-z_]+)\(\)", item)[1] for item in executed[1:]]
    assert functions[0] == GATE_TRIGGER
    assert functions[1:] == list(migration.FUNCTIONS)
    assert len(set(functions)) == 21
    assert not any(name in SURVIVING_TABLES for name in dropped)


def test_downgrade_restores_every_table_function_and_the_gate_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = load_migration()
    executed: list[str] = []
    monkeypatch.setattr(migration.op, "execute", lambda statement: executed.append(statement))

    migration.downgrade()

    functions, tables, trigger = executed
    restored_functions = re.findall(r"^CREATE OR REPLACE FUNCTION ([a-z_]+)\(\)$", functions, re.M)
    assert sorted(restored_functions) == sorted([*migration.FUNCTIONS, GATE_TRIGGER])
    created = re.findall(r"^CREATE TABLE ([a-z_]+) \($", tables, re.M)
    assert sorted(created) == sorted(REMOVED_TABLES)
    assert len(re.findall(r"^CREATE TRIGGER ", tables, re.M)) == 25
    assert tables.count(" PRIMARY KEY (") == len(REMOVED_TABLES)
    assert "public." not in functions and "public." not in tables and "public." not in trigger
    assert not re.search(r"^(DROP |TRUNCATE |DELETE FROM )", functions + tables + trigger, re.M)
    assert trigger.strip().startswith(
        f"CREATE TRIGGER {GATE_TRIGGER} BEFORE INSERT OR UPDATE ON human_gates"
    )
    for table in REMOVED_TABLES:
        assert f"ADD CONSTRAINT pk_{table} PRIMARY KEY" in tables
    for table in ("users", "projects", "human_gates"):
        assert f"REFERENCES {table}(id)" in tables
