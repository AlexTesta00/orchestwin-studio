"""Runtime configuration for requirements proposal providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.models.fake_requirements import (
    FakeDeterministicRequirementsAdapter,
)
from orchestwin.models.requirements import RequirementsProposalPort


class RequirementsRuntimeMode(StrEnum):
    """Requirements provider runtimes supported in the current milestone."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"


class RequirementsRuntimeSettings(BaseSettings):
    """Environment-backed requirements provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_REQUIREMENTS_",
        case_sensitive=False,
        extra="forbid",
    )

    mode: RequirementsRuntimeMode = RequirementsRuntimeMode.FAKE_DETERMINISTIC


@dataclass(frozen=True, slots=True)
class RequirementsRuntime:
    """Resolved requirements proposal runtime dependencies."""

    mode: RequirementsRuntimeMode
    proposal_port: RequirementsProposalPort


def build_requirements_proposal_port(
    settings: RequirementsRuntimeSettings,
) -> RequirementsProposalPort:
    """Build the configured requirements proposal provider."""
    if settings.mode is RequirementsRuntimeMode.FAKE_DETERMINISTIC:
        return FakeDeterministicRequirementsAdapter()

    raise RuntimeError(f"unsupported requirements runtime mode: {settings.mode}")


def build_requirements_runtime(
    settings: RequirementsRuntimeSettings | None = None,
) -> RequirementsRuntime:
    """Resolve requirements provider dependencies without global state."""
    resolved = settings if settings is not None else RequirementsRuntimeSettings()

    return RequirementsRuntime(
        mode=resolved.mode,
        proposal_port=build_requirements_proposal_port(resolved),
    )


__all__ = [
    "RequirementsRuntime",
    "RequirementsRuntimeMode",
    "RequirementsRuntimeSettings",
    "build_requirements_proposal_port",
    "build_requirements_runtime",
]
