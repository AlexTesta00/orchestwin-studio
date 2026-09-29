"""Password policy and Argon2 hashing service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


class PasswordPolicyViolation(StrEnum):
    """Stable reasons for rejecting a proposed password."""

    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    MISSING_UPPERCASE = "missing_uppercase"
    MISSING_SPECIAL = "missing_special"


class PasswordPolicyError(ValueError):
    """Raised when a password violates the local policy."""

    def __init__(
        self,
        violation: PasswordPolicyViolation,
    ) -> None:
        self.violation = violation
        super().__init__(violation.value)


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    minimum_length: int = 8
    maximum_length: int = 1024

    def validate(self, password: str) -> str:
        """Validate the complete password without trimming or truncating."""
        if len(password) < self.minimum_length:
            raise PasswordPolicyError(PasswordPolicyViolation.TOO_SHORT)

        if len(password) > self.maximum_length:
            raise PasswordPolicyError(PasswordPolicyViolation.TOO_LONG)

        if not any(character.isupper() for character in password):
            raise PasswordPolicyError(PasswordPolicyViolation.MISSING_UPPERCASE)

        if all(character.isalnum() or character.isspace() for character in password):
            raise PasswordPolicyError(PasswordPolicyViolation.MISSING_SPECIAL)

        return password


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    """Result of password verification and optional hash upgrading."""

    valid: bool
    replacement_hash: str | None = None


class Argon2PasswordService:
    """Hash and verify passwords using pwdlib's recommended Argon2 profile."""

    def __init__(
        self,
        *,
        policy: PasswordPolicy | None = None,
        password_hash: PasswordHash | None = None,
    ) -> None:
        self._policy = policy or PasswordPolicy()
        self._password_hash = password_hash or PasswordHash.recommended()

    def hash(self, password: str) -> str:
        """Validate and hash a new password."""
        validated_password = self._policy.validate(password)
        return self._password_hash.hash(validated_password)

    def verify(
        self,
        password: str,
        encoded_hash: str,
    ) -> PasswordVerification:
        """Verify a password without exposing hash-format failures."""
        try:
            valid, replacement_hash = self._password_hash.verify_and_update(
                password,
                encoded_hash,
            )
        except UnknownHashError:
            return PasswordVerification(valid=False)

        return PasswordVerification(
            valid=valid,
            replacement_hash=(replacement_hash if valid else None),
        )
