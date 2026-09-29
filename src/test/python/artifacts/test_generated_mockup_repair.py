from __future__ import annotations

from html.parser import HTMLParser
from random import Random

import pytest

from orchestwin.artifacts.generated_mockup_document import mockup_document
from orchestwin.artifacts.generated_mockup_repair import (
    ATTRIBUTE_REMOVED,
    ELEMENT_REMOVED,
    ELEMENT_UNWRAPPED,
    LINK_REMOVED,
    MAX_NOTE_NAME_LENGTH,
    REPAIR_NOTE_CODES,
    REQUIREMENT_CODE_REMOVED,
    REQUIREMENT_INHERITED,
    MockupRepair,
    RepairNote,
    repair_generated_mockup,
)
from orchestwin.artifacts.generated_mockup_review import (
    MockupIssueSeverity,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockups import (
    ALLOWED_ELEMENTS,
    GeneratedMockup,
    GeneratedMockupError,
    create_generated_mockup,
    serialize_markup,
)

from .test_generated_mockup_document import HOSTILE_MARKUP, assert_safe
from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_FIRST,
    BASE_SECOND,
    BASE_STYLES,
    FIXTURES,
    HTML_COMMENT_CLOSE,
    HTML_COMMENT_OPEN,
    LIGHT_TOKENS,
    TOKEN_NAMES,
    fixture_data,
    fixture_tokens,
    screen_payloads,
)
from .test_generated_mockups import REJECTED_ELEMENTS, TreeFactory, merge

CODES = frozenset({"REQ-001", "REQ-002"})
RANDOM_CODES = frozenset({"REQ-001", "REQ-002", "AC-010", "US-003"})
PREFIX = BASE_FIRST[: -len("</main>")]
ICON = '<svg aria-hidden="true" viewBox="0 0 1 1"><path d="M0 0"></path></svg>'
EXTRA_HOSTILE = [
    '<p onclick="alert(1)" style="width:expression(1)">a</p>',
    '<a href="javascript:alert(1)" onmouseover="x">b</a>',
    "<div><script><script>alert(1)</script></script></div>",
    "<svg><script>alert(1)</script></svg>",
    '<svg><a href="javascript:x"><text>y</text></a></svg>',
    '<object><embed src="x"><iframe srcdoc="<script>x</script>"></iframe></object>',
    '<p title="a\x00b">c</p>',
    "<p>\x00</p>",
    '<p class="a\'b">c</p>',
    "<p class='unterminated>c</p>",
    '<p aria-label="' + "x" * 5000 + '">c</p>',
    "<img src=x onerror=alert(1)//>",
    "<math><mtext><img src=x></mtext></math>",
    "<template><script>x</script></template>",
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>"></p></noscript>',
    "<style><img src=x onerror=alert(1)></style>",
    "<iframe><img src=x onerror=alert(1)></iframe>",
    '<form action="javascript:x" aria-label="f"><button formaction="javascript:y">z</button></form>',
    '<input name="q" aria-label="q" type="image" src="x">',
    '<svg><use xlink:href="data:image/svg+xml,&lt;svg onload=alert(1)&gt;"></use></svg>',
    '<a href="#SCR-002" style="background:url(https://example.org/x.png)">vai</a>',
    '<p STYLE="x" OnClick="y" SrC="z">maiuscole</p>',
    '<div data-req="REQ-099" hidden="false">nascosto</div>',
]


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)


def repair(
    first: str = BASE_FIRST,
    second: str = BASE_SECOND,
    *,
    extra: tuple[str, ...] = (),
    styles: str = BASE_STYLES,
    codes: frozenset[str] = CODES,
    declared: tuple[str, ...] = (),
) -> MockupRepair:
    markups = (first, second, *extra)
    return repair_generated_mockup(
        styles=styles,
        screens=[(f"SCR-{index:03d}", markup) for index, markup in enumerate(markups, start=1)],
        requirement_codes=codes,
        token_names=TOKEN_NAMES,
        declared_codes=declared,
    )


