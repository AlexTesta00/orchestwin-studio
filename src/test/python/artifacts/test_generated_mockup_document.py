from __future__ import annotations

import re
from dataclasses import replace
from html import escape
from html.parser import HTMLParser
from random import Random

import pytest

from orchestwin.artifacts.generated_mockup_document import (
    BASE_RULES,
    CONTENT_SECURITY_POLICY,
    SCREEN_ITEM_RULE,
    SHRINKING_ELEMENTS,
    MockupPin,
    mockup_document,
)
from orchestwin.artifacts.generated_mockup_structure import derive_elements
from orchestwin.artifacts.generated_mockups import (
    ALLOWED_ELEMENTS,
    GeneratedMockupError,
    create_generated_mockup,
)
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.artifacts.visual_catalog import FontFamily
from orchestwin.artifacts.visual_fonts import font_faces
from orchestwin.artifacts.visual_language import create_visual_language

from .test_generated_mockup_support import (
    ALTERNATIVE_ID,
    BASE_FIRST,
    BASE_SECOND,
    BASE_STYLES,
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN,
    DASHBOARD,
    FIXTURES,
    HTML_COMMENT_CLOSE,
    HTML_COMMENT_OPEN,
    LIGHT_CHOICES,
    LIGHT_TOKENS,
    TOKEN_NAMES,
    build,
    fixture_mockup,
    fixture_tokens,
    screen_payloads,
    with_first,
)
from .test_visual_directions import direction

POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "form-action 'none'; base-uri 'none'"
)
SECTION = re.compile(r'<section class="ot-screen" id="(SCR-\d{3})"[^>]*>')
DATA_FONT = re.compile(r"url\(data:font/woff2;base64,[A-Za-z0-9+/]+={0,2}\)")


class Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(name for name, _ in attrs)


def collect(document: str) -> Collector:
    collector = Collector()
    collector.feed(document)
    collector.close()
    return collector


def style_of(document: str) -> str:
    return document.split("<style>", 1)[1].split("</style>", 1)[0]


def sections(document: str) -> dict[str, str]:
    body = document.split('<body class="ot-mockup">', 1)[1].removesuffix("</body></html>")
    parts = SECTION.split(body)
    assert parts[0] == ""
    return {
        parts[index]: parts[index + 1].removesuffix("</section>")
        for index in range(1, len(parts), 2)
    }


def test_policy_constant_is_the_contract_policy() -> None:
    assert CONTENT_SECURITY_POLICY == POLICY


def test_document_has_the_required_parts_in_order() -> None:
    document = mockup_document(build(), tokens=LIGHT_TOKENS, language="it")
    assert document.startswith(
        '<!doctype html><html lang="it"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Registro dei prestiti</title><style>:root{"
    )
    assert document.count("<style>") == 1
    assert document.count("</style>") == 1
    assert '</style></head><body class="ot-mockup">' in document
    assert (
        '<section class="ot-screen" id="SCR-001" data-state="DEFAULT" '
        'aria-label="Prestiti della settimana" data-entry>'
    ) in document
    assert (
        '<section class="ot-screen" id="SCR-002" data-state="SUCCESS" '
        'aria-label="Promemoria inviato">'
    ) in document
    assert document.endswith("</section></body></html>")
    assert document.index('id="SCR-001"') < document.index('id="SCR-002"')


def test_style_holds_tokens_then_base_rules_then_mockup_styles() -> None:
    mockup = build()
    style = style_of(mockup_document(mockup, tokens=LIGHT_TOKENS, language="it"))
    root = ":root{" + ";".join(f"{name}:{value}" for name, value in sorted(LIGHT_TOKENS.items()))
    assert style.startswith(root + "}")
    assert style.endswith(mockup.styles)
    ordered = [
        "box-sizing:border-box",
        "body{margin:0;background:var(--vl-color-background);color:var(--vl-color-text);"
        "font-family:var(--vl-font-body);font-size:var(--vl-size-body);"
        "line-height:var(--vl-line-height)}",
        ".ot-screen{display:none}",
        ".ot-screen:target{display:block}",
        "body:not(:has(.ot-screen:target)) .ot-screen[data-entry]{display:block}",
        ":focus-visible{outline:",
        "@media (prefers-reduced-motion:reduce)",
        ".ot-pin{",
        SCREEN_ITEM_RULE,
        mockup.styles,
    ]
    positions = [style.index(part) for part in ordered]
    assert positions == sorted(positions)
    pin = style[style.index(".ot-pin{") :]
    pin = pin[: pin.index("}")]
    for part in (
        "width:22px",
        "height:22px",
        "border-radius:50%",
        "background:#6b4f8a",
        "color:#ffffff",
        "#ffffff",
        "z-index:",
    ):
        assert part in pin
    assert "animation:none" in style and "transition:none" in style


