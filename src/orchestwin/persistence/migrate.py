"""Programmatic Alembic migration runner."""

from __future__ import annotations

import argparse
from importlib.resources import files
from typing import TextIO

from alembic import command
from alembic.config import Config

from orchestwin.persistence.config import DatabaseSettings, load_database_settings


def create_alembic_config(
    database_url: str,
    *,
    output_buffer: TextIO | None = None,
) -> Config:
    """Create an Alembic configuration independent from the working directory."""
    migration_directory = files("orchestwin.persistence.migrations")

    configuration = Config(output_buffer=output_buffer)
    configuration.set_main_option(
        "script_location",
        str(migration_directory),
    )
    configuration.set_main_option(
        "sqlalchemy.url",
        database_url.replace("%", "%%"),
    )

    return configuration


def upgrade_database(
    settings: DatabaseSettings,
    *,
    revision: str = "head",
) -> None:
    """Upgrade the configured database to a migration revision."""
    command.upgrade(
        create_alembic_config(settings.url.get_secret_value()),
        revision,
    )


def downgrade_database(
    settings: DatabaseSettings,
    *,
    revision: str,
) -> None:
    """Downgrade the configured database to a migration revision."""
    command.downgrade(
        create_alembic_config(settings.url.get_secret_value()),
        revision,
    )


def show_current_revision(settings: DatabaseSettings) -> None:
    """Print the current database revision."""
    command.current(
        create_alembic_config(settings.url.get_secret_value()),
        verbose=True,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the migration command-line parser."""
    parser = argparse.ArgumentParser(
        prog="orchestwin-migrate",
        description="Run OrchesTwin Studio database migrations.",
    )
    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    upgrade_parser = subcommands.add_parser(
        "upgrade",
        help="Upgrade the database.",
    )
    upgrade_parser.add_argument(
        "revision",
        nargs="?",
        default="head",
    )

    downgrade_parser = subcommands.add_parser(
        "downgrade",
        help="Downgrade the database.",
    )
    downgrade_parser.add_argument("revision")

    subcommands.add_parser(
        "current",
        help="Display the current revision.",
    )

    return parser


def main(arguments: list[str] | None = None) -> None:
    """Execute a migration command using environment configuration."""
    parsed = build_argument_parser().parse_args(arguments)
    settings = load_database_settings()

    if parsed.command == "upgrade":
        upgrade_database(
            settings,
            revision=parsed.revision,
        )
        return

    if parsed.command == "downgrade":
        downgrade_database(
            settings,
            revision=parsed.revision,
        )
        return

    show_current_revision(settings)


if __name__ == "__main__":
    main()
