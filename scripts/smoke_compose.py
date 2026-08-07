"""Build and smoke-test the local OrchesTwin Studio Compose platform."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
COMPOSE_FILE: Final = PROJECT_ROOT / "compose.yaml"
SERVICES: Final = ("database", "api", "frontend")
HEALTH_TIMEOUT_SECONDS: Final = 240.0


class SmokeFailure(RuntimeError):
    """Raised when the container platform violates its smoke contract."""


@dataclass(frozen=True, slots=True)
class SmokeEnvironment:
    """Ephemeral ports and credentials for one isolated smoke run."""

    project_name: str
    api_port: int
    frontend_port: int
    database_name: str = "orchestwin_smoke"
    database_user: str = "orchestwin_smoke"
    database_password: str = ""

    def variables(self) -> dict[str, str]:
        """Return the environment used for Compose interpolation."""
        variables = os.environ.copy()
        variables.update(
            {
                "DOCKER_BUILDKIT": "1",
                "ORCHESTWIN_API_PORT": str(self.api_port),
                "ORCHESTWIN_FRONTEND_PORT": str(self.frontend_port),
                "ORCHESTWIN_POSTGRES_DB": self.database_name,
                "ORCHESTWIN_POSTGRES_USER": self.database_user,
                "ORCHESTWIN_POSTGRES_PASSWORD": self.database_password,
            }
        )
        return variables


def available_port() -> int:
    """Ask the operating system for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def create_environment() -> SmokeEnvironment:
    """Create an isolated Compose project configuration."""
    return SmokeEnvironment(
        project_name=f"orchestwin-smoke-{os.getpid()}",
        api_port=available_port(),
        frontend_port=available_port(),
        database_password=secrets.token_urlsafe(24),
    )