def test_the_boxes_of_a_screen_may_shrink_unless_the_mockup_says_otherwise() -> None:
    assert SCREEN_ITEM_RULE == (
        ":where(.ot-screen) :where(article,aside,details,div,dl,fieldset,figure,footer,form,"
        "header,li,main,nav,ol,section,ul){min-width:0}"
    )
    assert set(SHRINKING_ELEMENTS) <= ALLOWED_ELEMENTS
    assert set(SHRINKING_ELEMENTS).isdisjoint(
        {"a", "button", "input", "select", "textarea", "label", "p", "span", "dt", "dd", "svg"}
    )
    assert BASE_RULES.endswith(SCREEN_ITEM_RULE)
    mockup = build(styles=BASE_STYLES + "table{min-width:640px}")
    style = style_of(mockup_document(mockup, tokens=LIGHT_TOKENS, language="it"))
    assert style.count(SCREEN_ITEM_RULE) == 1
    assert style.index(SCREEN_ITEM_RULE) + len(SCREEN_ITEM_RULE) == style.index(mockup.styles)
    assert style.endswith("table{min-width:640px}")


@pytest.mark.parametrize(
    "tokens",
    [
        {"--vl-color-primary": "url(x)"},
        {"--vl-color-primary": "red;}p{color:blue"},
        {"--vl-color-primary": "#fff</style><script>"},
        {"--vl-color-primary": " #ffffff"},
        {"--vl-color-primary": "var(--vl-x)"},
        {"color": "#ffffff"},
        {"--vl-color-primary}": "#ffffff"},
        {"--vl-color-primary": 3},
    ],
)
def test_token_values_are_checked_again(tokens: dict[str, object]) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        mockup_document(build(), tokens=tokens, language="it")
    assert error.value.code == "DOCUMENT_TOKEN"


def test_token_values_with_plain_css_are_written_in_the_root_rule() -> None:
    document = mockup_document(
        build(),
        tokens={"--vl-color-primary": "#123456", "--vl-font-body": '"Segoe UI", sans-serif'},
        language="it",
    )
    assert ':root{--vl-color-primary:#123456;--vl-font-body:"Segoe UI", sans-serif}' in document


@pytest.mark.parametrize("name", FIXTURES)
def test_every_derived_element_carries_its_code(name: str) -> None:
    mockup = fixture_mockup(name)
    document = mockup_document(mockup, tokens=fixture_tokens(name), language="it")
    derived = derive_elements(mockup)
    assert document.count('data-elm="') == len(derived)
    for item in derived:
        assert document.count(f'data-elm="{item.code}"') == 1
    found = sections(document)
    assert list(found) == [screen.code for screen in mockup.screens]
    for screen in mockup.screens:
        assert re.sub(r' data-elm="ELM-\d+"', "", found[screen.code]) == screen.markup
    assert "<script" not in document.lower()
    assert mockup_document(mockup, tokens=fixture_tokens(name), language="it") == document


def test_baseline_elements_carry_codes_in_the_attribute_order() -> None:
    document = mockup_document(build(), tokens=LIGHT_TOKENS, language="it")
    assert '<h1 data-elm="ELM-001">Prestiti della settimana</h1>' in document
    assert '<select data-elm="ELM-003" id="stato" name="stato">' in document
    assert '<tr data-elm="ELM-004"><th scope="col">Lettore</th>' in document
    assert '<a data-elm="ELM-008" href="#SCR-002">Invia promemoria</a>' in document
    assert '<p data-elm="ELM-010" role="status">' in document


