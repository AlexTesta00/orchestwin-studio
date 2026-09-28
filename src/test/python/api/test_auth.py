"""API contract tests for local authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, AuthAttemptLimits
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
    IdentityApplicationService,
    IdentityUnitOfWork,
    LocalIdentityApplicationService,
)
from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.sessions import (
    IssuedRefreshToken,
    RefreshSession,
    digest_refresh_token,
)
from orchestwin.identity.tokens import (
    AccessTokenSettings,
    IssuedAccessToken,
    JwtAccessTokenService,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("00000000-0000-4000-8000-000000000002")
FAMILY_ID = UUID("00000000-0000-4000-8000-000000000003")
NOW = datetime.now(UTC)


@pytest.mark.parametrize(
    ("password", "code"),
    [("Abcde1!", "password_too_short"), ("x" * 1025, "password_too_long")],
)
def test_registration_validation_is_actionable_and_does_not_echo_password(password, code):
    with build_client(FakeIdentityService()) as client:
        response = client.post(
            "/api/v1/auth/register", json={"email": "owner@example.com", "password": password}
        )
    assert response.status_code == 422
    assert response.json()["detail"] == code
    assert password not in response.text
    assert "input" not in response.json()["errors"][0]


def unavailable_unit_of_work() -> IdentityUnitOfWork:
    raise AssertionError("a rejected registration must not open a transaction")


def build_policy_identity_service() -> LocalIdentityApplicationService:
    return LocalIdentityApplicationService(
        unit_of_work_factory=unavailable_unit_of_work,
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr("auth-api-test-secret-with-more-than-32-characters"),
                _env_file=None,
            )
        ),
    )


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("owner@example.com", "abcdefg1!", "password_missing_uppercase"),
        ("owner@example.com", "Abcdefg12", "password_missing_special"),
        ("owner@example.com", "Abcdefg h", "password_missing_special"),
        ("not-an-email", "Abcdef1!", "invalid_registration"),
    ],
)
def test_registration_reports_the_password_rule_that_failed(
    email: str,
    password: str,
    code: str,
) -> None:
    with build_client(build_policy_identity_service()) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": code}
    assert password not in response.text


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
        self.register_calls = 0
        self.login_calls = 0

    async def register(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        self.register_calls += 1
        return self.register_result

    async def login(
        self,
        *,
        email: str,
        password: str,
    ) -> AuthenticationResult:
        self.login_calls += 1
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
    service: IdentityApplicationService | None,
    attempt_limits: AuthAttemptLimits | None = None,
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
            auth_attempt_limits=attempt_limits,
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
                "password": ("Correct horse battery staple!"),
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
                "password": ("Correct horse battery staple!"),
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
                "password": ("Correct horse battery staple!"),
            },
        )

    assert health.status_code == 200
    assert registration.status_code == 503
    assert registration.json() == {"detail": "identity_service_unavailable"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


def failed_sign_in_service() -> FakeIdentityService:
    service = FakeIdentityService()
    service.login_result = AuthenticationResult(status=AuthenticationStatus.INVALID_CREDENTIALS)
    return service


def sign_in(client: TestClient, email: str) -> httpx2.Response:
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Wrong horse battery staple!"},
    )


def register(client: TestClient, email: str) -> httpx2.Response:
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Correct horse battery staple!"},
    )


def test_login_does_not_apply_the_registration_password_rule() -> None:
    service = FakeIdentityService()

    with build_client(service) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "legacy"},
        )

    assert response.status_code == 200
    assert service.login_calls == 1


def test_eleventh_failed_sign_in_for_one_email_is_limited_before_verification() -> None:
    service = failed_sign_in_service()
    clock = FakeClock()

    with build_client(service, AuthAttemptLimits(clock=clock)) as client:
        failures = [sign_in(client, " Owner@Example.COM ") for _ in range(10)]
        blocked = sign_in(client, "owner@example.com")
        other = sign_in(client, "other@example.com")
        clock.now += 600
        after_window = sign_in(client, "owner@example.com")

    assert [response.status_code for response in failures] == [401] * 10
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "too_many_attempts"}
    assert blocked.headers["retry-after"] == "600"
    assert other.status_code == 401
    assert after_window.status_code == 401
    assert service.login_calls == 12


def test_successful_sign_in_resets_the_email_counter() -> None:
    service = failed_sign_in_service()
    success = AuthenticationResult(
        status=AuthenticationStatus.AUTHENTICATED,
        authenticated=build_authenticated(),
    )
    failure = service.login_result

    with build_client(service, AuthAttemptLimits(clock=FakeClock())) as client:
        before = [sign_in(client, "owner@example.com") for _ in range(9)]
        service.login_result = success
        succeeded = sign_in(client, "owner@example.com")
        service.login_result = failure
        after = [sign_in(client, "owner@example.com") for _ in range(10)]
        blocked = sign_in(client, "owner@example.com")

    assert [response.status_code for response in before + after] == [401] * 19
    assert succeeded.status_code == 200
    assert blocked.status_code == 429


def test_failed_sign_ins_are_limited_per_client_address() -> None:
    service = failed_sign_in_service()
    limits = AuthAttemptLimits(login_client_limit=3, clock=FakeClock())

    with build_client(service, limits) as client:
        failures = [sign_in(client, f"user-{index}@example.com") for index in range(3)]
        blocked = sign_in(client, "fresh@example.com")

    assert [response.status_code for response in failures] == [401] * 3
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "600"
    assert service.login_calls == 3


def test_registrations_are_limited_per_client_address() -> None:
    service = FakeIdentityService()

    with build_client(service, AuthAttemptLimits(clock=FakeClock())) as client:
        accepted = [register(client, f"user-{index}@example.com") for index in range(20)]
        blocked = register(client, "late@example.com")

    assert [response.status_code for response in accepted] == [201] * 20
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "too_many_attempts"}
    assert blocked.headers["retry-after"] == "3600"
    assert service.register_calls == 20


def test_each_application_starts_with_empty_attempt_counters() -> None:
    service = failed_sign_in_service()
    limits = AuthAttemptLimits(login_email_limit=1, clock=FakeClock())

    with build_client(service, limits) as client:
        sign_in(client, "owner@example.com")
        blocked = sign_in(client, "owner@example.com")

    with build_client(service, limits) as client:
        fresh = sign_in(client, "owner@example.com")

    assert blocked.status_code == 429
    assert fresh.status_code == 401
