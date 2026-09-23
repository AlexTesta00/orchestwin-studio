"""Synthetic catalogs test API projection; they are never runner validation evidence."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.brownfield_runtime import LocalExecutionQueryService
from orchestwin.api.execution_catalog import project_execution_catalog
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.jvm_execution.profile_loader import LoadedJvmProfileCatalog
from orchestwin.jvm_execution.validation_evidence import JvmProfileValidationEvidenceCatalog
from orchestwin.jvm_execution.validation_evidence_persistence import (
    canonical_jvm_validation_evidence,
)
from orchestwin.sandbox.builtin_execution_profiles import create_builtin_execution_profile_registry
from orchestwin.sandbox.execution_policy import DEFAULT_SANDBOX_RESOURCE_LIMITS
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus, ExecutionTarget
from orchestwin.web_execution.profile_loader import LoadedWebProfileCatalog
from orchestwin.web_execution.validation_evidence import WebProfileValidationEvidenceCatalog
from orchestwin.web_execution.validation_evidence_persistence import (
    canonical_web_validation_evidence,
)
from src.test.python.jvm_execution.test_validation_evidence import _evidence_catalog
from src.test.python.web_execution.test_validation_evidence import evidence_catalog

TARGETS = tuple(t for t in ExecutionTarget if t.value.startswith(("WEB_", "JVM_")))


def catalogs(targets=TARGETS, conflicting_target=None):
    web_records, jvm_records = [], []
    for target in targets:
        records = (
            evidence_catalog(target).records
            if target.value.startswith("WEB_")
            else _evidence_catalog(target).records
        )
        if target == conflicting_target:
            records = (
                *records,
                replace(records[0], evidence_id="test.catalog.conflict", passed=False),
            )
        (web_records if target.value.startswith("WEB_") else jvm_records).extend(records)
    return (
        LoadedWebProfileCatalog(
            WebProfileValidationEvidenceCatalog(
                canonical_web_validation_evidence(tuple(web_records))
            )
        ),
        LoadedJvmProfileCatalog(
            JvmProfileValidationEvidenceCatalog(
                canonical_jvm_validation_evidence(tuple(jvm_records))
            )
        ),
    )


def projected(*args, **kwargs):
    web, jvm = catalogs(*args, **kwargs)
    return project_execution_catalog(
        create_builtin_execution_profile_registry(),
        web=web,
        jvm=jvm,
        web_resources=DEFAULT_SANDBOX_RESOURCE_LIMITS,
    )


def test_all_eight_promotions_are_scoped_and_leave_android_and_brownfield_unchanged():
    registry = create_builtin_execution_profile_registry()
    original = registry.to_snapshot()
    web, jvm = catalogs()
    values = project_execution_catalog(
        registry, web=web, jvm=jvm, web_resources=DEFAULT_SANDBOX_RESOURCE_LIMITS
    )
    assert registry.to_snapshot() == original
    assert len(values) == 10
    assert (
        sum(p.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D for p in values) == 8
    )
    for p in values:
        base = registry.find(p.profile_id, p.version).metadata
        assert base.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        if p.profile_id.startswith("ANDROID_"):
            assert p == base
            continue
        snapshot = p.to_snapshot()
        governed = snapshot["governed_execution"]
        assert governed["validation_scope"]["validation_evidence_refs"] == list(
            p.validation_evidence_refs
        )
        assert governed["runtime_availability"] == "NOT_CHECKED"
        assert governed["source_validation_required"] and governed["gate_7_required"]
        assert governed["legacy_brownfield_capability_status"] == "DESIGN_ONLY_LEVEL_C"
        assert snapshot["content_hash"] != base.content_hash
        assert p.required_runners
        if p.profile_id.startswith("JVM_"):
            assert "maven" in governed["validation_scope"]["excluded_configurations"]
            assert p.resource_defaults.memory_mib == 4096


@pytest.mark.parametrize("target", TARGETS)
def test_conflicting_evidence_downgrades_only_its_exact_target(target):
    values = projected(conflicting_target=target)
    for p in values:
        expected = p.profile_id != target.value and not p.profile_id.startswith("ANDROID_")
        assert (p.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D) == expected
        if p.profile_id == target.value:
            assert p.validation_evidence_refs == () and p.runner_image_digests == ()


def test_empty_catalog_never_promotes_and_scope_is_bound_into_descriptor_hash():
    empty = projected(())
    assert all(p.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C for p in empty)
    value = next(p for p in projected() if p.profile_id == "JVM_JAVA")
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        replace(value, validation_evidence_refs=value.validation_evidence_refs[1:])
    changed = replace(value, runner_image_digests=("b" * 64,))
    assert changed.content_hash != value.content_hash


def test_list_and_exact_lookup_reload_evidence_and_propagate_storage_failure():
    loader = SimpleNamespace(
        load=AsyncMock(
            side_effect=[projected(), projected(()), RuntimeError("storage unavailable")]
        )
    )
    service = LocalExecutionQueryService(
        registry=create_builtin_execution_profile_registry(),
        sandbox_uow_factory=None,
        catalog_loader=loader,
    )

    async def scenario():
        first = await service.profiles()
        assert (
            sum(p.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D for p in first)
            == 8
        )
        second = await service.profile(profile_id="WEB_STATIC", profile_version="1.0.0")
        assert second.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        with pytest.raises(RuntimeError, match="storage unavailable"):
            await service.profiles()

    asyncio.run(scenario())
    assert loader.load.await_count == 3


def test_http_catalog_preserves_legacy_ids_and_exposes_exact_runtime_scope():
    loader = SimpleNamespace(load=AsyncMock(return_value=projected()))
    queries = LocalExecutionQueryService(
        registry=create_builtin_execution_profile_registry(),
        sandbox_uow_factory=None,
        catalog_loader=loader,
    )
    app = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST),
        runtime=ApplicationRuntime(execution_query_service=queries),
        auth_settings=AuthApiSettings(),
    )
    with TestClient(app) as client:
        listed = client.get("/api/v1/execution-profiles")
        assert listed.status_code == 200
        detail = client.get("/api/v1/execution-profiles/WEB_STATIC?profile_version=1.0.0")
        assert detail.status_code == 200
        snapshot = detail.json()["snapshot"]
        assert snapshot == next(
            p for p in listed.json()["items"] if p["profile_id"] == "WEB_STATIC"
        )
        assert snapshot["governed_execution"]["profile_id"] == "web.static"
        assert snapshot["capability_status"] == "VALIDATED_LEVEL_D"
        assert (
            client.get("/api/v1/execution-profiles/WEB_STATIC?profile_version=99.0.0").status_code
            == 404
        )
        assert client.get("/api/v1/execution-profiles/UNKNOWN").status_code == 404
