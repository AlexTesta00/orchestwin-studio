"""Runtime configuration for design proposal providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.models.design import DesignProposalPort
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter


class DesignRuntimeMode(StrEnum):
    """Design provider runtimes supported in the current milestone."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"


class DesignRuntimeSettings(BaseSettings):
    """Environment-backed design provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_DESIGN_",
        case_sensitive=False,
        extra="forbid",
    )

    mode: DesignRuntimeMode = DesignRuntimeMode.FAKE_DETERMINISTIC


@dataclass(frozen=True, slots=True)
class DesignRuntime:
    """Resolved design proposal runtime dependencies."""

    mode: DesignRuntimeMode
    proposal_port: DesignProposalPort


def build_design_proposal_port(
    settings: DesignRuntimeSettings,
) -> DesignProposalPort:
    """Build the configured design proposal provider."""
    if settings.mode is DesignRuntimeMode.FAKE_DETERMINISTIC:
        return FakeDeterministicDesignAdapter()

    raise RuntimeError(f"unsupported design runtime mode: {settings.mode}")


def build_design_runtime(
    settings: DesignRuntimeSettings | None = None,
) -> DesignRuntime:
    """Resolve design provider dependencies without mutable global state."""
    resolved = settings if settings is not None else DesignRuntimeSettings()

    return DesignRuntime(
        mode=resolved.mode,
        proposal_port=build_design_proposal_port(resolved),
    )


__all__ = [
    "DesignRuntime",
    "DesignRuntimeMode",
    "DesignRuntimeSettings",
    "build_design_proposal_port",
    "build_design_runtime",
]