def test_pins_follow_their_element_or_sit_inside_rows_captions_and_summaries() -> None:
    mockup = with_first(
        "<details><summary>Dettagli</summary><p>Testo del dettaglio</p></details>"
        '<label for="c1">Codice</label><input id="c1" name="c">'
    )
    pins = [
        MockupPin("ELM-001", 1, "Titolo poco chiaro"),
        MockupPin("ELM-005", 2, "Riga senza stato"),
        MockupPin("ELM-009", 3, "Sommario"),
        MockupPin("ELM-011", 4, "Campo senza aiuto"),
        MockupPin("ELM-001", 5, "Secondo commento"),
    ]
    document = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it", pins=pins)
    assert (
        '<h1 data-elm="ELM-001">Prestiti della settimana</h1>'
        '<span class="ot-pin" aria-label="Titolo poco chiaro">1</span>'
        '<span class="ot-pin" aria-label="Secondo commento">5</span>'
    ) in document
    assert (
        '<tr data-elm="ELM-005"><td>Anna Riva<span class="ot-pin" '
        'aria-label="Riga senza stato">2</span></td>'
    ) in document
    assert (
        '<summary data-elm="ELM-009">Dettagli<span class="ot-pin" aria-label="Sommario">3</span>'
        "</summary>"
    ) in document
    assert (
        '<input data-elm="ELM-011" id="c1" name="c">'
        '<span class="ot-pin" aria-label="Campo senza aiuto">4</span>'
    ) in document


def test_documents_hold_plain_buttons_and_no_comments() -> None:
    mockup = with_first(
        HTML_COMMENT_OPEN
        + " azioni "
        + HTML_COMMENT_CLOSE
        + '<button type="submit" title="Salva la scheda">Salva</button>'
        + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1" aria-hidden="true">'
        + '<path d="M0 0"></path></svg>'
    )
    document = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it")
    assert (
        '<button data-elm="ELM-009" title="Salva la scheda" type="button">Salva</button>'
    ) in document
    assert HTML_COMMENT_OPEN not in document
    assert "xmlns" not in document
    assert 'type="submit"' not in document


def test_pins_inside_captions_of_the_fixture() -> None:
    mockup = fixture_mockup(DASHBOARD)
    document = mockup_document(
        mockup,
        tokens=fixture_tokens(DASHBOARD),
        language="it",
        pins=[MockupPin("ELM-020", 7, "Didascalia lunga")],
    )
    assert (
        'per primi<span class="ot-pin" aria-label="Didascalia lunga">7</span></caption>'
    ) in document


def test_pin_labels_and_numbers_are_escaped_and_unknown_codes_raise() -> None:
    document = mockup_document(
        build(),
        tokens=LIGHT_TOKENS,
        language="it",
        pins=[MockupPin("ELM-002", 12, '<script>alert("x")</script> & "q" onload=1')],
    )
    assert (
        'aria-label="&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &quot;q&quot; '
        'onload=1">12</span>'
    ) in document
    assert "<script" not in document
    for pins in ([MockupPin("ELM-099", 1, "x")], None, "ELM-001", [("ELM-001", 1, "x")]):
        with pytest.raises(GeneratedMockupError) as error:
            mockup_document(build(), tokens=LIGHT_TOKENS, language="it", pins=pins)
        assert error.value.code == "DOCUMENT_PIN"


@pytest.mark.parametrize(
    ("code", "number", "label"),
    [
        ("ELM-1", 1, "x"),
        ("SCR-001", 1, "x"),
        ("ELM-001", 0, "x"),
        ("ELM-001", -2, "x"),
        ("ELM-001", True, "x"),
        ("ELM-001", 1, ""),
        ("ELM-001", 1, "x" * 201),
        ("ELM-001", 1, "a\x00b"),
    ],
)
def test_pins_are_validated(code: str, number: int, label: str) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        MockupPin(code, number, label)
    assert error.value.code == "DOCUMENT_PIN"


def test_entry_screen_is_marked_for_the_default_view() -> None:
    mockup = build()
    default = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it")
    assert default.count(" data-entry>") == 1
    assert (
        'id="SCR-001" data-state="DEFAULT" aria-label="Prestiti della settimana" data-entry>'
        in (default)
    )
    second = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it", entry_screen="SCR-002")
    assert 'aria-label="Promemoria inviato" data-entry>' in second
    assert second.count(" data-entry>") == 1
    with pytest.raises(GeneratedMockupError) as error:
        mockup_document(mockup, tokens=LIGHT_TOKENS, language="it", entry_screen="SCR-009")
    assert error.value.code == "DOCUMENT_ENTRY_SCREEN"


@pytest.mark.parametrize(("language", "valid"), [("it", True), ("en-GB", True), ("de", True)])
def test_language_tags_are_written_in_the_html_element(language: str, valid: bool) -> None:
    assert f'<html lang="{language}">' in mockup_document(
        build(), tokens=LIGHT_TOKENS, language=language
    )


