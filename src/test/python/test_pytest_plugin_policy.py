from __future__ import annotations

import pytest


def test_unused_langsmith_pytest_plugin_is_blocked(
    pytestconfig: pytest.Config,
) -> None:
    plugin_manager = pytestconfig.pluginmanager

    assert plugin_manager.is_blocked("langsmith_plugin")
    assert not plugin_manager.hasplugin("langsmith_plugin")
