from __future__ import annotations

from dataclasses import replace
from random import Random

import pytest

from orchestwin.artifacts.generated_mockup_styles import MAX_STYLES_LENGTH
from orchestwin.artifacts.generated_mockups import (
    MAX_DEPTH,
    MAX_ELEMENTS,
    MAX_MARKUP_LENGTH,
    MAX_MOCKUP_LENGTH,
    MOCKUP_CONTRACT_VERSION,
    GeneratedMockup,
    GeneratedMockupError,
    GeneratedScreen,
    MarkupElement,
    MarkupText,
    create_generated_mockup,
    generated_mockup_from_snapshot,
    parse_markup,
    serialize_markup,
)
from orchestwin.artifacts.prototypes import PrototypeScreenState

from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_FIRST,
    BASE_SECOND,
    BASE_STYLES,
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN,
    FIXTURES,
    HTML_COMMENT_CLOSE,
    HTML_COMMENT_OPEN,
    TOKEN_NAMES,
    build,
    fixture_mockup,
    fixture_tokens,
    screen_payloads,
    with_first,
)

SCREEN_CODES = frozenset({"SCR-001", "SCR-002"})


def rejects(snippet: str, code: str) -> GeneratedMockupError:
    with pytest.raises(GeneratedMockupError) as error:
        with_first(snippet)
    assert error.value.code == code, error.value.detail
    return error.value


def rejects_markup(markup: str, code: str) -> GeneratedMockupError:
    with pytest.raises(GeneratedMockupError) as error:
        build(markup)
    assert error.value.code == code, error.value.detail
    return error.value


def stored(snippet: str) -> str:
    markup = with_first(snippet).screens[0].markup
    prefix, suffix = BASE_FIRST[: -len("</main>")], "</main>"
    assert markup.startswith(prefix) and markup.endswith(suffix)
    return markup[len(prefix) : -len(suffix)]


def test_baseline_mockup_is_normalized_versioned_and_hashable() -> None:
    mockup = build(title="  Registro   dei prestiti ")
    assert mockup.contract_version == MOCKUP_CONTRACT_VERSION == 1
    assert mockup.design_alternative_id == ALTERNATIVE_ID
    assert mockup.title == "Registro dei prestiti"
    assert [screen.code for screen in mockup.screens] == ["SCR-001", "SCR-002"]
    assert mockup.screens[1].state is PrototypeScreenState.SUCCESS
    assert mockup.screens[0].markup == BASE_FIRST
    assert mockup.styles == BASE_STYLES
    assert len(mockup.content_hash) == 64
    assert set(mockup.to_snapshot()) == {
        "contract_version",
        "design_alternative_id",
        "title",
        "styles",
        "screens",
    }
    assert set(mockup.to_snapshot()["screens"][0]) == {"code", "title", "state", "markup"}


@pytest.mark.parametrize("name", FIXTURES)
def test_snapshot_round_trip_gives_an_equal_object_with_the_same_hash(name: str) -> None:
    mockup = fixture_mockup(name)
    names = frozenset(fixture_tokens(name))
    restored = generated_mockup_from_snapshot(mockup.to_snapshot(), token_names=names)
    assert restored == mockup
    assert restored.content_hash == mockup.content_hash
    assert restored.canonical_json() == mockup.canonical_json()
    again = create_generated_mockup(
        design_alternative_id=mockup.design_alternative_id,
        title=mockup.title,
        styles=mockup.styles,
        screens=mockup.screens,
        token_names=names,
    )
    assert again == mockup


def test_snapshot_loading_rejects_malformed_and_non_canonical_payloads() -> None:
    snapshot = build().to_snapshot()
    cases = [
        ({**snapshot, "extra": 1}, "SNAPSHOT_INVALID"),
        ({key: value for key, value in snapshot.items() if key != "styles"}, "SNAPSHOT_INVALID"),
        ({**snapshot, "screens": "SCR-001"}, "SNAPSHOT_INVALID"),
        ({**snapshot, "screens": [{**snapshot["screens"][0], "x": 1}]}, "SNAPSHOT_INVALID"),
        ({**snapshot, "title": 3}, "SNAPSHOT_INVALID"),
        ({**snapshot, "contract_version": 2}, "CONTRACT_VERSION"),
        ({**snapshot, "contract_version": True}, "CONTRACT_VERSION"),
        ({**snapshot, "design_alternative_id": "nope"}, "ALTERNATIVE_ID"),
        (
            {**snapshot, "design_alternative_id": str(ALTERNATIVE_ID).upper()},
            "SNAPSHOT_NOT_CANONICAL",
        ),
        (
            {**snapshot, "styles": CSS_COMMENT_OPEN + " x " + CSS_COMMENT_CLOSE + BASE_STYLES},
            "SNAPSHOT_NOT_CANONICAL",
        ),
        (
            {
                **snapshot,
                "screens": [
                    {**snapshot["screens"][0], "markup": BASE_FIRST.replace("<h1>", "<H1>")},
                    snapshot["screens"][1],
                ],
            },
            "SNAPSHOT_NOT_CANONICAL",
        ),
        ({**snapshot, "title": " Registro dei prestiti"}, "SNAPSHOT_NOT_CANONICAL"),
    ]
    for payload, code in cases:
        with pytest.raises(GeneratedMockupError) as error:
            generated_mockup_from_snapshot(payload, token_names=TOKEN_NAMES)
        assert error.value.code == code
    with pytest.raises(GeneratedMockupError) as error:
        generated_mockup_from_snapshot([snapshot], token_names=TOKEN_NAMES)
    assert error.value.code == "SNAPSHOT_INVALID"


def test_markup_is_rewritten_by_the_serializer_so_the_stored_text_is_the_document_text() -> None:
    markup = (
        "<MAIN DATA-REQ=\"REQ-001\"><H1 class='title  big'>Prestiti &amp; rinnovi</H1>"
        "<p>Uno<br/>due &egrave; &#8364; 5 &gt; 3 \"citato\" 'apice'</p>"
        '<input type=text name=q disabled="disabled">'
        '<a href="&#x23;SCR-002" aria-label=\'Vai "oltre"\'>Avanti</a></MAIN>'
    )
    assert build(markup).screens[0].markup == (
        '<main data-req="REQ-001"><h1 class="title big">Prestiti &amp; rinnovi</h1>'
        "<p>Uno<br>due è € 5 &gt; 3 \"citato\" 'apice'</p>"
        '<input disabled name="q" type="text">'
        '<a aria-label="Vai &quot;oltre&quot;" href="#SCR-002">Avanti</a></main>'
    )


def test_markup_line_breaks_are_normalized_like_the_html_input_stream() -> None:
    assert stored("<p>uno\r\ndue\rtre</p>") == "<p>uno\ndue\ntre</p>"


def test_styles_comments_are_removed() -> None:
    styles = CSS_COMMENT_OPEN + " intestazione " + CSS_COMMENT_CLOSE + "\n" + BASE_STYLES
    assert build(styles=styles).styles == "\n" + BASE_STYLES


def test_direct_construction_validates_safety_and_canonical_form() -> None:
    mockup = build()
    first, second = mockup.screens
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, screens=(replace(first, markup="<script>x</script>"), second))
    assert error.value.code == "ELEMENT_FORBIDDEN"
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, screens=(replace(first, markup=BASE_FIRST.replace("<h1>", "<H1>")), second))
    assert error.value.code == "NOT_CANONICAL"
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, styles=CSS_COMMENT_OPEN + "x" + CSS_COMMENT_CLOSE)
    assert error.value.code == "NOT_CANONICAL"
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, styles="main{background:url(x)}")
    assert error.value.code == "STYLES_FORBIDDEN"
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, contract_version=2)
    assert error.value.code == "CONTRACT_VERSION"
    with pytest.raises(GeneratedMockupError) as error:
        replace(mockup, screens=[first, second])
    assert error.value.code == "SCREEN_INVALID"
    with pytest.raises(GeneratedMockupError) as error:
        replace(first, code="SCR-1")
    assert error.value.code == "SCREEN_CODE"
    with pytest.raises(GeneratedMockupError) as error:
        replace(first, title=" x")
    assert error.value.code == "TITLE_INVALID"
    with pytest.raises(GeneratedMockupError) as error:
        replace(first, state="DEFAULT")
    assert error.value.code == "SCREEN_STATE"


