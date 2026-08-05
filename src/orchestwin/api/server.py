"""Command-line ASGI server runner for OrchesTwin Studio."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import uvicorn

APPLICATION_IMPORT: Final = "orchestwin.api.app:create_app"
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8000
DEFAULT_LOG_LEVEL: Final = "info"


@dataclass(frozen=True, slots=True)
class ServerOptions:
    """Validated network options for the ASGI server process."""

    host: str
    port: int


def parse_host(value: str) -> str:
    """Normalize and validate the server host argument."""
    normalized = value.strip()
    if not normalized:
        raise argparse.ArgumentTypeError("host must not be empty")
    return normalized


def parse_port(value: str) -> int:
    """Parse and validate a TCP port number."""
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error

    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")

    return port


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the backend server."""
    parser = argparse.ArgumentParser(
        prog="orchestwin-api",
        description="Run the OrchesTwin Studio FastAPI backend.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        type=parse_host,
        help=f"Host interface to bind. Default: {DEFAULT_HOST}.",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=parse_port,
        help=f"TCP port to bind. Default: {DEFAULT_PORT}.",
    )
    return parser


def parse_server_options(
    arguments: Sequence[str] | None = None,
) -> ServerOptions:
    """Parse command-line arguments into immutable server options."""
    namespace = build_argument_parser().parse_args(arguments)
    return ServerOptions(
        host=namespace.host,
        port=namespace.port,
    )


def run_server(options: ServerOptions) -> None:
    """Run Uvicorn using the FastAPI application factory."""
    uvicorn.run(
        APPLICATION_IMPORT,
        factory=True,
        host=options.host,
        port=options.port,
        log_level=DEFAULT_LOG_LEVEL,
    )


def main(arguments: Sequence[str] | None = None) -> None:
    """Parse command-line options and start the ASGI server."""
    run_server(parse_server_options(arguments))


if __name__ == "__main__":
    main()