def with_snippet(snippet: str, **options: object) -> MockupRepair:
    return repair(BASE_FIRST.replace("</main>", snippet + "</main>"), **options)


def inner(result: MockupRepair) -> str:
    markup = result.markups[0]
    assert markup.startswith(PREFIX) and markup.endswith("</main>"), markup
    return markup[len(PREFIX) : -len("</main>")]


def notes(result: MockupRepair) -> list[tuple[str, str | None, str]]:
    return [(note.code, note.screen_code, note.detail) for note in result.notes]


def built(result: MockupRepair) -> GeneratedMockup:
    return create_generated_mockup(
        design_alternative_id=ALTERNATIVE_ID,
        title="Registro dei prestiti",
        styles=result.styles,
        screens=screen_payloads(result.markups),
        token_names=TOKEN_NAMES,
    )


def again(result: MockupRepair, **options: object) -> MockupRepair:
    first, second, *extra = result.markups
    return repair(first, second, extra=tuple(extra), styles=result.styles, **options)


def test_a_valid_answer_comes_back_byte_for_byte_and_without_notes() -> None:
    result = repair()
    assert result.markups == (BASE_FIRST, BASE_SECOND)
    assert result.styles is BASE_STYLES
    assert result.notes == ()


@pytest.mark.parametrize(
    "variant",
    [
        lambda markup: markup.replace('"', "'"),
        lambda markup: markup.replace(
            "<h1>", HTML_COMMENT_OPEN + " titolo " + HTML_COMMENT_CLOSE + "<h1>"
        ),
        lambda markup: markup.replace("<main ", "<MAIN ").replace("</main>", "</MAIN>"),
        lambda markup: markup.replace("<p>", "<p\n>").replace("\n", "\r\n"),
    ],
    ids=["single-quotes", "comment", "upper-case", "line-breaks"],
)
def test_valid_answers_written_in_another_accepted_form_come_back_unchanged(variant) -> None:
    first, second = variant(BASE_FIRST), variant(BASE_SECOND)
    result = repair(first, second)
    assert result.markups == (first, second)
    assert result.notes == ()
    assert built(result) == built(repair())


@pytest.mark.parametrize("name", FIXTURES)
def test_the_fixture_answers_come_back_byte_for_byte(name: str) -> None:
    data = fixture_data(name)
    screens = data["screens"]
    assert isinstance(screens, list)
    result = repair_generated_mockup(
        styles=str(data["styles"]),
        screens=[(screen["code"], screen["markup"]) for screen in screens],
        requirement_codes=frozenset(data["requirement_codes"]),
        token_names=frozenset(fixture_tokens(name)),
    )
    assert result.markups == tuple(screen["markup"] for screen in screens)
    assert result.styles == data["styles"]
    assert result.notes == ()


@pytest.mark.parametrize("seed", range(40))
def test_random_valid_trees_come_back_byte_for_byte(seed: int) -> None:
    markup = (
        '<main data-req="REQ-001">' + serialize_markup(merge(TreeFactory(seed).flow(4))) + "</main>"
    )
    result = repair(markup, codes=RANDOM_CODES)
    assert result.markups[0] == markup
    assert result.notes == ()


MESSY = [
    BASE_FIRST.replace("</main>", '<img src="x"><p style="color:red" onclick="x">Nota</p></main>'),
    BASE_FIRST.replace('data-req="REQ-001"', 'data-req="REQ-099"'),
    BASE_FIRST.replace("<h1>", "<hgroup><h1>").replace("</h1>", "</h1></hgroup>"),
    BASE_FIRST.replace("</main>", '<a href="https://example.org">Esci</a></main>'),
    BASE_FIRST.replace("</main>", "<section><p>Fine</p></main>"),
    BASE_FIRST.replace("</main>", "<p>Q&A e a < b<span class='dot'/></p></main>"),
    BASE_FIRST.replace(' data-req="REQ-001"', ""),
]


