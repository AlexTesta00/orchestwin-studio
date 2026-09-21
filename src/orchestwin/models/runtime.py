"""Runtime selection for provider-independent team-proposal adapters."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.proposal_generation import ProposalRuntimeConfigurationError
from orchestwin.models.team_proposals import (
    TeamProposalPort,
)

TEAM_PROPOSAL_PROVIDER_ENVIRONMENT: Final = "ORCHESTWIN_TEAM_PROPOSAL_PROVIDER"
TeamProposalRuntimeConfigurationError = ProposalRuntimeConfigurationError


class TeamProposalRuntimeProvider(StrEnum):
    """Configured runtime providers for typed team proposals."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class TeamProposalRuntimeSettings(BaseSettings):
    """Environment-backed team-proposal runtime policy."""

    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_TEAM_PROPOSAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    provider: TeamProposalRuntimeProvider = TeamProposalRuntimeProvider.FAKE_DETERMINISTIC
    model_config_file: Path | None = None


def load_team_proposal_runtime_settings(
    *,
    env_file: str | None = ".env",
) -> TeamProposalRuntimeSettings:
    """Load the team-proposal runtime policy."""
    return TeamProposalRuntimeSettings(_env_file=env_file)


def create_team_proposal_port(
    settings: TeamProposalRuntimeSettings,
) -> TeamProposalPort:
    """Create the configured provider-independent proposal adapter."""
    if settings.provider is TeamProposalRuntimeProvider.FAKE_DETERMINISTIC:
        return FakeDeterministicTeamProposalAdapter()

    from orchestwin.models.model_proposals import ModelTeamProposalAdapter
    from orchestwin.models.proposal_generation import build_proposal_generator

    return ModelTeamProposalAdapter(build_proposal_generator(settings.model_config_file))
