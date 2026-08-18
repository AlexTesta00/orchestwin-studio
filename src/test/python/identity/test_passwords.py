"""Tests for the local Argon2 password service."""

import pytest

from orchestwin.identity.passwords import (
    Argon2PasswordService,
    PasswordPolicy,
    PasswordPolicyError,
    PasswordPolicyViolation,
)


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short",
        "fourteen-char!",
    ],
)
def test_password_policy_rejects_short_values(
    password: str,
) -> None:
    """Require at least fifteen Unicode code points."""
    policy = PasswordPolicy()

    with pytest.raises(PasswordPolicyError) as captured:
        policy.validate(password)

    assert captured.value.violation is (PasswordPolicyViolation.TOO_SHORT)


def test_password_policy_rejects_excessive_values() -> None:
    """Bound hashing work without silently truncating passwords."""
    policy = PasswordPolicy(maximum_length=64)

    with pytest.raises(PasswordPolicyError) as captured:
        policy.validate("a" * 65)

    assert captured.value.violation is (PasswordPolicyViolation.TOO_LONG)


def test_password_policy_accepts_unicode_spaces_and_passphrases() -> None:
    """Avoid arbitrary composition rules."""
    password = "corretto cavallo 🔐 batteria graffetta"

    assert PasswordPolicy().validate(password) == password


def test_argon2_service_hashes_and_verifies_password() -> None:
    """Store only a salted Argon2 hash and verify the original input."""
    service = Argon2PasswordService()
    password = "correct horse battery staple"

    encoded_hash = service.hash(password)
    verification = service.verify(
        password,
        encoded_hash,
    )

    assert encoded_hash != password
    assert encoded_hash.startswith("$argon2")
    assert verification.valid is True


def test_argon2_service_rejects_wrong_password() -> None:
    """Return one generic invalid result for a wrong password."""
    service = Argon2PasswordService()
    encoded_hash = service.hash("correct horse battery staple")

    verification = service.verify(
        "incorrect horse battery staple",
        encoded_hash,
    )

    assert verification.valid is False
    assert verification.replacement_hash is None


def test_argon2_service_rejects_unknown_hash_format() -> None:
    """Treat corrupted or unsupported stored hashes as invalid credentials."""
    service = Argon2PasswordService()

    verification = service.verify(
        "correct horse battery staple",
        "not-a-password-hash",
    )

    assert verification.valid is False
    assert verification.replacement_hash is None
