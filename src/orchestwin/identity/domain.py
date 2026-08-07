"""Immutable identity-domain values."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from email_validator import EmailNotValidError, validate_email


class InvalidEmailAddress(ValueError):
    """Raised when an email address cannot identify a local account."""


@dataclass(frozen=True, slots=True)
class NormalizedEmail:
    """Case-normalized, syntax-validated account email."""

    value: str

    @classmethod
    def parse(cls, raw_value: str) -> NormalizedEmail:
        """Validate and normalize an email without network deliverability checks."""
        candidate = raw_value.strip()

        if not candidate:
            raise InvalidEmailAddress("email address is required")

        try:
            result = validate_email(
                candidate,
                check_deliverability=False,
            )
        except EmailNotValidError as error:
            raise InvalidEmailAddress("email address is invalid") from error

        return cls(result.normalized.casefold())

    def __str__(self) -> str:
        """Return the normalized email value."""
        return self.value


@dataclass(frozen=True, slots=True)
class UserAccount:
    """Local user account independent from SQLAlchemy."""

    id: UUID
    email: NormalizedEmail
    password_hash: str = field(repr=False)
    is_active: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Protect account invariants at the domain boundary."""
        if not self.password_hash:
            raise ValueError("password hash must not be empty")

        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")


def create_user_account(
    *,
    email: NormalizedEmail,
    password_hash: str,
    user_id: UUID | None = None,
    created_at: datetime | None = None,
) -> UserAccount:
    """Create a new active local account."""
    timestamp = created_at or datetime.now(UTC)

    return UserAccount(
        id=user_id or uuid4(),
        email=email,
        password_hash=password_hash,
        is_active=True,
        created_at=timestamp,
        updated_at=timestamp,
    )
