"""Migration readiness is checked against real isolated PostgreSQL schemas."""

import os

import pytest
from alembic import command

from orchestwin.models.real_runtime import RealModelRuntimeError, _check_schema
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import create_alembic_config
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"),
        reason="explicit disposable PostgreSQL URL required",
    ),
]


@pytest.mark.parametrize("migrated", [False, True])
def test_real_runtime_requires_proposal_evidence_schema(database, migrated):
    if not migrated:
        command.downgrade(
            create_alembic_config(database.url.get_secret_value()),
            "0038_proposal_generation_evidence",
        )

    async def scenario():
        runtime = create_database_runtime(database)
        try:
            if migrated:
                assert (await _check_schema(runtime.session_factory))[
                    "proposal_evidence_schema_available"
                ] is True
            else:
                with pytest.raises(
                    RealModelRuntimeError, match="PROPOSAL_EVIDENCE_MIGRATION_REQUIRED"
                ):
                    await _check_schema(runtime.session_factory)
        finally:
            await runtime.dispose()

    run(scenario())
