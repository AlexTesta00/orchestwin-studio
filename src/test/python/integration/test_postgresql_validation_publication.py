"""Exercise atomic publication only inside disposable PostgreSQL test schemas.

The receipts and runner/browser observations are explicitly synthetic fixtures.
Their test-schema records never grant application capability or formal evidence.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
import sqlalchemy as sa

from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.web_execution.validation_evidence_persistence import (
    SqlAlchemyWebValidationEvidenceUnitOfWork,
    WebValidationEvidenceAppendStatus,
)
from orchestwin.web_execution.validation_harvest import (
    WebValidationHarvestError,
    publish_validation_batch,
    verify_validation_harvest,
)
from src.test.python.web_execution.test_validation_harvest import (
    complete_campaign as complete_campaign,
)

pytestmark = pytest.mark.integration


def prepared_batch(complete_campaign):
    objects, request, read = complete_campaign
    batch = verify_validation_harvest(request, read_artifact=read)
    assert batch.is_complete and len(batch.records) == 52
    for reference, body in batch.artifacts:
        assert objects.put(body) == reference
    return batch, read


def single_connection_runtime():
    settings = load_database_settings(env_file=None).model_copy(
        update={"pool_size": 1, "max_overflow": 0, "pool_timeout_seconds": 5}
    )
    return create_database_runtime(settings)


def test_verified_test_batch_publishes_52_once_using_same_transaction_advisory_lock(
    complete_campaign,
):
    batch, read = prepared_batch(complete_campaign)

    async def scenario():
        database = single_connection_runtime()
        statements = []

        def observed_statement(_connection, _cursor, statement, _parameters, _context, _many):
            if "pg_advisory_xact_lock" in statement:
                statements.append(statement)

        sa.event.listen(database.engine.sync_engine, "after_cursor_execute", observed_statement)

        def unit():
            return SqlAlchemyWebValidationEvidenceUnitOfWork(database.session_factory)

        try:
            first = await asyncio.wait_for(
                publish_validation_batch(batch, unit_of_work_factory=unit, read_artifact=read), 60
            )
            second = await asyncio.wait_for(
                publish_validation_batch(batch, unit_of_work_factory=unit, read_artifact=read), 60
            )
            assert (first.appended, first.already_present) == (52, 0)
            assert (second.appended, second.already_present) == (0, 52)
            assert len(statements) == 2
            async with unit() as restored:
                assert await restored.evidence.history() == batch.records
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        sa.text("SELECT count(*) FROM web_profile_validation_evidence")
                    )
                    == 52
                )
                assert (
                    await connection.scalar(
                        sa.text(
                            "SELECT count(*) FROM pg_locks "
                            "WHERE pid = pg_backend_pid() AND locktype = 'advisory'"
                        )
                    )
                    == 0
                )
        finally:
            await database.dispose()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)


def test_conflict_on_last_record_rolls_back_every_previous_append(complete_campaign):
    batch, read = prepared_batch(complete_campaign)
    conflict = replace(batch.records[-1], passed=False)

    async def scenario():
        database = single_connection_runtime()

        def unit():
            return SqlAlchemyWebValidationEvidenceUnitOfWork(database.session_factory)

        try:
            async with unit() as existing:
                assert (
                    await existing.evidence.append(conflict)
                    is WebValidationEvidenceAppendStatus.APPENDED
                )
                await existing.commit()
            with pytest.raises(WebValidationHarvestError, match="PUBLICATION_CONFLICT"):
                await asyncio.wait_for(
                    publish_validation_batch(batch, unit_of_work_factory=unit, read_artifact=read),
                    60,
                )
            async with unit() as restored:
                assert await restored.evidence.history() == (conflict,)
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        sa.text("SELECT count(*) FROM web_profile_validation_evidence")
                    )
                    == 1
                )
        finally:
            await database.dispose()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
