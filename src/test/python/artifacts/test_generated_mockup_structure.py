from __future__ import annotations

from dataclasses import replace
from uuid import uuid5

import pytest

from orchestwin.artifacts.design_evaluation import evaluation_document
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.generated_mockup_structure import (
    ElementPosition,
    derive_elements,
    derive_prototype,
    element_positions,
    nodes_text,
)
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockupError,
    MarkupElement,
    create_generated_mockup,
    generated_mockup_from_snapshot,
    parse_markup,
)
from orchestwin.artifacts.mockup_html import render_evaluation_document
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
)
from orchestwin.knowledge.diagrams import design_diagrams
from orchestwin.knowledge.tables import design_tables

from . import design_fixtures
from .test_generated_mockup_support import (
    BASE_CODES,
    BASE_FIRST,
    DASHBOARD,
    FIXTURES,
    GUIDED_FORM,
    build,
    fixture_codes,
    fixture_data,
    fixture_mockup,
    fixture_tokens,
    requirement_ids,
    with_first,
)

HEADING = PrototypeElementKind.HEADING
TEXT = PrototypeElementKind.TEXT
TEXT_INPUT = PrototypeElementKind.TEXT_INPUT
SELECT = PrototypeElementKind.SELECT
BUTTON = PrototypeElementKind.BUTTON
LINK = PrototypeElementKind.LINK
LIST = PrototypeElementKind.LIST
CARD = PrototypeElementKind.CARD
STATUS = PrototypeElementKind.STATUS


def prototype_of(mockup, codes=BASE_CODES):
    return derive_prototype(mockup, requirement_ids_by_code=requirement_ids(codes))


def kinds(prototype, code: str) -> list[PrototypeElementKind]:
    screen = next(item for item in prototype.screens if item.code == code)
    return [element.kind for element in screen.elements]


def element(prototype, code: str):
    return next(
        item for screen in prototype.screens for item in screen.elements if item.code == code
    )


def transitions(prototype) -> list[tuple[str, str, str, str]]:
    screens = {screen.id: screen.code for screen in prototype.screens}
    elements = {item.id: item.code for screen in prototype.screens for item in screen.elements}
    return [
        (
            transition.code,
            screens[transition.source_screen_id],
            elements[transition.trigger_element_id],
            screens[transition.target_screen_id],
            transition.outcome,
        )
        for transition in prototype.transitions
    ]


def test_baseline_prototype_has_the_expected_elements_and_transitions() -> None:
    mockup = build()
    prototype = prototype_of(mockup)
    assert prototype.code == "PRT-001"
    assert prototype.title == mockup.title
    assert prototype.design_alternative_id == mockup.design_alternative_id
    assert prototype.supported_viewports == (
        PrototypeViewport.DESKTOP,
        PrototypeViewport.MOBILE,
        PrototypeViewport.TABLET,
    )
    entry = prototype.screens[0]
    assert prototype.entry_screen_id == entry.id
    assert entry.code == "SCR-001"
    assert entry.state is PrototypeScreenState.DEFAULT
    assert kinds(prototype, "SCR-001") == [HEADING, TEXT, SELECT, TEXT, LIST, LIST, LIST, LINK]
    assert kinds(prototype, "SCR-002") == [HEADING, STATUS, HEADING, LIST, LIST, TEXT, LINK]
    select = element(prototype, "ELM-003")
    assert select.content == "Stato del prestito"
    assert select.accessible_name == "Stato del prestito"
    assert select.options == ("Tutti", "In ritardo")
    assert select.field_name == "stato"
    assert element(prototype, "ELM-004").content == "Lettore · Titolo · Scadenza"
    assert element(prototype, "ELM-005").content == "Anna Riva · Le città invisibili · 3 ottobre"
    assert transitions(prototype) == [
        ("TRN-001", "SCR-001", "ELM-008", "SCR-002", "Invia promemoria"),
        ("TRN-002", "SCR-002", "ELM-015", "SCR-001", "Torna al registro"),
    ]
    ids = requirement_ids(BASE_CODES)
    assert entry.requirement_ids == (ids["REQ-001"],)
    assert all(item.requirement_ids == (ids["REQ-001"],) for item in entry.elements)