@pytest.mark.parametrize("language", ["", 'it"><script>', "it IT", "i", "x" * 40, 3])
def test_invalid_language_tags_raise(language: object) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        mockup_document(build(), tokens=LIGHT_TOKENS, language=language)
    assert error.value.code == "DOCUMENT_LANGUAGE"


def test_titles_and_text_are_escaped_and_the_style_end_never_appears_early() -> None:
    hostile = '</style><script>alert("x")</script>'
    payload = screen_payloads(
        (
            BASE_FIRST.replace("</main>", f"<p>{escape(hostile)}</p></main>"),
            BASE_SECOND,
        ),
        titles=(hostile, 'Fine "citata"'),
    )
    mockup = create_generated_mockup(
        design_alternative_id=ALTERNATIVE_ID,
        title=hostile,
        styles=BASE_STYLES,
        screens=payload,
        token_names=TOKEN_NAMES,
    )
    document = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it")
    assert "<script" not in document.lower()
    assert document.lower().count("</style") == 1
    assert '<title>&lt;/style&gt;&lt;script&gt;alert("x")&lt;/script&gt;</title>' in document
    assert (
        'aria-label="&lt;/style&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"'
    ) in document
    assert 'aria-label="Fine &quot;citata&quot;"' in document


HOSTILE_MARKUP = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<p onclick="alert(1)">a</p>',
    "</style>",
    "<style>p{}</style>",
    "<svg onload=alert(1)></svg>",
    '<a href="javascript:alert(1)">x</a>',
    '<a href="#SCR-002">vai</a>',
    "<p>testo</p>",
    "<b>forte</b>",
    HTML_COMMENT_OPEN + " x " + HTML_COMMENT_CLOSE,
    "<![CDATA[x]]>",
    "<",
    ">",
    "&",
    '"',
    "'",
    "<iframe src=x></iframe>",
    '<p aria-label="</style><script>">x</p>',
    '<p aria-label="&quot;><script>">x</p>',
    "<br/>",
    "onload=alert(1)",
    '<textarea name="t" aria-label="t">&lt;/style&gt;</textarea>',
    "</p>",
    "<p>",
    "<div>",
    "</div>",
    "<span>x</span>",
    '<svg viewBox="0 0 1 1"><path d="M0 0"></path></svg>',
    "<SCRIPT>x</SCRIPT>",
    "<scr<script>ipt>",
    "&lt;script&gt;",
    "<math><mi>x</mi></math>",
    "<p style=x>y</p>",
    '<input name="x" onfocus="x" aria-label="x">',
    "<table><tbody><tr><td>c</td></tr></tbody></table>",
]
HOSTILE_STYLES = [
    "</style>",
    "</STYLE>",
    "main{margin:0}",
    "p{color:var(--vl-color-text)}",
    "@import 'x';",
    "p{background:url(x)}",
    "\\",
    "p{content:'</style>'}",
    "<" + "!--",
    "}",
    "{",
    "p{background:var(--vl-color-surface)}",
    CSS_COMMENT_OPEN,
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN + " </style> " + CSS_COMMENT_CLOSE,
    "@media (max-width:600px){main{padding:0}}",
    "p::after{content:'<script>'}",
    "p{behavior:url(x)}",
    "*{margin:0}",
]
HOSTILE_TEXT = [
    "</style>",
    "<script>",
    '"><script>',
    "onload=",
    "&amp;",
    "Titolo",
    "\N{NO-BREAK SPACE}",
]


def assert_safe(document: str) -> None:
    lowered = document.lower()
    assert "<script" not in lowered
    style = style_of(document)
    assert "</style" not in style.lower()
    assert lowered.count("</style") == 1
    collector = collect(document)
    assert not [name for name in collector.attributes if name.startswith("on")]
    assert "script" not in collector.tags


