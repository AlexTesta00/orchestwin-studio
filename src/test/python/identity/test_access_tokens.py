"""Tests for short-lived JWT access tokens."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr, ValidationError

from orchestwin.identity.tokens import (
    AccessTokenSettings,
    AccessTokenStatus,
    JwtAccessTokenService,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
TOKEN_ID = UUID("00000000-0000-4000-8000-000000000002")
JWT_SECRET = "development-only-jwt-secret-with-more-than-32-characters"


def build_settings(
    *,
    audience: str = "orchestwin-api",
) -> AccessTokenSettings:
    """Create deterministic JWT configuration."""
    return AccessTokenSettings(
        jwt_secret=SecretStr(JWT_SECRET),
        jwt_issuer="orchestwin-studio",
        jwt_audience=audience,
        access_token_lifetime_seconds=900,
        access_token_leeway_seconds=0,
        _env_file=None,
    )


def test_jwt_secret_must_be_sufficiently_long() -> None:
    """Reject undersized HMAC secrets."""
    with pytest.raises(ValidationError):
        AccessTokenSettings(
            jwt_secret=SecretStr("too-short"),
            _env_file=None,
        )


def test_jwt_secret_is_not_exposed_in_settings_repr() -> None:
    """Keep the signing secret out of ordinary diagnostics."""
    settings = build_settings()

    assert JWT_SECRET not in repr(settings)


def test_access_token_contains_required_verified_claims() -> None:
    """Issue and verify one deterministic access token."""
    issued_at = datetime.now(UTC)
    service = JwtAccessTokenService(
        build_settings(),
        clock=lambda: issued_at,
        uuid_factory=lambda: TOKEN_ID,
    )

    issued = service.issue(user_id=USER_ID)
    verification = service.verify(issued.token)

    assert verification.status is AccessTokenStatus.VALID
    assert verification.principal is not None
    assert verification.principal.user_id == USER_ID
    assert verification.principal.token_id == TOKEN_ID
    assert verification.principal.issued_at == issued_at.replace(microsecond=0)
    assert verification.principal.expires_at == (issued_at + timedelta(minutes=15)).replace(
        microsecond=0
    )
    assert issued.expires_at == (issued_at + timedelta(minutes=15))


def test_expired_access_token_returns_typed_status() -> None:
    """Reject tokens whose expiration is already in the past."""
    issued_at = datetime.now(UTC) - timedelta(hours=1)
    settings = AccessTokenSettings(
        jwt_secret=SecretStr(JWT_SECRET),
        access_token_lifetime_seconds=60,
        access_token_leeway_seconds=0,
        _env_file=None,
    )
    service = JwtAccessTokenService(
        settings,
        clock=lambda: issued_at,
        uuid_factory=lambda: TOKEN_ID,
    )

    issued = service.issue(user_id=USER_ID)
    verification = service.verify(issued.token)

    assert verification.status is AccessTokenStatus.EXPIRED
    assert verification.principal is None


def test_tampered_access_token_is_invalid() -> None:
    """Reject a token whose signature no longer matches."""
    service = JwtAccessTokenService(
        build_settings(),
        uuid_factory=lambda: TOKEN_ID,
    )
    issued = service.issue(user_id=USER_ID)

    verification = service.verify(f"{issued.token}tampered")

    assert verification.status is AccessTokenStatus.INVALID
    assert verification.principal is None


def test_token_for_another_audience_is_invalid() -> None:
    """Bind access tokens to the configured API audience."""
    issuer = JwtAccessTokenService(
        build_settings(audience="other-api"),
        uuid_factory=lambda: TOKEN_ID,
    )
    verifier = JwtAccessTokenService(build_settings(audience="orchestwin-api"))

    issued = issuer.issue(user_id=USER_ID)
    verification = verifier.verify(issued.token)

    assert verification.status is AccessTokenStatus.INVALID


def test_non_access_jwt_is_invalid() -> None:
    """Reject correctly signed JWTs created for another token use."""
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "orchestwin-studio",
            "aud": "orchestwin-api",
            "sub": str(USER_ID),
            "jti": str(TOKEN_ID),
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=15),
            "token_use": "refresh",
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    service = JwtAccessTokenService(build_settings())
    verification = service.verify(token)

    assert verification.status is AccessTokenStatus.INVALID
    assert verification.principal is None
