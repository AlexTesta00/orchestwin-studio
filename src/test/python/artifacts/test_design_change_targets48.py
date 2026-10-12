from __future__ import annotations

import json

import pytest

from orchestwin.artifacts.design_change_targets import (
    DESIGN_CHANGE_TARGET_INVALID,
    ELEMENT_PART_KIND,
    MAX_PART_HTML_LENGTH,
    MAX_ZONE_HTML_LENGTH,
    DesignChangeTargetError,
    describe_target,
    target_codes,
    validate_target,
)
from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockups import GeneratedMockup

from .test_generated_mockup_support import BASE_SECOND, LIGHT_TOKENS, build
from .test_generated_mockup_zones48 import BOTTEGA

SEARCH_HTML = (
    '<form aria-label="Cerca nel quartiere" data-ot-zone="ZON-002" role="search">'
    '<input aria-label="Cosa cerchi oggi?" data-elm="ELM-004" name="q" type="search">'
    '<button data-elm="ELM-005" type="button">Cerca</button></form>'
)
TILES_HTML = (
    '<ul class="ptiles" data-ot-zone="ZON-006"><li data-elm="ELM-009">Pane di segale</li>'
    '<li data-elm="ELM-010">Focaccia</li></ul>'
)


@pytest.fixture(scope="module")
def mockup() -> GeneratedMockup:
    return build(BOTTEGA, BASE_SECOND)


def failure(target: dict[str, object], mockup: GeneratedMockup) -> DesignChangeTargetError:
    with pytest.raises(DesignChangeTargetError) as raised:
        validate_target(target, mockup)
    return raised.value


@pytest.mark.parametrize(
    ("target", "codes"),
    [
        ({"screen_code": "SCR-001"}, ()),
        ({"screen_code": "SCR-001", "label": "Home"}, ()),
        ({"screen_code": "SCR-001", "element_code": "ELM-004"}, ("ELM-004",)),
        ({"screen_code": "SCR-001", "element_code": "ZON-002"}, ("ZON-002",)),
        (
            {
                "screen_code": "SCR-001",
                "elements": [{"element_code": "ZON-006"}, {"element_code": "ELM-007"}],
            },
            ("ZON-006", "ELM-007"),
        ),
    ],
)
def test_the_codes_of_a_target_come_from_its_parts_or_its_element(
    target: dict[str, object], codes: tuple[str, ...]
) -> None:
    assert target_codes(target) == codes


@pytest.mark.parametrize(
    "target",
    [
        {"screen_code": "SCR-002"},
        {"screen_code": "SCR-001", "element_code": "ELM-014"},
        {"screen_code": "SCR-001", "element_code": "ZON-007"},
        {"screen_code": "SCR-002", "element_code": "ZON-008"},
        {
            "screen_code": "SCR-001",
            "elements": [{"element_code": "ELM-001"}, {"element_code": "ZON-005"}],
        },
    ],
)
def test_codes_of_the_screen_are_accepted(
    target: dict[str, object], mockup: GeneratedMockup
) -> None:
    assert validate_target(target, mockup) is None


@pytest.mark.parametrize(
    "target",
    [
        {"screen_code": "SCR-009"},
        {"element_code": "ELM-001"},
        {"screen_code": "SCR-001", "element_code": "ELM-015"},
        {"screen_code": "SCR-001", "element_code": "ELM-999"},
        {"screen_code": "SCR-001", "element_code": "ZON-008"},
        {"screen_code": "SCR-001", "element_code": "ZON-099"},
        {
            "screen_code": "SCR-001",
            "elements": [{"element_code": "ELM-001"}, {"element_code": "ELM-020"}],
        },
        {
            "screen_code": "SCR-001",
            "elements": [{"element_code": "ZON-005"}, {"element_code": "ZON-005"}],
        },
    ],
)
def test_a_screen_or_a_code_that_the_screen_does_not_hold_is_refused(
    target: dict[str, object], mockup: GeneratedMockup
) -> None:
    assert failure(target, mockup).code == DESIGN_CHANGE_TARGET_INVALID
    with pytest.raises(DesignChangeTargetError):
        describe_target(target, mockup)


@pytest.mark.parametrize(
    "target",
    [
        {"screen_code": "SCR-001"},
        {"screen_code": "SCR-001", "label": "Home", "html": "<main>…</main>"},
        {
            "screen_code": "SCR-001",
            "element_code": "ELM-013",
            "label": "Vedi i prodotti",
            "html": '<a data-elm="ELM-013" href="#SCR-002">Vedi i prodotti</a>',
        },
    ],
)
def test_a_screen_or_an_element_with_the_values_of_the_page_is_described_as_sent(
    target: dict[str, object], mockup: GeneratedMockup
) -> None:
    view = describe_target(target, mockup)
    assert view == target
    assert json.dumps(view, ensure_ascii=False) == json.dumps(target, ensure_ascii=False)
    assert view is not target