@pytest.mark.parametrize(
    ("title", "valid"),
    [
        ("Registro", True),
        ("x" * 200, True),
        ("", False),
        ("   ", False),
        ("x" * 201, False),
        ("Registro\x00", False),
        ("Registro\x07prestiti", False),
        ("Registro\ud800", False),
    ],
)
def test_titles_are_normalized_text_of_one_to_two_hundred_characters(
    title: str, valid: bool
) -> None:
    if valid:
        assert build(title=title).title == title
        payload = screen_payloads((BASE_FIRST, BASE_SECOND), titles=(title, "Fine"))
        mockup = create_generated_mockup(
            design_alternative_id=ALTERNATIVE_ID,
            title="Registro",
            styles=BASE_STYLES,
            screens=payload,
            token_names=TOKEN_NAMES,
        )
        assert mockup.screens[0].title == title
        return
    with pytest.raises(GeneratedMockupError) as error:
        build(title=title)
    assert error.value.code == "TITLE_INVALID"
    with pytest.raises(GeneratedMockupError) as error:
        create_generated_mockup(
            design_alternative_id=ALTERNATIVE_ID,
            title="Registro",
            styles=BASE_STYLES,
            screens=screen_payloads((BASE_FIRST, BASE_SECOND), titles=(title, "Fine")),
            token_names=TOKEN_NAMES,
        )
    assert error.value.code == "TITLE_INVALID"


@pytest.mark.parametrize(("count", "valid"), [(1, False), (2, True), (8, True), (9, False)])
def test_a_mockup_has_two_to_eight_screens(count: int, valid: bool) -> None:
    markups = ["<p>Schermata</p>"] * count
    payload = screen_payloads(markups, titles=[f"Schermata {index}" for index in range(count)])
    arguments = {
        "design_alternative_id": ALTERNATIVE_ID,
        "title": "Registro",
        "styles": "",
        "screens": payload,
        "token_names": TOKEN_NAMES,
    }
    if valid:
        assert len(create_generated_mockup(**arguments).screens) == count
        return
    with pytest.raises(GeneratedMockupError) as error:
        create_generated_mockup(**arguments)
    assert error.value.code == "SCREEN_COUNT"


@pytest.mark.parametrize(
    "codes",
    [
        ("SCR-002", "SCR-001"),
        ("SCR-001", "SCR-003"),
        ("scr-001", "scr-002"),
        ("SCR-000", "SCR-001"),
    ],
)
def test_screen_codes_are_consecutive_and_in_order(codes: tuple[str, str]) -> None:
    payload = screen_payloads(("<p>Uno</p>", "<p>Due</p>"))
    for item, code in zip(payload, codes, strict=True):
        item["code"] = code
    with pytest.raises(GeneratedMockupError) as error:
        create_generated_mockup(
            design_alternative_id=ALTERNATIVE_ID,
            title="Registro",
            styles="",
            screens=payload,
            token_names=TOKEN_NAMES,
        )
    assert error.value.code == "SCREEN_CODE"


def test_screen_states_are_prototype_states() -> None:
    payload = screen_payloads(("<p>Uno</p>", "<p>Due</p>"))
    payload[1]["state"] = "EMPTY"
    mockup = create_generated_mockup(
        design_alternative_id=ALTERNATIVE_ID,
        title="Registro",
        styles="",
        screens=payload,
        token_names=TOKEN_NAMES,
    )
    assert mockup.screens[1].state is PrototypeScreenState.EMPTY
    payload[1]["state"] = "LOADING"
    with pytest.raises(GeneratedMockupError) as error:
        create_generated_mockup(
            design_alternative_id=ALTERNATIVE_ID,
            title="Registro",
            styles="",
            screens=payload,
            token_names=TOKEN_NAMES,
        )
    assert error.value.code == "SCREEN_STATE"


def test_screen_entries_must_be_screens_or_mappings_with_every_field() -> None:
    for screens in (
        ["<p>Uno</p>", "<p>Due</p>"],
        [{"code": "SCR-001", "title": "Uno", "state": "DEFAULT"}, {"code": "SCR-002"}],
    ):
        with pytest.raises(GeneratedMockupError) as error:
            create_generated_mockup(
                design_alternative_id=ALTERNATIVE_ID,
                title="Registro",
                styles="",
                screens=screens,
                token_names=TOKEN_NAMES,
            )
        assert error.value.code == "SCREEN_INVALID"


