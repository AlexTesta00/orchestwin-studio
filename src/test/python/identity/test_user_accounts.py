"""Tests for immutable local user accounts."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.identity.domain import (
    InvalidEmailAddress,
    NormalizedEmail,
    create_user_account,
)


def test_email_is_validated_and_case_normalized() -> None:
    """Create one stable identity key for equivalent email casing."""
    email = NormalizedEmail.parse("  Alex.Example@Example.COM  ")

    assert email.value == "alex.example@example.com"
    assert str(email) == "alex.example@example.com"


@pytest.mark.parametrize(
    "raw_email",
    [
        "",
        "not-an-email",
        "missing-domain@",
        "@missing-local.example",
    ],
)
def test_invalid_email_is_rejected(raw_email: str) -> None:
    """Reject values that cannot safely identify an account."""
    with pytest.raises(InvalidEmailAddress):
        NormalizedEmail.parse(raw_email)


def test_user_account_is_created_with_stable_values() -> None:
    """Create an immutable active user from validated inputs."""
    timestamp = datetime(
        2026,
        8,
        7,
        12,
        0,
        tzinfo=UTC,
    )
    user = create_user_account(
        user_id=UUID("00000000-0000-4000-8000-000000000001"),
        email=NormalizedEmail.parse("owner@example.com"),
        password_hash="$argon2id$test-hash",
        created_at=timestamp,
    )

    assert user.email.value == "owner@example.com"
    assert user.is_active is True
    assert user.created_at == timestamp
    assert user.updated_at == timestamp
    assert "test-hash" not in repr(user)
