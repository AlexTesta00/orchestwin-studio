"""Tests for deterministic team-proposal runtime configuration."""

import pytest
from pydantic import ValidationError

from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.runtime import (
    TEAM_PROPOSAL_PROVIDER_ENVIRONMENT,
    TeamProposalRuntimeConfigurationError,
    TeamProposalRuntimeProvider,
    TeamProposalRuntimeSettings,
    create_team_proposal_port,
    load_team_proposal_runtime_settings,
)
from orchestwin.models.team_proposals import (
    TeamProposalPort,
)


def test_default_runtime_uses_fake_deterministic_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep local development deterministic without credentials."""
    monkeypatch.delenv(
        TEAM_PROPOSAL_PROVIDER_ENVIRONMENT,
        raising=False,
    )

    settings = load_team_proposal_runtime_settings(env_file=None)
    adapter = create_team_proposal_port(settings)

    assert settings.provider is (TeamProposalRuntimeProvider.FAKE_DETERMINISTIC)
    assert isinstance(
        adapter,
        FakeDeterministicTeamProposalAdapter,
    )
    assert isinstance(
        adapter,
        TeamProposalPort,
    )


def test_runtime_provider_is_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Load the explicit Compose runtime provider."""
    monkeypatch.setenv(
        TEAM_PROPOSAL_PROVIDER_ENVIRONMENT,
        "FAKE_DETERMINISTIC",
    )

    settings = load_team_proposal_runtime_settings(env_file=None)

    assert settings.provider is (TeamProposalRuntimeProvider.FAKE_DETERMINISTIC)


def test_unimplemented_model_adapter_fails_fast() -> None:
    """Avoid claiming a live-model capability without an adapter."""
    settings = TeamProposalRuntimeSettings(
        provider=(TeamProposalRuntimeProvider.MODEL_ADAPTER),
        _env_file=None,
    )

    with pytest.raises(
        TeamProposalRuntimeConfigurationError,
        match=("MODEL_ADAPTER is not configured"),
    ):
        create_team_proposal_port(settings)


def test_unknown_runtime_provider_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject runtime values outside the versioned provider policy."""
    monkeypatch.setenv(
        TEAM_PROPOSAL_PROVIDER_ENVIRONMENT,
        "UNREGISTERED_PROVIDER",
    )

    with pytest.raises(ValidationError):
        load_team_proposal_runtime_settings(env_file=None)