def test_size_limits_of_styles_markup_and_whole_mockup() -> None:
    assert MAX_STYLES_LENGTH == 60_000
    assert MAX_MARKUP_LENGTH == 40_000
    assert MAX_MOCKUP_LENGTH == 250_000
    filler = "main{margin:0}"
    styles = filler * (MAX_STYLES_LENGTH // len(filler))
    assert len(build(styles=styles).styles) <= MAX_STYLES_LENGTH
    with pytest.raises(GeneratedMockupError) as error:
        build(styles=styles + "a" * (MAX_STYLES_LENGTH - len(styles) + 1))
    assert error.value.code == "STYLES_TOO_LONG"
    exact = "<p>" + "x" * (MAX_MARKUP_LENGTH - 7) + "</p>"
    assert len(build(exact).screens[0].markup) == MAX_MARKUP_LENGTH
    with pytest.raises(GeneratedMockupError) as error:
        build("<p>" + "x" * (MAX_MARKUP_LENGTH - 6) + "</p>")
    assert error.value.code == "MARKUP_TOO_LONG"
    with pytest.raises(GeneratedMockupError) as error:
        build("<p>" + ">" * (MAX_MARKUP_LENGTH - 10) + "</p>")
    assert error.value.code == "MARKUP_TOO_LONG"
    large = "<p>" + "y" * 39_000 + "</p>"
    with pytest.raises(GeneratedMockupError) as error:
        build(large, large, extra=[large] * 5)
    assert error.value.code == "MOCKUP_TOO_LONG"


def test_identity_arguments_are_checked() -> None:
    with pytest.raises(GeneratedMockupError) as error:
        create_generated_mockup(
            design_alternative_id="5b7e0d0a-2f4c-4d7b-9a1e-3c6f8e2b1d10",
            title="Registro",
            styles="",
            screens=screen_payloads(("<p>Uno</p>", "<p>Due</p>")),
            token_names=TOKEN_NAMES,
        )
    assert error.value.code == "ALTERNATIVE_ID"
    for names in ({"color"}, {"--vl-X"}, {"--m-gap"}, {3}):
        with pytest.raises(GeneratedMockupError) as error:
            build(token_names=names)
        assert error.value.code == "TOKEN_NAMES"


def test_errors_name_the_place_and_never_repeat_the_whole_text() -> None:
    error = rejects("<script>" + "alert(1);" * 200 + "</script>", "ELEMENT_FORBIDDEN")
    assert "SCR-001" in error.detail
    assert "script" in error.detail
    assert "alert" not in error.detail
    assert len(error.detail) < 120
    assert str(error).startswith("ELEMENT_FORBIDDEN")
    assert isinstance(error, ValueError)
    long_name = rejects("<x" + "y" * 500 + ">z</x" + "y" * 500 + ">", "ELEMENT_FORBIDDEN")
    assert len(long_name.detail) < 120


REJECTED_ELEMENTS = [
    "<script>alert(1)</script>",
    "<SCRIPT>alert(1)</SCRIPT>",
    "<ScRiPt>alert(1)</sCrIpT>",
    "<style>p{color:red}</style>",
    '<link rel="stylesheet" href="x.css">',
    '<meta http-equiv="refresh" content="0">',
    '<base href="https://example.org/">',
    "<title>x</title>",
    '<iframe src="https://example.org"></iframe>',
    '<IFRAME srcdoc="x"></IFRAME>',
    '<frame src="x">',
    '<object data="x"></object>',
    '<embed src="x">',
    '<img src="x" alt="x">',
    '<IMG SRC="x">',
    "<picture></picture>",
    '<source src="x">',
    "<video></video>",
    "<audio></audio>",
    "<canvas></canvas>",
    "<template><p>x</p></template>",
    "<slot></slot>",
    "<noscript>x</noscript>",
    "<math><mi>x</mi></math>",
    "<svg><foreignObject><p>x</p></foreignObject></svg>",
    "<svg><foreignobject></foreignobject></svg>",
    '<svg><use href="#x"></use></svg>',
    '<svg><image href="x"></image></svg>',
    '<svg><animate attributeName="x"></animate></svg>',
    '<svg><set attributeName="x"></set></svg>',
    "<svg><text>x</text></svg>",
    "<body>x</body>",
    "<html>x</html>",
    "<head></head>",
    "<xmp>x</xmp>",
    "<plaintext>x",
    "<marquee>x</marquee>",
    "<dialog open>x</dialog>",
    "<pre>x</pre>",
    "<font>x</font>",
    "<custom-card>x</custom-card>",
    "<frameset></frameset>",
    "<applet></applet>",
    "<keygen>",
]


@pytest.mark.parametrize("snippet", REJECTED_ELEMENTS)
def test_elements_outside_the_allowed_vocabulary_are_rejected(snippet: str) -> None:
    rejects(snippet, "ELEMENT_FORBIDDEN")


ACCEPTED_SNIPPETS = [
    "<article><h2>Titolo</h2><p>Testo con <abbr>ISBN</abbr>, <b>b</b>, <i>i</i>, <em>em</em>, "
    "<strong>forte</strong>, <small>piccolo</small>, <mark>evidenza</mark>, <code>codice</code>, "
    "<kbd>Invio</kbd>, <sub>2</sub>, <sup>3</sup>, <span>span</span> e "
    '<time datetime="2026-09-29">oggi</time>.<br>Riga</p></article>',
    "<aside><blockquote><p>Citazione</p></blockquote><hr></aside>",
    "<section><header><h2>A</h2></header><div><h3>B</h3><h4>C</h4></div>"
    "<footer><p>Fine</p></footer></section>",
    '<nav><ul><li>Uno</li><li>Due</li></ul><ol start="3" reversed><li>Tre</li></ol></nav>',
    "<dl><dt>Termine</dt><dd>Definizione</dd></dl>",
    "<figure><div>Grafico</div><figcaption>Didascalia</figcaption></figure>",
    "<details open><summary>Dettagli</summary><p>Contenuto</p></details>",
    '<form aria-label="Modulo"><fieldset><legend>Scelta</legend>'
    '<label for="a1">Nome</label><input id="a1" name="nome" type="text" required>'
    '<label><input type="checkbox" name="c" value="x" checked> Opzione</label>'
    '<select name="s" required><optgroup label="G"><option value="1" selected>Uno</option>'
    "</optgroup><option disabled>Due</option></select>"
    '<textarea name="t" rows="3" cols="20" placeholder="Note">Testo</textarea>'
    '<button type="button" name="b" value="v" disabled>Invia</button>'
    "<output>42</output>"
    '<meter value="0.6" min="0" max="1" low="0.2" high="0.8" optimum="0.5">60%</meter>'
    '<progress value="3" max="10">3</progress></fieldset></form>',
    '<table><caption>Tabella</caption><colgroup span="2"></colgroup>'
    '<colgroup><col span="1"><col></colgroup>'
    '<thead><tr><th scope="col" id="h1c">A</th><th scope="col">B</th></tr></thead>'
    '<tbody><tr><td headers="h1c" colspan="1" rowspan="1">1</td><td>2</td></tr></tbody>'
    "<tfoot><tr><td>3</td><td>4</td></tr></tfoot></table>",
    '<button type="button" aria-label="Chiudi"><svg viewBox="0 0 24 24" width="24" height="24" '
    'aria-hidden="true" focusable="false"><g transform="translate(2 2) rotate(45)">'
    '<path d="M0 0L10 10M10 0L0 10" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" fill="none"></path>'
    '<circle cx="5" cy="5" r="4" fill="var(--vl-color-primary)" opacity="0.5"></circle>'
    '<ellipse cx="5" cy="5" rx="4" ry="2"></ellipse><line x1="0" y1="0" x2="1" y2="1"></line>'
    '<polyline points="0,0 1,1 2,0"></polyline><polygon points="0,0 1,1 2,0"></polygon>'
    '<rect x="0" y="0" width="4" height="4" rx="1" stroke-dasharray="2 2"></rect>'
    "</g></svg></button>",
    '<main lang="it-IT" dir="ltr" role="region" hidden tabindex="-1" aria-label="Area" '
    'aria-describedby="d1" data-req="REQ-001 AC-002"><p id="d1" tabindex="0">Descrizione</p></main>',
]


@pytest.mark.parametrize("snippet", ACCEPTED_SNIPPETS)
def test_every_allowed_element_is_accepted_in_a_valid_context(snippet: str) -> None:
    markup = stored(snippet)
    assert parse_markup(markup, screen_code="SCR-001", screen_codes=SCREEN_CODES)
    assert stored(markup) == markup


@pytest.mark.parametrize(
    ("snippet", "code"),
    [
        (HTML_COMMENT_OPEN + ">", "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + "->", "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + "->testo" + HTML_COMMENT_CLOSE, "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + ">testo" + HTML_COMMENT_CLOSE, "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + " senza fine", "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + " a -- b " + HTML_COMMENT_CLOSE, "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + "------" + HTML_COMMENT_CLOSE, "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + " a --!>", "MARKUP_COMMENT"),
        (HTML_COMMENT_OPEN + " a --!> b " + HTML_COMMENT_CLOSE, "MARKUP_COMMENT"),
        (
            HTML_COMMENT_OPEN + " a " + HTML_COMMENT_OPEN + " b " + HTML_COMMENT_CLOSE,
            "MARKUP_COMMENT",
        ),
        ("<p>a" + HTML_COMMENT_OPEN + "b -- c" + HTML_COMMENT_CLOSE + "d</p>", "MARKUP_COMMENT"),
        ("<!DOCTYPE html>", "MARKUP_DOCTYPE"),
        ("<!doctype html>", "MARKUP_DOCTYPE"),
        ('<?xml version="1.0"?>', "MARKUP_PROCESSING_INSTRUCTION"),
        ("<![CDATA[<script>x</script>]]>", "MARKUP_CDATA"),
        ("<!ELEMENT br EMPTY>", "MARKUP_DECLARATION"),
        ("<!x>", "MARKUP_DECLARATION"),
        ("</ p>", "MARKUP_SYNTAX"),
        ("</3>", "MARKUP_SYNTAX"),
    ],
)
def test_comments_declarations_and_instructions_are_rejected(snippet: str, code: str) -> None:
    rejects(snippet, code)


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        (HTML_COMMENT_OPEN + " nota " + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + "-" + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + "x-" + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + " a > b - c " + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + "\nriga uno\r\nriga due\n" + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + "[if IE]><p>vecchio</p><![endif]" + HTML_COMMENT_CLOSE, ""),
        (HTML_COMMENT_OPEN + " a <!- b " + HTML_COMMENT_CLOSE, ""),
        ("<p>a" + HTML_COMMENT_OPEN + " b " + HTML_COMMENT_CLOSE + "c</p>", "<p>ac</p>"),
        (
            "<ul>"
            + HTML_COMMENT_OPEN
            + " voci "
            + HTML_COMMENT_CLOSE
            + "<li>a</li><li>b</li></ul>",
            "<ul><li>a</li><li>b</li></ul>",
        ),
        (
            "<table>"
            + HTML_COMMENT_OPEN
            + " t "
            + HTML_COMMENT_CLOSE
            + "<tbody><tr>"
            + HTML_COMMENT_OPEN
            + " r "
            + HTML_COMMENT_CLOSE
            + "<td>1</td></tr></tbody></table>",
            "<table><tbody><tr><td>1</td></tr></tbody></table>",
        ),
        (
            '<select name="s" aria-label="s">'
            + HTML_COMMENT_OPEN
            + " o "
            + HTML_COMMENT_CLOSE
            + "<option>a</option></select>",
            '<select aria-label="s" name="s"><option>a</option></select>',
        ),
        (
            '<svg viewBox="0 0 1 1">'
            + HTML_COMMENT_OPEN
            + " icona "
            + HTML_COMMENT_CLOSE
            + '<path d="M0 0"></path></svg>',
            '<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>',
        ),
        (
            "<details>"
            + HTML_COMMENT_OPEN
            + " s "
            + HTML_COMMENT_CLOSE
            + "<summary>S</summary></details>",
            "<details><summary>S</summary></details>",
        ),
    ],
)
def test_comments_in_the_accepted_form_are_dropped(snippet: str, expected: str) -> None:
    markup = stored(snippet)
    assert markup == expected
    assert HTML_COMMENT_OPEN not in with_first(snippet).screens[0].markup


