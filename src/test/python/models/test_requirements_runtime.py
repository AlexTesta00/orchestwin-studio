"""Tests for deterministic requirements runtime configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestwin.models.fake_requirements import (
    FakeDeterministicRequirementsAdapter,
)
from orchestwin.models.requirements_runtime import (
    RequirementsRuntimeMode,
    RequirementsRuntimeSettings,
    build_requirements_runtime,
)


def test_default_requirements_runtime_is_the_deterministic_fake() -> None:
    """Keep ordinary execution independent from live model providers."""
    runtime = build_requirements_runtime(RequirementsRuntimeSettings())

    assert runtime.mode is RequirementsRuntimeMode.FAKE_DETERMINISTIC
    assert isinstance(
        runtime.proposal_port,
        FakeDeterministicRequirementsAdapter,
    )


def test_runtime_mode_loads_from_the_dedicated_environment_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve the configured provider through one explicit setting."""
    monkeypatch.setenv(
        "ORCHESTWIN_REQUIREMENTS_MODE",
        "FAKE_DETERMINISTIC",
    )

    settings = RequirementsRuntimeSettings()

    assert settings.mode is RequirementsRuntimeMode.FAKE_DETERMINISTIC


def test_unknown_requirements_runtime_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently fall back from an unsupported provider mode."""
    monkeypatch.setenv(
        "ORCHESTWIN_REQUIREMENTS_MODE",
        "LIVE_CLOUD_PROVIDER",
    )

    with pytest.raises(ValidationError):
        RequirementsRuntimeSettings()


def test_sprint_five_runtime_exposes_no_provider_credentials() -> None:
    """Keep the deterministic runtime free from secrets and network URLs."""
    assert set(RequirementsRuntimeSettings.model_fields) == {"mode"}
