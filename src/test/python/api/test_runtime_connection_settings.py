"""Regression tests for dotenv-backed runtime enablement without environment mutation."""

from __future__ import annotations

import os
import traceback
from pathlib import Path

import pytest

from orchestwin.api.runtime_configuration import (
    RuntimeConfigurationError,
    load_runtime_connection_settings,
)

DATABASE_URL = "postgresql+psycopg://owner:sentinel-db-password@127.0.0.1:5432/runtime_test"
JWT_SECRET = "sentinel-jwt-secret-used-only-in-tests-0123456789"


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never depend on, modify, or print the developer's real configuration."""
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def write_configuration(path: Path, **overrides: str) -> bytes:
    values = {
        "ORCHESTWIN_DATABASE_URL": DATABASE_URL,
        "ORCHESTWIN_AUTH_JWT_SECRET": JWT_SECRET,
        **overrides,
    }
    content = "".join(f'{key}="{value}"\n' for key, value in values.items()).encode("utf-8")
    path.write_bytes(content)
    return content


def test_dotenv_alone_enables_validated_connection_settings(tmp_path: Path) -> None:
    original = write_configuration(tmp_path / ".env")
    before = dict(os.environ)

    result = load_runtime_connection_settings()

    assert result is not None
    assert result.database.url.get_secret_value() == DATABASE_URL
    assert result.access_tokens.signing_secret == JWT_SECRET
    assert dict(os.environ) == before
    assert (tmp_path / ".env").read_bytes() == original


def test_process_configuration_works_without_a_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", JWT_SECRET)

    result = load_runtime_connection_settings()

    assert result is not None
    assert result.database.url.get_secret_value() == DATABASE_URL
    assert result.access_tokens.signing_secret == JWT_SECRET


def test_process_values_override_dotenv_without_mutating_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = write_configuration(tmp_path / ".env")
    override_url = DATABASE_URL.replace("runtime_test", "runtime_override")
    override_secret = JWT_SECRET + "-override"
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", override_url)
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", override_secret)

    result = load_runtime_connection_settings()

    assert result is not None
    assert result.database.url.get_secret_value() == override_url
    assert result.access_tokens.signing_secret == override_secret
    assert (tmp_path / ".env").read_bytes() == original


@pytest.mark.parametrize("process_key", ["ORCHESTWIN_DATABASE_URL", "ORCHESTWIN_AUTH_JWT_SECRET"])
def test_configuration_may_be_split_across_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, process_key: str
) -> None:
    values = {"ORCHESTWIN_DATABASE_URL": DATABASE_URL, "ORCHESTWIN_AUTH_JWT_SECRET": JWT_SECRET}
    process_value = values.pop(process_key)
    (tmp_path / ".env").write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8"
    )
    monkeypatch.setenv(process_key, process_value)

    assert load_runtime_connection_settings() is not None


def test_no_credentials_preserves_unconfigured_runtime() -> None:
    assert load_runtime_connection_settings() is None


def test_unrelated_dotenv_values_do_not_enable_runtime(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "ORCHESTWIN_LOG_LEVEL=INFO\nOTHER_VALUE=ignored\n", encoding="utf-8"
    )
    assert load_runtime_connection_settings() is None


@pytest.mark.parametrize("only_key", ["ORCHESTWIN_DATABASE_URL", "ORCHESTWIN_AUTH_JWT_SECRET"])
def test_partial_configuration_is_not_silently_treated_as_unconfigured(
    tmp_path: Path, only_key: str
) -> None:
    values = {"ORCHESTWIN_DATABASE_URL": DATABASE_URL, "ORCHESTWIN_AUTH_JWT_SECRET": JWT_SECRET}
    (tmp_path / ".env").write_text(f"{only_key}={values[only_key]}\n", encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_INCOMPLETE"):
        load_runtime_connection_settings()


@pytest.mark.parametrize("blank", ["", "   "])
@pytest.mark.parametrize("key", ["ORCHESTWIN_DATABASE_URL", "ORCHESTWIN_AUTH_JWT_SECRET"])
def test_empty_process_value_never_falls_back_to_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str, blank: str
) -> None:
    write_configuration(tmp_path / ".env")
    monkeypatch.setenv(key, blank)
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_INCOMPLETE"):
        load_runtime_connection_settings()


