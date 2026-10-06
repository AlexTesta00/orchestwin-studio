import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestwin.config import (
    LOCAL_OWNER_DEFAULT_EMAIL,
    AccessMode,
    ApplicationSettings,
    load_settings,
)


@pytest.fixture(autouse=True)
def clear_studio_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name, raising=False)


def test_the_studio_keeps_accounts_and_no_owner_by_default() -> None:
    settings = load_settings(env_file=None)

    assert [mode.value for mode in AccessMode] == ["ACCOUNTS", "LOCAL_OWNER"]
    assert settings.access_mode is AccessMode.ACCOUNTS
    assert settings.local_owner_email is None
    assert LOCAL_OWNER_DEFAULT_EMAIL == "local-owner@example.com"
    assert settings.resolved_local_owner_email() == LOCAL_OWNER_DEFAULT_EMAIL


def test_the_access_mode_and_the_owner_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTWIN_ACCESS_MODE", "LOCAL_OWNER")
    monkeypatch.setenv("ORCHESTWIN_LOCAL_OWNER_EMAIL", " Owner@Example.COM ")

    settings = load_settings(env_file=None)

    assert settings.access_mode is AccessMode.LOCAL_OWNER
    assert settings.local_owner_email == "owner@example.com"
    assert settings.resolved_local_owner_email() == "owner@example.com"


def test_the_access_mode_and_the_owner_come_from_the_dotenv_file(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "ORCHESTWIN_ACCESS_MODE=LOCAL_OWNER\nORCHESTWIN_LOCAL_OWNER_EMAIL=owner@example.com\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file=dotenv)

    assert settings.access_mode is AccessMode.LOCAL_OWNER
    assert settings.resolved_local_owner_email() == "owner@example.com"


def test_local_mode_without_an_owner_uses_the_default_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORCHESTWIN_ACCESS_MODE", "LOCAL_OWNER")

    settings = load_settings(env_file=None)

    assert settings.access_mode is AccessMode.LOCAL_OWNER
    assert settings.local_owner_email is None
    assert settings.resolved_local_owner_email() == LOCAL_OWNER_DEFAULT_EMAIL


def test_an_owner_written_for_accounts_is_kept_but_has_no_effect() -> None:
    settings = ApplicationSettings(local_owner_email="owner@example.com", _env_file=None)

    assert settings.access_mode is AccessMode.ACCOUNTS
    assert settings.local_owner_email == "owner@example.com"


@pytest.mark.parametrize("email", ["", " ", "not-an-email", "owner@", "@example.com"])
def test_an_invalid_owner_email_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    email: str,
) -> None:
    monkeypatch.setenv("ORCHESTWIN_ACCESS_MODE", "LOCAL_OWNER")
    monkeypatch.setenv("ORCHESTWIN_LOCAL_OWNER_EMAIL", email)

    with pytest.raises(ValidationError, match="local_owner_email"):
        load_settings(env_file=None)


@pytest.mark.parametrize("mode", ["OPEN", "local", "LOCAL"])
def test_an_unknown_access_mode_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv("ORCHESTWIN_ACCESS_MODE", mode)

    with pytest.raises(ValidationError, match="access_mode"):
        load_settings(env_file=None)


def test_the_access_settings_are_immutable() -> None:
    settings = load_settings(env_file=None)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        settings.access_mode = AccessMode.LOCAL_OWNER
