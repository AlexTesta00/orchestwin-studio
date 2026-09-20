"""Exercise real child processes without Docker or the developer's database."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from orchestwin.sandbox.host_process import run_bounded_host_process


def run_code(code: str, *, limit: int = 8192, timeout: int = 3, overrides=None):
    return asyncio.run(
        run_bounded_host_process(
            (sys.executable, "-c", code),
            timeout_seconds=timeout,
            maximum_output_bytes_per_stream=limit,
            environment_overrides={} if overrides is None else overrides,
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_real_process_runs_on_selector_loop() -> None:
    result = run_code("import sys; print('observed'); print('err', file=sys.stderr)")
    assert result.status == "COMPLETED"
    assert result.exit_code == 0
    assert result.stdout.strip() == b"observed"
    assert result.stderr.strip() == b"err"


def test_nonzero_exit_is_not_a_spawn_error() -> None:
    result = run_code("raise SystemExit(7)")
    assert result.status == "COMPLETED"
    assert result.exit_code == 7


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_output_is_bounded(stream: str) -> None:
    result = run_code(f"import sys; sys.{stream}.write('x' * 200000)", limit=257)
    assert result.status == "OUTPUT_LIMIT_EXCEEDED"
    assert result.exit_code is None
    assert len(result.stdout) <= 257
    assert len(result.stderr) <= 257


def test_timeout_kills_the_process() -> None:
    result = run_code("import time; time.sleep(30)", timeout=1)
    assert result.status == "TIMED_OUT"
    assert result.exit_code is None


def test_missing_executable_is_redacted() -> None:
    result = asyncio.run(
        run_bounded_host_process(
            ("this-executable-does-not-exist-orchestwin",),
            timeout_seconds=1,
            maximum_output_bytes_per_stream=64,
            environment_overrides={},
        )
    )
    assert result.status == "SPAWN_ERROR"
    assert b"this-executable" not in result.stderr


def test_environment_is_not_mutated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTWIN_PROCESS_TEST", "parent")
    result = run_code(
        "import os; print(os.environ['ORCHESTWIN_PROCESS_TEST'])",
        overrides={"ORCHESTWIN_PROCESS_TEST": "child"},
    )
    assert result.stdout.strip() == b"child"
    assert os.environ["ORCHESTWIN_PROCESS_TEST"] == "parent"


def test_arguments_are_not_interpreted_by_a_shell() -> None:
    async def scenario():
        return await run_bounded_host_process(
            (sys.executable, "-c", "import sys; print(sys.argv[1])", "a; echo b | c"),
            timeout_seconds=3,
            maximum_output_bytes_per_stream=1024,
            environment_overrides={},
        )

    assert asyncio.run(scenario()).stdout.strip() == b"a; echo b | c"


@pytest.mark.parametrize("timeout,limit", [(0, 10), (1, 0), (True, 2), (2, True)])
def test_invalid_limits_are_rejected(timeout, limit) -> None:
    with pytest.raises(ValueError):
        run_code("pass", timeout=timeout, limit=limit)


def test_cancellation_reaps_a_started_child(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    done = tmp_path / "should-not-exist"
    code = (
        "from pathlib import Path; import time; "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(2); "
        f"Path({str(done)!r}).write_text('not stopped')"
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            run_bounded_host_process(
                (sys.executable, "-c", code),
                timeout_seconds=8,
                maximum_output_bytes_per_stream=1024,
                environment_overrides={},
            )
        )
        async with asyncio.timeout(5):
            while not ready.exists():
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(2.1)
        assert not done.exists()

    asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
