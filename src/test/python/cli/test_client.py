from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from orchestwin.cli.client import (
    AUTH_TIMEOUT,
    StudioClient,
    api_failure,
    ensure_access,
    refresh_cookie,
)
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import ApiFailure, CliError
from orchestwin.cli.http import Reply, multipart
from orchestwin.cli.session import LOCK_FILE, SessionStore, StudioAddress, StudioSession

from .support.terminal import (
    START,
    TEST_ACCESS_TOKEN,
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_REFRESH_TOKEN,
    Terminal,
    command_context,
    terminal,
)
from .support.transports import (
    API,
    ScriptedTransport,
    Sent,
    authentication,
    reply,
)
from .support.transports import (
    refresh_cookie as cookie_header,
)

LOCAL = StudioAddress.parse("http://127.0.0.1:8000")
REMOTE = StudioAddress.parse("https://studio.example.test")
RENEWED_ACCESS = "test-access-renewed-not-real"
ROTATED_REFRESH = "test-refresh-rotated-not-real"
RENEWED_UNTIL = START + timedelta(minutes=30)
MODE_PATH = f"{API}/auth/mode"
LOCAL_MODE = {"access_mode": "LOCAL_OWNER", "registration_open": False}


def signed_in(
    tmp_path: Path, transport: ScriptedTransport, *, expires_in: float = 900.0
) -> tuple[StudioClient, SessionStore, Terminal]:
    bundle = terminal(tmp_path, transport=transport)
    store = SessionStore(bundle.environment)
    store.save(
        LOCAL,
        StudioSession(
            email=TEST_EMAIL,
            refresh_token=TEST_REFRESH_TOKEN,
            access_token=TEST_ACCESS_TOKEN,
            access_expires_at=START + timedelta(seconds=expires_in),
            saved_at=START,
        ),
        make_default=True,
    )
    return StudioClient(LOCAL, bundle.environment, store), store, bundle


def expect_renewal(transport: ScriptedTransport, *, cookie: bool = True) -> ScriptedTransport:
    return transport.expect(
        "POST",
        f"{API}/auth/refresh",
        body=authentication(access_token=RENEWED_ACCESS, expires_at=RENEWED_UNTIL),
        headers={"set-cookie": cookie_header(ROTATED_REFRESH)} if cookie else {},
    )


def bearer(request: Sent) -> str | None:
    return request.header("authorization")


