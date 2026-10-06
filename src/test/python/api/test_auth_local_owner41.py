from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, AuthAttemptLimits
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import AccessMode, ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.application import (
    AuthenticationResult,
    AuthenticationStatus,
    IdentityApplicationService,
    LocalOwnerUnavailable,
)
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from src.test.python.api.test_auth import (
    USER_ID,
    FakeClock,
    FakeIdentityService,
    register,
    sign_in,
)
from src.test.python.api.test_project_api import FakeProjectService
from src.test.python.identity.test_identity_application import (
    build_service as build_identity_service,
)

AUTH = "/api/v1/auth"
LOCAL_OWNER_ID = UUID("00000000-0000-4000-8000-000000000041")
LOCAL_EMAIL = "local-owner@example.com"
NOW = datetime.now(UTC)
BEARER = {"Authorization": "Bearer signed-access-token"}
INVALID_AUTHENTICATION = (401, {"detail": "invalid_authentication"})
STUDIO_ORIGINS = ("http://127.0.0.1:8080", "http://127.0.0.1:5173")
FROM_UT = {"Host": "127.0.0.1:8000"}
FROM_WEB_PROXY = {
    "Host": "127.0.0.1:8000",
    "Origin": "http://127.0.0.1:8080",
    "Sec-Fetch-Site": "same-origin",
}
INVALID_REFRESH = AuthenticationResult(status=AuthenticationStatus.INVALID_REFRESH_TOKEN)


@pytest.fixture(autouse=True)
def isolate_studio_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)


def local_identity_service() -> FakeIdentityService:
    service = FakeIdentityService()
    service.local_owner_result = UserAccount(
        id=LOCAL_OWNER_ID,
        email=NormalizedEmail(LOCAL_EMAIL),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )
    return service


def build_client(
    service: IdentityApplicationService | None,
    access_mode: AccessMode,
    *,
    local_owner_email: str | None = None,
    project_service: FakeProjectService | None = None,
    attempt_limits: AuthAttemptLimits | None = None,
) -> TestClient:
    settings = ApplicationSettings(
        application_name="OrchesTwin Local Owner Test API",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix="/api/v1",
        cors_allowed_origins=STUDIO_ORIGINS,
        access_mode=access_mode,
        local_owner_email=local_owner_email,
        _env_file=None,
    )

    return TestClient(
        create_app(
            settings,
            runtime=ApplicationRuntime(identity_service=service, project_service=project_service),
            auth_settings=AuthApiSettings(_env_file=None),
            auth_attempt_limits=attempt_limits,
        ),
        headers=dict(FROM_UT),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (AccessMode.ACCOUNTS, {"access_mode": "ACCOUNTS", "registration_open": True}),
        (AccessMode.LOCAL_OWNER, {"access_mode": "LOCAL_OWNER", "registration_open": False}),
    ],
)
def test_the_access_mode_is_public_in_both_modes(
    mode: AccessMode,
    expected: dict[str, object],
) -> None:
    with build_client(None, mode) as client:
        response = client.get(AUTH + "/mode")

    assert (response.status_code, response.json()) == (200, expected)


def test_the_access_mode_is_published_in_the_contract() -> None:
    with build_client(None, AccessMode.ACCOUNTS) as client:
        document = client.get("/api/v1/openapi.json").json()

    operation = document["paths"][AUTH + "/mode"]["get"]
    schema = document["components"]["schemas"]["AccessModeResponse"]
    assert operation["operationId"] == "getAccessMode"
    assert "security" not in operation
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccessModeResponse"
    }
    assert schema["required"] == ["access_mode", "registration_open"]
    assert schema["properties"]["access_mode"]["enum"] == ["ACCOUNTS", "LOCAL_OWNER"]
    assert schema["properties"]["registration_open"]["type"] == "boolean"


