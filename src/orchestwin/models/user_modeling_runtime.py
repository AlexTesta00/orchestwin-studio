"""Runtime configuration for User Modeling proposal providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)

from orchestwin.models.fake_user_modeling import (
    FakeDeterministicUserModelingAdapter,
)
from orchestwin.models.user_modeling import (
    UserModelingProposalPort,
)


class UserModelingRuntimeMode(StrEnum):
    """User Modeling proposal runtimes supported in the current milestone."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class UserModelingRuntimeSettings(BaseSettings):
    """Environment-backed User Modeling runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_USER_MODELING_",
        case_sensitive=False,
        extra="forbid",
    )

    mode: UserModelingRuntimeMode = UserModelingRuntimeMode.FAKE_DETERMINISTIC
    model_config_file: Path | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class UserModelingRuntime:
    """Resolved User Modeling runtime dependencies."""

    mode: UserModelingRuntimeMode
    proposal_port: UserModelingProposalPort


def build_user_modeling_proposal_port(
    settings: UserModelingRuntimeSettings,
) -> UserModelingProposalPort:
    """Build the configured User Modeling proposal provider."""
    if settings.mode is UserModelingRuntimeMode.MODEL_ADAPTER:
        from orchestwin.models.model_proposals import ModelUserModelingAdapter
        from orchestwin.models.proposal_generation import build_proposal_generator

        return ModelUserModelingAdapter(build_proposal_generator(settings.model_config_file))

    if settings.mode is UserModelingRuntimeMode.FAKE_DETERMINISTIC:
        return FakeDeterministicUserModelingAdapter()

    raise RuntimeError(f"unsupported User Modeling runtime mode: {settings.mode}")


def build_user_modeling_runtime(
    settings: (UserModelingRuntimeSettings | None) = None,
) -> UserModelingRuntime:
    """Resolve User Modeling runtime dependencies without global state."""
    resolved_settings = settings if settings is not None else UserModelingRuntimeSettings()

    return UserModelingRuntime(
        mode=resolved_settings.mode,
        proposal_port=(build_user_modeling_proposal_port(resolved_settings)),
    )


__all__ = [
    "UserModelingRuntime",
    "UserModelingRuntimeMode",
    "UserModelingRuntimeSettings",
    "build_user_modeling_proposal_port",
    "build_user_modeling_runtime",
]
