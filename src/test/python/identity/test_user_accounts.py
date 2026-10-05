"""Tests for immutable local user accounts."""

from dataclasses import fields, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.identity.domain import (
    GuidanceMode,
    InvalidEmailAddress,
    NormalizedEmail,
    UserAccount,
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


def test_the_guidance_modes_are_exactly_guided_and_expert() -> None:
    assert [mode.value for mode in GuidanceMode] == ["GUIDED", "EXPERT"]
    assert GuidanceMode("GUIDED") is GuidanceMode.GUIDED
    assert GuidanceMode("EXPERT") is GuidanceMode.EXPERT

    for value in ("guided", "Expert", "", " GUIDED", "NOVICE"):
        with pytest.raises(ValueError):
            GuidanceMode(value)


def test_a_new_account_has_not_chosen_a_guidance_mode() -> None:
    user = create_user_account(
        user_id=UUID("00000000-0000-4000-8000-000000000001"),
        email=NormalizedEmail.parse("owner@example.com"),
        password_hash="$argon2id$test-hash",
        created_at=datetime(2026, 10, 5, 9, 0, tzinfo=UTC),
    )
    chosen = replace(user, guidance_mode=GuidanceMode.EXPERT)

    assert [field.name for field in fields(UserAccount)][-1] == "guidance_mode"
    assert user.guidance_mode is None
    assert chosen.guidance_mode is GuidanceMode.EXPERT
    assert replace(chosen, guidance_mode=None) == user
    assert chosen != user