def test_a_comment_can_open_and_close_the_markup() -> None:
    markup = HTML_COMMENT_OPEN + " inizio " + HTML_COMMENT_CLOSE + BASE_FIRST
    markup += HTML_COMMENT_OPEN + " fine " + HTML_COMMENT_CLOSE
    assert build(markup).screens[0].markup == BASE_FIRST


@pytest.mark.parametrize(
    "snippet",
    [
        '<p onclick="alert(1)">x</p>',
        '<p ONCLICK="alert(1)">x</p>',
        '<p onClick="alert(1)">x</p>',
        "<p onmouseover=alert(1)>x</p>",
        "<p onfocus>x</p>",
        '<svg onload="alert(1)"></svg>',
        '<p style="color:red">x</p>',
        '<p STYLE="color:red">x</p>',
        '<p src="x">x</p>',
        '<p srcset="x 1x">x</p>',
        '<form action="https://example.org" aria-label="f"></form>',
        '<button type="button" formaction="https://example.org">x</button>',
        '<form method="post" aria-label="f"></form>',
        '<a href="#SCR-002" target="_blank">x</a>',
        '<a href="#SCR-002" download>x</a>',
        '<a href="#SCR-002" ping="https://example.org">x</a>',
        '<a href="#SCR-002" rel="noopener">x</a>',
        '<p srcdoc="x">x</p>',
        '<svg><path xlink:href="#x" d="M0 0"></path></svg>',
        '<svg xmlns:xlink="http://www.w3.org/1999/xlink"></svg>',
        '<svg><path xmlns="http://www.w3.org/2000/svg" d="M0 0"></path></svg>',
        '<p xmlns="http://www.w3.org/1999/xhtml">x</p>',
        '<div xmlns="http://www.w3.org/2000/svg">x</div>',
        '<p href="#SCR-002">x</p>',
        '<button type="button" href="#SCR-002">x</button>',
        '<svg><path href="#SCR-002" d="M0 0"></path></svg>',
        '<p is="x-p">x</p>',
        '<p contenteditable="true">x</p>',
        '<input name="x" autofocus aria-label="x">',
        '<abbr titel="International Standard Book Number">ISBN</abbr>',
        '<p data-x="1">x</p>',
        '<p data-elm="ELM-001">x</p>',
        '<p data-ot="1">x</p>',
        "<p data-entry>x</p>",
        '<input name="x" form="f" aria-label="x">',
        '<input name="x" accept="image/png" aria-label="x">',
        '<select name="s" multiple aria-label="s"><option>a</option></select>',
        '<output for="x">1</output>',
        '<form name="f" aria-label="f"></form>',
        '<p width="10">x</p>',
        '<p d="M0 0">x</p>',
        '<li value="3">x</li>',
        '<svg class="i" lang="it" style="x"></svg>',
    ],
)
def test_attributes_outside_the_allowed_list_are_rejected(snippet: str) -> None:
    if snippet.startswith("<li"):
        snippet = "<ul>" + snippet + "</ul>"
    rejects(snippet, "ATTRIBUTE_FORBIDDEN")


@pytest.mark.parametrize(
    "snippet",
    [
        "<a href>x</a>",
        "<p class>x</p>",
        "<p id>x</p>",
        "<p data-req>x</p>",
        "<p aria-label>x</p>",
        "<p role>x</p>",
        "<p tabindex>x</p>",
        '<input name="x" disabled="false" aria-label="x">',
        '<input name="x" required="no" aria-label="x">',
        '<details open="closed"><summary>x</summary></details>',
    ],
)
def test_attributes_without_a_required_value_and_wrong_booleans_are_rejected(
    snippet: str,
) -> None:
    rejects(snippet, "ATTRIBUTE_VALUE")


def test_boolean_attributes_are_stored_as_bare_names() -> None:
    assert stored('<input name="x" disabled aria-label="x">') == (
        '<input aria-label="x" disabled name="x">'
    )
    assert stored('<input name="x" DISABLED="DISABLED" required="" aria-label="x">') == (
        '<input aria-label="x" disabled name="x" required>'
    )


@pytest.mark.parametrize(
    "snippet",
    [
        '<p class="a" class="b">x</p>',
        '<p CLASS="a" class="b">x</p>',
        '<a href="#SCR-002" HREF="#SCR-001">x</a>',
        '<p id="a1" id="a2">x</p>',
        '<input name="x" disabled disabled aria-label="x">',
    ],
)
def test_duplicated_attributes_are_rejected(snippet: str) -> None:
    rejects(snippet, "ATTRIBUTE_DUPLICATED")


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "JaVaScRiPt:alert(1)",
        "jav&#x61;script:alert(1)",
        "&#106;avascript:alert(1)",
        "https://example.org",
        "//example.org",
        "data:text/html,x",
        "#SCR-009",
        "#scr-002",
        "#SCR-002 ",
        " #SCR-002",
        "#SCR-02",
        "#top",
        "SCR-002",
        "#SCR-002#x",
        "",
    ],
)
def test_links_only_name_a_screen_of_the_mockup(href: str) -> None:
    rejects(f'<a href="{href}">Vai</a>', "LINK_TARGET")


def test_links_to_screens_are_accepted_also_when_written_with_references() -> None:
    assert stored('<a href="&#x23;SCR-002">Vai</a>') == '<a href="#SCR-002">Vai</a>'
    assert stored('<a href="#SCR-001" aria-current="page">Qui</a>') == (
        '<a aria-current="page" href="#SCR-001">Qui</a>'
    )


@pytest.mark.parametrize(
    "value",
    ["Main", "1abc", "ot-screen", "a b", "a_b", "SCR-001", "x" * 65, "-a", "é"],
)
def test_identifiers_follow_the_pattern(value: str) -> None:
    rejects(f'<p id="{value}">x</p>', "ID_INVALID")


def test_identifiers_are_unique_in_the_whole_mockup() -> None:
    assert stored('<p id="a' + "b" * 63 + '">x</p>')
    rejects('<p id="dup">x</p><p id="dup">y</p>', "ID_DUPLICATED")
    with pytest.raises(GeneratedMockupError) as error:
        build(
            BASE_FIRST.replace("</main>", '<p id="dup">x</p></main>'),
            BASE_SECOND.replace("</main>", '<p id="dup">y</p></main>'),
        )
    assert error.value.code == "ID_DUPLICATED"
    assert "SCR-002" in error.value.detail


@pytest.mark.parametrize(
    "snippet",
    [
        '<label for="missing">Nome</label>',
        '<p aria-labelledby="missing">x</p>',
        '<p id="a1">x</p><p aria-labelledby="a1 missing">y</p>',
        '<p aria-describedby="missing">x</p>',
        '<p aria-controls="missing">x</p>',
        '<table><tbody><tr><td headers="missing">1</td></tr></tbody></table>',
        '<p aria-labelledby="">x</p>',
        '<label for="Bad Id">x</label>',
    ],
)
def test_references_name_identifiers_of_the_same_screen(snippet: str) -> None:
    rejects(snippet, "ID_REFERENCE")


def test_references_to_another_screen_are_rejected() -> None:
    with pytest.raises(GeneratedMockupError) as error:
        build(
            BASE_FIRST.replace("</main>", '<p aria-describedby="other">x</p></main>'),
            BASE_SECOND.replace("</main>", '<p id="other">y</p></main>'),
        )
    assert error.value.code == "ID_REFERENCE"


