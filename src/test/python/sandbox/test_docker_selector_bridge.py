"""Exercise the actual Docker adapter bridge, not a second process-runner implementation."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from orchestwin.sandbox.docker_runtime import (
    AsyncioHostProcessRunner,
    HostProcessStatus,
    LocalDockerContainerRuntimeAdapter,
)


def test_existing_runner_does_not_need_event_loop_subprocess_support(monkeypatch) -> None:
    async def unsupported(*_args, **_kwargs):
        raise NotImplementedError("SelectorEventLoop cannot create subprocesses on Windows")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported)
    result = asyncio.run(
        AsyncioHostProcessRunner().run(
            (sys.executable, "-c", "print('actual-cli')"),
            timeout_seconds=3,
            maximum_output_bytes_per_stream=1024,
            environment_overrides={},
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )
    assert result.status is HostProcessStatus.COMPLETED
    assert result.stdout.strip() == b"actual-cli"


@pytest.mark.parametrize("confirmed", [True, False])
def test_cancelled_execution_attempts_cleanup_of_only_its_container(confirmed: bool) -> None:
    adapter = object.__new__(LocalDockerContainerRuntimeAdapter)
    adapter._clock = SimpleNamespace(now=lambda: datetime.now(UTC))
    adapter._preflight_failure = lambda _request: None
    adapter._build_run_arguments = lambda *_args, **_kwargs: ("docker",)
    adapter._runtime_policy = SimpleNamespace(maximum_output_bytes_per_stream=1024)
    adapter._process_runner = SimpleNamespace(run=AsyncMock(side_effect=asyncio.CancelledError))
    adapter._cleanup_container = AsyncMock(return_value=confirmed)
    request = SimpleNamespace(
        run_id=UUID(int=56),
        plan=SimpleNamespace(commands=(SimpleNamespace(timeout_seconds=5),)),
        environment_for=lambda _command: (),
    )
    expected = asyncio.CancelledError if confirmed else RuntimeError
    with pytest.raises(expected):
        asyncio.run(adapter.execute(request))
    adapter._cleanup_container.assert_awaited_once_with("orchestwin-000000000000-01")
