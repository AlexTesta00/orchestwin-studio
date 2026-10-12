from __future__ import annotations

import re

import pytest

from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_structure import ElementPosition, derive_elements
from orchestwin.artifacts.generated_mockup_zones import (
    MAX_ZONE_LABEL_LENGTH,
    MIN_ZONE_ELEMENTS,
    ZONE_ATTRIBUTE,
    ZONE_CODE_PATTERN,
    ZONE_CODE_PREFIX,
    ZONE_KINDS,
    DerivedZone,
    derive_zones,
    zone_by_code,
    zone_positions,
)
from orchestwin.artifacts.generated_mockups import GeneratedMockup

from .test_generated_mockup_support import (
    BASE_SECOND,
    FIXTURES,
    LIGHT_TOKENS,
    build,
    fixture_mockup,
    fixture_tokens,
    with_first,
)

BOTTEGA = (
    '<header class="topbar"><a href="#SCR-001" aria-current="page">Bottega Vicina</a>'
    '<button type="button">Accedi</button><button type="button">Carrello</button></header>'
    '<form role="search" aria-label="Cerca nel quartiere">'
    '<input type="search" name="q" aria-label="Cosa cerchi oggi?">'
    '<button type="button">Cerca</button></form>'
    '<main data-req="REQ-001"><h1>Botteghe del quartiere</h1><div class="hero-row">'
    '<section class="panel"><h2>Forno Ravasi</h2><p>Pane cotto a legna ogni mattina.</p>'
    '<ul class="ptiles"><li>Pane di segale</li><li>Focaccia</li></ul></section>'
    '<section class="panel"><h2>Panificio Colombo</h2><p>Aperto fino alle 20.</p>'
    '<a href="#SCR-002">Vedi i prodotti</a><button type="button">Prenota</button></section>'
    "</div></main>"
)
SECOND_LIST = (
    "Verifica le restituzioni di venerdì mattina. Aggiorna il registro dopo ogni restituzione."
)
PAIR = "<p>Prima riga del riquadro.</p><p>Seconda riga del riquadro.</p>"


def elements(first: int, last: int) -> tuple[str, ...]:
    return tuple(f"ELM-{number:03d}" for number in range(first, last + 1))


def shape(zone: DerivedZone) -> tuple[object, ...]:
    return (zone.code, zone.kind, zone.label, zone.element_codes, zone.parent_code)


def added(snippet: str) -> list[DerivedZone]:
    known = {zone.path for zone in derive_zones(build()) if zone.screen_code == "SCR-001"}
    return [
        zone
        for zone in derive_zones(with_first(snippet))
        if zone.screen_code == "SCR-001" and zone.path not in known
    ]


def test_a_screen_shaped_like_the_bottega_has_its_zones_in_document_order() -> None:
    zones = derive_zones(build(BOTTEGA, BASE_SECOND))
    assert [shape(zone) for zone in zones] == [
        ("ZON-001", "header", "Bottega Vicina Accedi Carrello", elements(1, 3), None),
        ("ZON-002", "form", "Cerca nel quartiere", elements(4, 5), None),
        ("ZON-003", "main", "Botteghe del quartiere", elements(6, 14), None),
        ("ZON-004", "cards", "Forno Ravasi", elements(7, 14), "ZON-003"),
        ("ZON-005", "section", "Forno Ravasi", elements(7, 10), "ZON-004"),
        ("ZON-006", "list", "Pane di segale Focaccia", elements(9, 10), "ZON-005"),
        ("ZON-007", "section", "Panificio Colombo", elements(11, 14), "ZON-004"),
        ("ZON-008", "list", SECOND_LIST, elements(18, 19), None),
    ]
    assert [(zone.screen_code, zone.path, zone.node_name) for zone in zones] == [
        ("SCR-001", (0,), "header"),
        ("SCR-001", (1,), "form"),
        ("SCR-001", (2,), "main"),
        ("SCR-001", (2, 1), "div"),
        ("SCR-001", (2, 1, 0), "section"),
        ("SCR-001", (2, 1, 0, 2), "ul"),
        ("SCR-001", (2, 1, 1), "section"),
        ("SCR-002", (0, 3), "ul"),
    ]
    assert all(re.fullmatch(ZONE_CODE_PATTERN, zone.code) for zone in zones)
    assert all(zone.code.startswith(f"{ZONE_CODE_PREFIX}-") for zone in zones)


def test_the_root_section_of_a_screen_and_a_container_of_every_element_are_not_zones() -> None:
    plain = derive_zones(build(BOTTEGA, BASE_SECOND))
    wrapped = derive_zones(build(f'<section class="screen">{BOTTEGA}</section>', BASE_SECOND))
    assert [shape(zone) for zone in wrapped] == [shape(zone) for zone in plain]
    assert [zone.path for zone in wrapped if zone.screen_code == "SCR-001"] == [
        (0, *zone.path) for zone in plain if zone.screen_code == "SCR-001"
    ]
    assert [zone.node_name for zone in plain if zone.screen_code == "SCR-002"] == ["ul"]