@pytest.mark.parametrize("markup", MESSY)
def test_the_repair_of_a_repaired_answer_changes_nothing(markup: str) -> None:
    first = repair(markup, BASE_SECOND.replace(' data-req="REQ-002"', ""), declared=("REQ-002",))
    second = again(first, declared=("REQ-002",))
    assert second.markups == first.markups
    assert second.styles == first.styles
    assert second.notes == ()


@pytest.mark.parametrize(
    ("snippet", "name", "remaining"),
    [
        ("<script>alert(1)</script>", "script", ""),
        ("<SCRIPT>alert(1)</SCRIPT>", "script", ""),
        ("<style>p{color:red}</style>", "style", ""),
        ('<link rel="stylesheet" href="x.css">', "link", ""),
        ('<meta http-equiv="refresh" content="0">', "meta", ""),
        ('<base href="https://example.org/">', "base", ""),
        ("<title>x</title>", "title", ""),
        ('<iframe src="https://example.org"><p>x</p></iframe>', "iframe", ""),
        ('<frame src="x">', "frame", ""),
        ('<object data="x"><p>riserva</p></object>', "object", ""),
        ('<embed src="x">', "embed", ""),
        ('<img src="x" alt="Copertina">', "img", ""),
        ('<picture><source srcset="x"><img src="x"></picture>', "picture", ""),
        ('<video src="x"><track src="y"></video>', "video", ""),
        ("<audio></audio>", "audio", ""),
        ("<canvas></canvas>", "canvas", ""),
        ("<template><p>x</p></template>", "template", ""),
        ("<noscript><p>x</p></noscript>", "noscript", ""),
        ("<slot></slot>", "slot", ""),
        ('<map name="m"><area href="x"></map>', "map", ""),
        ("<dialog open><p>x</p></dialog>", "dialog", ""),
        ('<datalist id="d"><option>Uno</option></datalist>', "datalist", ""),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><use href="#x"></use></svg>',
            "use",
            '<svg aria-hidden="true" viewBox="0 0 1 1"></svg>',
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><foreignObject><p>x</p></foreignObject>'
            '<path d="M0 0"></path></svg>',
            "foreignobject",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><text>x</text><path d="M0 0"></path></svg>',
            "text",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><image href="x"></image><path d="M0 0"></path></svg>',
            "image",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><animate attributeName="x"></animate><path d="M0 0"></path></svg>',
            "animate",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><title>Icona</title><path d="M0 0"></path></svg>',
            "title",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><span>x</span><path d="M0 0"></path></svg>',
            "span",
            ICON,
        ),
    ],
)
def test_elements_that_load_or_run_something_are_removed_with_their_content(
    snippet: str, name: str, remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert notes(result) == [(ELEMENT_REMOVED, "SCR-001", name)]
    assert built(result).screens[0].markup == result.markups[0]


@pytest.mark.parametrize(
    ("snippet", "names", "remaining"),
    [
        (
            "<hgroup><h2>Prestiti</h2><p>Settimana</p></hgroup>",
            ["hgroup"],
            "<h2>Prestiti</h2><p>Settimana</p>",
        ),
        ("<address><p>Via Roma 1</p></address>", ["address"], "<p>Via Roma 1</p>"),
        (
            '<search><form aria-label="Cerca"><p>Filtri</p></form></search>',
            ["search"],
            '<form aria-label="Cerca"><p>Filtri</p></form>',
        ),
        ("<p><u>sotto</u> e <s>barrato</s></p>", ["s", "u"], "<p>sotto e barrato</p>"),
        (
            "<p><del>12</del> <ins>10</ins> <q>ok</q> <cite>Libro</cite></p>",
            ["cite", "del", "ins", "q"],
            "<p>12 10 ok Libro</p>",
        ),
        ("<center><p>Centro</p></center>", ["center"], "<p>Centro</p>"),
        ("<p><menu>Voce</menu></p>", ["menu"], "<p>Voce</p>"),
        ('<p><font color="red">Rosso</font></p>', ["font"], "<p>Rosso</p>"),
    ],
)
def test_other_elements_outside_the_allowed_list_are_unwrapped(
    snippet: str, names: list[str], remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert notes(result) == [(ELEMENT_UNWRAPPED, "SCR-001", name) for name in names]
    built(result)


def test_allowed_elements_are_never_removed_or_unwrapped() -> None:
    snippet = (
        "<article><h2>Titolo</h2><p>Testo con <abbr>ISBN</abbr>, <mark>evidenza</mark> e "
        '<time datetime="2026-09-29">oggi</time>.</p></article>'
        "<details><summary>Dettagli</summary><p>Contenuto</p></details>" + ICON
    )
    result = with_snippet(snippet)
    assert inner(result) == snippet
    assert result.notes == ()


def test_a_hidden_input_is_removed_instead_of_becoming_a_visible_field() -> None:
    result = with_snippet('<input type="hidden" name="prestito" value="8">')
    assert inner(result) == ""
    assert notes(result) == [(ELEMENT_REMOVED, "SCR-001", "input")]


@pytest.mark.parametrize(
    ("snippet", "name", "remaining"),
    [
        ('<p style="color:red">Nota</p>', "style", "<p>Nota</p>"),
        ('<p onclick="alert(1)">Nota</p>', "onclick", "<p>Nota</p>"),
        ("<p ONMOUSEOVER=alert(1)>Nota</p>", "onmouseover", "<p>Nota</p>"),
        ('<p src="x">Nota</p>', "src", "<p>Nota</p>"),
        ('<p srcset="x 1x">Nota</p>', "srcset", "<p>Nota</p>"),
        (
            '<form action="https://example.org" aria-label="f"><p>x</p></form>',
            "action",
            '<form aria-label="f"><p>x</p></form>',
        ),
        (
            '<button type="button" formaction="https://example.org">Invia</button>',
            "formaction",
            '<button type="button">Invia</button>',
        ),
        ('<a href="#SCR-002" target="_blank">Vai</a>', "target", '<a href="#SCR-002">Vai</a>'),
        ('<a href="#SCR-002" download>Vai</a>', "download", '<a href="#SCR-002">Vai</a>'),
        (
            '<a href="#SCR-002" ping="https://example.org">Vai</a>',
            "ping",
            '<a href="#SCR-002">Vai</a>',
        ),
        ('<p srcdoc="x">Nota</p>', "srcdoc", "<p>Nota</p>"),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><path xlink:href="#x" d="M0 0"></path></svg>',
            "xlink:href",
            ICON,
        ),
    ],
)
def test_attributes_that_give_a_behaviour_or_a_resource_are_removed_with_a_note(
    snippet: str, name: str, remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert notes(result) == [(ATTRIBUTE_REMOVED, "SCR-001", name)]
    built(result)


@pytest.mark.parametrize(
    ("snippet", "remaining"),
    [
        (
            '<input name="q" aria-label="Cerca" autocomplete="off" inputmode="search" '
            'spellcheck="false" autocapitalize="off" autocorrect="off" enterkeyhint="search" '
            "autofocus>",
            '<input aria-label="Cerca" name="q">',
        ),
        ('<p translate="no" draggable="true" loading="lazy">Nota</p>', "<p>Nota</p>"),
        ('<form novalidate aria-label="f"><p>x</p></form>', '<form aria-label="f"><p>x</p></form>'),
        ('<p data-status="late" x-data="{}" @click="x">Nota</p>', "<p>Nota</p>"),
        ('<a href="#SCR-002" rel="noopener">Vai</a>', '<a href="#SCR-002">Vai</a>'),
        ('<p href="#SCR-002" width="10" align="left">Nota</p>', "<p>Nota</p>"),
        (
            '<select name="s" aria-label="s" multiple><option>A</option><option>B</option></select>',
            '<select aria-label="s" name="s"><option>A</option><option>B</option></select>',
        ),
    ],
)
def test_attributes_without_effect_on_a_static_mockup_are_removed_without_a_note(
    snippet: str, remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert result.notes == ()
    built(result)


def test_the_recorded_slip_is_removed_without_a_note() -> None:
    markup = BASE_FIRST.replace("<select ", '<select autocomplete="off" ')
    with pytest.raises(GeneratedMockupError) as error:
        built(MockupRepair(BASE_STYLES, (markup, BASE_SECOND), ()))
    assert error.value.code == "ATTRIBUTE_FORBIDDEN"
    result = repair(markup)
    assert result.markups[0] == BASE_FIRST
    assert result.notes == ()


@pytest.mark.parametrize(
    ("href", "name"),
    [
        ("javascript:alert(1)", "javascript:alert(1)"),
        ("https://example.org/x", "https://example.org/x"),
        ("#SCR-009", "#SCR-009"),
        ("#scr-002", "#scr-002"),
        ("#top", "#top"),
        ("SCR-002", "SCR-002"),
        ("", "(empty)"),
    ],
)
def test_links_that_name_no_screen_of_the_answer_lose_their_target(href: str, name: str) -> None:
    result = with_snippet(f'<a href="{href}">Esci</a>')
    assert inner(result) == "<a>Esci</a>"
    assert notes(result) == [(LINK_REMOVED, "SCR-001", name)]
    built(result)


def test_a_link_without_a_value_and_links_to_screens_of_the_answer() -> None:
    assert notes(with_snippet("<a href>Esci</a>")) == [(LINK_REMOVED, "SCR-001", "(empty)")]
    kept = with_snippet('<a href="#SCR-002">Vai</a><a href="#SCR-001" aria-current="page">Qui</a>')
    assert kept.notes == ()


@pytest.mark.parametrize(
    ("snippet", "remaining"),
    [
        (
            '<input type="submit" value="Invia" aria-label="Invia">',
            '<input aria-label="Invia" type="text" value="Invia">',
        ),
        (
            '<input type="file" name="f" aria-label="f">',
            '<input aria-label="f" name="f" type="text">',
        ),
        (
            '<input type="email" name="m" aria-label="m">',
            '<input type="email" name="m" aria-label="m">',
        ),
        ('<button type="menu">Apri</button>', '<button type="button">Apri</button>'),
        ('<p class="card Card ot-pin col_2 x">Nota</p>', '<p class="card col_2 x">Nota</p>'),
        ('<p class="Card OT">Nota</p>', "<p>Nota</p>"),
        ('<p id="nota">A</p><p id="nota">B</p>', '<p id="nota">A</p><p>B</p>'),
        ('<p id="Nota">A</p><p id="ot-x">B</p><p id="1a">C</p>', "<p>A</p><p>B</p><p>C</p>"),
        (
            '<p id="a1">A</p><p aria-describedby="a1 assente">B</p>',
            '<p id="a1">A</p><p aria-describedby="a1">B</p>',
        ),
        ('<p aria-describedby="assente">B</p>', "<p>B</p>"),
        ('<label for="x y">Nome</label>', "<label>Nome</label>"),
        (
            '<input name="x" aria-label="x" disabled="true" required="required" checked="no">',
            '<input aria-label="x" checked disabled name="x" required>',
        ),
        ('<p tabindex="5" lang="italiano!" dir="up" title="" role="Bottone">x</p>', "<p>x</p>"),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><path d="M0 0" fill="#ff0000" stroke="red">'
            "</path></svg>",
            ICON,
        ),
        (
            '<svg aria-hidden="true" viewBox="0 0 1 1"><path d="M0 0" fill="var(--vl-color-nope)">'
            "</path></svg>",
            ICON,
        ),
        ('<ol start="x"><li>A</li><li>B</li></ol>', "<ol><li>A</li><li>B</li></ol>"),
    ],
)
def test_attribute_values_that_the_contract_refuses_are_repaired_or_removed(
    snippet: str, remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert result.notes == ()
    built(result)


@pytest.mark.parametrize(
    ("value", "kept", "removed"),
    [
        ("REQ-099 REQ-001", "REQ-001", ["REQ-099"]),
        ("REQ-099", None, ["REQ-099"]),
        ("", None, ["(empty)"]),
        ("req-001", None, ["req-001"]),
        ("REQ-001, REQ-002", "REQ-001 REQ-002", []),
        ("REQ-001 REQ-001", "REQ-001", []),
        ("REQ-002  REQ-001", "REQ-002 REQ-001", []),
    ],
)
def test_requirement_codes_that_the_project_does_not_have_are_removed(
    value: str, kept: str | None, removed: list[str]
) -> None:
    result = with_snippet(f'<p data-req="{value}">Nota</p>')
    expected = "<p>Nota</p>" if kept is None else f'<p data-req="{kept}">Nota</p>'
    assert inner(result) == expected
    assert notes(result) == [(REQUIREMENT_CODE_REMOVED, "SCR-001", code) for code in removed]


def test_a_code_that_is_only_formally_valid_is_removed_like_any_unknown_code() -> None:
    result = with_snippet('<p data-req="AC-010">Nota</p>')
    assert inner(result) == "<p>Nota</p>"
    assert notes(result) == [(REQUIREMENT_CODE_REMOVED, "SCR-001", "AC-010")]
    kept = with_snippet('<p data-req="AC-010">Nota</p>', codes=CODES | {"AC-010"})
    assert kept.notes == ()


def test_identifiers_reused_in_a_later_screen_are_renamed_with_their_references() -> None:
    twin = '<label for="titolo">Titolo</label><input id="titolo" name="t">'
    first = BASE_FIRST.replace("</main>", twin + '<p id="titolo-2">Nota</p></main>')
    second = BASE_SECOND.replace("</main>", twin + "</main>")
    result = repair(first, second)
    assert result.markups[0] == first
    assert result.markups[1].endswith(
        '<label for="titolo-3">Titolo</label><input id="titolo-3" name="t"></main>'
    )
    assert result.notes == ()
    mockup = built(result)
    report = review_generated_mockup(mockup, tokens=LIGHT_TOKENS, requirement_codes=CODES)
    assert not [issue for issue in report.issues if issue.code == "UNLABELLED_CONTROL"]


def test_long_identifiers_stay_within_the_pattern_when_renamed() -> None:
    identifier = "a" * 64
    element = f'<p id="{identifier}">Nota</p>'
    result = repair(
        BASE_FIRST.replace("</main>", element + "</main>"),
        BASE_SECOND.replace("</main>", element + "</main>"),
    )
    assert f'<p id="{"a" * 62}-2">Nota</p>' in result.markups[1]
    built(result)


def test_controls_without_a_requirement_receive_the_codes_of_their_screen() -> None:
    untraced = BASE_FIRST.replace('<main data-req="REQ-001">', "<main>").replace(
        "<h1>", '<h1 data-req="REQ-001">'
    )
    result = repair(untraced)
    assert '<select data-req="REQ-001" id="stato" name="stato">' in result.markups[0]
    assert '<a data-req="REQ-001" href="#SCR-002">' in result.markups[0]
    assert notes(result) == [(REQUIREMENT_INHERITED, "SCR-001", "REQ-001 (2)")]
    report = review_generated_mockup(built(result), tokens=LIGHT_TOKENS, requirement_codes=CODES)
    assert not [issue for issue in report.issues if issue.code.startswith("UNTRACED")]


def test_a_screen_without_requirements_receives_the_codes_of_the_link_that_leads_to_it() -> None:
    bare = BASE_SECOND.replace(' data-req="REQ-002"', "")
    result = repair(second=bare, declared=("REQ-002",))
    assert result.markups[1].startswith('<main data-req="REQ-001"><h1>Promemoria inviato</h1>')
    assert notes(result) == [(REQUIREMENT_INHERITED, "SCR-002", "REQ-001")]


def test_a_screen_without_requirements_nor_traced_links_receives_the_declared_codes() -> None:
    first = BASE_FIRST.replace(' data-req="REQ-001"', "")
    second = BASE_SECOND.replace(' data-req="REQ-002"', "")
    result = repair(first, second, declared=("REQ-002", "REQ-099"))
    assert result.markups[0].startswith('<main data-req="REQ-002">')
    assert result.markups[1].startswith('<main data-req="REQ-002">')
    assert notes(result) == [
        (REQUIREMENT_INHERITED, "SCR-001", "REQ-002"),
        (REQUIREMENT_INHERITED, "SCR-002", "REQ-002"),
    ]
    report = review_generated_mockup(built(result), tokens=LIGHT_TOKENS, requirement_codes=CODES)
    assert report.is_acceptable


def test_without_any_code_to_inherit_the_screen_stays_untraced_and_is_rejected() -> None:
    first = BASE_FIRST.replace(' data-req="REQ-001"', "")
    second = BASE_SECOND.replace(' data-req="REQ-002"', "")
    result = repair(first, second)
    assert result.markups == (first, second)
    assert result.notes == ()
    report = review_generated_mockup(built(result), tokens=LIGHT_TOKENS, requirement_codes=CODES)
    untraced = [issue for issue in report.issues if issue.code.startswith("UNTRACED")]
    assert untraced and all(issue.severity is MockupIssueSeverity.ERROR for issue in untraced)


@pytest.mark.parametrize(
    ("snippet", "remaining"),
    [
        ("<p>Domande Q&A e a < b</p>", "<p>Domande Q&amp;A e a &lt; b</p>"),
        ('<p><span class="dot"/>Attivo</p>', '<p><span class="dot"></span>Attivo</p>'),
        ('<input name="x" aria-label="x"></input>', '<input aria-label="x" name="x">'),
        ("<p>a</br>b</p>", "<p>ab</p>"),
        ('<p class="a" class="b">x</p>', '<p class="a">x</p>'),
        ('<a href="#SCR-002"title="Vai">x</a>', '<a href="#SCR-002" title="Vai">x</a>'),
        (
            '<textarea name="t" aria-label="t">a<b</textarea>',
            '<textarea aria-label="t" name="t">a&lt;b</textarea>',
        ),
        ("<![CDATA[x]]><?xml version='1.0'?><!DOCTYPE html><p>x</p>", "<p>x</p>"),
    ],
)
def test_harmless_syntax_slips_are_written_again_in_the_accepted_form(
    snippet: str, remaining: str
) -> None:
    result = with_snippet(snippet)
    assert inner(result) == remaining
    assert result.notes == ()
    built(result)


@pytest.mark.parametrize(
    ("markup", "code"),
    [
        (BASE_FIRST.replace("</main>", "<section><p>Fine</p></main>"), "MISNESTED_ELEMENT"),
        (BASE_FIRST.replace("</main>", "<b><i>x</b></i></main>"), "MISNESTED_ELEMENT"),
        (BASE_FIRST + "</div>", "UNEXPECTED_END_TAG"),
        (BASE_FIRST + "<section>", "UNCLOSED_ELEMENT"),
        (BASE_FIRST.replace("</main>", "<p><div>x</div></p></main>"), "CONTENT_RULE"),
        ("<div>" * 41 + "x" + "</div>" * 41 + BASE_FIRST, "MARKUP_TOO_DEEP"),
        (BASE_FIRST + "<br>" * 1500, "TOO_MANY_ELEMENTS"),
        (BASE_FIRST.replace("</main>", "<script>never closed</main>"), "ELEMENT_FORBIDDEN"),
    ],
)
def test_markup_that_cannot_be_repaired_without_guessing_is_still_rejected(
    markup: str, code: str
) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        built(repair(markup))
    assert error.value.code == code
    slipped = repair(markup.replace("<select ", '<select autocomplete="off" '))
    with pytest.raises(GeneratedMockupError):
        built(slipped)


def test_markup_whose_structure_is_broken_comes_back_as_it_was() -> None:
    broken = BASE_FIRST.replace("</main>", '<section><p style="x">Fine</p></main>')
    result = repair(broken)
    assert result.markups[0] == broken
    assert result.notes == ()


def test_notes_are_counted_ordered_and_bounded() -> None:
    first = BASE_FIRST.replace(
        "</main>", '<p style="a">x</p><p style="b">y</p><img src="x"><img src="y"></main>'
    )
    second = BASE_SECOND.replace("</main>", '<a href="#SCR-009">Altro</a></main>')
    result = repair(first, second, styles=BASE_STYLES + "p{color:red}")
    assert notes(result) == [
        ("STYLE_DECLARATION_REMOVED", None, "color"),
        (ATTRIBUTE_REMOVED, "SCR-001", "style (2)"),
        (ELEMENT_REMOVED, "SCR-001", "img (2)"),
        (LINK_REMOVED, "SCR-002", "#SCR-009"),
    ]
    assert result.notes[1] == RepairNote(ATTRIBUTE_REMOVED, "SCR-001", "style", 2)
    assert result.notes[1].to_snapshot() == {
        "code": ATTRIBUTE_REMOVED,
        "screen_code": "SCR-001",
        "detail": "style (2)",
    }
    long = with_snippet(f'<a href="https://example.org/{"x" * 300}">Esci</a>')
    assert len(long.notes[0].name) == MAX_NOTE_NAME_LENGTH
    odd = with_snippet('<a href="https://example.org/è">Esci</a>')
    assert odd.notes[0].name == "https://example.org/?"
    assert {note.code for note in result.notes} <= set(REPAIR_NOTE_CODES)


def safe_markup(markup: str) -> None:
    collector = Collector()
    collector.feed(markup)
    collector.close()
    assert set(collector.tags) <= ALLOWED_ELEMENTS
    for name, value in collector.attributes:
        assert not name.startswith("on")
        assert name not in {"style", "src", "srcset", "srcdoc", "action", "formaction", "target"}
        if name == "href":
            assert value is not None and value.startswith("#SCR-")
    assert "javascript:" not in markup.lower()


@pytest.mark.parametrize("snippet", [*REJECTED_ELEMENTS, *HOSTILE_MARKUP, *EXTRA_HOSTILE])
def test_hostile_markup_is_either_rejected_or_free_of_everything_forbidden(snippet: str) -> None:
    result = with_snippet(snippet)
    try:
        mockup = built(result)
    except GeneratedMockupError:
        return
    for screen in mockup.screens:
        safe_markup(screen.markup)
    assert_safe(mockup_document(mockup, tokens=LIGHT_TOKENS, language="it"))


def test_random_hostile_combinations_are_either_rejected_or_safe() -> None:
    generator = Random(20260928)
    fragments = [*REJECTED_ELEMENTS, *HOSTILE_MARKUP, *EXTRA_HOSTILE]
    accepted = 0
    for _ in range(300):
        chosen = "".join(generator.choice(fragments) for _ in range(generator.randint(1, 5)))
        if generator.random() < 0.5:
            markup = BASE_FIRST.replace("</main>", chosen + "</main>")
        else:
            markup = BASE_FIRST.replace("<p>", "<p>" + chosen, 1)
        result = repair(markup)
        assert again(result).markups == result.markups
        try:
            mockup = built(result)
        except GeneratedMockupError:
            continue
        accepted += 1
        for screen in mockup.screens:
            safe_markup(screen.markup)
        assert_safe(mockup_document(mockup, tokens=LIGHT_TOKENS, language="it"))
    assert accepted >= 150