def run(
    command: list[str],
    environment: dict[str, str],
    *,
    check: bool = True,
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and preserve complete diagnostics."""
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError as error:
        raise SmokeFailure(f"unable to execute {' '.join(command)}: {error}") from error

    if check and result.returncode != 0:
        raise SmokeFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n\n"
            f"stdout:\n{result.stdout or '<empty>'}\n\n"
            f"stderr:\n{result.stderr or '<empty>'}"
        )

    return result


def compose(
    environment: SmokeEnvironment,
    *arguments: str,
    check: bool = True,
    timeout: float = 900.0,
) -> subprocess.CompletedProcess[str]:
    """Run Docker Compose for the isolated smoke project."""
    command = [
        "docker",
        "compose",
        "--project-name",
        environment.project_name,
        "--file",
        str(COMPOSE_FILE),
        *arguments,
    ]

    return run(
        command,
        environment.variables(),
        check=check,
        timeout=timeout,
    )


def container_id(environment: SmokeEnvironment, service: str) -> str:
    """Return the single container ID for a Compose service."""
    identifiers = compose(environment, "ps", "--quiet", service).stdout.splitlines()

    if len(identifiers) != 1:
        raise SmokeFailure(f"expected one container for {service}, found {len(identifiers)}")

    return identifiers[0]


def inspect(environment: SmokeEnvironment, service: str) -> dict[str, object]:
    """Return the Docker inspection payload for a Compose service."""
    result = run(
        ["docker", "inspect", container_id(environment, service)],
        environment.variables(),
    )
    payload = json.loads(result.stdout)

    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SmokeFailure(f"unexpected Docker inspection payload for {service}")

    return payload[0]


def mapping(value: object, name: str) -> dict[str, object]:
    """Require a mapping-shaped inspection field."""
    if not isinstance(value, dict):
        raise SmokeFailure(f"inspection field is not a mapping: {name}")

    return value


def health_status(inspection: dict[str, object]) -> str:
    """Extract a container health status."""
    state = mapping(inspection.get("State"), "State")
    health = mapping(state.get("Health"), "State.Health")
    status = health.get("Status")

    if not isinstance(status, str):
        raise SmokeFailure("container health status is not a string")

    return status


def wait_for_platform(environment: SmokeEnvironment) -> None:
    """Wait until database, API, and frontend are healthy."""
    deadline = monotonic() + HEALTH_TIMEOUT_SECONDS
    latest: dict[str, str] = {}

    while monotonic() < deadline:
        all_healthy = True

        for service in SERVICES:
            inspection = inspect(environment, service)
            state = mapping(inspection.get("State"), "State")

            if state.get("Running") is not True:
                raise SmokeFailure(f"service stopped during startup: {service}")

            status = health_status(inspection)
            latest[service] = status

            if status == "unhealthy":
                raise SmokeFailure(f"service became unhealthy: {service}")

            if status != "healthy":
                all_healthy = False

        if all_healthy:
            return

        sleep(1)

    raise SmokeFailure(f"platform health timeout: {latest}")


def http_get(url: str) -> tuple[int, str, str]:
    """Request a loopback URL and return status, content type, and body."""
    try:
        with urlopen(
            Request(url, headers={"Accept": "*/*"}),
            timeout=5,
        ) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode("utf-8"),
            )
    except (HTTPError, URLError, TimeoutError) as error:
        raise SmokeFailure(f"HTTP request failed for {url}: {error}") from error


def verify_http(environment: SmokeEnvironment) -> None:
    """Verify API, frontend health, and static document contracts."""
    status, content_type, body = http_get(f"http://127.0.0.1:{environment.api_port}/api/v1/health")

    if status != 200 or not content_type.startswith("application/json"):
        raise SmokeFailure("API health response has an unexpected status or content type")

    if json.loads(body) != {"status": "ok"}:
        raise SmokeFailure(f"API health returned an unexpected payload: {body!r}")

    status, _, body = http_get(f"http://127.0.0.1:{environment.frontend_port}/healthz")

    if status != 200 or body.strip() != "ok":
        raise SmokeFailure("frontend health contract failed")

    status, content_type, body = http_get(f"http://127.0.0.1:{environment.frontend_port}/")

    if status != 200 or not content_type.startswith("text/html"):
        raise SmokeFailure("frontend document response is invalid")

    if "<title>OrchesTwin Studio</title>" not in body:
        raise SmokeFailure("frontend document title is missing")


def verify_database(environment: SmokeEnvironment) -> None:
    """Verify PostgreSQL with a deterministic query."""
    result = compose(
        environment,
        "exec",
        "--no-tty",
        "database",
        "psql",
        "--username",
        environment.database_user,
        "--dbname",
        environment.database_name,
        "--tuples-only",
        "--no-align",
        "--command",
        "SELECT 1;",
    )

    if result.stdout.strip() != "1":
        raise SmokeFailure(f"database query returned: {result.stdout!r}")


def verify_no_docker_socket(inspection: dict[str, object]) -> None:
    """Reject any Docker socket mount."""
    mounts = inspection.get("Mounts")

    if not isinstance(mounts, list):
        raise SmokeFailure("inspection payload is missing mounts")

    for mount in mounts:
        if not isinstance(mount, dict):
            continue

        values = (
            str(mount.get("Source", "")),
            str(mount.get("Destination", "")),
        )

        if any("docker.sock" in value for value in values):
            raise SmokeFailure("container mounts the Docker socket")


def verify_application_security(
    inspection: dict[str, object],
    *,
    container_port: str,
    host_port: int,
) -> None:
    """Verify non-root, read-only, capability, and port-binding controls."""
    configuration = mapping(inspection.get("Config"), "Config")
    host = mapping(inspection.get("HostConfig"), "HostConfig")
    network = mapping(inspection.get("NetworkSettings"), "NetworkSettings")

    user = str(configuration.get("User", "")).split(":", maxsplit=1)[0]

    if user in {"", "0", "root"}:
        raise SmokeFailure(f"application container is configured as root: {user!r}")

    if host.get("ReadonlyRootfs") is not True:
        raise SmokeFailure("application root filesystem is not read-only")

    if host.get("Init") is not True:
        raise SmokeFailure("application container is missing init=true")

    cap_drop = host.get("CapDrop")

    if not isinstance(cap_drop, list) or "ALL" not in {str(value).upper() for value in cap_drop}:
        raise SmokeFailure("application container does not drop all capabilities")

    security_options = host.get("SecurityOpt")

    if not isinstance(security_options, list) or not any(
        str(value).startswith("no-new-privileges") for value in security_options
    ):
        raise SmokeFailure("application container is missing no-new-privileges")

    memory = host.get("Memory")

    if not isinstance(memory, int) or memory <= 0:
        raise SmokeFailure("application container has no memory limit")

    pids_limit = host.get("PidsLimit")

    if not isinstance(pids_limit, int) or pids_limit <= 0:
        raise SmokeFailure("application container has no PID limit")

    verify_no_docker_socket(inspection)

    ports = mapping(network.get("Ports"), "NetworkSettings.Ports")
    bindings = ports.get(container_port)

    if not isinstance(bindings, list) or len(bindings) != 1:
        raise SmokeFailure(f"unexpected binding for {container_port}: {bindings!r}")

    binding = mapping(bindings[0], f"binding {container_port}")

    if binding.get("HostIp") != "127.0.0.1":
        raise SmokeFailure(f"{container_port} is not bound to loopback")

    if binding.get("HostPort") != str(host_port):
        raise SmokeFailure(f"{container_port} uses an unexpected host port")


def verify_security(environment: SmokeEnvironment) -> None:
    """Verify the container security and network exposure baseline."""
    verify_application_security(
        inspect(environment, "api"),
        container_port="8000/tcp",
        host_port=environment.api_port,
    )
    verify_application_security(
        inspect(environment, "frontend"),
        container_port="8080/tcp",
        host_port=environment.frontend_port,
    )

    database = inspect(environment, "database")
    verify_no_docker_socket(database)

    network = mapping(database.get("NetworkSettings"), "NetworkSettings")
    ports = mapping(network.get("Ports"), "NetworkSettings.Ports")

    if any(bindings for bindings in ports.values()):
        raise SmokeFailure("database publishes a host port")


def diagnostics(environment: SmokeEnvironment) -> None:
    """Print status and logs without masking the original failure."""
    for arguments in (
        ("ps", "--all"),
        ("logs", "--no-color"),
    ):
        try:
            result = compose(
                environment,
                *arguments,
                check=False,
                timeout=60,
            )
        except (SmokeFailure, subprocess.TimeoutExpired) as error:
            print(
                f"unable to collect diagnostics: {error}",
                file=sys.stderr,
            )
            continue

        if result.stdout:
            print(result.stdout, file=sys.stderr)

        if result.stderr:
            print(result.stderr, file=sys.stderr)


def cleanup(environment: SmokeEnvironment) -> None:
    """Remove containers, networks, and smoke-test volumes."""
    compose(
        environment,
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        timeout=120,
    )


def main() -> None:
    """Build, start, verify, and remove the complete platform."""
    environment = create_environment()
    failure: Exception | None = None

    try:
        compose(environment, "config", "--quiet")
        compose(
            environment,
            "up",
            "--build",
            "--detach",
            "--remove-orphans",
        )
        wait_for_platform(environment)
        verify_http(environment)
        verify_database(environment)
        verify_security(environment)
    except (
        SmokeFailure,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        failure = error
        diagnostics(environment)
    finally:
        try:
            cleanup(environment)
        except (SmokeFailure, subprocess.TimeoutExpired) as error:
            if failure is None:
                failure = error
            else:
                print(
                    f"cleanup also failed: {error}",
                    file=sys.stderr,
                )

    if failure is not None:
        raise SystemExit(f"Compose platform smoke test: FAIL\n{failure}")

    print(
        "Compose platform smoke test: PASS "
        f"(api={environment.api_port}, "
        f"frontend={environment.frontend_port})"
    )


if __name__ == "__main__":
    main()
