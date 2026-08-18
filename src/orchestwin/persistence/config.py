"""Typed PostgreSQL configuration for the persistence boundary."""

from pathlib import Path
from typing import ClassVar

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class DatabaseSettings(BaseSettings):
    """Immutable SQLAlchemy and connection-pool configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_DATABASE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    url: SecretStr = Field(repr=False)
    echo: bool = False
    pool_size: int = Field(default=5, ge=1, le=50)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    pool_recycle_seconds: int = Field(default=1800, ge=0, le=86400)

    @field_validator("url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Require an explicit PostgreSQL URL using the Psycopg 3 driver."""
        raw_value = value.get_secret_value()

        try:
            parsed_url = make_url(raw_value)
        except ArgumentError as error:
            raise ValueError("database URL is not a valid SQLAlchemy URL") from error

        if parsed_url.get_backend_name() != "postgresql":
            raise ValueError("database URL must use PostgreSQL")

        if parsed_url.get_driver_name() != "psycopg":
            raise ValueError("database URL must use the psycopg driver")

        if not parsed_url.database:
            raise ValueError("database URL must select a database")

        return value

    @property
    def sqlalchemy_url(self) -> URL:
        """Return the validated SQLAlchemy URL for infrastructure adapters."""
        return make_url(self.url.get_secret_value())


def load_database_settings(
    *,
    env_file: str | Path | None = ".env",
) -> DatabaseSettings:
    """Load a fresh database-settings value from explicit sources."""
    return DatabaseSettings(_env_file=env_file)