def test_registration_and_sign_in_do_not_exist_in_local_mode() -> None:
    service = local_identity_service()
    limits = AuthAttemptLimits(
        login_email_limit=1,
        login_client_limit=1,
        registration_client_limit=1,
        clock=FakeClock(),
    )

    with build_client(service, AccessMode.LOCAL_OWNER, attempt_limits=limits) as client:
        refused = [
            *(register(client, "owner@example.com") for _ in range(3)),
            *(sign_in(client, "owner@example.com") for _ in range(3)),
            client.post(AUTH + "/register", json={"email": "owner@example.com", "password": "x"}),
            client.post(AUTH + "/login", json={}),
        ]
        client.app.state.access_mode = AccessMode.ACCOUNTS
        registered = register(client, "owner@example.com")
        signed_in = sign_in(client, "owner@example.com")

    assert [(response.status_code, response.json()) for response in refused] == [
        (404, {"detail": "local_mode"})
    ] * 8
    assert (registered.status_code, signed_in.status_code) == (201, 200)
    assert (service.register_calls, service.login_calls) == (1, 1)


@pytest.mark.parametrize("headers", [FROM_UT, FROM_WEB_PROXY], ids=["ut", "web-proxy"])
def test_ut_and_the_web_through_the_proxy_act_as_the_local_owner(
    headers: dict[str, str],
) -> None:
    service = local_identity_service()
    service.refresh_result = INVALID_REFRESH
    projects = FakeProjectService()

    with build_client(service, AccessMode.LOCAL_OWNER, project_service=projects) as client:
        me = client.get(AUTH + "/me", headers=headers)
        listed = client.get("/api/v1/projects", headers=headers)
        refreshed = client.post(AUTH + "/refresh", headers=headers)
        chosen = client.post(
            AUTH + "/guidance-mode", json={"guidance_mode": "GUIDED"}, headers=headers
        )

    assert (me.status_code, me.json()["id"]) == (200, str(LOCAL_OWNER_ID))
    assert listed.status_code == 200
    assert (refreshed.status_code, refreshed.json()["user"]["id"]) == (200, str(LOCAL_OWNER_ID))
    assert "orchestwin_refresh=local-refresh-token" in refreshed.headers["set-cookie"]
    assert chosen.status_code == 200
    assert projects.overview_calls == [LOCAL_OWNER_ID]
    assert service.guidance_calls == [(LOCAL_OWNER_ID, "GUIDED")]
    assert service.local_session_emails == [LOCAL_EMAIL]


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "localhost:8000", "LOCALHOST", "[::1]:8000", "[::1]"]
)
def test_every_loopback_name_reaches_the_local_owner(host: str) -> None:
    with build_client(local_identity_service(), AccessMode.LOCAL_OWNER) as client:
        response = client.get(AUTH + "/me", headers={"Host": host})

    assert (response.status_code, response.json()["id"]) == (200, str(LOCAL_OWNER_ID))


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Host": "attacker.example:8000"},
        {"Host": "127.0.0.1.attacker.example"},
        {"Host": "localhost.attacker.example:8000"},
        {"Host": "127.0.0.2:8000"},
        {"Host": "0.0.0.0:8000"},
        {"Host": "::1"},
        {"Host": "testserver"},
        {"Host": "127.0.0.1:8000", "Origin": "https://attacker.example"},
        {"Host": "127.0.0.1:8000", "Origin": "http://localhost:8080"},
        {"Host": "127.0.0.1:8000", "Origin": "null"},
        {"Host": "127.0.0.1:8000", "Sec-Fetch-Site": "cross-site"},
        {**FROM_WEB_PROXY, "Sec-Fetch-Site": "cross-site"},
    ],
)
def test_a_request_that_may_come_from_another_site_is_not_the_local_owner(
    headers: dict[str, str],
) -> None:
    service = local_identity_service()
    service.refresh_result = INVALID_REFRESH
    projects = FakeProjectService()

    with build_client(service, AccessMode.LOCAL_OWNER, project_service=projects) as client:
        me = client.get(AUTH + "/me", headers=headers)
        listed = client.get("/api/v1/projects", headers=headers)
        refreshed = client.post(AUTH + "/refresh", headers=headers)
        chosen = client.post(
            AUTH + "/guidance-mode", json={"guidance_mode": "GUIDED"}, headers=headers
        )
        signed = client.get(AUTH + "/me", headers={**headers, **BEARER})

    assert (me.status_code, me.json()) == INVALID_AUTHENTICATION
    assert me.headers["www-authenticate"] == "Bearer"
    assert (listed.status_code, listed.json()) == INVALID_AUTHENTICATION
    assert (refreshed.status_code, refreshed.json()) == (401, {"detail": "invalid_refresh_token"})
    assert "max-age=0" in refreshed.headers["set-cookie"].casefold()
    assert (chosen.status_code, chosen.json()) == INVALID_AUTHENTICATION
    assert (signed.status_code, signed.json()["id"]) == (200, str(USER_ID))
    assert service.local_owner_emails == [LOCAL_EMAIL]
    assert service.local_session_emails == []
    assert service.guidance_calls == []
    assert projects.overview_calls == []


