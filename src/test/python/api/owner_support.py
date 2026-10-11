from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-000000128001")
NOW = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("training-owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
