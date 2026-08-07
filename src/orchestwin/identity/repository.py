"""Identity repository ports."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)


class UserRepository(Protocol):
    """Persistence operations required by identity use cases."""

    async def add(self, user: UserAccount) -> UserAccount:
        """Persist a user account."""

    async def get_by_id(
        self,
        user_id: UUID,
    ) -> UserAccount | None:
        """Return an account by identifier."""

    async def get_by_email(
        self,
        email: NormalizedEmail,
    ) -> UserAccount | None:
        """Return an account by normalized email."""
