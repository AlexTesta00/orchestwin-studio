from __future__ import annotations

import importlib
import re
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.script import ScriptDirectory

from orchestwin.persistence.migrate import create_alembic_config

URL = "postgresql+psycopg://synthetic@localhost:5432/orchestwin"
REVISION = "0074_design_version_restore"
PREVIOUS = "0073_knowledge_alignment"
NEXT = "0075_design_critiques"
TABLE = "design_package_versions"
CONSTRAINT = "uq_design_package_versions_project_hash"
DROP = f"ALTER TABLE {TABLE} DROP CONSTRAINT {CONSTRAINT}"
ADD = f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} UNIQUE (project_id, content_hash)"
STEPS = ["BEGIN", "ALTER TABLE", "UPDATE alembic_version", "COMMIT"]


def migration():
    return importlib.import_module(f"orchestwin.persistence.migrations.versions.{REVISION}")


def capture(monkeypatch):
    module = migration()
    calls = []
    for name in ("drop_constraint", "create_unique_constraint"):
        monkeypatch.setattr(
            module.op, name, lambda *args, _name=name, **kwargs: calls.append((_name, args, kwargs))
        )
    return module, calls


def offline_sql(step, revisions) -> str:
    output = StringIO()
    step(create_alembic_config(URL, output_buffer=output), revisions, sql=True)
    return output.getvalue()


def statements(sql: str) -> list[str]:
    text = "\n".join(line for line in sql.splitlines() if not line.startswith("--"))
    return [" ".join(part.split()) for part in text.split(";\n") if part.strip()]


def test_revision_follows_the_knowledge_alignment_and_precedes_the_design_critiques():
    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, PREVIOUS)
    assert (module.branch_labels, module.depends_on) == (None, None)
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert {
        name.split(".")[0] for name in re.findall(r"^(?:from|import) ([\w.]+)", source, re.M)
    } == {"alembic"}
    scripts = ScriptDirectory.from_config(create_alembic_config(URL))
    assert len(scripts.get_heads()) == 1
    assert scripts.get_revision(REVISION).down_revision == PREVIOUS
    assert scripts.get_revision(PREVIOUS).nextrev == {REVISION}
    assert scripts.get_revision(REVISION).nextrev == {NEXT}


def test_upgrade_only_drops_the_uniqueness_of_the_content_hash(monkeypatch):
    module, calls = capture(monkeypatch)
    module.upgrade()
    assert calls == [("drop_constraint", (CONSTRAINT, TABLE), {"type_": "unique"})]


def test_downgrade_only_puts_the_same_uniqueness_back(monkeypatch):
    module, calls = capture(monkeypatch)
    module.downgrade()
    assert calls == [
        ("create_unique_constraint", (CONSTRAINT, TABLE, ["project_id", "content_hash"]), {})
    ]


def test_offline_upgrade_drops_the_constraint_and_touches_nothing_else():
    sql = offline_sql(command.upgrade, f"{PREVIOUS}:{REVISION}")
    rendered = statements(sql)
    assert [" ".join(statement.split()[:2]) for statement in rendered] == STEPS
    assert rendered[1] == DROP
    assert f"SET version_num='{REVISION}'" in rendered[2]
    assert f"version_num = '{PREVIOUS}'" in rendered[2]
    assert "synthetic" not in sql


def test_offline_downgrade_adds_the_same_constraint_back_and_touches_nothing_else():
    sql = offline_sql(command.downgrade, f"{REVISION}:{PREVIOUS}")
    rendered = statements(sql)
    assert [" ".join(statement.split()[:2]) for statement in rendered] == STEPS
    assert rendered[1] == ADD
    assert f"SET version_num='{PREVIOUS}'" in rendered[2]
    assert f"version_num = '{REVISION}'" in rendered[2]
    assert "synthetic" not in sql
