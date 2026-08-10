"""API contract tests for local authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import (
    ApplicationRuntime,
)
from orchestwin.config import (
    ApplicationSettings,
    LogLevel,
    RuntimeEnvironment,
)
from orchestwin.identity.application import (
    AuthenticatedSession,
    AuthenticationResult,
    AuthenticationStatus,
)
from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.identity.sessions import (
    IssuedRefreshToken,
    RefreshSession,
    digest_refresh_token,
)
from orchestwin.identity.tokens import (
    IssuedAccessToken,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000002")
FAMILY_ID = UUID("00000000-0000-4000-8000-000000000003")
NOW = datetime.now(UTC)


def build_user() -> UserAccount:
    """Create a deterministic safe API user."""
    return UserAccount(
        id=USER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def build_authenticated(
    *,
    refresh_token: str = "new-refresh-token",
) -> AuthenticatedSession:
    """Create deterministic credentials for API tests."""
    user = build_user()
    refresh_session = RefreshSession(
        id=SESSION_ID,
        user_id=USER_ID,
        token_family_id=FAMILY_ID,
        refresh_token_digest=(digest_refresh_token(refresh_token)),
        expires_at=NOW + timedelta(days=30),
        created_at=NOW,
        last_used_at=NOW,
    )

    return AuthenticatedSession(
        user=user,
        access_token=IssuedAccessToken(
            token="signed-access-token",
            expires_at=NOW + timedelta(minutes=15),
        ),
        refresh_token=IssuedRefreshToken(
            token=refresh_token,
            session=refresh_session,
        ),
    )


class FakeIdentityService:
    """Configurable identity service double."""

    def __init__(self) -> None:
        self.register_result = AuthenticationResult(
            status=AuthenticationStatus.AUTHENTICATED,
            authenticated=build_authenticated(),
        )
        self.login_result = self.register_result
        self.refresh_result = self.register_result
        self.current_user_result: UserAccount | None = build_user()
        self.logout_tokens: list[str] = []

    async def register(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        return self.register_result

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        return self.login_result

    async def refresh(
        self,
        refresh_token: str,
    ) -> AuthenticationResult:
        return self.refresh_result

    async def logout(
        self,
        refresh_token: str,
    ) -> bool:
        self.logout_tokens.append(refresh_token)
        return True

    async def current_user(
        self,
        access_token: str,
    ) -> UserAccount | None:
        if access_token != "signed-access-token":
            return None

        return self.current_user_result


def build_client(
    service: FakeIdentityService | None,
) -> TestClient:
    """Create an API client with explicit identity adapters."""
    settings = ApplicationSettings(
        application_name="OrchesTwin Test API",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix="/api/v1",
        cors_allowed_origins=("http://127.0.0.1:5173",),
        cors_allow_credentials=True,
        _env_file=None,
    )
    auth_settings = AuthApiSettings(
        refresh_cookie_name=("orchestwin_refresh"),
        refresh_cookie_path="/api/v1/auth",
        refresh_cookie_secure=False,
        refresh_cookie_same_site="lax",
        refresh_cookie_max_age_seconds=2592000,
        _env_file=None,
    )
    runtime = ApplicationRuntime(identity_service=service)

    return TestClient(
        create_app(
            settings,
            runtime=runtime,
            auth_settings=auth_settings,
        )
    )


def test_registration_sets_http_only_refresh_cookie() -> None:
    """Return an access token while keeping refresh state in a cookie."""
    service = FakeIdentityService()

    with build_client(service) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": ("correct horse battery staple"),
            },
        )

    assert response.status_code == 201
    assert response.json()["access_token"] == ("signed-access-token")
    assert response.json()["user"]["email"] == ("owner@example.com")

    set_cookie = response.headers["set-cookie"].casefold()

    assert "orchestwin_refresh=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


def test_duplicate_registration_returns_conflict() -> None:
    """Expose one stable duplicate-email response."""
    service = FakeIdentityService()
    service.register_result = AuthenticationResult(
        status=(AuthenticationStatus.EMAIL_ALREADY_REGISTERED)
    )

    with build_client(service) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": ("correct horse battery staple"),
            },
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "email_already_registered"}


def test_login_uses_generic_unauthorized_response() -> None:
    """Do not expose the reason credentials failed."""
    service = FakeIdentityService()
    service.login_result = AuthenticationResult(status=(AuthenticationStatus.INVALID_CREDENTIALS))

    with build_client(service) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "owner@example.com",
                "password": ("incorrect horse battery staple"),
            },
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_authentication"}
    assert response.headers["www-authenticate"] == ("Bearer")


def test_refresh_rotates_cookie_and_returns_access_token() -> None:
    """Accept the cookie and replace it after successful rotation."""
    service = FakeIdentityService()
    service.refresh_result = AuthenticationResult(
        status=AuthenticationStatus.AUTHENTICATED,
        authenticated=build_authenticated(refresh_token="rotated-refresh-token"),
    )

    with build_client(service) as client:
        client.cookies.set(
            "orchestwin_refresh",
            "previous-refresh-token",
            path="/api/v1/auth",
        )
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"] == ("signed-access-token")
    assert "rotated-refresh-token" in response.headers["set-cookie"]


def test_invalid_refresh_clears_cookie() -> None:
    """Delete unusable refresh state from the browser."""
    service = FakeIdentityService()
    service.refresh_result = AuthenticationResult(
        status=(AuthenticationStatus.INVALID_REFRESH_TOKEN)
    )

    with build_client(service) as client:
        client.cookies.set(
            "orchestwin_refresh",
            "invalid-refresh-token",
            path="/api/v1/auth",
        )
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert "max-age=0" in (response.headers["set-cookie"].casefold())


def test_logout_is_idempotent_and_deletes_cookie() -> None:
    """Revoke a known session without exposing whether it existed."""
    service = FakeIdentityService()

    with build_client(service) as client:
        client.cookies.set(
            "orchestwin_refresh",
            "current-refresh-token",
            path="/api/v1/auth",
        )
        response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert service.logout_tokens == ["current-refresh-token"]
    assert "max-age=0" in (response.headers["set-cookie"].casefold())


def test_me_requires_valid_bearer_token() -> None:
    """Return the current account only for a valid access token."""
    service = FakeIdentityService()

    with build_client(service) as client:
        valid = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": ("Bearer signed-access-token"),
            },
        )
        missing = client.get("/api/v1/auth/me")

    assert valid.status_code == 200
    assert valid.json()["id"] == str(USER_ID)
    assert missing.status_code == 401


def test_authentication_endpoints_report_unavailable_runtime() -> None:
    """Keep health available while identity infrastructure is absent."""
    with build_client(None) as client:
        health = client.get("/api/v1/health")
        registration = client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.com",
                "password": ("correct horse battery staple"),
            },
        )

    assert health.status_code == 200
    assert registration.status_code == 503
    assert registration.json() == {"detail": "identity_service_unavailable"}
