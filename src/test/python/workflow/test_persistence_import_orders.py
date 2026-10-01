import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "first",
    ["orchestwin.workflow.persistence.repositories", "orchestwin.projects.persistence.brief_gate"],
)
def test_persistence_consumers_import_in_both_orders_in_a_clean_process(first):
    source = f"""
import importlib
importlib.import_module({first!r})
from orchestwin.projects import persistence as projects
from orchestwin.workflow import persistence as workflow
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
assert projects.ProjectRecord is ProjectRecord
assert workflow.SqlAlchemyHumanGateRepository is SqlAlchemyHumanGateRepository
for name in projects.__all__:
    assert getattr(projects, name).__name__ == name
for name in workflow.__all__:
    assert getattr(workflow, name).__name__ == name
"""
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=Path(__file__).resolve().parents[4],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
