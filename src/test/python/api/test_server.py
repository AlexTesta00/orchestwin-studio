"""Tests for the OrchesTwin ASGI server entry point."""

from importlib.metadata import entry_points

import pytest

from orchestwin.api.server import (
    APPLICATION_IMPORT,
    DEFAULT_HOST,
    DEFAULT_LOG_LEVEL,
    DEFAULT_PORT,
    ServerOptions,
    parse_server_options,
    run_server,
)


def test_server_options_use_local_defaults() -> None:
    """Bind the development server to deterministic local defaults."""
    options = parse_server_options([])

    assert options == ServerOptions(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
    )


def test_server_options_accept_explicit_host_and_port() -> None:
    """Allow deployment adapters to select another host and port."""
    options = parse_server_options(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
        ]
    )

    assert options == ServerOptions(
        host="0.0.0.0",
        port=8080,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["--host", " "],
        ["--port", "not-a-port"],
        ["--port", "0"],
        ["--port", "65536"],
    ],
)
def test_invalid_server_options_are_rejected(
    arguments: list[str],
) -> None:
    """Reject malformed network configuration before server startup."""
    with pytest.raises(SystemExit):
        parse_server_options(arguments)


def test_run_server_uses_the_application_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delegate startup to Uvicorn with explicit validated arguments."""
    captured_arguments: dict[str, object] = {}

    def fake_run(application: str, **arguments: object) -> None:
        captured_arguments["application"] = application
        captured_arguments.update(arguments)

    monkeypatch.setattr(
        "orchestwin.api.server.uvicorn.run",
        fake_run,
    )

    run_server(
        ServerOptions(
            host="0.0.0.0",
            port=9000,
        )
    )

    assert captured_arguments == {
        "application": APPLICATION_IMPORT,
        "factory": True,
        "host": "0.0.0.0",
        "port": 9000,
        "log_level": DEFAULT_LOG_LEVEL,
    }


def test_package_exposes_the_api_console_script() -> None:
    """Expose a stable executable command through package metadata."""
    matching_scripts = [
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "orchestwin-api"
    ]

    assert [entry_point.value for entry_point in matching_scripts] == ["orchestwin.api.server:main"]
