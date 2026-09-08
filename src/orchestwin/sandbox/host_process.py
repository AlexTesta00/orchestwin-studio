"""Bounded direct subprocess I/O compatible with Windows SelectorEventLoop.

The event loop stays available to Psycopg. Blocking pipe reads run in two
short-lived threads; a third worker supervises timeout, overflow and cancellation.
This runs a CLI process, not an authorization policy or container sandbox.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import BinaryIO


@dataclass(frozen=True, slots=True)
class BoundedHostProcessResult:
    """Private transport result converted to the existing HostProcessResult."""

    status: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    failure_message: str | None


async def run_bounded_host_process(
    arguments: tuple[str, ...],
    *,
    timeout_seconds: int,
    maximum_output_bytes_per_stream: int,
    environment_overrides: Mapping[str, str],
) -> BoundedHostProcessResult:
    """Invoke argv with no shell, bounded memory and cooperative cancellation."""
    if not arguments or any(not isinstance(part, str) or "\x00" in part for part in arguments):
        raise ValueError("host process requires a non-empty valid argument vector")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in (timeout_seconds, maximum_output_bytes_per_stream)
    ):
        raise ValueError("host process limits must be positive integers")
    environment = dict(os.environ)
    environment.update(environment_overrides)
    cancelled = threading.Event()
    worker = asyncio.create_task(
        asyncio.to_thread(
            _run_process,
            arguments,
            timeout_seconds,
            maximum_output_bytes_per_stream,
            environment,
            cancelled,
        )
    )
    try:
        # Shield keeps the supervisor alive long enough to terminate/reap the CLI.
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        # Repeated cancellation still cannot interrupt the worker's kill/reap logic.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled.set()
        worker.result()
        raise


def _run_process(
    arguments: tuple[str, ...],
    timeout_seconds: int,
    maximum_output: int,
    environment: dict[str, str],
    cancelled: threading.Event,
) -> BoundedHostProcessResult:
    buffers = (bytearray(), bytearray())
    overflow = threading.Event()
    read_error = threading.Event()
    finished = (threading.Event(), threading.Event())
    deadline = time.monotonic() + timeout_seconds
    if cancelled.is_set():
        return _failure("RUNTIME_ERROR", buffers, "Host process was cancelled before startup.")
    try:
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            shell=False,
            bufsize=0,
        )
    except (OSError, ValueError):
        return _failure("SPAWN_ERROR", buffers, "Host process could not be started.")
    pipes = (process.stdout, process.stderr)
    if any(pipe is None for pipe in pipes):
        _stop(process)
        return _failure("RUNTIME_ERROR", buffers, "Host process streams are unavailable.")

    def collect(pipe: BinaryIO, index: int) -> None:
        try:
            while chunk := pipe.read(65536):
                available = maximum_output - len(buffers[index])
                buffers[index].extend(chunk[:available])
                if len(chunk) > available:
                    overflow.set()
                    break
        except OSError:
            read_error.set()
        finally:
            pipe.close()
            finished[index].set()

    threads = []
    for index, pipe in enumerate(pipes):
        assert pipe is not None
        thread = threading.Thread(
            target=collect, args=(pipe, index), name="orchestwin-cli-stream", daemon=True
        )
        thread.start()
        threads.append(thread)

    status = "COMPLETED"
    try:
        while True:
            if cancelled.is_set():
                status = "RUNTIME_ERROR"
                break
            if overflow.is_set():
                status = "OUTPUT_LIMIT_EXCEEDED"
                break
            if read_error.is_set():
                status = "RUNTIME_ERROR"
                break
            if process.poll() is not None and all(event.is_set() for event in finished):
                break
            if time.monotonic() >= deadline:
                status = "TIMED_OUT"
                break
            cancelled.wait(0.01)
    finally:
        if status != "COMPLETED":
            _stop(process)
        else:
            process.wait()
        # Never wait indefinitely if a descendant has inherited a pipe handle.
        for thread in threads:
            thread.join(timeout=1)
    if overflow.is_set() and status == "COMPLETED":
        status = "OUTPUT_LIMIT_EXCEEDED"
    if status != "COMPLETED":
        messages = {
            "OUTPUT_LIMIT_EXCEEDED": "Host process output exceeded its stream limit.",
            "TIMED_OUT": "Host process exceeded its timeout.",
            "RUNTIME_ERROR": "Host process was cancelled or its streams failed.",
        }
        return _failure(status, buffers, messages[status])
    if process.returncode is None or not 0 <= process.returncode <= 255:
        return _failure("RUNTIME_ERROR", buffers, "Host process returned a non-portable exit code.")
    return BoundedHostProcessResult(
        "COMPLETED", process.returncode, bytes(buffers[0]), bytes(buffers[1]), None
    )


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Reap this CLI only. Container cleanup belongs to the Docker adapter."""
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()
    process.wait()


def _failure(status: str, buffers: tuple[bytearray, bytearray], message: str):
    return BoundedHostProcessResult(status, None, bytes(buffers[0]), bytes(buffers[1]), message)
