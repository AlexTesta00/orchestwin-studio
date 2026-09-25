from __future__ import annotations

import pytest

from orchestwin.artifacts.mockup_layout import COLUMN_ZONE, MAIN_ZONE, SEARCH_ZONE, layout_zones
from orchestwin.artifacts.visual_catalog import LayoutArchetype


def element(kind: str, content: str | None = None) -> dict[str, object]:
    return {"kind": kind, "content": content or kind.lower()}


def kinds(zone) -> list[str]:
    return [str(item["kind"]) for item in zone]


def names(zones) -> list[str]:
    return [name for name, _ in zones]


def test_single_column_archetypes_keep_one_main_zone():
    elements = [element("HEADING"), element("TEXT_INPUT"), element("BUTTON")]
    for archetype in (
        LayoutArchetype.GUIDED_STEPS,
        LayoutArchetype.SINGLE_CARD,
        LayoutArchetype.FOCUS_MODE,
    ):
        zones = layout_zones(archetype, elements)
        assert names(zones) == [MAIN_ZONE]
        assert kinds(zones[0][1]) == ["HEADING", "TEXT_INPUT", "BUTTON"]


def test_dashboard_lifts_tiles_and_list_detail_moves_collections_aside():
    elements = [
        element("HEADING"),
        element("STATUS"),
        element("CARD"),
        element("LIST"),
        element("BUTTON"),
    ]
    dashboard = layout_zones(LayoutArchetype.DASHBOARD, elements)
    assert names(dashboard) == ["tiles", MAIN_ZONE]
    assert kinds(dashboard[0][1]) == ["STATUS", "CARD"]
    assert kinds(dashboard[1][1]) == ["HEADING", "LIST", "BUTTON"]
    detail = layout_zones(LayoutArchetype.LIST_DETAIL, elements)
    assert names(detail) == ["aside", MAIN_ZONE]
    assert kinds(detail[0][1]) == ["CARD", "LIST"]
    assert kinds(detail[1][1]) == ["HEADING", "STATUS", "BUTTON"]


def test_split_conversational_table_gallery_and_feed_zones():
    split = layout_zones(
        LayoutArchetype.SPLIT_SCREEN,
        [element("HEADING"), element("TEXT_INPUT"), element("BUTTON"), element("CARD")],
    )
    assert names(split) == [MAIN_ZONE, "aside"]
    conversation = layout_zones(
        LayoutArchetype.CONVERSATIONAL,
        [
            element("HEADING"),
            element("TEXT"),
            element("TEXT"),
            element("TEXT_INPUT"),
            element("BUTTON"),
        ],
    )
    assert names(conversation) == [MAIN_ZONE, "thread", "composer"]
    assert kinds(conversation[1][1]) == ["TEXT", "TEXT"]
    table = layout_zones(
        LayoutArchetype.TABLE_FIRST,
        [element("HEADING"), element("LIST"), element("LIST"), element("BUTTON")],
    )
    assert names(table) == ["intro", "table", MAIN_ZONE]
    gallery = layout_zones(
        LayoutArchetype.CARD_GALLERY,
        [element("HEADING"), element("CARD"), element("CARD"), element("LINK")],
    )
    assert names(gallery) == ["intro", "gallery", MAIN_ZONE]
    feed = layout_zones(
        LayoutArchetype.FEED_TIMELINE,
        [
            element("HEADING"),
            element("TEXT_INPUT"),
            element("BUTTON"),
            element("CARD"),
            element("CARD"),
            element("LINK"),
        ],
    )
    assert names(feed) == ["intro", "composer", "timeline", MAIN_ZONE]
    assert kinds(feed[3][1]) == ["LINK"]


def test_kanban_columns_follow_headings_and_search_takes_the_first_query_controls():
    board = layout_zones(
        LayoutArchetype.KANBAN_BOARD,
        [
            element("CARD", "orphan"),
            element("HEADING", "To do"),
            element("CARD", "a"),
            element("CARD", "b"),
            element("HEADING", "Done"),
            element("CARD", "c"),
            element("BUTTON"),
        ],
    )
    assert names(board) == [COLUMN_ZONE, COLUMN_ZONE, MAIN_ZONE]
    assert [item["content"] for item in board[0][1]] == ["To do", "a", "b"]
    assert [item["content"] for item in board[1][1]] == ["Done", "c"]
    assert [item["content"] for item in board[2][1]] == ["orphan", "button"]
    search = layout_zones(
        LayoutArchetype.SEARCH_FIRST,
        [
            element("HEADING"),
            element("TEXT_INPUT", "query"),
            element("BUTTON", "search"),
            element("LIST"),
            element("TEXT_INPUT", "filter"),
            element("BUTTON", "apply"),
        ],
    )
    assert names(search) == ["intro", SEARCH_ZONE, MAIN_ZONE]
    assert [item["content"] for item in search[1][1]] == ["query", "search"]
    assert [item["content"] for item in search[2][1]] == ["list", "filter", "apply"]


@pytest.mark.parametrize("archetype", list(LayoutArchetype))
def test_every_element_is_placed_exactly_once(archetype):
    elements = [
        element(kind, f"{kind}-{index}")
        for index, kind in enumerate(
            ("HEADING", "TEXT", "TEXT_INPUT", "SELECT", "BUTTON", "LINK", "LIST", "CARD", "STATUS")
            * 2
        )
    ]
    zones = layout_zones(archetype, elements)
    placed = [item["content"] for _, items in zones for item in items]
    assert sorted(placed) == sorted(item["content"] for item in elements)
    assert all(items for _, items in zones)