def test_random_hostile_strings_never_produce_scripts_handlers_or_an_early_style_end() -> None:
    generator = Random(20260929)
    accepted = 0
    for _ in range(400):
        fragments = [generator.choice(HOSTILE_MARKUP) for _ in range(generator.randint(1, 6))]
        if generator.random() < 0.4:
            first = BASE_FIRST.replace(
                "</main>", "<p>" + escape("".join(fragments)) + "</p></main>"
            )
        else:
            first = BASE_FIRST.replace("</main>", "".join(fragments) + "</main>")
        styles = "".join(generator.choice(HOSTILE_STYLES) for _ in range(generator.randint(0, 3)))
        if generator.random() < 0.4:
            styles = BASE_STYLES
        title = "".join(generator.choice(HOSTILE_TEXT) for _ in range(generator.randint(1, 3)))
        try:
            mockup = create_generated_mockup(
                design_alternative_id=ALTERNATIVE_ID,
                title=title,
                styles=styles,
                screens=screen_payloads(
                    (first, BASE_SECOND),
                    states=(PrototypeScreenState.DEFAULT, PrototypeScreenState.SUCCESS),
                    titles=(title, "Fine"),
                ),
                token_names=TOKEN_NAMES,
            )
        except GeneratedMockupError:
            continue
        accepted += 1
        pins = [MockupPin("ELM-001", 1, mockup.title)]
        document = mockup_document(mockup, tokens=LIGHT_TOKENS, language="it", pins=pins)
        assert_safe(document)
    assert accepted >= 80


def directed_tokens() -> dict[str, str]:
    return create_visual_language(
        choices=replace(
            LIGHT_CHOICES,
            heading_family=FontFamily.GEOMETRIC_SANS,
            body_family=FontFamily.GROTESQUE_SANS,
        ),
        product_name="Registro dei prestiti",
        rationale="Una pagina stampata per il banco prestiti.",
        direction=direction(),
    ).token_values


def root_of(tokens: dict[str, str]) -> str:
    return ":root{" + ";".join(f"{name}:{value}" for name, value in sorted(tokens.items())) + "}"


@pytest.mark.parametrize("name", FIXTURES)
def test_a_design_without_bundled_fonts_keeps_the_document_of_today(name: str) -> None:
    for mockup, tokens in ((build(), LIGHT_TOKENS), (fixture_mockup(name), fixture_tokens(name))):
        document = mockup_document(mockup, tokens=tokens, language="it")
        assert font_faces(tokens) == ""
        assert style_of(document) == root_of(tokens) + BASE_RULES + mockup.styles
        assert "@font-face" not in document
        assert "url(" not in document


def test_the_bundled_fonts_open_the_style_before_the_tokens() -> None:
    tokens = directed_tokens()
    mockup = build(token_names=frozenset(tokens))
    document = mockup_document(mockup, tokens=tokens, language="it")
    faces = font_faces(tokens)

    assert style_of(document) == faces + root_of(tokens) + BASE_RULES + mockup.styles
    assert faces.count("@font-face{") == 8
    for family in ("Geist", "Geist Mono", "Libre Franklin"):
        assert f'@font-face{{font-family:"{family}";' in faces
    assert CONTENT_SECURITY_POLICY == POLICY
    assert f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">' in document
    assert_safe(document)
    assert mockup_document(mockup, tokens=tokens, language="it") == document


def test_the_document_with_bundled_fonts_makes_no_external_reference() -> None:
    tokens = directed_tokens()
    document = mockup_document(build(token_names=frozenset(tokens)), tokens=tokens, language="it")
    bare = DATA_FONT.sub("", document).lower()

    assert len(DATA_FONT.findall(document)) == document.count("url(") == 8
    assert document.count("url(data:font/woff2;base64,") == 8
    for reference in ("http:", "https:", "//", "url(", "@import", "<link", " src="):
        assert reference not in bare, reference


def test_tokens_that_name_a_bundled_family_are_checked_before_the_faces() -> None:
    for value in ('"Geist", url(x)', '"Geist"</style><script>', '"Geist";}p{color:red'):
        with pytest.raises(GeneratedMockupError) as error:
            mockup_document(
                build(), tokens={**LIGHT_TOKENS, "--vl-font-heading": value}, language="it"
            )
        assert error.value.code == "DOCUMENT_TOKEN"


@pytest.mark.parametrize(
    "styles",
    [
        '@font-face{font-family:"Geist";src:url(data:font/woff2;base64,d09GMg==)}',
        "@font-face{font-family:x}",
        "p{font-family:x;src:url(data:font/woff2;base64,d09GMg==)}",
        "p{background:url(data:image/png;base64,iVBORw0KGgo=)}",
        "p{background:url(//fonts.example/x.woff2)}",
        "@import url(fonts.css);",
    ],
)
def test_a_sheet_cannot_bring_its_own_fonts_into_a_design_with_bundled_fonts(styles: str) -> None:
    with pytest.raises(GeneratedMockupError) as error:
        build(styles=styles, token_names=frozenset(directed_tokens()))
    assert error.value.code == "STYLES_FORBIDDEN"