def test_identifiers_are_name_based_uuids_of_the_content_hash_and_code() -> None:
    mockup = build()
    prototype = prototype_of(mockup)
    namespace = mockup.design_alternative_id
    stem = mockup.content_hash
    assert prototype.id == uuid5(namespace, f"{stem}:PRT-001")
    assert prototype.screens[1].id == uuid5(namespace, f"{stem}:SCR-002")
    assert element(prototype, "ELM-003").id == uuid5(namespace, f"{stem}:ELM-003")
    assert prototype.transitions[0].id == uuid5(namespace, f"{stem}:TRN-001")
    assert all(item.id.version == 5 for screen in prototype.screens for item in screen.elements)


GUIDED_KINDS = {
    "SCR-001": [
        TEXT,
        TEXT,
        LIST,
        LIST,
        LIST,
        TEXT,
        HEADING,
        TEXT,
        HEADING,
        TEXT_INPUT,
        TEXT_INPUT,
        TEXT_INPUT,
        TEXT_INPUT,
        TEXT,
        HEADING,
        TEXT_INPUT,
        TEXT_INPUT,
        LINK,
    ],
    "SCR-002": [
        TEXT,
        TEXT,
        LIST,
        LIST,
        LIST,
        TEXT,
        HEADING,
        TEXT,
        SELECT,
        TEXT,
        SELECT,
        SELECT,
        TEXT,
        LINK,
        LINK,
    ],
    "SCR-003": [
        TEXT,
        TEXT,
        LIST,
        LIST,
        LIST,
        TEXT,
        HEADING,
        TEXT,
        HEADING,
        LINK,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        HEADING,
        LINK,
        TEXT,
        TEXT,
        TEXT,
        SELECT,
        LINK,
        LINK,
    ],
    "SCR-004": [TEXT, TEXT, HEADING, STATUS, HEADING, LIST, LIST, LIST, LINK],
}


def test_guided_form_fixture_derives_every_element_in_document_order() -> None:
    prototype = prototype_of(fixture_mockup(GUIDED_FORM), fixture_codes(GUIDED_FORM))
    for code, expected in GUIDED_KINDS.items():
        assert kinds(prototype, code) == expected, code
    codes = [item.code for screen in prototype.screens for item in screen.elements]
    assert codes == [f"ELM-{index:03d}" for index in range(1, 65)]
    name = element(prototype, "ELM-010")
    assert (name.content, name.accessible_name, name.field_name, name.required) == (
        "Nome",
        "Nome",
        "nome",
        True,
    )
    phone = element(prototype, "ELM-017")
    assert (phone.content, phone.field_name, phone.required) == ("Cellulare", "cellulare", False)
    card = element(prototype, "ELM-027")
    assert card.content == "Tipo di tessera"
    assert card.field_name == "tessera"
    assert card.options == (
        "Ordinaria fino a 5 prestiti per 30 giorni, gratuita",
        "Studio 8 prestiti e sala studio aperta dalle 8 alle 23",
        "Famiglia una tessera per 4 persone con prestiti condivisi",
    )
    alerts = element(prototype, "ELM-030")
    assert alerts.field_name == "avvisi"
    assert alerts.options[1] == "Quando una prenotazione è pronta al banco"
    ids = requirement_ids(fixture_codes(GUIDED_FORM))
    assert alerts.requirement_ids == (ids["REQ-004"],)
    assert element(prototype, "ELM-044").content == "Nome e cognome: Chiara Esposito"
    assert element(prototype, "ELM-047").content == (
        "Contatti: chiara.esposito@esempio.it · 333 418 2291"
    )
    privacy = element(prototype, "ELM-053")
    assert privacy.kind is SELECT
    assert privacy.options == ("Ho letto l'informativa sul trattamento dei dati personali",)
    assert (privacy.field_name, privacy.required) == ("privacy", True)
    assert element(prototype, "ELM-003").content == "1 Dati personali"
    assert element(prototype, "ELM-059").content.startswith("Iscrizione completata.")
    assert element(prototype, "ELM-001").requirement_ids == ()
    assert transitions(prototype) == [
        ("TRN-001", "SCR-001", "ELM-018", "SCR-002", "Continua"),
        ("TRN-002", "SCR-002", "ELM-032", "SCR-001", "Indietro"),
        ("TRN-003", "SCR-002", "ELM-033", "SCR-003", "Continua"),
        ("TRN-004", "SCR-003", "ELM-043", "SCR-001", "Modifica i dati personali"),
        ("TRN-005", "SCR-003", "ELM-049", "SCR-002", "Modifica tessera e avvisi"),
        ("TRN-006", "SCR-003", "ELM-054", "SCR-002", "Indietro"),
        ("TRN-007", "SCR-003", "ELM-055", "SCR-004", "Conferma l'iscrizione"),
        ("TRN-008", "SCR-004", "ELM-064", "SCR-001", "Iscrivi un'altra persona"),
    ]
    states = [screen.state for screen in prototype.screens]
    assert states[-1] is PrototypeScreenState.SUCCESS