def test_references_in_the_same_screen_are_accepted() -> None:
    assert stored('<p id="n1">Nome</p><p aria-labelledby="n1" aria-controls="n1">x</p>')


@pytest.mark.parametrize(
    "value", ["Card", "ot-card", "OT-card", "1col", "a/b", "a.b", "ot-", "x" * 65, "", "   "]
)
def test_class_tokens_follow_the_pattern(value: str) -> None:
    rejects(f'<p class="{value}">x</p>', "CLASS_INVALID")


def test_class_tokens_are_normalized_to_single_spaces() -> None:
    assert stored('<p class=" card  wide\tcompact ">x</p>') == (
        '<p class="card wide compact">x</p>'
    )
    assert stored('<p class="a_b-c">x</p>') == '<p class="a_b-c">x</p>'


@pytest.mark.parametrize(
    "value",
    [
        "req-001",
        "REQ-1",
        "REQ-0001",
        "R-001",
        "REQUIR-001",
        "REQ-001,REQ-002",
        "REQ-001  REQ-002",
        "REQ-001 ",
        " REQ-001",
        "REQ-001 REQ-001",
        "",
    ],
)
def test_requirement_codes_follow_the_pattern(value: str) -> None:
    rejects(f'<p data-req="{value}">x</p>', "DATA_REQ_INVALID")


def test_requirement_codes_that_the_review_does_not_know_are_still_safe() -> None:
    assert stored('<p data-req="US-010 AC-002 ZZZZZ-999">x</p>')


@pytest.mark.parametrize(
    "snippet",
    [
        '<p tabindex="1">x</p>',
        '<p tabindex="2">x</p>',
        '<p tabindex="-2">x</p>',
        '<p tabindex="00">x</p>',
        '<p tabindex=" 0">x</p>',
        '<input type="submit" name="x" aria-label="x">',
        '<input type="image" name="x" aria-label="x">',
        '<input type="file" name="x" aria-label="x">',
        '<input type="hidden" name="x">',
        '<input type="button" name="x" aria-label="x">',
        '<input type="reset" name="x" aria-label="x">',
        '<input type="color" name="x" aria-label="x">',
        '<input type="TEXT" name="x" aria-label="x">',
        '<button type="">x</button>',
        '<button type="menu">x</button>',
        '<button type="Submit">x</button>',
        "<button type>x</button>",
        '<svg xmlns="http://www.w3.org/2000/SVG"></svg>',
        '<svg xmlns="http://www.w3.org/1999/xhtml"></svg>',
        '<svg xmlns=""></svg>',
        "<svg xmlns></svg>",
        '<p title="">x</p>',
        '<p title="' + "t" * 201 + '">x</p>',
        "<p title>x</p>",
        '<p dir="up">x</p>',
        '<p lang="it IT">x</p>',
        '<p role="Button">x</p>',
        '<p role="button,link">x</p>',
        '<table><tbody><tr><td colspan="0">x</td></tr></tbody></table>',
        '<table><tbody><tr><td colspan="x">x</td></tr></tbody></table>',
        '<table><tbody><tr><th scope="all">x</th></tr></tbody></table>',
        '<textarea name="t" rows="-1" aria-label="t"></textarea>',
        '<input name="x" maxlength="1e3" aria-label="x">',
        '<meter value="abc" aria-label="m">x</meter>',
        '<ol start="1.5"><li>x</li><li>y</li></ol>',
        '<table><colgroup span="0"></colgroup></table>',
    ],
)
def test_enumerated_and_numeric_values_are_checked(snippet: str) -> None:
    rejects(snippet, "ATTRIBUTE_VALUE")


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ("<button>Invia</button>", '<button type="button">Invia</button>'),
        ('<button type="submit">Invia</button>', '<button type="button">Invia</button>'),
        (
            '<button type="reset" name="r">Azzera</button>',
            '<button name="r" type="button">Azzera</button>',
        ),
        ('<button type="button">Chiudi</button>', '<button type="button">Chiudi</button>'),
        (
            '<form aria-label="Modulo"><button disabled>Invia</button></form>',
            '<form aria-label="Modulo"><button disabled type="button">Invia</button></form>',
        ),
    ],
)
def test_buttons_are_always_stored_as_plain_buttons(snippet: str, expected: str) -> None:
    assert stored(snippet) == expected


def test_the_serializer_writes_every_button_as_a_plain_button() -> None:
    nodes = (
        MarkupElement("button", (("type", "submit"),), (MarkupText("Invia"),)),
        MarkupElement("button", (), (MarkupText("Apri"),)),
    )
    assert serialize_markup(nodes) == (
        '<button type="button">Invia</button><button type="button">Apri</button>'
    )


@pytest.mark.parametrize(
    "snippet",
    [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0"></path></svg>',
        '<svg XMLNS="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0"></path></svg>',
        '<svg viewBox="0 0 1 1" xmlns=http://www.w3.org/2000/svg><path d="M0 0"></path></svg>',
    ],
)
def test_the_svg_namespace_is_accepted_and_not_written_back(snippet: str) -> None:
    assert stored(snippet) == '<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>'


def test_a_nested_svg_may_declare_the_namespace_too() -> None:
    assert (
        stored('<svg><svg xmlns="http://www.w3.org/2000/svg"><circle r="1"></circle></svg></svg>')
        == '<svg><svg><circle r="1"></circle></svg></svg>'
    )
    assert (
        serialize_markup((MarkupElement("svg", (("xmlns", "http://www.w3.org/2000/svg"),), ()),))
        == "<svg></svg>"
    )


@pytest.mark.parametrize(
    ("snippet", "expected"),
    [
        ('<p title="Nota">x</p>', '<p title="Nota">x</p>'),
        (
            '<abbr title="International Standard Book Number">ISBN</abbr>',
            '<abbr title="International Standard Book Number">ISBN</abbr>',
        ),
        (
            '<button title="Chiudi &amp; salva" aria-label="Chiudi">x</button>',
            '<button aria-label="Chiudi" title="Chiudi &amp; salva" type="button">x</button>',
        ),
        (
            '<svg title="Icona"><path title="Tratto" d="M0 0"></path></svg>',
            '<svg title="Icona"><path d="M0 0" title="Tratto"></path></svg>',
        ),
        ('<p title=" ">x</p>', '<p title=" ">x</p>'),
        ('<p title="' + "t" * 200 + '">x</p>', '<p title="' + "t" * 200 + '">x</p>'),
        ('<p title="a &quot;b&quot; <c>">x</p>', '<p title="a &quot;b&quot; &lt;c&gt;">x</p>'),
    ],
)
def test_the_title_attribute_is_plain_text_on_every_element(snippet: str, expected: str) -> None:
    assert stored(snippet) == expected


@pytest.mark.parametrize("character", ["\x01", "\x7f", "\x9f"])
def test_the_title_attribute_follows_the_character_rules(character: str) -> None:
    rejects(f'<p title="a{character}b">x</p>', "MARKUP_CONTROL_CHARACTER")
    rejects('<p title="a &#1; b">x</p>', "MARKUP_CHARACTER_REFERENCE")


@pytest.mark.parametrize(
    "input_type",
    [
        "text",
        "search",
        "email",
        "tel",
        "url",
        "number",
        "date",
        "time",
        "datetime-local",
        "month",
        "week",
        "password",
        "checkbox",
        "radio",
        "range",
    ],
)
def test_every_allowed_input_type_is_accepted(input_type: str) -> None:
    assert stored(f'<input type="{input_type}" name="x" aria-label="x">')


