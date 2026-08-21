"""Tests for deterministic design runtime configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestwin.models.design_runtime import (
    DesignRuntimeMode,
    DesignRuntimeSettings,
    build_design_runtime,
)
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter


def test_default_design_runtime_is_the_deterministic_fake() -> None:
    """Keep ordinary Design execution independent from live providers."""
    runtime = build_design_runtime(DesignRuntimeSettings())

    assert runtime.mode is DesignRuntimeMode.FAKE_DETERMINISTIC
    assert isinstance(runtime.proposal_port, FakeDeterministicDesignAdapter)


def test_runtime_mode_loads_from_the_dedicated_environment_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve the configured Design provider through one explicit setting."""
    monkeypatch.setenv(
        "ORCHESTWIN_DESIGN_MODE",
        "FAKE_DETERMINISTIC",
    )

    settings = DesignRuntimeSettings()

    assert settings.mode is DesignRuntimeMode.FAKE_DETERMINISTIC


def test_unknown_design_runtime_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently fall back from an unsupported Design provider mode."""
    monkeypatch.setenv(
        "ORCHESTWIN_DESIGN_MODE",
        "LIVE_CLOUD_PROVIDER",
    )

    with pytest.raises(ValidationError):
        DesignRuntimeSettings()


def test_sprint_six_runtime_exposes_no_provider_credentials() -> None:
    """Keep the deterministic Design runtime free from secrets and URLs."""
    assert set(DesignRuntimeSettings.model_fields) == {"mode"}
