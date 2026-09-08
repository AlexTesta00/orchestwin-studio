"""Resolve runtime credentials consistently from process settings and the local dotenv file."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.exceptions import SettingsError

from orchestwin.identity.tokens import AccessTokenSettings, load_access_token_settings
from orchestwin.persistence.config import DatabaseSettings, load_database_settings


class RuntimeConfigurationError(RuntimeError):
    """Safe startup error whose message never contains configuration values."""


class _RuntimeCredentialPresence(BaseSettings):
    """Probe optional credentials with the same source precedence as the domain settings."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        env_ignore_empty=False,
    )

    database_url: SecretStr | None = Field(default=None, repr=False)
    auth_jwt_secret: SecretStr | None = Field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RuntimeConnectionSettings:
    """Validated configuration only; constructing it opens no database connection."""

    database: DatabaseSettings = field(repr=False)
    access_tokens: AccessTokenSettings = field(repr=False)


def load_runtime_connection_settings(
    *,
    env_file: str | Path | None = ".env",
) -> RuntimeConnectionSettings | None:
    """Resolve startup settings without populating or otherwise mutating os.environ.

    No credentials preserves the existing unconfigured/liveness-only runtime.
    Partial or invalid credentials fail explicitly instead of silently disabling
    application services. Existing database and JWT validators remain authoritative.
    """
    try:
        presence = _RuntimeCredentialPresence(_env_file=env_file)
    except (OSError, UnicodeError, ValidationError, SettingsError):
        raise RuntimeConfigurationError("RUNTIME_CONFIGURATION_UNREADABLE") from None

    credentials = (presence.database_url, presence.auth_jwt_secret)
    if all(value is None for value in credentials):
        return None
    if any(value is None or not value.get_secret_value().strip() for value in credentials):
        raise RuntimeConfigurationError(
            "RUNTIME_CONFIGURATION_INCOMPLETE: both ORCHESTWIN_DATABASE_URL and "
            "ORCHESTWIN_AUTH_JWT_SECRET must be non-empty"
        ) from None

    try:
        database = load_database_settings(env_file=env_file)
    except (OSError, UnicodeError, ValidationError, SettingsError):
        raise RuntimeConfigurationError("RUNTIME_DATABASE_CONFIGURATION_INVALID") from None

    try:
        access_tokens = load_access_token_settings(env_file=env_file)
    except (OSError, UnicodeError, ValidationError, SettingsError):
        raise RuntimeConfigurationError("RUNTIME_AUTH_CONFIGURATION_INVALID") from None

    return RuntimeConnectionSettings(database=database, access_tokens=access_tokens)