@pytest.mark.parametrize(
    "snippet",
    [
        '<svg><path d="M0 0" fill="red"></path></svg>',
        '<svg><path d="M0 0" fill="#fff"></path></svg>',
        '<svg><path d="M0 0" fill="url(#g)"></path></svg>',
        '<svg><path d="M0 0" fill="var(--vl-color-unknown)"></path></svg>',
        '<svg><path d="M0 0" fill="var(--vl-color-primary"></path></svg>',
        '<svg><path d="M0 0" fill="var(--m-accent)"></path></svg>',
        '<svg><path d="M0 0" stroke="rgb(0,0,0)"></path></svg>',
        '<svg><path d="M0 0 L x"></path></svg>',
        '<svg><path d="M1e3 0"></path></svg>',
        '<svg><path d="' + "M0 0" * 1001 + '"></path></svg>',
        '<svg><path d=""></path></svg>',
        '<svg><g transform="translate(1 2) evil(1)"></g></svg>',
        '<svg><g transform="expression(1)"></g></svg>',
        '<svg width="100%"></svg>',
        '<svg width="10px"></svg>',
        '<svg viewBox="0 0 a b"></svg>',
        '<svg><path d="M0 0" stroke-linecap="butt2"></path></svg>',
        '<svg focusable="yes"></svg>',
        '<svg><polyline points="0,0 x"></polyline></svg>',
        '<svg><path d="M0 0" opacity="half"></path></svg>',
    ],
)
def test_svg_attribute_values_are_restricted(snippet: str) -> None:
    rejects(snippet, "ATTRIBUTE_VALUE")


def test_svg_colours_accept_none_current_colour_and_known_colour_tokens() -> None:
    markup = stored(
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M0 0" fill="none" '
        'stroke="currentColor"></path><path d="M1 1" fill="var(--vl-color-accent)" '
        'stroke="currentcolor"></path></svg>'
    )
    assert 'viewBox="0 0 24 24"' in markup
    assert 'fill="var(--vl-color-accent)"' in markup


@pytest.mark.parametrize(
    "text",
    ["\x01", "\x07", "\x0b", "\x0c", "\x1b", "\x7f", "\x80", "\x9f", "\x00", "\ud800"],
)
def test_control_characters_are_rejected_in_text_and_attributes(text: str) -> None:
    rejects(f"<p>a{text}b</p>", "MARKUP_CONTROL_CHARACTER")
    rejects(f'<p aria-label="a{text}b">x</p>', "MARKUP_CONTROL_CHARACTER")


def test_tab_and_line_breaks_are_accepted_in_text_and_attributes() -> None:
    assert stored('<p aria-label="a\tb\nc">x\ty\nz</p>') == ('<p aria-label="a\tb\nc">x\ty\nz</p>')


@pytest.mark.parametrize(
    "reference",
    [
        "&notit;",
        "&foo;",
        "&copy",
        "&amp",
        "&#65",
        "&#0;",
        "&#x110000;",
        "&#xD800;",
        "&#128;",
        "&#x9F;",
        "&#13;",
        "&#x1;",
        "&#xFFFE;",
        "&#99999999;",
        "&#x;",
        "&#;",
    ],
)
def test_ambiguous_or_unsafe_character_references_are_rejected(reference: str) -> None:
    rejects(f"<p>a {reference} b</p>", "MARKUP_CHARACTER_REFERENCE")
    rejects(f'<p aria-label="a {reference} b">x</p>', "MARKUP_CHARACTER_REFERENCE")


def test_complete_character_references_and_plain_ampersands_are_accepted() -> None:
    assert stored("<p>&amp; &lt; &gt; &quot; &egrave; &#8364; &#x20AC; &#9;</p>") == (
        '<p>&amp; &lt; &gt; " è € € \t</p>'
    )
    assert stored("<p>R & D, a &, b &</p>") == "<p>R &amp; D, a &amp;, b &amp;</p>"


@pytest.mark.parametrize(
    "markup",
    [
        BASE_FIRST + "<div>",
        BASE_FIRST + "<p>testo",
        BASE_FIRST + '<textarea name="t" aria-label="t">abc',
        BASE_FIRST + "<svg><g>",
    ],
)
def test_unclosed_elements_are_rejected(markup: str) -> None:
    rejects_markup(markup, "UNCLOSED_ELEMENT")


@pytest.mark.parametrize(
    "snippet",
    [
        "<b><i>x</b></i>",
        "<div><span>x</div></span>",
        "<ul><li>a</ul>",
        "<p>a</div>",
    ],
)
def test_misnested_elements_are_rejected(snippet: str) -> None:
    rejects(snippet, "MISNESTED_ELEMENT")


@pytest.mark.parametrize(
    "markup",
    [
        BASE_FIRST + "</div>",
        BASE_FIRST + "</main>",
        BASE_FIRST.replace("</main>", "</br></main>"),
        BASE_FIRST.replace("</main>", '<input name="x" aria-label="x"></input></main>'),
        BASE_FIRST.replace("</main>", "<hr></hr></main>"),
    ],
)
def test_unexpected_end_tags_are_rejected(markup: str) -> None:
    rejects_markup(markup, "UNEXPECTED_END_TAG")


@pytest.mark.parametrize("snippet", ["<div/>", '<span class="x"/>', "<p/>", "<textarea/>"])
def test_self_closing_syntax_on_elements_that_are_not_void_is_rejected(snippet: str) -> None:
    rejects(snippet, "SELF_CLOSING")


def test_self_closing_syntax_is_accepted_on_void_and_svg_elements() -> None:
    assert stored('<p>a<br/>b<input name="x" aria-label="x"/></p>') == (
        '<p>a<br>b<input aria-label="x" name="x"></p>'
    )
    assert stored('<svg><path d="M0 0"/></svg>') == '<svg><path d="M0 0"></path></svg>'


@pytest.mark.parametrize(
    "snippet",
    [
        "<p><div>x</div></p>",
        "<p><ul><li>x</li></ul></p>",
        "<p><table><tbody><tr><td>x</td></tr></tbody></table></p>",
        "<p>a<hr></p>",
        "<p><h2>x</h2></p>",
        "<h1><p>x</p></h1>",
        "<h2><span><div>x</div></span></h2>",
        "<span><div>x</div></span>",
        "<p><span><section>x</section></span></p>",
        '<a href="#SCR-002"><div>x</div></a>',
        "<label><p>x</p></label>",
        '<button type="button"><section>x</section></button>',
        '<a href="#SCR-002"><a href="#SCR-001">x</a></a>',
        '<a href="#SCR-002"><button type="button">x</button></a>',
        '<button type="button"><button type="button">x</button></button>',
        '<button type="button"><input name="x" aria-label="x"></button>',
        '<a href="#SCR-002"><select name="s" aria-label="s"><option>a</option></select></a>',
        '<a href="#SCR-002"><label>x</label></a>',
        '<button type="button"><textarea name="t" aria-label="t"></textarea></button>',
        '<a href="#SCR-002"><span><input name="x" aria-label="x"></span></a>',
        '<form aria-label="a"><div><form aria-label="b"></form></div></form>',
        "<li>x</li>",
        "<div><li>x</li></div>",
        "<dt>x</dt>",
        "<ul><dd>x</dd></ul>",
        "<option>x</option>",
        "<div><option>x</option></div>",
        '<select name="s" aria-label="s"><optgroup label="a"><optgroup label="b">'
        "</optgroup></optgroup></select>",
        "<table><tr><td>x</td></tr></table>",
        "<table><tbody><td>x</td></tbody></table>",
        "<table><thead><th>x</th></thead></table>",
        "<div><tbody></tbody></div>",
        "<div><tr><td>x</td></tr></div>",
        "<div><caption>x</caption></div>",
        "<div><colgroup></colgroup></div>",
        "<table><col></table>",
        "<table><div>x</div></table>",
        "<table><tbody><tr><div>x</div></tr></tbody></table>",
        "<details><p>x</p><summary>y</summary></details>",
        "<details>testo<summary>y</summary></details>",
        "<summary>x</summary>",
        "<div><summary>x</summary></div>",
        "<fieldset><p>x</p><legend>y</legend></fieldset>",
        "<legend>x</legend>",
        '<path d="M0 0"></path>',
        "<g></g>",
        '<div><circle r="1"></circle></div>',
        "<svg><div>x</div></svg>",
        "<svg><span>x</span></svg>",
        "<svg><g><p>x</p></g></svg>",
        '<svg><path d="M0 0"><path d="M1 1"></path></path></svg>',
        "<table>testo</table>",
        "<table><tbody><tr>testo<td>x</td></tr></tbody></table>",
        "<table><tbody>testo</tbody></table>",
        "<table>\N{NO-BREAK SPACE}<tbody></tbody></table>",
        '<select name="s" aria-label="s">testo<option>a</option></select>',
        '<select name="s" aria-label="s"><option><b>a</b></option></select>',
        '<select name="s" aria-label="s"><div>a</div></select>',
        "<table><colgroup><p>x</p></colgroup></table>",
        "<svg>testo</svg>",
        '<textarea name="t" aria-label="t">\nabc</textarea>',
        '<textarea name="t" aria-label="t">&#10;abc</textarea>',
        '<textarea name="t" aria-label="t">\r\nabc</textarea>',
    ],
)
def test_content_rules_keep_a_single_reading_of_the_tree(snippet: str) -> None:
    rejects(snippet, "CONTENT_RULE")