def test_dashboard_fixture_derives_cards_rows_groups_and_statuses() -> None:
    prototype = prototype_of(fixture_mockup(DASHBOARD), fixture_codes(DASHBOARD))
    assert [len(screen.elements) for screen in prototype.screens] == [35, 28, 21]
    first = kinds(prototype, "SCR-001")
    assert first.count(CARD) == 4
    assert first.count(LIST) == 9
    assert first.count(LINK) == 9
    assert first.count(BUTTON) == 1
    assert element(prototype, "ELM-013").content == (
        "Prestiti attivi 128 12 in più della settimana scorsa"
    )
    assert element(prototype, "ELM-017").kind is HEADING
    search = element(prototype, "ELM-018")
    assert (search.kind, search.content, search.field_name) == (
        TEXT_INPUT,
        "Lettore o titolo",
        "ricerca",
    )
    assert element(prototype, "ELM-019").options == (
        "Tutti gli stati",
        "In ritardo",
        "In scadenza",
        "Regolari",
    )
    assert element(prototype, "ELM-020").content == (
        "Prestiti ordinati per giorni di ritardo, i più urgenti per primi"
    )
    header = element(prototype, "ELM-021")
    assert (header.kind, header.content) == (TEXT, "Lettore · Volume · Scadenza · Stato · Azione")
    row = element(prototype, "ELM-022")
    assert (row.kind, row.content) == (
        LIST,
        "Giulia Ferri tessera 0412 · Il sistema periodico · 14 set · 15 giorni di ritardo · "
        "Sollecita",
    )
    ids = requirement_ids(fixture_codes(DASHBOARD))
    assert row.requirement_ids == (ids["REQ-002"],)
    assert element(prototype, "ELM-023").requirement_ids == (ids["REQ-003"],)
    assert (element(prototype, "ELM-033").kind, element(prototype, "ELM-033").content) == (
        BUTTON,
        "Proroga",
    )
    assert element(prototype, "ELM-034").content == (
        "Mostrati 6 dei 128 prestiti attivi · aggiornato alle 10:42"
    )
    assert element(prototype, "ELM-050").content == "Lettore: Giulia Ferri, tessera 0412"
    assert element(prototype, "ELM-054").kind is STATUS
    channels = element(prototype, "ELM-059")
    assert (channels.kind, channels.field_name, channels.options) == (
        SELECT,
        "canali",
        ("Email a g.ferri@esempio.it", "SMS al 347 551 2290"),
    )
    body = element(prototype, "ELM-058")
    assert (body.kind, body.content, body.field_name, body.required) == (
        TEXT_INPUT,
        "Testo del messaggio",
        "testo",
        True,
    )
    assert transitions(prototype) == [
        ("TRN-001", "SCR-001", "ELM-005", "SCR-002", "Solleciti"),
        ("TRN-002", "SCR-001", "ELM-007", "SCR-003", "Esiti degli invii"),
        ("TRN-003", "SCR-001", "ELM-012", "SCR-002", "Sollecita i 9 ritardi"),
        ("TRN-004", "SCR-001", "ELM-023", "SCR-002", "Sollecita"),
        ("TRN-005", "SCR-001", "ELM-025", "SCR-002", "Sollecita"),
        ("TRN-006", "SCR-001", "ELM-027", "SCR-002", "Sollecita"),
        ("TRN-007", "SCR-001", "ELM-029", "SCR-002", "Avvisa"),
        ("TRN-008", "SCR-001", "ELM-031", "SCR-002", "Avvisa"),
        ("TRN-009", "SCR-002", "ELM-038", "SCR-001", "Prestiti"),
        ("TRN-010", "SCR-002", "ELM-042", "SCR-003", "Esiti degli invii"),
        ("TRN-011", "SCR-002", "ELM-045", "SCR-001", "Prestiti in corso"),
        ("TRN-012", "SCR-002", "ELM-061", "SCR-003", "Invia il sollecito"),
        ("TRN-013", "SCR-002", "ELM-062", "SCR-001", "Annulla"),
        ("TRN-014", "SCR-003", "ELM-066", "SCR-001", "Prestiti"),
        ("TRN-015", "SCR-003", "ELM-068", "SCR-002", "Solleciti"),
        ("TRN-016", "SCR-003", "ELM-082", "SCR-001", "Torna ai prestiti in corso"),
        ("TRN-017", "SCR-003", "ELM-083", "SCR-002", "Invia un altro sollecito"),
    ]
    assert element(prototype, "ELM-003").kind is LINK


