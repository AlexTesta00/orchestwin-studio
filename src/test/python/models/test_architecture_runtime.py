"""Tests for architecture proposal runtime configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestwin.models.architecture_runtime import (
    ArchitectureRuntimeMode,
    ArchitectureRuntimeSettings,
    build_architecture_runtime,
)
from orchestwin.models.fake_architecture import FakeDeterministicArchitectureAdapter


def test_default_architecture_runtime_is_the_deterministic_fake() -> None:
    """Keep ordinary architecture tests independent from network and credentials."""
    runtime = build_architecture_runtime()

    assert runtime.mode is ArchitectureRuntimeMode.FAKE_DETERMINISTIC
    assert isinstance(runtime.proposal_port, FakeDeterministicArchitectureAdapter)


def test_runtime_mode_loads_from_the_dedicated_environment_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read architecture configuration without sharing another provider namespace."""
    monkeypatch.setenv("ORCHESTWIN_ARCHITECTURE_MODE", "FAKE_DETERMINISTIC")

    settings = ArchitectureRuntimeSettings()

    assert settings.mode is ArchitectureRuntimeMode.FAKE_DETERMINISTIC


def test_unknown_architecture_runtime_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject silent provider fallbacks when runtime configuration is invalid."""
    monkeypatch.setenv("ORCHESTWIN_ARCHITECTURE_MODE", "LIVE_PROVIDER")

    with pytest.raises(ValidationError):
        ArchitectureRuntimeSettings()


def test_runtime_exposes_config_path_without_provider_credentials() -> None:
    """Expose only mode and a non-secret configuration path."""
    assert set(ArchitectureRuntimeSettings.model_fields) == {"mode", "model_config_file"}