@pytest.mark.parametrize(
    ("snippet", "phrase"),
    [
        ("<li>x</li>", "li must be a direct child of ul or ol"),
        ("<ul><div><li>x</li></div></ul>", "li must be a direct child of ul or ol"),
        ("<ol><span><li>x</li></span></ol>", "li must be a direct child of ul or ol"),
        ("<dt>x</dt>", "dt must be a direct child of dl"),
        ("<dl><div><dt>x</dt><dd>y</dd></div></dl>", "dt must be a direct child of dl"),
        ("<dd>x</dd>", "dd must be a direct child of dl"),
        ("<ul><li><dd>x</dd></li></ul>", "dd must be a direct child of dl"),
    ],
)
def test_list_items_and_terms_are_direct_children_of_their_lists(snippet: str, phrase: str) -> None:
    error = rejects(snippet, "CONTENT_RULE")
    assert phrase in error.detail
    assert error.detail.startswith("SCR-001")


def test_direct_list_children_are_accepted() -> None:
    assert stored("<ul><li>a</li><li>b</li></ul><ol><li>c</li></ol><dl><dt>d</dt><dd>e</dd></dl>")


def test_whitespace_is_accepted_where_browsers_keep_it_in_place() -> None:
    markup = stored(
        "<table>\n  <thead>\n    <tr>\n      <th>A</th>\n    </tr>\n  </thead>\n"
        "  <tbody>\t<tr> <td>1</td> </tr></tbody>\n</table>"
        "<details>\n  <summary>S</summary></details><fieldset> <legend>L</legend></fieldset>"
        '<select name="s" aria-label="s">\n  <option>a</option>\n</select>'
        '<svg viewBox="0 0 1 1">\n  <path d="M0 0"></path>\n</svg>'
        '<textarea name="t" aria-label="t">abc\n\ndef</textarea>'
    )
    assert "<tbody>\t<tr> <td>1</td> </tr></tbody>" in markup
    assert '<textarea aria-label="t" name="t">abc\n\ndef</textarea>' in markup


def test_depth_is_at_most_forty_levels() -> None:
    assert MAX_DEPTH == 40
    deep = "<div>" * 39 + "x" + "</div>" * 39
    assert stored(deep)
    rejects("<div>" * 40 + "x" + "</div>" * 40, "MARKUP_TOO_DEEP")


def test_a_screen_holds_at_most_one_thousand_five_hundred_elements() -> None:
    assert MAX_ELEMENTS == 1500
    assert build("<br>" * MAX_ELEMENTS).screens[0].markup == "<br>" * MAX_ELEMENTS
    rejects_markup("<br>" * (MAX_ELEMENTS + 1), "TOO_MANY_ELEMENTS")


@pytest.mark.parametrize(
    "snippet",
    [
        "<p>a < b</p>",
        "<p>x<3</p>",
        "<p>a</>b</p>",
        "<br / >",
        '<p class="a"id="b">x</p>',
        '<p class=a"b>x</p>',
        "<p class=a`b>x</p>",
        "<p>\N{KELVIN SIGN}bd</p><\N{KELVIN SIGN}bd>x</\N{KELVIN SIGN}bd>",
        '<textarea name="t" aria-label="t">a<b</textarea>',
    ],
)
def test_markup_with_more_than_one_reading_is_rejected(snippet: str) -> None:
    rejects(snippet, "MARKUP_SYNTAX")


@pytest.mark.parametrize(
    "markup",
    [
        BASE_FIRST + "<span",
        BASE_FIRST + '<p class="x',
        BASE_FIRST.replace("</main>", "</main class=x>"),
        BASE_FIRST.replace("</main>", "</main >"),
        BASE_FIRST.replace("</main>", "</ main>"),
        "text <",
    ],
)
def test_truncated_or_decorated_tags_are_rejected(markup: str) -> None:
    rejects_markup(markup, "MARKUP_SYNTAX")


def test_serializer_writes_the_canonical_form() -> None:
    nodes = (
        MarkupElement(
            "p",
            (("aria-label", 'a "b" <c> & d'), ("class", "x"), ("hidden", None)),
            (MarkupText("1 < 2 & 3 > 0 \"q\" 'a'"), MarkupElement("br", (), ())),
        ),
        MarkupElement(
            "svg",
            (("viewbox", "0 0 1 1"),),
            (MarkupElement("path", (("d", "M0 0"),), ()),),
        ),
    )
    markup = serialize_markup(nodes)
    assert markup == (
        '<p aria-label="a &quot;b&quot; &lt;c&gt; &amp; d" class="x" hidden>'
        "1 &lt; 2 &amp; 3 &gt; 0 \"q\" 'a'<br></p>"
        '<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>'
    )
    assert parse_markup(markup, screen_code="SCR-001", screen_codes=SCREEN_CODES) == nodes


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_markup_is_canonical_and_parses_back_to_the_same_tree(name: str) -> None:
    mockup = fixture_mockup(name)
    codes = frozenset(screen.code for screen in mockup.screens)
    for screen in mockup.screens:
        nodes = parse_markup(screen.markup, screen_code=screen.code, screen_codes=codes)
        assert serialize_markup(nodes) == screen.markup
        assert parse_markup(
            serialize_markup(nodes), screen_code=screen.code, screen_codes=codes
        ) == (nodes)


def test_generated_screen_and_mockup_are_frozen_value_objects() -> None:
    mockup = build()
    assert isinstance(mockup.screens[0], GeneratedScreen)
    assert isinstance(mockup, GeneratedMockup)
    with pytest.raises(AttributeError):
        mockup.title = "x"
    assert build() == mockup
    assert hash(build()) == hash(mockup)


TEXT_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyz ABCXYZ 0123456789 àèéìòùÀÉ &<>\"'=/#;:.,!?-_()[]{}"
    "\N{NO-BREAK SPACE}\t\n€✓\U0001f600"
)
WHITESPACE = " \t\n"
SHAPES = ("path", "circle", "ellipse", "line", "polyline", "polygon", "rect")
PHRASING = ("span", "b", "i", "em", "strong", "small", "mark", "code", "kbd", "abbr", "sub", "sup")
CONTAINERS = (
    "div",
    "section",
    "article",
    "aside",
    "header",
    "footer",
    "main",
    "nav",
    "figure",
    "blockquote",
    "form",
)