@pytest.mark.parametrize("name", FIXTURES)
def test_derivation_is_deterministic_and_survives_a_snapshot_round_trip(name: str) -> None:
    mockup = fixture_mockup(name)
    codes = fixture_codes(name)
    first = prototype_of(mockup, codes)
    assert prototype_of(mockup, codes) == first
    restored = generated_mockup_from_snapshot(
        mockup.to_snapshot(), token_names=frozenset(fixture_tokens(name))
    )
    again = prototype_of(restored, codes)
    assert again == first
    assert again.content_hash == first.content_hash
    assert again.to_snapshot() == first.to_snapshot()


@pytest.mark.parametrize("name", FIXTURES)
def test_element_positions_point_at_the_nodes_that_carry_the_codes(name: str) -> None:
    mockup = fixture_mockup(name)
    positions = element_positions(mockup)
    derived = derive_elements(mockup)
    assert list(positions) == [item.code for item in derived]
    codes = frozenset(screen.code for screen in mockup.screens)
    trees = {
        screen.code: parse_markup(screen.markup, screen_code=screen.code, screen_codes=codes)
        for screen in mockup.screens
    }
    expected_names = {
        HEADING: {"h1", "h2", "h3", "h4"},
        TEXT: {"p", "blockquote", "figcaption", "summary", "legend", "caption", "dt", "dd", "tr"},
        TEXT_INPUT: {"input", "textarea"},
        SELECT: {"select", "fieldset", "input"},
        BUTTON: {"button", "a"},
        LINK: {"a"},
        LIST: {"li", "tr"},
        CARD: {"article"},
        STATUS: {"output", "meter", "progress", "p", "div"},
    }
    for item in derived:
        position = positions[item.code]
        assert isinstance(position, ElementPosition)
        assert position.screen_code == item.screen_code
        node = locate(trees[position.screen_code], position.path)
        assert node.name in expected_names[item.kind], (item.code, node.name)