@pytest.mark.parametrize("cookie", [None, "stale-refresh-token"])
def test_refresh_without_a_valid_cookie_opens_a_session_of_the_local_owner(
    cookie: str | None,
) -> None:
    service = local_identity_service()
    service.refresh_result = INVALID_REFRESH

    with build_client(service, AccessMode.LOCAL_OWNER) as client:
        if cookie is not None:
            client.cookies.set("orchestwin_refresh", cookie, path="/api/v1/auth")
        response = client.post(AUTH + "/refresh")

    set_cookie = response.headers["set-cookie"].casefold()
    assert response.status_code == 200
    assert response.json()["access_token"] == "signed-access-token"
    assert response.json()["user"]["id"] == str(LOCAL_OWNER_ID)
    assert response.json()["user"]["email"] == LOCAL_EMAIL
    assert "orchestwin_refresh=local-refresh-token" in set_cookie
    assert "httponly" in set_cookie
    assert "path=/api/v1/auth" in set_cookie
    assert service.local_session_emails == [LOCAL_EMAIL]


def test_refresh_without_a_valid_cookie_is_refused_with_accounts() -> None:
    service = local_identity_service()
    service.refresh_result = INVALID_REFRESH

    with build_client(service, AccessMode.ACCOUNTS) as client:
        response = client.post(AUTH + "/refresh")

    assert (response.status_code, response.json()) == (401, {"detail": "invalid_refresh_token"})
    assert "max-age=0" in response.headers["set-cookie"].casefold()
    assert service.local_session_emails == []


def test_a_valid_refresh_cookie_rotates_as_today_in_local_mode() -> None:
    service = local_identity_service()

    with build_client(service, AccessMode.LOCAL_OWNER) as client:
        client.cookies.set("orchestwin_refresh", "previous-refresh-token", path="/api/v1/auth")
        response = client.post(AUTH + "/refresh")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(USER_ID)
    assert "new-refresh-token" in response.headers["set-cookie"]
    assert service.local_session_emails == []


def test_me_without_a_bearer_is_the_local_owner_only_in_local_mode() -> None:
    local = local_identity_service()
    accounts = local_identity_service()

    with build_client(local, AccessMode.LOCAL_OWNER) as client:
        anonymous = client.get(AUTH + "/me")
        signed = client.get(AUTH + "/me", headers=BEARER)
        unknown = client.get(AUTH + "/me", headers={"Authorization": "Bearer unknown-token"})
    with build_client(accounts, AccessMode.ACCOUNTS) as client:
        refused = client.get(AUTH + "/me")

    assert anonymous.status_code == 200
    assert (anonymous.json()["id"], anonymous.json()["email"]) == (str(LOCAL_OWNER_ID), LOCAL_EMAIL)
    assert (signed.status_code, signed.json()["id"]) == (200, str(USER_ID))
    assert (unknown.status_code, unknown.json()) == INVALID_AUTHENTICATION
    assert (refused.status_code, refused.json()) == INVALID_AUTHENTICATION
    assert refused.headers["www-authenticate"] == "Bearer"
    assert local.local_owner_emails == [LOCAL_EMAIL, LOCAL_EMAIL]
    assert accounts.local_owner_emails == []