def test_nested_containers_with_the_same_elements_keep_the_outermost() -> None:
    menu = (
        '<nav aria-label="Sezioni del registro"><ul>'
        '<li><a href="#SCR-002">Solleciti</a></li><li><a href="#SCR-001">Prestiti</a></li>'
        "</ul></nav>"
    )
    [zone] = added(menu)
    assert (zone.node_name, zone.kind, zone.label) == ("nav", "navigation", "Sezioni del registro")
    assert len(zone.element_codes) == 4


@pytest.mark.parametrize(
    ("snippet", "kind"),
    [
        (f'<nav aria-label="Menu">{PAIR}</nav>', "navigation"),
        (f"<header>{PAIR}</header>", "header"),
        (f"<footer>{PAIR}</footer>", "footer"),
        (f"<aside>{PAIR}</aside>", "aside"),
        (f"<section>{PAIR}</section>", "section"),
        (f"<form>{PAIR}</form>", "form"),
        ("<ul><li>Uno</li><li>Due</li></ul>", "list"),
        ("<ol><li>Uno</li><li>Due</li></ol>", "list"),
        ("<dl><dt>Sede</dt><dd>Centro</dd><dt>Orario</dt><dd>9-19</dd></dl>", "list"),
        (
            "<table><thead><tr><th>Giorno</th></tr></thead>"
            "<tbody><tr><td>Lunedì</td></tr></tbody></table>",
            "table",
        ),
        (f"<details><summary>Dettagli</summary>{PAIR}</details>", "details"),
        (f"<figure>{PAIR}</figure>", "figure"),
        (f"<fieldset>{PAIR}</fieldset>", "group"),
        (f'<div role="navigation">{PAIR}</div>', "navigation"),
        (f'<div role="banner">{PAIR}</div>', "header"),
        (f'<div role="main">{PAIR}</div>', "main"),
        (f'<div role="contentinfo">{PAIR}</div>', "footer"),
        (f'<div role="complementary">{PAIR}</div>', "aside"),
        (f'<div role="region">{PAIR}</div>', "section"),
        (f'<div role="form">{PAIR}</div>', "form"),
        (f'<div role="search">{PAIR}</div>', "form"),
        (f'<div role="list">{PAIR}</div>', "list"),
        (f'<div role="tablist">{PAIR}</div>', "group"),
        (f'<div role="group">{PAIR}</div>', "group"),
        (f'<div role="toolbar">{PAIR}</div>', "group"),
        (f'<div role="radiogroup">{PAIR}</div>', "group"),
        (
            "<div><article><h3>Uno</h3><p>Prima scheda.</p></article>"
            "<article><h3>Due</h3><p>Seconda scheda.</p></article></div>",
            "cards",
        ),
        ("<div><section><p>Uno.</p></section><section><p>Due.</p></section></div>", "cards"),
        ("<div><figure><p>Uno.</p></figure><figure><p>Due.</p></figure></div>", "cards"),
        (
            '<div role="list"><article><h3>Uno</h3></article><article><h3>Due</h3></article></div>',
            "list",
        ),
    ],
)
def test_the_kind_follows_the_tag_or_the_role(snippet: str, kind: str) -> None:
    [zone] = added(snippet)
    assert zone.kind == kind
    assert zone.kind in ZONE_KINDS


def test_the_kinds_are_the_keys_of_the_contract() -> None:
    assert ZONE_KINDS == (
        "navigation",
        "header",
        "main",
        "footer",
        "aside",
        "section",
        "form",
        "list",
        "table",
        "details",
        "figure",
        "group",
        "cards",
    )


@pytest.mark.parametrize(
    "snippet",
    [
        f"<section hidden>{PAIR}</section>",
        (
            "<article><h3>Scheda</h3><ul><li><a href='#SCR-002'>Uno</a></li>"
            "<li><a href='#SCR-002'>Due</a></li></ul></article>"
        ),
        "<section><h2>Un titolo soltanto</h2></section>",
        f"<div>{PAIR}</div>",
        f'<div role="presentation">{PAIR}</div>',
        "<div><article><h3>Una scheda sola</h3></article><p>Accanto.</p></div>",
        (
            '<fieldset><legend>Ritiro</legend><label><input type="radio" name="r"> Oggi</label>'
            '<label><input type="radio" name="r"> Domani</label></fieldset>'
        ),
    ],
)
def test_containers_outside_the_rules_are_not_zones(snippet: str) -> None:
    assert added(snippet) == []


