from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from .support.terminal import (
    START,
    TEST_ACCESS_TOKEN,
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_REFRESH_TOKEN,
    link_folder,
    read_session,
    run_ut,
    store_session,
)
from .support.transports import API, ScriptedTransport, authentication, refresh_cookie

LOCAL = "http://127.0.0.1:8000"
REMOTE = "https://studio.example.test"
MODE_PATH = f"{API}/auth/mode"
ACCOUNTS_MODE = {"access_mode": "ACCOUNTS", "registration_open": True}
LOCAL_MODE = {"access_mode": "LOCAL_OWNER", "registration_open": False}


def expect_health(
    transport: ScriptedTransport, *, mode: dict[str, object] | None = ACCOUNTS_MODE
) -> ScriptedTransport:
    transport.expect("GET", f"{API}/health", body={"status": "ok"})
    if mode is not None:
        transport.expect("GET", MODE_PATH, body=mode)
    return transport


def expect_sign_in(
    transport: ScriptedTransport,
    *,
    status: int = 200,
    email: str = TEST_EMAIL,
    mode: dict[str, object] | None = ACCOUNTS_MODE,
) -> ScriptedTransport:
    expect_health(transport, mode=mode)
    if status == 200:
        transport.expect(
            "POST",
            f"{API}/auth/login",
            body=authentication(
                access_token=TEST_ACCESS_TOKEN,
                expires_at=START + timedelta(minutes=15),
                email=email,
            ),
            headers={"set-cookie": refresh_cookie(TEST_REFRESH_TOKEN)},
        )
    else:
        transport.expect("POST", f"{API}/auth/login", status=status, body={"detail": "refused"})
    return transport


