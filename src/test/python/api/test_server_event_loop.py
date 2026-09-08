"""Regression tests for the Windows ASGI/Psycopg event-loop boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from uvicorn import Config

from orchestwin.api import server


@pytest.mark.parametrize(
    ("platform", "expected_loop"),
    [
        ("win32", "asyncio:SelectorEventLoop"),
        ("linux", "auto"),
        ("darwin", "auto"),
    ],
)
def test_server_selects_database_compatible_loop(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected_loop: str,
) -> None:
    """Pin Windows to Selector without changing the Unix selection policy."""
    captured: dict[str, object] = {}
    # Replace only this module's binding; never mutate the real sys.platform.
    monkeypatch.setattr(server, "sys", SimpleNamespace(platform=platform), raising=False)

    def capture_run(application: str, **options: object) -> None:
        captured.update(application=application, **options)

    monkeypatch.setattr(server.uvicorn, "run", capture_run)
    server.run_server(server.ServerOptions(host="127.0.0.1", port=8000))

    assert captured.get("loop") == expected_loop
    assert captured["application"] == server.APPLICATION_IMPORT
    assert captured["factory"] is True
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000


@pytest.mark.parametrize("workers", [1, 2])
def test_uvicorn_resolves_the_selected_windows_loop(
    monkeypatch: pytest.MonkeyPatch,
    workers: int,
) -> None:
    """Resolve the real Uvicorn loop hook and execute a coroutine on that loop."""
    captured: dict[str, object] = {}
    monkeypatch.setattr(server, "sys", SimpleNamespace(platform="win32"), raising=False)

    def capture_run(application: str, **options: object) -> None:
        del application
        captured.update(options)

    monkeypatch.setattr(server.uvicorn, "run", capture_run)
    server.run_server(server.ServerOptions(host="127.0.0.1", port=8000))
    selected = captured.get("loop")
    assert selected == "asyncio:SelectorEventLoop"

    # Config construction does not import the app, start workers, or bind HTTP.
    config = Config(server.APPLICATION_IMPORT, loop=selected, workers=workers)
    factory = config.get_loop_factory()
    assert factory is asyncio.SelectorEventLoop

    async def observed_loop() -> asyncio.AbstractEventLoop:
        await asyncio.sleep(0)
        return asyncio.get_running_loop()

    with asyncio.Runner(loop_factory=factory) as runner:
        loop = runner.run(observed_loop())
        assert isinstance(loop, asyncio.SelectorEventLoop)
    assert loop.is_closed()


def test_server_does_not_set_a_global_event_loop_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep selection local to Uvicorn, not a process-wide deprecated policy."""
    monkeypatch.setattr(server, "sys", SimpleNamespace(platform="win32"), raising=False)
    calls: list[object] = []

    def record_policy(value: object) -> None:
        calls.append(value)

    monkeypatch.setattr(asyncio, "set_event_loop_policy", record_policy)
    monkeypatch.setattr(server.uvicorn, "run", lambda *_args, **_kwargs: None)

    server.run_server(server.ServerOptions(host="127.0.0.1", port=8000))

    assert calls == []
