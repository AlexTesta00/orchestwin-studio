"""Load synthetic profile catalogs from isolated PostgreSQL test schemas.

These schemas contain only storage fixtures. Promotion here is a test assertion,
never evidence that a production Web profile has attained Level D.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError

from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.config import DatabaseSettings
from orchestwin.persistence.database import DatabaseRuntime
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus, ExecutionTarget
from orchestwin.web_execution.profile_loader import build_web_profile_catalog_loader
from orchestwin.web_execution.targets import web_scope_for
from orchestwin.web_execution.validation_evidence import (
    WebProfilePromotionStatus,
    WebProfileValidationEvidenceCatalog,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    WEB_PROFILE_VALIDATION_EVIDENCE,
    SqlAlchemyWebValidationEvidenceUnitOfWork,
    WebValidationEvidenceAppendStatus,
    canonical_web_validation_evidence,
    web_validation_evidence_to_record,
)
from src.test.python.web_execution.test_validation_evidence import evidence_catalog

pytestmark = pytest.mark.integration

_ALL_TARGETS = (
    ExecutionTarget.WEB_STATIC,
    ExecutionTarget.WEB_VUE,
    ExecutionTarget.WEB_NODE_EXPRESS,
    ExecutionTarget.WEB_PHP,
    ExecutionTarget.WEB_VUE_NODE,
)


@asynccontextmanager
async def _runtime(settings: DatabaseSettings) -> AsyncIterator[DatabaseRuntime]:
    runtime = create_database_runtime(settings)
    try:
        yield runtime
    finally:
        await runtime.dispose()


def _run(scenario: Callable[[DatabaseSettings], Awaitable[None]]) -> None:
    async def isolated_schema() -> None:
        settings = load_database_settings(env_file=None)
        schema = f"test_web_profile_loader_{uuid4().hex}"
        table = WEB_PROFILE_VALIDATION_EVIDENCE.to_metadata(sa.MetaData(), schema=schema)
        # The search path names only this fresh schema, excluding public evidence.
        scoped_url = settings.sqlalchemy_url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        scoped_settings = settings.model_copy(
            update={"url": SecretStr(scoped_url.render_as_string(hide_password=False))}
        )
        async with _runtime(settings) as administration:
            async with administration.engine.begin() as connection:
                await connection.execute(sa.schema.CreateSchema(schema))
            try:
                async with administration.engine.begin() as connection:
                    await connection.run_sync(table.create)
                # Unit 2 separately verifies the migration and append-only guards.
                await scenario(scoped_settings)
            finally:
                # All scoped engines have closed before dropping only our own schema.
                assert schema.startswith("test_web_profile_loader_")
                assert len(schema.removeprefix("test_web_profile_loader_")) == 32
                async with administration.engine.begin() as connection:
                    await connection.execute(sa.schema.DropSchema(schema, cascade=True))

    asyncio.run(isolated_schema(), loop_factory=asyncio.SelectorEventLoop)


def _catalog(targets: tuple[ExecutionTarget, ...]) -> WebProfileValidationEvidenceCatalog:
    return WebProfileValidationEvidenceCatalog(
        canonical_web_validation_evidence(
            tuple(record for target in targets for record in evidence_catalog(target).records)
        )
    )


async def _append(runtime: DatabaseRuntime, catalog: WebProfileValidationEvidenceCatalog) -> None:
    async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
        # Insertion order must not determine the catalog or its promotion decisions.
        for record in reversed(catalog.records):
            assert await unit.evidence.append(record) is WebValidationEvidenceAppendStatus.APPENDED
        await unit.commit()


def test_empty_database_loads_all_five_profiles_as_design_only() -> None:
    async def scenario(settings: DatabaseSettings) -> None:
        async with _runtime(settings) as runtime:
            loaded = await build_web_profile_catalog_loader(runtime.session_factory).load()
            assert loaded.catalog.records == ()
            assert len(loaded.registry.profiles) == len(_ALL_TARGETS)
            assert len(loaded.promotion_decisions) == len(_ALL_TARGETS)
            for profile in loaded.registry.profiles:
                assert (
                    profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
                )
                assert profile.scope.validation_evidence_refs == ()
                decision = loaded.promotion_for(
                    profile.scope.profile_id, profile.scope.profile_version
                )
                assert decision in loaded.promotion_decisions
                assert decision is not None
                assert decision.status is WebProfilePromotionStatus.INCOMPLETE
            assert loaded.promotion_for("web.unknown", "1.0.0") is None
            assert loaded.promotion_for("web.static", "999.0.0") is None

    _run(scenario)


@pytest.mark.parametrize("targets", [(ExecutionTarget.WEB_STATIC,), _ALL_TARGETS])
def test_committed_catalog_is_fresh_and_survives_engine_restart_with_identical_decisions(
    targets: tuple[ExecutionTarget, ...],
) -> None:
    catalog = _catalog(targets)

    async def scenario(settings: DatabaseSettings) -> None:
        async with _runtime(settings) as runtime:
            loader = build_web_profile_catalog_loader(runtime.session_factory)
            before = await loader.load()
            assert before.catalog.records == ()
            await _append(runtime, catalog)
            loaded = await loader.load()
            assert loaded.catalog == catalog
            assert before.catalog.records == ()
            for profile in loaded.registry.profiles:
                expected_capability = (
                    ExecutionCapabilityStatus.VALIDATED_LEVEL_D
                    if profile.scope.target in targets
                    else ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
                )
                assert profile.scope.capability_status is expected_capability
                decision = loaded.promotion_for(
                    profile.scope.profile_id, profile.scope.profile_version
                )
                assert decision is not None
                assert decision.status is (
                    WebProfilePromotionStatus.ELIGIBLE
                    if profile.scope.target in targets
                    else WebProfilePromotionStatus.INCOMPLETE
                )
            expected_registry_snapshot = loaded.registry.to_snapshot()
            expected_registry_hash = loaded.registry.content_hash
            expected_decisions = loaded.promotion_decisions

        # A new engine and new session factory cannot reuse the prior loader or pool.
        async with _runtime(settings) as restarted:
            restored = await build_web_profile_catalog_loader(restarted.session_factory).load()
            assert restored.catalog == catalog
            assert tuple(record.content_hash for record in restored.catalog.records) == tuple(
                record.content_hash for record in catalog.records
            )
            assert restored.registry.to_snapshot() == expected_registry_snapshot
            assert restored.registry.content_hash == expected_registry_hash
            assert restored.promotion_decisions == expected_decisions
            for decision in expected_decisions:
                assert (
                    restored.promotion_for(decision.profile_id, decision.profile_version)
                    == decision
                )

    _run(scenario)


@pytest.mark.parametrize(
    ("observation", "expected_status"),
    [
        ("stale", WebProfilePromotionStatus.STALE),
        ("failed", WebProfilePromotionStatus.FAILED),
        ("conflicting", WebProfilePromotionStatus.CONFLICTING),
    ],
)
def test_history_keeps_adverse_observations_even_when_complete_good_evidence_exists(
    observation: str, expected_status: WebProfilePromotionStatus
) -> None:
    complete = _catalog((ExecutionTarget.WEB_STATIC,))
    changes = {
        "stale": {"baseline_scope_hash": "9" * 64},
        "failed": {"passed": False},
        "conflicting": {"execution_runner_image_digest": "f" * 64},
    }
    adverse = replace(
        complete.records[0],
        evidence_id=f"test.additional.{observation}",
        **changes[observation],
    )
    catalog = WebProfileValidationEvidenceCatalog(
        canonical_web_validation_evidence((*complete.records, adverse))
    )

    async def scenario(settings: DatabaseSettings) -> None:
        async with _runtime(settings) as runtime:
            await _append(runtime, catalog)
            loaded = await build_web_profile_catalog_loader(runtime.session_factory).load()
            assert loaded.catalog == catalog
            assert adverse in loaded.catalog.records
            scope = web_scope_for(ExecutionTarget.WEB_STATIC)
            decision = loaded.promotion_for(scope.profile_id, scope.profile_version)
            assert decision is not None
            assert decision.status is expected_status
            assert all(
                profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
                for profile in loaded.registry.profiles
            )

    _run(scenario)


def test_committed_corruption_in_unregistered_profile_aborts_fresh_catalog_load() -> None:
    catalog = _catalog((ExecutionTarget.WEB_STATIC,))
    corrupt = replace(
        catalog.records[0], evidence_id="test.corrupt.unknown", profile_id="web.unknown"
    )
    values = web_validation_evidence_to_record(corrupt)
    values["content_hash"] = "0" * 64
    assert values["content_hash"] != corrupt.content_hash

    async def scenario(settings: DatabaseSettings) -> None:
        async with _runtime(settings) as runtime:
            await _append(runtime, catalog)
            loader = build_web_profile_catalog_loader(runtime.session_factory)
            assert (await loader.load()).catalog == catalog
            async with runtime.session_factory.begin() as session:
                await session.execute(sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(values))
            with pytest.raises(ValueError, match="content_hash"):
                await loader.load()

    _run(scenario)


def test_database_error_is_not_replaced_by_cached_or_empty_profiles() -> None:
    async def scenario(settings: DatabaseSettings) -> None:
        async with _runtime(settings) as runtime:
            loader = build_web_profile_catalog_loader(runtime.session_factory)
            assert (await loader.load()).catalog.records == ()
            async with runtime.engine.begin() as connection:
                await connection.execute(sa.schema.DropTable(WEB_PROFILE_VALIDATION_EVIDENCE))
            with pytest.raises(DBAPIError):
                await loader.load()

    _run(scenario)
