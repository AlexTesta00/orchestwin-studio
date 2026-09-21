"""Stdin transport must stay bounded and work on a selector event loop."""

import asyncio
import sys

import pytest

from orchestwin.sandbox.host_process import run_bounded_host_process


def invoke(code: str, data: bytes, *, limit: int = 1024):
    return asyncio.run(
        run_bounded_host_process(
            (sys.executable, "-c", code),
            timeout_seconds=3,
            maximum_output_bytes_per_stream=limit,
            environment_overrides={},
            stdin_bytes=data,
        ),
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_binary_stdin_and_eof_reach_child() -> None:
    data = bytes(range(256)) * 8
    result = invoke(
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", data, limit=4096
    )
    assert result.status == "COMPLETED"
    assert result.exit_code == 0
    assert result.stdout == data


def test_large_input_does_not_deadlock_on_simultaneous_output() -> None:
    code = (
        "import sys; sys.stderr.write('x'*90000); sys.stderr.flush(); "
        "print(len(sys.stdin.buffer.read()))"
    )
    result = invoke(code, b"a" * 200000, limit=100000)
    assert result.status == "COMPLETED"
    assert result.stdout.strip() == b"200000"
    assert len(result.stderr) == 90000


def test_input_size_is_bounded_before_spawn() -> None:
    with pytest.raises(ValueError, match="stdin"):
        invoke("raise AssertionError('must not spawn')", b"x" * (4 * 1024 * 1024 + 1))


def test_stdin_requires_bytes() -> None:
    with pytest.raises(ValueError, match="stdin"):
        invoke("pass", "not bytes")


def test_child_that_does_not_read_stdin_times_out() -> None:
    result = invoke("import time; time.sleep(10)", b"x" * 200000)
    assert result.status == "TIMED_OUT"


def test_early_closed_stdin_does_not_hide_exit_code() -> None:
    result = invoke("import sys; sys.exit(7)", b"x" * 200000)
    assert result.status == "COMPLETED"
    assert result.exit_code == 7
