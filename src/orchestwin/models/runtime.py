"""Runtime selection for provider-independent team-proposal adapters."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    TeamProposalPort,
)

TEAM_PROPOSAL_PROVIDER_ENVIRONMENT: Final = "ORCHESTWIN_TEAM_PROPOSAL_PROVIDER"


class TeamProposalRuntimeProvider(StrEnum):
    """Configured runtime providers for typed team proposals."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class TeamProposalRuntimeConfigurationError(RuntimeError):
    """Raised when a configured provider has no available adapter."""


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

    raise TeamProposalRuntimeConfigurationError(
        "team-proposal provider "
        f"{settings.provider.value} is not configured; "
        "use FAKE_DETERMINISTIC until a model adapter "
        "is implemented"
    )
