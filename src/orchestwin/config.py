"""Typed application configuration for the OrchesTwin Studio backend."""

from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Self

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeEnvironment(StrEnum):
    """Supported backend runtime environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Log levels accepted by the backend configuration boundary."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ApplicationSettings(BaseSettings):
    """Immutable settings loaded from environment variables or a dotenv file."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    application_name: str = "OrchesTwin Studio API"
    environment: RuntimeEnvironment = RuntimeEnvironment.DEVELOPMENT
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO
    api_prefix: str = "/api/v1"

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Normalize and validate the versioned API prefix."""
        normalized = value.strip().rstrip("/")
        if not normalized or not normalized.startswith("/"):
            raise ValueError("api_prefix must be an absolute non-root path")
        return normalized

    @model_validator(mode="after")
    def reject_debug_in_production(self) -> Self:
        """Prevent accidental production startup with debug mode enabled."""
        if self.environment is RuntimeEnvironment.PRODUCTION and self.debug:
            raise ValueError("debug must be disabled in production")
        return self


def load_settings(*, env_file: str | Path | None = ".env") -> ApplicationSettings:
    """Load a fresh immutable settings object from explicit configuration sources."""
    return ApplicationSettings(_env_file=env_file)