def config_text(tmp_path: Path) -> str:
    path = tmp_path / "config" / "sessions.json"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_login_with_the_email_option_and_a_typed_password(tmp_path: Path) -> None:
    transport = expect_sign_in(ScriptedTransport())

    run = run_ut(
        ["login", "--email", TEST_EMAIL], tmp_path, transport=transport, secrets=[TEST_PASSWORD]
    )

    assert run.status == 0
    assert run.output == f"Signed in as {TEST_EMAIL} to the Studio {LOCAL}.\n"
    assert run.errors == ""
    login = transport.requests("POST", f"{API}/auth/login")[0]
    assert login.json() == {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    session = read_session(tmp_path)
    assert session is not None
    assert (session.access_token, session.refresh_token) == (TEST_ACCESS_TOKEN, TEST_REFRESH_TOKEN)
    for text in (run.output, run.errors, config_text(tmp_path)):
        assert TEST_PASSWORD not in text
    assert f'"default_studio": "{LOCAL}"' in config_text(tmp_path)
    transport.assert_done()


def test_login_in_italian_asks_the_email(tmp_path: Path) -> None:
    transport = expect_sign_in(ScriptedTransport())

    run = run_ut(
        ["--lang", "it", "login"],
        tmp_path,
        transport=transport,
        answers=[TEST_EMAIL],
        secrets=[TEST_PASSWORD],
    )

    assert run.status == 0
    assert run.output == (f"E-mail: \nAccesso eseguito come {TEST_EMAIL} sullo Studio {LOCAL}.\n")


def test_the_email_of_the_last_sign_in_is_offered(tmp_path: Path) -> None:
    store_session(tmp_path, email="old@example.test", access_token=None, refresh_token=None)
    transport = expect_sign_in(ScriptedTransport(), email="old@example.test")

    run = run_ut(["login"], tmp_path, transport=transport, answers=[""], secrets=[TEST_PASSWORD])

    assert run.status == 0
    assert "E-mail: [old@example.test] " in run.output
    assert transport.requests("POST")[0].json()["email"] == "old@example.test"


@pytest.mark.parametrize(
    ("arguments", "answers", "email"),
    [
        (["login", "--email", TEST_EMAIL, "--password-stdin"], [TEST_PASSWORD], TEST_EMAIL),
        (
            ["login", "--password-stdin"],
            [TEST_PASSWORD, "other@example.test"],
            "other@example.test",
        ),
    ],
)
def test_the_password_can_come_from_the_first_line_of_the_input(
    tmp_path: Path, arguments: list[str], answers: list[str], email: str
) -> None:
    transport = expect_sign_in(ScriptedTransport(), email=email)

    run = run_ut(arguments, tmp_path, transport=transport, answers=answers)

    assert run.status == 0
    assert transport.requests("POST")[0].json() == {"email": email, "password": TEST_PASSWORD}
    assert TEST_PASSWORD not in run.output


def test_an_empty_password_is_never_sent(tmp_path: Path) -> None:
    transport = expect_health(ScriptedTransport())

    run = run_ut(
        ["login", "--email", TEST_EMAIL, "--password-stdin"],
        tmp_path,
        transport=transport,
        answers=[""],
    )

    assert run.status == 2
    assert run.errors == "The password is empty: nothing was sent to the Studio.\n"
    assert transport.requests("POST") == []


@pytest.mark.parametrize("status", [401, 422])
def test_a_refused_sign_in_does_not_say_which_part_is_wrong(tmp_path: Path, status: int) -> None:
    transport = expect_sign_in(ScriptedTransport(), status=status)

    run = run_ut(
        ["login", "--email", TEST_EMAIL], tmp_path, transport=transport, secrets=[TEST_PASSWORD]
    )

    assert run.status == 3
    assert run.errors == "Sign-in refused: the e-mail or the password is not correct.\n"
    assert read_session(tmp_path) is None


def test_too_many_attempts(tmp_path: Path) -> None:
    transport = expect_sign_in(ScriptedTransport(), status=429)

    run = run_ut(
        ["--lang", "it", "login", "--email", TEST_EMAIL],
        tmp_path,
        transport=transport,
        secrets=[TEST_PASSWORD],
    )

    assert run.status == 3
    assert run.errors == "Troppi tentativi di accesso: aspetta qualche minuto e riprova.\n"


def test_a_studio_that_does_not_answer(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", f"{API}/health", unreachable=True)

    run = run_ut(["login"], tmp_path, transport=transport)

    assert run.status == 4
    assert run.errors == (
        f"The Studio at {LOCAL} does not answer. Check that it is running, then try again.\n"
    )
    assert len(transport.sent) == 1


def test_an_address_that_is_not_a_studio(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", f"{API}/health", status=404, body=b"")

    run = run_ut(["login"], tmp_path, transport=transport)

    assert run.status == 4
    assert "does not look like the OrchesTwin Studio (status 404)" in run.errors


@pytest.mark.parametrize(
    ("address", "fragment"),
    [
        ("http://studio.example.test", "uses http towards another computer"),
        ("ftp://127.0.0.1", "is not valid"),
    ],
)
def test_addresses_that_are_refused_before_any_request(
    tmp_path: Path, address: str, fragment: str
) -> None:
    transport = ScriptedTransport()

    run = run_ut(["login", "--studio", address], tmp_path, transport=transport)

    assert run.status == 2
    assert fragment in run.errors
    assert transport.sent == []


def test_login_to_a_remote_studio_makes_it_the_default(tmp_path: Path) -> None:
    transport = expect_sign_in(ScriptedTransport(), mode=None)

    run = run_ut(
        ["login", "--studio", f"{REMOTE}/api/v1/", "--email", TEST_EMAIL],
        tmp_path,
        transport=transport,
        secrets=[TEST_PASSWORD],
    )

    assert run.status == 0
    assert transport.sent[0].url == f"{REMOTE}/api/v1/health"
    assert transport.requests("GET", MODE_PATH) == []
    assert read_session(tmp_path, REMOTE) is not None
    assert f'"default_studio": "{REMOTE}"' in config_text(tmp_path)
    transport.assert_done()


def test_the_default_studio_of_the_sessions_file_is_used(tmp_path: Path) -> None:
    store_session(tmp_path, studio=REMOTE)
    transport = expect_sign_in(ScriptedTransport(), mode=None)

    run = run_ut(
        ["login", "--email", TEST_EMAIL], tmp_path, transport=transport, secrets=[TEST_PASSWORD]
    )

    assert run.status == 0
    assert transport.sent[0].url == f"{REMOTE}/api/v1/health"


def test_a_folder_linked_to_another_studio_is_mentioned(tmp_path: Path) -> None:
    link_folder(tmp_path / "project", studio=REMOTE)
    transport = expect_sign_in(ScriptedTransport())

    run = run_ut(
        ["login", "--studio", LOCAL, "--email", TEST_EMAIL],
        tmp_path,
        transport=transport,
        secrets=[TEST_PASSWORD],
    )

    assert run.status == 0
    assert run.output.splitlines() == [
        f"Signed in as {TEST_EMAIL} to the Studio {LOCAL}.",
        f"This folder is linked to a project of the Studio {REMOTE}: the commands launched "
        "here use that Studio.",
    ]


def test_a_folder_linked_to_the_same_studio_adds_nothing(tmp_path: Path) -> None:
    link_folder(tmp_path / "project")
    transport = expect_sign_in(ScriptedTransport())

    run = run_ut(
        ["login", "--email", TEST_EMAIL], tmp_path, transport=transport, secrets=[TEST_PASSWORD]
    )

    assert run.output == f"Signed in as {TEST_EMAIL} to the Studio {LOCAL}.\n"


@pytest.mark.parametrize(("answers", "secrets"), [([], [TEST_PASSWORD]), ([TEST_EMAIL], [])])
def test_input_closed_while_a_question_is_open(
    tmp_path: Path, answers: list[str], secrets: list[str]
) -> None:
    transport = expect_health(ScriptedTransport())

    run = run_ut(["login"], tmp_path, transport=transport, answers=answers, secrets=secrets)

    assert run.status == 1
    assert run.errors == "The input closed while an answer was awaited: nothing else was done.\n"
    assert transport.requests("POST") == []


@pytest.mark.parametrize(
    ("language", "message"),
    [
        (
            "en",
            f"The Studio {LOCAL} is local and needs no sign-in: the commands work without "
            "`ut login`.\n",
        ),
        (
            "it",
            f"Lo Studio {LOCAL} è locale e non chiede l'accesso: i comandi funzionano senza "
            "`ut login`.\n",
        ),
    ],
)
def test_a_local_studio_asks_neither_the_email_nor_the_password(
    tmp_path: Path, language: str, message: str
) -> None:
    transport = expect_health(ScriptedTransport(), mode=LOCAL_MODE)

    run = run_ut(["--lang", language, "login"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output == message
    assert run.errors == ""
    assert transport.requests("POST") == []
    assert read_session(tmp_path) is None
    assert config_text(tmp_path) == ""
    transport.assert_done()


def test_a_local_studio_still_names_the_studio_of_the_linked_folder(tmp_path: Path) -> None:
    link_folder(tmp_path / "project", studio=REMOTE)
    transport = expect_health(ScriptedTransport(), mode=LOCAL_MODE)

    run = run_ut(["login", "--studio", LOCAL], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output.splitlines() == [
        f"The Studio {LOCAL} is local and needs no sign-in: the commands work without `ut login`.",
        f"This folder is linked to a project of the Studio {REMOTE}: the commands launched "
        "here use that Studio.",
    ]


@pytest.mark.parametrize(
    ("status", "body"),
    [(404, {"detail": "Not Found"}), (200, b"not a document")],
)
def test_a_studio_that_does_not_tell_its_mode_asks_the_sign_in_as_before(
    tmp_path: Path, status: int, body: object
) -> None:
    transport = ScriptedTransport().expect("GET", f"{API}/health", body={"status": "ok"})
    transport.expect("GET", MODE_PATH, status=status, body=body)
    transport.expect(
        "POST",
        f"{API}/auth/login",
        body=authentication(
            access_token=TEST_ACCESS_TOKEN, expires_at=START + timedelta(minutes=15)
        ),
        headers={"set-cookie": refresh_cookie(TEST_REFRESH_TOKEN)},
    )

    run = run_ut(
        ["login", "--email", TEST_EMAIL], tmp_path, transport=transport, secrets=[TEST_PASSWORD]
    )

    assert run.status == 0
    assert run.output == f"Signed in as {TEST_EMAIL} to the Studio {LOCAL}.\n"
    assert [request.path for request in transport.sent] == [
        f"{API}/health",
        MODE_PATH,
        f"{API}/auth/login",
    ]
    transport.assert_done()