class TreeFactory:
    def __init__(self, seed: int) -> None:
        self.random = Random(seed)
        self.counter = 0
        self.forms = 0

    def text(self, *, first_line_break: bool = True) -> str:
        size = self.random.randint(1, 14)
        value = "".join(self.random.choice(TEXT_ALPHABET) for _ in range(size))
        if not first_line_break and value.startswith("\n"):
            value = "x" + value
        return value

    def whitespace(self) -> str:
        return "".join(self.random.choice(WHITESPACE) for _ in range(self.random.randint(1, 3)))

    def attributes(self, *extra: tuple[str, str | None]) -> tuple[tuple[str, str | None], ...]:
        chosen: dict[str, str | None] = dict(extra)
        options = [
            ("class", lambda: " ".join(f"c{self.random.randint(0, 9)}-x" for _ in range(2))),
            ("id", self.identifier),
            ("lang", lambda: self.random.choice(["it", "en-GB", "de"])),
            ("dir", lambda: self.random.choice(["ltr", "rtl", "auto"])),
            ("role", lambda: self.random.choice(["region", "note", "group", "status"])),
            ("hidden", lambda: None),
            ("tabindex", lambda: self.random.choice(["0", "-1"])),
            ("aria-label", lambda: self.text()),
            ("title", lambda: self.text()),
            ("aria-hidden", lambda: self.random.choice(["true", "false"])),
            ("data-req", lambda: self.random.choice(["REQ-001", "REQ-002 AC-010", "US-003"])),
        ]
        for name, value in options:
            if name not in chosen and self.random.random() < 0.18:
                chosen[name] = value()
        return tuple(sorted(chosen.items()))

    def identifier(self) -> str:
        self.counter += 1
        return f"n{self.counter}"

    def element(
        self,
        name: str,
        children: list[MarkupElement | MarkupText] | tuple = (),
        *extra: tuple[str, str | None],
    ) -> MarkupElement:
        return MarkupElement(name, self.attributes(*extra), merge(children))

    def phrasing(self, depth: int, *, interactive: bool = True) -> list:
        nodes: list = []
        for _ in range(self.random.randint(1, 3)):
            roll = self.random.random()
            if roll < 0.4 or depth <= 0:
                nodes.append(MarkupText(self.text()))
            elif roll < 0.6:
                name = self.random.choice(PHRASING)
                nodes.append(self.element(name, self.phrasing(depth - 1, interactive=interactive)))
            elif roll < 0.65:
                nodes.append(self.element("br"))
            elif roll < 0.7:
                nodes.append(
                    self.element("time", [MarkupText(self.text())], ("datetime", "2026-09-29"))
                )
            elif roll < 0.75:
                nodes.append(self.icon())
            elif roll < 0.8:
                nodes.append(
                    self.element(
                        self.random.choice(("meter", "progress")),
                        [MarkupText(self.text())],
                        ("max", "10"),
                        ("value", "3"),
                    )
                )
            elif roll < 0.83:
                nodes.append(self.element("output", [MarkupText(self.text())]))
            elif not interactive:
                nodes.append(MarkupText(self.text()))
            elif roll < 0.87:
                nodes.append(
                    self.element(
                        "a",
                        self.phrasing(depth - 1, interactive=False),
                        ("href", self.random.choice(["#SCR-001", "#SCR-002"])),
                    )
                )
            elif roll < 0.9:
                nodes.append(
                    self.element(
                        "button",
                        self.phrasing(depth - 1, interactive=False),
                        ("type", "button"),
                    )
                )
            elif roll < 0.93:
                nodes.append(
                    self.element(
                        "label",
                        [MarkupText(self.text()), self.control()],
                    )
                )
            else:
                nodes.append(self.control())
        return nodes

    def control(self) -> MarkupElement:
        roll = self.random.random()
        if roll < 0.4:
            kind = self.random.choice(["text", "email", "date", "checkbox", "radio", "range"])
            extra = [("name", "campo"), ("type", kind)]
            if self.random.random() < 0.5:
                extra.append(("required", None))
            return self.element("input", (), *extra)
        if roll < 0.7:
            options = [
                self.element("option", [MarkupText(self.text())], ("value", str(index)))
                for index in range(self.random.randint(1, 3))
            ]
            if self.random.random() < 0.3:
                grouped = self.element("option", [MarkupText(self.text())], ("value", "g"))
                options.append(self.element("optgroup", [grouped], ("label", "Gruppo")))
            return self.element("select", options, ("name", "scelta"))
        return self.element(
            "textarea",
            [MarkupText(self.text(first_line_break=False))],
            ("name", "note"),
            ("rows", "3"),
        )

    def icon(self) -> MarkupElement:
        shapes = []
        for _ in range(self.random.randint(0, 3)):
            shape = self.random.choice(SHAPES)
            shapes.append(
                self.element(
                    shape,
                    [MarkupText(self.whitespace())] if self.random.random() < 0.2 else [],
                    ("d", "M0 0L1 1z"),
                    ("fill", self.random.choice(["none", "currentColor"])),
                )
            )
        group = self.element("g", shapes, ("transform", "translate(1 1)"))
        return self.element("svg", [MarkupText(self.whitespace()), group], ("viewbox", "0 0 24 24"))

    def table(self, depth: int) -> MarkupElement:
        head = self.element(
            "thead",
            [self.element("tr", [self.element("th", self.phrasing(depth - 1)) for _ in range(2)])],
        )
        rows = [
            self.element(
                "tr",
                [
                    MarkupText(self.whitespace()),
                    self.element("td", self.flow(depth - 1)),
                    self.element("td", self.phrasing(depth - 1)),
                ],
            )
            for _ in range(self.random.randint(1, 3))
        ]
        body = self.element("tbody", rows)
        columns = self.element("colgroup", [self.element("col", (), ("span", "2"))])
        caption = self.element("caption", self.phrasing(depth - 1))
        return self.element("table", [caption, MarkupText(self.whitespace()), columns, head, body])

    def flow(self, depth: int) -> list:
        nodes: list = []
        for _ in range(self.random.randint(1, 3)):
            roll = self.random.random()
            if depth <= 0 or roll < 0.2:
                nodes.extend(self.phrasing(max(depth, 1)))
            elif roll < 0.35:
                nodes.append(self.element("p", self.phrasing(depth - 1)))
            elif roll < 0.42:
                level = self.random.choice(["h1", "h2", "h3", "h4"])
                nodes.append(self.element(level, self.phrasing(depth - 1)))
            elif roll < 0.55:
                name = self.random.choice(CONTAINERS)
                if name == "form" and self.forms:
                    name = "div"
                self.forms += name == "form"
                children = self.flow(depth - 1)
                self.forms -= name == "form"
                nodes.append(self.element(name, children))
            elif roll < 0.62:
                items = [self.element("li", self.flow(depth - 1)) for _ in range(2)]
                nodes.append(self.element(self.random.choice(["ul", "ol"]), items))
            elif roll < 0.67:
                nodes.append(
                    self.element(
                        "dl",
                        [
                            self.element("dt", self.phrasing(depth - 1)),
                            self.element("dd", self.flow(depth - 1)),
                        ],
                    )
                )
            elif roll < 0.74:
                nodes.append(self.table(depth))
            elif roll < 0.8:
                nodes.append(
                    self.element(
                        "details",
                        [
                            MarkupText(self.whitespace()),
                            self.element("summary", self.phrasing(depth - 1)),
                            *self.flow(depth - 1),
                        ],
                    )
                )
            elif roll < 0.86:
                nodes.append(
                    self.element(
                        "fieldset",
                        [
                            self.element("legend", self.phrasing(depth - 1)),
                            *self.flow(depth - 1),
                        ],
                    )
                )
            elif roll < 0.9:
                nodes.append(
                    self.element(
                        "figure",
                        [
                            *self.flow(depth - 1),
                            self.element("figcaption", self.phrasing(depth - 1)),
                        ],
                    )
                )
            elif roll < 0.95:
                nodes.append(self.element("hr"))
            else:
                nodes.append(self.icon())
        return nodes


def merge(nodes: list | tuple) -> tuple:
    merged: list = []
    for node in nodes:
        if isinstance(node, MarkupText) and merged and isinstance(merged[-1], MarkupText):
            merged[-1] = MarkupText(merged[-1].text + node.text)
        else:
            merged.append(node)
    return tuple(merged)


@pytest.mark.parametrize("seed", range(120))
def test_random_trees_from_the_allowed_vocabulary_survive_parse_and_serialize(
    seed: int,
) -> None:
    factory = TreeFactory(seed)
    nodes = merge(factory.flow(4))
    markup = serialize_markup(nodes)
    parsed = parse_markup(markup, screen_code="SCR-001", screen_codes=SCREEN_CODES)
    assert parsed == nodes
    assert serialize_markup(parsed) == markup
    mockup = build(markup)
    assert mockup.screens[0].markup == markup
    assert generated_mockup_from_snapshot(mockup.to_snapshot(), token_names=TOKEN_NAMES) == mockup