@pytest.mark.parametrize(
    ("snippet", "label"),
    [
        (
            '<p id="offerte">Le offerte del giorno</p>'
            '<section aria-labelledby="offerte" aria-label="Etichetta">'
            f"<h2>Titolo interno</h2>{PAIR}</section>",
            "Le offerte del giorno",
        ),
        (
            f'<section aria-label="  Etichetta   della sezione "><h2>Titolo interno</h2>{PAIR}'
            "</section>",
            "Etichetta della sezione",
        ),
        (
            "<table><caption>Orari della settimana</caption>"
            "<thead><tr><th>Giorno</th></tr></thead><tbody><tr><td>Lunedì</td></tr></tbody></table>",
            "Orari della settimana",
        ),
        (
            '<fieldset><legend>Recapiti</legend><input name="email" aria-label="Email">'
            '<input name="tel" aria-label="Telefono"></fieldset>',
            "Recapiti",
        ),
        (f"<details><summary>Dettagli del ritiro</summary>{PAIR}</details>", "Dettagli del ritiro"),
        (f"<figure>{PAIR}<figcaption>Didascalia</figcaption></figure>", "Didascalia"),
        (f"<section>{PAIR}<div><h4>Titolo in fondo</h4></div></section>", "Titolo in fondo"),
        ("<ul><li>Uno</li><li>Due</li></ul>", "Uno Due"),
        ('<form><input name="primo"><input name="secondo"></form>', "form"),
    ],
)
def test_the_label_follows_the_order_of_the_contract(snippet: str, label: str) -> None:
    [zone] = added(snippet)
    assert zone.label == label


def test_a_long_label_is_cut_to_its_limit() -> None:
    words = " ".join(f"parola{number}" for number in range(40))
    [zone] = added(f"<ul><li>{words}</li><li>Due</li></ul>")
    assert zone.label == f"{words} Due"[:MAX_ZONE_LABEL_LENGTH].rstrip()
    assert len(zone.label) <= MAX_ZONE_LABEL_LENGTH


def test_codes_widen_beyond_nine_hundred_ninety_nine_zones() -> None:
    lists = "<ul><li>Uno</li><li>Due</li></ul>" * 250
    screens = [f'<main data-req="REQ-001"><h1>Schermata</h1>{lists}</main>' for _ in range(4)]
    zones = derive_zones(build(*screens[:2], extra=screens[2:]))
    assert [zone.code for zone in zones] == [f"ZON-{number:04d}" for number in range(1, 1001)]


@pytest.mark.parametrize("name", FIXTURES)
def test_every_zone_holds_the_elements_inside_it(name: str) -> None:
    mockup = fixture_mockup(name)
    derived = derive_elements(mockup)
    zones = derive_zones(mockup)
    assert zones
    for zone in zones:
        screen = [item for item in derived if item.screen_code == zone.screen_code]
        inside = tuple(
            item.code
            for item in screen
            if len(item.path) > len(zone.path) and item.path[: len(zone.path)] == zone.path
        )
        assert zone.element_codes == inside
        assert MIN_ZONE_ELEMENTS <= len(inside) < len(screen)
        assert zone.path not in {item.path for item in screen}
        parent = zone_by_code(zones, zone.parent_code) if zone.parent_code else None
        if parent is not None:
            assert set(zone.element_codes) < set(parent.element_codes)


def test_positions_and_lookup_by_code() -> None:
    mockup = build(BOTTEGA, BASE_SECOND)
    zones = derive_zones(mockup)
    assert zone_positions(mockup) == {
        zone.code: ElementPosition(zone.screen_code, zone.path) for zone in zones
    }
    assert zone_by_code(zones, "ZON-006") == zones[5]
    assert zone_by_code(zones, "ZON-099") is None


def subject(name: str) -> tuple[GeneratedMockup, dict[str, str]]:
    if name == "bottega":
        return build(BOTTEGA, BASE_SECOND), LIGHT_TOKENS
    return fixture_mockup(name), fixture_tokens(name)


def documents(mockup: GeneratedMockup, tokens: dict[str, str]) -> tuple[str, str]:
    plain = mockup_document(mockup, tokens=tokens, language="it")
    zoned = mockup_document(mockup, tokens=tokens, language="it", zones=True)
    return plain, zoned


@pytest.mark.parametrize("name", ["bottega", *FIXTURES])
def test_the_document_numbers_the_zones_only_when_asked(name: str) -> None:
    mockup, tokens = subject(name)
    plain, zoned = documents(mockup, tokens)
    zones = derive_zones(mockup)
    assert ZONE_ATTRIBUTE not in plain
    assert zoned.count(f'{ZONE_ATTRIBUTE}="') == len(zones)
    assert all(zoned.count(f'{ZONE_ATTRIBUTE}="{zone.code}"') == 1 for zone in zones)
    assert re.sub(rf' {ZONE_ATTRIBUTE}="ZON-\d+"', "", zoned) == plain


def test_a_zone_attribute_sits_with_the_other_attributes_of_its_node() -> None:
    _plain, zoned = documents(*subject("bottega"))
    assert '<header class="topbar" data-ot-zone="ZON-001">' in zoned
    assert '<form aria-label="Cerca nel quartiere" data-ot-zone="ZON-002" role="search">' in zoned
    assert '<ul class="ptiles" data-ot-zone="ZON-006"><li data-elm="ELM-009">' in zoned
