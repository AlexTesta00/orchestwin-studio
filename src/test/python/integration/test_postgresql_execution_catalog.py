"""Real read-only catalog transactions with synthetic evidence in isolated schemas."""

import pytest
import sqlalchemy as sa

from orchestwin.api.execution_catalog import SqlAlchemyExecutionCatalogLoader
from orchestwin.jvm_execution.validation_evidence_persistence import (
    SqlAlchemyJvmValidationEvidenceRepository,
)
from orchestwin.sandbox.builtin_execution_profiles import create_builtin_execution_profile_registry
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.web_execution.validation_evidence_persistence import (
    SqlAlchemyWebValidationEvidenceRepository,
)
from src.test.python.api.test_execution_catalog import catalogs
from src.test.python.integration.test_postgresql_jvm_validation_evidence import _run

pytestmark = pytest.mark.integration


def loader(runtime):
    return SqlAlchemyExecutionCatalogLoader(
        runtime.session_factory,
        registry=create_builtin_execution_profile_registry(),
        web_resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
    )


async def append(runtime, repository, records):
    async with runtime.session_factory() as session, session.begin():
        for record in records:
            await repository(session).append(record)


def test_public_catalog_survives_restart_and_preserves_all_evidence():
    web, jvm = catalogs()
    expected = []

    async def store(runtime):
        empty = await loader(runtime).load()
        assert len(empty) == 10 and not any(p.advertises_level_d for p in empty)
        await append(runtime, SqlAlchemyWebValidationEvidenceRepository, web.catalog.records)
        await append(runtime, SqlAlchemyJvmValidationEvidenceRepository, jvm.catalog.records)
        result = await loader(runtime).load()
        assert (
            sum(p.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D for p in result)
            == 8
        )
        expected.extend(p.to_snapshot() for p in result)

    async def reload(runtime):
        result = await loader(runtime).load()
        assert [p.to_snapshot() for p in result] == expected
        async with runtime.session_factory() as session:
            assert (
                await SqlAlchemyWebValidationEvidenceRepository(session).history()
                == web.catalog.records
            )
            assert (
                await SqlAlchemyJvmValidationEvidenceRepository(session).history()
                == jvm.catalog.records
            )

    _run(store)
    _run(reload)


def test_catalog_uses_one_read_only_snapshot_during_concurrent_publication(monkeypatch):
    web, jvm = catalogs()
    original = SqlAlchemyWebValidationEvidenceRepository.history

    async def scenario(runtime):
        await append(runtime, SqlAlchemyWebValidationEvidenceRepository, web.catalog.records)
        published = False

        async def history(repository):
            nonlocal published
            records = await original(repository)
            assert await repository._session.scalar(sa.text("SHOW transaction_read_only")) == "on"
            assert (
                await repository._session.scalar(sa.text("SHOW transaction_isolation"))
                == "repeatable read"
            )
            if not published:
                await append(
                    runtime, SqlAlchemyJvmValidationEvidenceRepository, jvm.catalog.records
                )
                published = True
            return records

        monkeypatch.setattr(SqlAlchemyWebValidationEvidenceRepository, "history", history)
        current = loader(runtime)
        first = await current.load()
        assert sum(p.advertises_level_d for p in first) == 5
        next_read = await current.load()
        assert sum(p.advertises_level_d for p in next_read) == 8

    _run(scenario)