def test_the_access_token_is_reused_while_it_is_fresh(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/projects", body=[]).expect("GET", f"{API}/projects", body=[])
    client, _, bundle = signed_in(tmp_path, transport, expires_in=61)

    assert client.get("/projects") == []
    bundle.clock.advance(0.5)
    assert client.get("/projects") == []

    assert [bearer(request) for request in transport.sent] == [f"Bearer {TEST_ACCESS_TOKEN}"] * 2
    assert all(request.header("user-agent").startswith("ut/") for request in transport.sent)
    transport.assert_done()


def test_the_access_is_renewed_sixty_seconds_before_it_expires(tmp_path: Path) -> None:
    transport = expect_renewal(ScriptedTransport())
    transport.expect("GET", f"{API}/projects", body=[])
    client, store, _ = signed_in(tmp_path, transport, expires_in=59)

    assert client.get("/projects") == []

    renewal, request = transport.sent
    assert renewal.header("cookie") == f"orchestwin_refresh={TEST_REFRESH_TOKEN}"
    assert renewal.header("authorization") is None
    assert renewal.body is None
    assert bearer(request) == f"Bearer {RENEWED_ACCESS}"
    saved = store.read(LOCAL)
    assert saved is not None
    assert (saved.refresh_token, saved.access_token) == (ROTATED_REFRESH, RENEWED_ACCESS)
    assert saved.access_expires_at == RENEWED_UNTIL
    assert saved.email == TEST_EMAIL
    transport.assert_done()


def test_the_renewal_happens_inside_the_lock(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    client, store, _ = signed_in(tmp_path, transport, expires_in=10)
    lock = store.folder / LOCK_FILE
    seen: list[bool] = []

    def renew(request: Sent) -> Reply:
        seen.append(lock.exists())
        return reply(
            200,
            authentication(access_token=RENEWED_ACCESS, expires_at=RENEWED_UNTIL),
            {"set-cookie": cookie_header(ROTATED_REFRESH)},
        )

    transport.expect("POST", f"{API}/auth/refresh", respond=renew)
    transport.expect("GET", f"{API}/projects", body=[])

    client.get("/projects")

    assert seen == [True]
    assert not lock.exists()


def test_a_401_renews_once_and_repeats_the_request_once(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{API}/projects", status=401, body={"detail": "invalid_authentication"}
    )
    expect_renewal(transport)
    transport.expect("POST", f"{API}/projects", status=201, body={"id": "one"})
    client, _, _ = signed_in(tmp_path, transport)

    created = client.post("/projects", {"display_name": "Calcolo mancia"})

    assert created == {"id": "one"}
    assert [request.path for request in transport.sent] == [
        f"{API}/projects",
        f"{API}/auth/refresh",
        f"{API}/projects",
    ]
    assert bearer(transport.sent[0]) == f"Bearer {TEST_ACCESS_TOKEN}"
    assert bearer(transport.sent[2]) == f"Bearer {RENEWED_ACCESS}"
    assert transport.sent[2].json() == {"display_name": "Calcolo mancia"}
    transport.assert_done()


def test_a_second_401_is_returned_and_raised_as_expired_sign_in(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "GET", f"{API}/projects", status=401, body={"detail": "invalid_authentication"}
    )
    expect_renewal(transport)
    transport.expect(
        "GET", f"{API}/projects", status=401, body={"detail": "invalid_authentication"}
    )
    client, _, _ = signed_in(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        client.get("/projects")

    assert caught.value.code == "invalid_authentication"
    assert caught.value.status == 3
    transport.assert_done()


def test_a_refused_renewal_removes_the_tokens(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{API}/auth/refresh", status=401, body={"detail": "refresh_token_expired"}
    )
    client, store, _ = signed_in(tmp_path, transport, expires_in=30)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "SESSION_EXPIRED"
    assert caught.value.status == 3
    assert caught.value.values["studio"] == "http://127.0.0.1:8000"
    saved = store.read(LOCAL)
    assert saved is not None
    assert saved.email == TEST_EMAIL
    assert not saved.signed_in
    assert TEST_REFRESH_TOKEN not in store.path.read_text(encoding="utf-8")
    transport.assert_done()


def test_two_clients_that_share_the_file_never_send_the_same_renewal_token(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport()
    first, _, bundle = signed_in(tmp_path, transport, expires_in=90)
    second = StudioClient(LOCAL, bundle.environment, SessionStore(bundle.environment))

    def in_flight(request: Sent) -> Reply:
        assert bearer(request) == f"Bearer {TEST_ACCESS_TOKEN}"
        bundle.clock.advance(60)
        assert first.get("/projects/one") == {"id": "one"}
        return reply(401, {"detail": "invalid_authentication"})

    transport.expect("GET", f"{API}/projects", respond=in_flight)
    expect_renewal(transport)
    transport.expect("GET", f"{API}/projects/one", body={"id": "one"})
    transport.expect("GET", f"{API}/projects", body=[])

    assert second.get("/projects") == []

    renewals = transport.requests("POST", f"{API}/auth/refresh")
    assert [request.header("cookie") for request in renewals] == [
        f"orchestwin_refresh={TEST_REFRESH_TOKEN}"
    ]
    assert bearer(transport.sent[-1]) == f"Bearer {RENEWED_ACCESS}"
    transport.assert_done()


def test_a_renewal_without_a_rotated_cookie_keeps_only_the_access(tmp_path: Path) -> None:
    transport = expect_renewal(ScriptedTransport(), cookie=False)
    transport.expect("GET", f"{API}/projects", body=[])
    client, store, _ = signed_in(tmp_path, transport, expires_in=5)

    client.get("/projects")

    saved = store.read(LOCAL)
    assert saved is not None
    assert saved.refresh_token is None
    assert saved.access_token == RENEWED_ACCESS


@pytest.mark.parametrize(("sent", "kept"), [(False, True), (True, False)])
def test_a_renewal_token_that_may_have_arrived_is_never_sent_again(
    tmp_path: Path, sent: bool, kept: bool
) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}/auth/refresh", unreachable=True, sent=sent)
    client, store, _ = signed_in(tmp_path, transport, expires_in=5)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "STUDIO_UNREACHABLE"
    saved = store.read(LOCAL)
    assert saved is not None
    assert (saved.refresh_token == TEST_REFRESH_TOKEN) is kept
    assert len(transport.sent) == 1


@pytest.mark.parametrize("sent", [False, True])
def test_a_post_is_never_sent_twice_after_a_network_failure(tmp_path: Path, sent: bool) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}/projects/one/design/proposals", unreachable=True, sent=sent)
    client, _, bundle = signed_in(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        client.post("/projects/one/design/proposals")

    assert caught.value.status == 4
    assert len(transport.requests("POST")) == 1
    assert bundle.clock.slept == 0


def test_a_get_is_tried_three_times_two_seconds_apart(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/projects", unreachable=True)
    transport.expect("GET", f"{API}/projects", unreachable=True, sent=True)
    transport.expect("GET", f"{API}/projects", body=[{"id": "one"}])
    client, _, bundle = signed_in(tmp_path, transport)

    assert client.get("/projects") == [{"id": "one"}]
    assert bundle.clock.slept == 4.0
    assert len(transport.sent) == 3


def test_a_get_gives_up_after_the_third_failure(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    for _ in range(3):
        transport.expect("GET", f"{API}/projects", unreachable=True)
    client, _, bundle = signed_in(tmp_path, transport)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "STUDIO_UNREACHABLE"
    assert bundle.clock.slept == 4.0
    transport.assert_done()


def anonymous(tmp_path: Path, transport: ScriptedTransport, studio: StudioAddress) -> StudioClient:
    bundle = terminal(tmp_path, transport=transport)
    return StudioClient(studio, bundle.environment, SessionStore(bundle.environment))


def context_and_client(
    tmp_path: Path, transport: ScriptedTransport, studio: StudioAddress
) -> tuple[CommandContext, StudioClient]:
    context = command_context(terminal(tmp_path, transport=transport).environment)
    return context, context.client(studio)


def test_without_a_sign_in_only_the_access_mode_is_asked(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", MODE_PATH, status=404, body={"detail": "Not Found"})
    client = anonymous(tmp_path, transport, LOCAL)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "NOT_SIGNED_IN"
    assert caught.value.status == 3
    assert [request.path for request in transport.sent] == [MODE_PATH]
    assert bearer(transport.sent[0]) is None


def test_nothing_is_sent_to_a_studio_of_another_computer_without_a_sign_in(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport()
    client = anonymous(tmp_path, transport, REMOTE)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "NOT_SIGNED_IN"
    assert client.local_access() is False
    assert transport.sent == []


def test_a_local_studio_is_asked_without_authorization_and_the_mode_is_kept(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport().expect("GET", MODE_PATH, body=LOCAL_MODE)
    transport.expect("GET", f"{API}/projects", body=[]).expect("GET", f"{API}/projects", body=[])
    client = anonymous(tmp_path, transport, LOCAL)

    assert client.get("/projects") == []
    assert client.get("/projects") == []

    assert client.access_mode() == "LOCAL_OWNER"
    assert [request.path for request in transport.sent] == [
        MODE_PATH,
        f"{API}/projects",
        f"{API}/projects",
    ]
    assert [bearer(request) for request in transport.sent] == [None, None, None]
    transport.assert_done()


def test_a_401_without_a_session_is_not_signed_in_and_nothing_is_renewed(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport().expect("GET", MODE_PATH, body=LOCAL_MODE)
    transport.expect(
        "GET", f"{API}/projects", status=401, body={"detail": "invalid_authentication"}
    )
    client = anonymous(tmp_path, transport, LOCAL)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert (caught.value.code, caught.value.status) == ("NOT_SIGNED_IN", 3)
    assert transport.requests("POST", f"{API}/auth/refresh") == []
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body", "mode"),
    [
        (200, LOCAL_MODE, "LOCAL_OWNER"),
        (200, {"access_mode": "ACCOUNTS", "registration_open": True}, "ACCOUNTS"),
        (404, {"detail": "Not Found"}, "ACCOUNTS"),
        (500, b"Internal Server Error", "ACCOUNTS"),
        (200, b"not a document", "ACCOUNTS"),
        (200, ["LOCAL_OWNER"], "ACCOUNTS"),
        (200, {"access_mode": "local"}, "ACCOUNTS"),
    ],
)
def test_the_access_mode_is_local_only_when_the_studio_says_so(
    tmp_path: Path, status: int, body: object, mode: str
) -> None:
    transport = ScriptedTransport().expect("GET", MODE_PATH, status=status, body=body)
    client = anonymous(tmp_path, transport, LOCAL)

    assert client.access_mode() == mode
    assert client.access_mode() == mode
    assert len(transport.sent) == 1
    assert transport.sent[0].timeout == AUTH_TIMEOUT


def test_a_session_keeps_the_bearer_and_never_asks_the_mode(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", f"{API}/projects", body=[])
    client, _, _ = signed_in(tmp_path, transport)

    assert client.get("/projects") == []

    assert [request.path for request in transport.sent] == [f"{API}/projects"]
    assert bearer(transport.sent[0]) == f"Bearer {TEST_ACCESS_TOKEN}"


def test_ensure_access_names_the_session_or_the_local_studio(tmp_path: Path) -> None:
    kept = ScriptedTransport()
    client, _, bundle = signed_in(tmp_path / "kept", kept)
    local = ScriptedTransport().expect("GET", MODE_PATH, body=LOCAL_MODE)
    accounts = ScriptedTransport().expect("GET", MODE_PATH, status=404, body=b"")
    remote = ScriptedTransport()

    session_access = ensure_access(command_context(bundle.environment), client)
    local_access = ensure_access(*context_and_client(tmp_path / "local", local, LOCAL))
    with pytest.raises(CliError) as refused:
        ensure_access(*context_and_client(tmp_path / "accounts", accounts, LOCAL))
    with pytest.raises(CliError) as far:
        ensure_access(*context_and_client(tmp_path / "remote", remote, REMOTE))

    assert (session_access, local_access) == ("session", "local")
    assert kept.sent == []
    assert [request.path for request in local.sent] == [MODE_PATH]
    assert (refused.value.code, refused.value.values["studio"]) == ("NOT_SIGNED_IN", LOCAL.origin)
    assert (far.value.code, far.value.values["studio"]) == ("NOT_SIGNED_IN", REMOTE.origin)
    assert remote.sent == []


def test_a_local_studio_that_does_not_answer_is_tried_three_times(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    for _ in range(3):
        transport.expect("GET", MODE_PATH, unreachable=True)
    transport.expect("GET", MODE_PATH, body=LOCAL_MODE)
    client = anonymous(tmp_path, transport, LOCAL)

    with pytest.raises(CliError) as caught:
        client.get("/projects")

    assert caught.value.code == "STUDIO_UNREACHABLE"
    assert client.access_mode() == "LOCAL_OWNER"
    assert len(transport.sent) == 4


@pytest.mark.parametrize(
    ("status", "body", "code", "exit_status"),
    [
        (404, {"detail": "project_not_found"}, "project_not_found", 1),
        (409, {"detail": {"code": "DESIGN_DISCUSSION_OPEN"}}, "DESIGN_DISCUSSION_OPEN", 1),
        (402, {"detail": {"code": "GENERATION_BUDGET_EXCEEDED"}}, "GENERATION_BUDGET_EXCEEDED", 5),
        (
            503,
            {"detail": {"code": "GENERATION_BUDGET_UNAVAILABLE"}},
            "GENERATION_BUDGET_UNAVAILABLE",
            5,
        ),
        (500, b"Internal Server Error", "API_FAILURE", 1),
        (422, {"detail": [{"loc": ["body"]}]}, "API_FAILURE", 1),
    ],
)
def test_failures_become_api_failures(
    tmp_path: Path, status: int, body: object, code: str, exit_status: int
) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/projects/one", status=status, body=body)
    client, _, _ = signed_in(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        client.get("/projects/one")

    assert caught.value.code == code
    assert caught.value.http_status == status
    assert caught.value.status == exit_status


def test_an_optional_read_gives_none_for_404(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/projects/one/design/current", status=404, body={"detail": "x"})
    client, _, _ = signed_in(tmp_path, transport)

    assert client.get("/projects/one/design/current", optional=True) is None


def test_json_bodies_forms_and_empty_answers(tmp_path: Path) -> None:
    form = multipart({"display_name": "Mancia"}, {"archive": ("a.zip", "application/zip", b"PK")})
    transport = ScriptedTransport()
    transport.expect("PATCH", f"{API}/projects/one", body={"id": "one"})
    transport.expect("POST", f"{API}/projects/imports", status=201, body={"id": "two"})
    transport.expect("DELETE", f"{API}/projects/one", status=204)
    transport.expect(
        "POST", f"{API}/projects/one/requirements/proposals", status=202, body={"job_id": "j"}
    )
    client, _, _ = signed_in(tmp_path, transport)

    assert client.patch("/projects/one", {"display_name": "Nuovo nome"}) == {"id": "one"}
    imported = client.request("POST", "/projects/imports", form=form)
    removed = client.request("DELETE", "/projects/one")
    started = client.request("POST", "/projects/one/requirements/proposals", prefer_async=True)

    patch, upload, deletion, job = transport.sent
    assert patch.header("content-type") == "application/json"
    assert patch.json() == {"display_name": "Nuovo nome"}
    assert upload.header("content-type") == form[0]
    assert upload.body == form[1]
    assert imported.status == 201
    assert deletion.body is None
    assert removed.status == 204
    assert job.header("prefer") == "respond-async"
    assert started.status == 202


def test_a_download_returns_the_bytes_and_raises_on_failure(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "GET",
        f"{API}/projects/one/knowledge-packages/1/archive",
        body=b"PK\x03\x04",
        headers={"X-Content-SHA256": "abc"},
    )
    transport.expect(
        "GET",
        f"{API}/projects/one/knowledge-packages/9/archive",
        status=404,
        body={"detail": {"code": "KNOWLEDGE_PACKAGE_NOT_FOUND"}},
    )
    client, _, _ = signed_in(tmp_path, transport)

    archive = client.download("/projects/one/knowledge-packages/1/archive")

    assert archive.content == b"PK\x03\x04"
    assert archive.headers["x-content-sha256"] == "abc"
    assert "application/zip" in transport.sent[0].header("accept")
    with pytest.raises(ApiFailure) as caught:
        client.download("/projects/one/knowledge-packages/9/archive")
    assert caught.value.code == "KNOWLEDGE_PACKAGE_NOT_FOUND"


def test_sign_in_sends_the_password_only_in_the_body_and_saves_the_session(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST",
        f"{API}/auth/login",
        body=authentication(
            access_token=TEST_ACCESS_TOKEN, expires_at=START + timedelta(minutes=15)
        ),
        headers={"set-cookie": cookie_header(TEST_REFRESH_TOKEN)},
    )
    bundle = terminal(tmp_path, transport=transport)
    store = SessionStore(bundle.environment)
    client = StudioClient(LOCAL, bundle.environment, store)

    user = client.sign_in(TEST_EMAIL, TEST_PASSWORD)

    request = transport.sent[0]
    assert request.url == "http://127.0.0.1:8000/api/v1/auth/login"
    assert request.json() == {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    assert all(TEST_PASSWORD not in value for value in request.headers.values())
    assert TEST_PASSWORD not in request.url
    assert user["email"] == TEST_EMAIL
    saved = store.read(LOCAL)
    assert saved is not None
    assert (saved.access_token, saved.refresh_token) == (TEST_ACCESS_TOKEN, TEST_REFRESH_TOKEN)
    assert store.default_studio() == LOCAL
    assert TEST_PASSWORD not in store.path.read_text(encoding="utf-8")


def test_a_refused_sign_in_saves_nothing(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST", f"{API}/auth/login", status=401, body={"detail": "invalid_authentication"}
    )
    bundle = terminal(tmp_path, transport=transport)
    store = SessionStore(bundle.environment)

    with pytest.raises(ApiFailure) as caught:
        StudioClient(LOCAL, bundle.environment, store).sign_in(TEST_EMAIL, TEST_PASSWORD)

    assert caught.value.http_status == 401
    assert not store.path.exists()


def test_sign_out_sends_the_cookie_and_forgets_even_when_the_studio_is_away(
    tmp_path: Path,
) -> None:
    transport = ScriptedTransport()
    transport.expect("POST", f"{API}/auth/logout", status=204)
    client, store, _ = signed_in(tmp_path, transport)

    client.sign_out()

    assert transport.sent[0].header("cookie") == f"orchestwin_refresh={TEST_REFRESH_TOKEN}"
    assert transport.sent[0].header("authorization") is None
    assert store.read(LOCAL) is None

    away = ScriptedTransport()
    away.expect("POST", f"{API}/auth/logout", unreachable=True)
    other, other_store, _ = signed_in(tmp_path / "second", away)
    with pytest.raises(CliError):
        other.sign_out()
    assert other_store.read(LOCAL) is None


def test_health_needs_no_sign_in(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    bundle = terminal(tmp_path, transport=transport)
    client = StudioClient(LOCAL, bundle.environment, SessionStore(bundle.environment))

    assert client.health().status == 200
    assert transport.sent[0].header("authorization") is None


def test_the_cookie_is_read_from_the_headers() -> None:
    header = "\n".join(
        (
            "other=1; Path=/",
            'orchestwin_refresh="quoted-token-not-real"; HttpOnly; Path=/api/v1/auth',
        )
    )

    assert refresh_cookie(header, "orchestwin_refresh") == (
        "orchestwin_refresh",
        "quoted-token-not-real",
    )
    assert refresh_cookie("single=value-not-real; Path=/", "orchestwin_refresh") == (
        "single",
        "value-not-real",
    )
    assert refresh_cookie('orchestwin_refresh=""; Max-Age=0', "orchestwin_refresh") is None
    assert refresh_cookie("a=1\nb=2", "orchestwin_refresh") is None


def test_api_failure_reads_the_code() -> None:
    failure = api_failure(Reply(429, {}, json.dumps({"detail": "too_many_attempts"}).encode()))

    assert (failure.code, failure.http_status, failure.detail) == (
        "too_many_attempts",
        429,
        "too_many_attempts",
    )


def test_a_session_saved_by_the_client_keeps_the_prefix_of_the_studio(tmp_path: Path) -> None:
    transport = ScriptedTransport()
    transport.expect(
        "POST",
        "/team/api/v1/auth/login",
        body=authentication(
            access_token=TEST_ACCESS_TOKEN, expires_at=START + timedelta(minutes=5)
        ),
    )
    bundle = terminal(tmp_path, transport=transport)
    store = SessionStore(bundle.environment)
    studio = StudioAddress.parse("https://studio.example.test/team/api/v1")

    StudioClient(studio, bundle.environment, store).sign_in(TEST_EMAIL, TEST_PASSWORD)

    saved = store.read(studio)
    assert saved is not None
    assert saved.api_prefix == "/team/api/v1"
    assert saved.refresh_token is None
    assert store.default_studio() == replace(studio)
