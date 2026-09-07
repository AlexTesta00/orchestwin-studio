"""Pinned LangGraph Graph API smoke contract."""

from __future__ import annotations

from importlib.metadata import version
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class _SmokeState(TypedDict):
    value: int


def test_langgraph_runtime_is_exactly_pinned() -> None:
    assert version("langgraph") == "1.2.11"


def test_pinned_runtime_compiles_the_required_graph_api() -> None:
    builder = StateGraph(_SmokeState)
    builder.add_node("increment", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)

    graph = builder.compile()

    assert graph.invoke({"value": 1}) == {"value": 2}