def test_an_element_without_its_values_takes_them_from_the_mockup(
    mockup: GeneratedMockup,
) -> None:
    assert describe_target({"screen_code": "SCR-001", "element_code": "ELM-013"}, mockup) == {
        "screen_code": "SCR-001",
        "element_code": "ELM-013",
        "label": "Vedi i prodotti",
        "html": '<a data-elm="ELM-013" href="#SCR-002">Vedi i prodotti</a>',
    }
    labelled = {"screen_code": "SCR-001", "element_code": "ELM-004", "label": "Ricerca"}
    assert describe_target(labelled, mockup) == {
        **labelled,
        "html": '<input aria-label="Cosa cerchi oggi?" data-elm="ELM-004" name="q" type="search">',
    }


def test_a_zone_is_described_by_the_server(mockup: GeneratedMockup) -> None:
    view = describe_target(
        {"screen_code": "SCR-001", "element_code": "ZON-002", "label": "Ricerca"}, mockup
    )
    assert view == {
        "screen_code": "SCR-001",
        "element_code": "ZON-002",
        "kind": "form",
        "label": "Cerca nel quartiere",
        "html": SEARCH_HTML,
        "holds": ["ELM-004", "ELM-005"],
    }
    assert list(view) == ["screen_code", "element_code", "kind", "label", "html", "holds"]


def test_the_markup_of_a_zone_is_the_one_of_the_page_with_zones(mockup: GeneratedMockup) -> None:
    page = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it", zones=True)
    for code in ("ZON-002", "ZON-004", "ZON-005", "ZON-006"):
        view = describe_target({"screen_code": "SCR-001", "element_code": code}, mockup)
        assert view["html"] in page
    nested = describe_target({"screen_code": "SCR-001", "element_code": "ZON-005"}, mockup)
    assert TILES_HTML in nested["html"]
    assert nested["holds"] == ["ELM-007", "ELM-008", "ELM-009", "ELM-010"]


def test_several_parts_are_described_in_the_order_of_the_page(mockup: GeneratedMockup) -> None:
    target = {
        "screen_code": "SCR-001",
        "elements": [
            {"element_code": "ZON-006", "label": "Prodotti"},
            {"element_code": "ELM-007", "label": "Titolo del forno"},
            {"element_code": "ELM-002"},
        ],
    }
    assert describe_target(target, mockup) == {
        "screen_code": "SCR-001",
        "elements": [
            {
                "element_code": "ELM-002",
                "kind": ELEMENT_PART_KIND,
                "label": "Accedi",
                "html": '<button data-elm="ELM-002" type="button">Accedi</button>',
            },
            {
                "element_code": "ELM-007",
                "kind": ELEMENT_PART_KIND,
                "label": "Titolo del forno",
                "html": '<h2 data-elm="ELM-007">Forno Ravasi</h2>',
            },
            {
                "element_code": "ZON-006",
                "kind": "list",
                "label": "Pane di segale Focaccia",
                "html": TILES_HTML,
                "holds": ["ELM-009", "ELM-010"],
            },
        ],
    }


def test_a_long_zone_loses_its_last_children_and_keeps_its_tags() -> None:
    texts = [f"Voce del listino numero {number}" for number in range(1, 301)]
    items = "".join(f"<li>{text}</li>" for text in texts)
    mockup = build(f'<main data-req="REQ-001"><h1>Listino</h1><ul>{items}</ul></main>', BASE_SECOND)
    html = describe_target({"screen_code": "SCR-001", "element_code": "ZON-001"}, mockup)["html"]
    opening, closing = '<ul data-ot-zone="ZON-001">', "</ul>"
    written = [
        f'<li data-elm="ELM-{number + 1:03d}">{text}</li>'
        for number, text in enumerate(texts, start=1)
    ]
    kept = 0
    while len(opening) + sum(map(len, written[: kept + 1])) + len(closing) <= MAX_ZONE_HTML_LENGTH:
        kept += 1
    assert 0 < kept < len(written)
    assert html == opening + "".join(written[:kept]) + closing
    assert len(html) <= MAX_ZONE_HTML_LENGTH


def test_a_long_element_loses_its_last_children_and_keeps_its_tags() -> None:
    words = "".join(f"<b>parola {number}</b> " for number in range(400))
    mockup = build(
        f'<main data-req="REQ-001"><h1>Testo</h1><p>{words}</p><p>Fine.</p></main>', BASE_SECOND
    )
    view = describe_target({"screen_code": "SCR-001", "element_code": "ELM-002"}, mockup)
    html = view["html"]
    assert html.startswith('<p data-elm="ELM-002"><b>parola 0</b> ')
    assert html.endswith("</p>")
    assert html.count("<b>") == html.count("</b>") > 0
    assert len(html) <= MAX_PART_HTML_LENGTH < len(words)
