"""Identity and Access application services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.exc import IntegrityError

from orchestwin.identity.domain import (
    InvalidEmailAddress,
    NormalizedEmail,
    UserAccount,
    create_user_account,
)
from orchestwin.identity.passwords import (
    Argon2PasswordService,
    PasswordPolicyError,
)
from orchestwin.identity.repository import UserRepository
from orchestwin.identity.sessions import (
    IssuedRefreshToken,
    RefreshRotationStatus,
    RefreshSessionRepository,
    RefreshSessionService,
)
from orchestwin.identity.tokens import (
    AccessTokenStatus,
    IssuedAccessToken,
    JwtAccessTokenService,
)


class AuthenticationStatus(StrEnum):
    """Stable outcomes of identity application use cases."""

    AUTHENTICATED = "authenticated"
    EMAIL_ALREADY_REGISTERED = "email_already_registered"
    INVALID_REGISTRATION = "invalid_registration"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_REFRESH_TOKEN = "invalid_refresh_token"
    EXPIRED_REFRESH_TOKEN = "expired_refresh_token"
    REFRESH_TOKEN_REUSE_DETECTED = "refresh_token_reuse_detected"


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Credentials and user returned after successful authentication."""

    user: UserAccount
    access_token: IssuedAccessToken
    refresh_token: IssuedRefreshToken


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    """Typed authentication use-case result."""

    status: AuthenticationStatus
    authenticated: AuthenticatedSession | None = None

    def __post_init__(self) -> None:
        """Associate credentials only with successful authentication."""
        succeeded = self.status is AuthenticationStatus.AUTHENTICATED

        if succeeded != (self.authenticated is not None):
            raise ValueError("only authenticated results may contain credentials")


class IdentityUnitOfWork(Protocol):
    """Transactional repository boundary for identity use cases."""

    @property
    def users(self) -> UserRepository:
        """Return the user repository."""

    @property
    def refresh_sessions(
        self,
    ) -> RefreshSessionRepository:
        """Return the refresh-session repository."""

    async def __aenter__(self) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


IdentityUnitOfWorkFactory = Callable[
    [],
    IdentityUnitOfWork,
]


