"""Short-lived JWT access tokens for local authentication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AccessTokenSettings(BaseSettings):
    """Immutable JWT signing and validation configuration."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="ORCHESTWIN_AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    jwt_secret: SecretStr = Field(repr=False)
    jwt_issuer: str = "orchestwin-studio"
    jwt_audience: str = "orchestwin-api"
    access_token_lifetime_seconds: int = Field(
        default=900,
        ge=60,
        le=86400,
    )
    access_token_leeway_seconds: int = Field(
        default=5,
        ge=0,
        le=300,
    )

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(
        cls,
        value: SecretStr,
    ) -> SecretStr:
        """Require a sufficiently long HMAC secret."""
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT secret must contain at least 32 characters")

        return value

    @field_validator("jwt_issuer", "jwt_audience")
    @classmethod
    def validate_non_empty_identifier(
        cls,
        value: str,
    ) -> str:
        """Require stable non-empty issuer and audience values."""
        normalized = value.strip()

        if not normalized:
            raise ValueError("JWT issuer and audience must not be empty")

        return normalized

    @property
    def lifetime(self) -> timedelta:
        """Return the access-token lifetime."""
        return timedelta(seconds=self.access_token_lifetime_seconds)

    @property
    def signing_secret(self) -> str:
        """Return the secret only to the cryptographic adapter."""
        return self.jwt_secret.get_secret_value()


def load_access_token_settings(
    *,
    env_file: str | Path | None = ".env",
) -> AccessTokenSettings:
    """Load fresh access-token settings."""
    return AccessTokenSettings(_env_file=env_file)


class AccessTokenStatus(StrEnum):
    """Stable outcomes of access-token verification."""

    VALID = "valid"
    EXPIRED = "expired"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class AccessTokenPrincipal:
    """Authenticated identity extracted from a verified token."""

    user_id: UUID
    token_id: UUID
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Protect principal timestamp invariants."""
        if self.issued_at.tzinfo is None:
            raise ValueError("access-token issued_at must be timezone-aware")

        if self.expires_at.tzinfo is None:
            raise ValueError("access-token expires_at must be timezone-aware")

        if self.expires_at <= self.issued_at:
            raise ValueError("access token must expire after issuance")


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    """JWT returned to an authenticated client."""

    token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        """Reject empty tokens and naive timestamps."""
        if not self.token:
            raise ValueError("issued access token must not be empty")

        if self.expires_at.tzinfo is None:
            raise ValueError("access-token expiry must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AccessTokenVerification:
    """Typed result of JWT verification."""

    status: AccessTokenStatus
    principal: AccessTokenPrincipal | None = None

    def __post_init__(self) -> None:
        """Associate a principal only with a valid token."""
        is_valid = self.status is AccessTokenStatus.VALID

        if is_valid != (self.principal is not None):
            raise ValueError("only a valid token may contain a principal")


Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class JwtAccessTokenService:
    """Issue and verify HS256 access tokens with fixed policy."""

    ALGORITHM = "HS256"
    TOKEN_USE = "access"

    def __init__(
        self,
        settings: AccessTokenSettings,
        *,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._uuid_factory = uuid_factory

    def issue(
        self,
        *,
        user_id: UUID,
    ) -> IssuedAccessToken:
        """Issue a signed access token for one active user."""
        issued_at = self._current_time()
        expires_at = issued_at + self._settings.lifetime
        token_id = self._uuid_factory()

        payload = {
            "iss": self._settings.jwt_issuer,
            "aud": self._settings.jwt_audience,
            "sub": str(user_id),
            "jti": str(token_id),
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            "token_use": self.TOKEN_USE,
        }

        encoded = jwt.encode(
            payload,
            self._settings.signing_secret,
            algorithm=self.ALGORITHM,
        )

        return IssuedAccessToken(
            token=encoded,
            expires_at=expires_at,
        )

    def verify(
        self,
        token: str,
    ) -> AccessTokenVerification:
        """Verify a JWT without exposing library exceptions."""
        if not token:
            return AccessTokenVerification(status=AccessTokenStatus.INVALID)

        try:
            payload = jwt.decode(
                token,
                self._settings.signing_secret,
                algorithms=[self.ALGORITHM],
                audience=self._settings.jwt_audience,
                issuer=self._settings.jwt_issuer,
                leeway=(self._settings.access_token_leeway_seconds),
                options={
                    "require": [
                        "aud",
                        "exp",
                        "iat",
                        "iss",
                        "jti",
                        "nbf",
                        "sub",
                        "token_use",
                    ],
                },
            )
        except ExpiredSignatureError:
            return AccessTokenVerification(status=AccessTokenStatus.EXPIRED)
        except InvalidTokenError:
            return AccessTokenVerification(status=AccessTokenStatus.INVALID)

        if payload.get("token_use") != self.TOKEN_USE:
            return AccessTokenVerification(status=AccessTokenStatus.INVALID)

        try:
            principal = AccessTokenPrincipal(
                user_id=UUID(str(payload["sub"])),
                token_id=UUID(str(payload["jti"])),
                issued_at=self._timestamp(payload["iat"]),
                expires_at=self._timestamp(payload["exp"]),
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return AccessTokenVerification(status=AccessTokenStatus.INVALID)

        return AccessTokenVerification(
            status=AccessTokenStatus.VALID,
            principal=principal,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected clock value."""
        current = self._clock()

        if current.tzinfo is None:
            raise ValueError("access-token clock must be timezone-aware")

        return current.astimezone(UTC)

    @staticmethod
    def _timestamp(value: object) -> datetime:
        """Convert a decoded NumericDate into a UTC datetime."""
        if isinstance(value, bool):
            raise TypeError("JWT timestamp must not be boolean")

        if not isinstance(value, int | float):
            raise TypeError("JWT timestamp must be numeric")

        return datetime.fromtimestamp(
            value,
            tz=UTC,
        )