def locate(nodes, path):
    current = None
    children = nodes
    for index in path:
        current = [node for node in children if isinstance(node, MarkupElement)][index]
        children = current.children
    return current


@pytest.mark.parametrize("name", FIXTURES)
def test_derived_prototype_feeds_the_design_package_knowledge_and_twin_review(name: str) -> None:
    data = fixture_data(name)
    mockup = create_generated_mockup(
        design_alternative_id=design_fixtures.ALTERNATIVE_ONE_ID,
        title=data["title"],
        styles=data["styles"],
        screens=data["screens"],
        token_names=frozenset(fixture_tokens(name)),
    )
    prototype = derive_prototype(
        mockup,
        requirement_ids_by_code={
            code: design_fixtures.REQUIREMENT_ID for code in fixture_codes(name)
        },
    )
    package = replace(design_fixtures.design_package(), prototype=prototype)
    snapshot = package.to_snapshot()
    assert design_package_from_snapshot(snapshot) == package
    specification = design_fixtures.requirements_version().specification.to_snapshot()
    tables = design_tables(snapshot, specification)
    assert any("screens" in key for key in tables)
    assert any("transitions" in key for key in tables)
    diagrams = design_diagrams(snapshot, specification, locale="it")
    assert any(diagram.key == "design/screen-map" for diagram in diagrams)
    document = render_evaluation_document(snapshot, language="it")
    assert document.count("<section") == len(mockup.screens)
    version = design_fixtures.design_version(package=package)
    assert len(evaluation_document(version, language="it").content) <= 8 * 1024


def test_derivation_fails_when_the_review_would_fail() -> None:
    unlabelled = with_first('<input name="q" type="search">')
    with pytest.raises(ValueError, match="accessible name"):
        prototype_of(unlabelled)
    untraced = BASE_FIRST.replace('<main data-req="REQ-001">', "<main>")
    with pytest.raises(ValueError, match="traceability"):
        prototype_of(build(untraced))


def test_requirement_codes_without_an_identifier_are_rejected() -> None:
    with pytest.raises(GeneratedMockupError) as error:
        derive_prototype(build(), requirement_ids_by_code=requirement_ids(["REQ-001"]))
    assert error.value.code == "REQUIREMENT_MAPPING"
    assert "REQ-002" in error.value.detail


def test_codes_keep_document_order_beyond_nine_hundred_ninety_nine_elements() -> None:
    first = (
        '<main data-req="REQ-001"><h1>Uno</h1>'
        + "<p>Riga del registro</p>" * 600
        + '<a href="#SCR-002">Avanti</a></main>'
    )
    second = (
        '<main data-req="REQ-002"><h1>Due</h1>'
        + "<p>Altra riga</p>" * 400
        + '<a href="#SCR-001">Indietro</a></main>'
    )
    prototype = prototype_of(build(first, second))
    codes = [item.code for screen in prototype.screens for item in screen.elements]
    assert codes == [f"ELM-{index:04d}" for index in range(1, 1005)]
    assert [item.code for item in prototype.transitions] == ["TRN-001", "TRN-002"]
    assert element(prototype, "ELM-0602").kind is LINK


def test_elements_without_text_are_skipped_but_controls_take_their_name() -> None:
    mockup = with_first(
        "<p> </p><h2></h2><ul><li></li><li>Voce</li></ul>"
        '<button type="button" aria-label="Chiudi il pannello"><svg viewBox="0 0 1 1" '
        'aria-hidden="true"><path d="M0 0"></path></svg></button>'
        '<a href="#SCR-002" role="button">Apri</a><output>12</output>'
        '<meter aria-label="Occupazione della sala" value="0.5"></meter>'
    )
    prototype = prototype_of(mockup)
    added = [
        (item.kind, item.content, item.accessible_name)
        for item in prototype.screens[0].elements[8:]
    ]
    assert added == [
        (LIST, "Voce", None),
        (BUTTON, "Chiudi il pannello", "Chiudi il pannello"),
        (BUTTON, "Apri", "Apri"),
        (STATUS, "12", None),
        (STATUS, "Occupazione della sala", "Occupazione della sala"),
    ]
    assert transitions(prototype)[1][2] == "ELM-011"


