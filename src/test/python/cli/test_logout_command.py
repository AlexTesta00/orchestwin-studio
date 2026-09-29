from __future__ import annotations

from pathlib import Path

import pytest

from .support.terminal import TEST_REFRESH_TOKEN, read_session, run_ut, store_session
from .support.transports import API, ScriptedTransport

LOCAL = "http://127.0.0.1:8000"
REMOTE = "https://studio.example.test"


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", f"Signed out of the Studio {LOCAL}.\n"),
        ("it", f"Uscita eseguita dallo Studio {LOCAL}.\n"),
    ],
)
def test_logout_tells_the_studio_and_forgets_the_session(
    tmp_path: Path, language: str, message: str
) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport().expect("POST", f"{API}/auth/logout", status=204)

    run = run_ut(["--lang", language, "logout"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output == message
    assert transport.sent[0].header("cookie") == f"orchestwin_refresh={TEST_REFRESH_TOKEN}"
    assert read_session(tmp_path) is None
    transport.assert_done()


def test_nobody_is_signed_in(tmp_path: Path) -> None:
    transport = ScriptedTransport()

    run = run_ut(["logout"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output == f"Nobody is signed in to the Studio {LOCAL} from this computer.\n"
    assert transport.sent == []


def test_a_session_without_tokens_is_cleaned_up(tmp_path: Path) -> None:
    store_session(tmp_path, access_token=None, refresh_token=None)

    run = run_ut(["--lang", "it", "logout"], tmp_path, transport=ScriptedTransport())

    assert run.status == 0
    assert run.output == (
        f"Nessuno ha eseguito l'accesso allo Studio {LOCAL} da questo computer.\n"
    )
    assert read_session(tmp_path) is None


def test_the_session_is_removed_even_when_the_studio_does_not_answer(tmp_path: Path) -> None:
    store_session(tmp_path)
    transport = ScriptedTransport().expect("POST", f"{API}/auth/logout", unreachable=True)

    run = run_ut(["logout"], tmp_path, transport=transport)

    assert run.status == 0
    assert run.output == (
        f"The Studio {LOCAL} does not answer: the sign-in was removed from this computer "
        "all the same.\n"
    )
    assert read_session(tmp_path) is None


def test_logout_of_one_studio_keeps_the_other(tmp_path: Path) -> None:
    store_session(tmp_path)
    store_session(tmp_path, studio=REMOTE, make_default=False)
    transport = ScriptedTransport().expect("POST", f"{API}/auth/logout", status=204)

    run = run_ut(["logout", "--studio", REMOTE], tmp_path, transport=transport)

    assert run.status == 0
    assert transport.sent[0].url == f"{REMOTE}{API}/auth/logout"
    assert read_session(tmp_path, REMOTE) is None
    assert read_session(tmp_path) is not None
