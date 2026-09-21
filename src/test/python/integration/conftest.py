"""Isolate PostgreSQL journeys without erasing immutable application audit data."""

from __future__ import annotations

import pytest

from orchestwin.persistence import load_database_settings
from src.test.python.integration.postgres_isolation import isolated_postgres_settings


@pytest.fixture(autouse=True)
def isolated_postgresql_journey(request, monkeypatch):
    # The profile-loader tests already own independent schemas; the two opt-in
    # Docker/operation suites manage their own explicitly configured databases.
    module_name = request.path.name
    if (
        request.node.get_closest_marker("integration") is None
        or not module_name.startswith("test_postgresql_")
        or module_name == "test_postgresql_web_profile_loader.py"
    ):
        yield
        return
    settings = load_database_settings(env_file=None)
    with isolated_postgres_settings(settings) as scoped:
        monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", scoped.url.get_secret_value())
        yield
