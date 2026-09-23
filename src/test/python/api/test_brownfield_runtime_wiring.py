"""Runtime and configuration tests for the Sprint 07 bounded context."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.brownfield_runtime import build_brownfield_services
from orchestwin.api.execution_catalog import SqlAlchemyExecutionCatalogLoader
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment

IMAGE = "example/web@sha256:" + "a" * 64


class _FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _settings(tmp_path: Path) -> ApplicationSettings:
    return ApplicationSettings(
        environment=RuntimeEnvironment.TEST,
        source_archive_storage_root=tmp_path / "archives",
        brownfield_workspace_root=tmp_path / "workspaces",
        sandbox_evidence_storage_root=tmp_path / "evidence",
        available_execution_runners=("runner.web",),
        sandbox_approved_images=(IMAGE,),
    )


def test_brownfield_settings_enforce_distinct_roots_digest_images_and_limits(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    assert settings.source_archive_maximum_upload_bytes == 25 * 1024 * 1024
    assert settings.sandbox_resource_limits.memory_mib == 4096
    assert settings.sandbox_runtime_enabled is False
    assert settings.available_execution_runners == ("runner.web",)

    with pytest.raises(ValidationError, match="pinned by SHA-256"):
        ApplicationSettings(sandbox_approved_images=("example/web:latest",))
    with pytest.raises(ValidationError, match="must be distinct"):
        ApplicationSettings(
            source_archive_storage_root=tmp_path / "same",
            brownfield_workspace_root=tmp_path / "same",
        )
    with pytest.raises(ValidationError, match="25 MiB"):
        ApplicationSettings(source_archive_maximum_upload_bytes=26 * 1024 * 1024)


def test_builder_composes_profiles_brownfield_queries_and_gate_7_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)

    bundle = build_brownfield_services(settings, object())  # type: ignore[arg-type]
    load = AsyncMock(return_value=tuple(p.metadata for p in bundle.profile_registry.profiles))
    monkeypatch.setattr(SqlAlchemyExecutionCatalogLoader, "load", load)
    profiles = asyncio.run(bundle.execution_queries.profiles())
    load.assert_awaited_once_with()

    assert len(profiles) == 10
    assert {profile.capability_status.value for profile in profiles} == {"DESIGN_ONLY_LEVEL_C"}
    assert bundle.brownfield is not None
    assert bundle.high_impact is not None
    assert not settings.source_archive_storage_root.exists()
    assert not settings.brownfield_workspace_root.exists()
    assert not settings.sandbox_evidence_storage_root.exists()


def test_default_runtime_wires_brownfield_services_with_the_database_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _FakeDatabaseRuntime()
    stage_marker = SimpleNamespace(
        generation=object(),
        revisions=object(),
        queries=object(),
        gate=object(),
    )
    brownfield_marker = SimpleNamespace(
        brownfield=object(),
        execution_queries=object(),
        high_impact=object(),
    )
    captured: list[tuple[ApplicationSettings, object]] = []

    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(
        services_module,
        "create_database_runtime",
        lambda _settings: database,
    )
    monkeypatch.setattr(
        services_module,
        "build_requirements_services",
        lambda _session_factory: stage_marker,
    )
    monkeypatch.setattr(
        services_module,
        "build_design_services",
        lambda _session_factory: stage_marker,
    )
    monkeypatch.setattr(
        services_module,
        "build_architecture_services",
        lambda _session_factory: stage_marker,
    )

    def build_brownfield(settings: ApplicationSettings, session_factory: object):
        captured.append((settings, session_factory))
        return brownfield_marker

    monkeypatch.setattr(services_module, "build_brownfield_services", build_brownfield)
    settings = _settings(tmp_path)

    runtime = create_default_runtime(settings)

    assert captured == [(settings, database.session_factory)]
    assert runtime.brownfield_service is brownfield_marker.brownfield
    assert runtime.execution_query_service is brownfield_marker.execution_queries
    assert runtime.high_impact_service is brownfield_marker.high_impact

    asyncio.run(runtime.close())
    assert database.disposed is True


def test_application_exposes_the_configured_archive_upload_limit(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    application = create_app(
        settings,
        runtime=ApplicationRuntime(),
        auth_settings=AuthApiSettings(),
    )

    assert application.state.source_archive_maximum_upload_bytes == 25 * 1024 * 1024