def test_articles_keep_only_their_interactive_descendants() -> None:
    mockup = with_first(
        "<article><h2>Novità</h2><p>Tre titoli arrivati oggi.</p><ul><li>Uno</li><li>Due</li>"
        '</ul><a href="#SCR-002">Prenota</a><p role="status">Disponibile</p></article>'
    )
    prototype = prototype_of(mockup)
    added = [(item.kind, item.content) for item in prototype.screens[0].elements[8:]]
    assert added == [
        (CARD, "Novità Tre titoli arrivati oggi. Uno Due Prenota Disponibile"),
        (LINK, "Prenota"),
    ]


def test_checkboxes_and_radios_become_selects_with_their_labels() -> None:
    mockup = with_first(
        '<fieldset><legend>Formato</legend><label><input type="radio" name="formato" '
        'value="a" required> Cartaceo</label><label><input type="radio" name="formato" '
        'value="b"> Digitale</label><label><input type="radio" name="formato" value="c">'
        " Digitale</label></fieldset>"
        '<label><input type="checkbox" name="avviso"> Avvisami</label>'
        '<fieldset aria-label="Lingue"><input type="checkbox" id="l1" name="it">'
        '<label for="l1">Italiano</label><input type="checkbox" id="l2" name="en">'
        '<label for="l2">Inglese</label></fieldset>'
    )
    prototype = prototype_of(mockup)
    added = [
        (item.kind, item.content, item.field_name, item.required, item.options)
        for item in prototype.screens[0].elements[8:]
    ]
    assert added == [
        (SELECT, "Formato", "formato", True, ("Cartaceo", "Digitale")),
        (TEXT, "Formato", None, False, ()),
        (SELECT, "Avvisami", "avviso", False, ("Avvisami",)),
        (SELECT, "Lingue", "it", False, ("Italiano", "Inglese")),
    ]


def test_fields_without_name_or_identifier_take_the_element_code_as_field_name() -> None:
    mockup = with_first('<input aria-label="Codice tessera">')
    field = prototype_of(mockup).screens[0].elements[8]
    assert (field.kind, field.field_name) == (TEXT_INPUT, "elm-009")


def text_of(markup: str) -> str:
    return nodes_text(
        parse_markup(markup, screen_code="SCR-001", screen_codes=("SCR-001", "SCR-002"))
    )


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ("<p><span>Registro</span><span>127</span></p>", "Registro 127"),
        (
            '<div class="tile"><span>Prestiti attivi</span><strong>128</strong></div>',
            "Prestiti attivi 128",
        ),
        ("<p><b>Scade</b><i>oggi</i><em>alle 18</em></p>", "Scade oggi alle 18"),
        (
            "<p>Il prestito dell'<em>utente</em> scade oggi</p>",
            "Il prestito dell'utente scade oggi",
        ),
        ("<p>Hai <strong>3</strong> prestiti</p>", "Hai 3 prestiti"),
        ("<p><em>Sede centrale</em>, via Roma</p>", "Sede centrale, via Roma"),
        ("<div><div>Totale</div><div>42</div></div>", "Totale 42"),
        ("<div><p>Totale</p>42 volumi</div>", "Totale 42 volumi"),
        ("<div>Totale<p>42 volumi</p></div>", "Totale 42 volumi"),
        ("<ul><li>Uno</li><li>Due</li></ul>", "Uno Due"),
        ("<dl><dt>Sede</dt><dd>Centrale</dd></dl>", "Sede Centrale"),
        (
            "<table><tbody><tr><td>Anna Riva</td><td>3 ottobre</td></tr></tbody></table>",
            "Anna Riva 3 ottobre",
        ),
        ("<section><h2>Novità</h2><article>Tre titoli</article></section>", "Novità Tre titoli"),
        ("<p>Via Roma 1<br>Milano</p>", "Via Roma 1 Milano"),
        ("<p><span>Via Roma 1</span><br><span>Milano</span></p>", "Via Roma 1 Milano"),
        ("<p>  Uno \n <span>due</span><span> tre </span>  </p>", "Uno due tre"),
        ("<p><span>Uno</span><span hidden>nascosto</span><span>due</span></p>", "Uno due"),
        (
            '<button type="button"><svg aria-hidden="true" viewBox="0 0 1 1">'
            '<path d="M0 0"></path></svg>Salva</button>',
            "Salva",
        ),
    ],
)
def test_collected_text_separates_adjacent_elements_and_keeps_inline_words_whole(
    markup: str, expected: str
) -> None:
    assert text_of(markup) == expected