@pytest.mark.parametrize(
    ("mode", "status_code", "owners"),
    [
        (AccessMode.LOCAL_OWNER, 200, [LOCAL_OWNER_ID]),
        (AccessMode.ACCOUNTS, 401, []),
    ],
)
def test_a_protected_route_answers_without_a_bearer_only_in_local_mode(
    mode: AccessMode,
    status_code: int,
    owners: list[UUID],
) -> None:
    projects = FakeProjectService()

    with build_client(local_identity_service(), mode, project_service=projects) as client:
        response = client.get("/api/v1/projects")

    assert response.status_code == status_code
    assert projects.overview_calls == owners


def test_the_local_owner_exists_from_the_first_start() -> None:
    local = local_identity_service()
    accounts = local_identity_service()

    with build_client(local, AccessMode.LOCAL_OWNER, local_owner_email=" Owner@Example.COM "):
        started = list(local.local_owner_emails)
    with build_client(accounts, AccessMode.ACCOUNTS, local_owner_email="owner@example.com"):
        pass
    with build_client(None, AccessMode.LOCAL_OWNER) as client:
        health = client.get("/api/v1/health")
        unavailable = client.get(AUTH + "/me")

    assert started == ["owner@example.com"]
    assert accounts.local_owner_emails == []
    assert health.status_code == 200
    assert (unavailable.status_code, unavailable.json()) == (
        503,
        {"detail": "identity_service_unavailable"},
    )


def test_the_local_owner_chooses_its_guidance_mode_once_without_signing_in() -> None:
    service, users, sessions = build_identity_service()

    with build_client(service, AccessMode.LOCAL_OWNER) as client:
        started = [user.email.value for user in users.users.values()]
        before = client.get(AUTH + "/me")
        refreshed = client.post(AUTH + "/refresh")
        bearer = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
        chosen = client.post(AUTH + "/guidance-mode", json={"guidance_mode": "GUIDED"})
        repeated = [
            client.post(AUTH + "/guidance-mode", json={"guidance_mode": mode}, headers=headers)
            for mode, headers in (("GUIDED", {}), ("EXPERT", bearer))
        ]
        after = client.get(AUTH + "/me", headers=bearer)
        rotated = client.post(AUTH + "/refresh")

    account = before.json()
    assert started == [LOCAL_EMAIL]
    assert before.status_code == 200
    assert (account["email"], account["guidance_mode"]) == (LOCAL_EMAIL, None)
    assert (refreshed.status_code, refreshed.json()["user"]) == (200, account)
    assert "orchestwin_refresh=" in refreshed.headers["set-cookie"]
    assert (chosen.status_code, chosen.json()) == (200, {**account, "guidance_mode": "GUIDED"})
    assert [(response.status_code, response.json()) for response in repeated] == [
        (409, {"detail": "guidance_mode_already_chosen"})
    ] * 2
    assert (after.status_code, after.json()) == (200, chosen.json())
    assert (rotated.status_code, rotated.json()["user"]) == (200, chosen.json())
    assert len(users.users) == 1
    assert len(sessions.sessions) == 2
    assert [session.rotated_at is not None for session in sessions.sessions.values()] == [
        True,
        False,
    ]


def test_a_local_owner_made_inactive_is_refused_like_any_inactive_account() -> None:
    service, users, sessions = build_identity_service()

    with build_client(service, AccessMode.LOCAL_OWNER) as client:
        (owner,) = users.users.values()
        users.users[owner.id] = replace(owner, is_active=False)
        me = client.get(AUTH + "/me")
        refreshed = client.post(AUTH + "/refresh")
        mode = client.get(AUTH + "/mode")

    assert (me.status_code, me.json()) == INVALID_AUTHENTICATION
    assert (refreshed.status_code, refreshed.json()) == (401, {"detail": "invalid_refresh_token"})
    assert "max-age=0" in refreshed.headers["set-cookie"].casefold()
    assert mode.status_code == 200
    assert sessions.sessions == {}


def test_the_studio_does_not_start_in_local_mode_with_an_inactive_owner() -> None:
    service, users, _ = build_identity_service()
    owner = asyncio.run(service.local_owner(email=LOCAL_EMAIL))
    users.users[owner.id] = replace(owner, is_active=False)

    with pytest.raises(LocalOwnerUnavailable), build_client(service, AccessMode.LOCAL_OWNER):
        pass