class IdentityApplicationService(Protocol):
    """Operations exposed to the HTTP identity adapter."""

    async def register(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        """Register and authenticate a local user."""

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        """Authenticate an existing local user."""

    async def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationResult:
        """Rotate a refresh token and issue a new access token."""

    async def logout(
        self,
        refresh_token: str,
    ) -> bool:
        """Revoke the current refresh session."""

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        """Resolve an active user from an access token."""


class LocalIdentityApplicationService:
    """Local account use cases composed from explicit ports."""

    DUMMY_PASSWORD = "not a real OrchesTwin account password"

    def __init__(
        self,
        *,
        unit_of_work_factory: IdentityUnitOfWorkFactory,
        password_service: Argon2PasswordService,
        access_token_service: JwtAccessTokenService,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._password_service = password_service
        self._access_token_service = access_token_service
        self._dummy_password_hash = password_service.hash(self.DUMMY_PASSWORD)

    async def register(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        """Create an account and its initial session."""
        try:
            normalized_email = NormalizedEmail.parse(email)
            password_hash = self._password_service.hash(password)
        except (
            InvalidEmailAddress,
            PasswordPolicyError,
        ):
            return AuthenticationResult(status=(AuthenticationStatus.INVALID_REGISTRATION))

        try:
            async with self._unit_of_work_factory() as unit:
                existing = await unit.users.get_by_email(normalized_email)

                if existing is not None:
                    return AuthenticationResult(
                        status=(AuthenticationStatus.EMAIL_ALREADY_REGISTERED)
                    )

                user = create_user_account(
                    email=normalized_email,
                    password_hash=password_hash,
                )
                persisted = await unit.users.add(user)
                authenticated = await self._issue_session(
                    unit=unit,
                    user=persisted,
                )
        except IntegrityError:
            return AuthenticationResult(status=(AuthenticationStatus.EMAIL_ALREADY_REGISTERED))

        return AuthenticationResult(
            status=AuthenticationStatus.AUTHENTICATED,
            authenticated=authenticated,
        )

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        """Verify local credentials and create a session."""
        try:
            normalized_email = NormalizedEmail.parse(email)
        except InvalidEmailAddress:
            normalized_email = None

        async with self._unit_of_work_factory() as unit:
            user = (
                await unit.users.get_by_email(normalized_email)
                if normalized_email is not None
                else None
            )

            encoded_hash = user.password_hash if user is not None else self._dummy_password_hash
            verification = self._password_service.verify(
                password,
                encoded_hash,
            )

            if user is None or not user.is_active or not verification.valid:
                return AuthenticationResult(status=(AuthenticationStatus.INVALID_CREDENTIALS))

            if verification.replacement_hash is not None:
                await unit.users.update_password_hash(
                    user_id=user.id,
                    password_hash=(verification.replacement_hash),
                )

            authenticated = await self._issue_session(
                unit=unit,
                user=user,
            )

        return AuthenticationResult(
            status=AuthenticationStatus.AUTHENTICATED,
            authenticated=authenticated,
        )

    async def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationResult:
        """Rotate a refresh token and issue new credentials."""
        async with self._unit_of_work_factory() as unit:
            refresh_service = RefreshSessionService(unit.refresh_sessions)
            rotation = await refresh_service.rotate(refresh_token)

            if rotation.status is RefreshRotationStatus.INVALID:
                return AuthenticationResult(status=(AuthenticationStatus.INVALID_REFRESH_TOKEN))

            if rotation.status is RefreshRotationStatus.EXPIRED:
                return AuthenticationResult(status=(AuthenticationStatus.EXPIRED_REFRESH_TOKEN))

            if rotation.status is RefreshRotationStatus.REUSE_DETECTED:
                return AuthenticationResult(
                    status=(AuthenticationStatus.REFRESH_TOKEN_REUSE_DETECTED)
                )

            if rotation.issued_token is None:
                raise RuntimeError("successful refresh did not issue a token")

            user = await unit.users.get_by_id(rotation.issued_token.session.user_id)

            if user is None or not user.is_active:
                await refresh_service.revoke(
                    rotation.issued_token.token,
                    reason="user_unavailable",
                )
                return AuthenticationResult(status=(AuthenticationStatus.INVALID_REFRESH_TOKEN))

            access_token = self._access_token_service.issue(user_id=user.id)

            authenticated = AuthenticatedSession(
                user=user,
                access_token=access_token,
                refresh_token=(rotation.issued_token),
            )

        return AuthenticationResult(
            status=AuthenticationStatus.AUTHENTICATED,
            authenticated=authenticated,
        )

    async def logout(
        self,
        refresh_token: str,
    ) -> bool:
        """Revoke one current refresh session."""
        async with self._unit_of_work_factory() as unit:
            refresh_service = RefreshSessionService(unit.refresh_sessions)
            return await refresh_service.revoke(refresh_token)

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        """Resolve an active account from a verified JWT."""
        verification = self._access_token_service.verify(access_token)

        if verification.status is not AccessTokenStatus.VALID or verification.principal is None:
            return None

        async with self._unit_of_work_factory() as unit:
            user = await unit.users.get_by_id(verification.principal.user_id)

        if user is None or not user.is_active:
            return None

        return user

    async def _issue_session(
        self,
        *,
        unit: IdentityUnitOfWork,
        user: UserAccount,
    ) -> AuthenticatedSession:
        """Issue access and refresh credentials."""
        refresh_token = await RefreshSessionService(unit.refresh_sessions).issue(user_id=user.id)
        access_token = self._access_token_service.issue(user_id=user.id)

        return AuthenticatedSession(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
        )