def test_every_derived_text_separates_adjacent_elements() -> None:
    mockup = with_first(
        "<ul><li><span>Registro</span><span>127</span></li>"
        "<li>Hai <strong>3</strong> prestiti</li></ul>"
        "<h3><span>Prestiti</span><span>in ritardo</span></h3>"
        "<article><h2>Prestiti attivi</h2><p><strong>128</strong><small>12 in più</small></p>"
        "</article>"
        "<dl><dt><span>Sede</span><small>principale</small></dt>"
        "<dd><strong>Via Roma</strong><span>1</span></dd></dl>"
        '<label for="isbn"><span>Codice</span><abbr>ISBN</abbr></label>'
        '<input id="isbn" name="isbn">'
        '<span id="cerca-etichetta"><b>Cerca</b><i>titolo</i></span>'
        '<input name="titolo" aria-labelledby="cerca-etichetta">'
        "<fieldset><legend><span>Formato</span><em>preferito</em></legend>"
        '<label><input type="radio" name="formato" value="a"><span>Cartaceo</span>'
        "<small>in sede</small></label>"
        '<label><input type="radio" name="formato" value="b"><span>Digitale</span>'
        "<small>da casa</small></label></fieldset>"
        '<table><thead><tr><th scope="col"><span>Lettore</span><small>tessera</small></th>'
        '<th scope="col">Scadenza</th></tr></thead>'
        "<tbody><tr><td><strong>Giulia Ferri</strong><small>0412</small></td>"
        "<td>14<br>settembre</td></tr></tbody></table>"
        '<a href="#SCR-002"><span>Solleciti</span><span>9</span></a>'
        '<p role="status"><span>Invio</span><strong>completato</strong></p>'
    )
    prototype = prototype_of(mockup)
    added = [
        (item.kind, item.content, item.accessible_name, item.options)
        for item in prototype.screens[0].elements[8:]
    ]
    assert added == [
        (LIST, "Registro 127", None, ()),
        (LIST, "Hai 3 prestiti", None, ()),
        (HEADING, "Prestiti in ritardo", None, ()),
        (CARD, "Prestiti attivi 128 12 in più", None, ()),
        (TEXT, "Sede principale: Via Roma 1", None, ()),
        (TEXT_INPUT, "Codice ISBN", "Codice ISBN", ()),
        (TEXT_INPUT, "Cerca titolo", "Cerca titolo", ()),
        (
            SELECT,
            "Formato preferito",
            "Formato preferito",
            ("Cartaceo in sede", "Digitale da casa"),
        ),
        (TEXT, "Formato preferito", None, ()),
        (TEXT, "Lettore tessera · Scadenza", None, ()),
        (LIST, "Giulia Ferri 0412 · 14 settembre", None, ()),
        (LINK, "Solleciti 9", "Solleciti 9", ()),
        (STATUS, "Invio completato", None, ()),
    ]
    link = prototype.screens[0].elements[-2]
    assert [
        item.outcome for item in prototype.transitions if item.trigger_element_id == link.id
    ] == ["Solleciti 9"]
