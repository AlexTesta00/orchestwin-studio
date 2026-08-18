"""Live-process smoke test for the OrchesTwin ASGI server."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from time import monotonic, sleep
from typing import Final

import pytest

HOST: Final = "127.0.0.1"
HEALTH_PATH: Final = "/api/v1/health"
STARTUP_TIMEOUT_SECONDS: Final = 15.0
REQUEST_TIMEOUT_SECONDS: Final = 1.0
SHUTDOWN_TIMEOUT_SECONDS: Final = 5.0
PROJECT_ROOT: Final = Path(__file__).resolve().parents[4]


class SmokeTestFailure(RuntimeError):
    """Raised when the live API process does not satisfy its smoke contract."""


class HealthConnectionFailure(SmokeTestFailure):
    """Raised while the live API process is not yet reachable over HTTP."""


@dataclass(frozen=True, slots=True)
class HealthResult:
    """Observed HTTP response from the live health endpoint."""

    status_code: int
    content_type: str
    payload: object


def select_available_port() -> int:
    """Select an unused loopback TCP port for the short-lived server process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((HOST, 0))
        return int(candidate.getsockname()[1])


def start_server(port: int) -> subprocess.Popen[str]:
    """Start the installed ASGI runner with deterministic test configuration."""
    environment = os.environ.copy()
    environment.update(
        {
            "ORCHESTWIN_APPLICATION_NAME": "OrchesTwin Smoke Test API",
            "ORCHESTWIN_ENVIRONMENT": "test",
            "ORCHESTWIN_DEBUG": "false",
            "ORCHESTWIN_LOG_LEVEL": "INFO",
            "ORCHESTWIN_API_PREFIX": "/api/v1",
            "PYTHONUNBUFFERED": "1",
        }
    )

    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "orchestwin.api.server",
            "--host",
            HOST,
            "--port",
            str(port),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def request_health(port: int) -> HealthResult:
    """Request and decode the live health endpoint without external clients."""
    connection = HTTPConnection(
        HOST,
        port,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    try:
        connection.request(
            "GET",
            HEALTH_PATH,
            headers={"Accept": "application/json"},
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type", "")
    except (HTTPException, OSError) as error:
        raise HealthConnectionFailure(f"health request failed: {error}") from error
    finally:
        connection.close()

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise SmokeTestFailure(f"health endpoint returned invalid JSON: {body!r}") from error

    return HealthResult(
        status_code=response.status,
        content_type=content_type,
        payload=payload,
    )


def wait_for_health(
    process: subprocess.Popen[str],
    port: int,
) -> HealthResult:
    """Poll the live health route until it responds or startup times out."""
    deadline = monotonic() + STARTUP_TIMEOUT_SECONDS
    last_connection_error: HealthConnectionFailure | None = None

    while monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise SmokeTestFailure(
                f"API process exited before becoming healthy with return code {return_code}"
            )

        try:
            return request_health(port)
        except HealthConnectionFailure as error:
            last_connection_error = error
            sleep(0.05)

    raise SmokeTestFailure(
        "API process did not become healthy within "
        f"{STARTUP_TIMEOUT_SECONDS:.0f} seconds; "
        f"last error: {last_connection_error}"
    )


def validate_health_contract(
    process: subprocess.Popen[str],
    result: HealthResult,
) -> None:
    """Validate the response contract while the child process remains alive."""
    if result.status_code != 200:
        raise SmokeTestFailure(f"health endpoint returned HTTP {result.status_code}, expected 200")

    if not result.content_type.startswith("application/json"):
        raise SmokeTestFailure(
            f"health endpoint returned unexpected content type: {result.content_type!r}"
        )

    if result.payload != {"status": "ok"}:
        raise SmokeTestFailure(f"health endpoint returned unexpected payload: {result.payload!r}")

    if process.poll() is not None:
        raise SmokeTestFailure("API process exited after serving the health request")


def stop_server(process: subprocess.Popen[str]) -> str:
    """Stop the child process and return its combined diagnostic output."""
    if process.poll() is None:
        process.terminate()

    try:
        output, _ = process.communicate(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()

    return output or ""


def test_live_server_starts_and_serves_health_contract() -> None:
    """Start the installed runner and verify its liveness contract over TCP."""
    port = select_available_port()
    process = start_server(port)
    failure: SmokeTestFailure | None = None

    try:
        result = wait_for_health(process, port)
        validate_health_contract(process, result)
    except SmokeTestFailure as error:
        failure = error
    finally:
        server_output = stop_server(process)

    if failure is not None:
        diagnostics = server_output.strip() or "<no server output>"
        pytest.fail(
            f"{failure}\n\nServer output:\n{diagnostics}",
            pytrace=False,
        )
