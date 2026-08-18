"""Tests for deterministic User Modeling runtime configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestwin.models.fake_user_modeling import (
    FakeDeterministicUserModelingAdapter,
)
from orchestwin.models.user_modeling_runtime import (
    UserModelingRuntimeMode,
    UserModelingRuntimeSettings,
    build_user_modeling_proposal_port,
    build_user_modeling_runtime,
)


def test_default_user_modeling_runtime_is_deterministic_fake() -> None:
    """Keep local and test execution independent from live providers."""
    runtime = build_user_modeling_runtime(UserModelingRuntimeSettings())

    assert runtime.mode is (UserModelingRuntimeMode.FAKE_DETERMINISTIC)

    assert isinstance(
        runtime.proposal_port,
        FakeDeterministicUserModelingAdapter,
    )


def test_runtime_mode_can_be_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolve the runtime through the dedicated environment namespace."""
    monkeypatch.setenv(
        "ORCHESTWIN_USER_MODELING_MODE",
        "FAKE_DETERMINISTIC",
    )

    settings = UserModelingRuntimeSettings()

    assert settings.mode is (UserModelingRuntimeMode.FAKE_DETERMINISTIC)

    runtime = build_user_modeling_runtime(settings)

    assert isinstance(
        runtime.proposal_port,
        FakeDeterministicUserModelingAdapter,
    )


def test_unknown_user_modeling_runtime_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently fall back from an unsupported configured provider."""
    monkeypatch.setenv(
        "ORCHESTWIN_USER_MODELING_MODE",
        "LIVE_CLOUD_PROVIDER",
    )

    with pytest.raises(ValidationError):
        UserModelingRuntimeSettings()


def test_sprint_four_runtime_exposes_no_provider_credentials() -> None:
    """Keep the deterministic Sprint 04 runtime free from API secrets."""
    fields = set(UserModelingRuntimeSettings.model_fields)

    assert fields == {
        "mode",
    }

    assert "api_key" not in fields
    assert "token" not in fields
    assert "base_url" not in fields


def test_runtime_builder_creates_fresh_adapter_instances() -> None:
    """Avoid hidden mutable singleton state between requests or tests."""
    settings = UserModelingRuntimeSettings()

    first = build_user_modeling_runtime(settings)
    second = build_user_modeling_runtime(settings)

    assert first is not second

    assert first.proposal_port is not second.proposal_port

    assert isinstance(
        first.proposal_port,
        FakeDeterministicUserModelingAdapter,
    )

    assert isinstance(
        second.proposal_port,
        FakeDeterministicUserModelingAdapter,
    )


def test_direct_proposal_port_builder_uses_configured_mode() -> None:
    """Keep provider construction available to composition roots."""
    settings = UserModelingRuntimeSettings(mode=(UserModelingRuntimeMode.FAKE_DETERMINISTIC))

    proposal_port = build_user_modeling_proposal_port(settings)

    assert isinstance(
        proposal_port,
        FakeDeterministicUserModelingAdapter,
    )
