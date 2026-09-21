"""Runtime configuration for architecture proposal providers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from orchestwin.models.architecture import ArchitectureProposalPort
from orchestwin.models.fake_architecture import FakeDeterministicArchitectureAdapter


class ArchitectureRuntimeMode(StrEnum):
    """Architecture provider runtimes supported in the current milestone."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class ArchitectureRuntimeSettings(BaseSettings):
    """Environment-backed architecture provider configuration."""

    model_config = SettingsConfigDict(
        env_prefix="ORCHESTWIN_ARCHITECTURE_",
        case_sensitive=False,
        extra="forbid",
    )

    mode: ArchitectureRuntimeMode = ArchitectureRuntimeMode.FAKE_DETERMINISTIC
    model_config_file: Path | None = None


@dataclass(frozen=True, slots=True)
class ArchitectureRuntime:
    """Resolved architecture proposal runtime dependencies."""

    mode: ArchitectureRuntimeMode
    proposal_port: ArchitectureProposalPort


def build_architecture_proposal_port(
    settings: ArchitectureRuntimeSettings,
) -> ArchitectureProposalPort:
    """Build the configured architecture proposal provider."""
    if settings.mode is ArchitectureRuntimeMode.MODEL_ADAPTER:
        from orchestwin.models.model_proposals import ModelArchitectureAdapter
        from orchestwin.models.proposal_generation import build_proposal_generator

        return ModelArchitectureAdapter(build_proposal_generator(settings.model_config_file))

    if settings.mode is ArchitectureRuntimeMode.FAKE_DETERMINISTIC:
        return FakeDeterministicArchitectureAdapter()

    raise RuntimeError(f"unsupported architecture runtime mode: {settings.mode}")


def build_architecture_runtime(
    settings: ArchitectureRuntimeSettings | None = None,
) -> ArchitectureRuntime:
    """Resolve architecture dependencies without mutable global state."""
    resolved = settings if settings is not None else ArchitectureRuntimeSettings()

    return ArchitectureRuntime(
        mode=resolved.mode,
        proposal_port=build_architecture_proposal_port(resolved),
    )


__all__ = [
    "ArchitectureRuntime",
    "ArchitectureRuntimeMode",
    "ArchitectureRuntimeSettings",
    "build_architecture_proposal_port",
    "build_architecture_runtime",
]
