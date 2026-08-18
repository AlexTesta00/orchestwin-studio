"""Tests for the initial OrchesTwin backend package and configuration boundary."""

from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from orchestwin import __version__
from orchestwin.config import LogLevel, RuntimeEnvironment, load_settings

SETTING_ENVIRONMENT_VARIABLES = (
    "ORCHESTWIN_APPLICATION_NAME",
    "ORCHESTWIN_ENVIRONMENT",
    "ORCHESTWIN_DEBUG",
    "ORCHESTWIN_LOG_LEVEL",
    "ORCHESTWIN_API_PREFIX",
)


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep settings tests independent from the developer or CI environment."""
    for variable_name in SETTING_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable_name, raising=False)
    yield


def test_backend_package_exposes_initial_version() -> None:
    """Expose package metadata without importing a framework application."""
    assert __version__ == "0.0.0"


def test_settings_use_safe_development_defaults() -> None:
    """Provide deterministic defaults without requiring a local dotenv file."""
    settings = load_settings(env_file=None)

    assert settings.application_name == "OrchesTwin Studio API"
    assert settings.environment is RuntimeEnvironment.DEVELOPMENT
    assert settings.debug is False
    assert settings.log_level is LogLevel.INFO
    assert settings.api_prefix == "/api/v1"


def test_settings_read_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse environment overrides through the OrchesTwin namespace only."""
    monkeypatch.setenv("ORCHESTWIN_ENVIRONMENT", "test")
    monkeypatch.setenv("ORCHESTWIN_DEBUG", "true")
    monkeypatch.setenv("ORCHESTWIN_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ORCHESTWIN_API_PREFIX", "/internal/v1/")

    settings = load_settings(env_file=None)

    assert settings.environment is RuntimeEnvironment.TEST
    assert settings.debug is True
    assert settings.log_level is LogLevel.DEBUG
    assert settings.api_prefix == "/internal/v1"


def test_settings_are_immutable() -> None:
    """Reject mutation after configuration has crossed the application boundary."""
    settings = load_settings(env_file=None)

    with pytest.raises(ValidationError, match="Instance is frozen"):
        settings.debug = True


def test_production_debug_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject the unsafe combination of production and debug mode."""
    monkeypatch.setenv("ORCHESTWIN_ENVIRONMENT", "production")
    monkeypatch.setenv("ORCHESTWIN_DEBUG", "true")

    with pytest.raises(ValidationError, match="debug must be disabled in production"):
        load_settings(env_file=None)


@pytest.mark.parametrize("api_prefix", ["", "/", "api/v1"])
def test_invalid_api_prefix_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    api_prefix: str,
) -> None:
    """Reject prefixes that are empty, root-only, or not absolute paths."""
    monkeypatch.setenv("ORCHESTWIN_API_PREFIX", api_prefix)

    with pytest.raises(
        ValidationError,
        match="api_prefix must be an absolute non-root path",
    ):
        load_settings(env_file=None)