@pytest.mark.parametrize(
    ("key", "value", "error_code"),
    [
        (
            "ORCHESTWIN_DATABASE_URL",
            "sqlite:///sentinel-invalid-url.db",
            "RUNTIME_DATABASE_CONFIGURATION_INVALID",
        ),
        (
            "ORCHESTWIN_DATABASE_URL",
            "sentinel-malformed-url",
            "RUNTIME_DATABASE_CONFIGURATION_INVALID",
        ),
        (
            "ORCHESTWIN_AUTH_JWT_SECRET",
            "sentinel-short",
            "RUNTIME_AUTH_CONFIGURATION_INVALID",
        ),
        (
            "ORCHESTWIN_DATABASE_POOL_SIZE",
            "sentinel-invalid-count",
            "RUNTIME_DATABASE_CONFIGURATION_INVALID",
        ),
        (
            "ORCHESTWIN_AUTH_ACCESS_TOKEN_LIFETIME_SECONDS",
            "sentinel-invalid-time",
            "RUNTIME_AUTH_CONFIGURATION_INVALID",
        ),
    ],
)
def test_invalid_settings_use_existing_validators_and_redact_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, value: str, error_code: str
) -> None:
    write_configuration(tmp_path / ".env", **{key: value})
    with pytest.raises(RuntimeConfigurationError, match=error_code) as caught:
        load_runtime_connection_settings()

    rendered = "".join(traceback.format_exception(caught.value))
    captured = capsys.readouterr()
    for secret in (DATABASE_URL, JWT_SECRET, value):
        assert secret not in rendered
        assert secret not in captured.out + captured.err
    assert caught.value.__suppress_context__ is True


def test_connection_settings_repr_does_not_expose_secrets(tmp_path: Path) -> None:
    write_configuration(tmp_path / ".env")
    result = load_runtime_connection_settings()
    assert result is not None
    assert DATABASE_URL not in repr(result)
    assert JWT_SECRET not in repr(result)
    assert "sentinel-db-password" not in repr(result.database)


def test_custom_dotenv_path_is_respected_by_both_validators(tmp_path: Path) -> None:
    custom = tmp_path / "runtime.env"
    write_configuration(
        custom,
        ORCHESTWIN_DATABASE_POOL_SIZE="7",
        ORCHESTWIN_AUTH_JWT_ISSUER="test-issuer",
    )
    result = load_runtime_connection_settings(env_file=custom)
    assert result is not None
    assert result.database.pool_size == 7
    assert result.access_tokens.jwt_issuer == "test-issuer"


def test_explicit_none_disables_dotenv(tmp_path: Path) -> None:
    write_configuration(tmp_path / ".env")
    assert load_runtime_connection_settings(env_file=None) is None


def test_lowercase_dotenv_keys_match_existing_settings_policy(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f"orchestwin_database_url={DATABASE_URL}\norchestwin_auth_jwt_secret={JWT_SECRET}\n",
        encoding="utf-8",
    )
    assert load_runtime_connection_settings() is not None


def test_loader_does_not_connect_to_database_or_build_an_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    write_configuration(tmp_path / ".env")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("configuration loading must not construct a database engine")

    monkeypatch.setattr("orchestwin.persistence.database.create_async_engine", forbidden)
    assert load_runtime_connection_settings() is not None


def test_unreadable_dotenv_uses_redacted_error(tmp_path: Path) -> None:
    (tmp_path / ".env").write_bytes(b"\xff\xfeinvalid-utf8")
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_UNREADABLE"):
        load_runtime_connection_settings()
