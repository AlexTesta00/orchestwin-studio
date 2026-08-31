from __future__ import annotations

import importlib

import pytest

_LANGSMITH_PYTHON_314_WARNING_FILTER = (
    r"ignore:.*asyncio\.iscoroutinefunction.*Python 3\.16.*:"
    r"DeprecationWarning:langsmith\..*"
)


def test_unused_langsmith_pytest_plugin_is_blocked(
    pytestconfig: pytest.Config,
) -> None:
    plugin_manager = pytestconfig.pluginmanager

    assert plugin_manager.is_blocked("langsmith_plugin")
    assert not plugin_manager.hasplugin("langsmith_plugin")


def test_langgraph_runtime_import_has_a_narrow_warning_exception(
    pytestconfig: pytest.Config,
) -> None:
    configured_filters = pytestconfig.getini("filterwarnings")

    assert configured_filters[0] == "error"
    assert _LANGSMITH_PYTHON_314_WARNING_FILTER in configured_filters

    langgraph_graph = importlib.import_module("langgraph.graph")
    assert hasattr(langgraph_graph, "StateGraph")
